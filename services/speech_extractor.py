# -*- coding: utf-8 -*-
"""
High-speed speech extraction & breath-trimming service for FlowCue.
Upgraded with VideoKit's high-concurrency pipeline:
1. FFmpeg 16kHz mono audio extraction before upload (~100x smaller payload)
2. Local sidecar transcription cache (_auto_edit/<stem>_transcription.json)
3. Fast 0.6s polling with HTTP connection pooling (requests.Session)
4. Word-level timestamp extraction (Gladia utterances.words / ElevenLabs words)
5. Automatic breath/silence trimming (前留白 pad_before / 后留白 pad_after)
6. Multi-threaded concurrent batch extraction with thread-safe multi-key rotation
7. ApiKeyPool: multiple API keys in parallel, ≤ 3 concurrent requests per key, automatic
   failover (401/429 → key disabled / cooled down, segment retried on another key)
"""
import json
import time
import difflib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests
from PyQt6.QtCore import QThread, pyqtSignal

from services.ffmpeg_helper import FFmpegHelper


# Serializes ProjectModel.save() calls issued from concurrent verification worker threads
_PROJECT_SAVE_LOCK = threading.RLock()


def _shutdown_executor(executor):
    """Shuts down a ThreadPoolExecutor, cancelling queued (not yet started) futures.
    Running futures finish quickly because they poll the worker's cancel flag."""
    try:
        executor.shutdown(wait=True, cancel_futures=True)
    except TypeError:  # Python < 3.9
        executor.shutdown(wait=True)


