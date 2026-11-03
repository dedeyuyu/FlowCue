# -*- coding: utf-8 -*-
"""
Video splicing, breath-trimmed clip caching, and synchronized SRT export service for FlowCue.
Implements VideoKit's SHA-256 per-clip cut cache + FFmpeg seamless concatenation +
anti-flicker SRT subtitle generation + Batch Reels project manifest output.
Supports both single-task splicing and multi-task batch splicing + one-click send to Batch Reels.
"""
import os
import sys
import json
import time
import uuid
import shutil
import hashlib
import tempfile
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from PyQt6.QtCore import QThread, pyqtSignal

from services.ffmpeg_helper import FFmpegHelper, _SUBPROCESS_FLAGS


class VideoSpliceService:
    """Trims video segments using [cut_in, cut_out], caches each trimmed clip by SHA-256,
    concatenates into a final MP4, and generates synchronized SRT subtitles.
    """

    @staticmethod
    def _format_srt_timestamp(ms: int) -> str:
        ms = max(0, int(ms))
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    @staticmethod
    def write_srt_file(srt_items: list, srt_path: Path):
        """Writes sorted, anti-flicker SRT cues to disk."""
        if not srt_items:
            return
        items = sorted(srt_items, key=lambda x: x["start_ms"])
        # Anti-flicker overlap elimination (learned from VideoKit autoEdit.js)
        for i in range(1, len(items)):
            if items[i]["start_ms"] < items[i - 1]["end_ms"]:
                items[i - 1]["end_ms"] = items[i]["start_ms"]
                if items[i - 1]["end_ms"] <= items[i - 1]["start_ms"]:
                    items[i - 1]["end_ms"] = items[i - 1]["start_ms"] + 50
                    items[i]["start_ms"] = items[i - 1]["end_ms"]
                    if items[i]["end_ms"] <= items[i]["start_ms"]:
                        items[i]["end_ms"] = items[i]["start_ms"] + 50

        lines = []
        for idx, cue in enumerate(items, start=1):
            start_str = VideoSpliceService._format_srt_timestamp(cue["start_ms"])
            end_str = VideoSpliceService._format_srt_timestamp(cue["end_ms"])
            text = str(cue.get("text", "")).strip()
            if not text:
                continue
            lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

        srt_path.parent.mkdir(parents=True, exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    @staticmethod
    def compute_clip_cache_signature(
        video_path: Path,
        cut_in: float,
        cut_out: float,
        target_width: int,
        target_height: int,
        fps: float,
    ) -> str:
        stat = video_path.stat()
        payload = {
            "v": 1,
            "path": str(video_path.resolve()),
            "size": stat.st_size,
            "mtime": int(stat.st_mtime),
            "in": round(float(cut_in), 3),
            "out": round(float(cut_out), 3),
            "w": int(target_width),
            "h": int(target_height),
            "fps": round(float(fps), 2),
        }
        raw = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @classmethod
    def trim_single_clip(
        cls,
        video_path: Path,
        cut_in: float,
        cut_out: float,
        out_clip_path: Path,
        target_width: int,
        target_height: int,
        fps: float = 30.0,
        has_audio: bool = True,
        is_cancelled_cb=None,
    ) -> bool:
        """Trims a single clip to [cut_in, cut_out] and normalizes video/audio streams for seamless concat.

        The clip is first rendered into a unique temporary file and then atomically moved to
        `out_clip_path`, so a cancelled / killed FFmpeg run never leaves a half-written file that
        would later be mistaken for a valid SHA-256 cache entry (and parallel workers never collide).
        """
        ffmpeg_bin = FFmpegHelper.get_ffmpeg_path()
        out_clip_path = Path(out_clip_path)
        out_clip_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_clip_path = out_clip_path.with_name(
            f"{out_clip_path.stem}.part{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:6]}{out_clip_path.suffix}"
        )

        cut_in = max(0.0, float(cut_in))
        cut_out = max(cut_in + 0.1, float(cut_out))
        fps_int = int(round(fps)) if fps > 0 else 30

        # Scale & pad filter to guarantee uniform resolution across all segments
        vf_scale = (
            f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"fps={fps_int},setsar=1"
        )

        cmd = [
            ffmpeg_bin,
            "-y", "-v", "error",
            "-ss", f"{cut_in:.3f}",
            "-to", f"{cut_out:.3f}",
            "-i", str(video_path),
        ]

        if has_audio:
            filter_complex = (
                f"[0:v]setpts=PTS-STARTPTS,{vf_scale}[v];"
                f"[0:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a]"
            )
        else:
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=cl=stereo:r=48000"])
            filter_complex = (
                f"[0:v]setpts=PTS-STARTPTS,{vf_scale}[v];"
                f"[1:a]asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo[a]"
            )

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-avoid_negative_ts", "make_zero",
            "-shortest",
            str(tmp_clip_path),
        ])

        try:
            returncode, _out, _err, _cancelled = FFmpegHelper.run_cancellable(
                cmd, timeout=300, is_cancelled_cb=is_cancelled_cb,
            )
            if returncode == 0 and tmp_clip_path.exists() and tmp_clip_path.stat().st_size > 512:
                os.replace(str(tmp_clip_path), str(out_clip_path))
            return out_clip_path.exists() and out_clip_path.stat().st_size > 512 and returncode == 0
        except Exception:
            return False
        finally:
            try:
                if tmp_clip_path.exists():
                    tmp_clip_path.unlink()
            except Exception:
                pass

    @classmethod
    def splice_single_project_plan(
        cls,
        segments_plan: list,
        output_video_path: Path,
        project_path: Path = None,
        progress_cb=None,
        is_cancelled_cb=None,
    ) -> tuple[bool, dict]:
        """Executes the full clip trim + SHA-256 cache reuse + FFmpeg concat + SRT & manifest export."""
        def _emit_prog(pct: int, msg: str):
            if callable(progress_cb):
                progress_cb(pct, msg)

        def _cancelled() -> bool:
            return bool(callable(is_cancelled_cb) and is_cancelled_cb())

        try:
            output_video_path = Path(output_video_path)
            total = len(segments_plan)
            if total == 0:
                return False, {"error": "没有可合并的视频片段"}

            _emit_prog(2, "正在检测首个视频分辨率与帧率...")
            first_path = Path(segments_plan[0]["video_path"])
            first_info = FFmpegHelper.get_media_info(first_path)
            target_w = first_info.get("width", 1080) or 1080
            target_h = first_info.get("height", 1920) or 1920
            fps = first_info.get("fps", 30.0) or 30.0

            output_base = output_video_path.stem
            eng_dir = output_video_path.parent / f"{output_base}-工程"
            processed_clips_dir = eng_dir / "处理片段"
            cut_cache_dir = eng_dir / "裁切缓存"
            processed_clips_dir.mkdir(parents=True, exist_ok=True)
            cut_cache_dir.mkdir(parents=True, exist_ok=True)

            trimmed_files = []
            processed_manifest_clips = []
            srt_items = []
            merged_words = []
            timeline_cursor_ms = 0
            cache_hits = 0

            for idx, item in enumerate(segments_plan):
                if _cancelled():
                    return False, {"error": "用户已取消合并任务"}

                seq_num = item.get("seq_num", idx + 1)
                vp = Path(item["video_path"])
                if not vp.exists():
                    return False, {"error": f"第 {seq_num:02d} 段视频不存在: {vp.name}"}

                media_info = FFmpegHelper.get_media_info(vp)
                vid_dur = float(item.get("video_duration", 0.0) or media_info.get("duration", 0.0) or 5.0)
                cut_in = max(0.0, float(item.get("cut_in", 0.0) or 0.0))
                cut_out = float(item.get("cut_out", 0.0) or 0.0)
                if cut_out <= cut_in + 0.05:
                    cut_out = vid_dur if vid_dur > cut_in else (cut_in + 5.0)
                if vid_dur > 0:
                    cut_out = min(vid_dur, cut_out)

                sig = cls.compute_clip_cache_signature(
                    vp, cut_in, cut_out, target_w, target_h, fps
                )
                cached_clip_path = cut_cache_dir / f"{sig}.mp4"
                reused_cache = False

                pct = 5 + int((idx / total) * 75)
                if cached_clip_path.exists() and cached_clip_path.stat().st_size > 512:
                    reused_cache = True
                    cache_hits += 1
                    _emit_prog(
                        pct,
                        f"⚡ 复用裁切缓存 ({idx + 1}/{total}): 第 {seq_num:02d} 段 [{cut_in:.2f}s ~ {cut_out:.2f}s]",
                    )
                else:
                    _emit_prog(
                        pct,
                        f"✂️ 正在裁切气口 ({idx + 1}/{total}): 第 {seq_num:02d} 段 [{cut_in:.2f}s ~ {cut_out:.2f}s]",
                    )
                    ok = cls.trim_single_clip(
                        video_path=vp,
                        cut_in=cut_in,
                        cut_out=cut_out,
                        out_clip_path=cached_clip_path,
                        target_width=target_w,
                        target_height=target_h,
                        fps=fps,
                        has_audio=media_info.get("has_audio", True),
                        is_cancelled_cb=is_cancelled_cb,
                    )
                    if not ok:
                        if _cancelled():
                            return False, {"error": "用户已取消合并任务"}
                        return False, {"error": f"第 {seq_num:02d} 段视频 FFmpeg 裁切失败: {vp.name}"}

                proc_name = f"{idx + 1:03d}_{vp.stem}_{cut_in:.2f}-{cut_out:.2f}.mp4"
                proc_path = processed_clips_dir / proc_name
                shutil.copy2(cached_clip_path, proc_path)
                trimmed_files.append(proc_path)

                actual_cut_dur = FFmpegHelper.get_media_duration(proc_path)
                if actual_cut_dur <= 0:
                    actual_cut_dur = max(0.1, cut_out - cut_in)
                cut_dur_ms = max(50, int(round(actual_cut_dur * 1000)))

                seg_start_ms = timeline_cursor_ms
                seg_end_ms = seg_start_ms + cut_dur_ms

                script_text = str(item.get("text", "")).strip()
                raw_words = item.get("words", []) or []

                clip_words_in_range = []
                abs_clip_words = []
                for w in raw_words:
                    w_start = float(w.get("start", 0.0) or 0.0)
                    w_end = float(w.get("end", w_start) or w_start)
                    if w_end <= cut_in + 0.02 or w_start >= cut_out - 0.02:
                        continue
                    rel_start = max(0.0, w_start - cut_in)
                    rel_end = min(actual_cut_dur, max(rel_start + 0.02, w_end - cut_in))
                    abs_start_sec = (seg_start_ms / 1000.0) + rel_start
                    abs_end_sec = (seg_start_ms / 1000.0) + rel_end
                    clip_words_in_range.append({
                        "word": w.get("word", ""),
                        "start": round(rel_start, 3),
                        "end": round(rel_end, 3),
                    })
                    abs_w = {
                        "word": w.get("word", ""),
                        "start": round(abs_start_sec, 3),
                        "end": round(abs_end_sec, 3),
                    }
                    abs_clip_words.append(abs_w)
                    merged_words.append(abs_w)

                if script_text:
                    if clip_words_in_range:
                        cue_start_ms = seg_start_ms + int(round(clip_words_in_range[0]["start"] * 1000))
                        cue_end_ms = seg_start_ms + int(round(clip_words_in_range[-1]["end"] * 1000))
                        cue_start_ms = max(seg_start_ms, min(seg_end_ms - 50, cue_start_ms))
                        cue_end_ms = max(cue_start_ms + 50, min(seg_end_ms, cue_end_ms))
                    else:
                        cue_start_ms = seg_start_ms
                        cue_end_ms = seg_end_ms

                    srt_items.append({
                        "start_ms": cue_start_ms,
                        "end_ms": cue_end_ms,
                        "text": script_text,
                    })

                processed_manifest_clips.append({
                    "index": idx + 1,
                    "seq_num": seq_num,
                    "path": str(proc_path),
                    "source": str(vp),
                    "source_start": round(cut_in, 3),
                    "source_end": round(cut_out, 3),
                    "duration": round(actual_cut_dur, 3),
                    "script": script_text,
                    "word_timeline": clip_words_in_range,
                    "words": abs_clip_words,
                    "cache_signature": sig,
                    "reused_from_cache": reused_cache,
                })

                timeline_cursor_ms = seg_end_ms

            # Step 2: Concatenate all trimmed clips into output_video_path
            _emit_prog(85, f"🔗 正在无缝合并拼接 {len(trimmed_files)} 个视频片段...")
            output_video_path.parent.mkdir(parents=True, exist_ok=True)
            ffmpeg_bin = FFmpegHelper.get_ffmpeg_path()

            if len(trimmed_files) == 1:
                shutil.copy2(trimmed_files[0], output_video_path)
            else:
                # Each task gets its own unique concat list + temporary output file, so several
                # tasks can be spliced in parallel without temp filename collisions.
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".txt", prefix="flowcue_concat_", delete=False, encoding="utf-8"
                ) as tf:
                    concat_list_path = Path(tf.name)
                    for clip_file in trimmed_files:
                        escaped_path = str(clip_file.resolve()).replace("'", "'\\''")
                        tf.write(f"file '{escaped_path}'\n")

                tmp_output_path = output_video_path.with_name(
                    f"{output_video_path.stem}.part{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex[:6]}"
                    f"{output_video_path.suffix}"
                )
                try:
                    cmd_concat = [
                        ffmpeg_bin,
                        "-y", "-v", "error",
                        "-f", "concat",
                        "-safe", "0",
                        "-i", str(concat_list_path),
                        "-c", "copy",
                        "-movflags", "+faststart",
                        str(tmp_output_path),
                    ]
                    rc_concat, _o, _e, was_cancelled = FFmpegHelper.run_cancellable(
                        cmd_concat, timeout=600, is_cancelled_cb=is_cancelled_cb,
                    )
                    if was_cancelled or _cancelled():
                        return False, {"error": "用户已取消合并任务"}
                    if rc_concat != 0 or not tmp_output_path.exists():
                        cmd_reenc = [
                            ffmpeg_bin,
                            "-y", "-v", "error",
                            "-f", "concat",
                            "-safe", "0",
                            "-i", str(concat_list_path),
                            "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                            "-c:a", "aac", "-b:a", "192k",
                            "-movflags", "+faststart",
                            str(tmp_output_path),
                        ]
                        rc_reenc, _o2, err_reenc, was_cancelled = FFmpegHelper.run_cancellable(
                            cmd_reenc, timeout=900, is_cancelled_cb=is_cancelled_cb,
                        )
                        if was_cancelled or _cancelled():
                            return False, {"error": "用户已取消合并任务"}
                        if rc_reenc != 0:
                            err_txt = (err_reenc or b"").decode("utf-8", errors="replace")[:300]
                            return False, {"error": f"FFmpeg 合并拼接失败: {err_txt}"}
                    try:
                        os.replace(str(tmp_output_path), str(output_video_path))
                    except Exception as e:
                        return False, {"error": f"无法写入成片（文件可能正被占用）: {output_video_path.name} ({e})"}
                finally:
                    try:
                        concat_list_path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    try:
                        tmp_output_path.unlink(missing_ok=True)
                    except Exception:
                        pass

            # Step 3: Write synchronized SRT and project manifest
            _emit_prog(95, "📝 正在生成同步 SRT 字幕与工程清单...")
            srt_path = output_video_path.with_suffix(".srt")
            cls.write_srt_file(srt_items, srt_path)

            all_scripts = [c["script"] for c in processed_manifest_clips if c.get("script")]
            with open(eng_dir / "文案.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(all_scripts))

            manifest_path = processed_clips_dir / "处理片段清单.json"
            total_dur_sec = round(timeline_cursor_ms / 1000.0, 3)
            manifest_data = {
                "version": 1,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "output_path": str(output_video_path),
                "srt_path": str(srt_path),
                "cut_cache_dir": str(cut_cache_dir),
                "total_duration": total_dur_sec,
                "output_duration": total_dur_sec,
                "clips": processed_manifest_clips,
                "merged_words": merged_words,
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, ensure_ascii=False, indent=2)

            _emit_prog(100, "✅ 成片与同步字幕导出完成！")
            return True, {
                "video_path": str(output_video_path),
                "srt_path": str(srt_path),
                "manifest_path": str(manifest_path),
                "engineering_dir": str(eng_dir),
                "total_clips": len(trimmed_files),
                "cache_hits": cache_hits,
                "total_duration": round(timeline_cursor_ms / 1000.0, 2),
                "merged_words": merged_words,
                "clips": processed_manifest_clips,
            }
        except Exception as e:
            return False, {"error": f"合并拼接异常: {str(e)}"}


class VideoSpliceWorker(QThread):
    """Background worker that trims all valid segments (with SHA-256 cut cache),
    concatenates them into the final MP4, and exports synchronized SRT + Reels manifest.
    """

    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, dict)

    def __init__(self, segments_plan: list, output_video_path: str, project_path: str = "", parent=None):
        super().__init__(parent)
        self.segments_plan = segments_plan
        self.output_video_path = Path(output_video_path)
        self.project_path = Path(project_path) if project_path else self.output_video_path.parent
        self._cancelled = False

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def run(self):
        ok, res = VideoSpliceService.splice_single_project_plan(
            segments_plan=self.segments_plan,
            output_video_path=self.output_video_path,
            project_path=self.project_path,
            progress_cb=lambda pct, msg: self.progress.emit(pct, msg),
            is_cancelled_cb=lambda: self._cancelled or self.isInterruptionRequested(),
        )
        self.finished.emit(ok, res)


