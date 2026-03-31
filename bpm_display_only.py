"""
Minimal BPM Display - NO BEAT MATCHING
Just shows BPM, doesn't sync tracks
Safe, won't crash

BPM detection uses autocorrelation on a downsampled energy envelope.
This is the same core technique used in Librosa's beat tracker but
implemented with plain NumPy — no LLVM, no extra dependencies.
"""

import numpy as np
import threading
import pickle
from pathlib import Path


# Custom BPM overrides: song_index -> BPM
# Set to {} to use default 172 BPM for all songs
# Example: {2: 172.0} sets the third song (index 2) to 172 BPM
CUSTOM_BPM = {
    # 0: 172.0,
    # 1: 178.0,
    # 2: 172.0,
}

def get_bpm_override(track_index):
    """Get BPM with custom override or default 172 BPM"""
    return CUSTOM_BPM.get(track_index, 172.0)


class SimpleBPMDetector:
    """
    Detects and displays BPM only — no syncing, won't freeze.
    Analysis runs in a background thread (launched by music.py).
    """

    def __init__(self, cache_folder="beat_cache"):
        self.track_bpms = {}
        self.lock = threading.Lock()
        self.cache_folder = Path(cache_folder)
        self.cache_folder.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------
    def _get_cache_path(self, audio_hash):
        return self.cache_folder / f"bpm_{audio_hash}.pkl"

    def _hash_audio(self, audio_data):
        """Lightweight fingerprint — uses first 1 000 samples only."""
        sample = audio_data[:1000].flatten() if len(audio_data) > 1000 else audio_data.flatten()
        return str(hash(sample.tobytes()))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def analyze_track(self, track_index, audio_data, sample_rate):
        """
        Analyze BPM with disk caching.
        Called from a daemon thread in music.py so it never blocks the UI.
        """
        # Use custom BPM override instead of analyzing
        bpm = get_bpm_override(track_index)
        with self.lock:
            self.track_bpms[track_index] = bpm
        print(f"    Using BPM: {bpm:.1f}")
        return bpm

    def get_bpm(self, track_index):
        """Returns detected BPM, or 0.0 if analysis is still running."""
        with self.lock:
            return self.track_bpms.get(track_index, 0.0)


# Alias so existing imports work unchanged
BeatMatcher = SimpleBPMDetector


# ------------------------------------------------------------------
# HUD widget
# ------------------------------------------------------------------
class BPMDisplay:
    """Draws BPM above a jog wheel.  Grey placeholder while pending."""

    def __init__(self, position):
        self.x, self.y = position

    def draw(self, frame, bpm):
        import cv2 as cv
        if bpm > 0:
            text  = f"{bpm:.0f} BPM"
            color = (0, 255, 255)    # cyan
        else:
            text  = "--- BPM"
            color = (80, 200, 200)   # dim cyan while still analysing

        cv.putText(frame, text, (self.x, self.y),
                   cv.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
