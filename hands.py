import os
import ctypes
import cv2 as cv
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
# from visualizer import DJVisualizer
import math
from playbutton import PlayButton
from jogwheel import JogWheel
import music as mc
import time
import songlist
from load import LoadButton
from volumeSlider import VolumeSlider
from stempads import StemPadBank
from recorder import DJRecorder, RecordButton
from cuebutton import CueButton
from bpm_display_only import BeatMatcher, BPMDisplay
from beat_grid import BeatGridManager

# -----------------------------
# Initialize Beat Matcher FIRST (must exist before load_music_folder)
# -----------------------------
beat_matcher = BeatMatcher()
mc.beat_matcher = beat_matcher
print(f"🎵 Beat matcher initialized")

beat_grid_manager = BeatGridManager()
mc.beat_grid_manager = beat_grid_manager
print(f"🎼 Beat grid manager initialized")
print()

# -----------------------------
# Initialize Recorder
# -----------------------------
recorder = DJRecorder(output_folder="recordings")
print(f"📹 Recorder initialized")
if not recorder.is_ffmpeg_available():
    print("⚠️  ffmpeg not found - install with: brew install ffmpeg")
    print("   Recording will work but videos won't be combined")
print()

# Set recorder in music module so it can capture audio
mc.audio_recorder = recorder

# -----------------------------
# Load Music (beat_matcher must already be set above)
# -----------------------------
MUSIC_FOLDER = "MP3"
mc.load_music_folder(MUSIC_FOLDER)

# -----------------------------
# Deck Initialization
# -----------------------------
left_song_index = -1
right_song_index = -1

# -----------------------------
# MediaPipe Hand Landmarker Setup
# -----------------------------
MODEL_PATH = "hand_landmarker.task"
BaseOptions = python.BaseOptions
HandLandmarker = vision.HandLandmarker
HandLandmarkerOptions = vision.HandLandmarkerOptions
VisionRunningMode = vision.RunningMode

options = HandLandmarkerOptions(
    base_options=BaseOptions(model_asset_path=MODEL_PATH),
    running_mode=VisionRunningMode.VIDEO,
    num_hands=2
)
landmarker = HandLandmarker.create_from_options(options)

# -----------------------------
# Song List Panel
# -----------------------------
song_names = [os.path.basename(s) for s in mc.songs]
song_list_panel = None
song_list_width = 350
item_height = 45
highlighted_index = None
song_pinch_id = None

# -----------------------------
# Pinch Detection (for play & load only)
# -----------------------------
def is_pinching(hand_landmarks, w, h, threshold=40):
    thumb_tip = hand_landmarks[4]
    index_tip = hand_landmarks[8]
    tx, ty = int(thumb_tip.x * w), int(thumb_tip.y * h)
    ix, iy = int(index_tip.x * w), int(index_tip.y * h)
    return math.hypot(tx - ix, ty - iy) < threshold

def format_time(seconds):
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"

class ScrubCallback:
    def __init__(self, index): self.index = index
    def __call__(self, delta):
        if self.index >= 0: mc.scrub(delta, self.index)

class ReleaseCallback:
    def __init__(self, index): self.index = index
    def __call__(self):
        if self.index >= 0: mc.end_scrub(self.index)

# -----------------------------
# Camera & UI
# -----------------------------
cam = cv.VideoCapture(0)
frame_idx = 0
left_button = right_button = left_load_button = right_load_button = None
left_cue_button = right_cue_button = None
left_cue_held = False
right_cue_held = False
left_jog = right_jog = None
left_volume = right_volume = None
left_stem_bank = right_stem_bank = None
record_button = None
left_bpm_display = right_bpm_display = None
beat_grid_manager_ui = None  # alias for drawing
pinching_previous = set()

# -----------------------------
# Main Loop
# -----------------------------
_user32 = ctypes.windll.user32
SCREEN_W = _user32.GetSystemMetrics(0)
SCREEN_H = _user32.GetSystemMetrics(1)

