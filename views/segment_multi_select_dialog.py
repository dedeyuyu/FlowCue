# -*- coding: utf-8 -*-
"""
「🖼️ 多选与图片预设可视化管理」独立大窗 (SegmentVisualBatchManagerDialog)

核心特性：
1. 任务内联切换：顶部直接提供「⬅ 上一个任务 / 任务下拉框 / 下一个任务 ➡」，无需关闭窗口即可在所有项目任务间无缝切换。
2. 顶部预设选项卡区域：多选断句后，直接在上方选择「📐 提示词模板」「🎥 运镜预设」「⚙️ 生成模式」「⏱️ 视频时长」，立即批量应用并自动保存；同时支持修改当前任务的全局统一模板与运镜。
3. 可折叠/展开的「🖼️ 任务资源图库」区域：位于预设选项下方、断句图片网格上方，直观展示当前任务 `downloads/` 下的所有图片资源；多选下方断句卡片后，单击任意资源图即可一键批量更换所选断句的图片！支持随时收起/展开。
4. 断句任务图片多排网格主视图：
   - 以图片为绝对视觉核心，一行多个、多排平铺展示当前任务所有断句的图片、序号、图片名、预设标签与文案预览。
   - 支持按住 `Ctrl + 鼠标滚轮` 无级缩放图片卡片大小（自动重排每行个数）。
   - 支持 单击、`Ctrl + 单击`、`Shift + 连选`、以及鼠标拖拽 **橡皮筋框选 (Marquee Box Selection)** 批量选择多个断句图片。
"""
import os
import re
import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QScrollArea, QFrame, QSlider, QFileDialog, QMessageBox,
    QToolTip, QSizePolicy, QCheckBox, QTabWidget, QListWidget, QListWidgetItem,
    QLineEdit, QSplitter, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QInputDialog
)
from PyQt6.QtCore import Qt, QRect, QPoint, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
    QCursor, QKeySequence, QShortcut
)

from models.project_model import ProjectModel
from models.template_manager import PRESET_COLOR_PALETTE, get_preset_color_info
from services.text_processor import TextProcessor
import uuid

IMG_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def _load_qpixmap_fast(img_path: str, cache: dict) -> QPixmap:
    """带内存缓存的 QPixmap 加载器（兼容 WebP/PNG/JPG）"""
    if not img_path:
        return QPixmap()
    try:
        st = os.stat(img_path)
        key = (img_path, st.st_mtime_ns, st.st_size)
    except Exception:
        return QPixmap()
    if key in cache:
        return cache[key]

    pm = QPixmap(img_path)
    if pm.isNull():
        try:
            from PIL import Image
            with Image.open(img_path) as pil_img:
                rgba = pil_img.convert("RGBA")
                w, h = rgba.size
                qimg = QImage(rgba.tobytes("raw", "RGBA"), w, h, QImage.Format.Format_RGBA8888).copy()
                pm = QPixmap.fromImage(qimg)
        except Exception:
            pm = QPixmap()
    if len(cache) > 600:
        cache.clear()
    cache[key] = pm
    return pm


