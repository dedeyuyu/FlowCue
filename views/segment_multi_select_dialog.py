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
    QToolTip, QSizePolicy, QCheckBox
)
from PyQt6.QtCore import Qt, QRect, QPoint, QSize, pyqtSignal, QTimer
from PyQt6.QtGui import (
    QPixmap, QImage, QPainter, QColor, QPen, QBrush, QFont, QFontMetrics,
    QCursor, QKeySequence, QShortcut
)

from models.project_model import ProjectModel
from services.text_processor import TextProcessor

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
    - 支持：
      1. Ctrl + 鼠标滚轮：实时无级调整卡片尺寸（card_width 130px ~ 440px），自动计算每行排列数量
      2. 鼠标左键单击：单选卡片
      3. Ctrl + 左键单击：切换单个卡片选中状态
      4. Shift + 左键单击：范围连选 [anchor .. clicked]
      5. 鼠标左键拖拽（橡皮筋框选）：画出半透明选框，自动选中框内所有断句卡片（按住 Ctrl/Shift 拖拽可追加框选）
    """
    selection_changed = pyqtSignal(list)      # sorted list of selected indices
    zoom_changed = pyqtSignal(int)            # new card_width
    card_double_clicked = pyqtSignal(int)     # segment index

    def __init__(self, parent_dialog=None):
        super().__init__(parent_dialog)
        self.dialog = parent_dialog
        self.card_width = 230
        self.card_gap = 12
        self.margin = 14

        self.selected_indices = set()
        self.anchor_index = 0
        self.hover_index = -1

        self._is_dragging_box = False
        self._drag_origin = QPoint()
        self._drag_current = QPoint()
        self._drag_base_selection = set()
        self._pressed_index = -1
        self._press_modifiers = Qt.KeyboardModifier.NoModifier

        self._card_rects = []  # list of QRect for each segment
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

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

    def _compute_card_height(self) -> int:
        # Image area takes ~68% height + metadata/tags/text area ~92px
        img_h = int(self.card_width * 0.72)
        return img_h + 94

    def recalculate_layout(self):
        segs = self._get_segments()
        count = len(segs)
        if count == 0:
            self._card_rects = []
            self.setMinimumHeight(260)
            return

        avail_w = max(200, self.width() - self.margin * 2)
        cols = max(1, (avail_w + self.card_gap) // (self.card_width + self.card_gap))
        card_h = self._compute_card_height()

        rects = []
        for idx in range(count):
            r = idx // cols
            c = idx % cols
            x = self.margin + c * (self.card_width + self.card_gap)
            y = self.margin + r * (card_h + self.card_gap)
            rects.append(QRect(x, y, self.card_width, card_h))

        self._card_rects = rects
        total_rows = (count + cols - 1) // cols
        total_h = self.margin * 2 + total_rows * card_h + max(0, total_rows - 1) * self.card_gap + 20
        self.setMinimumHeight(max(300, total_h))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.recalculate_layout()

    def _index_at_pos(self, pos: QPoint) -> int:
        for idx, rect in enumerate(self._card_rects):
            if rect.contains(pos):
                return idx
        return -1

    def select_all(self):
        segs = self._get_segments()
        self.selected_indices = set(range(len(segs)))
        self.update()
        self.selection_changed.emit(sorted(self.selected_indices))

    def clear_selection(self):
        self.selected_indices.clear()
        self.update()
        self.selection_changed.emit([])

    def invert_selection(self):
        segs = self._get_segments()
        all_set = set(range(len(segs)))
        self.selected_indices = all_set - self.selected_indices
        self.update()
        self.selection_changed.emit(sorted(self.selected_indices))

    def set_selected_indices(self, indices, emit_signal: bool = True):
        segs = self._get_segments()
        total = len(segs)
        self.selected_indices = {i for i in indices if 0 <= i < total}
        if self.selected_indices:
            self.anchor_index = min(self.selected_indices)
        self.update()
        if emit_signal:
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
            self._pressed_index = self._index_at_pos(pos)
            self._press_modifiers = event.modifiers()
            if (self._press_modifiers & Qt.KeyboardModifier.ControlModifier) or (
                self._press_modifiers & Qt.KeyboardModifier.ShiftModifier
            ):
                self._drag_base_selection = set(self.selected_indices)
            else:
                self._drag_base_selection = set()
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
                hit = {idx for idx, r in enumerate(self._card_rects) if box.intersects(r)}
                new_sel = self._drag_base_selection | hit
                if new_sel != self.selected_indices:
                    self.selected_indices = new_sel
                    self.selection_changed.emit(sorted(self.selected_indices))
                self.update()
                event.accept()
                return

        hov = self._index_at_pos(pos)
        if hov != self.hover_index:
            self.hover_index = hov
            self.update()
            if hov >= 0:
                segs = self._get_segments()
                if hov < len(segs):
                    seg = segs[hov]
                    tpl_name, mot_name, mode_name, dur_label = self.dialog.get_segment_display_badges(hov, seg)
                    img_name = seg.get("image_name") or "未绑定"
                    end_img = seg.get("end_image_name") or ""
                    end_line = f"\n🎬 尾帧图片: {end_img}" if end_img else ""
                    tip = (
                        f"【第 {hov + 1:02d} 句】\n"
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

            idx = self._pressed_index
            mods = self._press_modifiers
            if idx < 0:
                if not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)):
                    self.selected_indices.clear()
                    self.selection_changed.emit([])
                    self.update()
            else:
                if mods & Qt.KeyboardModifier.ShiftModifier:
                    start = min(self.anchor_index, idx)
                    end = max(self.anchor_index, idx)
                    range_set = set(range(start, end + 1))
                    if mods & Qt.KeyboardModifier.ControlModifier:
                        self.selected_indices |= range_set
                    else:
                        self.selected_indices = range_set
                elif mods & Qt.KeyboardModifier.ControlModifier:
                    if idx in self.selected_indices:
                        self.selected_indices.remove(idx)
                    else:
                        self.selected_indices.add(idx)
                    self.anchor_index = idx
                else:
                    self.selected_indices = {idx}
                    self.anchor_index = idx

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

        if len(self._card_rects) != len(segs):
            self.recalculate_layout()

        clip_rect = event.rect()
        img_h = int(self.card_width * 0.72)

        font_idx = QFont("Microsoft YaHei", 10, QFont.Weight.Bold)
        font_tag = QFont("Microsoft YaHei", 8, QFont.Weight.Bold)
        font_text = QFont("Microsoft YaHei", 9)

        for idx, card_rect in enumerate(self._card_rects):
            if not card_rect.intersects(clip_rect):
                continue

            seg = segs[idx]
            is_sel = idx in self.selected_indices
            is_hov = idx == self.hover_index

            # 1. Card background & border
            if is_dark:
                bg_color = QColor("#1E293B") if is_sel else (QColor("#2E2A1E") if is_hov else QColor("#242429"))
                border_color = QColor("#3B82F6") if is_sel else (QColor("#F59E0B") if is_hov else QColor("#3F3F46"))
            else:
                bg_color = QColor("#EFF6FF") if is_sel else (QColor("#FFFBEB") if is_hov else QColor("#FFFFFF"))
                border_color = QColor("#2563EB") if is_sel else (QColor("#F59E0B") if is_hov else QColor("#CBD5E1"))
            border_width = 3 if is_sel else (2 if is_hov else 1)

            painter.setPen(QPen(border_color, border_width))
            painter.setBrush(QBrush(bg_color))
            painter.drawRoundedRect(card_rect.adjusted(1, 1, -1, -1), 8, 8)

            # 2. Image box (Primary visual focus!)
            img_rect = QRect(card_rect.left() + 6, card_rect.top() + 6, card_rect.width() - 12, img_h - 6)
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

            # 3. Top-left #Index + checkbox indicator overlay on image
            badge_str = f"{'☑' if is_sel else '☐'} #{idx + 1:02d}"
            painter.setFont(font_idx)
            fm_idx = QFontMetrics(font_idx)
            bw = fm_idx.horizontalAdvance(badge_str) + 14
            bh = 22
            idx_rect = QRect(img_rect.left() + 6, img_rect.top() + 6, bw, bh)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#2563EB") if is_sel else QColor(15, 23, 42, 200)))
            painter.drawRoundedRect(idx_rect, 5, 5)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(idx_rect, Qt.AlignmentFlag.AlignCenter, badge_str)

            # 4. Top-right duration badge on image
            tpl_name, mot_name, mode_name, dur_label = self.dialog.get_segment_display_badges(idx, seg)
            painter.setFont(font_tag)
            fm_tag = QFontMetrics(font_tag)
            dw = fm_tag.horizontalAdvance(dur_label) + 10
            dur_rect = QRect(img_rect.right() - dw - 6, img_rect.top() + 6, dw, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#DC2626") if "超时" in dur_label else QColor(15, 23, 42, 200)))
            painter.drawRoundedRect(dur_rect, 4, 4)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(dur_rect, Qt.AlignmentFlag.AlignCenter, dur_label)

            # 5. Bottom of image: Image filename bar
            img_name = seg.get("image_name") or "未指定图片"
            end_name = seg.get("end_image_name") or ""
            img_label_str = f"📸 {img_name}" + (f" ➔ 🎬 {end_name}" if end_name else "")
            name_bar_rect = QRect(img_rect.left(), img_rect.bottom() - 21, img_rect.width(), 22)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(15, 23, 42, 195)))
            painter.drawRoundedRect(name_bar_rect, 4, 4)
            painter.setPen(QColor("#F8FAFC"))
            painter.setFont(font_tag)
            elided_img = fm_tag.elidedText(img_label_str, Qt.TextElideMode.ElideMiddle, name_bar_rect.width() - 10)
            painter.drawText(name_bar_rect.adjusted(5, 0, -5, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided_img)

            # 6. Preset badges row (Template / Motion / Mode)
            tags_y = img_rect.bottom() + 5
            has_custom_tpl = bool(seg.get("template_id"))
            has_custom_mot = bool(seg.get("motion_id"))
            has_custom_mode = bool(seg.get("mode_overridden"))

            if is_dark:
                tags = [
                    (f"📐{tpl_name}", "#172554" if has_custom_tpl else "#27272A", "#93C5FD" if has_custom_tpl else "#D4D4D8"),
                    (f"🎥{mot_name}", "#3B2F14" if has_custom_mot else "#27272A", "#FDE68A" if has_custom_mot else "#D4D4D8"),
                    (f"{mode_name}", "#143326" if has_custom_mode else "#27272A", "#6EE7B7" if has_custom_mode else "#D4D4D8"),
                ]
            else:
                tags = [
                    (f"📐{tpl_name}", "#DBEAFE" if has_custom_tpl else "#F1F5F9", "#1D4ED8" if has_custom_tpl else "#475569"),
                    (f"🎥{mot_name}", "#FEF3C7" if has_custom_mot else "#F1F5F9", "#B45309" if has_custom_mot else "#475569"),
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

        # Row 2A: Selection controls & Zoom slider
        sel_row = QHBoxLayout()
        sel_row.setSpacing(6)

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

        btn_sel_inv = QPushButton("🔄 反选")
        btn_sel_inv.setStyleSheet("QPushButton { background: #FFFFFF; color: #1E40AF; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #93C5FD; } QPushButton:hover { background: #DBEAFE; }")
        btn_sel_inv.clicked.connect(lambda: self.grid_viewport.invert_selection())
        sel_row.addWidget(btn_sel_inv)

        btn_sel_none = QPushButton("⏹️ 取消选择")
        btn_sel_none.setStyleSheet("QPushButton { background: #FFFFFF; color: #475569; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #CBD5E1; } QPushButton:hover { background: #F1F5F9; }")
        btn_sel_none.clicked.connect(lambda: self.grid_viewport.clear_selection())
        sel_row.addWidget(btn_sel_none)

        lbl_hint = QLabel("💡 支持：鼠标拖拽直接框选 · Ctrl+点击多选 · Shift+点击连选 · 按住 Ctrl+鼠标滚轮 缩放图片")
        lbl_hint.setStyleSheet("font-size: 12px; color: #1E3A8A; border: none;")
        sel_row.addWidget(lbl_hint)

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

        lbl_res_tip = QLabel("👆 先在下方多选断句图片，再点击下方任意「资源图」即可一键批量更换所选断句的图片！")
        lbl_res_tip.setStyleSheet("font-size: 12px; font-weight: bold; color: #0F766E; border: none;")
        res_header.addWidget(lbl_res_tip)

        self.chk_assign_end_frame = QCheckBox("🎬 更换为尾帧图片 (不勾选则更换首帧图片)")
        self.chk_assign_end_frame.setStyleSheet("font-size: 12px; font-weight: bold; color: #7C3AED;")
        res_header.addWidget(self.chk_assign_end_frame)

        res_header.addStretch()

        btn_add_res_img = QPushButton("➕ 添加本地图片到资源库")
        btn_add_res_img.setStyleSheet(
            "QPushButton { background: #10B981; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #059669; }"
        )
        btn_add_res_img.clicked.connect(self._on_add_local_images_to_resources)
        res_header.addWidget(btn_add_res_img)

        btn_clear_seg_img = QPushButton("🚫 清空所选断句图片")
        btn_clear_seg_img.setStyleSheet(
            "QPushButton { background: #EF4444; color: white; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #DC2626; }"
        )
        btn_clear_seg_img.clicked.connect(lambda: self._on_resource_card_clicked(""))
        res_header.addWidget(btn_clear_seg_img)

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
    def _bind_current_project(self, initial_selected_rows=None):
        if not self.project_model:
            return

        # 确保每个断句已解析默认关联的首帧图片
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

        # 2. 批量指定分句模板下拉框
        u_tpl_name = self.combo_unified_tpl.currentText() or "未选择"
        u_mot_name = self.combo_unified_mot.currentText() or "未选择"

        self.combo_batch_tpl.blockSignals(True)
        self.combo_batch_tpl.clear()
        self.combo_batch_tpl.addItem("📐 选择模板直接应用到已选...", None)
        self.combo_batch_tpl.addItem(f"-- 遵循统一模板 ({u_tpl_name}) --", "")
        if self.template_manager:
            for t in self.template_manager.templates:
                self.combo_batch_tpl.addItem(t["name"], t["id"])
        self.combo_batch_tpl.setCurrentIndex(0)
        self.combo_batch_tpl.blockSignals(False)

        # 3. 批量指定分句运镜下拉框
        self.combo_batch_mot.blockSignals(True)
        self.combo_batch_mot.clear()
        self.combo_batch_mot.addItem("🎥 选择运镜直接应用到已选...", None)
        self.combo_batch_mot.addItem(f"-- 遵循统一运镜 ({u_mot_name}) --", "")
        if self.template_manager:
            for m in self.template_manager.motions:
                self.combo_batch_mot.addItem(m["name"], m["id"])
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
            im_n = s.get("image_name") or ""
            if im_n:
                usage_map[im_n] = usage_map.get(im_n, 0) + 1

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
        rows = sorted(self.grid_viewport.selected_indices)
        if not rows:
            QMessageBox.information(
                self,
                "请先选择断句图片",
                "请先在下方网格中点击或拖拽框选需要更换图片的断句卡片，然后再点击上方的资源图！"
            )
            return
        if not self.project_model:
            return

        segs = self.project_model.spanish_segments
        assign_end = self.chk_assign_end_frame.isChecked()
        if assign_end and self.detail_widget and not getattr(self.detail_widget, "enable_end_frame", False):
            self.detail_widget.chk_enable_end_frame.setChecked(True)

        for r in rows:
            if 0 <= r < len(segs):
                if assign_end:
                    segs[r]["end_image_name"] = image_name
                    # 尾帧自动联动下一句首帧
                    if r + 1 < len(segs) and image_name:
                        segs[r + 1]["image_name"] = image_name
                else:
                    segs[r]["image_name"] = image_name

        self._save_and_sync_detail_widget(rows)
        self._populate_resource_images()
        self.grid_viewport.update()
        target_label = "尾帧图片" if assign_end else "首帧图片"
        disp = image_name if image_name else "无图片"
        self._flash_save_badge(f"✅ 已将 {len(rows)} 个断句的{target_label}批量更换为: {disp}")

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
            preview = "、".join(f"#{r + 1:02d}" for r in selected_rows[:12])
            if sel_cnt > 12:
                preview += f" 等共 {sel_cnt} 句"
            self.lbl_selection_info.setText(f"✅ 已选 {sel_cnt} / {total} 个断句 ({preview})")
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
        self.lbl_bottom_summary.setText(
            f"📊 当前任务：{self.project_model.project_id}  |  共 {len(segs)} 个断句  |  "
            f"任务资源图：{len(imgs)} 张  |  独立模板断句：{custom_tpl_cnt} 句  |  独立运镜断句：{custom_mot_cnt} 句"
        )