cv.namedWindow("Show Video", cv.WINDOW_NORMAL)
cv.setWindowProperty("Show Video", cv.WND_PROP_FULLSCREEN, cv.WINDOW_FULLSCREEN)
while cam.isOpened():
    success, frame = cam.read()
    if not success: continue

    mc.update_active_track_position()
    frame = cv.flip(frame, 1)
    frame = cv.resize(frame, (SCREEN_W, SCREEN_H))
    h, w, _ = frame.shape

    # Initialize song list
    if song_list_panel is None:
        song_list_x = w // 2 - song_list_width // 2
        song_list_y = 100
        song_list_panel = songlist.SongList(song_names, position=(song_list_x, song_list_y), width=song_list_width, item_height=item_height)

    # Initialize UI elements
    if left_button is None:
        center_x = w//2
        button_y = int(h*0.83)
        left_button = PlayButton(center=(center_x-200, button_y), radius=30, label="PLAY 1")
        right_button = PlayButton(center=(center_x+200, button_y), radius=30, label="PLAY 2")
        left_load_button = LoadButton(center=(center_x-200, button_y-70), radius=25, label="LOAD")
        right_load_button = LoadButton(center=(center_x+200, button_y-70), radius=25, label="LOAD")
        left_cue_button = CueButton(center=(center_x-130, button_y), radius=25, label="CUE")
        right_cue_button = CueButton(center=(center_x+130, button_y), radius=25, label="CUE")
        
        # Record button - top center
        record_button = RecordButton(center=(center_x, 60), radius=35)
        
        jog_y = int(h*0.55)
        left_jog = JogWheel(center=(center_x-350, jog_y), radius=160)
        right_jog = JogWheel(center=(center_x+350, jog_y), radius=160)
        
        # BPM displays - below jog wheels (time text is at radius+50, BPM sits at radius+75)
        left_bpm_display = BPMDisplay(position=(center_x-350-40, jog_y+160+75))
        right_bpm_display = BPMDisplay(position=(center_x+350-40, jog_y+160+75))

        slider_width = 30
        slider_height = 200
        slider_offset = 220
        left_volume = VolumeSlider(x=left_jog.cx - slider_offset - slider_width, y=left_jog.cy - slider_height//2, width=slider_width, height=slider_height, track_index=0)
        right_volume = VolumeSlider(x=right_jog.cx + slider_offset, y=right_jog.cy - slider_height//2, width=slider_width, height=slider_height, track_index=1)

        # Stem pad banks — own row below play/cue, in the center gap
        stem_pad_y = button_y + 65
        left_stem_bank = StemPadBank(
            position=(center_x - 55, stem_pad_y),
            track_index=0,
            deck_label="L"
        )
        right_stem_bank = StemPadBank(
            position=(center_x + 55, stem_pad_y),
            track_index=1,
            deck_label="R"
        )


    # -----------------------------
    # Hand Detection
    # -----------------------------
    rgb_frame = cv.cvtColor(frame, cv.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
    timestamp_ms = int(time.time() * 1000)
    detection_result = landmarker.detect_for_video(mp_image, timestamp_ms)

    pinch_positions = []
    if detection_result.hand_landmarks:
        for hand_landmarks in detection_result.hand_landmarks:
            if is_pinching(hand_landmarks, w, h):
                thumb_tip = hand_landmarks[4]
                index_tip = hand_landmarks[8]
                cx = int((thumb_tip.x + index_tip.x)/2 * w)
                cy = int((thumb_tip.y + index_tip.y)/2 * h)
                pinch_positions.append((cx, cy))
                cv.circle(frame, (cx, cy), 10, (0,255,0), -1)

    # -----------------------------
    # Song List Update (dragging and collapse)
    # -----------------------------
    song_list_panel.update(pinch_positions)
    
    song_pinched_this_frame = False
    if not song_list_panel.is_collapsed and not song_list_panel.is_dragging:
        idx = song_list_panel.check_pinch(pinch_positions)
        if idx is not None:
            song_pinched_this_frame = True
            if song_pinch_id != idx:
                highlighted_index = None if highlighted_index == idx else idx
                song_pinch_id = idx
    
    if not song_pinched_this_frame:
        song_pinch_id = None

    song_list_panel.draw(frame, highlight_index=highlighted_index)

    # -----------------------------
    # Load Buttons Logic
    # -----------------------------
    left_load_active = right_load_active = False
    if not song_list_panel.is_collapsed and not song_list_panel.is_dragging:
        for px, py in pinch_positions:
            if highlighted_index is not None:
                if left_load_button.contains(px, py):
                    if left_song_index >= 0:
                        mc.stop(left_song_index)
                    left_song_index = highlighted_index
                    mc.stop(left_song_index)
                    highlighted_index = None
                    left_load_active = True
                if right_load_button.contains(px, py):
                    if right_song_index >= 0:
                        mc.stop(right_song_index)
                    right_song_index = highlighted_index
                    mc.stop(right_song_index)
                    highlighted_index = None
                    right_load_active = True

    # -----------------------------
    # Play & Load Buttons
    # -----------------------------
    left_state = "empty" if left_song_index<0 else "playing" if mc.is_playing(left_song_index) else "loaded"
    right_state = "empty" if right_song_index<0 else "playing" if mc.is_playing(right_song_index) else "loaded"
    left_button.draw(frame, state=left_state)
    right_button.draw(frame, state=right_state)
    left_load_button.draw(frame, active=left_load_active)
    right_load_button.draw(frame, active=right_load_active)

    # -----------------------------
    # Trigger Play if Pinched
    # -----------------------------
    left_active = left_song_index>=0 and any(left_button.contains(x,y) for x,y in pinch_positions)
    right_active = right_song_index>=0 and any(right_button.contains(x,y) for x,y in pinch_positions)
    
    if left_active and left_button.center not in pinching_previous:
        mc.toggle_play(left_song_index)

    if right_active and right_button.center not in pinching_previous:
        mc.toggle_play(right_song_index)

    pinching_previous = set()
    if left_active: pinching_previous.add(left_button.center)
    if right_active: pinching_previous.add(right_button.center)

    # -----------------------------
    # CUE Buttons (hold = preview, release = volver al cue y parar)
    # -----------------------------
    left_cue_active = left_song_index >= 0 and any(left_cue_button.contains(x, y) for x, y in pinch_positions)
    right_cue_active = right_song_index >= 0 and any(right_cue_button.contains(x, y) for x, y in pinch_positions)

    if left_cue_active and not left_cue_held:
        mc.start_cue(left_song_index)
    elif not left_cue_active and left_cue_held:
        mc.release_cue(left_song_index)

    if right_cue_active and not right_cue_held:
        mc.start_cue(right_song_index)
    elif not right_cue_active and right_cue_held:
        mc.release_cue(right_song_index)

    left_cue_held = left_cue_active
    right_cue_held = right_cue_active

    left_cue_pt = mc.get_cue_point(left_song_index) if left_song_index >= 0 else None
    right_cue_pt = mc.get_cue_point(right_song_index) if right_song_index >= 0 else None

    left_cue_state = "active" if left_cue_active else ("cue_set" if left_cue_pt is not None else "no_cue")
    right_cue_state = "active" if right_cue_active else ("cue_set" if right_cue_pt is not None else "no_cue")

    left_cue_button.draw(frame, state=left_cue_state)
    right_cue_button.draw(frame, state=right_cue_state)

    # -----------------------------
    # Stem Pads Control
    # -----------------------------
    # Left deck
    if left_song_index >= 0 and mc.has_stems(left_song_index):
        left_stem_states = {
            stem: mc.get_stem_state(left_song_index, stem)
            for stem in mc.get_available_stems(left_song_index)
        }
        pinched_stems = left_stem_bank.update(pinch_positions, left_stem_states)
        for stem_type in pinched_stems:
            mc.toggle_stem(left_song_index, stem_type)
    else:
        left_stem_bank.update([], {'vocals': False})
    left_stem_bank.draw(frame)

    # Right deck
    if right_song_index >= 0 and mc.has_stems(right_song_index):
        right_stem_states = {
            stem: mc.get_stem_state(right_song_index, stem)
            for stem in mc.get_available_stems(right_song_index)
        }
        pinched_stems = right_stem_bank.update(pinch_positions, right_stem_states)
        for stem_type in pinched_stems:
            mc.toggle_stem(right_song_index, stem_type)
    else:
        right_stem_bank.update([], {'vocals': False})
    right_stem_bank.draw(frame)

    # -----------------------------
    # Jog Wheels
    # -----------------------------
    left_pinching_jog = right_pinching_jog = False
    for cx, cy in pinch_positions:
        if left_song_index>=0 and left_jog.contains(cx, cy):
            left_pinching_jog = True
            left_jog.update(frame, cx, cy, True, ScrubCallback(left_song_index), ReleaseCallback(left_song_index))
        if right_song_index>=0 and right_jog.contains(cx, cy):
            right_pinching_jog = True
            right_jog.update(frame, cx, cy, True, ScrubCallback(right_song_index), ReleaseCallback(right_song_index))
    if not left_pinching_jog: left_jog.check_release()
    if not right_pinching_jog: right_jog.check_release()

    # Spin visuals
    if left_song_index>=0 and mc.is_playing(left_song_index):
        left_jog.angle += 0.05
    if right_song_index>=0 and mc.is_playing(right_song_index):
        right_jog.angle += 0.05
    left_jog.draw(frame)
    right_jog.draw(frame)

    # -----------------------------
    # Volume Sliders (grab & drag)
    # -----------------------------
    left_volume.update(pinch_positions)
    right_volume.update(pinch_positions)
    if left_song_index >= 0:
        mc.set_volume(left_song_index, left_volume.volume)
    if right_song_index >= 0:
        mc.set_volume(right_song_index, right_volume.volume)

    left_volume.draw(frame)
    right_volume.draw(frame)

    # -----------------------------
    # Display Time & Colors
    # -----------------------------
    left_time = mc.get_position(left_song_index) if left_song_index>=0 else 0
    right_time = mc.get_position(right_song_index) if right_song_index>=0 else 0
    
    left_color = (0,255,255) if mc.is_playing(left_song_index) else (100,100,100)
    right_color = (0,255,255) if mc.is_playing(right_song_index) else (100,100,100)
    
    left_time_pos = (left_jog.cx-40, left_jog.cy+left_jog.radius+50)
    right_time_pos = (right_jog.cx-40, right_jog.cy+right_jog.radius+50)
    cv.putText(frame, format_time(left_time), left_time_pos, cv.FONT_HERSHEY_SIMPLEX, 0.6, left_color, 2)
    cv.putText(frame, format_time(right_time), right_time_pos, cv.FONT_HERSHEY_SIMPLEX, 0.6, right_color, 2)
    
    # Draw BPM displays - always draw when a song is loaded (shows "--- BPM" while analyzing)
    if left_song_index >= 0:
        left_bpm = mc.get_bpm(left_song_index)
        left_bpm_display.draw(frame, left_bpm)
    
    if right_song_index >= 0:
        right_bpm = mc.get_bpm(right_song_index)
        right_bpm_display.draw(frame, right_bpm)

    # -----------------------------
    # Beat Grid Strips + Phase Ring
    # drawn here so they are baked into the frame before the recorder captures it
    # -----------------------------
    strip_y = left_jog.cy - left_jog.radius - 80
    if left_song_index >= 0:
        beat_grid_manager.draw_strip(
            frame, left_song_index,
            mc.get_position(left_song_index),
            cx=left_jog.cx, y=strip_y,
            is_playing=mc.is_playing(left_song_index),
            other_track_index=right_song_index if right_song_index >= 0 else None,
            other_position_sec=mc.get_position(right_song_index) if right_song_index >= 0 else None
        )
    if right_song_index >= 0:
        beat_grid_manager.draw_strip(
            frame, right_song_index,
            mc.get_position(right_song_index),
            cx=right_jog.cx, y=strip_y,
            is_playing=mc.is_playing(right_song_index),
            other_track_index=left_song_index if left_song_index >= 0 else None,
            other_position_sec=mc.get_position(left_song_index) if left_song_index >= 0 else None
        )
    if left_song_index >= 0 and right_song_index >= 0:
        ring_cx = w // 2
        ring_cy = strip_y + 25
        beat_grid_manager.draw_phase_ring(
            frame, ring_cx, ring_cy,
            left_song_index,  mc.get_position(left_song_index),
            right_song_index, mc.get_position(right_song_index)
        )

    # Display now playing for both decks
    now_playing_text = []
    if left_song_index >= 0 and mc.is_playing(left_song_index):
        now_playing_text.append(f"LEFT: {mc.get_current_song_name(left_song_index)}")
    if right_song_index >= 0 and mc.is_playing(right_song_index):
        now_playing_text.append(f"RIGHT: {mc.get_current_song_name(right_song_index)}")
    
    if now_playing_text:
        cv.putText(frame, " | ".join(now_playing_text), (10,210), cv.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
    
    # Show stem status if active
    stem_status_y = 240
    if left_song_index >= 0 and mc.has_stems(left_song_index):
        active_stems = [s for s in mc.get_available_stems(left_song_index) if mc.get_stem_state(left_song_index, s)]
        if active_stems:
            cv.putText(frame, f"LEFT STEMS: {', '.join(active_stems)}", (10, stem_status_y), 
                      cv.FONT_HERSHEY_SIMPLEX, 0.5, (100,200,255), 1)
            stem_status_y += 25
    
    if right_song_index >= 0 and mc.has_stems(right_song_index):
        active_stems = [s for s in mc.get_available_stems(right_song_index) if mc.get_stem_state(right_song_index, s)]
        if active_stems:
            cv.putText(frame, f"RIGHT STEMS: {', '.join(active_stems)}", (10, stem_status_y), 
                      cv.FONT_HERSHEY_SIMPLEX, 0.5, (100,200,255), 1)

    # -----------------------------
    # Visualizer (commented out)
    # -----------------------------

    # -----------------------------
    # Recording Controls
    # capture LAST — everything above is already drawn onto the frame
    # -----------------------------
    record_duration = recorder.get_recording_duration()
    record_newly_pinched = record_button.update(pinch_positions, recorder.is_recording)
    
    if record_newly_pinched:
        if not recorder.is_recording:
            if recorder.start_recording(w, h):
                print(f"🔴 Recording session started")
        else:
            output_file = recorder.stop_recording()
            if output_file:
                print(f"✅ Session saved: {output_file}")
    
    record_button.draw(frame, duration=record_duration)

    # Add frame to recorder LAST — all UI elements including beat grid are drawn by this point
    if recorder.is_recording:
        recorder.add_video_frame(frame.copy())

    # Show Frame
    cv.imshow("Show Video", frame)
    if cv.waitKey(20) & 0xFF == ord('q'): break

cam.release()
cv.destroyAllWindows()