class BatchMultiProjectSpliceWorker(QThread):
    """Background worker that splices multiple selected FlowCue tasks (up to 4 in parallel,
    see `max_parallel_tasks`; 1 = one by one) and collects all spliced MP4 + SRT + word-timeline
    payloads (in the original task order) for one-click import into Batch Reels.
    """

    task_started = pyqtSignal(str)
    task_progress = pyqtSignal(str, int, str)
    task_finished = pyqtSignal(str, bool, dict)
    overall_progress = pyqtSignal(int, int, str)
    all_finished = pyqtSignal(int, int, list)

    MAX_PARALLEL_TASKS_LIMIT = 4

    def __init__(
        self,
        tasks_to_splice: list = None,
        reuse_existing_merged: bool = False,
        projects_list: list = None,
        base_storage_path=None,
        skip_already_merged: bool = False,
        parent=None,
        max_parallel_tasks: int = 4,
    ):
        """
        Args:
            tasks_to_splice: optional pre-built list of dicts
            projects_list: list of {"id": str, "path": Path/str} to build plan & splice automatically
            base_storage_path: base storage path for VideoChecker
            skip_already_merged / reuse_existing_merged: if True and output_video_path + .srt + manifest exist, reuse
            max_parallel_tasks: number of tasks spliced in parallel (并行线程数, clamped to 1..4)
        """
        super().__init__(parent)
        self.tasks_to_splice = tasks_to_splice or []
        self.projects_list = projects_list or []
        self.base_storage_path = base_storage_path
        self.reuse_existing_merged = bool(reuse_existing_merged or skip_already_merged)
        try:
            self.max_parallel_tasks = max(1, min(self.MAX_PARALLEL_TASKS_LIMIT, int(max_parallel_tasks or 1)))
        except (TypeError, ValueError):
            self.max_parallel_tasks = 1
        self._cancelled = False

    def _is_cancelled(self) -> bool:
        return bool(self._cancelled or self.isInterruptionRequested())

    def cancel(self):
        self._cancelled = True
        self.requestInterruption()

    def stop(self):
        self.cancel()
        self.wait(3000)

    def _build_task_item_from_project(self, p_info: dict) -> dict:
        from models.project_model import ProjectModel
        from services.video_checker import VideoChecker

        proj_id = str(p_info.get("id", ""))
        proj_path = Path(p_info.get("path", ""))
        model = ProjectModel(proj_path)
        report = VideoChecker.check_project_videos(model, proj_path, base_storage_path=self.base_storage_path)

        # Auto-relocate any pending videos found in download folder so splicing has all ready files
        if report.get("pending_count", 0) > 0:
            try:
                relocate_fn = getattr(VideoChecker, "relocate_found_videos", None)
                if callable(relocate_fn):
                    relocate_fn(report)
                else:
                    VideoChecker.relocate_videos(report, proj_path)
                report = VideoChecker.check_project_videos(model, proj_path, base_storage_path=self.base_storage_path)
            except Exception:
                pass

        segments = model.spanish_segments or []
        details = report.get("segments_detail", [])
        plan = []
        model_dirty = False

        for i, detail in enumerate(details):
            if not detail.get("found") or not detail.get("source_path"):
                continue
            seg = segments[i] if i < len(segments) else {}
            if seg.get("marked_for_deletion", False):
                continue
            vp = Path(str(detail["source_path"]))
            if not vp.exists():
                continue

            vid_dur = float(seg.get("video_duration", 0.0) or 0.0)
            if vid_dur <= 0:
                vid_dur = FFmpegHelper.get_media_duration(vp)
                seg["video_duration"] = round(vid_dur, 3)
                model_dirty = True

            cut_in = float(seg.get("cut_in", 0.0) or 0.0)
            cut_out = float(seg.get("cut_out", 0.0) or 0.0)
            if cut_out <= cut_in + 0.05:
                cut_in = 0.0
                cut_out = vid_dur if vid_dur > 0 else 5.0

            plan.append({
                "segment_index": i,
                "seq_num": detail.get("index", i + 1),
                "video_path": str(vp),
                "text": seg.get("text", ""),
                "cut_in": cut_in,
                "cut_out": cut_out,
                "video_duration": vid_dur,
                "words": seg.get("word_timings", []) or [],
            })

        if model_dirty:
            try:
                model.save()
            except Exception:
                pass

        output_dir = proj_path / "merged_output"
        output_dir.mkdir(parents=True, exist_ok=True)
        proj_name = model.project_id or proj_id or proj_path.name
        output_video_path = output_dir / f"{proj_name}_成片.mp4"

        return {
            "project_id": proj_id or proj_name,
            "project_path": str(proj_path),
            "output_video_path": str(output_video_path),
            "segments_plan": plan,
        }

    def _splice_one(self, idx: int, raw_item: dict, total: int):
        """Splices a single task inside a pool thread (independent FFmpeg processes, per-project
        engineering/cache dirs and unique temp files, so up to 4 tasks can safely run in parallel).

        Returns:
            tuple: (ok: bool, payload: dict | None)
        """
        if self._is_cancelled():
            return False, None

        if "segments_plan" not in raw_item:
            proj_id = str(raw_item.get("id") or raw_item.get("project_id") or f"Task_{idx + 1}")
            self.task_started.emit(proj_id)
            self.task_progress.emit(proj_id, 0, "🎬 正在准备合并拼接（加载项目 / 归位视频）...")
            try:
                item = self._build_task_item_from_project(raw_item)
            except Exception as e:
                self.task_finished.emit(proj_id, False, {"error": f"加载项目失败: {e}"})
                return False, None
        else:
            item = raw_item
            proj_id = str(item.get("project_id", f"Task_{idx + 1}"))
            self.task_started.emit(proj_id)

        proj_path = Path(item.get("project_path", ""))
        out_video = Path(item.get("output_video_path", ""))
        plan = item.get("segments_plan", [])

        if not plan:
            self.task_finished.emit(proj_id, False, {"error": "没有可合并的有效视频片段"})
            return False, None

        # Check fast reuse if requested
        out_srt = out_video.with_suffix(".srt")
        manifest_path = out_video.parent / f"{out_video.stem}-工程" / "处理片段" / "处理片段清单.json"
        if self.reuse_existing_merged and out_video.exists() and out_srt.exists() and manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    m_data = json.load(f)
                dur = float(m_data.get("total_duration") or m_data.get("output_duration") or 0.0)
                words = m_data.get("merged_words", [])
                clips = m_data.get("clips", [])
                res = {
                    "project_name": proj_id,
                    "video_path": str(out_video),
                    "srt_path": str(out_srt),
                    "manifest_path": str(manifest_path),
                    "output_dir": str(out_video.parent),
                    "duration": dur,
                    "total_duration": dur,
                    "total_clips": len(clips) or len(plan),
                    "cache_hits": len(clips) or len(plan),
                    "words": words,
                    "merged_words": words,
                    "segments": clips,
                    "reused_full_video": True,
                    "reused_existing": True,
                }
                self.task_finished.emit(proj_id, True, res)
                return True, res
            except Exception:
                pass

        if self._is_cancelled():
            self.task_finished.emit(proj_id, False, {"error": "用户已取消合并任务"})
            return False, None

        ok, res = VideoSpliceService.splice_single_project_plan(
            segments_plan=plan,
            output_video_path=out_video,
            project_path=proj_path,
            progress_cb=lambda pct, msg, pid=proj_id: self.task_progress.emit(pid, pct, msg),
            is_cancelled_cb=self._is_cancelled,
        )

        if ok:
            payload = {
                "project_name": proj_id,
                "video_path": res.get("video_path", ""),
                "srt_path": res.get("srt_path", ""),
                "manifest_path": res.get("manifest_path", ""),
                "output_dir": str(out_video.parent),
                "duration": res.get("total_duration", 0.0),
                "total_duration": res.get("total_duration", 0.0),
                "total_clips": res.get("total_clips", 0),
                "cache_hits": res.get("cache_hits", 0),
                "words": res.get("merged_words", []),
                "merged_words": res.get("merged_words", []),
                "segments": res.get("clips", []),
            }
            self.task_finished.emit(proj_id, True, payload)
            return True, payload

        self.task_finished.emit(proj_id, False, res)
        return False, None

    def run(self):
        work_items = list(self.tasks_to_splice) if self.tasks_to_splice else list(self.projects_list)
        total = len(work_items)
        success_count = 0
        done_count = 0
        payload_by_index = {}

        if total == 0:
            self.overall_progress.emit(0, 0, "✅ 批量拼接完成：没有需要拼接的任务")
            self.all_finished.emit(0, 0, [])
            return

        workers = max(1, min(self.max_parallel_tasks, total))
        self.overall_progress.emit(
            0, total, f"🎬 正在合并拼接 {total} 个任务（并行线程数 {workers}）..."
        )

        executor = ThreadPoolExecutor(max_workers=workers)
        pending_cancelled = False
        try:
            fut_to_idx = {
                executor.submit(self._splice_one, idx, raw_item, total): idx
                for idx, raw_item in enumerate(work_items)
            }
            for fut in as_completed(fut_to_idx):
                if fut.cancelled():
                    continue
                idx = fut_to_idx[fut]
                try:
                    ok, payload = fut.result()
                except Exception as exc:
                    ok, payload = False, None
                    raw = work_items[idx] if idx < len(work_items) else {}
                    pid = str(raw.get("id") or raw.get("project_id") or f"Task_{idx + 1}")
                    self.task_finished.emit(pid, False, {"error": f"合并拼接异常: {exc}"})
                done_count += 1
                if ok and payload:
                    success_count += 1
                    payload_by_index[idx] = payload
                self.overall_progress.emit(
                    done_count, total,
                    f"🎬 已完成 {done_count}/{total} 个任务（成功 {success_count}，并行线程数 {workers}）",
                )
                if self._is_cancelled() and not pending_cancelled:
                    # Drop queued tasks; running ones abort quickly (their FFmpeg processes are killed)
                    pending_cancelled = True
                    for f in fut_to_idx:
                        f.cancel()
        finally:
            try:
                executor.shutdown(wait=True, cancel_futures=True)
            except TypeError:  # Python < 3.9
                executor.shutdown(wait=True)

        # Keep the original task order for the Batch Reels payload list
        completed_payloads = [payload_by_index[i] for i in sorted(payload_by_index)]
        success_count = len(completed_payloads)

        self.overall_progress.emit(
            total, total,
            f"✅ 批量拼接完成：成功 {success_count}/{total} 个任务"
        )
        self.all_finished.emit(success_count, total, completed_payloads)