class ResourceImageCard(QFrame):
    """上方「任务资源图库」中的单张资源图卡片：点击即可将该资源图批量应用到下方所有已选断句"""
    clicked_resource = pyqtSignal(str)  # image_name

    def __init__(self, img_path: Path, pixmap: QPixmap, usage_count: int = 0, parent=None):
        super().__init__(parent)
        self.img_path = img_path
        self.image_name = img_path.name
        self.usage_count = usage_count
        self.setFixedSize(132, 134)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"🖼️ 资源图: {self.image_name}\n"
            f"📊 当前被 {usage_count} 个断句使用\n"
            f"💡 先在下方多选断句图片，再点击此资源图即可一键批量更换！"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(3)

        self.lbl_img = QLabel()
        self.lbl_img.setFixedSize(120, 88)
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_img.setStyleSheet("background-color: #1E293B; border-radius: 5px; color: #94A3B8; font-size: 11px;")
        if not pixmap.isNull():
            self.lbl_img.setPixmap(
                pixmap.scaled(
                    120, 88,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )
        else:
            self.lbl_img.setText("无法预览")
        lay.addWidget(self.lbl_img)

        bottom_row = QHBoxLayout()
        bottom_row.setContentsMargins(1, 0, 1, 0)
        bottom_row.setSpacing(2)

        disp_name = self.image_name if len(self.image_name) <= 12 else self.image_name[:10] + "…"
        lbl_name = QLabel(disp_name)
        lbl_name.setStyleSheet("font-size: 11px; font-weight: bold; color: #334155; border: none; background: transparent;")
        bottom_row.addWidget(lbl_name)
        bottom_row.addStretch()

        badge = QLabel(f"{usage_count}句")
        badge.setStyleSheet(
            "font-size: 10px; font-weight: bold; padding: 1px 5px; border-radius: 3px; border: none; "
            + ("background: #DBEAFE; color: #1D4ED8;" if usage_count > 0 else "background: #F1F5F9; color: #64748B;")
        )
        bottom_row.addWidget(badge)
        lay.addLayout(bottom_row)

        self.setStyleSheet("""
            ResourceImageCard {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 7px;
            }
            ResourceImageCard:hover {
                background-color: #EFF6FF;
                border: 2px solid #2563EB;
            }
        """)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked_resource.emit(self.image_name)
            event.accept()
            return
        super().mousePressEvent(event)


class SegmentCardGridViewport(QWidget):
    """
    高性能断句图片多排网格画布：
    - 直接使用 QPainter 绘制每张断句卡片（以图片为主体 + 序号角标 + 预设标签 + 文案摘要），支持上百个断句 60fps 丝滑缩放与框选！
    - 开启「首尾帧模式」时，每张卡片的图片区自动分为上下两个独立可选板块（上：📸首帧，下：🎬尾帧），共享底部的模板/运镜预设与文案。
    - 支持：
      1. Ctrl + 鼠标滚轮：实时无级调整卡片尺寸（card_width 130px ~ 440px），自动计算每行排列数量
      2. 鼠标左键单击：单选卡片（首尾帧模式下单选对应的首帧或尾帧板块）
      3. Ctrl + 左键单击：切换单个卡片/板块选中状态
      4. Shift + 左键单击：范围连选 [anchor .. clicked]（首尾帧模式下同类型板块连选只选中对应首帧或尾帧板块）
      5. 鼠标左键拖拽（橡皮筋框选）：画出半透明选框，自动选中框内所有卡片/上下板块（按住 Ctrl/Shift 拖拽可追加框选）
    """
    selection_changed = pyqtSignal(list)      # sorted list of selected card indices
    zoom_changed = pyqtSignal(int)            # new card_width
    card_double_clicked = pyqtSignal(int)     # segment index

    def __init__(self, parent_dialog=None):
        super().__init__(parent_dialog)
        self.dialog = parent_dialog
        self.card_width = 230
        self.card_gap = 12
        self.margin = 14

        self.selected_indices = set()
        self.selected_slots = set()   # set of (idx, "start" | "end")
        self.anchor_index = 0
        self.anchor_slot = (0, "start")
        self.hover_index = -1
        self.hover_slot = (-1, "")

        self._is_dragging_box = False
        self._drag_origin = QPoint()
        self._drag_current = QPoint()
        self._drag_base_slots = set()
        self._pressed_slot = (-1, "")
        self._press_modifiers = Qt.KeyboardModifier.NoModifier

        self._card_rects = []   # list of QRect for each segment
        self._slot_rects = []   # list of {"start": QRect, "end": QRect | None} for each segment
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _is_end_frame_mode(self) -> bool:
        return bool(getattr(self.dialog, "end_frame_mode", False))

    def _sync_indices_from_slots(self):
        if not self._is_end_frame_mode():
            self.selected_slots = {(idx, "start") for idx, _ in self.selected_slots}
        self.selected_indices = {idx for idx, _ in self.selected_slots}

    def set_card_width(self, width: int, emit_signal: bool = True):
        clamped = max(130, min(440, int(width)))
        if clamped == self.card_width:
            return
        self.card_width = clamped
        self.recalculate_layout()
        self.update()
        if emit_signal:
            self.zoom_changed.emit(self.card_width)

    def _get_segments(self) -> list:
        if not self.dialog or not self.dialog.project_model:
            return []
        return self.dialog.project_model.spanish_segments or []

    def _compute_slot_image_height(self) -> int:
        if self._is_end_frame_mode():
            return max(86, int(self.card_width * 0.60))
        return int(self.card_width * 0.72)

    def _compute_card_height(self) -> int:
        slot_h = self._compute_slot_image_height()
        if self._is_end_frame_mode():
            # 上板块(首帧) + 中间分隔带(8px) + 下板块(尾帧) + 底部共享预设与文案(94px)
            return 6 + slot_h + 8 + slot_h + 94
        return slot_h + 94

    def recalculate_layout(self):
        segs = self._get_segments()
        count = len(segs)
        if count == 0:
            self._card_rects = []
            self._slot_rects = []
            self.setMinimumHeight(260)
            return

        avail_w = max(200, self.width() - self.margin * 2)
        cols = max(1, (avail_w + self.card_gap) // (self.card_width + self.card_gap))
        card_h = self._compute_card_height()
        slot_h = self._compute_slot_image_height()
        end_mode = self._is_end_frame_mode()

        rects = []
        slot_rects = []
        for idx in range(count):
            r = idx // cols
            c = idx % cols
            x = self.margin + c * (self.card_width + self.card_gap)
            y = self.margin + r * (card_h + self.card_gap)
            crect = QRect(x, y, self.card_width, card_h)
            rects.append(crect)
            if end_mode:
                s_rect = QRect(crect.left() + 6, crect.top() + 6, crect.width() - 12, slot_h)
                e_rect = QRect(crect.left() + 6, s_rect.bottom() + 9, crect.width() - 12, slot_h)
                slot_rects.append({"start": s_rect, "end": e_rect})
            else:
                s_rect = QRect(crect.left() + 6, crect.top() + 6, crect.width() - 12, slot_h - 6)
                slot_rects.append({"start": s_rect, "end": None})

        self._card_rects = rects
        self._slot_rects = slot_rects
        total_rows = (count + cols - 1) // cols
        total_h = self.margin * 2 + total_rows * card_h + max(0, total_rows - 1) * self.card_gap + 20
        self.setMinimumHeight(max(300, total_h))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.recalculate_layout()

    def _slot_at_pos(self, pos: QPoint):
        end_mode = self._is_end_frame_mode()
        for idx, crect in enumerate(self._card_rects):
            if not crect.contains(pos):
                continue
            if end_mode and idx < len(self._slot_rects):
                sr = self._slot_rects[idx]
                e_rect = sr.get("end")
                s_rect = sr.get("start")
                if e_rect is not None and e_rect.contains(pos):
                    return idx, "end"
                if s_rect is not None and s_rect.contains(pos):
                    return idx, "start"
                # 点击中间分隔条或底部预设/文案区：按离上下板块位置归属，底部文案区默认选中首帧板块以便快捷改预设
                if e_rect is not None and pos.y() >= e_rect.top() and pos.y() <= e_rect.bottom() + 4:
                    return idx, "end"
            return idx, "start"
        return -1, ""

    def _index_at_pos(self, pos: QPoint) -> int:
        idx, _ = self._slot_at_pos(pos)
        return idx

    def select_all(self):
        segs = self._get_segments()
        if self._is_end_frame_mode():
            self.selected_slots = {(i, "start") for i in range(len(segs))} | {(i, "end") for i in range(len(segs))}
        else:
            self.selected_slots = {(i, "start") for i in range(len(segs))}
        self._sync_indices_from_slots()
        self.update()
        self.selection_changed.emit(sorted(self.selected_indices))

    def select_all_by_slot(self, slot_role: str):
        segs = self._get_segments()
        role = "end" if (slot_role == "end" and self._is_end_frame_mode()) else "start"
        self.selected_slots = {(i, role) for i in range(len(segs))}
        if segs:
            self.anchor_index = 0
            self.anchor_slot = (0, role)
        self._sync_indices_from_slots()
        self.update()
        self.selection_changed.emit(sorted(self.selected_indices))

    def clear_selection(self):
        self.selected_slots.clear()
        self.selected_indices.clear()
        self.update()
        self.selection_changed.emit([])

    def invert_selection(self):
        segs = self._get_segments()
        if self._is_end_frame_mode():
            all_slots = {(i, "start") for i in range(len(segs))} | {(i, "end") for i in range(len(segs))}
            self.selected_slots = all_slots - self.selected_slots
        else:
            all_slots = {(i, "start") for i in range(len(segs))}
            self.selected_slots = all_slots - {(i, "start") for i in self.selected_indices}
        self._sync_indices_from_slots()
        self.update()
        self.selection_changed.emit(sorted(self.selected_indices))

    def set_selected_indices(self, indices, emit_signal: bool = True):
        segs = self._get_segments()
        total = len(segs)
        valid = {i for i in indices if 0 <= i < total}
        self.selected_slots = {(i, "start") for i in valid}
        self._sync_indices_from_slots()
        if self.selected_indices:
            self.anchor_index = min(self.selected_indices)
            self.anchor_slot = (self.anchor_index, "start")
        self.update()
        if emit_signal:
            self.selection_changed.emit(sorted(self.selected_indices))

    def on_end_frame_mode_changed(self):
        self._sync_indices_from_slots()
        self.recalculate_layout()
        self.update()
        self.selection_changed.emit(sorted(self.selected_indices))

    def wheelEvent(self, event):
        modifiers = event.modifiers()
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta != 0:
                step = 22 if delta > 0 else -22
                self.set_card_width(self.card_width + step, emit_signal=True)
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            self._drag_origin = pos
            self._drag_current = pos
            self._is_dragging_box = False
            self._pressed_slot = self._slot_at_pos(pos)
            self._press_modifiers = event.modifiers()
            if (self._press_modifiers & Qt.KeyboardModifier.ControlModifier) or (
                self._press_modifiers & Qt.KeyboardModifier.ShiftModifier
            ):
                self._drag_base_slots = set(self.selected_slots)
            else:
                self._drag_base_slots = set()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if event.buttons() & Qt.MouseButton.LeftButton:
            if not self._is_dragging_box and (pos - self._drag_origin).manhattanLength() >= 6:
                self._is_dragging_box = True

            if self._is_dragging_box:
                self._drag_current = pos
                box = QRect(self._drag_origin, self._drag_current).normalized()
                hit_slots = set()
                if self._is_end_frame_mode():
                    for idx, sr in enumerate(self._slot_rects):
                        s_rect = sr.get("start")
                        e_rect = sr.get("end")
                        if s_rect is not None and box.intersects(s_rect):
                            hit_slots.add((idx, "start"))
                        if e_rect is not None and box.intersects(e_rect):
                            hit_slots.add((idx, "end"))
                        # 若框选仅扫过卡片底部文案区，默认归入首帧板块
                        if (
                            idx < len(self._card_rects)
                            and box.intersects(self._card_rects[idx])
                            and (idx, "start") not in hit_slots
                            and (idx, "end") not in hit_slots
                        ):
                            hit_slots.add((idx, "start"))
                else:
                    for idx, r in enumerate(self._card_rects):
                        if box.intersects(r):
                            hit_slots.add((idx, "start"))
                new_slots = self._drag_base_slots | hit_slots
                if new_slots != self.selected_slots:
                    self.selected_slots = new_slots
                    self._sync_indices_from_slots()
                    self.selection_changed.emit(sorted(self.selected_indices))
                self.update()
                event.accept()
                return

        hov_idx, hov_role = self._slot_at_pos(pos)
        if (hov_idx, hov_role) != self.hover_slot or hov_idx != self.hover_index:
            self.hover_index = hov_idx
            self.hover_slot = (hov_idx, hov_role)
            self.update()
            if hov_idx >= 0:
                segs = self._get_segments()
                if hov_idx < len(segs):
                    seg = segs[hov_idx]
                    tpl_name, mot_name, mode_name, dur_label = self.dialog.get_segment_display_badges(hov_idx, seg)
                    img_name = seg.get("image_name") or "未绑定"
                    end_img = seg.get("end_image_name") or ""
                    if self._is_end_frame_mode():
                        panel_hint = "【当前悬停：下板块 · 🎬 尾帧】" if hov_role == "end" else "【当前悬停：上板块 · 📸 首帧】"
                        end_line = f"\n🎬 尾帧图片: {end_img or '未选择 (默认不自动分配)'}"
                    else:
                        panel_hint = ""
                        end_line = f"\n🎬 尾帧图片: {end_img}" if end_img else ""
                    tip = (
                        f"【第 {hov_idx + 1:02d} 句】{(' ' + panel_hint) if panel_hint else ''}\n"
                        f"📸 首帧图片: {img_name}{end_line}\n"
                        f"📐 模板预设: {tpl_name}\n"
                        f"🎥 运镜预设: {mot_name}\n"
                        f"⚙️ 生成模式: {mode_name}  |  ⏱️ 时长: {dur_label}\n"
                        f"📝 文案: {seg.get('text', '')}"
                    )
                    QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_dragging_box:
                self._is_dragging_box = False
                self.update()
                event.accept()
                return

            idx, role = self._pressed_slot
            if not self._is_end_frame_mode() and idx >= 0:
                role = "start"
            mods = self._press_modifiers
            if idx < 0:
                if not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                    self.selected_slots.clear()
                    self.selected_indices.clear()
                    self.selection_changed.emit([])
                    self.update()
            else:
                target_slot = (idx, role or "start")
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    anc_idx, anc_role = self.anchor_slot if self.anchor_slot[0] >= 0 else (self.anchor_index, target_slot[1])
                    if not self._is_end_frame_mode():
                        anc_role = "start"
                    start_i = min(anc_idx, idx)
                    end_i = max(anc_idx, idx)
                    if not self._is_end_frame_mode() or anc_role == target_slot[1]:
                        # 相同板块（如首帧→首帧，或尾帧→尾帧）：仅连选该板块！
                        slot_set = {(i, target_slot[1]) for i in range(start_i, end_i + 1)}
                    else:
                        # 跨首帧与尾帧连选：按线性板块顺序选中
                        segs_len = len(self._get_segments())
                        ordered = []
                        for i in range(segs_len):
                            ordered.append((i, "start"))
                            ordered.append((i, "end"))
                        try:
                            p1 = ordered.index((anc_idx, anc_role))
                            p2 = ordered.index(target_slot)
                            lo, hi = min(p1, p2), max(p1, p2)
                            slot_set = set(ordered[lo:hi + 1])
                        except ValueError:
                            slot_set = {(i, target_slot[1]) for i in range(start_i, end_i + 1)}
                    if mods & Qt.KeyboardModifier.ControlModifier:
                        self.selected_slots |= slot_set
                    else:
                        self.selected_slots = slot_set
                elif mods & Qt.KeyboardModifier.ControlModifier:
                    if target_slot in self.selected_slots:
                        self.selected_slots.remove(target_slot)
                    else:
                        self.selected_slots.add(target_slot)
                    self.anchor_index = idx
                    self.anchor_slot = target_slot
                else:
                    self.selected_slots = {target_slot}
                    self.anchor_index = idx
                    self.anchor_slot = target_slot

                self._sync_indices_from_slots()
                self.selection_changed.emit(sorted(self.selected_indices))
                self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self._index_at_pos(event.position().toPoint())
            if idx >= 0:
                self.card_double_clicked.emit(idx)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Background
        from services.theme_manager import ThemeManager
        is_dark = ThemeManager.is_dark()
        painter.fillRect(self.rect(), QColor("#18181B" if is_dark else "#F8FAFC"))

        segs = self._get_segments()
        if not segs:
            painter.setPen(QColor("#A1A1AA" if is_dark else "#64748B"))
            f = painter.font()
            f.setPointSize(13)
            f.setBold(True)
            painter.setFont(f)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "当前任务暂无切分断句")
            return

        end_mode = self._is_end_frame_mode()
        if len(self._card_rects) != len(segs) or len(self._slot_rects) != len(segs):
            self.recalculate_layout()

        clip_rect = event.rect()

        font_idx = QFont("Microsoft YaHei", 9 if end_mode else 10, QFont.Weight.Bold)
        font_tag = QFont("Microsoft YaHei", 8, QFont.Weight.Bold)
        font_text = QFont("Microsoft YaHei", 9)
        fm_idx = QFontMetrics(font_idx)
        fm_tag = QFontMetrics(font_tag)

        for idx, card_rect in enumerate(self._card_rects):
            if not card_rect.intersects(clip_rect):
                continue

            seg = segs[idx]
            is_start_sel = (idx, "start") in self.selected_slots
            is_end_sel = end_mode and ((idx, "end") in self.selected_slots)
            is_sel = is_start_sel or is_end_sel
            is_hov = idx == self.hover_index

            # Check if segment has individual preset override (follows unified -> card_color_info is None)
            card_color_info, tpl_color_info, mot_color_info = self.dialog.get_segment_card_color_info(seg)

            # 1. Card background & border
            if card_color_info is not None:
                bg_color = QColor(card_color_info["dark_bg"] if is_dark else card_color_info["bg"])
                if is_sel:
                    border_color = QColor("#7C3AED" if (is_end_sel and not is_start_sel) else ("#3B82F6" if is_dark else "#2563EB"))
                elif is_hov:
                    border_color = QColor("#F59E0B")
                else:
                    border_color = QColor(card_color_info["dark_border"] if is_dark else card_color_info["border"])
                border_width = 3 if is_sel else 2
            else:
                if is_dark:
                    bg_color = QColor("#1E293B") if is_sel else (QColor("#2E2A1E") if is_hov else QColor("#242429"))
                    border_color = QColor("#A855F7" if (is_end_sel and not is_start_sel) else "#3B82F6") if is_sel else (QColor("#F59E0B") if is_hov else QColor("#3F3F46"))
                else:
                    bg_color = QColor("#F5F3FF" if (is_end_sel and not is_start_sel) else "#EFF6FF") if is_sel else (QColor("#FFFBEB") if is_hov else QColor("#FFFFFF"))
                    border_color = QColor("#7C3AED" if (is_end_sel and not is_start_sel) else "#2563EB") if is_sel else (QColor("#F59E0B") if is_hov else QColor("#CBD5E1"))
                border_width = 3 if is_sel else (2 if is_hov else 1)

            painter.setPen(QPen(border_color, border_width))
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(card_rect.adjusted(1, 1, -1, -1), 8, 8)

            tpl_name, mot_name, mode_name, dur_label = self.dialog.get_segment_display_badges(idx, seg)
            sr = self._slot_rects[idx]
            start_rect = sr["start"]
            end_rect = sr["end"]

            if not end_mode:
                # ── 单图模式（未开启首尾帧模式）──
                img_rect = start_rect
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#0F172A")))
                painter.drawRoundedRect(img_rect, 6, 6)

                pm = self.dialog.get_segment_pixmap(idx, seg)
                if not pm.isNull():
                    scaled = pm.scaled(
                        img_rect.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    px = img_rect.left() + (img_rect.width() - scaled.width()) // 2
                    py = img_rect.top() + (img_rect.height() - scaled.height()) // 2
                    painter.drawPixmap(px, py, scaled)
                else:
                    painter.setPen(QColor("#64748B"))
                    painter.setFont(font_text)
                    painter.drawText(img_rect, Qt.AlignmentFlag.AlignCenter, "📷 无关联图片")

                # Top-left #Index + checkbox indicator overlay
                badge_str = f"{'☑' if is_sel else '☐'} #{idx + 1:02d}"
                painter.setFont(font_idx)
                bw = fm_idx.horizontalAdvance(badge_str) + 14
                idx_rect = QRect(img_rect.left() + 6, img_rect.top() + 6, bw, 22)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#2563EB") if is_sel else QColor(15, 23, 42, 200)))
                painter.drawRoundedRect(idx_rect, 5, 5)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(idx_rect, Qt.AlignmentFlag.AlignCenter, badge_str)

                # Top-right duration badge
                painter.setFont(font_tag)
                dw = fm_tag.horizontalAdvance(dur_label) + 10
                dur_rect = QRect(img_rect.right() - dw - 6, img_rect.top() + 6, dw, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#DC2626") if "超时" in dur_label else QColor(15, 23, 42, 200)))
                painter.drawRoundedRect(dur_rect, 4, 4)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(dur_rect, Qt.AlignmentFlag.AlignCenter, dur_label)

                # Bottom of image: Image filename bar
                img_name = seg.get("image_name") or "未指定图片"
                img_label_str = f"📸 {img_name}"
                name_bar_rect = QRect(img_rect.left(), img_rect.bottom() - 21, img_rect.width(), 22)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(15, 23, 42, 195)))
                painter.drawRoundedRect(name_bar_rect, 4, 4)
                painter.setPen(QColor("#F8FAFC"))
                painter.setFont(font_tag)
                elided_img = fm_tag.elidedText(img_label_str, Qt.TextElideMode.ElideMiddle, name_bar_rect.width() - 10)
                painter.drawText(name_bar_rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_img)
                tags_y = img_rect.bottom() + 5
            else:
                # ── 首尾帧双板块模式（上：📸首帧板块，下：🎬尾帧板块）──
                is_start_hov = self.hover_slot == (idx, "start")
                is_end_hov = self.hover_slot == (idx, "end")

                # [A] 上板块：首帧 (Start Frame)
                s_border = QColor("#2563EB") if is_start_sel else (QColor("#F59E0B") if is_start_hov else QColor("#475569"))
                s_bw = 3 if is_start_sel else (2 if is_start_hov else 1)
                painter.setPen(QPen(s_border, s_bw))
                painter.setBrush(QBrush(QColor("#0F172A")))
                painter.drawRoundedRect(start_rect, 6, 6)

                pm_start = self.dialog.get_segment_pixmap(idx, seg)
                if not pm_start.isNull():
                    scaled_s = pm_start.scaled(
                        start_rect.adjusted(2, 2, -2, -2).size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    px = start_rect.left() + (start_rect.width() - scaled_s.width()) // 2
                    py = start_rect.top() + (start_rect.height() - scaled_s.height()) // 2
                    painter.drawPixmap(px, py, scaled_s)
                else:
                    painter.setPen(QColor("#94A3B8"))
                    painter.setFont(font_tag)
                    painter.drawText(start_rect, Qt.AlignmentFlag.AlignCenter, "📸 未选择首帧")

                s_badge = f"{'☑' if is_start_sel else '☐'} #{idx + 1:02d} 首帧"
                painter.setFont(font_idx)
                s_bw_px = fm_idx.horizontalAdvance(s_badge) + 12
                s_idx_rect = QRect(start_rect.left() + 5, start_rect.top() + 5, s_bw_px, 21)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#2563EB") if is_start_sel else QColor(15, 23, 42, 210)))
                painter.drawRoundedRect(s_idx_rect, 4, 4)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(s_idx_rect, Qt.AlignmentFlag.AlignCenter, s_badge)

                # Top-right duration badge on upper panel
                painter.setFont(font_tag)
                dw = fm_tag.horizontalAdvance(dur_label) + 10
                dur_rect = QRect(start_rect.right() - dw - 5, start_rect.top() + 5, dw, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#DC2626") if "超时" in dur_label else QColor(15, 23, 42, 205)))
                painter.drawRoundedRect(dur_rect, 4, 4)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(dur_rect, Qt.AlignmentFlag.AlignCenter, dur_label)

                img_name = seg.get("image_name") or "未指定首帧"
                s_bar_rect = QRect(start_rect.left() + 1, start_rect.bottom() - 20, start_rect.width() - 2, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(37, 99, 235, 215) if is_start_sel else QColor(15, 23, 42, 200)))
                painter.drawRoundedRect(s_bar_rect, 4, 4)
                painter.setPen(QColor("#F8FAFC"))
                painter.setFont(font_tag)
                elided_s = fm_tag.elidedText(f"📸 首帧: {img_name}", Qt.TextElideMode.ElideMiddle, s_bar_rect.width() - 10)
                painter.drawText(s_bar_rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_s)

                # [B] 上下板块分界线
                div_y = (start_rect.bottom() + end_rect.top()) // 2
                painter.setPen(QPen(QColor("#94A3B8" if not is_dark else "#52525B"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(card_rect.left() + 10, div_y, card_rect.right() - 10, div_y)

                # [C] 下板块：尾帧 (End Frame) — 默认不自动分配，留空由用户手动选择
                end_name = (seg.get("end_image_name") or "").strip()
                pm_end = self.dialog.get_segment_end_pixmap(idx, seg) if end_name else QPixmap()
                has_end = bool(end_name and not pm_end.isNull())

                if is_end_sel:
                    e_pen = QPen(QColor("#7C3AED"), 3, Qt.PenStyle.SolidLine)
                elif is_end_hov:
                    e_pen = QPen(QColor("#F59E0B"), 2, Qt.PenStyle.SolidLine)
                elif has_end:
                    e_pen = QPen(QColor("#8B5CF6"), 1, Qt.PenStyle.SolidLine)
                else:
                    e_pen = QPen(QColor("#64748B" if not is_dark else "#52525B"), 1, Qt.PenStyle.DashLine)

                painter.setPen(e_pen)
                painter.setBrush(QBrush(QColor("#0F172A") if has_end else QColor("#1E293B" if is_dark else "#F1F5F9")))
                painter.drawRoundedRect(end_rect, 6, 6)

                if has_end:
                    scaled_e = pm_end.scaled(
                        end_rect.adjusted(2, 2, -2, -2).size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    epx = end_rect.left() + (end_rect.width() - scaled_e.width()) // 2
                    epy = end_rect.top() + (end_rect.height() - scaled_e.height()) // 2
                    painter.drawPixmap(epx, epy, scaled_e)
                else:
                    painter.setPen(QColor("#7C3AED" if is_end_sel else ("#A1A1AA" if is_dark else "#64748B")))
                    painter.setFont(font_tag)
                    empty_hint = "🎬 未选尾帧\n点击此板块后点上方资源图"
                    painter.drawText(end_rect.adjusted(6, 18, -6, -18), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, empty_hint)

                e_badge = f"{'☑' if is_end_sel else '☐'} #{idx + 1:02d} 尾帧"
                painter.setFont(font_idx)
                e_bw_px = fm_idx.horizontalAdvance(e_badge) + 12
                e_idx_rect = QRect(end_rect.left() + 5, end_rect.top() + 5, e_bw_px, 21)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor("#7C3AED") if is_end_sel else (QColor("#5B21B6") if has_end else QColor(71, 85, 105, 200))))
                painter.drawRoundedRect(e_idx_rect, 4, 4)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(e_idx_rect, Qt.AlignmentFlag.AlignCenter, e_badge)

                e_bar_rect = QRect(end_rect.left() + 1, end_rect.bottom() - 20, end_rect.width() - 2, 20)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(124, 58, 237, 220) if is_end_sel else (QColor(30, 27, 75, 205) if has_end else QColor(51, 65, 85, 185))))
                painter.drawRoundedRect(e_bar_rect, 4, 4)
                painter.setPen(QColor("#F8FAFC"))
                painter.setFont(font_tag)
                e_bar_label = f"🎬 尾帧: {end_name}" if end_name else "🎬 尾帧: 未选择"
                elided_e = fm_tag.elidedText(e_bar_label, Qt.TextElideMode.ElideMiddle, e_bar_rect.width() - 10)
                painter.drawText(e_bar_rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_e)

                tags_y = end_rect.bottom() + 5

            # 6. Preset badges row (Template / Motion / Mode) — 开启首尾帧后仍旧只有一个描述词预设、一个运镜预设、一个文案
            has_custom_tpl = tpl_color_info is not None
            has_custom_mot = mot_color_info is not None
            has_custom_mode = bool(seg.get("mode_overridden"))

            if is_dark:
                tpl_t_bg = tpl_color_info["dark_border"] if tpl_color_info else "#27272A"
                tpl_t_fg = "#FFFFFF" if tpl_color_info else "#D4D4D8"
                mot_t_bg = mot_color_info["dark_border"] if mot_color_info else "#27272A"
                mot_t_fg = "#FFFFFF" if mot_color_info else "#D4D4D8"
                tags = [
                    (f"📐{tpl_name}", tpl_t_bg, tpl_t_fg),
                    (f"🎥{mot_name}", mot_t_bg, mot_t_fg),
                    (f"{mode_name}", "#143326" if has_custom_mode else "#27272A", "#6EE7B7" if has_custom_mode else "#D4D4D8"),
                ]
            else:
                tpl_t_bg = tpl_color_info["tag_bg"] if tpl_color_info else "#F1F5F9"
                tpl_t_fg = tpl_color_info["tag_fg"] if tpl_color_info else "#475569"
                mot_t_bg = mot_color_info["tag_bg"] if mot_color_info else "#F1F5F9"
                mot_t_fg = mot_color_info["tag_fg"] if mot_color_info else "#475569"
                tags = [
                    (f"📐{tpl_name}", tpl_t_bg, tpl_t_fg),
                    (f"🎥{mot_name}", mot_t_bg, mot_t_fg),
                    (f"{mode_name}", "#DCFCE7" if has_custom_mode else "#F1F5F9", "#15803D" if has_custom_mode else "#475569"),
                ]

            cur_x = card_rect.left() + 6
            max_x = card_rect.right() - 6
            painter.setFont(font_tag)
            for tag_text, t_bg, t_fg in tags:
                if cur_x >= max_x - 20:
                    break
                avail_tag_w = max_x - cur_x
                elided_t = fm_tag.elidedText(tag_text, Qt.TextElideMode.ElideRight, min(avail_tag_w - 6, int(card_rect.width() * 0.44)))
                tw = min(avail_tag_w, fm_tag.horizontalAdvance(elided_t) + 8)
                t_rect = QRect(cur_x, tags_y, tw, 19)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(t_bg)))
                painter.drawRoundedRect(t_rect, 4, 4)
                painter.setPen(QColor(t_fg))
                painter.drawText(t_rect, Qt.AlignmentFlag.AlignCenter, elided_t)
                cur_x += tw + 4

            # 7. Spanish segment text preview (2 lines)
            text_rect = QRect(
                card_rect.left() + 7,
                tags_y + 22,
                card_rect.width() - 14,
                card_rect.bottom() - (tags_y + 22) - 4
            )
            painter.setFont(font_text)
            if is_dark:
                painter.setPen(QColor("#F4F4F5") if is_sel else QColor("#D4D4D8"))
            else:
                painter.setPen(QColor("#1E293B") if is_sel else QColor("#475569"))
            raw_text = seg.get("text", "")
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                raw_text
            )

        # 8. Rubber-band Marquee Box Selection overlay
        if self._is_dragging_box:
            box = QRect(self._drag_origin, self._drag_current).normalized()
            painter.setPen(QPen(QColor("#2563EB"), 2, Qt.PenStyle.SolidLine))
            painter.setBrush(QBrush(QColor(37, 99, 235, 45)))
            painter.drawRect(box)


