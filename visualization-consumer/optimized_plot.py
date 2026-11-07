# Current version. Replaces old/plot-v1.py and old/plot-v2.py.

import os
import pandas as pd
import cv2
import numpy as np
import time


def add_transparent_image(background, foreground, x_offset=None, y_offset=None):
    bg_h, bg_w, bg_channels = background.shape
    fg_h, fg_w, fg_channels = foreground.shape

    assert bg_channels == 3, f'background image should have exactly 3 channels (RGB). found:{bg_channels}'
    assert fg_channels == 4, f'foreground image should have exactly 4 channels (RGBA). found:{fg_channels}'

    if x_offset is None:
        x_offset = (bg_w - fg_w) // 2
    if y_offset is None:
        y_offset = (bg_h - fg_h) // 2

    w = min(fg_w, bg_w, fg_w + x_offset, bg_w - x_offset)
    h = min(fg_h, bg_h, fg_h + y_offset, bg_h - y_offset)

    if w < 1 or h < 1:
        return

    bg_x = max(0, x_offset)
    bg_y = max(0, y_offset)
    fg_x = max(0, x_offset * -1)
    fg_y = max(0, y_offset * -1)
    foreground = foreground[fg_y:fg_y + h, fg_x:fg_x + w]
    background_subsection = background[bg_y:bg_y + h, bg_x:bg_x + w]

    foreground_colors = foreground[:, :, :3]
    alpha_channel = foreground[:, :, 3] / 255

    alpha_mask = np.dstack((alpha_channel, alpha_channel, alpha_channel))

    composite = background_subsection * (1 - alpha_mask) + foreground_colors * alpha_mask

    background[bg_y:bg_y + h, bg_x:bg_x + w] = composite


frames_dir = './amazon-kinesis-video-streams-consumer-library-for-python/frames'
detections_dir = './amazon-kinesis-video-streams-consumer-library-for-python/detections'
processed_fragments_dir = './amazon-kinesis-video-streams-consumer-library-for-python/processed_fragments'
license_plates_dir = './amazon-kinesis-video-streams-consumer-library-for-python/license_plates'

visualized_fragments = set()
track_ids_ = []

current_license_text = None
current_license_track_id = None
license_plate_display_frames = 0
LICENSE_PLATE_DISPLAY_DURATION = 45

loading_frames = []
loading_frames_dir = './loading_frames'
if os.path.exists(loading_frames_dir):
    for file in sorted(os.listdir(loading_frames_dir)):
        img = cv2.imread(os.path.join(loading_frames_dir, file), cv2.IMREAD_UNCHANGED)
        if img is not None:
            loading_frames.append(img)

TARGET_FPS = 12
FRAME_DELAY = int(1000 / TARGET_FPS)
PROCESSING_DELAY = 0.05
MIN_FRAGMENTS_TO_START = 2

def get_all_license_plates():
    """Get all available license plates"""
    if not os.path.exists(license_plates_dir):
        return {}

    license_plates = {}
    files = os.listdir(license_plates_dir)

    for file in files:
        parts = file.split('_')
        if len(parts) >= 2:
            try:
                track_id = int(parts[0])
                text = parts[1].split('.')[0] if '.' in parts[1] else parts[1]
                license_plates[track_id] = text
            except ValueError:
                continue

    return license_plates


def update_license_plate_display(detections_in_frame):
    """Update which license plate to display based on current detections"""
    global current_license_text, current_license_track_id, license_plate_display_frames

    license_plates = get_all_license_plates()

    if not license_plates:
        if current_license_text is not None:
            current_license_text = None
            current_license_track_id = None
            license_plate_display_frames = 0
        return

    current_track_ids = list(detections_in_frame['track_id'].values)

    available_plates_in_frame = []
    for track_id in current_track_ids:
        if track_id in license_plates:
            available_plates_in_frame.append((track_id, license_plates[track_id]))

    if available_plates_in_frame:
        best_track_id = None
        best_position = -1

        for track_id, text in available_plates_in_frame:
            if track_id in track_ids_:
                position = len(track_ids_) - 1 - track_ids_[::-1].index(track_id)
                if position > best_position:
                    best_position = position
                    best_track_id = track_id

        if best_track_id is None and available_plates_in_frame:
            best_track_id = available_plates_in_frame[0][0]

        if best_track_id is not None:
            new_plate_text = license_plates[best_track_id]

            if best_track_id != current_license_track_id:
                current_license_track_id = best_track_id
                current_license_text = new_plate_text
                license_plate_display_frames = LICENSE_PLATE_DISPLAY_DURATION
                print(f" Switching to license plate: {current_license_text} (track_id: {current_license_track_id})")
            else:
                license_plate_display_frames = LICENSE_PLATE_DISPLAY_DURATION
    else:
        if license_plate_display_frames > 0:
            license_plate_display_frames -= 5
            if license_plate_display_frames <= 0:
                print(f" License plate cleared: {current_license_text}")
                current_license_text = None
                current_license_track_id = None
                license_plate_display_frames = 0


def show_loading_animation(frame_template, loading_frames):
    """Show one cycle of loading animation"""
    if not loading_frames:
        frame = frame_template.copy()
        cv2.imshow('frame', frame)
        cv2.waitKey(100)
        return True

    for img in loading_frames:
        frame = frame_template.copy()
        add_transparent_image(frame, img)
        cv2.imshow('frame', frame)
        if cv2.waitKey(50) & 0xFF == ord('q'):
            return False
    return True


