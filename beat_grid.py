"""
Beat Grid Visualizer
====================
Draws three things for each deck:

  1. Waveform strip  — a mini scrolling waveform showing ~4 seconds of audio
                       centred on the current playhead.
  2. Beat markers    — vertical tick lines at detected beat positions.
  3. Phase ring      — a small ring between the two decks that shows how well
                       the beats of deck A and deck B are aligned.  Green = in
                       phase, red = out of phase.

All heavy work (beat detection) is done once at load time in a background
thread.  The per-frame draw cost is purely NumPy slicing + a handful of
cv2 calls — safe to run every frame.
"""

import cv2 as cv
import numpy as np
import threading
import pickle
from pathlib import Path

from bpm_display_only import CUSTOM_BPM, get_bpm_override


# ─────────────────────────────────────────────────────────────────────────────
# Beat detector  (reuses the autocorrelation from bpm_display_only.py but
# also returns beat *positions* in seconds)
# ─────────────────────────────────────────────────────────────────────────────

class BeatGrid:
    """
    Stores the waveform thumbnail + beat positions for one track.
    Created once per track, drawn every frame.
    """
    def __init__(self):
        self.ready       = False   # True once background thread finishes
        self.bpm         = 0.0
        self.beat_times  = []      # list of beat positions in seconds
        self.waveform    = None    # 1-D float32 array, full track, downsampled
        self.duration    = 0.0
        self.sample_rate = 44100
        self.lock        = threading.Lock()
        self.deck        = -1      # 0=left, 1=right, -1=unassigned