class PresetGroupAndColorDialog(QDialog):
    """
    📦 预设组合与专属浅色管理弹窗：
    - Tab 1: 📦 运镜预设组合（创建/删除运镜组合，勾选哪些运镜放入组合，支持上下调整顺序，同一运镜可出现在多个组合中）
    - Tab 2: 📦 模板预设组合（创建/删除模板组合，勾选哪些模板放入组合，支持上下调整顺序，同一模板可出现在多个组合中）
    - Tab 3: 🎨 预设专属浅色设置（为任意运镜或提示词模板指定浅色卡片颜色；未指定颜色时默认使用浅粉红色 #FCE7F3）
    """

    def __init__(self, template_manager, on_changed_callback=None, initial_tab: int = 0, parent=None):
        super().__init__(parent)
        self.tm = template_manager
        self.on_changed_callback = on_changed_callback
        self.setWindowTitle("📦 预设组合与卡片专属浅色设置 (模板组合 · 运镜组合 · 预设颜色)")
        self.resize(960, 620)
        self.setStyleSheet("""
            QDialog { background-color: #FAF6F0; color: #334155; font-family: "Microsoft YaHei", sans-serif; }
            QLabel { font-size: 13px; color: #334155; font-weight: bold; }
            QLineEdit, QComboBox, QListWidget, QTableWidget {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 5px;
                padding: 5px 8px;
                color: #1E293B;
                font-size: 13px;
            }
            QListWidget::item { padding: 7px 6px; border-bottom: 1px solid #F1F5F9; }
            QListWidget::item:selected { background-color: #DBEAFE; color: #1E3A8A; font-weight: bold; }
            QPushButton {
                background-color: #2563EB; color: white; border: none; border-radius: 5px;
                padding: 6px 12px; font-size: 12px; font-weight: bold;
            }
            QPushButton:hover { background-color: #1D4ED8; }
            QTabWidget::pane { border: 1px solid #CBD5E1; background-color: #FFFDF9; border-radius: 6px; }
            QTabBar::tab {
                background-color: #E2E8F0; color: #475569; padding: 8px 18px;
                border-top-left-radius: 6px; border-top-right-radius: 6px; font-weight: bold; font-size: 13px;
            }
            QTabBar::tab:selected {
                background-color: #FFFDF9; color: #1E40AF; border: 1px solid #CBD5E1; border-bottom-color: #FFFDF9;
            }
        """)
        self._init_ui()
        self.tabs.setCurrentIndex(initial_tab)

    def _notify_changed(self):
        if callable(self.on_changed_callback):
            try:
                self.on_changed_callback()
            except Exception:
                pass

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        lbl_banner = QLabel(
            "💡 使用说明：\n"
            "1️⃣ 【预设组合】：模板组合与运镜组合分开管理。您可创建多个组合，勾选任意预设加入组合并调整顺序（同一预设可出现在多个组合中）。多选任务卡片后选择组合，即可按顺序平均分配！\n"
            "2️⃣ 【卡片浅色】：遵循任务统一模板/统一运镜的卡片无额外颜色；当单个任务卡片选择了单独的预设时，卡片会变为该预设指定的浅色（未指定颜色的预设默认显示为「浅粉红色」）。"
        )
        lbl_banner.setWordWrap(True)
        lbl_banner.setStyleSheet(
            "background-color: #EFF6FF; color: #1E3A8A; border: 1px solid #BFDBFE; "
            "border-radius: 6px; padding: 8px 12px; font-size: 12px; font-weight: bold;"
        )
        layout.addWidget(lbl_banner)

        self.tabs = QTabWidget()
        self._init_motion_groups_tab()
        self._init_template_groups_tab()
        self._init_colors_tab()
        layout.addWidget(self.tabs, 1)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        btn_close = QPushButton("✅ 完成并关闭")
        btn_close.setStyleSheet("background-color: #059669; color: white; padding: 7px 24px; font-size: 13px;")
        btn_close.clicked.connect(self.accept)
        bottom_row.addWidget(btn_close)
        layout.addLayout(bottom_row)

        self._reload_motion_groups_ui()
        self._reload_template_groups_ui()
        self._reload_colors_table_ui()

    def _format_preset_label_with_color(self, preset: dict) -> str:
        name = preset.get("name", "未命名")
        ck = (preset.get("color") or "").strip()
        c_info = get_preset_color_info(ck)
        return f"[{c_info['label']}]  {name}"

    # ───────────────────────────────────────────────────────────────────────
    # Tab 1: 运镜预设组合
    # ───────────────────────────────────────────────────────────────────────
    def _init_motion_groups_tab(self):
        tab = QWidget()
        lay = QHBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Motion group list
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(4, 4, 4, 4)
        left_l.addWidget(QLabel("📦 已创建的运镜组合:"))

        self.list_mot_groups = QListWidget()
        self.list_mot_groups.currentRowChanged.connect(self._on_mot_group_selected)
        left_l.addWidget(self.list_mot_groups, 1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("＋ 新建运镜组合")
        btn_add.setStyleSheet("background-color: #059669; color: white;")
        btn_add.clicked.connect(self._create_mot_group)
        btn_del = QPushButton("🗑️ 删除组合")
        btn_del.setStyleSheet("background-color: #EF4444; color: white;")
        btn_del.clicked.connect(self._delete_mot_group)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        left_l.addLayout(btn_row)
        splitter.addWidget(left_w)

        # Right: Presets in current motion group
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(4, 4, 4, 4)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("组合名称:"))
        self.txt_mot_group_name = QLineEdit()
        self.txt_mot_group_name.setPlaceholderText("输入运镜组合名称（如：推进+拉远交替组合）")
        self.txt_mot_group_name.editingFinished.connect(self._on_mot_group_name_edited)
        name_row.addWidget(self.txt_mot_group_name, 1)
        right_l.addLayout(name_row)

        hdr_row = QHBoxLayout()
        hdr_row.addWidget(QLabel("☑️ 勾选要放入该组合的运镜预设（按列表从上到下的顺序平均分配）:"))
        hdr_row.addStretch()
        btn_up = QPushButton("⬆️ 上移顺序")
        btn_up.setStyleSheet("background-color: #64748B; color: white; padding: 4px 10px;")
        btn_up.clicked.connect(lambda: self._move_group_preset_item(self.list_mot_group_presets, -1, is_motion=True))
        btn_down = QPushButton("⬇️ 下移顺序")
        btn_down.setStyleSheet("background-color: #64748B; color: white; padding: 4px 10px;")
        btn_down.clicked.connect(lambda: self._move_group_preset_item(self.list_mot_group_presets, 1, is_motion=True))
        hdr_row.addWidget(btn_up)
        hdr_row.addWidget(btn_down)
        right_l.addLayout(hdr_row)

        self.list_mot_group_presets = QListWidget()
        self.list_mot_group_presets.itemChanged.connect(self._on_mot_group_preset_checked)
        right_l.addWidget(self.list_mot_group_presets, 1)

        self.lbl_mot_group_preview = QLabel("当前组合顺序预览：暂无")
        self.lbl_mot_group_preview.setWordWrap(True)
        self.lbl_mot_group_preview.setStyleSheet(
            "background-color: #F0FDF4; color: #166534; border: 1px solid #BBF7D0; "
            "border-radius: 5px; padding: 6px 10px; font-size: 12px;"
        )
        right_l.addWidget(self.lbl_mot_group_preview)

        splitter.addWidget(right_w)
        splitter.setSizes([300, 620])
        lay.addWidget(splitter)
        self.tabs.addTab(tab, "📦 运镜预设组合")

    def _reload_motion_groups_ui(self, select_group_id: str = None):
        if not self.tm:
            return
        self.list_mot_groups.blockSignals(True)
        self.list_mot_groups.clear()
        sel_row = 0
        for i, g in enumerate(self.tm.motion_groups):
            cnt = len([pid for pid in g.get("preset_ids", []) if self.tm.get_motion(pid)])
            it = QListWidgetItem(f"📦 {g.get('name', '未命名组合')} ({cnt} 个运镜)")
            it.setData(Qt.ItemDataRole.UserRole, g["id"])
            self.list_mot_groups.addItem(it)
            if select_group_id and g["id"] == select_group_id:
                sel_row = i
        self.list_mot_groups.blockSignals(False)

        if self.list_mot_groups.count() > 0:
            self.list_mot_groups.setCurrentRow(sel_row)
            self._on_mot_group_selected(sel_row)
        else:
            self._on_mot_group_selected(-1)

    def _on_mot_group_selected(self, row: int):
        self.list_mot_group_presets.blockSignals(True)
        self.list_mot_group_presets.clear()
        if row < 0 or row >= self.list_mot_groups.count() or not self.tm:
            self.txt_mot_group_name.clear()
            self.txt_mot_group_name.setEnabled(False)
            self.list_mot_group_presets.setEnabled(False)
            self.lbl_mot_group_preview.setText("💡 请先点击左侧「＋ 新建运镜组合」创建一个运镜组合。")
            self.list_mot_group_presets.blockSignals(False)
            return

        self.txt_mot_group_name.setEnabled(True)
        self.list_mot_group_presets.setEnabled(True)
        gid = self.list_mot_groups.item(row).data(Qt.ItemDataRole.UserRole)
        grp = self.tm.get_motion_group(gid)
        if not grp:
            self.list_mot_group_presets.blockSignals(False)
            return

        self.txt_mot_group_name.setText(grp.get("name", ""))
        selected_ids = [pid for pid in grp.get("preset_ids", []) if self.tm.get_motion(pid)]
        selected_set = set(selected_ids)

        # 先按组合内已保存的顺序排列已勾选的预设，再列出未勾选的预设
        ordered_motions = []
        for pid in selected_ids:
            m = self.tm.get_motion(pid)
            if m:
                ordered_motions.append((m, True))
        for m in self.tm.motions:
            if m["id"] not in selected_set:
                ordered_motions.append((m, False))

        for m, is_checked in ordered_motions:
            it = QListWidgetItem(self._format_preset_label_with_color(m))
            it.setData(Qt.ItemDataRole.UserRole, m["id"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
            c_info = get_preset_color_info((m.get("color") or "").strip())
            it.setBackground(QBrush(QColor(c_info["bg"])))
            it.setForeground(QBrush(QColor(c_info["tag_fg"])))
            self.list_mot_group_presets.addItem(it)

        self.list_mot_group_presets.blockSignals(False)
        self._update_mot_group_preview(grp)

    def _update_mot_group_preview(self, grp: dict):
        names = []
        for pid in grp.get("preset_ids", []):
            m = self.tm.get_motion(pid)
            if m:
                names.append(m["name"])
        if names:
            seq_str = "  ➔  ".join(f"【{i + 1}. {n}】" for i, n in enumerate(names))
            self.lbl_mot_group_preview.setText(f"✅ 当前组合分配顺序（共 {len(names)} 个运镜）：\n{seq_str}")
        else:
            self.lbl_mot_group_preview.setText("⚠️ 当前组合尚未勾选任何运镜预设，请在上方列表中勾选要加入组合的运镜。")

    def _create_mot_group(self):
        if not self.tm:
            return
        name, ok = QInputDialog.getText(self, "新建运镜预设组合", "请输入运镜组合名称：")
        if not ok or not name.strip():
            return
        new_grp = {
            "id": f"mgrp_{uuid.uuid4().hex[:8]}",
            "name": name.strip(),
            "preset_ids": []
        }
        self.tm.motion_groups.append(new_grp)
        self.tm.save_motion_groups()
        self._reload_motion_groups_ui(select_group_id=new_grp["id"])
        self._notify_changed()

    def _delete_mot_group(self):
        row = self.list_mot_groups.currentRow()
        if row < 0 or not self.tm:
            return
        gid = self.list_mot_groups.item(row).data(Qt.ItemDataRole.UserRole)
        grp = self.tm.get_motion_group(gid)
        gname = grp.get("name", "") if grp else ""
        reply = QMessageBox.question(
            self, "确认删除运镜组合",
            f"确定要删除运镜组合【{gname}】吗？\n（仅删除组合关系，不会删除里面的运镜预设本身）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.motion_groups = [g for g in self.tm.motion_groups if g.get("id") != gid]
            self.tm.save_motion_groups()
            self._reload_motion_groups_ui()
            self._notify_changed()

    def _on_mot_group_name_edited(self):
        row = self.list_mot_groups.currentRow()
        if row < 0 or not self.tm:
            return
        new_name = self.txt_mot_group_name.text().strip()
        if not new_name:
            return
        gid = self.list_mot_groups.item(row).data(Qt.ItemDataRole.UserRole)
        grp = self.tm.get_motion_group(gid)
        if grp:
            grp["name"] = new_name
            self.tm.save_motion_groups()
            cnt = len([pid for pid in grp.get("preset_ids", []) if self.tm.get_motion(pid)])
            self.list_mot_groups.item(row).setText(f"📦 {new_name} ({cnt} 个运镜)")
            self._notify_changed()

    def _on_mot_group_preset_checked(self, _item):
        self._sync_current_group_presets(is_motion=True)

    # ───────────────────────────────────────────────────────────────────────
    # Tab 2: 模板预设组合
    # ───────────────────────────────────────────────────────────────────────
    def _init_template_groups_tab(self):
        tab = QWidget()
        lay = QHBoxLayout(tab)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Template group list
        left_w = QWidget()
        left_l = QVBoxLayout(left_w)
        left_l.setContentsMargins(4, 4, 4, 4)
        left_l.addWidget(QLabel("📦 已创建的模板组合:"))

        self.list_tpl_groups = QListWidget()
        self.list_tpl_groups.currentRowChanged.connect(self._on_tpl_group_selected)
        left_l.addWidget(self.list_tpl_groups, 1)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("＋ 新建模板组合")
        btn_add.setStyleSheet("background-color: #059669; color: white;")
        btn_add.clicked.connect(self._create_tpl_group)
        btn_del = QPushButton("🗑️ 删除组合")
        btn_del.setStyleSheet("background-color: #EF4444; color: white;")
        btn_del.clicked.connect(self._delete_tpl_group)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_del)
        left_l.addLayout(btn_row)
        splitter.addWidget(left_w)

        # Right: Presets in current template group
        right_w = QWidget()
        right_l = QVBoxLayout(right_w)
        right_l.setContentsMargins(4, 4, 4, 4)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("组合名称:"))
        self.txt_tpl_group_name = QLineEdit()
        self.txt_tpl_group_name.setPlaceholderText("输入模板组合名称（如：多动作交替模板组合）")
        self.txt_tpl_group_name.editingFinished.connect(self._on_tpl_group_name_edited)
        name_row.addWidget(self.txt_tpl_group_name, 1)
        right_l.addLayout(name_row)

        hdr_row = QHBoxLayout()
        hdr_row.addWidget(QLabel("☑️ 勾选要放入该组合的提示词模板（按列表从上到下的顺序平均分配）:"))
        hdr_row.addStretch()
        btn_up = QPushButton("⬆️ 上移顺序")
        btn_up.setStyleSheet("background-color: #64748B; color: white; padding: 4px 10px;")
        btn_up.clicked.connect(lambda: self._move_group_preset_item(self.list_tpl_group_presets, -1, is_motion=False))
        btn_down = QPushButton("⬇️ 下移顺序")
        btn_down.setStyleSheet("background-color: #64748B; color: white; padding: 4px 10px;")
        btn_down.clicked.connect(lambda: self._move_group_preset_item(self.list_tpl_group_presets, 1, is_motion=False))
        hdr_row.addWidget(btn_up)
        hdr_row.addWidget(btn_down)
        right_l.addLayout(hdr_row)

        self.list_tpl_group_presets = QListWidget()
        self.list_tpl_group_presets.itemChanged.connect(self._on_tpl_group_preset_checked)
        right_l.addWidget(self.list_tpl_group_presets, 1)

        self.lbl_tpl_group_preview = QLabel("当前组合顺序预览：暂无")
        self.lbl_tpl_group_preview.setWordWrap(True)
        self.lbl_tpl_group_preview.setStyleSheet(
            "background-color: #F0FDF4; color: #166534; border: 1px solid #BBF7D0; "
            "border-radius: 5px; padding: 6px 10px; font-size: 12px;"
        )
        right_l.addWidget(self.lbl_tpl_group_preview)

        splitter.addWidget(right_w)
        splitter.setSizes([300, 620])
        lay.addWidget(splitter)
        self.tabs.addTab(tab, "📦 模板预设组合")

    def _reload_template_groups_ui(self, select_group_id: str = None):
        if not self.tm:
            return
        self.list_tpl_groups.blockSignals(True)
        self.list_tpl_groups.clear()
        sel_row = 0
        for i, g in enumerate(self.tm.template_groups):
            cnt = len([pid for pid in g.get("preset_ids", []) if self.tm.get_template(pid)])
            it = QListWidgetItem(f"📦 {g.get('name', '未命名组合')} ({cnt} 个模板)")
            it.setData(Qt.ItemDataRole.UserRole, g["id"])
            self.list_tpl_groups.addItem(it)
            if select_group_id and g["id"] == select_group_id:
                sel_row = i
        self.list_tpl_groups.blockSignals(False)

        if self.list_tpl_groups.count() > 0:
            self.list_tpl_groups.setCurrentRow(sel_row)
            self._on_tpl_group_selected(sel_row)
        else:
            self._on_tpl_group_selected(-1)

    def _on_tpl_group_selected(self, row: int):
        self.list_tpl_group_presets.blockSignals(True)
        self.list_tpl_group_presets.clear()
        if row < 0 or row >= self.list_tpl_groups.count() or not self.tm:
            self.txt_tpl_group_name.clear()
            self.txt_tpl_group_name.setEnabled(False)
            self.list_tpl_group_presets.setEnabled(False)
            self.lbl_tpl_group_preview.setText("💡 请先点击左侧「＋ 新建模板组合」创建一个模板组合。")
            self.list_tpl_group_presets.blockSignals(False)
            return

        self.txt_tpl_group_name.setEnabled(True)
        self.list_tpl_group_presets.setEnabled(True)
        gid = self.list_tpl_groups.item(row).data(Qt.ItemDataRole.UserRole)
        grp = self.tm.get_template_group(gid)
        if not grp:
            self.list_tpl_group_presets.blockSignals(False)
            return

        self.txt_tpl_group_name.setText(grp.get("name", ""))
        selected_ids = [pid for pid in grp.get("preset_ids", []) if self.tm.get_template(pid)]
        selected_set = set(selected_ids)

        ordered_tpls = []
        for pid in selected_ids:
            t = self.tm.get_template(pid)
            if t:
                ordered_tpls.append((t, True))
        for t in self.tm.templates:
            if t["id"] not in selected_set:
                ordered_tpls.append((t, False))

        for t, is_checked in ordered_tpls:
            it = QListWidgetItem(self._format_preset_label_with_color(t))
            it.setData(Qt.ItemDataRole.UserRole, t["id"])
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked)
            c_info = get_preset_color_info((t.get("color") or "").strip())
            it.setBackground(QBrush(QColor(c_info["bg"])))
            it.setForeground(QBrush(QColor(c_info["tag_fg"])))
            self.list_tpl_group_presets.addItem(it)

        self.list_tpl_group_presets.blockSignals(False)
        self._update_tpl_group_preview(grp)

    def _update_tpl_group_preview(self, grp: dict):
        names = []
        for pid in grp.get("preset_ids", []):
            t = self.tm.get_template(pid)
            if t:
                names.append(t["name"])
        if names:
            seq_str = "  ➔  ".join(f"【{i + 1}. {n}】" for i, n in enumerate(names))
            self.lbl_tpl_group_preview.setText(f"✅ 当前组合分配顺序（共 {len(names)} 个模板）：\n{seq_str}")
        else:
            self.lbl_tpl_group_preview.setText("⚠️ 当前组合尚未勾选任何提示词模板，请在上方列表中勾选要加入组合的模板。")

    def _create_tpl_group(self):
        if not self.tm:
            return
        name, ok = QInputDialog.getText(self, "新建模板预设组合", "请输入模板组合名称：")
        if not ok or not name.strip():
            return
        new_grp = {
            "id": f"tgrp_{uuid.uuid4().hex[:8]}",
            "name": name.strip(),
            "preset_ids": []
        }
        self.tm.template_groups.append(new_grp)
        self.tm.save_template_groups()
        self._reload_template_groups_ui(select_group_id=new_grp["id"])
        self._notify_changed()

    def _delete_tpl_group(self):
        row = self.list_tpl_groups.currentRow()
        if row < 0 or not self.tm:
            return
        gid = self.list_tpl_groups.item(row).data(Qt.ItemDataRole.UserRole)
        grp = self.tm.get_template_group(gid)
        gname = grp.get("name", "") if grp else ""
        reply = QMessageBox.question(
            self, "确认删除模板组合",
            f"确定要删除模板组合【{gname}】吗？\n（仅删除组合关系，不会删除里面的提示词模板本身）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.tm.template_groups = [g for g in self.tm.template_groups if g.get("id") != gid]
            self.tm.save_template_groups()
            self._reload_template_groups_ui()
            self._notify_changed()

    def _on_tpl_group_name_edited(self):
        row = self.list_tpl_groups.currentRow()
        if row < 0 or not self.tm:
            return
        new_name = self.txt_tpl_group_name.text().strip()
        if not new_name:
            return
        gid = self.list_tpl_groups.item(row).data(Qt.ItemDataRole.UserRole)
        grp = self.tm.get_template_group(gid)
        if grp:
            grp["name"] = new_name
            self.tm.save_template_groups()
            cnt = len([pid for pid in grp.get("preset_ids", []) if self.tm.get_template(pid)])
            self.list_tpl_groups.item(row).setText(f"📦 {new_name} ({cnt} 个模板)")
            self._notify_changed()

    def _on_tpl_group_preset_checked(self, _item):
        self._sync_current_group_presets(is_motion=False)

    def _move_group_preset_item(self, list_widget: QListWidget, direction: int, is_motion: bool):
        row = list_widget.currentRow()
        if row < 0:
            return
        target = row + direction
        if target < 0 or target >= list_widget.count():
            return
        list_widget.blockSignals(True)
        it = list_widget.takeItem(row)
        list_widget.insertItem(target, it)
        list_widget.setCurrentRow(target)
        list_widget.blockSignals(False)
        self._sync_current_group_presets(is_motion=is_motion)

    def _sync_current_group_presets(self, is_motion: bool):
        if not self.tm:
            return
        if is_motion:
            g_row = self.list_mot_groups.currentRow()
            if g_row < 0:
                return
            gid = self.list_mot_groups.item(g_row).data(Qt.ItemDataRole.UserRole)
            grp = self.tm.get_motion_group(gid)
            if not grp:
                return
            checked_ids = []
            for i in range(self.list_mot_group_presets.count()):
                it = self.list_mot_group_presets.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    checked_ids.append(it.data(Qt.ItemDataRole.UserRole))
            grp["preset_ids"] = checked_ids
            self.tm.save_motion_groups()
            self.list_mot_groups.item(g_row).setText(f"📦 {grp.get('name', '未命名组合')} ({len(checked_ids)} 个运镜)")
            self._update_mot_group_preview(grp)
        else:
            g_row = self.list_tpl_groups.currentRow()
            if g_row < 0:
                return
            gid = self.list_tpl_groups.item(g_row).data(Qt.ItemDataRole.UserRole)
            grp = self.tm.get_template_group(gid)
            if not grp:
                return
            checked_ids = []
            for i in range(self.list_tpl_group_presets.count()):
                it = self.list_tpl_group_presets.item(i)
                if it.checkState() == Qt.CheckState.Checked:
                    checked_ids.append(it.data(Qt.ItemDataRole.UserRole))
            grp["preset_ids"] = checked_ids
            self.tm.save_template_groups()
            self.list_tpl_groups.item(g_row).setText(f"📦 {grp.get('name', '未命名组合')} ({len(checked_ids)} 个模板)")
            self._update_tpl_group_preview(grp)
        self._notify_changed()

    # ───────────────────────────────────────────────────────────────────────
    # Tab 3: 预设专属浅色设置
    # ───────────────────────────────────────────────────────────────────────
    def _init_colors_tab(self):
        tab = QWidget()
        lay = QHBoxLayout(tab)

        # Left column: Camera Motions Colors
        mot_box = QVBoxLayout()
        mot_box.addWidget(QLabel("🎥 运镜预设卡片浅色设置（单独应用该运镜时卡片显示的颜色）:"))
        self.table_mot_colors = QTableWidget(0, 2)
        self.table_mot_colors.setHorizontalHeaderLabels(["运镜预设名称 (浅色预览)", "选择卡片专属浅色"])
        self.table_mot_colors.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_mot_colors.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_mot_colors.verticalHeader().setDefaultSectionSize(38)
        mot_box.addWidget(self.table_mot_colors, 1)
        lay.addLayout(mot_box, 1)

        # Right column: Prompt Templates Colors
        tpl_box = QVBoxLayout()
        tpl_box.addWidget(QLabel("📐 提示词模板卡片浅色设置（单独应用该模板时卡片显示的颜色）:"))
        self.table_tpl_colors = QTableWidget(0, 2)
        self.table_tpl_colors.setHorizontalHeaderLabels(["提示词模板名称 (浅色预览)", "选择卡片专属浅色"])
        self.table_tpl_colors.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table_tpl_colors.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table_tpl_colors.verticalHeader().setDefaultSectionSize(38)
        tpl_box.addWidget(self.table_tpl_colors, 1)
        lay.addLayout(tpl_box, 1)

        self.tabs.addTab(tab, "🎨 预设专属浅色设置")

    def _reload_colors_table_ui(self):
        if not self.tm:
            return
        # Populate Motion Colors table
        self.table_mot_colors.setRowCount(len(self.tm.motions))
        for r, m in enumerate(self.tm.motions):
            ck = (m.get("color") or "").strip()
            c_info = get_preset_color_info(ck)
            name_item = QTableWidgetItem(f"🎥 {m.get('name', '未命名')}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setBackground(QBrush(QColor(c_info["bg"])))
            name_item.setForeground(QBrush(QColor(c_info["tag_fg"])))
            self.table_mot_colors.setItem(r, 0, name_item)

            cb = QComboBox()
            for c in PRESET_COLOR_PALETTE:
                idx = cb.count()
                cb.addItem(c["label"], c["key"])
                cb.setItemData(idx, QBrush(QColor(c["bg"])), Qt.ItemDataRole.BackgroundRole)
                cb.setItemData(idx, QBrush(QColor(c["tag_fg"])), Qt.ItemDataRole.ForegroundRole)
            c_idx = cb.findData(ck)
            cb.setCurrentIndex(c_idx if c_idx >= 0 else 0)
            cb.currentIndexChanged.connect(lambda _idx, row=r, mid=m["id"], combo=cb: self._on_table_preset_color_changed(True, row, mid, combo))
            self.table_mot_colors.setCellWidget(r, 1, cb)

        # Populate Template Colors table
        self.table_tpl_colors.setRowCount(len(self.tm.templates))
        for r, t in enumerate(self.tm.templates):
            ck = (t.get("color") or "").strip()
            c_info = get_preset_color_info(ck)
            name_item = QTableWidgetItem(f"📐 {t.get('name', '未命名')}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name_item.setBackground(QBrush(QColor(c_info["bg"])))
            name_item.setForeground(QBrush(QColor(c_info["tag_fg"])))
            self.table_tpl_colors.setItem(r, 0, name_item)

            cb = QComboBox()
            for c in PRESET_COLOR_PALETTE:
                idx = cb.count()
                cb.addItem(c["label"], c["key"])
                cb.setItemData(idx, QBrush(QColor(c["bg"])), Qt.ItemDataRole.BackgroundRole)
                cb.setItemData(idx, QBrush(QColor(c["tag_fg"])), Qt.ItemDataRole.ForegroundRole)
            c_idx = cb.findData(ck)
            cb.setCurrentIndex(c_idx if c_idx >= 0 else 0)
            cb.currentIndexChanged.connect(lambda _idx, row=r, tid=t["id"], combo=cb: self._on_table_preset_color_changed(False, row, tid, combo))
            self.table_tpl_colors.setCellWidget(r, 1, cb)

    def _on_table_preset_color_changed(self, is_motion: bool, row: int, preset_id: str, combo: QComboBox):
        if not self.tm:
            return
        new_ck = combo.currentData() or ""
        c_info = get_preset_color_info(new_ck)
        if is_motion:
            m = self.tm.get_motion(preset_id)
            if m:
                m["color"] = new_ck
                self.tm.save_motions()
            it = self.table_mot_colors.item(row, 0)
            if it:
                it.setBackground(QBrush(QColor(c_info["bg"])))
                it.setForeground(QBrush(QColor(c_info["tag_fg"])))
            self._on_mot_group_selected(self.list_mot_groups.currentRow())
        else:
            t = self.tm.get_template(preset_id)
            if t:
                t["color"] = new_ck
                self.tm.save_templates()
            it = self.table_tpl_colors.item(row, 0)
            if it:
                it.setBackground(QBrush(QColor(c_info["bg"])))
                it.setForeground(QBrush(QColor(c_info["tag_fg"])))
            self._on_tpl_group_selected(self.list_tpl_groups.currentRow())
        self._notify_changed()


class SegmentVisualBatchManagerDialog(QDialog):
    """
    🖼️ 多选与图片预设可视化管理大窗：
    - 顶部第1栏：任务直接切换栏（⬅ 上一个任务 / 任务选择下拉框 / 下一个任务 ➡ + 任务统一模板/统一运镜设置）
    - 顶部第2栏：多选断句预设批量指定选项卡（📐 提示词模板 / 🎥 运镜预设 / ⚙️ 生成模式 / ⏱️ 视频时长 + 全选/反选/取消 + Ctrl+滚轮缩放滑块）
    - 中部可折叠栏：🖼️ 任务资源图库（展示当前任务全部图片资源，支持一键收起/展开；多选断句后点击任意资源图即刻批量更换图片）
    - 主体多排网格区：断句任务图片多排直观平铺（支持 Ctrl+滚轮缩放、Ctrl/Shift/橡皮筋框选多张图片）
    """

    def __init__(self, detail_widget, initial_selected_rows=None, parent=None):
        super().__init__(parent or detail_widget)
        self.detail_widget = detail_widget
        self.main_window = detail_widget.window() if detail_widget else None
        self.storage_manager = getattr(self.main_window, "storage_manager", None)
        self.template_manager = getattr(detail_widget, "template_manager", None)
        self.config_manager = getattr(detail_widget, "config_manager", None)

        self.project_path: Path = Path(detail_widget.project_path) if (detail_widget and detail_widget.project_path) else None
        self.project_model: ProjectModel = detail_widget.project_model if detail_widget else None
        self._pixmap_cache = {}
        self._project_list = []
        self._resource_expanded = True
        self.end_frame_mode = False

        self.setWindowTitle("🖼️ 多选与图片预设可视化管理 — 支持 Ctrl+滚轮缩放图片 · 鼠标拖拽框选 · 点击资源图批量更换 · 直接切换任务")
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.resize(1440, 880)
        self.setStyleSheet("""
            QDialog { background-color: #FAF6F0; color: #334155; }
            QLabel { color: #334155; font-size: 12px; }
            QComboBox {
                background-color: #FFFFFF;
                border: 1px solid #CBD5E1;
                border-radius: 5px;
                padding: 4px 8px;
                font-size: 12px;
                color: #1E293B;
            }
            QComboBox:hover { border: 1px solid #3B82F6; }
        """)

        self._init_ui()
        self._load_projects_into_switcher()
        self._bind_current_project(initial_selected_rows=initial_selected_rows)

        # 快捷键 Ctrl+A 全选
        self._sc_select_all = QShortcut(QKeySequence("Ctrl+A"), self)
        self._sc_select_all.activated.connect(self.grid_viewport.select_all)

    def _init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # ═══════════════════════════════════════════════════════════════════
        # 1. 顶部第一栏：任务切换栏 + 任务级统一模板/运镜设置
        # ═══════════════════════════════════════════════════════════════════
        task_bar = QFrame()
        task_bar.setStyleSheet(
            "QFrame { background-color: #FFFDF9; border: 1px solid #E6CCB2; border-radius: 8px; }"
        )
        task_lay = QHBoxLayout(task_bar)
        task_lay.setContentsMargins(10, 6, 10, 6)
        task_lay.setSpacing(8)

        lbl_task = QLabel("📋 当前任务:")
        lbl_task.setStyleSheet("font-weight: bold; font-size: 13px; color: #5C3D2E; border: none;")
        task_lay.addWidget(lbl_task)

        self.btn_prev_task = QPushButton("⬅ 上一个任务")
        self.btn_prev_task.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; font-weight: bold; padding: 5px 10px; border-radius: 5px; border: 1px solid #D4A373; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        self.btn_prev_task.clicked.connect(self._switch_prev_task)
        task_lay.addWidget(self.btn_prev_task)

        self.combo_task_switcher = QComboBox()
        self.combo_task_switcher.setMinimumWidth(300)
        self.combo_task_switcher.setMaxVisibleItems(18)
        self.combo_task_switcher.activated.connect(self._on_task_combo_switched)
        task_lay.addWidget(self.combo_task_switcher)

        self.btn_next_task = QPushButton("下一个任务 ➡")
        self.btn_next_task.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; font-weight: bold; padding: 5px 10px; border-radius: 5px; border: 1px solid #D4A373; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        self.btn_next_task.clicked.connect(self._switch_next_task)
        task_lay.addWidget(self.btn_next_task)

        task_lay.addSpacing(12)

        lbl_uni_tpl = QLabel("🌐 任务统一模板:")
        lbl_uni_tpl.setStyleSheet("font-weight: bold; color: #5C3D2E; border: none;")
        task_lay.addWidget(lbl_uni_tpl)

        self.combo_unified_tpl = QComboBox()
        self.combo_unified_tpl.setMinimumWidth(150)
        self.combo_unified_tpl.activated.connect(self._on_unified_tpl_changed)
        task_lay.addWidget(self.combo_unified_tpl)

        lbl_uni_mot = QLabel("🌐 任务统一运镜:")
        lbl_uni_mot.setStyleSheet("font-weight: bold; color: #5C3D2E; border: none;")
        task_lay.addWidget(lbl_uni_mot)

        self.combo_unified_mot = QComboBox()
        self.combo_unified_mot.setMinimumWidth(150)
        self.combo_unified_mot.activated.connect(self._on_unified_mot_changed)
        task_lay.addWidget(self.combo_unified_mot)

        task_lay.addStretch()

        self.lbl_save_status = QLabel("✅ 所有修改实时自动保存")
        self.lbl_save_status.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #047857; background: #ECFDF5; "
            "padding: 4px 10px; border-radius: 4px; border: 1px solid #A7F3D0;"
        )
        task_lay.addWidget(self.lbl_save_status)

        root_layout.addWidget(task_bar)

        # ═══════════════════════════════════════════════════════════════════
        # 2. 顶部第二栏：多选控制 + 选项卡区域（直接为所选断句图片指定各种预设）
        # ═══════════════════════════════════════════════════════════════════
        preset_bar = QFrame()
        preset_bar.setStyleSheet(
            "QFrame { background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px; }"
        )
        preset_outer = QVBoxLayout(preset_bar)
        preset_outer.setContentsMargins(10, 7, 10, 7)
        preset_outer.setSpacing(6)

        # Row 2A: Selection controls & End-Frame Mode Toggle & Zoom slider
        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)

        self.btn_end_frame_mode = QPushButton("🎬 首尾帧模式：已关闭")
        self.btn_end_frame_mode.setCheckable(True)
        self.btn_end_frame_mode.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_end_frame_mode.setToolTip(
            "开启/关闭「首尾帧模式」：\n"
            "• 开启后：每张断句卡片分为上下两个独立板块（上：📸首帧，下：🎬尾帧）\n"
            "• 默认自动分配首帧图片，尾帧默认留空不自动分配，由您点击下板块后自由选择资源图\n"
            "• 开启后每张卡片仍共享同一个描述词模板、同一个运镜预设和同一句文案"
        )
        self.btn_end_frame_mode.toggled.connect(self._on_end_frame_mode_toggled)
        sel_row.addWidget(self.btn_end_frame_mode)

        self.lbl_selection_info = QLabel("已选 0 / 0 个断句图片")
        self.lbl_selection_info.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #1E40AF; background: #DBEAFE; "
            "padding: 4px 10px; border-radius: 5px; border: none;"
        )
        sel_row.addWidget(self.lbl_selection_info)

        btn_sel_all = QPushButton("☑️ 全选 (Ctrl+A)")
        btn_sel_all.setStyleSheet("QPushButton { background: #2563EB; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; } QPushButton:hover { background: #1D4ED8; }")
        btn_sel_all.clicked.connect(lambda: self.grid_viewport.select_all())
        sel_row.addWidget(btn_sel_all)

        self.btn_sel_all_start = QPushButton("📸 全选首帧")
        self.btn_sel_all_start.setToolTip("仅选中所有卡片的上半板块（📸 首帧），便于批量更换首帧图片")
        self.btn_sel_all_start.setStyleSheet("QPushButton { background: #1D4ED8; color: white; font-weight: bold; padding: 4px 9px; border-radius: 4px; border: none; } QPushButton:hover { background: #1E40AF; }")
        self.btn_sel_all_start.clicked.connect(lambda: self.grid_viewport.select_all_by_slot("start"))
        self.btn_sel_all_start.setVisible(False)
        sel_row.addWidget(self.btn_sel_all_start)

        self.btn_sel_all_end = QPushButton("🎬 全选尾帧")
        self.btn_sel_all_end.setToolTip("仅选中所有卡片的下半板块（🎬 尾帧），便于批量设置或清空尾帧图片")
        self.btn_sel_all_end.setStyleSheet("QPushButton { background: #7C3AED; color: white; font-weight: bold; padding: 4px 9px; border-radius: 4px; border: none; } QPushButton:hover { background: #6D28D9; }")
        self.btn_sel_all_end.clicked.connect(lambda: self.grid_viewport.select_all_by_slot("end"))
        self.btn_sel_all_end.setVisible(False)
        sel_row.addWidget(self.btn_sel_all_end)

        btn_sel_inv = QPushButton("🔄 反选")
        btn_sel_inv.setStyleSheet("QPushButton { background: #FFFFFF; color: #1E40AF; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #93C5FD; } QPushButton:hover { background: #DBEAFE; }")
        btn_sel_inv.clicked.connect(lambda: self.grid_viewport.invert_selection())
        sel_row.addWidget(btn_sel_inv)

        btn_sel_none = QPushButton("⏹️ 取消选择")
        btn_sel_none.setStyleSheet("QPushButton { background: #FFFFFF; color: #475569; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #CBD5E1; } QPushButton:hover { background: #F1F5F9; }")
        btn_sel_none.clicked.connect(lambda: self.grid_viewport.clear_selection())
        sel_row.addWidget(btn_sel_none)

        self.lbl_sel_hint = QLabel("💡 拖拽框选 · Ctrl+点击多选 · Shift+连选 · Ctrl+滚轮缩放")
        self.lbl_sel_hint.setStyleSheet("font-size: 12px; color: #1E3A8A; border: none;")
        sel_row.addWidget(self.lbl_sel_hint)

        sel_row.addStretch()

        lbl_zoom = QLabel("🔍 图片缩放 (Ctrl+滚轮):")
        lbl_zoom.setStyleSheet("font-weight: bold; color: #1E40AF; border: none;")
        sel_row.addWidget(lbl_zoom)

        self.slider_zoom = QSlider(Qt.Orientation.Horizontal)
        self.slider_zoom.setRange(130, 440)
        self.slider_zoom.setValue(230)
        self.slider_zoom.setFixedWidth(130)
        self.slider_zoom.valueChanged.connect(self._on_zoom_slider_changed)
        sel_row.addWidget(self.slider_zoom)

        self.lbl_zoom_val = QLabel("100%")
        self.lbl_zoom_val.setFixedWidth(44)
        self.lbl_zoom_val.setStyleSheet("font-weight: bold; color: #1E40AF; border: none;")
        sel_row.addWidget(self.lbl_zoom_val)

        preset_outer.addLayout(sel_row)

        # Row 2B: Direct Preset Pickers for Selected Segments
        pick_row = QHBoxLayout()
        pick_row.setSpacing(8)

        lbl_batch_title = QLabel("🎯 为已选图片指定预设:")
        lbl_batch_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #1E3A8A; border: none;")
        pick_row.addWidget(lbl_batch_title)

        # 1) 提示词模板预设
        lbl_t = QLabel("📐 模板:")
        lbl_t.setStyleSheet("font-weight: bold; color: #1E293B; border: none;")
        pick_row.addWidget(lbl_t)
        self.combo_batch_tpl = QComboBox()
        self.combo_batch_tpl.setMinimumWidth(165)
        self.combo_batch_tpl.activated.connect(self._on_apply_batch_tpl)
        pick_row.addWidget(self.combo_batch_tpl)

        # 2) 运镜预设
        lbl_m = QLabel("🎥 运镜:")
        lbl_m.setStyleSheet("font-weight: bold; color: #1E293B; border: none;")
        pick_row.addWidget(lbl_m)
        self.combo_batch_mot = QComboBox()
        self.combo_batch_mot.setMinimumWidth(165)
        self.combo_batch_mot.activated.connect(self._on_apply_batch_mot)
        pick_row.addWidget(self.combo_batch_mot)

        # 3) 生成模式预设
        lbl_mode = QLabel("⚙️ 模式:")
        lbl_mode.setStyleSheet("font-weight: bold; color: #1E293B; border: none;")
        pick_row.addWidget(lbl_mode)
        self.combo_batch_mode = QComboBox()
        self.combo_batch_mode.setMinimumWidth(155)
        self.combo_batch_mode.activated.connect(self._on_apply_batch_mode)
        pick_row.addWidget(self.combo_batch_mode)

        # 4) 视频时长预设
        lbl_dur = QLabel("⏱️ 时长:")
        lbl_dur.setStyleSheet("font-weight: bold; color: #1E293B; border: none;")
        pick_row.addWidget(lbl_dur)
        self.combo_batch_dur = QComboBox()
        self.combo_batch_dur.setMinimumWidth(120)
        self.combo_batch_dur.addItem("⏱️ 选择时长直接应用...", None)
        self.combo_batch_dur.addItem("自动按字数计算", "auto")
        for s in (4, 5, 6, 8, 10):
            self.combo_batch_dur.addItem(f"固定 {s} 秒 ({s}s)", s)
        self.combo_batch_dur.activated.connect(self._on_apply_batch_dur)
        pick_row.addWidget(self.combo_batch_dur)

        pick_row.addStretch()

        btn_reset_sel = QPushButton("🧹 恢复所选为默认统一设置")
        btn_reset_sel.setToolTip("将当前选中分句的独立模板、独立运镜和生成模式恢复为跟随任务统一设置")
        btn_reset_sel.setStyleSheet(
            "QPushButton { background: #F59E0B; color: white; font-weight: bold; padding: 5px 12px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #D97706; }"
        )
        btn_reset_sel.clicked.connect(self._on_reset_selected_to_unified)
        pick_row.addWidget(btn_reset_sel)

        preset_outer.addLayout(pick_row)

        # Row 2C: Preset Group Average Distribution & Preset Pastel Color Manager
        group_row = QHBoxLayout()
        group_row.setSpacing(8)

        lbl_grp_title = QLabel("📦 按预设组合平均分配:")
        lbl_grp_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #7C3AED; border: none;")
        group_row.addWidget(lbl_grp_title)

        lbl_tg = QLabel("📐 模板组合:")
        lbl_tg.setStyleSheet("font-weight: bold; color: #1E293B; border: none;")
        group_row.addWidget(lbl_tg)
        self.combo_batch_tpl_group = QComboBox()
        self.combo_batch_tpl_group.setMinimumWidth(185)
        self.combo_batch_tpl_group.activated.connect(self._on_apply_batch_tpl_group)
        group_row.addWidget(self.combo_batch_tpl_group)

        lbl_mg = QLabel("🎥 运镜组合:")
        lbl_mg.setStyleSheet("font-weight: bold; color: #1E293B; border: none;")
        group_row.addWidget(lbl_mg)
        self.combo_batch_mot_group = QComboBox()
        self.combo_batch_mot_group.setMinimumWidth(185)
        self.combo_batch_mot_group.activated.connect(self._on_apply_batch_mot_group)
        group_row.addWidget(self.combo_batch_mot_group)

        lbl_dist = QLabel("分配顺序:")
        lbl_dist.setStyleSheet("font-weight: bold; color: #1E293B; border: none;")
        group_row.addWidget(lbl_dist)
        self.combo_group_dist_mode = QComboBox()
        self.combo_group_dist_mode.addItem("🔄 按顺序轮流平均 (1→2→3→1→2→3)", "cycle")
        self.combo_group_dist_mode.addItem("📊 按顺序分段平均 (1,1→2,2→3,3)", "block")
        self.combo_group_dist_mode.setToolTip(
            "选择多个任务卡片并应用组合预设时的平均分配方式：\n"
            "• 按顺序轮流平均：第1张用预设1、第2张用预设2、第3张用预设3、第4张用预设1...\n"
            "• 按顺序分段平均：前1/N卡片用预设1、中间1/N卡片用预设2、后1/N卡片用预设3..."
        )
        group_row.addWidget(self.combo_group_dist_mode)

        group_row.addStretch()

        self.btn_manage_groups_colors = QPushButton("🎨 管理预设组合 & 预设浅色")
        self.btn_manage_groups_colors.setToolTip(
            "打开预设组合与卡片专属浅色设置：\n"
            "• 创建/编辑/删除「模板预设组合」与「运镜预设组合」（同一预设可加入多个组合）\n"
            "• 为任意预设指定专属浅色（未指定颜色的独立预设默认显示为浅粉红色）"
        )
        self.btn_manage_groups_colors.setStyleSheet(
            "QPushButton { background: #EC4899; color: white; font-weight: bold; padding: 5px 14px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #DB2777; }"
        )
        self.btn_manage_groups_colors.clicked.connect(lambda: self._open_preset_group_and_color_dialog(initial_tab=0))
        group_row.addWidget(self.btn_manage_groups_colors)

        preset_outer.addLayout(group_row)
        root_layout.addWidget(preset_bar)

        # ═══════════════════════════════════════════════════════════════════
        # 3. 中部可折叠/展开区域：该任务的资源图（位于预设选项下面、所有断句任务图片上方）
        # ═══════════════════════════════════════════════════════════════════
        self.resource_panel = QFrame()
        self.resource_panel.setStyleSheet(
            "QFrame { background-color: #FFFDF9; border: 1px solid #CBD5E1; border-radius: 8px; }"
        )
        res_lay = QVBoxLayout(self.resource_panel)
        res_lay.setContentsMargins(10, 6, 10, 6)
        res_lay.setSpacing(6)

        res_header = QHBoxLayout()
        res_header.setSpacing(8)

        self.btn_toggle_resource = QPushButton("▼ 收起任务资源图库 (共 0 张)")
        self.btn_toggle_resource.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_toggle_resource.setStyleSheet(
            "QPushButton { background: #0F766E; color: white; font-weight: bold; font-size: 12px; padding: 5px 12px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background: #0D9488; }"
        )
        self.btn_toggle_resource.clicked.connect(self._toggle_resource_panel)
        res_header.addWidget(self.btn_toggle_resource)

        self.lbl_res_tip = QLabel("👆 先在下方多选断句图片，再点击任意「资源图」即可一键批量更换所选断句的图片！")
        self.lbl_res_tip.setStyleSheet("font-size: 12px; font-weight: bold; color: #0F766E; border: none;")
        res_header.addWidget(self.lbl_res_tip)

        res_header.addStretch()

        btn_add_res_img = QPushButton("➕ 添加本地图片到资源库")
        btn_add_res_img.setStyleSheet(
            "QPushButton { background: #10B981; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #059669; }"
        )
        btn_add_res_img.clicked.connect(self._on_add_local_images_to_resources)
        res_header.addWidget(btn_add_res_img)

        self.btn_clear_seg_img = QPushButton("🚫 清空所选板块图片")
        self.btn_clear_seg_img.setStyleSheet(
            "QPushButton { background: #EF4444; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #DC2626; }"
        )
        self.btn_clear_seg_img.clicked.connect(lambda: self._on_resource_card_clicked(""))
        res_header.addWidget(self.btn_clear_seg_img)

        btn_refresh_res = QPushButton("🔄 刷新资源图")
        btn_refresh_res.setStyleSheet(
            "QPushButton { background: #E2E8F0; color: #334155; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #CBD5E1; }"
            "QPushButton:hover { background: #CBD5E1; }"
        )
        btn_refresh_res.clicked.connect(self._populate_resource_images)
        res_header.addWidget(btn_refresh_res)

        res_lay.addLayout(res_header)

        # Collapsible body for resource images
        self.resource_scroll = QScrollArea()
        self.resource_scroll.setWidgetResizable(True)
        self.resource_scroll.setFixedHeight(154)
        self.resource_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.resource_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.resource_scroll.setStyleSheet("QScrollArea { background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 6px; }")

        self.resource_container = QWidget()
        self.resource_cards_layout = QHBoxLayout(self.resource_container)
        self.resource_cards_layout.setContentsMargins(8, 6, 8, 6)
        self.resource_cards_layout.setSpacing(10)
        self.resource_cards_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.resource_scroll.setWidget(self.resource_container)

        res_lay.addWidget(self.resource_scroll)
        root_layout.addWidget(self.resource_panel)

        # ═══════════════════════════════════════════════════════════════════
        # 4. 主体区域：当前任务所有断句任务图片的多排网格视图
        # ═══════════════════════════════════════════════════════════════════
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setStyleSheet("QScrollArea { border: 1px solid #CBD5E1; border-radius: 8px; background: #F8FAFC; }")

        self.grid_viewport = SegmentCardGridViewport(self)
        self.grid_viewport.selection_changed.connect(self._on_grid_selection_changed)
        self.grid_viewport.zoom_changed.connect(self._on_grid_zoom_changed)
        self.grid_scroll.setWidget(self.grid_viewport)

        root_layout.addWidget(self.grid_scroll, 1)

        # ═══════════════════════════════════════════════════════════════════
        # 5. 底部状态与关闭栏
        # ═══════════════════════════════════════════════════════════════════
        bottom_bar = QHBoxLayout()
        self.lbl_bottom_summary = QLabel("")
        self.lbl_bottom_summary.setStyleSheet("font-size: 12px; color: #475569; font-weight: bold;")
        bottom_bar.addWidget(self.lbl_bottom_summary)
        bottom_bar.addStretch()

        btn_done = QPushButton("✅ 完成并关闭窗口")
        btn_done.setStyleSheet(
            "QPushButton { background-color: #059669; color: white; font-size: 13px; font-weight: bold; padding: 7px 24px; border-radius: 6px; border: none; }"
            "QPushButton:hover { background-color: #047857; }"
        )
        btn_done.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_done)

        root_layout.addLayout(bottom_bar)

    # ───────────────────────────────────────────────────────────────────────
    # 任务列表加载与无缝切换
    # ───────────────────────────────────────────────────────────────────────
    def _load_projects_into_switcher(self):
        self.combo_task_switcher.blockSignals(True)
        self.combo_task_switcher.clear()
        self._project_list = []

        if self.storage_manager:
            try:
                self._project_list = self.storage_manager.list_projects() or []
            except Exception:
                self._project_list = []

        cur_idx = 0
        cur_norm = os.path.normcase(str(self.project_path.resolve())) if self.project_path else ""

        for i, p in enumerate(self._project_list):
            p_path = Path(p["path"])
            label = f"{p.get('index_str', '')}  {p.get('col1', '')}".strip()
            if p.get("col7"):
                label += f" - {p['col7']}"
            self.combo_task_switcher.addItem(label, str(p_path))
            if cur_norm and os.path.normcase(str(p_path.resolve())) == cur_norm:
                cur_idx = i

        if self.combo_task_switcher.count() > 0:
            self.combo_task_switcher.setCurrentIndex(cur_idx)
        self.combo_task_switcher.blockSignals(False)
        self._update_prev_next_buttons()

    def _update_prev_next_buttons(self):
        cnt = self.combo_task_switcher.count()
        idx = self.combo_task_switcher.currentIndex()
        self.btn_prev_task.setEnabled(cnt > 1 and idx > 0)
        self.btn_next_task.setEnabled(cnt > 1 and 0 <= idx < cnt - 1)

    def _switch_prev_task(self):
        idx = self.combo_task_switcher.currentIndex()
        if idx > 0:
            self.combo_task_switcher.setCurrentIndex(idx - 1)
            self._on_task_combo_switched(idx - 1)

    def _switch_next_task(self):
        idx = self.combo_task_switcher.currentIndex()
        if idx + 1 < self.combo_task_switcher.count():
            self.combo_task_switcher.setCurrentIndex(idx + 1)
            self._on_task_combo_switched(idx + 1)

    def _on_task_combo_switched(self, _index: int):
        new_path_str = self.combo_task_switcher.currentData()
        if not new_path_str:
            return
        new_path = Path(new_path_str)
        if not new_path.exists():
            return

        self._update_prev_next_buttons()

        # 同步切换主窗口与 ProjectDetailWidget 的当前项目，保证内外完全一致！
        if self.main_window and hasattr(self.main_window, "list_projects"):
            lw = self.main_window.list_projects
            lw.blockSignals(True)
            for i in range(lw.count()):
                it = lw.item(i)
                it_p = it.data(Qt.ItemDataRole.UserRole)
                if it_p and os.path.normcase(str(Path(it_p).resolve())) == os.path.normcase(str(new_path.resolve())):
                    lw.setCurrentItem(it)
                    break
            lw.blockSignals(False)

        if self.detail_widget:
            self.detail_widget.set_project(new_path)
            self.project_path = self.detail_widget.project_path
            self.project_model = self.detail_widget.project_model
        else:
            self.project_path = new_path
            self.project_model = ProjectModel(new_path)

        self._bind_current_project(initial_selected_rows=[])

    # ───────────────────────────────────────────────────────────────────────
    # 绑定当前任务的数据、预设下拉框、资源图库与断句网格
    # ───────────────────────────────────────────────────────────────────────
    def _refresh_end_frame_mode_ui(self):
        self.btn_end_frame_mode.blockSignals(True)
        self.btn_end_frame_mode.setChecked(self.end_frame_mode)
        if self.end_frame_mode:
            self.btn_end_frame_mode.setText("🎬 首尾帧模式：已开启")
            self.btn_end_frame_mode.setStyleSheet(
                "QPushButton { background: #7C3AED; color: white; font-weight: bold; padding: 4px 12px; border-radius: 5px; border: 2px solid #5B21B6; }"
                "QPushButton:hover { background: #6D28D9; }"
            )
            self.btn_sel_all_start.setVisible(True)
            self.btn_sel_all_end.setVisible(True)
            self.lbl_res_tip.setText(
                "👆 首尾帧模式已开启：每张卡片分为【上：📸首帧】与【下：🎬尾帧（默认空）】，点击或框选对应板块后再点「资源图」即可分别更换！"
            )
            self.lbl_res_tip.setStyleSheet("font-size: 12px; font-weight: bold; color: #6D28D9; border: none;")
        else:
            self.btn_end_frame_mode.setText("🎬 首尾帧模式：已关闭")
            self.btn_end_frame_mode.setStyleSheet(
                "QPushButton { background: #FFFFFF; color: #5B21B6; font-weight: bold; padding: 4px 12px; border-radius: 5px; border: 1px solid #C4B5FD; }"
                "QPushButton:hover { background: #F5F3FF; }"
            )
            self.btn_sel_all_start.setVisible(False)
            self.btn_sel_all_end.setVisible(False)
            self.lbl_res_tip.setText(
                "👆 先在下方多选断句图片，再点击任意「资源图」即可一键批量更换图片！（如需尾帧请点击上方「🎬 首尾帧模式」）"
            )
            self.lbl_res_tip.setStyleSheet("font-size: 12px; font-weight: bold; color: #0F766E; border: none;")
        self.btn_end_frame_mode.blockSignals(False)

    def _on_end_frame_mode_toggled(self, checked: bool):
        self.end_frame_mode = bool(checked)
        self._refresh_end_frame_mode_ui()

        if self.project_model:
            self.project_model.enable_end_frame = self.end_frame_mode
            try:
                self.project_model.save()
            except Exception as e:
                print(f"[SegmentVisualBatchManager] save enable_end_frame error: {e}")

        if self.detail_widget and self.detail_widget.project_model is self.project_model:
            self.detail_widget.enable_end_frame = self.end_frame_mode
            if hasattr(self.detail_widget, "chk_enable_end_frame"):
                self.detail_widget.chk_enable_end_frame.blockSignals(True)
                self.detail_widget.chk_enable_end_frame.setChecked(self.end_frame_mode)
                self.detail_widget.chk_enable_end_frame.blockSignals(False)
            if hasattr(self.detail_widget, "container_end_image"):
                self.detail_widget.container_end_image.setVisible(self.end_frame_mode)
            if hasattr(self.detail_widget, "table_segments"):
                for r in range(self.detail_widget.table_segments.rowCount()):
                    self.detail_widget.refresh_table_row_index_label(r)

        self.grid_viewport.on_end_frame_mode_changed()
        self._populate_resource_images()
        self._update_bottom_summary()
        if self.end_frame_mode:
            self._flash_save_badge("✅ 已开启「首尾帧模式」：每张卡片已拆分为上下两个独立板块（尾帧默认不自动分配，请按需自由选择）")
        else:
            self._flash_save_badge("✅ 已关闭「首尾帧模式」：已恢复单图卡片视图")

    def _bind_current_project(self, initial_selected_rows=None):
        if not self.project_model:
            return

        # 同步当前任务的首尾帧模式开关状态（默认不自动分配尾帧）
        if self.project_model.enable_end_frame is not None:
            self.end_frame_mode = bool(self.project_model.enable_end_frame)
        elif self.detail_widget is not None:
            self.end_frame_mode = bool(getattr(self.detail_widget, "enable_end_frame", False))
        else:
            self.end_frame_mode = bool(getattr(self.config_manager, "enable_end_frame", False)) if self.config_manager else False
        self._refresh_end_frame_mode_ui()

        # 确保每个断句已解析默认关联的首帧图片（尾帧绝不自动分配）
        segs = self.project_model.spanish_segments or []
        all_imgs = self._list_resource_images()
        for idx, seg in enumerate(segs):
            self._resolve_segment_default_image(idx, seg, all_imgs)

        self._populate_preset_combos()
        self._populate_resource_images()
        self.grid_viewport.recalculate_layout()
        self.grid_viewport.set_selected_indices(initial_selected_rows or [], emit_signal=True)
        self.grid_viewport.update()
        self._update_bottom_summary()

    def _list_resource_images(self) -> list:
        if not self.project_path:
            return []
        downloads_dir = self.project_path / "downloads"
        if not downloads_dir.exists():
            return []
        try:
            imgs = [p for p in downloads_dir.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTENSIONS]
            imgs.sort(key=lambda x: x.name)
            return imgs
        except Exception:
            return []

    def _resolve_segment_default_image(self, idx: int, seg: dict, all_imgs: list):
        if not all_imgs:
            return
        explicit_name = (seg.get("image_name") or "").strip()
        if explicit_name:
            for im in all_imgs:
                if im.name == explicit_name:
                    return
        idx_s1 = f"{idx + 1}"
        idx_s2 = f"{idx + 1:02d}"
        chosen = None
        for im in all_imgs:
            stem = im.stem
            if (
                stem == idx_s1
                or stem == idx_s2
                or stem.startswith(f"{idx_s1}_")
                or stem.startswith(f"{idx_s2}_")
                or stem.startswith(f"{idx_s1}-")
                or stem.startswith(f"{idx_s2}-")
            ):
                chosen = im
                break
        if not chosen:
            chosen = all_imgs[idx] if idx < len(all_imgs) else all_imgs[idx % len(all_imgs)]
        if chosen:
            seg["image_name"] = chosen.name

    def get_segment_pixmap(self, idx: int, seg: dict) -> QPixmap:
        if not self.project_path:
            return QPixmap()
        img_name = (seg.get("image_name") or "").strip()
        if not img_name:
            return QPixmap()
        fp = self.project_path / "downloads" / img_name
        if not fp.exists():
            return QPixmap()
        return _load_qpixmap_fast(str(fp), self._pixmap_cache)

    def get_segment_end_pixmap(self, idx: int, seg: dict) -> QPixmap:
        if not self.project_path:
            return QPixmap()
        end_name = (seg.get("end_image_name") or "").strip()
        if not end_name:
            return QPixmap()
        fp = self.project_path / "downloads" / end_name
        if not fp.exists():
            return QPixmap()
        return _load_qpixmap_fast(str(fp), self._pixmap_cache)

    def get_segment_display_badges(self, idx: int, seg: dict):
        """返回 (tpl_name, motion_name, mode_name, duration_label)"""
        tpl_id = seg.get("template_id") or ""
        mot_id = seg.get("motion_id") or ""

        if tpl_id and self.template_manager:
            t_obj = self.template_manager.get_template(tpl_id)
            tpl_name = t_obj["name"] if t_obj else "自定义模板"
        else:
            u_id = getattr(self.project_model, "selected_template_id", "") if self.project_model else ""
            t_obj = self.template_manager.get_template(u_id) if (self.template_manager and u_id) else None
            tpl_name = f"统:{t_obj['name']}" if t_obj else "统一模板"

        if mot_id and self.template_manager:
            m_obj = self.template_manager.get_motion(mot_id)
            mot_name = m_obj["name"] if m_obj else "自定义运镜"
        else:
            u_mid = getattr(self.project_model, "selected_motion_id", "") if self.project_model else ""
            m_obj = self.template_manager.get_motion(u_mid) if (self.template_manager and u_mid) else None
            mot_name = f"统:{m_obj['name']}" if m_obj else "统一运镜"

        default_mode_code = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
        eff_mode = seg.get("mode", default_mode_code) if seg.get("mode_overridden") else default_mode_code
        if self.end_frame_mode and (seg.get("end_image_name") or "").strip():
            mode_name = "首尾帧"
        else:
            mode_name = "素材模式" if eff_mode == "VIDEO_REFERENCES" else "帧模式"

        dur_val = seg.get("duration")
        if dur_val:
            dur_label = f"{dur_val}s"
        else:
            length = len(seg.get("text", ""))
            total = len(self.project_model.spanish_segments) if self.project_model else 1
            is_edge = (idx == 0 or idx == total - 1)
            dur_label = self.config_manager.get_duration_label(length, is_edge=is_edge) if self.config_manager else "6s"

        return tpl_name, mot_name, mode_name, dur_label

    def get_segment_card_color_info(self, seg: dict):
        """
        返回 (card_color_info, tpl_color_info, mot_color_info)。
        - 当任务分句遵循统一模板和统一运镜时，card_color_info / tpl_color_info / mot_color_info 均为 None（无额外颜色）。
        - 当单个分句选择了单独的模板或运镜预设时，返回该预设指定的浅色配置；若用户未为该预设指定颜色，默认返回浅粉红色 (#FCE7F3)。
        """
        tpl_id = (seg.get("template_id") or "").strip()
        mot_id = (seg.get("motion_id") or "").strip()

        has_custom_tpl = bool(tpl_id)
        has_custom_mot = bool(mot_id)

        if not has_custom_tpl and not has_custom_mot:
            return None, None, None

        tpl_color_key = ""
        mot_color_key = ""
        tpl_color_info = None
        mot_color_info = None

        if has_custom_tpl:
            t_obj = self.template_manager.get_template(tpl_id) if self.template_manager else None
            tpl_color_key = (t_obj.get("color") or "").strip() if t_obj else ""
            tpl_color_info = get_preset_color_info(tpl_color_key)

        if has_custom_mot:
            m_obj = self.template_manager.get_motion(mot_id) if self.template_manager else None
            mot_color_key = (m_obj.get("color") or "").strip() if m_obj else ""
            mot_color_info = get_preset_color_info(mot_color_key)

        # 决定整张卡片的背景浅色：
        # 1. 若运镜单独指定且该运镜设置了专属颜色 -> 用运镜专属颜色
        # 2. 否则若模板单独指定且该模板设置了专属颜色 -> 用模板专属颜色
        # 3. 否则（有单独运镜或单独模板，但用户未指定特殊颜色）-> 默认浅粉红色 (#FCE7F3)
        if has_custom_mot and mot_color_key:
            card_color_info = mot_color_info
        elif has_custom_tpl and tpl_color_key:
            card_color_info = tpl_color_info
        else:
            card_color_info = get_preset_color_info("")

        return card_color_info, tpl_color_info, mot_color_info

    def _populate_preset_combos(self):
        # 1. 任务级统一模板 & 统一运镜
        self.combo_unified_tpl.blockSignals(True)
        self.combo_unified_mot.blockSignals(True)
        self.combo_unified_tpl.clear()
        self.combo_unified_mot.clear()

        if self.template_manager:
            for t in self.template_manager.templates:
                self.combo_unified_tpl.addItem(t["name"], t["id"])
            for m in self.template_manager.motions:
                self.combo_unified_mot.addItem(m["name"], m["id"])

        if self.project_model:
            ti = self.combo_unified_tpl.findData(getattr(self.project_model, "selected_template_id", ""))
            if ti >= 0:
                self.combo_unified_tpl.setCurrentIndex(ti)
            mi = self.combo_unified_mot.findData(getattr(self.project_model, "selected_motion_id", ""))
            if mi >= 0:
                self.combo_unified_mot.setCurrentIndex(mi)

        self.combo_unified_tpl.blockSignals(False)
        self.combo_unified_mot.blockSignals(False)

        # 2. 批量指定分句模板下拉框（附带浅色标记）
        u_tpl_name = self.combo_unified_tpl.currentText() or "未选择"
        u_mot_name = self.combo_unified_mot.currentText() or "未选择"

        self.combo_batch_tpl.blockSignals(True)
        self.combo_batch_tpl.clear()
        self.combo_batch_tpl.addItem("📐 选择模板直接应用到已选...", None)
        self.combo_batch_tpl.addItem(f"-- 遵循统一模板 ({u_tpl_name}) [无额外底色] --", "")
        if self.template_manager:
            for t in self.template_manager.templates:
                ck = (t.get("color") or "").strip()
                c_info = get_preset_color_info(ck)
                idx = self.combo_batch_tpl.count()
                label = f"{t['name']}  ({c_info['label']})" if ck else f"{t['name']}  (🌸默认浅粉红)"
                self.combo_batch_tpl.addItem(label, t["id"])
                self.combo_batch_tpl.setItemData(idx, QBrush(QColor(c_info["bg"])), Qt.ItemDataRole.BackgroundRole)
                self.combo_batch_tpl.setItemData(idx, QBrush(QColor(c_info["tag_fg"])), Qt.ItemDataRole.ForegroundRole)
        self.combo_batch_tpl.setCurrentIndex(0)
        self.combo_batch_tpl.blockSignals(False)

        # 3. 批量指定分句运镜下拉框（附带浅色标记）
        self.combo_batch_mot.blockSignals(True)
        self.combo_batch_mot.clear()
        self.combo_batch_mot.addItem("🎥 选择运镜直接应用到已选...", None)
        self.combo_batch_mot.addItem(f"-- 遵循统一运镜 ({u_mot_name}) [无额外底色] --", "")
        if self.template_manager:
            for m in self.template_manager.motions:
                ck = (m.get("color") or "").strip()
                c_info = get_preset_color_info(ck)
                idx = self.combo_batch_mot.count()
                label = f"{m['name']}  ({c_info['label']})" if ck else f"{m['name']}  (🌸默认浅粉红)"
                self.combo_batch_mot.addItem(label, m["id"])
                self.combo_batch_mot.setItemData(idx, QBrush(QColor(c_info["bg"])), Qt.ItemDataRole.BackgroundRole)
                self.combo_batch_mot.setItemData(idx, QBrush(QColor(c_info["tag_fg"])), Qt.ItemDataRole.ForegroundRole)
        self.combo_batch_mot.setCurrentIndex(0)
        self.combo_batch_mot.blockSignals(False)

        # 4. 批量指定生成模式下拉框
        default_mode_code = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
        default_mode_label = "素材模式" if default_mode_code == "VIDEO_REFERENCES" else "帧模式"
        self.combo_batch_mode.blockSignals(True)
        self.combo_batch_mode.clear()
        self.combo_batch_mode.addItem("⚙️ 选择模式直接应用到已选...", None)
        self.combo_batch_mode.addItem(f"-- 遵循规则设置 ({default_mode_label}) --", "")
        self.combo_batch_mode.addItem("帧模式 (First Frame)", "VIDEO_FRAMES")
        self.combo_batch_mode.addItem("素材模式 (Reference)", "VIDEO_REFERENCES")
        self.combo_batch_mode.setCurrentIndex(0)
        self.combo_batch_mode.blockSignals(False)

        # 5. 模板预设组合下拉框
        if hasattr(self, "combo_batch_tpl_group"):
            self.combo_batch_tpl_group.blockSignals(True)
            self.combo_batch_tpl_group.clear()
            self.combo_batch_tpl_group.addItem("📦 选择模板组合平均分配...", None)
            if self.template_manager:
                for g in getattr(self.template_manager, "template_groups", []):
                    valid_ids = [pid for pid in g.get("preset_ids", []) if self.template_manager.get_template(pid)]
                    self.combo_batch_tpl_group.addItem(f"📦 {g.get('name', '未命名')} ({len(valid_ids)}个模板)", g.get("id"))
            self.combo_batch_tpl_group.addItem("➕ 新建 / 管理模板组合...", "__MANAGE_TPL_GROUPS__")
            self.combo_batch_tpl_group.setCurrentIndex(0)
            self.combo_batch_tpl_group.blockSignals(False)

        # 6. 运镜预设组合下拉框
        if hasattr(self, "combo_batch_mot_group"):
            self.combo_batch_mot_group.blockSignals(True)
            self.combo_batch_mot_group.clear()
            self.combo_batch_mot_group.addItem("📦 选择运镜组合平均分配...", None)
            if self.template_manager:
                for g in getattr(self.template_manager, "motion_groups", []):
                    valid_ids = [pid for pid in g.get("preset_ids", []) if self.template_manager.get_motion(pid)]
                    self.combo_batch_mot_group.addItem(f"📦 {g.get('name', '未命名')} ({len(valid_ids)}个运镜)", g.get("id"))
            self.combo_batch_mot_group.addItem("➕ 新建 / 管理运镜组合...", "__MANAGE_MOT_GROUPS__")
            self.combo_batch_mot_group.setCurrentIndex(0)
            self.combo_batch_mot_group.blockSignals(False)

    # ───────────────────────────────────────────────────────────────────────
    # 资源图面板（展示、展开/收起、点击批量更换断句图片）
    # ───────────────────────────────────────────────────────────────────────
    def _toggle_resource_panel(self):
        self._resource_expanded = not self._resource_expanded
        self.resource_scroll.setVisible(self._resource_expanded)
        imgs = self._list_resource_images()
        arrow = "▼ 收起任务资源图库" if self._resource_expanded else "▶ 展开任务资源图库"
        self.btn_toggle_resource.setText(f"{arrow} (共 {len(imgs)} 张)")

    def _populate_resource_images(self):
        while self.resource_cards_layout.count():
            item = self.resource_cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        imgs = self._list_resource_images()
        arrow = "▼ 收起任务资源图库" if self._resource_expanded else "▶ 展开任务资源图库"
        self.btn_toggle_resource.setText(f"{arrow} (共 {len(imgs)} 张)")

        segs = self.project_model.spanish_segments if self.project_model else []
        usage_map = {}
        for s in segs:
            im_n = (s.get("image_name") or "").strip()
            if im_n:
                usage_map[im_n] = usage_map.get(im_n, 0) + 1
            if self.end_frame_mode:
                end_n = (s.get("end_image_name") or "").strip()
                if end_n:
                    usage_map[end_n] = usage_map.get(end_n, 0) + 1

        if not imgs:
            lbl_empty = QLabel("📂 当前任务 downloads/ 目录下暂无图片资源，可点击右上角「➕ 添加本地图片到资源库」导入。")
            lbl_empty.setStyleSheet("color: #64748B; font-size: 12px; padding: 20px;")
            self.resource_cards_layout.addWidget(lbl_empty)
            return

        for img_p in imgs:
            pm = _load_qpixmap_fast(str(img_p), self._pixmap_cache)
            card = ResourceImageCard(img_p, pm, usage_count=usage_map.get(img_p.name, 0), parent=self.resource_container)
            card.clicked_resource.connect(self._on_resource_card_clicked)
            self.resource_cards_layout.addWidget(card)

    def _on_add_local_images_to_resources(self):
        if not self.project_path:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "选择要加入当前任务资源库的图片",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.gif *.bmp)"
        )
        if not files:
            return
        downloads_dir = self.project_path / "downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        copied = 0
        for f in files:
            src = Path(f)
            if src.is_file():
                dst = downloads_dir / src.name
                try:
                    if src.resolve() != dst.resolve():
                        shutil.copy2(src, dst)
                    copied += 1
                except Exception as e:
                    print(f"[SegmentVisualBatchManager] copy image error: {e}")
        if copied > 0:
            self._populate_resource_images()
            if self.detail_widget:
                self.detail_widget.refresh_media_list()
                self.detail_widget.refresh_prop_image_combo_items()
            self._flash_save_badge(f"✅ 已导入 {copied} 张图片到任务资源库")

    def _on_resource_card_clicked(self, image_name: str):
        selected_slots = sorted(self.grid_viewport.selected_slots)
        if not selected_slots:
            msg = (
                "请先在下方网格中点击或拖拽框选需要更换图片的【上板块·📸首帧】或【下板块·🎬尾帧】，然后再点击上方的资源图！"
                if self.end_frame_mode
                else "请先在下方网格中点击或拖拽框选需要更换图片的断句卡片，然后再点击上方的资源图！"
            )
            QMessageBox.information(self, "请先选择断句板块", msg)
            return
        if not self.project_model:
            return

        segs = self.project_model.spanish_segments
        changed_rows = set()
        start_cnt = 0
        end_cnt = 0

        for r, role in selected_slots:
            if 0 <= r < len(segs):
                if self.end_frame_mode and role == "end":
                    segs[r]["end_image_name"] = image_name
                    end_cnt += 1
                else:
                    segs[r]["image_name"] = image_name
                    start_cnt += 1
                changed_rows.add(r)

        rows = sorted(changed_rows)
        self._save_and_sync_detail_widget(rows)
        self._populate_resource_images()
        self.grid_viewport.update()
        disp = image_name if image_name else "无图片(已清空)"
        if self.end_frame_mode:
            parts = []
            if start_cnt:
                parts.append(f"📸首帧 {start_cnt} 个")
            if end_cnt:
                parts.append(f"🎬尾帧 {end_cnt} 个")
            self._flash_save_badge(f"✅ 已将 {' + '.join(parts)} 更换为: {disp}")
        else:
            self._flash_save_badge(f"✅ 已将 {len(rows)} 个断句的首帧图片批量更换为: {disp}")

    # ───────────────────────────────────────────────────────────────────────
    # 顶部预设选项卡批量修改回调
    # ───────────────────────────────────────────────────────────────────────
    def _ensure_has_selection(self) -> list:
        rows = sorted(self.grid_viewport.selected_indices)
        if not rows:
            QMessageBox.information(
                self,
                "请先选择断句图片",
                "请先在下方网格中点击、Ctrl+点击、Shift+连选、或直接拖拽鼠标框选要修改的断句图片！"
            )
        return rows

    def _on_unified_tpl_changed(self, _idx: int):
        if not self.project_model:
            return
        tpl_id = self.combo_unified_tpl.currentData() or ""
        self.project_model.selected_template_id = tpl_id
        self.project_model.save()
        if self.detail_widget:
            i = self.detail_widget.combo_templates.findData(tpl_id)
            if i >= 0:
                self.detail_widget.combo_templates.setCurrentIndex(i)
        self._populate_preset_combos()
        self.grid_viewport.update()
        self._flash_save_badge(f"✅ 已更新任务统一模板为: {self.combo_unified_tpl.currentText()}")

    def _on_unified_mot_changed(self, _idx: int):
        if not self.project_model:
            return
        mot_id = self.combo_unified_mot.currentData() or ""
        self.project_model.selected_motion_id = mot_id
        self.project_model.save()
        if self.detail_widget:
            i = self.detail_widget.combo_motions.findData(mot_id)
            if i >= 0:
                self.detail_widget.combo_motions.setCurrentIndex(i)
        self._populate_preset_combos()
        self.grid_viewport.update()
        self._flash_save_badge(f"✅ 已更新任务统一运镜为: {self.combo_unified_mot.currentText()}")

    def _on_apply_batch_tpl(self, idx: int):
        if idx <= 0:
            return
        tpl_val = self.combo_batch_tpl.currentData()
        tpl_label = self.combo_batch_tpl.currentText()
        self.combo_batch_tpl.setCurrentIndex(0)

        rows = self._ensure_has_selection()
        if not rows or not self.project_model:
            return
        segs = self.project_model.spanish_segments
        for r in rows:
            if 0 <= r < len(segs):
                segs[r]["template_id"] = tpl_val or ""
        self._save_and_sync_detail_widget(rows, update_prompts=True)
        self.grid_viewport.update()
        self._flash_save_badge(f"✅ 已为 {len(rows)} 个断句设置模板: {tpl_label}")

    def _on_apply_batch_mot(self, idx: int):
        if idx <= 0:
            return
        mot_val = self.combo_batch_mot.currentData()
        mot_label = self.combo_batch_mot.currentText()
        self.combo_batch_mot.setCurrentIndex(0)

        rows = self._ensure_has_selection()
        if not rows or not self.project_model:
            return
        segs = self.project_model.spanish_segments
        for r in rows:
            if 0 <= r < len(segs):
                segs[r]["motion_id"] = mot_val or ""
        self._save_and_sync_detail_widget(rows, update_prompts=True)
        self.grid_viewport.update()
        self._flash_save_badge(f"✅ 已为 {len(rows)} 个断句设置运镜: {mot_label}")

    def _open_preset_group_and_color_dialog(self, initial_tab: int = 0):
        def _on_changed():
            self._populate_preset_combos()
            self.grid_viewport.update()

        dlg = PresetGroupAndColorDialog(
            self.template_manager,
            on_changed_callback=_on_changed,
            initial_tab=initial_tab,
            parent=self
        )
        dlg.exec()
        self._populate_preset_combos()
        self.grid_viewport.update()

    def _on_apply_batch_tpl_group(self, idx: int):
        if idx <= 0:
            return
        grp_id = self.combo_batch_tpl_group.currentData()
        self.combo_batch_tpl_group.setCurrentIndex(0)
        if not grp_id:
            return
        if grp_id == "__MANAGE_TPL_GROUPS__":
            self._open_preset_group_and_color_dialog(initial_tab=1)
            return

        if not self.template_manager:
            return
        grp = self.template_manager.get_template_group(grp_id)
        if not grp:
            return
        valid_ids = [pid for pid in grp.get("preset_ids", []) if self.template_manager.get_template(pid)]
        if not valid_ids:
            QMessageBox.warning(
                self, "组合为空",
                f"模板组合【{grp.get('name', '')}】中尚未勾选任何模板预设！\n将为您打开组合设置界面进行勾选。"
            )
            self._open_preset_group_and_color_dialog(initial_tab=1)
            return

        rows = self._ensure_has_selection()
        if not rows or not self.project_model:
            return

        dist_mode = self.combo_group_dist_mode.currentData() if hasattr(self, "combo_group_dist_mode") else "cycle"
        segs = self.project_model.spanish_segments
        n_rows = len(rows)
        n_presets = len(valid_ids)

        for i, r in enumerate(rows):
            if 0 <= r < len(segs):
                if dist_mode == "block":
                    p_idx = min(n_presets - 1, (i * n_presets) // n_rows)
                else:
                    p_idx = i % n_presets
                segs[r]["template_id"] = valid_ids[p_idx]

        self._save_and_sync_detail_widget(rows, update_prompts=True)
        self.grid_viewport.update()
        self._flash_save_badge(
            f"✅ 已将模板组合【{grp.get('name', '')}】({n_presets}个模板) 按顺序平均分配到 {n_rows} 个任务卡片！"
        )

    def _on_apply_batch_mot_group(self, idx: int):
        if idx <= 0:
            return
        grp_id = self.combo_batch_mot_group.currentData()
        self.combo_batch_mot_group.setCurrentIndex(0)
        if not grp_id:
            return
        if grp_id == "__MANAGE_MOT_GROUPS__":
            self._open_preset_group_and_color_dialog(initial_tab=0)
            return

        if not self.template_manager:
            return
        grp = self.template_manager.get_motion_group(grp_id)
        if not grp:
            return
        valid_ids = [pid for pid in grp.get("preset_ids", []) if self.template_manager.get_motion(pid)]
        if not valid_ids:
            QMessageBox.warning(
                self, "组合为空",
                f"运镜组合【{grp.get('name', '')}】中尚未勾选任何运镜预设！\n将为您打开组合设置界面进行勾选。"
            )
            self._open_preset_group_and_color_dialog(initial_tab=0)
            return

        rows = self._ensure_has_selection()
        if not rows or not self.project_model:
            return

        dist_mode = self.combo_group_dist_mode.currentData() if hasattr(self, "combo_group_dist_mode") else "cycle"
        segs = self.project_model.spanish_segments
        n_rows = len(rows)
        n_presets = len(valid_ids)

        for i, r in enumerate(rows):
            if 0 <= r < len(segs):
                if dist_mode == "block":
                    p_idx = min(n_presets - 1, (i * n_presets) // n_rows)
                else:
                    p_idx = i % n_presets
                segs[r]["motion_id"] = valid_ids[p_idx]

        self._save_and_sync_detail_widget(rows, update_prompts=True)
        self.grid_viewport.update()
        self._flash_save_badge(
            f"✅ 已将运镜组合【{grp.get('name', '')}】({n_presets}个运镜) 按顺序平均分配到 {n_rows} 个任务卡片！"
        )

    def _on_apply_batch_mode(self, idx: int):
        if idx <= 0:
            return
        mode_val = self.combo_batch_mode.currentData()
        mode_label = self.combo_batch_mode.currentText()
        self.combo_batch_mode.setCurrentIndex(0)

        rows = self._ensure_has_selection()
        if not rows or not self.project_model:
            return
        default_mode_code = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
        segs = self.project_model.spanish_segments
        for r in rows:
            if 0 <= r < len(segs):
                if mode_val:
                    segs[r]["mode"] = mode_val
                    segs[r]["mode_overridden"] = True
                else:
                    segs[r]["mode"] = default_mode_code
                    segs[r]["mode_overridden"] = False
        self._save_and_sync_detail_widget(rows)
        self.grid_viewport.update()
        self._flash_save_badge(f"✅ 已为 {len(rows)} 个断句设置生成模式: {mode_label}")

    def _on_apply_batch_dur(self, idx: int):
        if idx <= 0:
            return
        dur_val = self.combo_batch_dur.currentData()
        dur_label = self.combo_batch_dur.currentText()
        self.combo_batch_dur.setCurrentIndex(0)

        rows = self._ensure_has_selection()
        if not rows or not self.project_model:
            return
        segs = self.project_model.spanish_segments
        total = len(segs)
        for r in rows:
            if 0 <= r < total:
                if dur_val == "auto":
                    length = len(segs[r].get("text", ""))
                    is_edge = (r == 0 or r == total - 1)
                    calc_d = self.config_manager.get_duration_for_length(length, is_edge=is_edge) if self.config_manager else 6
                    segs[r]["duration"] = calc_d
                else:
                    segs[r]["duration"] = int(dur_val)
        self._save_and_sync_detail_widget(rows)
        self.grid_viewport.update()
        self._flash_save_badge(f"✅ 已为 {len(rows)} 个断句设置时长: {dur_label}")

    def _on_reset_selected_to_unified(self):
        rows = self._ensure_has_selection()
        if not rows or not self.project_model:
            return
        default_mode_code = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
        segs = self.project_model.spanish_segments
        for r in rows:
            if 0 <= r < len(segs):
                segs[r]["template_id"] = ""
                segs[r]["motion_id"] = ""
                segs[r]["mode"] = default_mode_code
                segs[r]["mode_overridden"] = False
        self._save_and_sync_detail_widget(rows, update_prompts=True)
        self.grid_viewport.update()
        self._flash_save_badge(f"✅ 已将 {len(rows)} 个断句恢复为任务默认统一设置")

    def _save_and_sync_detail_widget(self, changed_rows: list, update_prompts: bool = False):
        if not self.project_model:
            return
        try:
            self.project_model.save()
        except Exception as e:
            print(f"[SegmentVisualBatchManager] save error: {e}")

        if self.detail_widget and self.detail_widget.project_model is self.project_model:
            try:
                self.detail_widget.table_segments.setUpdatesEnabled(False)
                for r in changed_rows:
                    if update_prompts:
                        self.detail_widget.update_segment_row_prompt(r)
                    self.detail_widget.refresh_table_row_index_label(r)
                self.detail_widget.table_segments.setUpdatesEnabled(True)
                cur = self.detail_widget.table_segments.currentItem()
                if cur is not None:
                    self.detail_widget.on_table_selection_changed(cur, None)
            except Exception as e:
                print(f"[SegmentVisualBatchManager] sync detail_widget warning: {e}")
        self._update_bottom_summary()

    def _flash_save_badge(self, text: str):
        self.lbl_save_status.setText(text)
        QToolTip.showText(QCursor.pos(), text, self)

    # ───────────────────────────────────────────────────────────────────────
    # 选中状态与缩放联动
    # ───────────────────────────────────────────────────────────────────────
    def _on_grid_selection_changed(self, selected_rows: list):
        total = len(self.project_model.spanish_segments) if self.project_model else 0
        sel_cnt = len(selected_rows)
        if sel_cnt > 0:
            if self.end_frame_mode:
                s_cnt = sum(1 for _, role in self.grid_viewport.selected_slots if role == "start")
                e_cnt = sum(1 for _, role in self.grid_viewport.selected_slots if role == "end")
                self.lbl_selection_info.setText(
                    f"✅ 已选 {sel_cnt}/{total} 句 (📸首帧 {s_cnt} · 🎬尾帧 {e_cnt})"
                )
            else:
                preview = "、".join(f"#{r + 1:02d}" for r in selected_rows[:12])
                if sel_cnt > 12:
                    preview += f" 等共 {sel_cnt} 句"
                self.lbl_selection_info.setText(f"✅ 已选 {sel_cnt} / {total} 个断句 ({preview})")
        else:
            if self.end_frame_mode:
                self.lbl_selection_info.setText(f"已选 0 / {total} 句 (可点选上:首帧 / 下:尾帧)")
            else:
                self.lbl_selection_info.setText(f"已选 0 / {total} 个断句图片")

        # 同步选中状态回 ProjectDetailWidget 的表格
        if self.detail_widget and hasattr(self.detail_widget, "table_segments"):
            tbl = self.detail_widget.table_segments
            tbl.blockSignals(True)
            tbl.clearSelection()
            for r in selected_rows:
                if 0 <= r < tbl.rowCount():
                    tbl.selectRow(r)
            tbl.blockSignals(False)

    def _on_zoom_slider_changed(self, val: int):
        self.grid_viewport.set_card_width(val, emit_signal=False)
        pct = int(round(val / 230.0 * 100))
        self.lbl_zoom_val.setText(f"{pct}%")

    def _on_grid_zoom_changed(self, new_width: int):
        self.slider_zoom.blockSignals(True)
        self.slider_zoom.setValue(new_width)
        self.slider_zoom.blockSignals(False)
        pct = int(round(new_width / 230.0 * 100))
        self.lbl_zoom_val.setText(f"{pct}%")

    def _update_bottom_summary(self):
        if not self.project_model:
            self.lbl_bottom_summary.setText("")
            return
        segs = self.project_model.spanish_segments or []
        imgs = self._list_resource_images()
        custom_tpl_cnt = sum(1 for s in segs if s.get("template_id"))
        custom_mot_cnt = sum(1 for s in segs if s.get("motion_id"))
        end_cnt = sum(1 for s in segs if (s.get("end_image_name") or "").strip())
        end_part = f"  |  🎬 首尾帧模式：已开启（已配尾帧 {end_cnt}/{len(segs)} 句）" if self.end_frame_mode else ""
        self.lbl_bottom_summary.setText(
            f"📊 当前任务：{self.project_model.project_id}  |  共 {len(segs)} 个断句  |  "
            f"任务资源图：{len(imgs)} 张  |  独立模板断句：{custom_tpl_cnt} 句  |  独立运镜断句：{custom_mot_cnt} 句{end_part}"
        )
