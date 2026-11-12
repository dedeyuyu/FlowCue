# -*- coding: utf-8 -*-
"""
拆批规划（纯数据逻辑，不依赖任何界面控件）。

以前「全局托管 → 分配」需要把项目管理页面逐个切换到每个项目（重建表格、刷新下拉框……）
才能调用 build_batches，项目一多界面就会卡住。现在拆批逻辑抽成纯函数：
  - 项目管理页的 build_batches() 直接调用它（保证两边结果完全一致）；
  - 全局托管在后台线程里对所有勾选项目调用它，界面全程不卡。
"""
import re
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from models.project_model import ProjectModel, parse_image_index
from services.text_processor import TextProcessor

IMG_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_PURE_IMG_INDEX_RE = re.compile(r'^(?:FC)?0*(\d+)$', re.IGNORECASE)


def list_project_images(project_path):
    downloads_dir = Path(project_path) / "downloads"
    if not downloads_dir.exists():
        return []
    try:
        imgs = [p for p in downloads_dir.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
    except Exception:
        return []
    imgs.sort(key=lambda x: x.name)
    return imgs


def match_explicit_image(explicit_name, all_imgs):
    """在本地图片列表中匹配用户指定/表格导入的图片名（支持精确名、忽略大小写、无后缀名、纯序号如 1 / 01 / FC0001）。"""
    raw = str(explicit_name or "").strip().strip('"\'')
    if not raw or not all_imgs:
        return None
    clean_name = Path(raw.replace("\\", "/")).name.strip()
    if not clean_name:
        return None

    # 1. 精确文件名匹配
    for img in all_imgs:
        if img.name == clean_name:
            return img

    # 2. 忽略大小写完整文件名匹配
    low = clean_name.lower()
    for img in all_imgs:
        if img.name.lower() == low:
            return img

    # 3. 去扩展名（stem）匹配，例如导入 "FC0003" 或 "03" 匹配 "FC0003.jpg" / "03.png"
    target_stem = Path(clean_name).stem.lower()
    if target_stem:
        for img in all_imgs:
            if img.stem.lower() == target_stem:
                return img

    # 4. 序号等价匹配，例如导入 "3" / "03" / "FC3" / "03.jpg" 匹配 "FC0003.jpg" / "3.png"
    want_idx = parse_image_index(clean_name)
    if want_idx is None:
        m = _PURE_IMG_INDEX_RE.match(target_stem or clean_name)
        if m:
            want_idx = int(m.group(1))
    if want_idx is not None:
        for img in all_imgs:
            if parse_image_index(img.name) == want_idx:
                return img
        s1, s2 = str(want_idx), f"{want_idx:02d}"
        for img in all_imgs:
            st = img.stem
            if st in (s1, s2) or st.startswith((f"{s1}_", f"{s2}_", f"{s1}-", f"{s2}-")):
                return img

    return None


def resolve_image_name(idx, seg, all_imgs):
    """与 ProjectDetailWidget.resolve_segment_image_and_data 相同的匹配规则（只返回文件名）。"""
    if not all_imgs:
        return ""
    explicit = (seg.get("image_name") or "").strip() if isinstance(seg, dict) else ""
    if explicit:
        matched = match_explicit_image(explicit, all_imgs)
        if matched is not None:
            return matched.name
    s1, s2 = f"{idx + 1}", f"{idx + 1:02d}"
    for img in all_imgs:
        st = img.stem
        if st in (s1, s2) or st.startswith((f"{s1}_", f"{s2}_", f"{s1}-", f"{s2}-")):
            return img.name
    if len(all_imgs) == 1:
        return all_imgs[0].name
    return all_imgs[idx % len(all_imgs)].name


def project_short_name(project_model, project_path):
    """项目序号 (如 01) + 用户项目名前 10 个字。"""
    pid = getattr(project_model, "project_id", "") or (Path(project_path).name if project_path else "")
    idx_val = getattr(project_model, "index", 0) if project_model else 0
    col1 = (getattr(project_model, "col1_name", "") or "").strip() if project_model else ""
    idx_str = f"{int(idx_val):02d}" if idx_val else "01"
    if pid:
        clean_pid = re.sub(r'-flow$', '', str(pid), flags=re.IGNORECASE)
        m = re.match(r'^(\d+)(?:[_\-\s]+(.*))?$', clean_pid)
        if m:
            idx_str = m.group(1).zfill(2)
            if not col1 and m.group(2):
                rest = m.group(2)
                col1 = rest.rsplit("_", 1)[0] if "_" in rest else rest
    if col1.startswith(f"{idx_str}_"):
        col1 = col1[len(idx_str) + 1:].strip()
    short_user = col1[:10]
    return f"{idx_str}_{short_user}" if short_user else idx_str


def compute_project_batches(project_model, project_path, template_manager, config_manager,
                            global_tpl_id=None, global_motion_id=None, enable_end_frame=None,
                            short_name=None, resolve_images=True, copied_rows=None):
    """
    按积分上限把项目未完成的分句拆成批次。
    返回 {"batches": [[task,...],...], "skipped": int, "error": str, "level": "warning"/"info"}
    """
    project_path = Path(project_path)
    segments = project_model.spanish_segments if project_model else []
    if not project_model:
        return {"batches": [], "skipped": 0, "error": "请先打开一个工程项目。"}
    if not segments:
        return {"batches": [], "skipped": 0, "error": "当前项目没有西文分句，无法生成任务。"}

    cm = config_manager
    tm = template_manager
    if global_tpl_id is None:
        global_tpl_id = project_model.selected_template_id or ""
        if global_tpl_id and tm and not tm.get_template(global_tpl_id):
            global_tpl_id = ""
    if global_motion_id is None:
        global_motion_id = project_model.selected_motion_id or ""
        if global_motion_id and tm and not tm.get_motion(global_motion_id):
            global_motion_id = ""
    if enable_end_frame is None:
        if project_model.enable_end_frame is not None:
            enable_end_frame = bool(project_model.enable_end_frame)
        else:
            enable_end_frame = bool(getattr(cm, "enable_end_frame", False)) if cm else False
    if short_name is None:
        short_name = project_short_name(project_model, project_path)

    # 1. Check prompt template selection
    if not global_tpl_id:
        return {"batches": [], "skipped": 0, "error": "导出失败：请先选择提示词模板！"}

    if resolve_images:
        all_imgs = list_project_images(project_path)
        for idx, seg in enumerate(segments):
            name = resolve_image_name(idx, seg, all_imgs)
            if name:
                seg["image_name"] = name

    # 2. Check image material association for all segments
    missing_image_rows = [idx + 1 for idx, seg in enumerate(segments) if not seg.get("image_name")]
    if missing_image_rows:
        if len(missing_image_rows) == len(segments):
            return {"batches": [], "skipped": 0, "error": "导出失败：句段尚未关联图片素材，请先选择关联图片素材！"}
        rows_str = "、".join([f"第 {r} 句" for r in missing_image_rows[:5]])
        if len(missing_image_rows) > 5:
            rows_str += f" 等 {len(missing_image_rows)} 句"
        return {"batches": [], "skipped": 0, "error": f"导出失败：{rows_str} 尚未关联图片素材，请先选择关联图片素材！"}

    all_tasks = []
    skipped_copied_count = 0
    project_id_str = getattr(project_model, "project_id", "") or project_path.name
    downloads_dir = project_path / "downloads"
    videos_dir = downloads_dir / "videos"

    default_mode = getattr(cm, "default_generation_mode", "VIDEO_FRAMES") if cm else "VIDEO_FRAMES"
    default_aspect = getattr(cm, "default_aspect_ratio", "9:16") if cm else "9:16"
    default_model = getattr(cm, "default_video_model", "omni_1_1_flash") if cm else "omni_1_1_flash"
    task_interval = getattr(cm, "task_interval", 5) if cm else 5

    for idx, seg in enumerate(segments):
        # 严格依据本地磁盘是否存在已完成的 mp4 视频文件作为跳过标准
        download_name = f"{idx+1:02d}.mp4"
        download_path_obj = (videos_dir / download_name).resolve()
        if download_path_obj.exists() and download_path_obj.stat().st_size > 0:
            seg["copied"] = True
            seg["completed"] = True
            if copied_rows is not None:
                copied_rows.add(idx)
            skipped_copied_count += 1
            continue
        seg["copied"] = False
        seg["completed"] = False
        if copied_rows is not None:
            copied_rows.discard(idx)

        text = TextProcessor.remove_punctuation(seg.get("text", ""))
        seg["text"] = text

        # Generate final prompt resolving segment override or global fallback
        tpl = tm.get_template(seg.get("template_id", "") or global_tpl_id) if tm else None
        motion = tm.get_motion(seg.get("motion_id", "") or global_motion_id) if tm else None
        template_content = tpl["content"] if tpl else "{spanish_text}"
        motion_content = motion["content"] if motion else ""
        final_prompt = template_content.replace("{spanish_text}", text)
        final_prompt = final_prompt.replace("{camera_motion}", motion_content)
        final_prompt = re.sub(r' +', ' ', final_prompt).strip()

        image_name = seg.get("image_name", "")
        if seg.get("mode_overridden") and seg.get("mode") in ("VIDEO_FRAMES", "VIDEO_REFERENCES"):
            mode = seg.get("mode")
        else:
            mode = default_mode
        is_edge = (idx == 0 or idx == len(segments) - 1)
        if cm:
            duration = cm.get_duration_for_length(len(text), is_edge=is_edge)
            seg["duration"] = duration
        else:
            duration = seg.get("duration", 6)

        local_image_path = str((downloads_dir / image_name).resolve()) if image_name else ""

        task_dict = {
            "project_id": project_id_str,
            "project_short": short_name,
            "segment_index": idx + 1,
            "segment_no": f"{idx+1:02d}",
            "prompt": final_prompt,
            "mode": mode,
            "aspect_ratio": default_aspect,
            "model": default_model,
            "interval": task_interval,
            "image_name": image_name,
            "local_image_path": local_image_path,
            "duration": duration,
            "download_path": str(download_path_obj),
            "_raw_duration": duration,
            "_original_index": idx,
            "_text_len": len(text),
            "_mode_overridden": bool(seg.get("mode_overridden")),
        }
        if enable_end_frame:
            end_name = (seg.get("end_image_name") or "").strip()
            cand = downloads_dir / end_name if end_name else None
            if cand is not None and cand.is_file():
                task_dict["end_image_name"] = end_name
                task_dict["end_local_image_path"] = str(cand.resolve())
                task_dict["mode"] = "VIDEO_FRAMES"
        all_tasks.append(task_dict)

    if not all_tasks:
        if skipped_copied_count > 0:
            return {"batches": [], "skipped": skipped_copied_count, "level": "info", "error": (
                f"所有 {skipped_copied_count} 个分句均已手动复制/生成过（已变绿标结）。\n"
                "已自动排除这些片段，没有需要新导出的任务！\n\n"
                "💡 如需重新导出，请在表格中双击对应句子的【秒数】列取消已完成标绿即可。")}
        return {"batches": [], "skipped": 0, "error": "当前项目没有可导出的有效分句。"}

    # Partition tasks using First Fit Decreasing (FFD) to maximize points utilization per batch
    batches = []
    max_batch_points = cm.max_batch_points if cm else 50

    def get_task_points(task):
        dur = task.get("duration", task.get("_raw_duration", 6))
        if cm:
            return cm.get_points_for_duration(dur)
        return {10: 15, 8: 12, 6: 10, 4: 7}.get(dur, 7)

    batch_pts = []
    for task in sorted(all_tasks, key=get_task_points, reverse=True):
        pts = get_task_points(task)
        for bi, batch in enumerate(batches):
            if batch_pts[bi] + pts <= max_batch_points:
                batch.append(task)
                batch_pts[bi] += pts
                break
        else:
            batches.append([task])
            batch_pts.append(pts)

    # Sort tasks within each batch by their original chronological index for clear display
    for batch_idx, batch in enumerate(batches):
        batch.sort(key=lambda t: t["_original_index"])
        for t in batch:
            t["batch_no"] = batch_idx + 1

    return {"batches": batches, "skipped": skipped_copied_count, "error": ""}


class ProjectBatchPlannerThread(QThread):
    """后台线程：对多个项目执行拆批。结果: finished_signal(list[(path, label, result_dict)])"""
    finished_signal = pyqtSignal(list)
    progress_signal = pyqtSignal(int, int, str)

    def __init__(self, items, template_manager, config_manager, open_project=None, parent=None):
        """
        items: [(project_path, label), ...]
        open_project: (project_path, overrides_dict) —— 当前在项目管理中打开的项目，
                      用界面上的实时选择（统一模板 / 运镜 / 尾帧开关）覆盖磁盘上的值。
        """
        super().__init__(parent)
        self.items = list(items)
        self.tm = template_manager
        self.cm = config_manager
        self.open_project = open_project

    def run(self):
        out = []
        total = len(self.items)
        for n, (path, label) in enumerate(self.items, start=1):
            if self.isInterruptionRequested():
                break
            self.progress_signal.emit(n, total, label)
            try:
                model = ProjectModel(Path(path))
                kwargs = {}
                if self.open_project and str(self.open_project[0]) == str(path):
                    kwargs = dict(self.open_project[1] or {})
                res = compute_project_batches(model, path, self.tm, self.cm, **kwargs)
            except Exception as e:
                res = {"batches": [], "skipped": 0, "error": f"拆批异常：{e}"}
            out.append((str(path), label, res))
        self.finished_signal.emit(out)