def compute_concurrency_plan(num_keys: int, parallel_tasks: int, parallel_segments: int,
                             per_key_limit: int = 3, max_tasks: int = 4, max_segments: int = 40) -> dict:
    """Computes the effective verification concurrency, capped by the number of API keys.

    Theoretical max = parallel_tasks * parallel_segments (≤ 4 * 40 = 160).
    Actual max      = min(theoretical, num_keys * per_key_limit)  (each key ≤ 3 concurrent requests).

    When keys are insufficient the parallelism is automatically reduced: the number of parallel
    tasks is kept (unless it alone exceeds the cap) and the per-task segment parallelism shrinks
    so that tasks * segments ≈ cap. The ApiKeyPool still strictly enforces the cap at runtime.

    Returns:
        dict: {
            "num_keys", "per_key_limit", "key_capacity", "requested_tasks", "requested_segments",
            "requested_total", "effective_total", "tasks", "segments", "adjusted", "note"
        }
    """
    try:
        n_keys = max(0, int(num_keys or 0))
    except (TypeError, ValueError):
        n_keys = 0
    per_key = max(1, int(per_key_limit or 3))
    req_tasks = max(1, min(int(max_tasks or 4), int(parallel_tasks or 1)))
    req_segs = max(1, min(int(max_segments or 40), int(parallel_segments or 1)))
    requested = req_tasks * req_segs
    cap = n_keys * per_key

    if n_keys <= 0:
        return {
            "num_keys": 0,
            "per_key_limit": per_key,
            "key_capacity": 0,
            "requested_tasks": req_tasks,
            "requested_segments": req_segs,
            "requested_total": requested,
            "effective_total": 0,
            "tasks": req_tasks,
            "segments": 1,
            "adjusted": True,
            "note": "⚠️ 未检测到可用 API Key：仅能读取本地缓存结果，新的片段将无法核对",
        }

    effective = min(requested, cap)
    if effective < requested:
        eff_tasks = max(1, min(req_tasks, effective))
        eff_segs = max(1, min(req_segs, -(-effective // eff_tasks)))  # ceil division
        note = (
            f"检测到 {n_keys} 个 Key，每个 Key 最多 {per_key} 个并发请求，最多并行 {cap} 个请求；"
            f"已自动调整为：任务并行 {eff_tasks} × 分段并行 {eff_segs}（实际同时请求 ≤ {effective}，"
            f"原设置 {req_tasks} × {req_segs} = {requested}）"
        )
        adjusted = True
    else:
        eff_tasks, eff_segs = req_tasks, req_segs
        note = (
            f"检测到 {n_keys} 个 Key（最多并行 {cap} 个请求），"
            f"当前：任务并行 {eff_tasks} × 分段并行 {eff_segs} = {requested} 个并发请求"
        )
        adjusted = False

    return {
        "num_keys": n_keys,
        "per_key_limit": per_key,
        "key_capacity": cap,
        "requested_tasks": req_tasks,
        "requested_segments": req_segs,
        "requested_total": requested,
        "effective_total": effective,
        "tasks": eff_tasks,
        "segments": eff_segs,
        "adjusted": adjusted,
        "note": note,
    }


class ApiKeyPool:
    """Thread-safe API key pool limiting concurrent requests per key (default ≤ 3 per Gladia key).

    - `acquire()` blocks until a key slot is free and returns the least-loaded healthy key
      (round-robin among equally loaded keys); returns None when cancelled or when every key
      has been disabled (invalid / quota exhausted).
    - `release(key, outcome)` frees the slot and records the outcome:
        "ok"      → resets the key's failure strikes
        "auth"    → key disabled for the rest of this pool's lifetime (401/402/403, invalid key)
        "rate"    → key cooled down temporarily (429 / concurrency / quota), escalating per strike
        "network" / "fatal" → key unaffected
    """

    DEFAULT_PER_KEY_LIMIT = 3
    RATE_LIMIT_COOLDOWN_SECONDS = 15.0
    MAX_RATE_STRIKES = 4
    LONG_COOLDOWN_SECONDS = 300.0

    def __init__(self, keys, per_key_limit: int = DEFAULT_PER_KEY_LIMIT):
        uniq = []
        for k in (keys or []):
            k = str(k or "").strip()
            if k and k not in uniq:
                uniq.append(k)
        self.keys = uniq
        self.per_key_limit = max(1, int(per_key_limit or self.DEFAULT_PER_KEY_LIMIT))
        self._cond = threading.Condition(threading.Lock())
        self._in_use = {k: 0 for k in self.keys}
        self._cooldown_until = {k: 0.0 for k in self.keys}
        self._strikes = {k: 0 for k in self.keys}
        self._disabled = {}
        self._rr = 0
        self._peak_in_use = 0
        self._total_in_use = 0

    # ── Introspection ───────────────────────────────────
    @property
    def capacity(self) -> int:
        return len(self.keys) * self.per_key_limit

    @property
    def peak_concurrency(self) -> int:
        return self._peak_in_use

    def in_use_total(self) -> int:
        with self._cond:
            return self._total_in_use

    def in_use_of(self, key) -> int:
        with self._cond:
            return self._in_use.get(key, 0)

    def is_disabled(self, key) -> bool:
        with self._cond:
            return key in self._disabled

    def usable_key_count(self) -> int:
        with self._cond:
            return sum(1 for k in self.keys if k not in self._disabled)

    def all_disabled(self) -> bool:
        with self._cond:
            return self._all_disabled_locked()

    def _all_disabled_locked(self) -> bool:
        return bool(self.keys) and all(k in self._disabled for k in self.keys)

    def status_text(self) -> str:
        with self._cond:
            now = time.monotonic()
            disabled = len(self._disabled)
            cooling = sum(1 for k in self.keys if k not in self._disabled and self._cooldown_until[k] > now)
            return f"Key 池: 共 {len(self.keys)} 个 / 失效 {disabled} / 冷却中 {cooling} / 占用 {self._total_in_use}"

    # ── Acquire / Release ───────────────────────────────
    def _pick_locked(self, exclude) -> str | None:
        n = len(self.keys)
        if n == 0:
            return None
        now = time.monotonic()
        exclude = exclude or set()
        best = None
        best_excluded = None
        for off in range(n):
            i = (self._rr + off) % n
            k = self.keys[i]
            if k in self._disabled or self._cooldown_until[k] > now:
                continue
            load = self._in_use[k]
            if load >= self.per_key_limit:
                continue
            if k in exclude:
                if best_excluded is None or load < best_excluded[2]:
                    best_excluded = (i, k, load)
                continue
            if best is None or load < best[2]:
                best = (i, k, load)
        if best is None and best_excluded is not None:
            # Only fall back to an already-tried key when every healthy key has been tried
            healthy = [k for k in self.keys if k not in self._disabled]
            if all(k in exclude for k in healthy):
                best = best_excluded
        if best is None:
            return None
        self._rr = (best[0] + 1) % n
        return best[1]

    def acquire(self, exclude=None, cancel_check=None, timeout: float | None = None) -> str | None:
        deadline = (time.monotonic() + float(timeout)) if timeout else None
        with self._cond:
            while True:
                if callable(cancel_check) and cancel_check():
                    return None
                if not self.keys or self._all_disabled_locked():
                    return None
                key = self._pick_locked(exclude)
                if key is not None:
                    self._in_use[key] += 1
                    self._total_in_use += 1
                    self._peak_in_use = max(self._peak_in_use, self._total_in_use)
                    return key
                if deadline is not None and time.monotonic() >= deadline:
                    return None
                self._cond.wait(0.25)

    def release(self, key, outcome: str = "ok"):
        with self._cond:
            if key in self._in_use and self._in_use[key] > 0:
                self._in_use[key] -= 1
                self._total_in_use = max(0, self._total_in_use - 1)
            if key in self._strikes:
                if outcome == "ok":
                    self._strikes[key] = 0
                elif outcome == "auth":
                    self._disabled[key] = "auth"
                elif outcome == "rate":
                    self._strikes[key] += 1
                    strikes = self._strikes[key]
                    if strikes >= self.MAX_RATE_STRIKES:
                        cooldown = self.LONG_COOLDOWN_SECONDS
                    else:
                        cooldown = self.RATE_LIMIT_COOLDOWN_SECONDS * strikes
                    self._cooldown_until[key] = time.monotonic() + cooldown
            self._cond.notify_all()


class SpeechExtractor:
    """Handles speech-to-text extraction and word-level timestamp alignment."""

    # Gladia API endpoints (v2)
    GLADIA_UPLOAD_URL = "https://api.gladia.io/v2/upload"
    GLADIA_TRANSCRIPTION_URL = "https://api.gladia.io/v2/pre-recorded"

    # ElevenLabs API endpoint
    ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"

    # Fast polling config (learned from VideoKit: 0.6s interval instead of 3.0s)
    MAX_POLL_ATTEMPTS = 200
    POLL_INTERVAL_SECONDS = 0.6

    # Default breath padding (seconds)
    DEFAULT_PAD_BEFORE = 0.10
    DEFAULT_PAD_AFTER = 0.15

    _key_lock = threading.Lock()

    # ═══════════════════════════════════════════════════════
    # Local Sidecar Cache (_auto_edit/<stem>_transcription.json)
    # ═══════════════════════════════════════════════════════
    @staticmethod
    def _get_cache_path(video_path: Path) -> Path:
        cache_dir = video_path.parent / "_auto_edit"
        return cache_dir / f"{video_path.stem}_transcription.json"

    @staticmethod
    def load_cached_transcription(video_path) -> dict | None:
        """Loads cached transcription if video file size and mtime match."""
        try:
            vp = Path(video_path)
            if not vp.exists():
                return None
            cache_file = SpeechExtractor._get_cache_path(vp)
            if not cache_file.exists():
                return None
            stat = vp.stat()
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if (
                data.get("file_size") == stat.st_size
                and abs(float(data.get("file_mtime", 0)) - stat.st_mtime) < 2.0
                and data.get("text")
            ):
                return {
                    "success": True,
                    "text": data.get("text", ""),
                    "words": data.get("words", []),
                    "video_duration": float(data.get("video_duration", 0.0) or 0.0),
                    "error": "",
                    "from_cache": True,
                }
        except Exception:
            pass
        return None

    @staticmethod
    def save_cached_transcription(video_path, text: str, words: list, video_duration: float = 0.0, engine: str = "gladia"):
        """Saves transcription + word timestamps to local sidecar JSON cache."""
        try:
            vp = Path(video_path)
            if not vp.exists() or not text:
                return
            cache_file = SpeechExtractor._get_cache_path(vp)
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            stat = vp.stat()
            payload = {
                "version": 1,
                "video_name": vp.name,
                "file_size": stat.st_size,
                "file_mtime": stat.st_mtime,
                "engine": engine,
                "video_duration": video_duration,
                "text": text,
                "words": words or [],
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def invalidate_cache(video_path):
        """Removes cached transcription for a video file (e.g. when replaced)."""
        try:
            vp = Path(video_path)
            cache_file = SpeechExtractor._get_cache_path(vp)
            if cache_file.exists():
                cache_file.unlink()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════
    # Gladia v2 Fast Extraction (with FFmpeg 16kHz audio + word timings)
    # ═══════════════════════════════════════════════════════
    @staticmethod
    def extract_with_gladia(video_path, api_key, language="es", use_cache=True,
                            prepared_audio_path=None, video_duration=None, cancel_check=None):
        """Extracts speech text and word-level timestamps from a video file using Gladia API v2.

        Optional args (used by the parallel key-pool pipeline):
            prepared_audio_path: already-extracted lightweight audio file to upload (skips FFmpeg).
            video_duration: already-probed video duration in seconds (skips ffprobe).
            cancel_check: callable returning True to abort polling early.

        Returns:
            dict: {
                "success": bool,
                "text": str,
                "words": list[{"word": str, "start": float, "end": float}],
                "video_duration": float,
                "error": str
            }
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return {"success": False, "text": "", "words": [], "video_duration": 0.0, "error": f"文件不存在: {video_path}"}

        if use_cache:
            cached = SpeechExtractor.load_cached_transcription(video_path)
            if cached:
                if cached.get("video_duration", 0.0) <= 0:
                    cached["video_duration"] = FFmpegHelper.get_media_duration(video_path)
                return cached

        # Probe video duration and extract lightweight 16kHz mono audio for instant upload
        if video_duration is None or float(video_duration or 0.0) <= 0:
            video_duration = FFmpegHelper.get_media_duration(video_path)
        if prepared_audio_path and Path(prepared_audio_path).exists():
            upload_file_path = Path(prepared_audio_path)
        else:
            upload_file_path = Path(FFmpegHelper.extract_fast_audio_for_asr(video_path))
        mime_type = "audio/mpeg" if upload_file_path.suffix.lower() == ".mp3" else (
            "audio/wav" if upload_file_path.suffix.lower() == ".wav" else "video/mp4"
        )

        headers = {
            "x-gladia-key": api_key,
        }

        session = requests.Session()
        try:
            # Step 1: Upload lightweight audio file
            with open(upload_file_path, "rb") as f:
                upload_response = session.post(
                    SpeechExtractor.GLADIA_UPLOAD_URL,
                    headers=headers,
                    files={"audio": (upload_file_path.name, f, mime_type)},
                    timeout=90,
                )

            if upload_response.status_code not in (200, 201):
                error_detail = ""
                try:
                    error_detail = upload_response.json().get("message", upload_response.text[:200])
                except Exception:
                    error_detail = upload_response.text[:200]
                return {
                    "success": False, "text": "", "words": [], "video_duration": video_duration,
                    "error": f"Gladia 上传失败 (HTTP {upload_response.status_code}): {error_detail}"
                }

            upload_data = upload_response.json()
            audio_url = upload_data.get("audio_url")
            if not audio_url:
                return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "Gladia 上传返回结果中缺少 audio_url"}

            # Step 2: Submit transcription
            transcription_payload = {
                "audio_url": audio_url,
            }
            if language and language != "auto":
                transcription_payload["language"] = language

            trans_response = session.post(
                SpeechExtractor.GLADIA_TRANSCRIPTION_URL,
                headers={**headers, "Content-Type": "application/json"},
                json=transcription_payload,
                timeout=30,
            )

            if trans_response.status_code not in (200, 201):
                error_detail = ""
                try:
                    error_detail = trans_response.json().get("message", trans_response.text[:200])
                except Exception:
                    error_detail = trans_response.text[:200]
                return {
                    "success": False, "text": "", "words": [], "video_duration": video_duration,
                    "error": f"Gladia 转录请求失败 (HTTP {trans_response.status_code}): {error_detail}"
                }

            trans_data = trans_response.json()
            result_url = trans_data.get("result_url")
            if not result_url:
                return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "Gladia 转录返回结果中缺少 result_url"}

            # Step 3: Fast polling (0.6s interval)
            for attempt in range(SpeechExtractor.MAX_POLL_ATTEMPTS):
                if callable(cancel_check) and cancel_check():
                    return {
                        "success": False, "text": "", "words": [], "video_duration": video_duration,
                        "error": "已取消", "cancelled": True,
                    }
                time.sleep(SpeechExtractor.POLL_INTERVAL_SECONDS)

                poll_response = session.get(
                    result_url,
                    headers=headers,
                    timeout=25,
                )

                if poll_response.status_code != 200:
                    continue

                poll_data = poll_response.json()
                status = poll_data.get("status", "")

                if status == "done":
                    result = poll_data.get("result", {})
                    transcription = result.get("transcription", {})
                    utterances = transcription.get("utterances", []) or []
                    full_transcript = transcription.get("full_transcript", "")

                    if not full_transcript and utterances:
                        full_transcript = " ".join(
                            u.get("transcript", "") for u in utterances if u.get("transcript")
                        )

                    # Extract word-level timestamps from utterances
                    words = []
                    for u in utterances:
                        u_words = u.get("words", []) or []
                        if u_words:
                            for w in u_words:
                                w_text = str(w.get("word", "")).strip()
                                w_start = float(w.get("start", u.get("start", 0.0)) or 0.0)
                                w_end = float(w.get("end", u.get("end", w_start)) or w_start)
                                if w_text:
                                    words.append({
                                        "word": w_text,
                                        "start": round(w_start, 3),
                                        "end": round(max(w_start, w_end), 3),
                                    })
                        else:
                            # Fallback if utterance has no word array: split transcript evenly across utterance
                            u_text = str(u.get("transcript", "")).strip()
                            u_start = float(u.get("start", 0.0) or 0.0)
                            u_end = float(u.get("end", u_start) or u_start)
                            tokens = [t for t in u_text.split() if t]
                            if tokens:
                                span = max(0.05, u_end - u_start)
                                step = span / len(tokens)
                                for idx_t, tok in enumerate(tokens):
                                    words.append({
                                        "word": tok,
                                        "start": round(u_start + idx_t * step, 3),
                                        "end": round(u_start + (idx_t + 1) * step, 3),
                                    })

                    clean_text = full_transcript.strip()
                    if clean_text:
                        SpeechExtractor.save_cached_transcription(
                            video_path, clean_text, words, video_duration, engine="gladia"
                        )

                    return {
                        "success": True,
                        "text": clean_text,
                        "words": words,
                        "video_duration": video_duration,
                        "error": "",
                        "from_cache": False,
                    }

                elif status == "error":
                    error_msg = poll_data.get("error", {}).get("message", "未知错误")
                    return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": f"Gladia 转录失败: {error_msg}"}

            return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "Gladia 转录超时 (轮询次数已达上限)"}

        except requests.exceptions.Timeout:
            return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "Gladia 请求超时"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "Gladia 网络连接失败，请检查网络"}
        except Exception as e:
            return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": f"Gladia 提取异常: {str(e)}"}
        finally:
            session.close()

    # ═══════════════════════════════════════════════════════
    # ElevenLabs Scribe Fast Extraction (with FFmpeg 16kHz audio + word timings)
    # ═══════════════════════════════════════════════════════
    @staticmethod
    def extract_with_elevenlabs(video_path, api_key, language="es", use_cache=True,
                                prepared_audio_path=None, video_duration=None, cancel_check=None):
        """Extracts speech text and word-level timestamps using ElevenLabs Speech-to-Text API.

        Optional args `prepared_audio_path` / `video_duration` skip FFmpeg/ffprobe when already
        prepared by the parallel key-pool pipeline (`cancel_check` is accepted for API symmetry).

        Returns:
            dict: {
                "success": bool,
                "text": str,
                "words": list[{"word": str, "start": float, "end": float}],
                "video_duration": float,
                "error": str
            }
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return {"success": False, "text": "", "words": [], "video_duration": 0.0, "error": f"文件不存在: {video_path}"}

        if use_cache:
            cached = SpeechExtractor.load_cached_transcription(video_path)
            if cached:
                if cached.get("video_duration", 0.0) <= 0:
                    cached["video_duration"] = FFmpegHelper.get_media_duration(video_path)
                return cached

        if video_duration is None or float(video_duration or 0.0) <= 0:
            video_duration = FFmpegHelper.get_media_duration(video_path)
        if prepared_audio_path and Path(prepared_audio_path).exists():
            upload_file_path = Path(prepared_audio_path)
        else:
            upload_file_path = Path(FFmpegHelper.extract_fast_audio_for_asr(video_path))
        mime_type = "audio/mpeg" if upload_file_path.suffix.lower() == ".mp3" else (
            "audio/wav" if upload_file_path.suffix.lower() == ".wav" else "video/mp4"
        )

        headers = {
            "xi-api-key": api_key,
        }

        try:
            with open(upload_file_path, "rb") as f:
                files = {
                    "file": (upload_file_path.name, f, mime_type),
                }
                data = {
                    "model_id": "scribe_v1",
                    "language_code": language,
                    "timestamps_granularity": "word",
                }

                response = requests.post(
                    SpeechExtractor.ELEVENLABS_STT_URL,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=120,
                )

            if response.status_code == 200:
                result = response.json()
                text = result.get("text", "") or result.get("transcription", "")
                raw_words = result.get("words", []) or []
                words = []
                for w in raw_words:
                    w_type = w.get("type", "word")
                    if w_type not in ("word", "punctuation", None):
                        continue
                    w_text = str(w.get("text", w.get("word", ""))).strip()
                    if not w_text:
                        continue
                    w_start = float(w.get("start", 0.0) or 0.0)
                    w_end = float(w.get("end", w_start) or w_start)
                    words.append({
                        "word": w_text,
                        "start": round(w_start, 3),
                        "end": round(max(w_start, w_end), 3),
                    })

                clean_text = text.strip()
                if clean_text:
                    SpeechExtractor.save_cached_transcription(
                        video_path, clean_text, words, video_duration, engine="elevenlabs"
                    )

                return {
                    "success": True,
                    "text": clean_text,
                    "words": words,
                    "video_duration": video_duration,
                    "error": "",
                    "from_cache": False,
                }

            elif response.status_code == 401:
                return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "ElevenLabs API Key 无效或已过期"}
            elif response.status_code == 429:
                return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "ElevenLabs API 请求频率超限，将尝试下一个 Key"}
            else:
                error_detail = ""
                try:
                    error_detail = response.json().get("detail", {})
                    if isinstance(error_detail, dict):
                        error_detail = error_detail.get("message", str(error_detail))
                    elif isinstance(error_detail, list):
                        error_detail = str(error_detail)
                except Exception:
                    error_detail = response.text[:200]
                return {
                    "success": False, "text": "", "words": [], "video_duration": video_duration,
                    "error": f"ElevenLabs 请求失败 (HTTP {response.status_code}): {error_detail}"
                }

        except requests.exceptions.Timeout:
            return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "ElevenLabs 请求超时"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": "ElevenLabs 网络连接失败，请检查网络"}
        except Exception as e:
            return {"success": False, "text": "", "words": [], "video_duration": video_duration, "error": f"ElevenLabs 提取异常: {str(e)}"}

    # ═══════════════════════════════════════════════════════
    # Breath Trimming (自动切气口: 前留白 pad_before / 后留白 pad_after)
    # ═══════════════════════════════════════════════════════
    @staticmethod
    def compute_breath_cut_range(
        words: list,
        original_text: str,
        video_duration: float,
        pad_before: float = DEFAULT_PAD_BEFORE,
        pad_after: float = DEFAULT_PAD_AFTER,
    ) -> dict:
        """Computes automatic breath-trimmed [cut_in, cut_out] for a known segment script.

        Because FlowCue already knows the exact target subtitle for each clip,
        we do not need cross-clip blind matching. Instead:
        1. Filter valid word timestamps within [0, video_duration].
        2. Align the recognized words with the known `original_text` tokens using SequenceMatcher
           so any accidental head/tail noise or coughs outside the sentence are excluded.
        3. Apply `pad_before` (前留白) and `pad_after` (后留白) around `[speech_start, speech_end]`.

        Returns:
            dict: {
                "speech_start": float,
                "speech_end": float,
                "cut_in": float,
                "cut_out": float,
                "trimmed_duration": float,
            }
        """
        dur = float(video_duration or 0.0)
        valid_words = []
        for w in (words or []):
            w_str = str(w.get("word", "")).strip()
            w_norm = SpeechExtractor._normalize_word_for_compare(w_str)
            if not w_norm:
                continue
            st = float(w.get("start", 0.0) or 0.0)
            ed = float(w.get("end", st) or st)
            if ed < st:
                ed = st
            valid_words.append({"word": w_str, "norm": w_norm, "start": st, "end": ed})

        if not valid_words:
            end_val = dur if dur > 0 else 0.0
            return {
                "speech_start": 0.0,
                "speech_end": round(end_val, 3),
                "cut_in": 0.0,
                "cut_out": round(end_val, 3),
                "trimmed_duration": round(end_val, 3),
            }

        # Default to first and last recognized word in the clip
        start_word_idx = 0
        end_word_idx = len(valid_words) - 1

        # Refine with known original_text if available (strips leading/trailing noise words)
        if original_text:
            orig_tokens = SpeechExtractor.collapse_and_normalize_tokens(original_text)
            orig_norms = [t["norm"] for t in orig_tokens if t["norm"]]
            ext_norms = [w["norm"] for w in valid_words]
            if orig_norms and ext_norms:
                sm = difflib.SequenceMatcher(None, orig_norms, ext_norms)
                matching_blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
                if matching_blocks:
                    first_match = matching_blocks[0]
                    last_match = matching_blocks[-1]
                    # If the first match starts near the beginning of original_text, use its start in ext_norms
                    if first_match.a == 0 and first_match.b > 0:
                        start_word_idx = first_match.b
                    # If the last match ends at the end of original_text, use its end in ext_norms
                    if (last_match.a + last_match.size) == len(orig_norms):
                        end_word_idx = min(len(valid_words) - 1, last_match.b + last_match.size - 1)

        speech_start = valid_words[start_word_idx]["start"]
        speech_end = valid_words[end_word_idx]["end"]
        if speech_end <= speech_start:
            speech_start = valid_words[0]["start"]
            speech_end = valid_words[-1]["end"]

        cut_in = max(0.0, speech_start - max(0.0, float(pad_before)))
        raw_cut_out = speech_end + max(0.0, float(pad_after))
        if dur > 0:
            cut_out = min(dur, raw_cut_out)
        else:
            cut_out = raw_cut_out

        # Safety guard: ensure at least 0.25s clip duration
        if cut_out <= cut_in + 0.25:
            cut_in = 0.0
            cut_out = dur if dur > 0 else max(speech_end, 1.0)

        return {
            "speech_start": round(speech_start, 3),
            "speech_end": round(speech_end, 3),
            "cut_in": round(cut_in, 3),
            "cut_out": round(cut_out, 3),
            "trimmed_duration": round(max(0.0, cut_out - cut_in), 3),
        }

    # ═══════════════════════════════════════════════════════
    # Text Normalization & Spanish/English Number Equivalence
    # ═══════════════════════════════════════════════════════
    _NUMBER_UNITS_AND_TEENS = {
        "cero": 0, "zero": 0,
        "uno": 1, "one": 1, "primero": 1, "primer": 1, "primera": 1, "first": 1,
        "dos": 2, "two": 2, "segundo": 2, "segunda": 2, "second": 2,
        "tres": 3, "three": 3, "tercero": 3, "tercer": 3, "tercera": 3, "third": 3,
        "cuatro": 4, "four": 4, "cuarto": 4, "cuarta": 4, "fourth": 4,
        "cinco": 5, "five": 5, "quinto": 5, "quinta": 5, "fifth": 5,
        "seis": 6, "six": 6, "sexto": 6, "sexta": 6, "sixth": 6,
        "siete": 7, "seven": 7, "septimo": 7, "septima": 7, "setimo": 7, "setima": 7, "seventh": 7,
        "ocho": 8, "eight": 8, "octavo": 8, "octava": 8, "eighth": 8,
        "nueve": 9, "nine": 9, "noveno": 9, "novena": 9, "ninth": 9,
        "diez": 10, "ten": 10, "decimo": 10, "decima": 10, "tenth": 10,
        "once": 11, "eleven": 11, "undecimo": 11, "decimoprimero": 11,
        "doce": 12, "twelve": 12, "duodecimo": 12, "decimosegundo": 12,
        "trece": 13, "thirteen": 13,
        "catorce": 14, "fourteen": 14,
        "quince": 15, "fifteen": 15,
        "dieciseis": 16, "sixteen": 16,
        "diecisiete": 17, "seventeen": 17,
        "dieciocho": 18, "eighteen": 18,
        "diecinueve": 19, "nineteen": 19,
        "veinte": 20, "twenty": 20, "vigesimo": 20, "vigesima": 20,
        "veintiuno": 21, "veintiun": 21, "veintiuna": 21, "twentyone": 21,
        "veintidos": 22, "twentytwo": 22,
        "veintitres": 23, "twentythree": 23,
        "veinticuatro": 24, "twentyfour": 24,
        "veinticinco": 25, "twentyfive": 25,
        "veintiseis": 26, "twentysix": 26,
        "veintisiete": 27, "twentyseven": 27,
        "veintiocho": 28, "twentyeight": 28,
        "veintinueve": 29, "twentynine": 29,
    }

    _NUMBER_TENS = {
        "treinta": 30, "thirty": 30, "trigesimo": 30,
        "cuarenta": 40, "forty": 40, "cuadragesimo": 40,
        "cincuenta": 50, "fifty": 50, "quincuagesimo": 50,
        "sesenta": 60, "sixty": 60, "sexagesimo": 60,
        "setenta": 70, "seventy": 70, "septuagesimo": 70,
        "ochenta": 80, "eighty": 80, "octogesimo": 80,
        "noventa": 90, "ninety": 90, "nonagesimo": 90,
    }

    _NUMBER_HUNDREDS = {
        "cien": 100, "ciento": 100, "hundred": 100, "centesimo": 100,
        "doscientos": 200, "doscientas": 200,
        "trescientos": 300, "trescientas": 300,
        "cuatrocientos": 400, "cuatrocientas": 400,
        "quinientos": 500, "quinientas": 500,
        "seiscientos": 600, "seiscientas": 600,
        "setecientos": 700, "setecientas": 700,
        "ochocientos": 800, "ochocientas": 800,
        "novecientos": 900, "novecientas": 900,
    }

    _NUMBER_MULTIPLIERS = {
        "mil": 1000, "thousand": 1000, "milesimo": 1000,
        "millon": 1000000, "millones": 1000000, "million": 1000000,
    }

    @staticmethod
    def _clean_word_for_display(word: str) -> str:
        """Strips leading/trailing punctuation while keeping original characters/accents for display."""
        import re
        import unicodedata
        w = str(word or "").lower().strip()
        def _is_word_char(c):
            return c != '_' and (bool(re.match(r'\w', c)) or unicodedata.category(c) in ('Mn', 'Mc', 'Me'))
        start = 0
        end = len(w)
        while start < end and not _is_word_char(w[start]):
            start += 1
        while end > start and not _is_word_char(w[end - 1]):
            end -= 1
        return w[start:end]

    @staticmethod
    def _strip_accents_and_punct(word: str) -> str:
        """Strips punctuation, case, and accents without number conversion."""
        import re
        import unicodedata
        w = str(word or "").lower().strip()
        w = "".join(
            c for c in w
            if (c != '_' and (re.match(r'\w', c) or unicodedata.category(c) in ('Mn', 'Mc', 'Me')))
        )
        accent_map = str.maketrans({
            'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u',
            'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        })
        return w.translate(accent_map)

    @staticmethod
    def _normalize_word_for_compare(word):
        """Internal helper to clean a single word for matching (ignores punctuation, case, accents,
        and normalizes Spanish/English number words like 'catorce' -> '14' so 'catorce' == '14').
        Preserves Unicode combining marks (e.g. Devanagari vowel signs for Nepali).
        Does NOT modify the original text data.
        """
        import re
        cleaned = SpeechExtractor._strip_accents_and_punct(word)
        if not cleaned:
            return ""
        # Strip Spanish/English ordinal suffixes attached to digits (e.g. 14º, 1ro, 2da, 3er, 4th)
        m_ord = re.match(r'^(\d+)(?:ro|ra|do|da|to|ta|mo|ma|vo|va|no|na|er|st|nd|rd|th|o|a)$', cleaned)
        if m_ord:
            return str(int(m_ord.group(1)))
        if cleaned.isdigit():
            return str(int(cleaned))
        if cleaned in SpeechExtractor._NUMBER_UNITS_AND_TEENS:
            return str(SpeechExtractor._NUMBER_UNITS_AND_TEENS[cleaned])
        if cleaned in SpeechExtractor._NUMBER_TENS:
            return str(SpeechExtractor._NUMBER_TENS[cleaned])
        if cleaned in SpeechExtractor._NUMBER_HUNDREDS:
            return str(SpeechExtractor._NUMBER_HUNDREDS[cleaned])
        if cleaned in SpeechExtractor._NUMBER_MULTIPLIERS:
            return str(SpeechExtractor._NUMBER_MULTIPLIERS[cleaned])
        return cleaned

    @classmethod
    def _try_parse_compound_number(cls, raw_tokens: list, start_idx: int):
        """Attempts to parse a Spanish/English number phrase starting at `start_idx` in `raw_tokens`.
        Supports single-word numbers ('catorce' -> 14, '14' -> 14) as well as multi-word Spanish
        numbers ('treinta y cinco' -> 35, 'ciento veinte' -> 120, 'dos mil veinticuatro' -> 2024).

        Returns:
            tuple: (numeric_str, consumed_count) or (None, 0) if not a number.
        """
        n = len(raw_tokens)
        if start_idx >= n:
            return None, 0

        first_clean = cls._strip_accents_and_punct(raw_tokens[start_idx])
        if not first_clean:
            return None, 0

        # Direct digits (e.g. "14", "2024")
        if first_clean.isdigit():
            return str(int(first_clean)), 1

        # Helper for unit value (including 'un'/'una' when inside a compound number)
        def _unit_val(w_clean, allow_un_una=False):
            if allow_un_una and w_clean in ("un", "una"):
                return 1
            return cls._NUMBER_UNITS_AND_TEENS.get(w_clean)

        # Parse a sub-1000 group starting at `idx`: [hundreds] + [tens (+ 'y' + unit 1..9) | unit_or_teen 1..29]
        def _parse_under_1000(idx, allow_leading_un=False):
            if idx >= n:
                return None, 0
            w0 = cls._strip_accents_and_punct(raw_tokens[idx])
            total_sub = 0
            consumed = 0

            # 1. Optional hundreds
            if w0 in cls._NUMBER_HUNDREDS:
                total_sub += cls._NUMBER_HUNDREDS[w0]
                consumed += 1
                idx += 1
                if idx >= n:
                    return total_sub, consumed
                w0 = cls._strip_accents_and_punct(raw_tokens[idx])

            # 2. Optional tens (30..90) + optional ('y' + 1..9)
            if w0 in cls._NUMBER_TENS:
                tens_v = cls._NUMBER_TENS[w0]
                total_sub += tens_v
                consumed += 1
                idx += 1
                if idx + 1 < n and cls._strip_accents_and_punct(raw_tokens[idx]) == "y":
                    w_unit = cls._strip_accents_and_punct(raw_tokens[idx + 1])
                    u_v = _unit_val(w_unit, allow_un_una=True)
                    if u_v is not None and 1 <= u_v <= 9:
                        total_sub += u_v
                        consumed += 2
                        idx += 2
                return total_sub, consumed

            # 3. Or "diez y seis..nueve" / "veinte y uno..nueve"
            if w0 in ("diez", "veinte"):
                base_v = 10 if w0 == "diez" else 20
                if idx + 1 < n and cls._strip_accents_and_punct(raw_tokens[idx + 1]) == "y" and idx + 2 < n:
                    w_unit = cls._strip_accents_and_punct(raw_tokens[idx + 2])
                    u_v = _unit_val(w_unit, allow_un_una=True)
                    if u_v is not None and 1 <= u_v <= 9:
                        total_sub += base_v + u_v
                        consumed += 3
                        return total_sub, consumed

            # 4. Or single unit/teen (0..29)
            u_v = _unit_val(w0, allow_un_una=(allow_leading_un or consumed > 0))
            if u_v is not None:
                # Only allow 0 ("cero") if it's the sole word
                if u_v == 0 and consumed > 0:
                    return total_sub, consumed
                total_sub += u_v
                consumed += 1
                return total_sub, consumed

            if consumed > 0:
                return total_sub, consumed
            return None, 0

        # Check if starts with "un mil" / "mil" or "<under_1000> mil"
        sub_val, sub_cnt = _parse_under_1000(start_idx, allow_leading_un=False)
        if sub_cnt == 0 and first_clean in ("un", "una") and start_idx + 1 < n:
            next_clean = cls._strip_accents_and_punct(raw_tokens[start_idx + 1])
            if next_clean in cls._NUMBER_MULTIPLIERS:
                sub_val, sub_cnt = 1, 1

        idx_curr = start_idx + sub_cnt
        total_val = 0
        total_cnt = 0

        if sub_cnt > 0:
            # Check if followed by "mil" / "millon"
            if idx_curr < n:
                mult_word = cls._strip_accents_and_punct(raw_tokens[idx_curr])
                if mult_word == "mil":
                    total_val += sub_val * 1000
                    total_cnt += sub_cnt + 1
                    idx_curr += 1
                    rem_val, rem_cnt = _parse_under_1000(idx_curr, allow_leading_un=True)
                    if rem_cnt > 0 and rem_val is not None:
                        total_val += rem_val
                        total_cnt += rem_cnt
                    return str(total_val), total_cnt
            return str(sub_val), sub_cnt

        # Starts directly with "mil" (e.g. "mil novecientos ochenta y cuatro")
        if first_clean == "mil":
            total_val = 1000
            total_cnt = 1
            rem_val, rem_cnt = _parse_under_1000(start_idx + 1, allow_leading_un=True)
            if rem_cnt > 0 and rem_val is not None:
                total_val += rem_val
                total_cnt += rem_cnt
            return str(total_val), total_cnt

        return None, 0

    @classmethod
    def collapse_and_normalize_tokens(cls, text: str) -> list:
        """Splits `text` into tokens for comparison and HTML diffing, collapsing multi-word
        Spanish/English numbers (e.g. 'treinta y cinco' -> norm '35') and normalizing single
        number words (e.g. 'catorce' -> norm '14') so that 'catorce' and '14' match 100% as equal.

        Returns:
            list[dict]: [{"display": str, "norm": str}, ...]
        """
        if not text:
            return []
        raw_words = [cls._clean_word_for_display(w) for w in str(text).split()]
        raw_words = [w for w in raw_words if w]
        if not raw_words:
            return []

        tokens = []
        i = 0
        n = len(raw_words)
        while i < n:
            num_str, consumed = cls._try_parse_compound_number(raw_words, i)
            if consumed > 0 and num_str is not None:
                disp = " ".join(raw_words[i : i + consumed])
                tokens.append({"display": disp, "norm": num_str})
                i += consumed
            else:
                w = raw_words[i]
                norm = cls._normalize_word_for_compare(w)
                if norm:
                    tokens.append({"display": w, "norm": norm})
                i += 1
        return tokens

    @staticmethod
    def calculate_similarity(text1, text2):
        """Calculates the word-level similarity ratio between two texts in-memory,
        ignoring punctuation, case, accents, and treating Spanish/English number words
        and digits as equivalent (e.g. 'catorce' == '14', 'treinta y cinco' == '35').
        Does not alter any original text data.

        Returns:
            float: Similarity score as a percentage (0-100).
        """
        if not text1 and not text2:
            return 100.0
        if not text1 or not text2:
            return 0.0

        tokens1 = SpeechExtractor.collapse_and_normalize_tokens(text1)
        tokens2 = SpeechExtractor.collapse_and_normalize_tokens(text2)
        words1 = [t["norm"] for t in tokens1 if t["norm"]]
        words2 = [t["norm"] for t in tokens2 if t["norm"]]

        if not words1 and not words2:
            return 100.0
        if not words1 or not words2:
            return 0.0

        ratio = difflib.SequenceMatcher(None, words1, words2).ratio()
        return round(ratio * 100, 1)

    @staticmethod
    def extract_with_retry(video_path, engine, config_manager, language="es", max_retries=3, use_cache=True):
        """Extracts text + word timings with thread-safe automatic key rotation on failure.

        Returns:
            dict: {
                "success": bool,
                "text": str,
                "words": list,
                "video_duration": float,
                "error": str,
                "key_used": str,
                "from_cache": bool
            }
        """
        if use_cache:
            cached = SpeechExtractor.load_cached_transcription(video_path)
            if cached:
                if cached.get("video_duration", 0.0) <= 0:
                    cached["video_duration"] = FFmpegHelper.get_media_duration(video_path)
                cached["key_used"] = "cache"
                return cached

        if engine == "gladia":
            key_count = len(config_manager.gladia_api_keys)
            get_key_fn = config_manager.get_next_gladia_key
            extract_fn = SpeechExtractor.extract_with_gladia
        elif engine == "elevenlabs":
            key_count = len(config_manager.elevenlabs_api_keys)
            get_key_fn = config_manager.get_next_elevenlabs_key
            extract_fn = SpeechExtractor.extract_with_elevenlabs
        else:
            return {"success": False, "text": "", "words": [], "video_duration": 0.0, "error": f"不支持的引擎: {engine}", "key_used": ""}

        if key_count == 0:
            engine_name = "Gladia" if engine == "gladia" else "ElevenLabs"
            return {
                "success": False, "text": "", "words": [], "video_duration": 0.0,
                "error": f"未配置 {engine_name} API Key，请在规则设置中添加",
                "key_used": ""
            }

        retries = max(1, min(max_retries, key_count))
        last_error = ""

        for _ in range(retries):
            with SpeechExtractor._key_lock:
                api_key = get_key_fn()
            if not api_key:
                continue

            result = extract_fn(video_path, api_key, language, use_cache=use_cache)

            if result["success"]:
                result["key_used"] = api_key[:8] + "..."
                return result

            last_error = result.get("error", "未知错误")

            # If it's a rate limit, concurrency, or auth error, rotate to next key
            err_lower = last_error.lower()
            if any(k in last_error for k in ("超限", "无效", "过期", "429", "401", "403")) or any(
                k in err_lower for k in ("rate limit", "quota", "concurren", "limit")
            ):
                continue
            else:
                break

        return {"success": False, "text": "", "words": [], "video_duration": 0.0, "error": last_error, "key_used": ""}

    # ═══════════════════════════════════════════════════════
    # Multi-key parallel pipeline (ApiKeyPool: ≤ 3 concurrent requests per key)
    # ═══════════════════════════════════════════════════════
    @staticmethod
    def classify_api_error(error_text: str) -> str:
        """Classifies an extraction error string into "auth" | "rate" | "network" | "fatal"."""
        e = str(error_text or "")
        low = e.lower()
        if "轮询次数已达上限" in e:
            return "fatal"
        if any(s in e for s in ("HTTP 401", "HTTP 402", "HTTP 403", "无效", "过期")) or any(
            s in low for s in ("invalid api key", "invalid key", "unauthorized", "forbidden", "payment required")
        ):
            return "auth"
        if any(s in e for s in ("HTTP 429", "超限")) or any(
            s in low for s in ("rate limit", "quota", "concurren", "too many", "exceeded", "limit reached")
        ):
            return "rate"
        if any(s in e for s in ("超时", "网络连接失败", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")) or any(
            s in low for s in ("timeout", "timed out", "connection")
        ):
            return "network"
        return "fatal"

    @staticmethod
    def create_key_pool(config_manager, engine: str = "gladia") -> "ApiKeyPool":
        """Builds an ApiKeyPool from the configured keys of the given engine."""
        keys = []
        if config_manager is not None:
            if hasattr(config_manager, "get_speech_keys"):
                keys = config_manager.get_speech_keys(engine)
            elif engine == "elevenlabs":
                keys = list(getattr(config_manager, "elevenlabs_api_keys", []) or [])
            else:
                keys = list(getattr(config_manager, "gladia_api_keys", []) or [])
        per_key = int(getattr(config_manager, "SPEECH_MAX_CONCURRENT_PER_KEY", ApiKeyPool.DEFAULT_PER_KEY_LIMIT) or 3)
        return ApiKeyPool(keys, per_key_limit=per_key)

    @staticmethod
    def extract_with_pool(video_path, engine, key_pool, language="es", use_cache=True,
                          cancel_check=None, max_attempts=None):
        """Extracts text + word timings using a shared ApiKeyPool (thread-safe, multi-key parallel).

        - Local cache hits never consume a key slot.
        - FFmpeg audio extraction / ffprobe happen BEFORE taking a key slot, so slots are only
          held during network I/O.
        - Auth failures (401/402/403) disable the key; rate/quota failures (429...) cool it down;
          the segment is retried on another key. Network errors are retried up to 2 times.

        Returns:
            dict: same shape as extract_with_retry (+ "cancelled": bool on cancellation)
        """
        def _fail(msg, dur=0.0, cancelled=False):
            return {
                "success": False, "text": "", "words": [], "video_duration": dur,
                "error": msg, "key_used": "", "cancelled": cancelled,
            }

        def _is_cancelled():
            return bool(callable(cancel_check) and cancel_check())

        if use_cache:
            cached = SpeechExtractor.load_cached_transcription(video_path)
            if cached:
                if cached.get("video_duration", 0.0) <= 0:
                    cached["video_duration"] = FFmpegHelper.get_media_duration(video_path)
                cached["key_used"] = "cache"
                return cached

        if engine == "gladia":
            extract_fn = SpeechExtractor.extract_with_gladia
            engine_name = "Gladia"
        elif engine == "elevenlabs":
            extract_fn = SpeechExtractor.extract_with_elevenlabs
            engine_name = "ElevenLabs"
        else:
            return _fail(f"不支持的引擎: {engine}")

        if key_pool is None or not getattr(key_pool, "keys", None):
            return _fail(f"未配置 {engine_name} API Key，请在规则设置中添加")

        vp = Path(video_path)
        if not vp.exists():
            return _fail(f"文件不存在: {vp}")
        if _is_cancelled():
            return _fail("已取消", cancelled=True)

        video_duration = FFmpegHelper.get_media_duration(vp)
        audio_path = FFmpegHelper.extract_fast_audio_for_asr(vp)

        attempts = int(max_attempts or max(3, min(8, len(key_pool.keys) + 2)))
        tried = set()
        last_error = ""
        network_retries = 0

        for _ in range(attempts):
            if _is_cancelled():
                return _fail("已取消", video_duration, cancelled=True)
            api_key = key_pool.acquire(exclude=tried, cancel_check=cancel_check)
            if api_key is None:
                if _is_cancelled():
                    return _fail("已取消", video_duration, cancelled=True)
                last_error = (
                    f"所有 {engine_name} API Key 均不可用（无效 / 额度用尽）"
                    + (f"；最后错误: {last_error}" if last_error else "")
                )
                break

            try:
                result = extract_fn(
                    vp, api_key, language, use_cache=False,
                    prepared_audio_path=audio_path, video_duration=video_duration,
                    cancel_check=cancel_check,
                )
            except Exception as exc:
                result = {"success": False, "text": "", "words": [], "video_duration": video_duration,
                          "error": f"{engine_name} 提取异常: {exc}"}

            if result.get("success"):
                key_pool.release(api_key, "ok")
                result["key_used"] = api_key[:8] + "..."
                return result

            if result.get("cancelled"):
                key_pool.release(api_key, "fatal")
                result.setdefault("key_used", "")
                return result

            last_error = result.get("error", "未知错误")
            outcome = SpeechExtractor.classify_api_error(last_error)
            key_pool.release(api_key, outcome)

            if outcome in ("auth", "rate"):
                tried.add(api_key)
                continue
            if outcome == "network" and network_retries < 2:
                network_retries += 1
                continue
            break

        return _fail(last_error or "未知错误", video_duration)


class ExtractionWorker(QThread):
    """High-concurrency background worker thread for batch speech extraction & breath trimming.

    Signals:
        progress(int, int, str): (completed_count, total, status_message)
        segment_done(int, str, float): (segment_index, extracted_text, similarity_score)
        segment_detail_done(int, dict): (segment_index, full_detail_dict)
        finished(int, int, list): (success_count, total_count, errors_list)
    """

    progress = pyqtSignal(int, int, str)
    segment_done = pyqtSignal(int, str, float)
    segment_detail_done = pyqtSignal(int, dict)
    finished = pyqtSignal(int, int, list)

    def __init__(
        self,
        segments_to_process,
        engine,
        config_manager,
        language="es",
        pad_before=SpeechExtractor.DEFAULT_PAD_BEFORE,
        pad_after=SpeechExtractor.DEFAULT_PAD_AFTER,
        use_cache=True,
        max_workers=8,
        parent=None,
        key_pool=None,
    ):
        super().__init__(parent)
        self.segments_to_process = segments_to_process
        self.engine = engine
        self.config_manager = config_manager
        self.language = language
        self.pad_before = pad_before
        self.pad_after = pad_after
        self.use_cache = use_cache
        # Desired segment parallelism (分段并行数, 1..40); actual value is capped by keys * 3 in run()
        self.max_workers = max(1, min(40, int(max_workers or 8)))
        self.key_pool = key_pool
        self.concurrency_plan = None
        self._cancelled = False

    def _is_cancelled(self) -> bool:
        return bool(self._cancelled or self.isInterruptionRequested())

    def cancel(self):
        """Requests cancellation of the extraction process."""
        self._cancelled = True
        self.requestInterruption()

    def stop(self):
        """Stops the worker thread safely."""
        self.cancel()
        if self.isRunning():
            self.quit()
            self.wait(2500)

    def _process_single_segment(self, seg_info: dict) -> dict:
        seg_idx = seg_info["segment_index"]
        video_path = seg_info["video_path"]
        original_text = seg_info.get("original_text", "")
        force_no_cache = seg_info.get("force_refresh", False) or (not self.use_cache)

        if self._cancelled or self.isInterruptionRequested():
            return {"cancelled": True, "segment_index": seg_idx}

        result = SpeechExtractor.extract_with_pool(
            video_path,
            self.engine,
            self.key_pool,
            self.language,
            use_cache=(not force_no_cache),
            cancel_check=self._is_cancelled,
        )

        if result.get("cancelled"):
            return {"cancelled": True, "segment_index": seg_idx}

        if not result.get("success"):
            return {
                "cancelled": False,
                "success": False,
                "segment_index": seg_idx,
                "error": result.get("error", "未知错误"),
            }

        extracted_text = result.get("text", "")
        words = result.get("words", [])
        video_duration = float(result.get("video_duration", 0.0) or 0.0)
        if video_duration <= 0:
            video_duration = FFmpegHelper.get_media_duration(video_path)

        similarity = SpeechExtractor.calculate_similarity(original_text, extracted_text)
        cut_info = SpeechExtractor.compute_breath_cut_range(
            words=words,
            original_text=original_text,
            video_duration=video_duration,
            pad_before=self.pad_before,
            pad_after=self.pad_after,
        )

        return {
            "cancelled": False,
            "success": True,
            "segment_index": seg_idx,
            "extracted_text": extracted_text,
            "similarity": similarity,
            "words": words,
            "video_duration": round(video_duration, 3),
            "speech_start": cut_info["speech_start"],
            "speech_end": cut_info["speech_end"],
            "cut_in": cut_info["cut_in"],
            "cut_out": cut_info["cut_out"],
            "trimmed_duration": cut_info["trimmed_duration"],
            "from_cache": bool(result.get("from_cache", False)),
        }

    def run(self):
        """Main concurrent extraction loop."""
        total = len(self.segments_to_process)
        if total == 0:
            self.finished.emit(0, 0, [])
            return

        success_count = 0
        completed_count = 0
        errors = []

        self.config_manager.reset_key_rotation()

        # Multi-key pool: each key ≤ 3 concurrent requests → segment parallelism capped by keys * 3
        if self.key_pool is None:
            self.key_pool = SpeechExtractor.create_key_pool(self.config_manager, self.engine)
        plan = compute_concurrency_plan(
            len(self.key_pool.keys), 1, self.max_workers,
            per_key_limit=self.key_pool.per_key_limit, max_tasks=1, max_segments=40,
        )
        self.concurrency_plan = plan
        workers = max(1, min(total, plan["effective_total"] or 1))

        self.progress.emit(0, total, f"⚡ 正在高速并发核对 ({workers} 线程并发) · {plan['note']}")

        executor = ThreadPoolExecutor(max_workers=workers)
        try:
            future_to_seg = {
                executor.submit(self._process_single_segment, seg_info): seg_info
                for seg_info in self.segments_to_process
            }

            for future in as_completed(future_to_seg):
                if self._cancelled or self.isInterruptionRequested():
                    self.progress.emit(completed_count, total, "⛔ 已取消提取")
                    for f in future_to_seg:
                        f.cancel()
                    break

                seg_info = future_to_seg[future]
                seg_idx = seg_info["segment_index"]
                completed_count += 1

                try:
                    res = future.result()
                except Exception as exc:
                    res = {
                        "cancelled": False,
                        "success": False,
                        "segment_index": seg_idx,
                        "error": str(exc),
                    }

                if res.get("cancelled"):
                    continue

                if res.get("success"):
                    extracted_text = res["extracted_text"]
                    similarity = res["similarity"]
                    cache_tag = " [秒读缓存]" if res.get("from_cache") else ""
                    self.progress.emit(
                        completed_count,
                        total,
                        f"⚡ 已完成 {completed_count}/{total} (第 {seg_idx + 1:02d} 段 {similarity:.0f}%{cache_tag})",
                    )
                    self.segment_detail_done.emit(seg_idx, res)
                    self.segment_done.emit(seg_idx, extracted_text, similarity)
                    success_count += 1
                else:
                    err_str = res.get("error", "未知错误")
                    error_msg = f"片段 {seg_idx + 1}: {err_str}"
                    errors.append(error_msg)
                    self.progress.emit(
                        completed_count,
                        total,
                        f"⚠️ 第 {seg_idx + 1:02d} 段失败 ({completed_count}/{total})",
                    )
                    self.segment_done.emit(seg_idx, "", 0.0)
        finally:
            _shutdown_executor(executor)

        self.finished.emit(success_count, total, errors)


class BatchMultiProjectVerifyWorker(QThread):
    """Parallel multi-project batch subtitle verification worker.

    Concurrency model:
        - 任务并行数 (max_parallel_tasks, 1..4): projects verified at the same time
        - 分段并行数 (max_parallel_segments, 1..40): segments per project verified concurrently
        - Theoretical max = tasks * segments (≤ 160); actual concurrency is capped by the shared
          ApiKeyPool (each API key ≤ 3 concurrent requests → total ≤ num_keys * 3). When keys are
          insufficient the parallelism is automatically reduced (see `concurrency_note`).

    Signals:
        task_started(str): project_id
        task_progress(str, int, int, str): (project_id, completed_segs, total_segs, status_text)
        task_finished(str, dict): (project_id, result_summary_dict)
        overall_progress(int, int, str): (completed_tasks, total_tasks, status_text)
        all_finished(int, int, list): (success_tasks_count, total_tasks_count, all_results_list)
        concurrency_note(str): human-readable note describing the effective concurrency / auto-adjustment
    """

    task_started = pyqtSignal(str)
    task_progress = pyqtSignal(str, int, int, str)
    task_finished = pyqtSignal(str, dict)
    overall_progress = pyqtSignal(int, int, str)
    all_finished = pyqtSignal(int, int, list)
    concurrency_note = pyqtSignal(str)

    MAX_PARALLEL_TASKS_LIMIT = 4
    MAX_PARALLEL_SEGMENTS_LIMIT = 40
    INCREMENTAL_SAVE_EVERY = 10

    def __init__(
        self,
        projects_list: list,
        engine: str,
        config_manager,
        base_storage_path=None,
        max_parallel_tasks: int = 4,
        pad_before: float = SpeechExtractor.DEFAULT_PAD_BEFORE,
        pad_after: float = SpeechExtractor.DEFAULT_PAD_AFTER,
        skip_already_checked: bool = True,
        force_no_cache: bool = False,
        parent=None,
        max_parallel_segments: int = None,
        key_pool=None,
    ):
        super().__init__(parent)
        self.projects_list = list(projects_list or [])
        self.engine = engine
        self.config_manager = config_manager
        self.base_storage_path = Path(base_storage_path) if base_storage_path else None
        # Strictly clamp parallel task concurrency to [1, 4]
        self.max_parallel_tasks = max(
            1, min(self.MAX_PARALLEL_TASKS_LIMIT, int(max_parallel_tasks or 4))
        )
        if max_parallel_segments is None:
            max_parallel_segments = getattr(config_manager, "verify_parallel_segments", 10)
        # Strictly clamp per-task segment concurrency to [1, 40]
        self.max_parallel_segments = max(
            1, min(self.MAX_PARALLEL_SEGMENTS_LIMIT, int(max_parallel_segments or 10))
        )
        self.pad_before = float(pad_before)
        self.pad_after = float(pad_after)
        self.skip_already_checked = bool(skip_already_checked)
        self.force_no_cache = bool(force_no_cache)
        self.key_pool = key_pool
        self.concurrency_plan = None
        self._seg_workers = 1
        self._cancelled = False

    def _is_cancelled(self) -> bool:
        return bool(self._cancelled or self.isInterruptionRequested())

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def stop(self):
        self.cancel()
        if self.isRunning():
            self.quit()
            self.wait(3000)

    def _verify_single_project(self, proj_item: dict) -> dict:
        import datetime
        from models.project_model import ProjectModel
        from services.video_checker import VideoChecker

        proj_id = str(proj_item.get("id") or Path(proj_item["path"]).name)
        proj_path = Path(proj_item["path"])

        if self._cancelled or self.isInterruptionRequested():
            return {"project_id": proj_id, "cancelled": True, "success": False}

        self.task_started.emit(proj_id)

        try:
            model = ProjectModel(proj_path)
            base_dir = self.base_storage_path or proj_path.parent
            report = VideoChecker.check_project_videos(model, proj_path, base_storage_path=base_dir)

            # Check if any newly generated replacement videos exist in pre_relocate_dir
            pre_dir = report.get("pre_relocate_dir", "")
            post_dir = Path(report.get("post_relocate_dir", str(proj_path / "downloads" / "videos")))
            replaced_indices = set()
            if pre_dir and Path(pre_dir).exists():
                import shutil
                post_dir.mkdir(parents=True, exist_ok=True)
                for i, d in enumerate(report.get("segments_detail", [])):
                    exp_name = d.get("download_name", f"{i + 1:02d}.mp4")
                    cand = Path(pre_dir) / exp_name
                    if cand.exists():
                        target = post_dir / exp_name
                        try:
                            if target.exists():
                                target.unlink()
                            shutil.move(str(cand), str(target))
                            SpeechExtractor.invalidate_cache(target)
                            replaced_indices.add(i)
                        except Exception:
                            pass

            # Auto-relocate any pending videos in Flow/ download folder
            if report.get("pending_count", 0) > 0:
                VideoChecker.relocate_found_videos(report)
            if replaced_indices or report.get("pending_count", 0) > 0:
                report = VideoChecker.check_project_videos(model, proj_path, base_storage_path=base_dir)

            segments = model.spanish_segments
            details = report.get("segments_detail", [])
            total_segs = len(segments)
            missing_cnt = report.get("missing_count", 0)

            if total_segs == 0:
                summary = {
                    "project_id": proj_id,
                    "cancelled": False,
                    "success": True,
                    "total_segments": 0,
                    "verified_count": 0,
                    "auto_checked_count": 0,
                    "flagged_count": 0,
                    "missing_count": 0,
                    "errors": [],
                }
                self.task_finished.emit(proj_id, summary)
                return summary

            language = getattr(self.config_manager, "speech_language", "es")
            to_extract = []
            already_verified = 0
            modified = False

            for i, detail in enumerate(details):
                if i >= len(segments):
                    break
                seg = segments[i]
                orig_text = seg.get("text", "")
                existing_ext = seg.get("extracted_text", "")

                # Always refresh similarity for already-extracted segments (e.g. Spanish number words fix)
                if existing_ext and orig_text and i not in replaced_indices:
                    recalc_sim = SpeechExtractor.calculate_similarity(orig_text, existing_ext)
                    if abs(float(seg.get("similarity_score", 0.0) or 0.0) - recalc_sim) >= 0.1:
                        seg["similarity_score"] = recalc_sim
                        if recalc_sim >= 90:
                            seg["checked"] = True
                            seg["auto_checked"] = True
                            seg["mismatch_flagged"] = False
                        modified = True

                if not detail.get("found") or not detail.get("source_path"):
                    continue

                vp = str(detail["source_path"])
                if not Path(vp).exists():
                    continue

                if i in replaced_indices:
                    SpeechExtractor.invalidate_cache(vp)
                elif (
                    self.skip_already_checked
                    and not self.force_no_cache
                    and seg.get("checked", False)
                    and existing_ext
                ):
                    already_verified += 1
                    continue

                to_extract.append({
                    "segment_index": i,
                    "video_path": vp,
                    "original_text": orig_text,
                    "force_no_cache": (i in replaced_indices),
                })

            total_to_extract = len(to_extract)
            errors = []
            extracted_ok = 0

            if total_to_extract == 0:
                if modified:
                    with _PROJECT_SAVE_LOCK:
                        model.save()
                checked_now = sum(1 for s in segments if s.get("checked", False))
                flagged_now = sum(
                    1
                    for s in segments
                    if s.get("mismatch_flagged", False)
                    or (s.get("extracted_text") and 0 < float(s.get("similarity_score", 0) or 0) < 70)
                )
                self.task_progress.emit(
                    proj_id, total_segs, total_segs, f"✅ 已全部核对 ({checked_now}/{total_segs})"
                )
                summary = {
                    "project_id": proj_id,
                    "cancelled": False,
                    "success": True,
                    "total_segments": total_segs,
                    "verified_count": already_verified,
                    "auto_checked_count": checked_now,
                    "flagged_count": flagged_now,
                    "missing_count": missing_cnt,
                    "errors": [],
                }
                self.task_finished.emit(proj_id, summary)
                return summary

            self.task_progress.emit(
                proj_id, 0, total_to_extract, f"🔄 正在核对 (0/{total_to_extract})..."
            )

            # 分段并行数: per-task segment threads (actual API concurrency enforced by the shared key pool)
            intra_workers = max(1, min(total_to_extract, int(self._seg_workers or 1)))

            def _extract_seg_item(item):
                if self._is_cancelled():
                    return {"cancelled": True, "segment_index": item["segment_index"]}
                s_idx = item["segment_index"]
                v_path = item["video_path"]
                o_text = item["original_text"]
                res = SpeechExtractor.extract_with_pool(
                    v_path,
                    self.engine,
                    self.key_pool,
                    language=language,
                    use_cache=(not self.force_no_cache and not item.get("force_no_cache", False)),
                    cancel_check=self._is_cancelled,
                )
                if res.get("cancelled"):
                    return {"cancelled": True, "segment_index": s_idx}
                if not res.get("success"):
                    return {
                        "cancelled": False,
                        "success": False,
                        "segment_index": s_idx,
                        "error": res.get("error", "未知错误"),
                    }
                ext_txt = res.get("text", "")
                words = res.get("words", [])
                v_dur = float(res.get("video_duration", 0.0) or 0.0)
                if v_dur <= 0:
                    v_dur = FFmpegHelper.get_media_duration(v_path)
                sim = SpeechExtractor.calculate_similarity(o_text, ext_txt)
                cut_info = SpeechExtractor.compute_breath_cut_range(
                    words=words,
                    original_text=o_text,
                    video_duration=v_dur,
                    pad_before=self.pad_before,
                    pad_after=self.pad_after,
                )
                return {
                    "cancelled": False,
                    "success": True,
                    "segment_index": s_idx,
                    "extracted_text": ext_txt,
                    "similarity": sim,
                    "words": words,
                    "video_duration": round(v_dur, 3),
                    "cut_info": cut_info,
                }

            done_in_task = 0
            unsaved_results = 0
            seg_pool = ThreadPoolExecutor(max_workers=intra_workers)
            try:
                futs = {seg_pool.submit(_extract_seg_item, it): it for it in to_extract}
                for fut in as_completed(futs):
                    if self._cancelled or self.isInterruptionRequested():
                        for f in futs:
                            f.cancel()
                        break
                    done_in_task += 1
                    try:
                        s_res = fut.result()
                    except Exception as exc:
                        s_res = {
                            "cancelled": False,
                            "success": False,
                            "segment_index": futs[fut]["segment_index"],
                            "error": str(exc),
                        }
                    if s_res.get("cancelled"):
                        continue
                    s_idx = s_res["segment_index"]
                    if s_res.get("success") and s_idx < len(segments):
                        seg = segments[s_idx]
                        ext_txt = s_res["extracted_text"]
                        sim = s_res["similarity"]
                        c_info = s_res["cut_info"]

                        seg["extracted_text"] = ext_txt
                        seg["similarity_score"] = sim
                        seg["extraction_engine"] = self.engine
                        seg["extraction_time"] = datetime.datetime.now().isoformat()
                        seg["word_timings"] = s_res["words"]
                        seg["video_duration"] = s_res["video_duration"]
                        seg["speech_start"] = c_info["speech_start"]
                        seg["speech_end"] = c_info["speech_end"]
                        if not seg.get("manual_cut_adjusted", False):
                            seg["cut_in"] = c_info["cut_in"]
                            seg["cut_out"] = c_info["cut_out"]

                        if ext_txt:
                            if sim >= 90:
                                seg["checked"] = True
                                seg["auto_checked"] = True
                                seg["mismatch_flagged"] = False
                                seg["marked_for_deletion"] = False
                            elif sim < 70:
                                seg["checked"] = False
                                seg["mismatch_flagged"] = True
                            else:
                                seg["checked"] = False
                                seg["mismatch_flagged"] = False

                        extracted_ok += 1
                        modified = True
                        unsaved_results += 1
                        # Incremental, lock-serialized save so progress survives cancel / crash
                        if unsaved_results >= self.INCREMENTAL_SAVE_EVERY:
                            with _PROJECT_SAVE_LOCK:
                                model.save()
                            unsaved_results = 0
                        self.task_progress.emit(
                            proj_id,
                            done_in_task,
                            total_to_extract,
                            f"⚡ 已核对 {done_in_task}/{total_to_extract} (第 {s_idx + 1:02d} 段 {sim:.0f}%)",
                        )
                    else:
                        err_msg = f"第 {s_idx + 1:02d} 段: {s_res.get('error', '失败')}"
                        errors.append(err_msg)
                        self.task_progress.emit(
                            proj_id,
                            done_in_task,
                            total_to_extract,
                            f"⚠️ 第 {s_idx + 1:02d} 段失败 ({done_in_task}/{total_to_extract})",
                        )
            finally:
                _shutdown_executor(seg_pool)

            if modified:
                with _PROJECT_SAVE_LOCK:
                    model.save()

            checked_now = sum(1 for s in segments if s.get("checked", False))
            flagged_now = sum(
                1
                for s in segments
                if s.get("mismatch_flagged", False)
                or (s.get("extracted_text") and 0 < float(s.get("similarity_score", 0) or 0) < 70)
            )
            summary = {
                "project_id": proj_id,
                "cancelled": self._cancelled,
                "success": (len(errors) == 0 and not self._cancelled),
                "total_segments": total_segs,
                "verified_count": already_verified + extracted_ok,
                "newly_extracted": extracted_ok,
                "auto_checked_count": checked_now,
                "flagged_count": flagged_now,
                "missing_count": missing_cnt,
                "errors": errors,
            }
            self.task_finished.emit(proj_id, summary)
            return summary

        except Exception as exc:
            summary = {
                "project_id": proj_id,
                "cancelled": False,
                "success": False,
                "total_segments": 0,
                "verified_count": 0,
                "auto_checked_count": 0,
                "flagged_count": 0,
                "missing_count": 0,
                "errors": [str(exc)],
            }
            self.task_finished.emit(proj_id, summary)
            return summary

    def run(self):
        total_tasks = len(self.projects_list)
        if total_tasks == 0:
            self.all_finished.emit(0, 0, [])
            return

        self.config_manager.reset_key_rotation()

        # Shared multi-key pool across ALL parallel tasks: each key ≤ 3 concurrent requests
        if self.key_pool is None:
            self.key_pool = SpeechExtractor.create_key_pool(self.config_manager, self.engine)
        plan = compute_concurrency_plan(
            len(self.key_pool.keys),
            min(self.max_parallel_tasks, total_tasks),
            self.max_parallel_segments,
            per_key_limit=self.key_pool.per_key_limit,
            max_tasks=self.MAX_PARALLEL_TASKS_LIMIT,
            max_segments=self.MAX_PARALLEL_SEGMENTS_LIMIT,
        )
        self.concurrency_plan = plan
        self._seg_workers = max(1, int(plan["segments"]))
        workers = max(1, min(total_tasks, int(plan["tasks"])))
        self.concurrency_note.emit(plan["note"])
        self.overall_progress.emit(
            0, total_tasks,
            f"🚀 正在并列核对所有任务 (任务并行 {workers} × 分段并行 {self._seg_workers}) · {plan['note']}",
        )

        completed_tasks = 0
        success_tasks = 0
        all_results = []

        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            fut_to_proj = {
                pool.submit(self._verify_single_project, proj): proj
                for proj in self.projects_list
            }
            for fut in as_completed(fut_to_proj):
                if self._cancelled or self.isInterruptionRequested():
                    for f in fut_to_proj:
                        f.cancel()
                    break
                completed_tasks += 1
                try:
                    res = fut.result()
                except Exception as exc:
                    p_id = str(fut_to_proj[fut].get("id", "未知任务"))
                    res = {
                        "project_id": p_id,
                        "cancelled": False,
                        "success": False,
                        "errors": [str(exc)],
                    }
                all_results.append(res)
                if res.get("success"):
                    success_tasks += 1
                self.overall_progress.emit(
                    completed_tasks,
                    total_tasks,
                    f"📊 总任务进度: {completed_tasks}/{total_tasks} (已完成: {res.get('project_id', '')})",
                )
        finally:
            _shutdown_executor(pool)

        self.all_finished.emit(success_tasks, total_tasks, all_results)

