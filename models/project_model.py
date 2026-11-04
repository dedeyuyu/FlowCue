# -*- coding: utf-8 -*-
import os
import re
import copy
import json
import uuid
from pathlib import Path

# ── 图片自动命名规则 ──────────────────────────────────────────────
# 新规则：FC + 4 位零填充的全局序号，例如 FC0001.jpg、FC0002.png ……（超过 9999 自动变为 FC10000）
#   · 固定宽度：同一范围内任何名字都不是另一个名字的前缀/子串（旧规则下 "1" 会命中 1/10/11/21…），
#     Flow「搜索资源」搜 FC0001 只会出现这一张，插件精确选图更快更稳；
#   · 字母前缀：不会与 Flow / 其它工具默认生成的 "1.jpg"、"image (1).png" 等撞名；
#   · 前缀与数字之间不加 "_" / "-"：插件旧版模糊比对会把分隔符拆成单词，"FC_0001" 会退化成与所有图都匹配的 "fc"；
#   · 零填充后「按文件名排序 = 按序号排序」，拆批时未显式指定图片的分句仍按正确顺序对应。
# 旧规则（1.jpg、2.jpg …）的文件依然可以正常读取 / 引用，全局最大序号会同时识别新旧两种格式。
IMAGE_NAME_PREFIX = "FC"
IMAGE_NAME_WIDTH = 4
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
_SEQ_IMAGE_NAME_RE = re.compile(r'^(?:%s)?(\d+)\.[a-zA-Z]+$' % IMAGE_NAME_PREFIX, re.IGNORECASE)
_TMP_RENAME_PREFIX = ".fc_tmp_"
# 分句中直接保存「文件名」的字段 / 保存「路径」的字段（路径只替换最后的文件名部分）
_SEG_NAME_KEYS = ("image_name", "end_image_name")
_SEG_PATH_KEYS = ("local_image_path", "end_local_image_path", "image_path", "end_image_path")


def format_image_name(idx, ext):
    """全局序号 → 新规则文件名，例如 (1, '.JPEG') → 'FC0001.jpg'。"""
    ext = (ext or "").lower()
    if ext == ".jpeg":
        ext = ".jpg"
    return f"{IMAGE_NAME_PREFIX}{int(idx):0{IMAGE_NAME_WIDTH}d}{ext}"


def parse_image_index(filename):
    """从新旧两种自动命名中解析全局序号：'FC0012.jpg' / '12.jpg' → 12；其它名字返回 None。"""
    m = _SEQ_IMAGE_NAME_RE.match(str(filename or ""))
    return int(m.group(1)) if m else None


