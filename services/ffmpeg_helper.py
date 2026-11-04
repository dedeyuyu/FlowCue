# -*- coding: utf-8 -*-
"""
FFmpeg & FFprobe helper service for FlowCue.
Provides fast audio extraction (for 10x faster ASR upload), media probing,
and cross-platform subprocess execution without console window popups.
"""
import os
import sys
import json
import time
import uuid
import shutil
import tempfile
import hashlib
import threading
import subprocess
from pathlib import Path

# Suppress console window on Windows
_SUBPROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class FFmpegHelper:
    """Locates ffmpeg/ffprobe binaries and provides fast audio/video utilities."""

    _ffmpeg_path_cache = None
    _ffprobe_path_cache = None

    @classmethod
    def clear_cache(cls):
        """Clears cached ffmpeg/ffprobe paths so newly installed runtime binaries are discovered."""
        cls._ffmpeg_path_cache = None
        cls._ffprobe_path_cache = None

    @classmethod
    def _candidate_dirs(cls):
        """Returns candidate directories where ffmpeg/ffprobe might reside."""
        candidates = []
        # 1. Environment variable overrides
        env_ffmpeg = os.environ.get("FFMPEG_PATH", "")
        if env_ffmpeg:
            p = Path(env_ffmpeg)
            candidates.append(p.parent if p.is_file() else p)

        # 2. Permanent user-level auto-installed runtime (%LOCALAPPDATA%\FlowCue\runtime)
        local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        runtime_base = Path(local_appdata) / "FlowCue" / "runtime"
        candidates.extend([
            runtime_base / "ffmpeg" / "bin",
            runtime_base / "ffmpeg",
            runtime_base / "videokit" / "vendor" / "windows" / "ffmpeg" / "bin",
            runtime_base / "videokit" / "vendor" / "ffmpeg" / "bin",
        ])

        # 3. Frozen PyInstaller bundle or FlowCue project vendor folder
        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).resolve().parent
            candidates.extend([
                base_dir / "vendor" / "ffmpeg" / "bin",
                base_dir / "vendor" / "windows" / "ffmpeg" / "bin",
                base_dir / "ffmpeg" / "bin",
                base_dir,
            ])
        code_root = Path(__file__).resolve().parent.parent
        candidates.extend([
            code_root / "vendor" / "ffmpeg" / "bin",
            code_root / "vendor" / "windows" / "ffmpeg" / "bin",
            # VideoKit shared vendor binary path on developer's machine
            Path(r"D:\Antigravity\videokit\vendor\windows\ffmpeg\bin"),
            code_root.parent.parent / "videokit" / "vendor" / "windows" / "ffmpeg" / "bin",
        ])
        return candidates

    @classmethod
    def get_ffmpeg_path(cls) -> str:
        """Returns the path to ffmpeg executable."""
        if cls._ffmpeg_path_cache and Path(cls._ffmpeg_path_cache).exists():
            return cls._ffmpeg_path_cache

        exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        for d in cls._candidate_dirs():
            cand = d / exe_name
            if cand.is_file():
                cls._ffmpeg_path_cache = str(cand)
                return cls._ffmpeg_path_cache

        which_res = shutil.which("ffmpeg")
        if which_res:
            cls._ffmpeg_path_cache = which_res
            return cls._ffmpeg_path_cache

        return "ffmpeg"

    @classmethod
    def get_ffprobe_path(cls) -> str:
        """Returns the path to ffprobe executable."""
        if cls._ffprobe_path_cache and Path(cls._ffprobe_path_cache).exists():
            return cls._ffprobe_path_cache

        exe_name = "ffprobe.exe" if sys.platform == "win32" else "ffprobe"
        for d in cls._candidate_dirs():
            cand = d / exe_name
            if cand.is_file():
                cls._ffprobe_path_cache = str(cand)
                return cls._ffprobe_path_cache

        which_res = shutil.which("ffprobe")
        if which_res:
            cls._ffprobe_path_cache = which_res
            return cls._ffprobe_path_cache

        return "ffprobe"

    @classmethod
    def is_available(cls) -> bool:
        """Returns True if ffmpeg is available and runnable."""
        ffmpeg_bin = cls.get_ffmpeg_path()
        try:
            res = subprocess.run(
                [ffmpeg_bin, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                creationflags=_SUBPROCESS_FLAGS,
            )
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def is_ffprobe_available(cls) -> bool:
        """Returns True if ffprobe is available and runnable."""
        ffprobe_bin = cls.get_ffprobe_path()
        try:
            res = subprocess.run(
                [ffprobe_bin, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                creationflags=_SUBPROCESS_FLAGS,
            )
            return res.returncode == 0
        except Exception:
            return False

    @classmethod
    def get_media_info(cls, media_path) -> dict:
        """Probes video/audio duration, width, height, fps, and audio presence.

        Returns:
            dict: {
                "duration": float,
                "width": int,
                "height": int,
                "fps": float,
                "has_audio": bool
            }
        """
        media_path = Path(media_path)
        info = {
            "duration": 0.0,
            "width": 1080,
            "height": 1920,
            "fps": 30.0,
            "has_audio": True,
        }
        if not media_path.exists():
            return info

        ffprobe_bin = cls.get_ffprobe_path()
        try:
            cmd = [
                ffprobe_bin,
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(media_path),
            ]
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=15,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if res.returncode == 0 and res.stdout:
                data = json.loads(res.stdout.decode("utf-8", errors="replace"))
                fmt = data.get("format", {})
                dur = float(fmt.get("duration", 0.0) or 0.0)
                if dur > 0:
                    info["duration"] = dur

                streams = data.get("streams", [])
                has_audio = False
                for st in streams:
                    codec_type = st.get("codec_type", "")
                    if codec_type == "video":
                        w = int(st.get("width", 0) or 0)
                        h = int(st.get("height", 0) or 0)
                        if w > 0 and h > 0:
                            info["width"] = w
                            info["height"] = h
                        if info["duration"] <= 0:
                            st_dur = float(st.get("duration", 0.0) or 0.0)
                            if st_dur > 0:
                                info["duration"] = st_dur
                        r_fps = st.get("r_frame_rate", "30/1")
                        if "/" in str(r_fps):
                            num, den = str(r_fps).split("/", 1)
                            if float(den or 0) > 0:
                                fps_val = float(num) / float(den)
                                if 1.0 <= fps_val <= 120.0:
                                    info["fps"] = round(fps_val, 3)
                    elif codec_type == "audio":
                        has_audio = True
                info["has_audio"] = has_audio
                if info["duration"] > 0:
                    return info
        except Exception:
            pass

        # Fallback to OpenCV if ffprobe failed
        try:
            import cv2
            cap = cv2.VideoCapture(str(media_path))
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1080)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1920)
                if fps > 0 and frame_count > 0:
                    info["duration"] = round(frame_count / fps, 3)
                    info["fps"] = round(fps, 3)
                if w > 0 and h > 0:
                    info["width"] = w
                    info["height"] = h
            cap.release()
        except Exception:
            pass

        return info

    @classmethod
    def get_media_duration(cls, media_path) -> float:
        """Returns media duration in seconds."""
        return cls.get_media_info(media_path).get("duration", 0.0)

    @classmethod
    def extract_fast_audio_for_asr(cls, video_path, temp_dir=None) -> str:
        """Extracts a lightweight 16kHz mono MP3 (48kbps) from a video file for ultra-fast ASR upload.
        A 10-second 10MB .mp4 becomes a ~55KB .mp3 in ~0.08 seconds!
        Falls back to original video_path if ffmpeg fails.

        Returns:
            str: Path to the extracted temporary audio file (or original video_path on failure).
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return str(video_path)

        # If already a small audio file, return directly
        if video_path.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg") and video_path.stat().st_size < 1024 * 1024:
            return str(video_path)

        if temp_dir is None:
            temp_dir = Path(tempfile.gettempdir()) / "flowcue_asr_audio"
        else:
            temp_dir = Path(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        stat = video_path.stat()
        key = f"{video_path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}"
        digest = hashlib.md5(key.encode("utf-8", errors="ignore")).hexdigest()[:12]
        out_mp3 = temp_dir / f"{video_path.stem}_{digest}.mp3"

        if out_mp3.exists() and out_mp3.stat().st_size > 256:
            return str(out_mp3)

        # Write to a unique temporary file first and atomically move it into place, so that
        # concurrent workers (multi-task / multi-segment parallel verification) never read a
        # half-written audio file or collide on the same output filename.
        unique_tag = f"{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:6]}"
        tmp_mp3 = temp_dir / f"{video_path.stem}_{digest}.part{unique_tag}.mp3"

        ffmpeg_bin = cls.get_ffmpeg_path()
        cmd = [
            ffmpeg_bin,
            "-y", "-v", "error",
            "-i", str(video_path),
            "-map", "0:a:0?",
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-b:a", "48k",
            str(tmp_mp3),
        ]
        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if res.returncode == 0 and tmp_mp3.exists() and tmp_mp3.stat().st_size > 256:
                if cls._atomic_move(tmp_mp3, out_mp3):
                    return str(out_mp3)
        except Exception:
            pass
        finally:
            cls._safe_unlink(tmp_mp3)

        # Fallback: try PCM 16kHz wav if libmp3lame is unavailable
        out_wav = temp_dir / f"{video_path.stem}_{digest}.wav"
        if out_wav.exists() and out_wav.stat().st_size > 256:
            return str(out_wav)
        tmp_wav = temp_dir / f"{video_path.stem}_{digest}.part{unique_tag}.wav"
        try:
            cmd_wav = [
                ffmpeg_bin,
                "-y", "-v", "error",
                "-i", str(video_path),
                "-map", "0:a:0?",
                "-vn",
                "-ac", "1",
                "-ar", "16000",
                "-c:a", "pcm_s16le",
                str(tmp_wav),
            ]
            res2 = subprocess.run(
                cmd_wav,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                creationflags=_SUBPROCESS_FLAGS,
            )
            if res2.returncode == 0 and tmp_wav.exists() and tmp_wav.stat().st_size > 256:
                if cls._atomic_move(tmp_wav, out_wav):
                    return str(out_wav)
        except Exception:
            pass
        finally:
            cls._safe_unlink(tmp_wav)

        return str(video_path)

    @staticmethod
    def _atomic_move(src: Path, dst: Path) -> bool:
        """Atomically replaces dst with src. Returns True on success (or if another worker
        already produced a valid dst in the meantime)."""
        try:
            os.replace(str(src), str(dst))
            return True
        except Exception:
            try:
                return dst.exists() and dst.stat().st_size > 256
            except Exception:
                return False

    @staticmethod
    def _safe_unlink(path: Path):
        try:
            if path and Path(path).exists():
                Path(path).unlink()
        except Exception:
            pass

    @staticmethod
    def run_cancellable(cmd, timeout: float = 600, is_cancelled_cb=None, poll_interval: float = 0.3):
        """Runs a subprocess (e.g. ffmpeg) that can be terminated when `is_cancelled_cb()` returns True.

        Each call spawns an independent process (no shared state), so it is safe to call from
        multiple worker threads in parallel.

        Returns:
            tuple: (returncode: int, stdout: bytes, stderr: bytes, cancelled: bool)
                   returncode is -1 on timeout / cancellation / launch failure.
        """
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=_SUBPROCESS_FLAGS,
            )
        except Exception as e:
            return -1, b"", str(e).encode("utf-8", errors="replace"), False

        start = time.monotonic()
        out_chunks, err_chunks = b"", b""
        while True:
            try:
                out, err = proc.communicate(timeout=poll_interval)
                out_chunks += out or b""
                err_chunks += err or b""
                return proc.returncode, out_chunks, err_chunks, False
            except subprocess.TimeoutExpired:
                cancelled = bool(callable(is_cancelled_cb) and is_cancelled_cb())
                timed_out = (time.monotonic() - start) > float(timeout or 600)
                if cancelled or timed_out:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        out, err = proc.communicate(timeout=5)
                        out_chunks += out or b""
                        err_chunks += err or b""
                    except Exception:
                        pass
                    msg = b"cancelled" if cancelled else b"timeout"
                    return -1, out_chunks, (err_chunks + b"\n" + msg), cancelled
            except Exception as e:
                try:
                    proc.kill()
                except Exception:
                    pass
                return -1, out_chunks, str(e).encode("utf-8", errors="replace"), False
