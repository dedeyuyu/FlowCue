# -*- coding: utf-8 -*-
"""素材管理页（图片下载 / 预览 / 重命名 / 翻转 / 删除）相关方法。

由 ProjectDetailWidget 通过多重继承组合使用，方法内的 self 即 ProjectDetailWidget 实例。"""
from views.project_detail.common import *  # noqa: F401,F403
from views.project_detail.common import logger  # noqa: F401


class MediaTabMixin:
    def init_media_tab(self):
        """Initializes the media management tab."""
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        
        # 1. Google Drive URL Downloader block
        dl_layout = QHBoxLayout()
        dl_layout.addWidget(QLabel("谷歌云盘链接 (Google Drive URL):"))
        
        self.txt_gdrive_url = QTextEdit()
        self.txt_gdrive_url.setMaximumHeight(60)
        self.txt_gdrive_url.setPlaceholderText("可包含多个谷歌云盘链接，每行一个...")
        dl_layout.addWidget(self.txt_gdrive_url)
        
        self.btn_download = QPushButton("📥 下载全部资源")
        self.btn_download.clicked.connect(self.start_download)
        dl_layout.addWidget(self.btn_download)
        
        layout.addLayout(dl_layout)
        
        # 2. Download status
        self.lbl_download_status = QLabel("下载状态: 未开始")
        self.lbl_download_status.setStyleSheet("color: #795548; font-style: italic;")
        layout.addWidget(self.lbl_download_status)
        
        # 3. Split-screen List and Image Preview
        splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # Left side: List
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("下载的本地素材列表 (双击打开 / 可按住 Ctrl 或 Shift 多选):"))
        
        self.list_media = QListWidget()
        self.list_media.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_media.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_media.customContextMenuRequested.connect(self.show_media_context_menu)
        self.list_media.doubleClicked.connect(self.open_media_file)
        self.list_media.currentItemChanged.connect(self.on_media_selection_changed)
        left_layout.addWidget(self.list_media)
        
        # Rename, Flip & Delete buttons
        media_btn_layout = QHBoxLayout()
        media_btn_layout.setSpacing(6)
        
        self.btn_flip_media = QPushButton("↔️ 左右翻转")
        self.btn_flip_media.setToolTip("将选中的图片进行左右水平翻转，生成新图替换并删除原图（保留原文件名，支持多选）")
        self.btn_flip_media.setStyleSheet("padding: 4px 10px; font-size: 12px; background-color: #0D9488; color: white; font-weight: bold;")
        self.btn_flip_media.clicked.connect(self.flip_selected_media_files)
        media_btn_layout.addWidget(self.btn_flip_media)
        
        self.btn_rename_media = QPushButton("✏️ 单个命名")
        self.btn_rename_media.setToolTip("手动重命名选中的图片文件")
        self.btn_rename_media.setStyleSheet("padding: 4px 10px; font-size: 12px;")
        self.btn_rename_media.clicked.connect(self.rename_media_file)
        media_btn_layout.addWidget(self.btn_rename_media)
        
        self.btn_auto_rename_media = QPushButton("🔄 一键命名")
        self.btn_auto_rename_media.setToolTip("为本项目里的图片自动编号（紧接全局最大序号）")
        self.btn_auto_rename_media.setStyleSheet("padding: 4px 10px; font-size: 12px; background-color: #6366F1; color: white; font-weight: bold;")
        self.btn_auto_rename_media.clicked.connect(self.auto_rename_project_images)
        media_btn_layout.addWidget(self.btn_auto_rename_media)
        
        self.btn_global_rename_media = QPushButton("🌐 全局命名")
        self.btn_global_rename_media.setToolTip("将所有项目视为一个整体，从 1.jpg 开始全部重新编号")
        self.btn_global_rename_media.setStyleSheet("padding: 4px 10px; font-size: 12px; background-color: #8B5CF6; color: white; font-weight: bold;")
        self.btn_global_rename_media.clicked.connect(self.global_rename_all_images)
        media_btn_layout.addWidget(self.btn_global_rename_media)
        
        self.btn_delete_media = QPushButton("🗑️ 删除")
        self.btn_delete_media.setToolTip("删除选中的图片文件（会同步清除分句中对该文件的引用）")
        self.btn_delete_media.setStyleSheet("padding: 4px 10px; font-size: 12px; color: #D32F2F;")
        self.btn_delete_media.clicked.connect(self.delete_media_file)
        media_btn_layout.addWidget(self.btn_delete_media)
        
        media_btn_layout.addStretch()
        left_layout.addLayout(media_btn_layout)
        
        left_widget.setLayout(left_layout)
        splitter.addWidget(left_widget)
        
        # Right side: Preview
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        preview_header_layout = QHBoxLayout()
        preview_header_layout.addWidget(QLabel("图片素材预览 (Preview):"))
        preview_header_layout.addStretch()
        self.btn_flip_preview = QPushButton("↔️ 左右翻转当前图片")
        self.btn_flip_preview.setToolTip("将当前预览的图片左右翻转，生成新图替换并删除原图（保留原文件名）")
        self.btn_flip_preview.setStyleSheet("padding: 3px 10px; font-size: 12px; background-color: #0D9488; color: white; font-weight: bold;")
        self.btn_flip_preview.clicked.connect(self.flip_selected_media_files)
        preview_header_layout.addWidget(self.btn_flip_preview)
        right_layout.addLayout(preview_header_layout)
        
        self.lbl_preview = QLabel("选择左侧素材以预览...")
        self.lbl_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_preview.setStyleSheet("""
            QLabel {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #8D6E63;
                font-weight: normal;
            }
        """)
        self.lbl_preview.setMinimumWidth(300)
        right_layout.addWidget(self.lbl_preview, stretch=1)
        
        right_widget.setLayout(right_layout)
        splitter.addWidget(right_widget)
        
        splitter.setSizes([350, 450])
        layout.addWidget(splitter, stretch=1)
        
        tab_widget.setLayout(layout)
        self.tabs.addTab(tab_widget, "📁 资源下载与管理")

    def open_project_folder(self):
        """Opens project folder in system file explorer."""
        if self.project_path and self.project_path.exists():
            QDesktopServices.openUrl(QUrl(self.project_path.as_uri()))

    def start_download(self):
        """Starts background download of Google Drive link by delegating to MainWindow."""
        url = self.txt_gdrive_url.toPlainText().strip()
        if not url:
            QMessageBox.warning(self, "错误", "谷歌云盘链接为空，无法下载。")
            return
            
        main_win = self.window()
        if hasattr(main_win, "active_downloads") and self.project_model.project_id in main_win.active_downloads:
            QMessageBox.warning(self, "提示", "该项目的下载任务已在后台运行中，请等待完成。")
            return
            
        if hasattr(main_win, "start_background_download"):
            self.btn_download.setEnabled(False)
            self.lbl_download_status.setText("下载状态: 初始化中...")
            main_win.start_background_download(self.project_model.project_id, url, self.project_path)
        else:
            # Fallback if window is not initialized
            downloads_dir = self.project_path / "downloads"
            self.btn_download.setEnabled(False)
            self.lbl_download_status.setText("下载状态: 初始化中...")
            if hasattr(self, "download_thread") and self.download_thread:
                try:
                    if self.download_thread.isRunning():
                        self.download_thread.stop()
                except Exception:
                    pass
                self.download_thread = None
            self.download_thread = DownloadThread(url, downloads_dir)
            self.download_thread.status_signal.connect(self.on_download_status_updated)
            self.download_thread.finished_signal.connect(self.on_download_finished)
            self.download_thread.finished_signal.connect(self.download_thread.deleteLater)
            self.download_thread.start()

    def on_download_status_updated(self, msg):
        self.lbl_download_status.setText(f"下载状态: {msg}")

    def on_download_finished(self, success, msg):
        self.btn_download.setEnabled(True)
        if success:
            self.lbl_download_status.setText("下载状态: 下载完成！")
            QMessageBox.information(self, "下载完成", msg)
        else:
            self.lbl_download_status.setText(f"下载状态: 下载失败 - {msg}")
            QMessageBox.critical(self, "下载失败", msg)
            
        # Refresh local files list
        self.refresh_media_list()
        
        # Update metadata.json list
        if self.project_model:
            self.project_model.update_media_files()
            if success:
                self.populate_segments_table()

    def refresh_media_list(self):
        """Populates list_media with files inside project_dir/downloads."""
        self.list_media.clear()
        if not self.project_path:
            return
            
        downloads_dir = self.project_path / "downloads"
        if downloads_dir.exists():
            for item in downloads_dir.iterdir():
                if item.is_file():
                    # Display filename and file size in KB
                    size_kb = item.stat().st_size / 1024
                    list_item = QListWidgetItem(f"{item.name} ({size_kb:.1f} KB)")
                    list_item.setData(Qt.ItemDataRole.UserRole, item.name)
                    self.list_media.addItem(list_item)
                    
        # Refresh combo_prop_image dropdown in property panel
        if hasattr(self, "combo_prop_image"):
            self.refresh_prop_image_combo_items()

    def open_media_file(self, qmodelindex):
        """Double click handler to open the media file with default system player/viewer."""
        current_item = self.list_media.currentItem()
        if not current_item:
            return
        filename = current_item.data(Qt.ItemDataRole.UserRole)
        if not filename:
            return
        file_path = self.project_path / "downloads" / filename
        
        if file_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(file_path.resolve())))

    def on_media_selection_changed(self, current, previous):
        """Displays a preview of the selected image on the right side."""
        if not current:
            self.lbl_preview.clear()
            self.lbl_preview.setText("选择左侧素材以预览...")
            return
            
        filename = current.data(Qt.ItemDataRole.UserRole)
        if not filename:
            self.lbl_preview.clear()
            self.lbl_preview.setText("无有效文件名")
            return
            
        file_path = self.project_path / "downloads" / filename
        
        if file_path.exists():
            pixmap = QPixmap()
            # 1. Use Pillow to load image (handles JPEG/PNG/WEBP/GIF with 100% reliability, bypassing Qt C++ plugins)
            try:
                from PIL import Image
                from PyQt6.QtGui import QImage
                
                with Image.open(file_path) as pil_img:
                    # Convert to RGBA format for safe rendering in Qt
                    pil_img_rgba = pil_img.convert("RGBA")
                    width, height = pil_img_rgba.size
                    
                    # Convert PIL image bytes directly to QImage
                    raw_data = pil_img_rgba.tobytes("raw", "RGBA")
                    # QImage requires a reference to the bytes data to stay alive, or we copy it using .copy()
                    qimg = QImage(raw_data, width, height, QImage.Format.Format_RGBA8888).copy()
                    
                    pixmap = QPixmap.fromImage(qimg)
            except Exception as e:
                print(f"Pillow load failed: {e}. Trying fallback direct loading...")
                # 2. Fallback to direct loading
                try:
                    with open(file_path, "rb") as f:
                        img_data = f.read()
                    pixmap = QPixmap()
                    pixmap.loadFromData(img_data)
                except Exception as fallback_err:
                    print(f"Fallback direct loading failed: {fallback_err}")
                    pixmap = QPixmap()
                
            if not pixmap.isNull():
                # Prevent negative or zero scaling size
                w = max(100, self.lbl_preview.width() - 12)
                h = max(100, self.lbl_preview.height() - 12)
                
                # Scale the image to fit the label, keeping aspect ratio
                scaled_pixmap = pixmap.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.lbl_preview.setPixmap(scaled_pixmap)
            else:
                self.lbl_preview.clear()
                self.lbl_preview.setText("无法预览此文件格式")
        else:
            self.lbl_preview.clear()
            self.lbl_preview.setText("文件不存在")

    def show_media_context_menu(self, pos):
        """Right-click context menu on list_media."""
        item = self.list_media.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        act_flip = menu.addAction("↔️ 左右翻转选中图片（替换并删除原图）")
        act_rename = menu.addAction("✏️ 单个命名")
        act_delete = menu.addAction("🗑️ 删除")
        chosen = menu.exec(self.list_media.viewport().mapToGlobal(pos))
        if chosen == act_flip:
            self.flip_selected_media_files()
        elif chosen == act_rename:
            self.rename_media_file()
        elif chosen == act_delete:
            self.delete_media_file()

    def flip_selected_media_files(self):
        """
        将资源管理中选中的图片进行左右水平翻转：
        生成翻转后的新图片替换原来的老图片，继承原图片名称，并删除原图片文件。
        """
        if not self.project_path:
            return

        selected_items = self.list_media.selectedItems()
        if not selected_items:
            cur = self.list_media.currentItem()
            if cur:
                selected_items = [cur]

        if not selected_items:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择要翻转的图片文件（可按住 Ctrl 或 Shift 多选）。")
            return

        selected_names = []
        for it in selected_items:
            fn = it.data(Qt.ItemDataRole.UserRole)
            if fn and fn not in selected_names:
                selected_names.append(fn)

        if not selected_names:
            return

        current_item = self.list_media.currentItem()
        current_name = current_item.data(Qt.ItemDataRole.UserRole) if current_item else selected_names[0]

        # 先释放预览可能占用的引用
        self.lbl_preview.clear()

        flipped_ok = []
        flipped_err = []
        downloads_dir = self.project_path / "downloads"

        for fn in selected_names:
            fp = downloads_dir / fn
            try:
                flip_image_horizontally_replace(fp)
                flipped_ok.append(fn)
            except Exception as e:
                flipped_err.append(f"{fn}: {e}")

        # 更新列表项显示的大小并保持选中状态
        for i in range(self.list_media.count()):
            it = self.list_media.item(i)
            fn = it.data(Qt.ItemDataRole.UserRole)
            if fn in flipped_ok:
                fp = downloads_dir / fn
                if fp.exists():
                    size_kb = fp.stat().st_size / 1024
                    it.setText(f"{fp.name} ({size_kb:.1f} KB)")

        # 刷新右侧大图预览
        self.on_media_selection_changed(self.list_media.currentItem(), None)

        # 刷新工作台属性面板中的下拉框缩略图与当前首/尾帧预览
        if hasattr(self, "combo_prop_image"):
            self.refresh_prop_image_combo_items()
            cur_prop_img = self.combo_prop_image.currentData()
            if cur_prop_img in flipped_ok:
                self.update_prop_image_preview(cur_prop_img)
        if hasattr(self, "combo_prop_end_image"):
            cur_prop_end_img = self.combo_prop_end_image.currentData()
            if cur_prop_end_img in flipped_ok:
                self.update_prop_end_image_preview(cur_prop_end_img)

        if flipped_ok:
            names_preview = "、".join(flipped_ok[:5]) + ("..." if len(flipped_ok) > 5 else "")
            self.lbl_download_status.setText(f"状态: ✅ 已左右翻转并替换原图 ({len(flipped_ok)} 张): {names_preview}")

        if flipped_err:
            QMessageBox.warning(
                self, "部分翻转失败",
                f"成功翻转 {len(flipped_ok)} 张，失败 {len(flipped_err)} 张：\n\n" + "\n".join(flipped_err[:10])
            )
        elif len(flipped_ok) > 1:
            QMessageBox.information(
                self, "批量翻转完成",
                f"已成功将选中的 {len(flipped_ok)} 张图片左右翻转！\n\n新图片已替换并删除原图（保留原文件名）。"
            )

    def rename_media_file(self):
        """Renames the selected media file and updates all segment references."""
        current_item = self.list_media.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择要重命名的文件。")
            return
        
        old_name = current_item.data(Qt.ItemDataRole.UserRole)
        if not old_name:
            return
        
        old_path = self.project_path / "downloads" / old_name
        if not old_path.exists():
            QMessageBox.warning(self, "提示", f"文件不存在: {old_name}")
            return
        
        # Get the file extension
        old_suffix = old_path.suffix
        old_stem = old_path.stem
        
        # Ask user for new name (without extension)
        new_stem, ok = QInputDialog.getText(
            self, "重命名文件", 
            f"当前文件名: {old_name}\n\n请输入新文件名（不含扩展名）:",
            QLineEdit.EchoMode.Normal, old_stem
        )
        
        if not ok or not new_stem.strip():
            return
        
        new_stem = new_stem.strip()
        # Sanitize: remove invalid filename characters
        invalid_chars = '<>:"/\\|?*'
        for ch in invalid_chars:
            new_stem = new_stem.replace(ch, '_')
        
        new_name = new_stem + old_suffix
        new_path = self.project_path / "downloads" / new_name
        
        if new_name == old_name:
            return  # No change
        
        if new_path.exists():
            QMessageBox.warning(self, "重命名失败", f"目标文件名已存在: {new_name}\n请使用其他名称。")
            return
        
        try:
            old_path.rename(new_path)
        except Exception as e:
            QMessageBox.critical(self, "重命名失败", f"无法重命名文件:\n{e}")
            return
        
        # Update all segment references (image_name, end_image_name)
        updated_count = 0
        if self.project_model and self.project_model.spanish_segments:
            for seg in self.project_model.spanish_segments:
                if seg.get("image_name") == old_name:
                    seg["image_name"] = new_name
                    updated_count += 1
                if seg.get("end_image_name") == old_name:
                    seg["end_image_name"] = new_name
                    updated_count += 1
            # Save updated metadata
            self.project_model.save()
        
        # Refresh UI
        self.refresh_media_list()
        self.populate_segments_table()
        
        msg = f"文件已重命名: {old_name} → {new_name}"
        if updated_count > 0:
            msg += f"\n\n同时更新了 {updated_count} 处分句素材关联引用。"
        QMessageBox.information(self, "重命名成功", msg)

    def auto_rename_project_images(self):
        """Automatically rename all images in the project based on the rule."""
        if not self.project_model:
            return
            
        reply = QMessageBox.question(
            self, "确认一键重命名",
            "是否要为本项目里的图片进行自动编号？\n\n(将紧接全局已有的最大序号往后命名)",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                renamed_count = self.project_model.rename_images()
                self.project_model.update_media_files()
                self.refresh_media_list()
                self.populate_segments_table()
                QMessageBox.information(self, "完成", f"重命名完成，共重命名了 {renamed_count} 张图片！")
            except Exception as e:
                QMessageBox.critical(self, "错误", f"重命名失败: {e}")

    def global_rename_all_images(self):
        """Triggers the global batch rename for all projects."""
        main_win = self.window()
        if hasattr(main_win, "batch_rename_all_images"):
            main_win.batch_rename_all_images()
        else:
            QMessageBox.warning(self, "提示", "主窗口未提供该功能。")

    def delete_media_file(self):
        """Deletes the selected media file and clears all segment references to it."""
        current_item = self.list_media.currentItem()
        if not current_item:
            QMessageBox.warning(self, "提示", "请先在左侧列表中选择要删除的文件。")
            return
        
        filename = current_item.data(Qt.ItemDataRole.UserRole)
        if not filename:
            return
        
        file_path = self.project_path / "downloads" / filename
        if not file_path.exists():
            QMessageBox.warning(self, "提示", f"文件不存在: {filename}")
            self.refresh_media_list()
            return
        
        # Check how many segments reference this file
        ref_count = 0
        if self.project_model and self.project_model.spanish_segments:
            for seg in self.project_model.spanish_segments:
                if seg.get("image_name") == filename:
                    ref_count += 1
                if seg.get("end_image_name") == filename:
                    ref_count += 1
        
        # Confirmation dialog
        ref_warning = ""
        if ref_count > 0:
            ref_warning = f"\n\n⚠️ 注意: 有 {ref_count} 处分句正在引用此文件作为素材，删除后将自动清除这些关联。"
        
        size_kb = file_path.stat().st_size / 1024
        res = QMessageBox.question(
            self, "确认删除",
            f"确定要删除以下文件吗？\n\n"
            f"文件名: {filename}\n"
            f"文件大小: {size_kb:.1f} KB"
            f"{ref_warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if res != QMessageBox.StandardButton.Yes:
            return
        
        try:
            file_path.unlink()
        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"无法删除文件:\n{e}")
            return
        
        # Clear all segment references to this file
        cleared_count = 0
        if self.project_model and self.project_model.spanish_segments:
            for seg in self.project_model.spanish_segments:
                if seg.get("image_name") == filename:
                    seg["image_name"] = ""
                    cleared_count += 1
                if seg.get("end_image_name") == filename:
                    seg["end_image_name"] = ""
                    cleared_count += 1
            # Save updated metadata
            self.project_model.save()
        
        # Refresh UI
        self.lbl_preview.clear()
        self.lbl_preview.setText("选择左侧素材以预览...")
        self.refresh_media_list()
        self.populate_segments_table()
        
        msg = f"文件已删除: {filename}"
        if cleared_count > 0:
            msg += f"\n已清除 {cleared_count} 处分句素材关联引用。"
        QMessageBox.information(self, "删除成功", msg)
