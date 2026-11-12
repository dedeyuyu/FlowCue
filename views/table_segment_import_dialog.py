# -*- coding: utf-8 -*-
"""项目管理 —— 单个任务「表格复制导入（断行文案 + 图片名称）」对话框。

支持从 Excel / WPS / 飞书 / 谷歌表格复制两列（断行后的文案 + 图片名称）直接导入到当前选中的单个任务：
- 仅针对单个选中任务生效；
- 仅导入「断行后的文案」与「图片名称」两项；
- 每句时长严格按导入文案清洗后的字符数与规则设置动态计算（含首尾句加成规则）；
- 提示词继续沿用当前任务的提示词模板与运镜预设；
- 严格以本次导入的有效非空行数为准重建任务分句列表（例如原任务自动切分了 15 个小任务，用户表格导入 10 个，则精确变为 10 个，绝不多出 5 个空任务）。
"""
import csv
import io
import re
from pathlib import Path

from bs4 import BeautifulSoup
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services.batch_planner import IMG_EXTENSIONS, list_project_images, match_explicit_image
from services.text_processor import TextProcessor

_HEADER_TEXT_KEYWORDS = {
    "文案", "断行", "断行文案", "断行后的文案", "分句", "分句文案", "台词", "字幕",
    "内容", "西文", "原文", "句子", "script", "text", "line", "lines", "subtitle", "segment",
}
_HEADER_IMG_KEYWORDS = {
    "图片", "图片名", "图片名称", "素材", "图片素材", "首帧", "首帧图片", "图号",
    "文件名", "配图", "image", "images", "img", "pic", "picture", "photo", "filename",
}
_HEADER_IDX_KEYWORDS = {"序号", "编号", "行号", "id", "index", "no", "no.", "#"}
_IMG_CODE_RE = re.compile(r"^(?:FC)?0*\d{1,6}(?:[-_][A-Za-z0-9]+)?$", re.IGNORECASE)


def parse_table_rows_from_html(html_content: str) -> list[list[str]]:
    """从剪贴板 HTML 表格（Excel / WPS / Google Sheets / 飞书）提取二维单元格数组。"""
    if not html_content or "<tr" not in html_content.lower():
        return []
    try:
        soup = BeautifulSoup(html_content, "html.parser")
    except Exception:
        return []

    rows = []
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        row = []
        for td in cells:
            txt = td.get_text(separator="\n").replace("\r\n", "\n").replace("\r", "\n").strip()
            row.append(txt)
        if any(c.strip() for c in row):
            rows.append(row)

    return _expand_single_multiline_row_if_needed(rows)


def parse_table_rows_from_tsv(raw_text: str) -> list[list[str]]:
    """从纯文本 TSV（制表符分隔，兼容 Excel 双引号单元格内换行）解析二维单元格数组。"""
    if not raw_text or not raw_text.strip():
        return []
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    rows = []
    try:
        reader = csv.reader(io.StringIO(normalized), delimiter="\t", quotechar='"')
        for r in reader:
            cleaned = [c.strip() for c in r]
            if any(cleaned):
                rows.append(cleaned)
    except Exception:
        for line in normalized.split("\n"):
            if not line.strip():
                continue
            rows.append([c.strip() for c in line.split("\t")])

    return _expand_single_multiline_row_if_needed(rows)


def _expand_single_multiline_row_if_needed(rows: list[list[str]]) -> list[list[str]]:
    """若用户复制的是单个多行合并单元格（只有 1 行，但列内用换行符分了多句），自动按行展开；
    对于常规多行表格，将同一单元格内部的软换行合并为空格，保证 1 行表格 = 1 个分句任务。"""
    if not rows:
        return []
    if len(rows) == 1:
        r0 = rows[0]
        if len(r0) == 1 and "\n" in r0[0]:
            return [[ln.strip()] for ln in r0[0].split("\n") if ln.strip()]
        if len(r0) >= 2 and "\n" in r0[0]:
            c0_lines = [ln.strip() for ln in r0[0].split("\n") if ln.strip()]
            c1_lines = [ln.strip() for ln in r0[1].split("\n") if ln.strip()]
            if len(c0_lines) > 1 and (len(c1_lines) == 0 or len(c1_lines) == len(c0_lines)):
                expanded = []
                for idx, l0 in enumerate(c0_lines):
                    l1 = c1_lines[idx] if idx < len(c1_lines) else ""
                    expanded.append([l0, l1])
                return expanded

    flattened = []
    for r in rows:
        clean_row = [re.sub(r"\s*\n+\s*", " ", c).strip() for c in r]
        if any(clean_row):
            flattened.append(clean_row)
    return flattened


