# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AirBenders is a gesture-controlled DJ application built with Python. It uses MediaPipe hand tracking via webcam to control music playback, mixing, and effects — no physical hardware required. Built for RoseHacks 2026.

## Running the Application

```bash
# Install dependencies (Python 3.8+ required)
pip install -r requirements.txt

# Place .mp3 files in the MP3/ folder, then run:
python hands.py
```

There is no test suite. Development is run-and-observe.

## Architecture

### Entry Point & Main Loop

`hands.py` is the single entry point. It owns the OpenCV video loop (~30 FPS), initializes all UI components, and routes gesture events to audio commands. It creates both deck instances (left and right).

### Audio Engine (`music.py`)

- `TrackState` — per-deck audio state (position, volume, rate, stem mix)
- `AudioMixer` — sounddevice callback that mixes both decks in real time at 44100 Hz stereo

Playback speed (0.3x–3.0x) is implemented via `scipy.signal.resample`, enabling scratch effects.

### Gesture Detection

MediaPipe tracks 21 landmarks per hand (up to 2 hands simultaneously):
- **Pinch** (thumb + index distance < 40px) → Play/Pause or Load
- **Claw** (5 extended fingers) → Volume via wrist Y position
- **Jog Wheel** (`jogwheel.py`) → Angle delta tracking for scratching/seeking

### UI Modules

Each UI element is its own module that handles its own OpenCV rendering:
- `playbutton.py` — empty/loaded/playing state indicator
- `songlist.py` — draggable, collapsible song library panel
- `stempads.py` — stem isolation toggle buttons (drums, bass, vocals, other, instrumental)
- `visualizer.py` — real-time waveform display
- `beat_grid.py` — beat position/BPM detection with waveform strip and phase ring
- `bpm_display_only.py` — BPM readout

### Stem Separation (`auto_stems.py`)

On first load of any track, Demucs (Facebook's source separation model via PyTorch) runs to split audio into stems. Results are cached permanently in `_temp_stems/` alongside each MP3. This can take minutes per track on first run.

### Beat Analysis (`beat_grid.py`)

Beat positions are detected via autocorrelation and cached in `beat_cache/` as `.npy` files. Cache is keyed by file path — delete `beat_cache/` to force re-analysis.

### Recording (`recorder.py`)

Simultaneously captures the OpenCV video frame and audio mix, then muxes them to MP4 via ffmpeg. Output goes to `recordings/`.

### Configuration

`scratch_config.py` contains tunable scratch behavior constants (sensitivity, smoothing, etc.).

## Key Data Flow

```
Webcam → MediaPipe landmarks → Gesture logic (hands.py)
    → UI state updates (songlist, stempads, jogwheel)
    → Audio commands → TrackState → AudioMixer callback → Speaker
                                                        → Recorder
```

## Important Notes

- `MP3/` and `beat_cache/` and `recordings/` are gitignored.
- The `hand_landmarker.task` file (7.8MB) is the MediaPipe model — do not delete it.
- ffmpeg must be installed and on PATH for the recorder to produce valid MP4 output.