class ProjectModel:
    """Manages the metadata for a single project (metadata.json)."""
    
    METADATA_FILE_NAME = "metadata.json"
    
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.metadata_path = self.project_dir / self.METADATA_FILE_NAME
        # 写盘去重缓存：(路径, 内容, mtime_ns, size)；内容与磁盘文件都未变化时跳过重复写入
        self._last_saved = None
        self._last_subtitle = None
        
        # Default empty fields
        self.project_id = self.project_dir.name
        self.index = 0
        self.col1_name = ""
        self.col7_notes = ""
        self.google_drive_url = ""
        self.chinese_text = ""
        self.spanish_text = ""
        self.spanish_segments = []  # List of dict: {"text": str, "length": int, "duration": int}
        self.associated_media = []  # List of dict: {"file_path": str, "associated_text_segment_index": int/None}
        self.prompt_template = ""
        self.selected_template_id = ""
        self.selected_motion_id = ""
        self.enable_end_frame = None  # None: follow config, True/False: explicit project override
        self.custom_srt_text = ""     # 用户自定义断行后的文本（仅用于最终合并生成 SRT 字幕，不影响分句与文案核对）
        
        # Load existing metadata if available
        self.load()

    def load(self):
        """Loads metadata from project_dir/metadata.json."""
        if self.metadata_path.exists():
            try:
                with open(self.metadata_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.project_id = data.get("project_id", self.project_id)
                    self.index = data.get("index", self.index)
                    self.col1_name = data.get("col1_name", self.col1_name)
                    self.col7_notes = data.get("col7_notes", self.col7_notes)
                    self.google_drive_url = data.get("google_drive_url", self.google_drive_url)
                    self.chinese_text = data.get("chinese_text", self.chinese_text)
                    self.spanish_text = data.get("spanish_text", self.spanish_text)
                    self.spanish_segments = data.get("spanish_segments", self.spanish_segments)
                    self.associated_media = data.get("associated_media", self.associated_media)
                    self.prompt_template = data.get("prompt_template", self.prompt_template)
                    self.selected_template_id = data.get("selected_template_id", "")
                    self.selected_motion_id = data.get("selected_motion_id", "")
                    self.enable_end_frame = data.get("enable_end_frame", None)
                    self.custom_srt_text = str(data.get("custom_srt_text", "") or "")

                # 记录「刚读到的内容」，之后内容未修改的 save() 可直接跳过写盘
                try:
                    self._last_saved = self._cache_entry(self.metadata_path, self._build_metadata_json())
                except Exception:
                    self._last_saved = None
                
                # Proactively ensure subtitle file exists
                subtitles_dir = self.project_dir.parent / "字幕"
                subtitle_file_path = subtitles_dir / f"{self.project_id}.txt"
                if not subtitle_file_path.exists() and self.spanish_segments:
                    self.save_subtitle_file()
            except Exception as e:
                print(f"Error loading project metadata: {e}")

    def _build_metadata_json(self):
        """按 save() 的格式序列化当前元数据（load 与 save 共用，保证去重比较一致）。"""
        data = {
            "project_id": self.project_id,
            "index": self.index,
            "col1_name": self.col1_name,
            "col7_notes": self.col7_notes,
            "google_drive_url": self.google_drive_url,
            "chinese_text": self.chinese_text,
            "spanish_text": self.spanish_text,
            "spanish_segments": self.spanish_segments,
            "associated_media": self.associated_media,
            "prompt_template": self.prompt_template,
            "selected_template_id": self.selected_template_id,
            "selected_motion_id": self.selected_motion_id,
            "custom_srt_text": getattr(self, "custom_srt_text", "") or "",
        }
        if self.enable_end_frame is not None:
            data["enable_end_frame"] = self.enable_end_frame
        return json.dumps(data, indent=4, ensure_ascii=False)

    @staticmethod
    def _file_stamp(path):
        try:
            st = os.stat(path)
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    @classmethod
    def _cache_entry(cls, path, text):
        return (str(path), text, cls._file_stamp(path))

    @classmethod
    def _is_cache_fresh(cls, cache, path, text):
        """内容相同、路径相同，且磁盘文件自上次读写后没有被其它实例/程序改动过。"""
        if not cache:
            return False
        c_path, c_text, c_stamp = cache
        if c_path != str(path) or c_text != text or c_stamp is None:
            return False
        return cls._file_stamp(path) == c_stamp

    @staticmethod
    def _atomic_write_text(path, text):
        """先写临时文件再 os.replace，写入中途出错也不会留下半截 metadata.json。"""
        path = Path(path)
        tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            try:
                os.replace(tmp, path)
            except OSError:
                # 目标文件被占用（杀毒软件/同步盘）时 os.replace 可能失败，退回直接覆盖写
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    def save(self):
        """Saves current state to project_dir/metadata.json."""
        # 项目文件夹被重命名后（外部直接修改 project_dir），始终写到新目录
        self.metadata_path = self.project_dir / self.METADATA_FILE_NAME
        try:
            text = self._build_metadata_json()
            if not self._is_cache_fresh(self._last_saved, self.metadata_path, text):
                self._atomic_write_text(self.metadata_path, text)
                self._last_saved = self._cache_entry(self.metadata_path, text)
            
            # Save subtitle file
            self.save_subtitle_file()
            
            return True
        except Exception as e:
            print(f"Error saving project metadata: {e}")
            return False

    def save_subtitle_file(self):
        """Saves Spanish segments as a subtitle text file in the '字幕' directory under the base storage path."""
        try:
            subtitles_dir = self.project_dir.parent / "字幕"
            
            subtitle_file_path = subtitles_dir / f"{self.project_id}.txt"
            
            lines = []
            for seg in self.spanish_segments:
                text = seg.get("text", "").strip()
                if text:
                    # Split this segment's text into short lines (max 28 characters)
                    short_lines = self.split_text_into_short_lines(text, max_len=28)
                    lines.extend(short_lines)

            content = "\n".join(lines)
            # 内容未变化且文件未被改动时跳过写盘
            if self._is_cache_fresh(self._last_subtitle, subtitle_file_path, content):
                return True

            subtitles_dir.mkdir(parents=True, exist_ok=True)
            with open(subtitle_file_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._last_subtitle = self._cache_entry(subtitle_file_path, content)
                
            return True
        except Exception as e:
            print(f"Error saving subtitle file: {e}")
            return False

    def split_text_into_short_lines(self, text, max_len=28):
        """Splits a string of text into lines of at most max_len characters, breaking at spaces."""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            if not current_line:
                current_line = word
            else:
                if len(current_line) + 1 + len(word) <= max_len:
                    current_line += " " + word
                else:
                    lines.append(current_line)
                    current_line = word
        if current_line:
            lines.append(current_line)
        return lines

    def _get_global_max_image_index(self, exclude_self=False):
        """Finds the maximum numeric image filename across all projects.

        同时识别旧规则 (12.jpg) 与新规则 (FC0012.jpg)。exclude_self=True 时不统计本项目自己的图片，
        这样对同一项目重复执行「一键命名」时编号保持稳定（不会每次都往后挪）。"""
        max_idx = 0
        base_path = self.project_dir.parent
        if not base_path.exists():
            return 0
        try:
            own = self.project_dir.resolve()
        except Exception:
            own = self.project_dir
        
        for proj_dir in base_path.iterdir():
            if proj_dir.is_dir():
                if exclude_self:
                    try:
                        if proj_dir.resolve() == own:
                            continue
                    except Exception:
                        if proj_dir == self.project_dir:
                            continue
                dl_dir = proj_dir / "downloads"
                if dl_dir.exists():
                    for f in dl_dir.iterdir():
                        if f.is_file():
                            val = parse_image_index(f.name)
                            if val is not None and val > max_idx:
                                max_idx = val
        return max_idx

    def _list_project_images(self):
        downloads_dir = self.project_dir / "downloads"
        if not downloads_dir.exists():
            return []
        return [item for item in downloads_dir.iterdir()
                if item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS]

    @staticmethod
    def _remap_path_value(value, name_mapping):
        """把路径字符串中的文件名部分按映射替换（保留原有的前缀与分隔符风格），未命中返回 None。"""
        if not isinstance(value, str) or not value:
            return None
        cut = max(value.rfind("/"), value.rfind("\\"))
        prefix, base = value[:cut + 1], value[cut + 1:]
        if base not in name_mapping:
            return None
        parent = prefix.rstrip("/\\")
        parent_name = parent[max(parent.rfind("/"), parent.rfind("\\")) + 1:] if parent else ""
        # 只替换本项目 downloads 目录下的文件（相对路径 downloads/x 或绝对路径 .../downloads/x）
        if prefix and parent_name.lower() != "downloads":
            return None
        return prefix + name_mapping[base]

    def _apply_image_name_mapping(self, name_mapping):
        """把 旧文件名 → 新文件名 的映射同时（非链式）应用到所有元数据引用上，返回更新的引用数。"""
        changed = 0
        for media in self.associated_media:
            if not isinstance(media, dict):
                continue
            new_p = self._remap_path_value(media.get("file_path"), name_mapping)
            if new_p is not None:
                media["file_path"] = new_p
                changed += 1
        for seg in self.spanish_segments:
            if not isinstance(seg, dict):
                continue
            for key in _SEG_NAME_KEYS:
                v = seg.get(key)
                if isinstance(v, str) and v in name_mapping:
                    seg[key] = name_mapping[v]
                    changed += 1
            for key in _SEG_PATH_KEYS:
                new_p = self._remap_path_value(seg.get(key), name_mapping)
                if new_p is not None:
                    seg[key] = new_p
                    changed += 1
        return changed

    def rename_images(self, start_idx=None, return_next_idx=False):
        """Renames downloaded images to a global sequential format: FC0001.ext, FC0002.ext, etc.

        · 按修改时间（同时间按文件名）排序后从 start_idx 开始编号；start_idx 为空时紧接其它项目的全局最大序号；
        · 两阶段改名（先全部改成临时名，再改成最终名），避免同目录内新旧名字互相覆盖；
        · 任一步失败都会把已改名的文件全部还原，元数据保持不变，并抛出异常（不会丢图 / 断引用）；
        · 成功后同时更新 associated_media、分句 image_name / end_image_name 及图片路径字段，并原子写入 metadata.json。
        返回值与旧版一致：return_next_idx=True 时返回 (改名数量, 下一个可用序号)，否则只返回改名数量。"""
        downloads_dir = self.project_dir / "downloads"
        images = self._list_project_images()
        if not images:
            return (0, start_idx) if return_next_idx else 0
            
        images.sort(key=lambda x: (x.stat().st_mtime, x.name))
        
        if start_idx is None:
            start_idx = self._get_global_max_image_index(exclude_self=True) + 1

        # 规划：每张图的目标名字（序号对所有图片连续递增，名字未变化的不动）
        plan = []
        idx = start_idx
        for img in images:
            plan.append((img, format_image_name(idx, img.suffix)))
            idx += 1
        next_idx = idx
        todo = [(img, new_name) for img, new_name in plan if img.name != new_name]
        if not todo:
            return (0, next_idx) if return_next_idx else 0

        moved_tmp = []    # [(原路径, 临时路径)]
        moved_final = []  # [(临时路径, 最终路径)]

        def _rollback():
            for tmp_path, final_path in reversed(moved_final):
                try:
                    final_path.rename(tmp_path)
                except Exception as re_err:
                    print(f"[rename_images] 回滚失败 {final_path.name} → {tmp_path.name}: {re_err}")
            for orig_path, tmp_path in reversed(moved_tmp):
                try:
                    tmp_path.rename(orig_path)
                except Exception as re_err:
                    print(f"[rename_images] 回滚失败 {tmp_path.name} → {orig_path.name}: {re_err}")

        try:
            # Pass 1: rename to temporary names to avoid collision within the same folder
            for img, _ in todo:
                tmp_path = downloads_dir / f"{_TMP_RENAME_PREFIX}{uuid.uuid4().hex}{img.suffix}"
                img.rename(tmp_path)
                moved_tmp.append((img, tmp_path))

            # Pass 2: rename to final sequence names
            tmp_of = {orig: tmp for orig, tmp in moved_tmp}
            for img, new_name in todo:
                final_path = downloads_dir / new_name
                if final_path.exists():
                    raise FileExistsError(f"目标文件已存在: {new_name}")
                tmp_of[img].rename(final_path)
                moved_final.append((tmp_of[img], final_path))
        except Exception as e:
            _rollback()
            raise RuntimeError(f"图片重命名失败，已还原所有文件：{e}") from e

        # 更新元数据引用；保存失败同样还原文件与内存中的元数据
        name_mapping = {img.name: new_name for img, new_name in todo}
        backup_media = copy.deepcopy(self.associated_media)
        backup_segments = copy.deepcopy(self.spanish_segments)
        self._apply_image_name_mapping(name_mapping)
        if not self.save():
            self.associated_media = backup_media
            self.spanish_segments = backup_segments
            _rollback()
            raise RuntimeError("图片已改名但保存项目元数据失败，已还原所有文件")

        rename_count = len(todo)
        return (rename_count, next_idx) if return_next_idx else rename_count

    def update_media_files(self):
        """Scans project_dir/downloads and updates associated_media."""
        downloads_dir = self.project_dir / "downloads"
        if not downloads_dir.exists():
            return
            
        existing_paths = {item["file_path"] for item in self.associated_media}
        new_media = list(self.associated_media)
        
        # Scan downloads folder
        for item in downloads_dir.iterdir():
            if item.is_file() and item.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
                # We save relative path to project_dir
                rel_path = f"downloads/{item.name}"
                if rel_path not in existing_paths:
                    new_media.append({
                        "file_path": rel_path,
                        "associated_text_segment_index": None
                    })
                    
        # Remove deleted files from metadata
        final_media = []
        for media in new_media:
            full_path = self.project_dir / media["file_path"]
            if full_path.exists():
                final_media.append(media)
                
        self.associated_media = final_media
        self.save()