def is_likely_header_row(row: list[str]) -> bool:
    """判断第 1 行是否为表头（如「断行文案 | 图片」）。"""
    if not row:
        return False
    norm_cells = [re.sub(r"[\s:：()（）\[\]【】]", "", c).lower() for c in row if c.strip()]
    if not norm_cells:
        return False
    hits = 0
    for c in norm_cells:
        if c in _HEADER_TEXT_KEYWORDS or c in _HEADER_IMG_KEYWORDS or c in _HEADER_IDX_KEYWORDS:
            hits += 1
    if hits >= 2:
        return True
    if len(norm_cells) == 1 and norm_cells[0] in _HEADER_TEXT_KEYWORDS:
        return True
    if hits == 1 and all(len(c) <= 12 for c in norm_cells):
        return True
    return False


def _cell_looks_like_image(val: str, all_imgs: list[Path]) -> float:
    """评估单个单元格像「图片名称」的置信分（0.0 ~ 1.0）。"""
    s = str(val or "").strip().strip('"\'')
    if not s:
        return 0.0
    name = Path(s.replace("\\", "/")).name
    suffix = Path(name).suffix.lower()
    if suffix in IMG_EXTENSIONS:
        return 1.0
    if all_imgs and match_explicit_image(name, all_imgs) is not None:
        return 0.9
    if _IMG_CODE_RE.match(name):
        return 0.85
    if " " not in name and len(name) <= 20 and re.search(r"\d", name):
        return 0.65
    return 0.0


