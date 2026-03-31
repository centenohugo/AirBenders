# AGENTS.md

This file provides guidance for AI agents working with the AirBenders codebase.

## Project Overview

AirBenders is a gesture-controlled DJ application built with Python. It uses MediaPipe hand tracking via webcam to control music playback, mixing, and effects — no physical hardware required. Built for RoseHacks 2026.

## Quick Start

```bash
# Install dependencies (Python 3.8+ required)
pip install -r requirements.txt

# Add music files to the MP3/ folder, then run:
python hands.py
```

**Note:** There is no test suite. Development is run-and-observe.

---

## Build / Run Commands

### Running the Application
```bash
python hands.py
```

### Dependency Management
```bash
pip install -r requirements.txt              # Fresh install
pip install --upgrade -r requirements.txt    # Upgrade existing packages
pip install --upgrade --force-reinstall -r requirements.txt  # Nuclear option
```

### GPU Acceleration (Optional)
For faster stem generation with NVIDIA GPU:
```bash
# For CUDA 11.8:
pip install torch==2.2.2+cu118 torchaudio==2.2.2+cu118 --index-url https://download.pytorch.org/whl/cu118

# For CUDA 12.1:
pip install torch==2.2.2+cu121 torchaudio==2.2.2+cu121 --index-url https://download.pytorch.org/whl/cu121

# Verify GPU detection:
python -c "import torch; print(torch.cuda.is_available())"
```

### External Dependencies
- **ffmpeg** must be installed and on PATH for the recorder to produce valid MP4 output.
  - macOS: `brew install ffmpeg`
  - Windows: Download from https://ffmpeg.org/

---

## Code Style Guidelines

### Import Conventions
```python
# Standard library first, then third-party, then local
import os
import time
import cv2 as cv
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np

from playbutton import PlayButton
from jogwheel import JogWheel
import music as mc
```

### Naming Conventions
| Element | Convention | Example |
|---------|------------|---------|
| Classes | PascalCase | `class PlayButton`, `class TrackState` |
| Functions | snake_case | `def toggle_play()`, `def is_pinching()` |
| Variables | snake_case | `left_song_index`, `scratch_speed` |
| Constants | SCREAMING_SNAKE_CASE | `SCRATCH_SENSITIVITY`, `TARGET_SAMPLE_RATE` |
| Module-level globals | snake_case | `songs`, `track_states`, `active_track` |

### Class Structure
Each UI component is its own module with a draw/contains/update pattern:
```python
class PlayButton:
    def __init__(self, center, radius=30, label="PLAY"):
        # Instance attributes

    def draw(self, frame, state="empty"):
        # Render to OpenCV frame

    def contains(self, px, py):
        # Hit detection, returns bool
```

### Type Hints
The codebase does not currently use type hints. When adding new code:
- Use type hints for function parameters and return types
- Keep them simple (no complex generics)

### Error Handling
- Use try/except blocks with specific exception types when possible
- Print user-facing messages for recoverable errors
- Let exceptions propagate for fatal errors
```python
try:
    audio_data, sample_rate = sf.read(filepath, dtype='float32')
except Exception as e:
    print(f"    Failed to load {stem_type} stem: {e}")
    return False
```

### Thread Safety
Audio callbacks and background threads access shared state:
- Use `threading.Lock()` for protecting shared data
- Always use `with self.lock:` context manager
- Be careful with closures in background threads (capture variables explicitly)

---

## Architecture

### Entry Point: `hands.py`
- Initializes MediaPipe hand tracking
- Owns the OpenCV video loop (~30 FPS)
- Routes gesture events to audio commands
- Creates both deck instances (left and right)

### Audio Engine: `music.py`
- `TrackState` — per-deck audio state (position, volume, rate, stem mix)
- `AudioMixer` — sounddevice callback that mixes both decks in real time at 44100 Hz stereo
- Playback speed (0.3x–3.0x) via `scipy.signal.resample` for scratch effects

### Gesture Detection
MediaPipe tracks 21 landmarks per hand (up to 2 hands simultaneously):
- **Pinch** (thumb + index distance < 40px) → Play/Pause or Load
- **Claw** (5 extended fingers) → Volume via wrist Y position
- **Jog Wheel** → Angle delta tracking for scratching/seeking

### UI Modules
Each UI element handles its own OpenCV rendering:
- `playbutton.py` — empty/loaded/playing state indicator
- `jogwheel.py` — virtual wheel for scratching/seeking
- `volumeSlider.py` — vertical slider with claw gesture control
- `songlist.py` — draggable, collapsible song library panel
- `stempads.py` — stem isolation toggle buttons
- `visualizer.py` — waveform display
- `beat_grid.py` — beat position/BPM detection
- `cuebutton.py` — cue point management
- `recorder.py` — session recording

### Stem Separation: `auto_stems.py`
On first load, Demucs runs to split audio into stems (drums, bass, vocals, other, instrumental). Results are cached in `_temp_stems/` alongside each MP3. First run can take minutes per track.

### Beat Analysis: `beat_grid.py`
Beat positions detected via autocorrelation, cached in `beat_cache/` as `.pkl` files. Delete `beat_cache/` to force re-analysis.

### Configuration: `scratch_config.py`
Contains tunable scratch behavior constants (sensitivity, smoothing, etc.).

---

## Data Flow
```
Webcam → MediaPipe landmarks → Gesture logic (hands.py)
    → UI state updates (songlist, stempads, jogwheel)
    → Audio commands → TrackState → AudioMixer callback → Speaker
                                                        → Recorder
```

---

## Important Notes

### Gitignored Directories
- `MP3/` — user music files
- `beat_cache/` — cached beat analysis
- `recordings/` — session recordings
- `_temp_stems/` — cached stem separation output

### Do Not Delete
- `hand_landmarker.task` — MediaPipe model (~7.8MB)

### Caching Behavior
- Beat grid analysis is cached in `beat_cache/`
- Stem separation is cached in `_temp_stems/`
- Delete these folders to force regeneration

---

## Adding New UI Components

1. Create a new `.py` file (e.g., `new_component.py`)
2. Follow the `draw/contains/update` pattern
3. Import `cv2 as cv` for rendering
4. Register the component in `hands.py`
5. Add gesture handling logic in the main loop

```python
# new_component.py
import cv2 as cv
import math

class NewComponent:
    def __init__(self, center, radius=30):
        self.cx, self.cy = center
        self.radius = radius

    def contains(self, x, y):
        return math.hypot(x - self.cx, y - self.cy) <= self.radius

    def update(self, pinch_positions):
        # Update state based on gestures
        pass

    def draw(self, frame):
        cv.circle(frame, (self.cx, self.cy), self.radius, (255, 255, 255), -1)
```
