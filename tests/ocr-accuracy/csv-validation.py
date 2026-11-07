import csv

with open('validation_results.csv', 'r') as f:
    reader = csv.DictReader(f)
    results = list(reader)

results = [r for r in results if r['Match']]

total = len(results)
correct = sum(1 for r in results if r['Match'].upper() == 'YES')
incorrect = sum(1 for r in results if r['Match'].upper() == 'NO')
partial = sum(1 for r in results if r['Match'].upper() == 'PARTIAL')

accuracy = (correct / total) * 100 if total > 0 else 0

print(f"OCR Accuracy Analysis (n={total})")
print(f"="*50)
print(f"Correct:   {correct:2d} ({correct/total*100:.1f}%)")
print(f"Incorrect: {incorrect:2d} ({incorrect/total*100:.1f}%)")
print(f"Partial:   {partial:2d} ({partial/total*100:.1f}%)")
print(f"\nOverall Accuracy: {accuracy:.1f}%")

high_conf = [r for r in results if float(r['Confidence_%']) >= 90]
med_conf = [r for r in results if 70 <= float(r['Confidence_%']) < 90]
low_conf = [r for r in results if float(r['Confidence_%']) < 70]

print(f"\nAccuracy by Confidence Level:")
print(f"High (≥90%): {sum(1 for r in high_conf if r['Match'].upper()=='YES')}/{len(high_conf)} = {sum(1 for r in high_conf if r['Match'].upper()=='YES')/len(high_conf)*100:.1f}%" if high_conf else "High (≥90%): N/A")
print(f"Med (70-89%): {sum(1 for r in med_conf if r['Match'].upper()=='YES')}/{len(med_conf)} = {sum(1 for r in med_conf if r['Match'].upper()=='YES')/len(med_conf)*100:.1f}%" if med_conf else "Med (70-89%): N/A")
print(f"Low (<70%): {sum(1 for r in low_conf if r['Match'].upper()=='YES')}/{len(low_conf)} = {sum(1 for r in low_conf if r['Match'].upper()=='YES')/len(low_conf)*100:.1f}%" if low_conf else "Low (<70%): N/A")

print(f"\nCommon OCR Errors:")
errors = [r for r in results if r['Match'].upper() == 'NO']
for e in errors[:5]:
    print(f"  OCR: {e['OCR_Result']:10s} → Actual: {e['Actual_Plate']:10s} (Confidence: {e['Confidence_%']}%)")
