# Current version. Replaces old/plate-validation-v1.py and old/plate-validation-v2.py.

import re


LICENSE_PLATE_FORMATS = [
    {
        'name': 'Standard X-XXXXX',
        'pattern': r'[A-Z0-9]-[A-Z0-9]{2}[0-9]{3}',
        'type': 'standard',
        'structure': 'L-AANNN',
        'enable_corrections': True,
        'validation': lambda prefix, suffix: (
            len(prefix) == 1
            and prefix.isalpha()
            and len(suffix) == 5
            and suffix[:2].isalnum()
            and suffix[2:].isdigit()
        )
    },

    {
        'name': 'Standard XXX-XXXX',
        'pattern': r'[A-Z0-9]{3}-[A-Z0-9]{4}',
        'type': 'standard',
        'structure': 'LLL-NNNN',
        'enable_corrections': True,
        'validation': lambda prefix, suffix: (
            len(prefix) == 3
            and prefix.isalpha()
            and len(suffix) == 4
            and suffix.isdigit()
        )
    },

    {
        'name': 'Standard XXX-XXX',
        'pattern': r'[A-Z0-9]{3}-[A-Z0-9]{3}',
        'type': 'standard',
        'structure': 'LLL-NNN',
        'enable_corrections': True,
        'validation': lambda prefix, suffix: (
            len(prefix) == 3
            and prefix.isalpha()
            and len(suffix) == 3
            and suffix.isdigit()
        )
    },

    {
        'name': 'Custom XXXX XXX',
        'pattern': r'[A-Z0-9]{2}[A-Z0-9]{2}\s?[A-Z0-9]{3}',
        'type': 'custom',
        'structure': 'LLNNLLL',
        'enable_corrections': True,
        'validation': lambda text: (
            len(text) == 7
            and text[0:2].isalpha()
            and text[2:4].isdigit()
            and text[4:7].isalpha()
        )
    },

]


OCR_CORRECTIONS = {
    '0': ['O'],
    '1': ['I'],
    '5': ['S'],
    '6': ['G'],
    '8': ['B'],

    'O': ['0'],
    'D': ['0'],
    'I': ['1'],
    'S': ['5'],
    'G': ['6'],
    'Б': ['6'],
    'B': ['8'],
}

def clean_text(raw):
    """
    Uppercase, remove invalid characters but preserve dashes and spaces.
    Collapse multiple spaces/dashes into one.
    """
    cyrillic_map = {
        '\u0410': 'A',
        '\u0412': 'B',
        '\u0415': 'E',
        '\u041A': 'K',
        '\u041C': 'M',
        '\u041D': 'H',
        '\u041E': 'O',
        '\u0420': 'P',
        '\u0421': 'C',
        '\u0422': 'T',
        '\u0423': 'Y',
        '\u0425': 'X',
        '\u0411': '6'
    }
    raw = ''.join(cyrillic_map.get(c, c) for c in raw)

    cleaned = re.sub(r'[^A-Za-z0-9\- ]', '', raw)
    cleaned = re.sub(r'[\s\-]+', lambda m: m.group(0)[0], cleaned)

    words = cleaned.split()

    if len(words) >= 2:
        word1, word2 = words[0], words[1]
        if len(word2) > len(word1) and word2.startswith(word1):
            words = [word1] + words[2:]
            cleaned = ' '.join(words)

    return cleaned

def apply_corrections_by_structure(text, structure, enable_corrections):
    """
    Apply OCR corrections only when:
    1. enable_corrections=True for this format
    2. Structure defines L (must be letter) or N (must be number)
    3. Character violates the structure requirement
    
    For 'A' positions: NO corrections applied (both valid)
    """
    if not enable_corrections or not structure:
        return [text]

    structure_chars = structure.replace('-', '').replace(' ', '')
    text_chars = list(text.replace('-', '').replace(' ', ''))

    if len(structure_chars) != len(text_chars):
        return [text]

    candidates = [text_chars[:]]

    for pos, (char, expected_type) in enumerate(zip(text_chars, structure_chars)):
        new_candidates = []

        for candidate in candidates:
            if expected_type == 'A':
                new_candidates.append(candidate)

            elif expected_type == 'L':
                if candidate[pos].isalpha():
                    new_candidates.append(candidate)
                elif candidate[pos].isdigit() and candidate[pos] in OCR_CORRECTIONS:
                    for correction in OCR_CORRECTIONS[candidate[pos]]:
                        new_candidate = candidate[:]
                        new_candidate[pos] = correction
                        new_candidates.append(new_candidate)
                else:
                    new_candidates.append(candidate)

            elif expected_type == 'N':
                if candidate[pos].isdigit():
                    new_candidates.append(candidate)
                elif candidate[pos].isalpha() and candidate[pos] in OCR_CORRECTIONS:
                    for correction in OCR_CORRECTIONS[candidate[pos]]:
                        new_candidate = candidate[:]
                        new_candidate[pos] = correction
                        new_candidates.append(new_candidate)
                else:
                    new_candidates.append(candidate)

        candidates = new_candidates

        if len(candidates) > 10:
            candidates = candidates[:10]

    results = []
    dash_positions = [i for i, c in enumerate(structure) if c == '-']
    space_positions = [i for i, c in enumerate(structure) if c == ' ']

    for candidate in candidates:
        result_chars = candidate[:]
        offset = 0
        for pos in sorted(dash_positions + space_positions):
            if pos in dash_positions:
                result_chars.insert(pos + offset, '-')
            else:
                result_chars.insert(pos + offset, ' ')
            offset += 1

        result_text = ''.join(result_chars)
        if result_text not in results:
            results.append(result_text)

    return results


