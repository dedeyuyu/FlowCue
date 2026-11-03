# -*- coding: utf-8 -*-
"""分句表格（填充 / 编辑 / 增删 / 复制 / 切分 / 保存）及统一模板选择相关方法。

由 ProjectDetailWidget 通过多重继承组合使用，方法内的 self 即 ProjectDetailWidget 实例。"""
from views.project_detail.common import *  # noqa: F401,F403
from views.project_detail.common import logger  # noqa: F401


class SegmentsTableMixin:
    def populate_segments_table(self):
        """Fills QTableWidget with stored Spanish segments and generated prompts."""
        self.table_segments.blockSignals(True)
        self.table_segments.clearContents()
        
        if not self.project_model:
            self.table_segments.setRowCount(0)
            self.table_segments.blockSignals(False)
            return
            
        segments = self.project_model.spanish_segments
        self.table_segments.setUpdatesEnabled(False)
        self.table_segments.setRowCount(len(segments))
        self._img_list_cache = None
        
        for idx, seg in enumerate(segments):
            # 智能解析关联首帧图片素材（仅解析文件名，不读取/编码图片，避免界面卡顿）
            img_name, _, _ = self.resolve_segment_image_and_data(idx, seg, with_data=False, use_cache=True)
            if img_name:
                seg["image_name"] = img_name

            # 智能解析关联尾帧图片素材（若启用）
            if getattr(self, "enable_end_frame", False):
                end_img_name, _, _ = self.resolve_segment_end_image_and_data(idx, seg, with_data=False)
                if end_img_name:
                    seg["end_image_name"] = end_img_name

            # 0. Index & Icons (📷: 首帧图片, 🎬: 尾帧图片, ⚙️: 自定义模板/运镜)
            has_image = bool(seg.get("image_name"))
            has_end_image = bool(seg.get("end_image_name")) if getattr(self, "enable_end_frame", False) else False
            has_custom = bool(seg.get("template_id")) or bool(seg.get("motion_id"))
            idx_text = str(idx + 1)
            if has_image:
                idx_text += " 📷"
            if has_end_image:
                idx_text += " 🎬"
            if has_custom:
                idx_text += " ⚙️"
            self.table_segments.setItem(idx, 0, QTableWidgetItem(idx_text))
            self.table_segments.item(idx, 0).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            
            # 1. Spanish segment text (editable)
            text = TextProcessor.remove_punctuation(seg.get("text", ""))
            seg["text"] = text
            self.table_segments.setItem(idx, 1, QTableWidgetItem(text))
            
            # Calculate length and duration dynamically
            length = len(text)
            is_edge = (idx == 0 or idx == len(segments) - 1)
            
            # Determine duration label
            if self.config_manager:
                duration_label = self.config_manager.get_duration_label(length, is_edge=is_edge)
                duration_val = self.config_manager.get_duration_for_length(length, is_edge=is_edge)
            else:
                if length <= 40:
                    duration_label = "4s"
                    duration_val = 4
                elif length <= 90:
                    duration_label = "6s"
                    duration_val = 6
                elif length <= 130:
                    duration_label = "8s"
                    duration_val = 8
                elif length <= 170:
                    duration_label = "10s"
                    duration_val = 10
                else:
                    duration_label = "超时 (>10s)"
                    duration_val = 10
                    
            seg["duration"] = duration_val
                
            # 2. Length (read-only)
            self.table_segments.setItem(idx, 2, QTableWidgetItem(str(length)))
            self.table_segments.item(idx, 2).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            
            # 3. Duration (read-only)
            duration_item = QTableWidgetItem(duration_label)
            duration_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if "超时" in duration_label:
                duration_item.setForeground(Qt.GlobalColor.red)
            self.table_segments.setItem(idx, 3, duration_item)
            
            # 4. Generated final prompt (read-only, taking segment override or global fallback)
            tpl, motion = self.get_effective_template_and_motion(idx)
            template_content = tpl["content"] if tpl else "{spanish_text}"
            motion_content = motion["content"] if motion else ""
            
            final_prompt = template_content.replace("{spanish_text}", text)
            final_prompt = final_prompt.replace("{camera_motion}", motion_content)
            final_prompt = re.sub(r' +', ' ', final_prompt).strip()
            
            prompt_item = QTableWidgetItem(final_prompt)
            prompt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_segments.setItem(idx, 4, prompt_item)
            
            # 5. Single action button (Copy Prompt)
            # 「复制提示词」按钮由 TableButtonDelegate 绘制，这里只放一个占位单元格
            op_item = QTableWidgetItem("")
            op_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table_segments.setItem(idx, 5, op_item)
            
        # Apply colors for rows based on whether local video exists on disk
        if not hasattr(self, 'copied_rows'):
            self.copied_rows = set()
        self.copied_rows.clear()
            
        videos_dir = self.project_path / "downloads" / "videos" if self.project_path else Path("downloads/videos")
        existing_videos = set()
        try:
            if videos_dir.is_dir():
                with os.scandir(videos_dir) as it:
                    for entry in it:
                        try:
                            if entry.is_file() and entry.stat().st_size > 0:
                                existing_videos.add(entry.name.lower())
                        except OSError:
                            pass
        except OSError:
            pass
        for idx, seg in enumerate(segments):
            if f"{idx+1:02d}.mp4" in existing_videos:
                seg["copied"] = True
                seg["completed"] = True
                self.copied_rows.add(idx)
                self.change_row_color(idx, copied=True, persist=False)
            else:
                seg["copied"] = False
                seg["completed"] = False
                self.change_row_color(idx, copied=False, persist=False)
        self._img_list_cache = None
        # 整表刷新后只落盘一次（原先每行各保存一次，行数多时非常卡顿）
        try:
            self.project_model.save()
        except Exception:
            pass
            
        self.table_segments.setUpdatesEnabled(True)
        self.table_segments.blockSignals(False)
        self.filter_segments_table()

    def filter_segments_table(self, query=None):
        """Filters the segments table based on search query in segment text or final prompt."""
        if query is None:
            query = self.txt_search.text() if hasattr(self, 'txt_search') else ""
            
        query = str(query).strip().lower()
        
        for row in range(self.table_segments.rowCount()):
            if not query:
                self.table_segments.setRowHidden(row, False)
                continue
                
            # Column 1: Segment text
            text_item = self.table_segments.item(row, 1)
            text_content = text_item.text().lower() if text_item else ""
            
            # Column 4: Final prompt
            prompt_item = self.table_segments.item(row, 4)
            prompt_content = prompt_item.text().lower() if prompt_item else ""
            
            # Match if query appears in segment text or final prompt
            match = (query in text_content) or (query in prompt_content)
            self.table_segments.setRowHidden(row, not match)

    def on_cell_changed(self, row, column):
        """Saves edited segment text, updates character count, duration and prompt columns in the UI."""
        if column != 1:
            return
            
        text_item = self.table_segments.item(row, 1)
        raw_text = text_item.text().strip() if text_item else ""
        new_text = TextProcessor.remove_punctuation(raw_text)
        
        # Calculate length and duration
        length = len(new_text)
        total_rows = self.table_segments.rowCount()
        is_edge = (row == 0 or row == total_rows - 1)
        
        if self.config_manager:
            duration_label = self.config_manager.get_duration_label(length, is_edge=is_edge)
            duration_val = self.config_manager.get_duration_for_length(length, is_edge=is_edge)
        else:
            if length <= 40:
                duration_label = "4s"
                duration_val = 4
            elif length <= 90:
                duration_label = "6s"
                duration_val = 6
            elif length <= 130:
                duration_label = "8s"
                duration_val = 8
            elif length <= 170:
                duration_label = "10s"
                duration_val = 10
            else:
                duration_label = "超时 (>10s)"
                duration_val = 10
            
        self.table_segments.blockSignals(True)
        
        if new_text != raw_text:
            self.table_segments.setItem(row, 1, QTableWidgetItem(new_text))
            
        # 1. Update length cell
        self.table_segments.setItem(row, 2, QTableWidgetItem(str(length)))
        self.table_segments.item(row, 2).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # 2. Update duration cell
        dur_item = QTableWidgetItem(duration_label)
        dur_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        max_limit = self.config_manager.get_max_chars() if self.config_manager else 170
        if length > max_limit:
            dur_item.setForeground(Qt.GlobalColor.red)
        self.table_segments.setItem(row, 3, dur_item)
        
        # 3. Update generated final prompt cell
        tpl, motion = self.get_effective_template_and_motion(row)
        template_content = tpl["content"] if tpl else "{spanish_text}"
        motion_content = motion["content"] if motion else ""
        
        final_prompt = template_content.replace("{spanish_text}", new_text)
        final_prompt = final_prompt.replace("{camera_motion}", motion_content)
        final_prompt = re.sub(r' +', ' ', final_prompt).strip()
        
        prompt_item = QTableWidgetItem(final_prompt)
        prompt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table_segments.setItem(row, 4, prompt_item)
        
        self.table_segments.blockSignals(False)
        
        # 4. Update in-memory model and persist immediately
        if self.project_model and row < len(self.project_model.spanish_segments):
            self.project_model.spanish_segments[row]["text"] = new_text
            self.project_model.spanish_segments[row]["length"] = length
            self.project_model.spanish_segments[row]["duration"] = duration_val
            self.project_model.save()

    def add_segment_row(self):
        """Adds a blank row to the segments table."""
        self.table_segments.blockSignals(True)
        row_idx = self.table_segments.rowCount()
        self.table_segments.insertRow(row_idx)
        
        self.table_segments.setItem(row_idx, 0, QTableWidgetItem(str(row_idx + 1)))
        self.table_segments.item(row_idx, 0).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table_segments.setItem(row_idx, 1, QTableWidgetItem(""))
        self.table_segments.setItem(row_idx, 2, QTableWidgetItem("0"))
        self.table_segments.item(row_idx, 2).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table_segments.setItem(row_idx, 3, QTableWidgetItem("6s"))
        
        self.table_segments.setItem(row_idx, 4, QTableWidgetItem(""))
        self.table_segments.item(row_idx, 4).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        
        # Add copy button in Col 5
        # 「复制提示词」按钮由 TableButtonDelegate 绘制，这里只放一个占位单元格
        op_item = QTableWidgetItem("")
        op_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table_segments.setItem(row_idx, 5, op_item)
        
        self.table_segments.blockSignals(False)
        
        if self.project_model:
            single_img = self.get_project_single_image()
            self.project_model.spanish_segments.append({
                "text": "",
                "length": 0,
                "duration": 6,
                "image_name": single_img if single_img else "",
                "end_image_name": "",
                "mode": "VIDEO_FRAMES"
            })
        self._refresh_all_row_durations()

    def _refresh_all_row_durations(self):
        """Recalculates durations for all rows so first & last segment extra duration stays accurate after add/delete."""
        total_rows = self.table_segments.rowCount()
        if total_rows <= 0:
            return
        self.table_segments.blockSignals(True)
        for idx in range(total_rows):
            text_item = self.table_segments.item(idx, 1)
            text = text_item.text().strip() if text_item else ""
            length = len(text)
            is_edge = (idx == 0 or idx == total_rows - 1)
            if self.config_manager:
                duration_label = self.config_manager.get_duration_label(length, is_edge=is_edge)
                duration_val = self.config_manager.get_duration_for_length(length, is_edge=is_edge)
            else:
                duration_val = 4 if length <= 40 else (6 if length <= 90 else (8 if length <= 130 else 10))
                duration_label = f"{duration_val}s" if length <= 170 else "超时 (>10s)"
            dur_item = QTableWidgetItem(duration_label)
            dur_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if "超时" in duration_label:
                dur_item.setForeground(Qt.GlobalColor.red)
            self.table_segments.setItem(idx, 3, dur_item)
            if self.project_model and idx < len(self.project_model.spanish_segments):
                self.project_model.spanish_segments[idx]["duration"] = duration_val
        self.table_segments.blockSignals(False)



    def copy_segment_prompt(self, target_row=None):
        """Copies generated prompt from corresponding row to clipboard."""
        if target_row is None or isinstance(target_row, bool):
            target_row = self.table_segments.currentRow()
        if target_row is None or target_row < 0 or target_row >= self.table_segments.rowCount():
            return
        # Highlight this row programmatically and update property panel
        self.table_segments.selectRow(target_row)
        item = self.table_segments.item(target_row, 0)
        if item:
            self.table_segments.setCurrentItem(item)
        prompt_item = self.table_segments.item(target_row, 4)
        if prompt_item:
            prompt_text = prompt_item.text().strip()
            if prompt_text:
                QGuiApplication.clipboard().setText(prompt_text)
                QToolTip.showText(QCursor.pos(), "已复制完整提示词！", self)
                self.change_row_color(target_row, copied=True)

    def on_cell_double_clicked(self, row, column):
        """Handle double-clicks on the table segments."""
        if column == 3: # Double clicked on "秒数" (Duration) column
            self.change_row_color(row, copied=False)
            return
            
        if column == 4: # Double clicked on "生成的提示词" column
            prompt_item = self.table_segments.item(row, 4)
            if not prompt_item:
                return
                
            prompt_text = prompt_item.text().strip()
            if not prompt_text:
                return
                
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
            dialog = QDialog(self)
            dialog.setWindowTitle(f"完整提示词 (第 {row + 1} 句)")
            dialog.resize(600, 400)
            
            layout = QVBoxLayout(dialog)
            
            text_edit = QTextEdit()
            text_edit.setPlainText(prompt_text)
            text_edit.setReadOnly(True)
            layout.addWidget(text_edit)
            
            btn_layout = QHBoxLayout()
            btn_layout.addStretch()
            
            btn_copy = QPushButton("📋 复制全部提示词")
            btn_copy.clicked.connect(lambda: self.copy_text_to_clipboard(prompt_text, dialog, row))
            btn_layout.addWidget(btn_copy)
            
            btn_close = QPushButton("关闭")
            btn_close.clicked.connect(dialog.accept)
            btn_layout.addWidget(btn_close)
            
            layout.addLayout(btn_layout)
            
            dialog.setStyleSheet(self.styleSheet())
            dialog.exec()

    def copy_text_to_clipboard(self, text, dialog, row):
        """Utility method to copy text and show tooltip inside dialog context."""
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(text)
        QToolTip.showText(QCursor.pos(), "已复制完整提示词！", dialog)
        self.change_row_color(row, copied=True)

    def change_row_color(self, row, copied=True, persist=True):
        """Change the background color of a specific row to indicate status."""
        from PyQt6.QtGui import QColor
        from services.theme_manager import ThemeManager
        if not hasattr(self, 'copied_rows'):
            self.copied_rows = set()
            
        if copied:
            bg_color, text_color = ThemeManager.get_copied_row_colors()
            self.copied_rows.add(row)
        else:
            bg_color = QColor()
            text_color = QColor()
            self.copied_rows.discard(row)

        if self.project_model and row < len(self.project_model.spanish_segments):
            self.project_model.spanish_segments[row]["copied"] = copied
            if persist:
                self.project_model.save()

        for col in range(5):
            item = self.table_segments.item(row, col)
            if item:
                if copied:
                    item.setBackground(bg_color)
                    item.setForeground(text_color)
                else:
                    item.setData(Qt.ItemDataRole.BackgroundRole, None)
                    item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def reset_all_segments_completed_state(self):
        """Resets all segments in the current project from completed/green back to uncompleted."""
        if hasattr(self, 'copied_rows'):
            self.copied_rows.clear()
        if hasattr(self, 'dispatched_indices'):
            self.dispatched_indices.clear()

        if self.project_model and self.project_model.spanish_segments:
            for seg in self.project_model.spanish_segments:
                seg["copied"] = False
                seg["completed"] = False
            self.project_model.save()

        self.populate_segments_table()
        QMessageBox.information(self, "重置完成", "✅ 已成功重置所有分句为【未完成状态】！\n\n再次点击分发时，所有浏览器将全量并发重新开刷。")

    def delete_selected_segment(self):
        """Deletes selected row in segments table."""
        selected_rows = self.table_segments.selectedRanges()
        if not selected_rows:
            return
            
        # Delete from bottom to top to avoid offset errors
        rows_to_delete = []
        for r in selected_rows:
            for i in range(r.topRow(), r.bottomRow() + 1):
                rows_to_delete.append(i)
        
        rows_to_delete = sorted(list(set(rows_to_delete)), reverse=True)
        for r in rows_to_delete:
            self.table_segments.removeRow(r)
            if self.project_model and r < len(self.project_model.spanish_segments):
                self.project_model.spanish_segments.pop(r)
            if hasattr(self, 'copied_rows'):
                # Remove this index, and shift all indices greater than r down by 1
                new_copied = set()
                for idx in self.copied_rows:
                    if idx < r:
                        new_copied.add(idx)
                    elif idx > r:
                        new_copied.add(idx - 1)
                self.copied_rows = new_copied
            
        # Recalculate IDs
        self.table_segments.blockSignals(True)
        for idx in range(self.table_segments.rowCount()):
            self.refresh_table_row_index_label(idx)
        self.table_segments.blockSignals(False)
        self._refresh_all_row_durations()

    def run_segmentation(self):
        """Cleans and segments the Spanish text."""
        if not self.project_model:
            return
            
        text = self.txt_spanish.toPlainText()
        if not text.strip():
            QMessageBox.warning(self, "提示", "西班牙语文案为空，请先输入。")
            return
            
        # Ensure latest config rules (especially min_segment_chars) are loaded
        if not self.config_manager:
            main_win = self.window()
            if hasattr(main_win, "config_manager"):
                self.config_manager = main_win.config_manager
        if self.config_manager:
            self.config_manager.load()

        # Perform segmentation while preserving existing image/mode/template bindings by row index
        old_segments = self.project_model.spanish_segments or []
        segments = TextProcessor.segment_spanish_text(text, self.config_manager)
        preserve_keys = ("image_name", "end_image_name", "mode", "mode_overridden", "template_id", "motion_id")
        for idx, new_seg in enumerate(segments):
            if idx < len(old_segments):
                old_seg = old_segments[idx]
                for k in preserve_keys:
                    if k in old_seg:
                        new_seg[k] = old_seg[k]
        self.project_model.spanish_segments = segments
        self.populate_segments_table()
        self.project_model.save()
        QMessageBox.information(self, "成功", "已完成西文的表情清理与智能切分！")

    def save_project_data(self):
        """Saves text changes and segments back to metadata.json."""
        if not self.project_model:
            return
            
        # 1. Update basic texts
        self.project_model.chinese_text = self.txt_chinese.toPlainText()
        self.project_model.spanish_text = self.txt_spanish.toPlainText()
        self.project_model.google_drive_url = self.txt_gdrive_url.toPlainText().strip()
        
        # 2. Update segments from table in-place to preserve other properties (image_name, mode)
        for row in range(self.table_segments.rowCount()):
            text_item = self.table_segments.item(row, 1)
            duration_item = self.table_segments.item(row, 3)
            
            raw_text = text_item.text().strip() if text_item else ""
            text = TextProcessor.remove_punctuation(raw_text)
            dur_str = duration_item.text().strip().replace("s", "") if duration_item else "6"
            try:
                duration = int(dur_str)
            except ValueError:
                duration = 6
                
            if row < len(self.project_model.spanish_segments):
                self.project_model.spanish_segments[row]["text"] = text
                self.project_model.spanish_segments[row]["length"] = len(text)
                self.project_model.spanish_segments[row]["duration"] = duration
            else:
                self.project_model.spanish_segments.append({
                    "text": text,
                    "length": len(text),
                    "duration": duration,
                    "image_name": "",
                    "end_image_name": "",
                    "mode": "VIDEO_FRAMES"
                })
                
        # Truncate model segments to match table row count if needed
        if len(self.project_model.spanish_segments) > self.table_segments.rowCount():
            self.project_model.spanish_segments = self.project_model.spanish_segments[:self.table_segments.rowCount()]
        
        # 3. Save to disk
        if self.project_model.save():
            QMessageBox.information(self, "成功", "工程文案与配置保存成功！")
        else:
            QMessageBox.critical(self, "错误", "工程保存失败，请检查写入权限。")

    def refresh_template_comboboxes(self):
        """Loads prompt templates and motions lists into dropdown selectors."""
        if not self.template_manager:
            return
            
        self.combo_templates.blockSignals(True)
        self.combo_motions.blockSignals(True)
        
        self.combo_templates.clear()
        self.combo_motions.clear()
        
        self.combo_templates.addItem("-- 请选择提示词模板 --", "")
        self.combo_motions.addItem("-- 请选择运镜预设 --", "")
        
        for t in self.template_manager.templates:
            self.combo_templates.addItem(t["name"], t["id"])
        for m in self.template_manager.motions:
            self.combo_motions.addItem(m["name"], m["id"])
            
        if self.project_model:
            tpl_idx = self.combo_templates.findData(self.project_model.selected_template_id)
            if tpl_idx >= 0:
                self.combo_templates.setCurrentIndex(tpl_idx)
            else:
                self.combo_templates.setCurrentIndex(0)
                
            motion_idx = self.combo_motions.findData(self.project_model.selected_motion_id)
            if motion_idx >= 0:
                self.combo_motions.setCurrentIndex(motion_idx)
            else:
                self.combo_motions.setCurrentIndex(0)
                
        self.combo_templates.blockSignals(False)
        self.combo_motions.blockSignals(False)
        
        self.populate_segments_table()

    def on_template_changed(self):
        if not self.project_model:
            return
        tpl_id = self.combo_templates.currentData()
        self.project_model.selected_template_id = tpl_id if tpl_id else ""
        self.project_model.save()
        self.refresh_prop_template_motion_combos()
        self.populate_segments_table()

    def on_motion_changed(self):
        if not self.project_model:
            return
        motion_id = self.combo_motions.currentData()
        self.project_model.selected_motion_id = motion_id if motion_id else ""
        self.project_model.save()
        self.refresh_prop_template_motion_combos()
        self.populate_segments_table()