def auto_detect_text_and_image_cols(rows: list[list[str]], skip_header: bool, all_imgs: list[Path]) -> tuple[int, int]:
    """智能识别哪一列是「断行文案」、哪一列是「图片名称」。
    返回 (text_col_idx, img_col_idx)，其中 img_col_idx = -1 表示无图片列。
    """
    if not rows:
        return 0, 1
    max_cols = max(len(r) for r in rows)
    if max_cols <= 1:
        return 0, -1

    header = rows[0] if skip_header else []
    data_rows = rows[1:] if (skip_header and len(rows) > 1) else rows

    # 1. 若有表头，优先参考表头列名
    hdr_text_col = -1
    hdr_img_col = -1
    if header:
        for ci, raw_h in enumerate(header):
            h = re.sub(r"[\s:：()（）\[\]【】]", "", raw_h).lower()
            if hdr_text_col < 0 and (h in _HEADER_TEXT_KEYWORDS or any(k in h for k in ("文案", "断行", "分句", "script", "text"))):
                hdr_text_col = ci
            elif hdr_img_col < 0 and (h in _HEADER_IMG_KEYWORDS or any(k in h for k in ("图片", "素材", "首帧", "图号", "image", "img"))):
                hdr_img_col = ci
        if hdr_text_col >= 0 and hdr_img_col >= 0 and hdr_text_col != hdr_img_col:
            return hdr_text_col, hdr_img_col

    if not data_rows:
        return (0, 1) if max_cols >= 2 else (0, -1)

    # 2. 对数据列计算「图片特征分」「纯序号特征」「平均文本长度」
    col_stats = []
    for ci in range(max_cols):
        vals = [r[ci].strip() for r in data_rows if ci < len(r) and r[ci].strip()]
        if not vals:
            col_stats.append({"ci": ci, "non_empty": 0, "img_score": 0.0, "avg_len": 0.0, "is_seq": False})
            continue
        img_score = sum(_cell_looks_like_image(v, all_imgs) for v in vals) / len(vals)
        avg_len = sum(len(v) for v in vals) / len(vals)
        is_seq = (
            max_cols >= 3
            and len(vals) >= 2
            and all(v.isdigit() for v in vals)
            and [int(v) for v in vals[: min(5, len(vals))]] == list(range(1, min(5, len(vals)) + 1))
        )
        col_stats.append({
            "ci": ci,
            "non_empty": len(vals),
            "img_score": img_score,
            "avg_len": avg_len,
            "is_seq": is_seq,
        })

    if max_cols == 2:
        c0, c1 = col_stats[0], col_stats[1]
        # 若第 1 列明显是图片名且第 2 列是长文案，自动选 (1, 0)；否则默认 (0, 1)
        if c0["img_score"] >= 0.6 and c1["img_score"] < 0.4 and c1["avg_len"] > c0["avg_len"]:
            return 1, 0
        return 0, 1

    # 3 列及以上（例如用户连同左侧「序号」列一起复制了：序号 | 断行文案 | 图片）
    non_seq = [s for s in col_stats if not s["is_seq"] and s["non_empty"] > 0]
    if not non_seq:
        non_seq = [s for s in col_stats if s["non_empty"] > 0] or col_stats

    # 文案列：优先选非图片特征且平均长度最长的列
    text_candidates = sorted(
        non_seq,
        key=lambda s: (1 if s["img_score"] < 0.5 else 0, s["avg_len"], s["non_empty"]),
        reverse=True,
    )
    text_col = hdr_text_col if hdr_text_col >= 0 else text_candidates[0]["ci"]

    # 图片列：在其余列中优先选 img_score 最高的列
    rem = [s for s in col_stats if s["ci"] != text_col and s["non_empty"] > 0]
    if hdr_img_col >= 0 and hdr_img_col != text_col:
        img_col = hdr_img_col
    elif rem:
        rem_non_seq = [s for s in rem if not s["is_seq"]] or rem
        best_img = max(rem_non_seq, key=lambda s: (s["img_score"], s["non_empty"], -s["avg_len"]))
        img_col = best_img["ci"]
    else:
        img_col = -1

    return text_col, img_col