def extract_candidates(cleaned):
    """
    Extract candidate license plates using configured formats.
    Returns list of (candidate, format_config) tuples.
    """
    candidates = []

    for format_config in LICENSE_PLATE_FORMATS:
        pattern = format_config['pattern']
        plate_type = format_config['type']

        matches = re.findall(pattern, cleaned)
        if matches:
            for match in matches:
                if plate_type == 'custom':
                    no_space = match.replace(' ', '')
                    if len(no_space) == 7 and '-' not in no_space:
                        candidates.append((match, format_config))
                else:
                    candidates.append((match, format_config))

    return candidates


def generate_corrections(candidate, format_config):
    """
    Generate corrected variations if format allows corrections.
    """
    enable_corrections = format_config.get('enable_corrections', False)
    structure = format_config.get('structure', None)

    variations = apply_corrections_by_structure(candidate, structure, enable_corrections)
    return variations


def format_license(text: str) -> str:
    """
    Format license plate:
    - Uppercase
    - Preserve dash for standard plates
    - Remove ALL spaces for custom plates
    """
    text = text.upper().strip()

    if '-' in text:
        parts = text.split('-')
        text = '-'.join(p.strip().replace(' ', '') for p in parts)
    else:
        text = text.replace(' ', '')

    return text


def license_complies_format(text: str) -> tuple:
    """
    Validate license plate against all configured formats.
    Returns (is_valid, format_name) tuple.
    """
    if '-' in text:
        parts = text.split('-')
        if len(parts) != 2:
            return False, None

        prefix, suffix = parts[0], parts[1]

        for format_config in LICENSE_PLATE_FORMATS:
            if format_config['type'] == 'standard':
                try:
                    if format_config['validation'](prefix, suffix):
                        return True, format_config['name']
                except:
                    continue

        return False, None
    else:
        for format_config in LICENSE_PLATE_FORMATS:
            if format_config['type'] == 'custom':
                try:
                    if format_config['validation'](text):
                        return True, format_config['name']
                except:
                    continue

        return False, None


def process_plate(raw_text):
    """
    Full OCR processing pipeline optimized for your province:
    
    Formats WITH corrections (safe, no false positives):
    - X-XXXXX   (letter-numbers)
    - XXX-XXXX  (letters-numbers)
    
    Formats WITHOUT corrections (prevents false positives):
    - XXXXXXX   (custom alphanumeric)
    """

    cleaned = clean_text(raw_text)

    if not cleaned:
        print(f"[DEBUG] Cleaned text is empty")
        return None

    candidates = extract_candidates(cleaned)
    if not candidates:
        print(f"[DEBUG] No candidates found matching any format")
        return None

    print("[DEBUG] #######################################")
    print(f"[DEBUG] Found {len(candidates)} candidate(s):")
    for i, (cand, fmt) in enumerate(candidates):
        corrections_status = "enabled" if fmt.get('enable_corrections', False) else "disabled"
        print(f"[DEBUG]   {i+1}. '{cand}' (format: {fmt['name']}, corrections: {corrections_status})")

    all_variations = []
    for candidate, format_config in candidates:
        variations = generate_corrections(candidate, format_config)

        if len(variations) > 1:
            print(f"[DEBUG]   Generated {len(variations)} variation(s) for '{candidate}':")
            for var in variations:
                if var != candidate:
                    print(f"[DEBUG]   - '{var}' (corrected)")

        for var in variations:
            is_corrected = (var != candidate)
            all_variations.append((var, format_config, is_corrected))

    valid_plates = []
    for variation, format_config, is_corrected in all_variations:
        formatted = format_license(variation)
        is_valid, format_name = license_complies_format(formatted)

        if is_valid:
            score = 100
            if is_corrected:
                score -= 10
            if format_config['type'] == 'standard':
                score += 5

            valid_plates.append((formatted, format_name, score, is_corrected))

            correction_note = " (corrected)" if is_corrected else " (original)"
            print(f"[DEBUG]     Valid: '{formatted}' (score: {score}){correction_note}")
        else:
            print(f"[DEBUG]     Invalid: '{formatted}'")

    if not valid_plates:
        print(f"[DEBUG] No valid plates after validation")
        return None

    print("[DEBUG] #######################################")

    valid_plates.sort(key=lambda x: (not x[3], x[2]), reverse=True)
    best_plate, best_format, best_score, was_corrected = valid_plates[0]

    print(f"[DEBUG] ═══════════════════════════════════════")
    print(f"[DEBUG]   Raw OCR input: '{raw_text}'")
    print(f"[DEBUG]   After cleaning: '{cleaned}'")
    print(f"[DEBUG]   SELECTED: '{best_plate}'")
    print(f"[DEBUG]   Format: {best_format}")
    print(f"[DEBUG]   Score: {best_score}")
    print(f"[DEBUG]   Corrected: {'Yes' if was_corrected else 'No'}")
    print(f"[DEBUG]   False positive risk: {'NONE' if not was_corrected else 'LOW (validated)'}")
    if len(valid_plates) > 1:
        print(f"[DEBUG]   (Rejected {len(valid_plates)-1} other variation(s))")
    print(f"[DEBUG] ═══════════════════════════════════════")

    return best_plate