class BeatGridManager:
    """
    Manages beat grids for all loaded tracks.
    Call  analyze(track_index, audio_data, sample_rate)  from a thread.
    Call  draw_strip(frame, track_index, position, ...)  every frame.
    """

    # visual constants
    STRIP_W        = 300   # width  of waveform strip in pixels
    STRIP_H        = 50    # height of waveform strip in pixels
    WINDOW_SEC     = 4.0   # how many seconds are visible in the strip
    BEAT_COLOR     = (0,   220, 255)   # cyan ticks
    PLAYHEAD_COLOR = (255, 255, 255)   # white centre line
    WAVEFORM_COLOR = (80,  180, 80)    # green waveform
    PHASE_RADIUS   = 22    # radius of the phase ring

    def __init__(self, cache_folder="beat_cache"):
        self.grids        = {}          # track_index -> BeatGrid
        self.cache_folder = Path(cache_folder)
        self.cache_folder.mkdir(exist_ok=True)
        self.track_decks  = {}          # track_index -> deck (0=left, 1=right)

    def set_track_deck(self, track_index, deck):
        self.track_decks[track_index] = deck

    # ── analysis ──────────────────────────────────────────────────────────────

    def analyze(self, track_index, audio_data, sample_rate):
        """
        Run beat detection in whatever thread calls this.
        Stores results in self.grids[track_index].
        """
        grid = BeatGrid()
        grid.sample_rate = sample_rate

        # mono
        if audio_data.ndim > 1:
            mono = np.mean(audio_data, axis=1).astype(np.float32)
        else:
            mono = audio_data.astype(np.float32)

        grid.duration = len(mono) / sample_rate

        # ── waveform thumbnail (downsample to ~1 sample per 5 ms) ───────────
        ds_factor = max(1, int(sample_rate * 0.005))   # 5 ms blocks
        n_blocks  = len(mono) // ds_factor
        blocks    = mono[: n_blocks * ds_factor].reshape(n_blocks, ds_factor)
        waveform  = np.max(np.abs(blocks), axis=1).astype(np.float32)
        peak      = waveform.max()
        if peak > 0:
            waveform /= peak
        grid.waveform = waveform

        # ── beat positions ───────────────────────────────────────────────────
        cache_key  = f"beatgrid_{track_index}_{int(grid.duration)}"
        cache_path = self.cache_folder / f"{cache_key}.pkl"

        if cache_path.exists():
            try:
                with open(cache_path, "rb") as f:
                    cached = pickle.load(f)
                grid.bpm        = cached["bpm"]
                grid.beat_times = cached["beat_times"]
                grid.ready      = True
                self.grids[track_index] = grid
                print(f"    [OK] Beat grid from cache: {grid.bpm:.1f} BPM, "
                      f"{len(grid.beat_times)} beats")
                return
            except Exception:
                pass

        # Get BPM - use custom override or default 172 BPM
        bpm = CUSTOM_BPM.get(track_index, 172.0)
        grid.bpm = bpm

        # Generate beat grid from BPM + first-beat onset
        beat_period = 60.0 / bpm
        first_beat  = 0.0
        beat_times  = []
        t = first_beat
        while t < grid.duration:
            beat_times.append(t)
            t += beat_period
        grid.beat_times = beat_times

        # cache
        try:
            with open(cache_path, "wb") as f:
                pickle.dump({"bpm": bpm, "beat_times": grid.beat_times}, f)
        except Exception:
            pass

        grid.ready = True
        self.grids[track_index] = grid
        print(f"    [OK] Beat grid computed: {bpm:.1f} BPM, {len(beat_times)} beats")

    # ── per-frame drawing ─────────────────────────────────────────────────────

    OTHER_WAVEFORM_COLOR = (0, 120, 255)   # orange — other deck waveform
    OTHER_BEAT_COLOR     = (0, 50,  220)   # red    — other deck beat markers

    def draw_strip(self, frame, track_index, position_sec,
                   cx, y, is_playing, deck,
                   other_track_index=None, other_position_sec=None):
        """
        Draw a waveform strip with stacked beat markers centred at (cx, y).
        cx   = horizontal centre (align with jog wheel centre)
        y    = top of the strip
        deck = 0 for left deck, 1 for right deck

        Stacked layout:
          - Top half: OTHER deck waveform + beat markers
          - Bottom half: MAIN deck waveform + beat markers
        
        Colors are based on which deck the song belongs to:
          - Left deck song = always green
          - Right deck song = always orange
        """
        GREEN_COLOR  = (80,  180, 80)
        ORANGE_COLOR = (0,   120, 255)
        
        if deck == 0:
            main_color     = GREEN_COLOR
            other_color    = ORANGE_COLOR
        else:
            main_color     = ORANGE_COLOR
            other_color    = GREEN_COLOR

        grid = self.grids.get(track_index)
        if grid is None or not grid.ready or grid.waveform is None:
            x1 = cx - self.STRIP_W // 2
            cv.rectangle(frame,
                         (x1, y), (x1 + self.STRIP_W, y + self.STRIP_H),
                         (40, 40, 40), cv.FILLED)
            cv.rectangle(frame,
                         (x1, y), (x1 + self.STRIP_W, y + self.STRIP_H),
                         (80, 80, 80), 1)
            cv.putText(frame, "analysing...",
                       (x1 + 10, y + self.STRIP_H // 2 + 5),
                       cv.FONT_HERSHEY_SIMPLEX, 0.4, (120, 120, 120), 1)
            return

        wf        = grid.waveform
        ds_factor = max(1, int(grid.sample_rate * 0.005))
        wf_sr     = grid.sample_rate / ds_factor

        half_h    = self.STRIP_H // 2
        half_w_sec = self.WINDOW_SEC / 2.0
        x1 = cx - self.STRIP_W // 2
        x2 = cx + self.STRIP_W // 2
        y_top = y
        y_bot = y + half_h

        cv.rectangle(frame, (x1, y), (x2, y + self.STRIP_H),
                     (25, 25, 25), cv.FILLED)
        cv.rectangle(frame, (x1, y), (x2, y + self.STRIP_H),
                     (70, 70, 70), 1)
        cv.line(frame, (x1, y + half_h), (x2, y + half_h), (50, 50, 50), 1)

        mid_y_top  = y + half_h // 2
        mid_y_bot  = y + half_h + half_h // 2
        bar_max_h  = half_h // 2 - 2

        other_grid = self.grids.get(other_track_index) if other_track_index is not None else None

        # ── TOP: other deck waveform + beat markers ──────────────────────────
        if (other_grid is not None and other_grid.ready
                and other_grid.waveform is not None
                and other_position_sec is not None):
            other_wf    = other_grid.waveform
            other_ds    = max(1, int(other_grid.sample_rate * 0.005))
            other_wf_sr = other_grid.sample_rate / other_ds
            for px in range(self.STRIP_W):
                t  = other_position_sec + (px / self.STRIP_W - 0.5) * self.WINDOW_SEC
                wi = int(t * other_wf_sr)
                if 0 <= wi < len(other_wf):
                    amp   = other_wf[wi]
                    bar_h = max(1, int(amp * bar_max_h))
                    cv.line(frame,
                            (x1 + px, mid_y_top - bar_h),
                            (x1 + px, mid_y_top + bar_h),
                            other_color, 1)

            o_start = other_position_sec - half_w_sec
            o_end   = other_position_sec + half_w_sec
            for bt in other_grid.beat_times:
                if o_start <= bt <= o_end:
                    rel  = (bt - o_start) / self.WINDOW_SEC
                    bx   = x1 + int(rel * self.STRIP_W)
                    bidx = other_grid.beat_times.index(bt)
                    is_bar   = (bidx % 4 == 0)
                    tick_h   = half_h if is_bar else half_h // 2
                    tick_y   = y_top if is_bar else y_top + half_h // 4
                    thickness = 2 if is_bar else 1
                    cv.line(frame, (bx, tick_y), (bx, tick_y + tick_h),
                            other_color, thickness)

        # ── BOTTOM: main deck waveform + beat markers ─────────────────────────
        for px in range(self.STRIP_W):
            t = position_sec + (px / self.STRIP_W - 0.5) * self.WINDOW_SEC
            wi = int(t * wf_sr)
            if 0 <= wi < len(wf):
                amp   = wf[wi]
                bar_h = max(1, int(amp * bar_max_h))
                alpha = 0.5 if t < position_sec else 1.0
                c = tuple(int(v * alpha) for v in main_color)
                cv.line(frame,
                        (x1 + px, mid_y_bot - bar_h),
                        (x1 + px, mid_y_bot + bar_h),
                        c, 1)

        t_start = position_sec - half_w_sec
        t_end   = position_sec + half_w_sec
        for bt in grid.beat_times:
            if t_start <= bt <= t_end:
                rel  = (bt - t_start) / self.WINDOW_SEC
                bx   = x1 + int(rel * self.STRIP_W)
                beat_idx = grid.beat_times.index(bt)
                is_bar   = (beat_idx % 4 == 0)
                tick_h   = half_h if is_bar else half_h // 2
                tick_y   = y_bot if is_bar else y_bot + half_h // 4
                color    = (0, 255, 180) if is_bar else self.BEAT_COLOR
                thickness = 2 if is_bar else 1
                cv.line(frame, (bx, tick_y), (bx, tick_y + tick_h),
                        color, thickness)

        # ── playhead ────────────────────────────────────────────────────────
        ph_color = (0, 255, 255) if is_playing else (160, 160, 160)
        cv.line(frame, (cx, y), (cx, y + self.STRIP_H), ph_color, 2)

        # ── time left ───────────────────────────────────────────────────────
        remaining = max(0.0, grid.duration - position_sec)
        mins = int(remaining // 60)
        secs = int(remaining  % 60)
        cv.putText(frame, f"-{mins}:{secs:02d}",
                   (x2 - 50, y + self.STRIP_H - 4),
                   cv.FONT_HERSHEY_SIMPLEX, 0.38, (180, 180, 180), 1)

    def draw_phase_ring(self, frame, cx, cy,
                        track_a, pos_a,
                        track_b, pos_b):
        """
        Draw a ring between the two decks showing beat-phase alignment.

          Green  = beats are closely aligned  (< 10 % of beat period apart)
          Yellow = close but not perfect       (10–30 %)
          Red    = out of phase                (> 30 %)

        A small dot on the ring shows exactly *where* in the beat cycle
        each deck is, like clock hands.
        """
        grid_a = self.grids.get(track_a)
        grid_b = self.grids.get(track_b)

        if (grid_a is None or not grid_a.ready or
                grid_b is None or not grid_b.ready):
            return

        bpm_a = grid_a.bpm
        bpm_b = grid_b.bpm
        if bpm_a <= 0 or bpm_b <= 0:
            return

        # Phase of each deck (0..1 within one beat period)
        def phase(bpm, pos):
            period = 60.0 / bpm
            return (pos % period) / period if period > 0 else 0.0

        ph_a = phase(bpm_a, pos_a)
        ph_b = phase(bpm_b, pos_b)

        diff  = abs(ph_a - ph_b)
        diff  = min(diff, 1.0 - diff)   # wrap — max possible diff is 0.5

        # Colour by alignment
        if diff < 0.10:
            ring_color = (0, 255, 80)     # green
        elif diff < 0.30:
            ring_color = (0, 200, 255)    # yellow-ish
        else:
            ring_color = (0, 80, 255)     # red

        r = self.PHASE_RADIUS

        # Background circle
        cv.circle(frame, (cx, cy), r, (40, 40, 40), cv.FILLED)
        cv.circle(frame, (cx, cy), r, ring_color, 2)

        # Dot for deck A (left)  — angle 0 = top, clockwise
        angle_a = ph_a * 2 * np.pi - np.pi / 2
        dot_a   = (int(cx + r * np.cos(angle_a)),
                   int(cy + r * np.sin(angle_a)))
        cv.circle(frame, dot_a, 4, (0, 220, 255), cv.FILLED)   # cyan

        # Dot for deck B (right)
        angle_b = ph_b * 2 * np.pi - np.pi / 2
        dot_b   = (int(cx + r * np.cos(angle_b)),
                   int(cy + r * np.sin(angle_b)))
        cv.circle(frame, dot_b, 4, (255, 120, 0), cv.FILLED)   # orange

        # Label
        label = "IN SYNC" if diff < 0.10 else f"{int(diff*100)}% off"
        (lw, _), _ = cv.getTextSize(label, cv.FONT_HERSHEY_SIMPLEX, 0.32, 1)
        cv.putText(frame, label,
                   (cx - lw // 2, cy + r + 14),
                   cv.FONT_HERSHEY_SIMPLEX, 0.32, ring_color, 1)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _detect_bpm(self, mono, sample_rate):
        """Autocorrelation BPM (same algorithm as bpm_display_only.py)."""
        max_samples = 30 * sample_rate
        if len(mono) > max_samples:
            mono = mono[:max_samples]

        hop  = 512
        flen = 1024
        n_frames = (len(mono) - flen) // hop
        if n_frames < 20:
            return 120.0

        env = np.array([
            np.sqrt(np.mean(mono[i * hop: i * hop + flen] ** 2))
            for i in range(n_frames)
        ], dtype=np.float32)

        env_sr = sample_rate / hop
        env   -= env.mean()
        env   *= np.hanning(len(env)).astype(np.float32)

        n_fft = 1
        while n_fft < 2 * len(env):
            n_fft <<= 1
        spec = np.fft.rfft(env, n=n_fft)
        acf  = np.fft.irfft(spec * np.conj(spec))[:len(env)]
        if acf[0] > 0:
            acf /= acf[0]

        bpm_lo, bpm_hi = 60.0, 180.0
        lag_lo = max(1, int(np.floor(60.0 / bpm_hi * env_sr)))
        lag_hi = min(len(acf) - 1, int(np.ceil(60.0 / bpm_lo * env_sr)))

        search = acf[lag_lo: lag_hi + 1]
        if len(search) == 0:
            return 120.0

        best_lag = np.argmax(search) + lag_lo
        raw_bpm  = 60.0 * env_sr / best_lag

        candidates = []
        for mult in [0.5, 1.0, 2.0]:
            c = raw_bpm * mult
            if bpm_lo <= c <= bpm_hi:
                c_lag = int(round(60.0 * env_sr / c))
                if 0 < c_lag < len(acf):
                    candidates.append((acf[c_lag], c))

        if candidates:
            return round(max(candidates, key=lambda x: x[0])[1], 1)
        return round(float(np.clip(raw_bpm, bpm_lo, bpm_hi)), 1)