class TableSegmentImportDialog(QDialog):
    """针对当前单个选中任务，从表格复制导入「断行后的文案」与「图片名称」的对话框。"""

    def __init__(self, project_model, project_path, config_manager=None, template_manager=None, parent=None):
        super().__init__(parent)
        self.project_model = project_model
        self.project_path = Path(project_path) if project_path else None
        self.config_manager = config_manager
        if self.config_manager:
            try:
                self.config_manager.load()
            except Exception:
                pass
        self.template_manager = template_manager
        self.all_imgs = list_project_images(self.project_path) if self.project_path else []
        self._raw_rows: list[list[str]] = []
        self._parsed_items: list[dict] = []
        self._updating_ui = False

        self.init_ui()
        # 打开窗口时若剪贴板已有表格数据，自动静默预读并展示预览
        self.read_from_clipboard(silent_if_empty=True)

    def init_ui(self):
        proj_id = getattr(self.project_model, "project_id", "") or (self.project_path.name if self.project_path else "当前任务")
        old_cnt = len(getattr(self.project_model, "spanish_segments", []) or [])

        self.setWindowTitle(f"📋 表格复制导入（断行文案 + 图片）— {proj_id}")
        self.resize(980, 680)
        self.setStyleSheet("""
            QDialog {
                background-color: #FAF6F0;
                color: #5D4037;
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
            }
            QLabel {
                color: #5D4037;
                font-size: 13px;
            }
            QPushButton {
                background-color: #E0A96D;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 7px 14px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #D2904C; }
            QPushButton:pressed { background-color: #B87635; }
            QPushButton:disabled { background-color: #BCAAA4; color: #EFEBE9; }
            QComboBox {
                background-color: white;
                color: #5D4037;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 13px;
                min-width: 130px;
            }
            QPlainTextEdit {
                background-color: white;
                color: #3E2723;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                font-family: Consolas, "Microsoft YaHei", monospace;
                font-size: 12px;
                padding: 6px;
            }
            QTableWidget {
                background-color: white;
                border: 1px solid #D7CCC8;
                gridline-color: #EFEBE9;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                border-radius: 4px;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #D7CCC8;
                color: #5D4037;
                padding: 5px;
                font-weight: bold;
                border: 1px solid #EFEBE9;
            }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # 1. 顶部任务确认说明横幅
        banner = QFrame()
        banner.setStyleSheet("QFrame { background-color: #EDE0D4; border: 1px solid #D7CCC8; border-radius: 6px; }")
        b_lay = QVBoxLayout(banner)
        b_lay.setContentsMargins(12, 8, 12, 8)
        b_lay.setSpacing(4)

        lbl_target = QLabel(f"🎯 <b>当前导入目标任务：</b><span style='color:#1D4ED8; font-weight:bold;'>{proj_id}</span>（仅针对当前选中的单个任务生效）")
        lbl_target.setTextFormat(Qt.TextFormat.RichText)
        b_lay.addWidget(lbl_target)

        lbl_rule = QLabel(
            f"📌 <b>导入规则：</b>仅导入<b>「断行后的文案」</b>与<b>「图片名称」</b>两列；"
            f"<b>时长</b>根据每句文案字符数按规则自动计算，<b>提示词</b>保持当前任务的模板与运镜选择方式。"
            f"（当前任务原有 <b>{old_cnt}</b> 个小任务，导入后将精确替换为新表格行数，<b>不会多出空任务</b>）"
        )
        lbl_rule.setWordWrap(True)
        lbl_rule.setTextFormat(Qt.TextFormat.RichText)
        b_lay.addWidget(lbl_rule)
        root.addWidget(banner)

        # 2. 工具栏：读取剪贴板 + 列映射 + 互换 + 跳过表头
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        self.btn_paste_clip = QPushButton("📋 从剪贴板读取表格")
        self.btn_paste_clip.setStyleSheet(
            "QPushButton { background-color: #2563EB; color: white; font-weight: bold; padding: 7px 16px; }"
            "QPushButton:hover { background-color: #1D4ED8; }"
        )
        self.btn_paste_clip.clicked.connect(lambda: self.read_from_clipboard(silent_if_empty=False))
        ctrl_row.addWidget(self.btn_paste_clip)

        ctrl_row.addSpacing(8)
        ctrl_row.addWidget(QLabel("<b>断行文案列:</b>"))
        self.combo_text_col = QComboBox()
        self.combo_text_col.currentIndexChanged.connect(self._on_mapping_changed)
        ctrl_row.addWidget(self.combo_text_col)

        ctrl_row.addWidget(QLabel("<b>图片名称列:</b>"))
        self.combo_img_col = QComboBox()
        self.combo_img_col.currentIndexChanged.connect(self._on_mapping_changed)
        ctrl_row.addWidget(self.combo_img_col)

        self.btn_swap_cols = QPushButton("⇄ 互换两列")
        self.btn_swap_cols.setToolTip("一键互换「断行文案列」与「图片名称列」")
        self.btn_swap_cols.setStyleSheet(
            "QPushButton { background-color: #0D9488; color: white; padding: 6px 12px; }"
            "QPushButton:hover { background-color: #0F766E; }"
        )
        self.btn_swap_cols.clicked.connect(self._swap_columns)
        ctrl_row.addWidget(self.btn_swap_cols)

        self.chk_skip_header = QCheckBox("跳过首行表头")
        self.chk_skip_header.setStyleSheet("font-weight: bold; color: #5D4037;")
        self.chk_skip_header.toggled.connect(self._on_mapping_changed)
        ctrl_row.addWidget(self.chk_skip_header)

        ctrl_row.addStretch()
        root.addLayout(ctrl_row)

        # 3. 上下分栏：上方可折叠/紧凑粘贴文本区 + 下方解析预览表
        splitter = QSplitter(Qt.Orientation.Vertical)

        paste_box = QWidget()
        p_lay = QVBoxLayout(paste_box)
        p_lay.setContentsMargins(0, 0, 0, 0)
        p_lay.setSpacing(4)
        p_lay.addWidget(QLabel("📝 表格原始数据区（可直接在此 Ctrl+V 粘贴 Excel / 飞书 / 谷歌表格复制的两列内容，也可直接编辑微调）："))
        self.txt_raw = QPlainTextEdit()
        self.txt_raw.setPlaceholderText(
            "示例（从 Excel 复制两列粘贴，制表符分隔）：\n"
            "Hola amigos bienvenidos a este video\tFC0001.jpg\n"
            "Hoy vamos a descobrir tres secretos importantes\tFC0002.jpg"
        )
        self.txt_raw.textChanged.connect(self._on_raw_text_edited)
        p_lay.addWidget(self.txt_raw)
        splitter.addWidget(paste_box)

        preview_box = QWidget()
        v_lay = QVBoxLayout(preview_box)
        v_lay.setContentsMargins(0, 0, 0, 0)
        v_lay.setSpacing(4)

        self.lbl_summary = QLabel("等待读取表格数据…")
        self.lbl_summary.setStyleSheet("font-weight: bold; color: #0F766E; font-size: 13px;")
        v_lay.addWidget(self.lbl_summary)

        self.table_preview = QTableWidget()
        self.table_preview.setColumnCount(6)
        self.table_preview.setHorizontalHeaderLabels([
            "序号", "断行后的文案（已自动去标点）", "字符数", "自动计算时长", "导入图片名", "本地素材匹配状态"
        ])
        self.table_preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table_preview.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_preview.setColumnWidth(0, 56)
        self.table_preview.setColumnWidth(2, 68)
        self.table_preview.setColumnWidth(3, 96)
        self.table_preview.setColumnWidth(4, 130)
        self.table_preview.setColumnWidth(5, 195)
        v_lay.addWidget(self.table_preview, 1)
        splitter.addWidget(preview_box)

        splitter.setSizes([145, 390])
        root.addWidget(splitter, 1)

        # 4. 底部确认按钮
        footer = QHBoxLayout()
        footer.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet(
            "QPushButton { background-color: #D7CCC8; color: #5D4037; padding: 8px 18px; }"
            "QPushButton:hover { background-color: #BCAAA4; }"
        )
        self.btn_cancel.clicked.connect(self.reject)
        footer.addWidget(self.btn_cancel)

        self.btn_confirm = QPushButton("✅ 确认导入并替换当前任务分句")
        self.btn_confirm.setStyleSheet(
            "QPushButton { background-color: #059669; color: white; font-weight: bold; padding: 8px 20px; font-size: 13px; }"
            "QPushButton:hover { background-color: #047857; }"
            "QPushButton:disabled { background-color: #9CA3AF; color: #E5E7EB; }"
        )
        self.btn_confirm.setEnabled(False)
        self.btn_confirm.clicked.connect(self._on_confirm_clicked)
        footer.addWidget(self.btn_confirm)

        root.addLayout(footer)

    def read_from_clipboard(self, silent_if_empty: bool = False):
        clipboard = QGuiApplication.clipboard()
        mime = clipboard.mimeData() if clipboard else None
        rows = []
        if mime is not None:
            if mime.hasHtml():
                rows = parse_table_rows_from_html(mime.html())
            if not rows and mime.hasText():
                rows = parse_table_rows_from_tsv(mime.text())

        if not rows:
            if not silent_if_empty:
                QMessageBox.warning(
                    self,
                    "剪贴板无有效表格数据",
                    "未能从剪贴板读取到表格内容。\n\n请先在 Excel / WPS / 飞书 / 谷歌表格中复制要导入的「断行文案 + 图片」区域后再点击读取，或直接在文本框内按 Ctrl+V 粘贴。",
                )
            return

        # 同步回显到文本框（触发列自动检测与预览表刷新）
        tsv_lines = ["\t".join(r) for r in rows]
        self._updating_ui = True
        self.txt_raw.setPlainText("\n".join(tsv_lines))
        self._updating_ui = False
        self._apply_new_raw_rows(rows, auto_detect=True)

    def _on_raw_text_edited(self):
        if self._updating_ui:
            return
        rows = parse_table_rows_from_tsv(self.txt_raw.toPlainText())
        self._apply_new_raw_rows(rows, auto_detect=True)

    def _apply_new_raw_rows(self, rows: list[list[str]], auto_detect: bool = True):
        self._raw_rows = rows
        max_cols = max((len(r) for r in rows), default=0)

        self._updating_ui = True
        prev_text_col = self.combo_text_col.currentData()
        prev_img_col = self.combo_img_col.currentData()

        self.combo_text_col.clear()
        self.combo_img_col.clear()
        self.combo_img_col.addItem("（不导入图片 / 按默认规则）", -1)

        col_count_for_ui = max(max_cols, 2)
        for ci in range(col_count_for_ui):
            sample = ""
            for r in rows[:2]:
                if ci < len(r) and r[ci].strip():
                    s = r[ci].strip()
                    sample = f" ({s[:12]}{'…' if len(s) > 12 else ''})"
                    break
            label = f"第 {ci + 1} 列{sample}"
            self.combo_text_col.addItem(label, ci)
            self.combo_img_col.addItem(label, ci)

        if auto_detect and rows:
            skip_hdr = is_likely_header_row(rows[0])
            self.chk_skip_header.setChecked(skip_hdr)
            t_col, i_col = auto_detect_text_and_image_cols(rows, skip_hdr, self.all_imgs)
        else:
            t_col = prev_text_col if prev_text_col is not None and 0 <= prev_text_col < col_count_for_ui else 0
            i_col = prev_img_col if prev_img_col is not None and -1 <= prev_img_col < col_count_for_ui else (1 if max_cols >= 2 else -1)

        t_idx = self.combo_text_col.findData(t_col)
        if t_idx >= 0:
            self.combo_text_col.setCurrentIndex(t_idx)
        i_idx = self.combo_img_col.findData(i_col)
        if i_idx >= 0:
            self.combo_img_col.setCurrentIndex(i_idx)

        self._updating_ui = False
        self._rebuild_preview()

    def _swap_columns(self):
        t_col = self.combo_text_col.currentData()
        i_col = self.combo_img_col.currentData()
        if t_col is None or i_col is None or i_col < 0:
            return
        self._updating_ui = True
        ti = self.combo_text_col.findData(i_col)
        ii = self.combo_img_col.findData(t_col)
        if ti >= 0:
            self.combo_text_col.setCurrentIndex(ti)
        if ii >= 0:
            self.combo_img_col.setCurrentIndex(ii)
        self._updating_ui = False
        self._rebuild_preview()

    def _on_mapping_changed(self):
        if self._updating_ui:
            return
        self._rebuild_preview()

    def _calc_duration(self, length: int, is_edge: bool) -> tuple[int, str]:
        if self.config_manager:
            return (
                self.config_manager.get_duration_for_length(length, is_edge=is_edge),
                self.config_manager.get_duration_label(length, is_edge=is_edge),
            )
        if length <= 40:
            return 4, "4s"
        if length <= 90:
            return 6, "6s"
        if length <= 130:
            return 8, "8s"
        if length <= 170:
            return 10, "10s"
        return 10, "超时 (>10s)"

    def _rebuild_preview(self):
        rows = self._raw_rows
        skip_hdr = self.chk_skip_header.isChecked()
        data_rows = rows[1:] if (skip_hdr and len(rows) >= 1) else rows
        t_col = self.combo_text_col.currentData()
        i_col = self.combo_img_col.currentData()
        t_col = int(t_col) if t_col is not None else 0
        i_col = int(i_col) if i_col is not None else -1

        # 严格过滤空文案行：绝不生成空任务！
        prelim = []
        skipped_empty = 0
        for r in data_rows:
            raw_text = r[t_col].strip() if 0 <= t_col < len(r) else ""
            clean_text = TextProcessor.remove_punctuation(raw_text).strip()
            if not clean_text:
                skipped_empty += 1
                continue
            raw_img = r[i_col].strip() if (i_col >= 0 and i_col < len(r)) else ""
            clean_img_input = Path(raw_img.replace("\\", "/")).name.strip().strip('"\'') if raw_img else ""
            prelim.append((clean_text, clean_img_input))

        total = len(prelim)
        parsed = []
        matched_cnt = 0
        for idx, (clean_text, clean_img_input) in enumerate(prelim):
            length = len(clean_text)
            is_edge = (idx == 0 or idx == total - 1)
            dur_val, dur_label = self._calc_duration(length, is_edge=is_edge)

            effective_img = ""
            status_text = "⚪ 未指定 (按默认规则匹配)"
            status_color = "#6B7280"
            if clean_img_input:
                matched_obj = match_explicit_image(clean_img_input, self.all_imgs) if self.all_imgs else None
                if matched_obj is not None:
                    effective_img = matched_obj.name
                    matched_cnt += 1
                    status_text = f"✅ 已匹配: {matched_obj.name}"
                    status_color = "#059669"
                elif not self.all_imgs:
                    effective_img = clean_img_input
                    status_text = f"📌 已记录: {clean_img_input} (待下载素材)"
                    status_color = "#2563EB"
                else:
                    effective_img = clean_img_input
                    status_text = f"⚠️ 本地未找到: {clean_img_input}"
                    status_color = "#D97706"

            parsed.append({
                "text": clean_text,
                "length": length,
                "duration": dur_val,
                "duration_label": dur_label,
                "raw_img": clean_img_input,
                "effective_img": effective_img,
                "status_text": status_text,
                "status_color": status_color,
            })

        self._parsed_items = parsed
        self.table_preview.setRowCount(total)
        for idx, item in enumerate(parsed):
            c0 = QTableWidgetItem(str(idx + 1))
            c0.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            c1 = QTableWidgetItem(item["text"])
            c2 = QTableWidgetItem(str(item["length"]))
            c2.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            c3 = QTableWidgetItem(item["duration_label"])
            c3.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if "超时" in item["duration_label"]:
                c3.setForeground(QColor("#DC2626"))
            c4 = QTableWidgetItem(item["raw_img"] or "—")
            c4.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            c5 = QTableWidgetItem(item["status_text"])
            c5.setForeground(QColor(item["status_color"]))

            for col_i, cell in enumerate((c0, c1, c2, c3, c4, c5)):
                cell.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table_preview.setItem(idx, col_i, cell)

        old_cnt = len(getattr(self.project_model, "spanish_segments", []) or [])
        if total == 0:
            self.lbl_summary.setText("⚠️ 当前尚未识别到有效断行文案，请点击「📋 从剪贴板读取表格」或在上方粘贴两列数据。")
            self.btn_confirm.setEnabled(False)
        else:
            extra_note = f"（已自动忽略 {skipped_empty} 个空行）" if skipped_empty > 0 else ""
            img_note = f"本地已匹配 {matched_cnt}/{total} 张图片" if self.all_imgs else "本地尚未下载图片（下载后将自动按导入名称匹配）"
            self.lbl_summary.setText(
                f"✅ 共解析出 {total} 个有效小任务 {extra_note}｜原任务 {old_cnt} 个 → 导入后精确变为 {total} 个（绝不残留空任务）｜{img_note}"
            )
            self.btn_confirm.setEnabled(True)

    def _on_confirm_clicked(self):
        if not self._parsed_items:
            QMessageBox.warning(self, "提示", "没有可导入的有效断行文案！")
            return
        self.accept()

    def build_new_segments(self) -> list[dict]:
        """构造精确等于有效导入行数的全新 spanish_segments 列表（不保留多余旧行或空行）。"""
        default_mode = (
            getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES")
            if self.config_manager
            else "VIDEO_FRAMES"
        )
        segments = []
        for item in self._parsed_items:
            segments.append({
                "text": item["text"],
                "length": item["length"],
                "duration": item["duration"],
                "image_name": item["effective_img"],
                "end_image_name": "",
                "template_id": "",
                "motion_id": "",
                "mode": default_mode,
                "mode_overridden": False,
                "copied": False,
                "completed": False,
            })
        return segments