def draw_detections_and_license_plate(frame, detections, show_license_plate=True):
    """Draw bounding boxes with license plates shown directly on the boxes"""
    global track_ids_

    license_plates = get_all_license_plates()

    for k in range(len(detections)):
        det = detections.iloc[k]
        x1, y1, x2, y2 = int(det['x1']), int(det['y1']), int(det['x2']), int(det['y2'])

        track_id = det['track_id']

        has_license_plate = track_id in license_plates

        if has_license_plate:
            box_color = (0, 255, 0)
            box_thickness = 10
            label = f"ID:{track_id} - {license_plates[track_id]}"
        else:
            box_color = (0, 0, 255)
            box_thickness = 8
            label = f"ID:{track_id} - Processing..."

        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, box_thickness)

        if track_id not in track_ids_:
            track_ids_.append(track_id)

        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.0
        font_thickness = 3

        label_size, _ = cv2.getTextSize(label, font, font_scale, font_thickness)
        label_width = label_size[0] + 20
        label_height = label_size[1] + 20

        label_x = x1
        label_y = max(y1 - label_height, label_height)

        overlay = frame.copy()
        cv2.rectangle(overlay,
                     (label_x, label_y - label_height),
                     (label_x + label_width, label_y),
                     box_color,
                     -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

        text_x = label_x + 10
        text_y = label_y - 10
        cv2.putText(frame, label, (text_x, text_y), font, font_scale, (0, 0, 0), font_thickness + 1)
        cv2.putText(frame, label, (text_x, text_y), font, font_scale, (255, 255, 255), font_thickness - 1)


def main():
    global visualized_fragments

    frame_template = np.ones((960, 1440, 3), dtype=np.uint8) * 128

    print("="*60)
    print("VIDEO PROCESSOR STARTED")
    print("="*60)
    print(f"Target FPS: {TARGET_FPS}")
    print(f"Frame delay: {FRAME_DELAY}ms")
    print(f"Buffering: Waiting for {MIN_FRAGMENTS_TO_START} fragments before playback")
    print("License plates shown directly on detection boxes")
    print("Green box = License plate available")
    print("Red box = Processing license plate...")
    print("Press 'q' to quit, 'p' to pause")
    print("="*60)

    print("Showing loading animation...")
    for _ in range(2):
        if not show_loading_animation(frame_template, loading_frames):
            return

    frame_count = 0
    no_data_cycles = 0
    playback_started = False

    while True:
        if not os.path.exists(frames_dir) or not os.path.exists(processed_fragments_dir):
            no_data_cycles += 1
            if no_data_cycles % 10 == 0:
                print(f"Waiting for data directories... ({no_data_cycles} cycles)")
            if not show_loading_animation(frame_template, loading_frames):
                return
            continue

        frames_list = os.listdir(frames_dir)
        if not frames_list:
            no_data_cycles += 1
            if no_data_cycles % 10 == 0:
                print(f"Waiting for frames... ({no_data_cycles} cycles)")
            if not show_loading_animation(frame_template, loading_frames):
                return
            continue

        no_data_cycles = 0

        fragments = sorted(set([f.split('-')[0] for f in frames_list]))
        fragments_object_detection = set(os.listdir(processed_fragments_dir))

        ready_fragments = []
        for fragment in fragments:
            if fragment not in visualized_fragments and fragment in fragments_object_detection:
                detection_file = os.path.join(detections_dir, f'{fragment}.csv')
                if os.path.exists(detection_file):
                    ready_fragments.append(fragment)

        if not playback_started and len(ready_fragments) < MIN_FRAGMENTS_TO_START:
            print(f"Buffering... ({len(ready_fragments)}/{MIN_FRAGMENTS_TO_START} fragments ready)")
            if not show_loading_animation(frame_template, loading_frames):
                return
            continue

        if not playback_started:
            print(f"Buffer ready! Starting playback with {len(ready_fragments)} fragments")
            playback_started = True

        frames_played_this_cycle = 0

        for fragment in ready_fragments:
            if fragment in visualized_fragments:
                continue

            visualized_fragments.add(fragment)

            detection_file = os.path.join(detections_dir, f'{fragment}.csv')

            try:
                data = pd.read_csv(detection_file)
            except Exception as e:
                print(f"Error reading detection file: {e}")
                continue

            fragment_frames = sorted([f for f in frames_list if fragment in f],
                                   key=lambda x: int(x[:-4].split('-')[1]))

            print(f"Processing fragment {fragment} ({len(fragment_frames)} frames)")

            for frame_path in fragment_frames:
                frame_start = time.time()

                full_path = os.path.join(frames_dir, frame_path)
                frame = cv2.imread(full_path)

                if frame is None:
                    continue

                try:
                    frame_number = int(frame_path[:-4].split('-')[1])
                except (ValueError, IndexError):
                    continue

                detections = data[data['frame_number'] == frame_number]

                draw_detections_and_license_plate(frame, detections)

                cv2.imshow('frame', frame)

                processing_time = (time.time() - frame_start) * 1000
                delay = max(10, int(FRAME_DELAY - processing_time))

                key = cv2.waitKey(delay) & 0xFF
                if key == ord('q'):
                    print("\nQuitting...")
                    cv2.destroyAllWindows()
                    return
                elif key == ord('p'):
                    print("Paused. Press any key to continue...")
                    cv2.waitKey(0)

                try:
                    os.remove(full_path)
                except OSError:
                    pass

                frame_count += 1
                frames_played_this_cycle += 1

                time.sleep(PROCESSING_DELAY)

            print(f"  Completed fragment {fragment}")

        if frame_count % 50 == 0 and frame_count > 0:
            print(f"Total frames played: {frame_count}")

        if frames_played_this_cycle == 0:
            if not show_loading_animation(frame_template, loading_frames):
                return


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nStopped by user")
    finally:
        cv2.destroyAllWindows()
        print("Cleanup complete")
