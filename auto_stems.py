"""
Auto Stem Manager - PERSISTENT VERSION
Automatically generates stems on startup ONLY if they don't exist.
Keeps stems on disk permanently to avoid 20-minute regeneration.
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


class AutoStemManager:
    def __init__(self, music_folder):
        self.music_folder = Path(music_folder)
        self.stems_folder = self.music_folder / "_temp_stems"
        self.generated_stems = []
        self.demucs_cmd = self._find_demucs()
        self.demucs_available = self.demucs_cmd is not None

        if self.demucs_available:
            print(f"✓ Demucs found: {self.demucs_cmd}")
        else:
            print("⚠ Demucs not found — stems cannot be auto-generated")
            print("  Fix: pip install demucs  then restart")

    # ------------------------------------------------------------------
    # Demucs detection  (the key fix — don't rely on exit code)
    # ------------------------------------------------------------------
    def _find_demucs(self):
        """
        Find demucs using three strategies, most-reliable first.

        NOTE: `demucs --help` exits with code 1 (argparse default) even
        when Demucs is correctly installed.  We therefore check for output
        content rather than the exit code.
        """
        # Strategy 1: executable sitting next to the current Python binary
        #   This is the most reliable approach inside a venv.
        python_dir = Path(sys.executable).parent
        for candidate in [python_dir / "demucs", python_dir / "demucs.exe"]:
            if candidate.exists():
                return str(candidate)

        # Strategy 2: anywhere on PATH
        found = shutil.which("demucs")
        if found:
            return found

        # Strategy 3: run as a module  (python -m demucs)
        #   Works even when the Scripts/bin directory isn't on PATH.
        try:
            result = subprocess.run(
                [sys.executable, "-m", "demucs", "--help"],
                capture_output=True, timeout=15
            )
            combined = (result.stdout or b"").decode("utf-8", errors="ignore") + \
                       (result.stderr or b"").decode("utf-8", errors="ignore")
            # demucs prints its usage info to stderr; just confirm it ran
            if "demucs" in combined.lower() or "usage" in combined.lower() \
                    or "separate" in combined.lower():
                # Return a sentinel that _run_demucs() recognises
                return "__module__"
        except Exception:
            pass

        return None

    def _run_demucs(self, extra_args, mp3_path, timeout=900):
        """Execute demucs and return (returncode, stderr_text)."""
        if self.demucs_cmd == "__module__":
            cmd = [sys.executable, "-m", "demucs"] + extra_args + [str(mp3_path)]
        else:
            cmd = [self.demucs_cmd] + extra_args + [str(mp3_path)]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode, result.stderr

    # ------------------------------------------------------------------
    # Stem existence check
    # ------------------------------------------------------------------
    def _stems_exist(self, mp3_path):
        mp3_path = Path(mp3_path)
        song_stem = mp3_path.stem
        return (self.music_folder / f"{song_stem}_vocals.mp3").exists()

    # ------------------------------------------------------------------
    # 2-stem separation  (vocals + instrumental)
    # ------------------------------------------------------------------
    def separate_song(self, mp3_path):
        if not self.demucs_available:
            print("  ⚠ Demucs not available, skipping")
            return None

        mp3_path = Path(mp3_path)
        song_name = mp3_path.stem

        if self._stems_exist(mp3_path):
            print(f"  ✓ Stems already exist for {mp3_path.name}, skipping...")
            return {'vocals': str(self.music_folder / f"{song_name}_vocals.mp3")}

        print(f"  Separating stems for {mp3_path.name}...")

        try:
            self.stems_folder.mkdir(parents=True, exist_ok=True)
            returncode, stderr = self._run_demucs(
                ['--two-stems', 'vocals',
                 '-o', str(self.stems_folder),
                 '--mp3', '--mp3-bitrate', '192'],
                mp3_path, timeout=900
            )

            if returncode != 0:
                print(f"  ❌ Failed to separate {mp3_path.name}")
                if stderr:
                    print(f"     Error: {stderr[:300]}")
                return None

            demucs_output = self.stems_folder / 'htdemucs' / song_name
            if not demucs_output.exists():
                print(f"  ❌ Demucs output not found at {demucs_output}")
                return None

            stems = {}
            src = demucs_output / 'vocals.mp3'
            if src.exists():
                dest = self.music_folder / f"{song_name}_vocals.mp3"
                shutil.copy2(src, dest)
                stems['vocals'] = str(dest)
                self.generated_stems.append(dest)

            if self.stems_folder.exists():
                shutil.rmtree(self.stems_folder, ignore_errors=True)

            print(f"  ✓ Generated {len(stems)} stems: {', '.join(stems.keys())}")
            return stems

        except subprocess.TimeoutExpired:
            print(f"  ❌ Timeout separating {mp3_path.name}")
            return None
        except Exception as e:
            print(f"  ❌ Error separating {mp3_path.name}: {e}")
            return None

    # ------------------------------------------------------------------
    # Process all songs
    # ------------------------------------------------------------------
    def process_all_songs(self, mp3_files):
        """Process all songs, skipping any that already have stems on disk."""
        if not self.demucs_available:
            print("⚠ Demucs not installed — skipping stem generation")
            print("  Tip: pip install demucs  (then restart)")
            return

        self.stems_folder.mkdir(parents=True, exist_ok=True)

        songs_to_process = [f for f in mp3_files if not self._stems_exist(f)]

        if not songs_to_process:
            print("✓ All stems already exist! Fast startup ⚡")
            return

        already = len(mp3_files) - len(songs_to_process)
        print(f"Found {len(songs_to_process)} song(s) needing stems "
              f"({already} already done).")
        print("Note: First-time model download (~320 MB) happens once only!")
        print()

        for mp3_file in mp3_files:
            self.separate_song(mp3_file)

        print("✓ Stem generation complete!")
        print("💾 Stems kept on disk — next startup will be instant!")

    # ------------------------------------------------------------------
    # Cleanup (keeps stems, only removes temp folder)
    # ------------------------------------------------------------------
    def cleanup(self):
        if self.stems_folder.exists():
            shutil.rmtree(self.stems_folder, ignore_errors=True)
        print("💾 Stems kept on disk for next session")


# ------------------------------------------------------------------
# Global singleton
# ------------------------------------------------------------------
_auto_stem_manager = None


def get_auto_stem_manager(music_folder=None):
    global _auto_stem_manager
    if _auto_stem_manager is None and music_folder is not None:
        _auto_stem_manager = AutoStemManager(music_folder)
    return _auto_stem_manager