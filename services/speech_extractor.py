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
    def extract_with_gladia(video_path, api_key, language="es", use_cache=True):
        """Extracts speech text and word-level timestamps from a video file using Gladia API v2.

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
        video_duration = FFmpegHelper.get_media_duration(video_path)
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
    def extract_with_elevenlabs(video_path, api_key, language="es", use_cache=True):
        """Extracts speech text and word-level timestamps using ElevenLabs Speech-to-Text API.

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

        video_duration = FFmpegHelper.get_media_duration(video_path)
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
    ):
        super().__init__(parent)
        self.segments_to_process = segments_to_process
        self.engine = engine
        self.config_manager = config_manager
        self.language = language
        self.pad_before = pad_before
        self.pad_after = pad_after
        self.use_cache = use_cache
        self.max_workers = max(1, min(16, int(max_workers or 8)))
        self._cancelled = False

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

        result = SpeechExtractor.extract_with_retry(
            video_path,
            self.engine,
            self.config_manager,
            self.language,
            max_retries=4,
            use_cache=(not force_no_cache),
        )

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

        # Scale concurrency smartly based on key count (minimum 4 concurrent workers even with 1 key)
        if self.engine == "gladia":
            key_cnt = max(1, len(self.config_manager.gladia_api_keys))
        else:
            key_cnt = max(1, len(self.config_manager.elevenlabs_api_keys))
        workers = min(total, max(4, min(self.max_workers, key_cnt * 4)))

        self.progress.emit(0, total, f"⚡ 正在高速并发核对 ({workers} 线程并发)...")

        with ThreadPoolExecutor(max_workers=workers) as executor:
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

        self.finished.emit(success_count, total, errors)


class BatchMultiProjectVerifyWorker(QThread):
    """Parallel multi-project batch subtitle verification worker (up to 4 tasks in parallel).

    Signals:
        task_started(str): project_id
        task_progress(str, int, int, str): (project_id, completed_segs, total_segs, status_text)
        task_finished(str, dict): (project_id, result_summary_dict)
        overall_progress(int, int, str): (completed_tasks, total_tasks, status_text)
        all_finished(int, int, list): (success_tasks_count, total_tasks_count, all_results_list)
    """

    task_started = pyqtSignal(str)
    task_progress = pyqtSignal(str, int, int, str)
    task_finished = pyqtSignal(str, dict)
    overall_progress = pyqtSignal(int, int, str)
    all_finished = pyqtSignal(int, int, list)

    MAX_PARALLEL_TASKS_LIMIT = 4

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
        self.pad_before = float(pad_before)
        self.pad_after = float(pad_after)
        self.skip_already_checked = bool(skip_already_checked)
        self.force_no_cache = bool(force_no_cache)
        self._cancelled = False

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

            # Auto-relocate any pending videos in Flow/ download folder
            if report.get("pending_count", 0) > 0:
                VideoChecker.relocate_found_videos(report)
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
                if existing_ext and orig_text:
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

                if (
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
                })

            total_to_extract = len(to_extract)
            errors = []
            extracted_ok = 0

            if total_to_extract == 0:
                if modified:
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

            # Use 2 intra-task threads so 4 parallel tasks * 2 threads = up to 8 concurrent segment requests
            intra_workers = min(total_to_extract, 2)

            def _extract_seg_item(item):
                if self._cancelled or self.isInterruptionRequested():
                    return {"cancelled": True, "segment_index": item["segment_index"]}
                s_idx = item["segment_index"]
                v_path = item["video_path"]
                o_text = item["original_text"]
                res = SpeechExtractor.extract_with_retry(
                    v_path,
                    self.engine,
                    self.config_manager,
                    language=language,
                    max_retries=4,
                    use_cache=(not self.force_no_cache),
                )
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
            with ThreadPoolExecutor(max_workers=intra_workers) as seg_pool:
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

            if modified:
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
        workers = min(total_tasks, self.max_parallel_tasks)
        self.overall_progress.emit(0, total_tasks, f"🚀 正在并列核对所有任务 (并发任务数: {workers})...")

        completed_tasks = 0
        success_tasks = 0
        all_results = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
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

        self.all_finished.emit(success_tasks, total_tasks, all_results)

