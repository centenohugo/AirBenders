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
        audio_hash = self._hash_audio(audio_data)
        cache_path = self._get_cache_path(audio_hash)

        # --- cache hit ---
        if cache_path.exists():
            try:
                with open(cache_path, 'rb') as f:
                    cached_bpm = pickle.load(f)
                with self.lock:
                    self.track_bpms[track_index] = float(cached_bpm)
                print(f"    ✓ BPM from cache: {cached_bpm:.1f}")
                return float(cached_bpm)
            except Exception:
                pass  # corrupt cache — re-analyse

        # --- analyse ---
        try:
            bpm = self._analyze_autocorr(track_index, audio_data, sample_rate)
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump(bpm, f)
            except Exception:
                pass
            return bpm
        except Exception as e:
            print(f"    ⚠️  BPM analysis failed: {e}")
            with self.lock:
                self.track_bpms[track_index] = 120.0
            return 120.0

    def get_bpm(self, track_index):
        """Returns detected BPM, or 0.0 if analysis is still running."""
        with self.lock:
            return self.track_bpms.get(track_index, 0.0)

    # ------------------------------------------------------------------
    # Core algorithm: autocorrelation on RMS energy envelope
    # ------------------------------------------------------------------
    def _analyze_autocorr(self, track_index, audio_data, sample_rate):
        """
        Accurate BPM via autocorrelation — works on all genres.

        Steps
        -----
        1. Collapse to mono, take first 30 s.
        2. Compute RMS energy in short frames → energy envelope.
        3. Downsample the envelope to ~100 Hz (one value per 10 ms).
        4. Subtract mean (remove DC) and apply a Hann window.
        5. Autocorrelate.  Peaks in the autocorrelation correspond to
           the period of the dominant beat.
        6. Search for the strongest peak in the range 60–180 BPM,
           then check the octave (half / double) and pick the best one.
        """
        # ---- 1. Mono, 30 s max ----------------------------------------
        if audio_data.ndim > 1:
            mono = np.mean(audio_data, axis=1).astype(np.float32)
        else:
            mono = audio_data.astype(np.float32)

        max_samples = 30 * sample_rate
        if len(mono) > max_samples:
            mono = mono[:max_samples]

        # ---- 2. RMS energy envelope ------------------------------------
        hop  = 512          # ~11.6 ms at 44100 Hz
        flen = 1024
        n_frames = (len(mono) - flen) // hop
        if n_frames < 20:
            bpm = 120.0
            with self.lock:
                self.track_bpms[track_index] = bpm
            print(f"    ✓ Estimated BPM: {bpm:.1f}  (too short, used default)")
            return bpm

        env = np.array([
            np.sqrt(np.mean(mono[i * hop: i * hop + flen] ** 2))
            for i in range(n_frames)
        ], dtype=np.float32)

        # ---- 3. Envelope sample rate -----------------------------------
        env_sr = sample_rate / hop          # frames per second (~86 Hz)

        # ---- 4. Remove DC + Hann window --------------------------------
        env -= env.mean()
        env *= np.hanning(len(env)).astype(np.float32)

        # ---- 5. Autocorrelation ----------------------------------------
        # Full autocorrelation via FFT (fast even for 30 s)
        n_fft = 1
        while n_fft < 2 * len(env):
            n_fft <<= 1
        spec = np.fft.rfft(env, n=n_fft)
        acf  = np.fft.irfft(spec * np.conj(spec))[:len(env)]
        # Normalise
        if acf[0] > 0:
            acf /= acf[0]

        # ---- 6. Find best BPM peak -------------------------------------
        # Convert BPM range to lag range (in envelope frames)
        bpm_lo, bpm_hi = 60.0, 180.0
        lag_lo = int(np.floor(60.0 / bpm_hi * env_sr))
        lag_hi = int(np.ceil (60.0 / bpm_lo * env_sr))
        lag_lo = max(lag_lo, 1)
        lag_hi = min(lag_hi, len(acf) - 1)

        search = acf[lag_lo: lag_hi + 1]
        if len(search) == 0:
            bpm = 120.0
        else:
            best_lag = np.argmax(search) + lag_lo
            raw_bpm  = 60.0 * env_sr / best_lag

            # Check octave candidates (half / double) and keep the one
            # with the highest autocorrelation within 60–180 BPM
            candidates = []
            for mult in [0.5, 1.0, 2.0]:
                c = raw_bpm * mult
                if bpm_lo <= c <= bpm_hi:
                    c_lag = int(round(60.0 * env_sr / c))
                    if 0 < c_lag < len(acf):
                        candidates.append((acf[c_lag], c))

            if candidates:
                bpm = max(candidates, key=lambda x: x[0])[1]
            else:
                bpm = float(np.clip(raw_bpm, bpm_lo, bpm_hi))

        bpm = round(bpm, 1)
        with self.lock:
            self.track_bpms[track_index] = bpm

        print(f"    ✓ Estimated BPM: {bpm:.1f}")
        return bpm


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