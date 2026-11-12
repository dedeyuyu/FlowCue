# -*- coding: utf-8 -*-
"""批量导出 / 多开分发对话框。"""
from views.project_detail.common import *  # noqa: F401,F403
from views.project_detail.common import logger  # noqa: F401


class BatchExportDialog(QDialog):
    def __init__(self, parent, batches, config_manager=None, skipped_count=0):
        super().__init__(parent)
        self.project_widget = parent if hasattr(parent, "start_auto_polling_dispatcher") else None
        if self.project_widget:
            self.project_widget.active_batch_dialog = self

        self.cm = config_manager
        self.skipped_count = skipped_count
        max_pts = self.cm.max_batch_points if self.cm else 50
        self.setWindowTitle(f"分批生成与多浏览器调度 (最高{max_pts}积分/批)")
        self.resize(780, 580)
        self.batches = batches  # List of lists of dicts
        self.copied_batches = set()
        self.init_ui()
        
    def closeEvent(self, event):
        if self.project_widget:
            self.project_widget.active_batch_dialog = None
        super().closeEvent(event)

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(12)
        
        # Summary Label
        total_segments = sum(len(b) for b in self.batches)
        total_points = sum(self.get_batch_points(b) for b in self.batches)
        total_end_frames = sum(sum(1 for t in b if t.get("end_image_name")) for b in self.batches)
        max_pts = self.cm.max_batch_points if self.cm else 50
        
        default_mode_code = getattr(self.cm, "default_generation_mode", "VIDEO_FRAMES") if self.cm else "VIDEO_FRAMES"
        default_mode_label = "素材模式 (Ingredients)" if default_mode_code == "VIDEO_REFERENCES" else "帧模式 (First Frame)"
        default_aspect = getattr(self.cm, "default_aspect_ratio", "9:16") if self.cm else "9:16"
        default_model_code = getattr(self.cm, "default_video_model", "omni_1_1_flash") if self.cm else "omni_1_1_flash"
        model_map = {
            "omni_1_1_flash": "Omni 1.1 Flash",
            "veo_3_1_lite": "Veo 3.1 - Lite",
            "veo_3_1_fast": "Veo 3.1 - Fast",
            "veo_3_1_quality": "Veo 3.1 - Quality",
            "veo_3_1_lite_low_priority": "Veo 3.1 - Lite [Lower Priority]"
        }
        default_model_label = model_map.get(default_model_code, default_model_code)
        task_interval = getattr(self.cm, "task_interval", 5) if self.cm else 5
        
        skipped_text = f" <span style='color: #10B981;'>(已自动排除 {self.skipped_count} 个已生成的变绿片段)</span>" if self.skipped_count > 0 else ""
        end_stat_text = f" | 🎬 包含 <b>{total_end_frames}</b> 个配置尾帧的分句" if total_end_frames > 0 else ""

        if default_aspect == "16:9":
            lbl_aspect_warn = QLabel(
                "🚨 【横屏尺寸提醒】当前默认画面尺寸为 16:9（横屏）！请确认本次导出任务确实需要生成 16:9 横屏视频。"
            )
            lbl_aspect_warn.setWordWrap(True)
            lbl_aspect_warn.setStyleSheet("""
                QLabel {
                    background-color: #FEE2E2;
                    color: #DC2626;
                    border: 2px solid #DC2626;
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 13px;
                    font-weight: bold;
                }
            """)
            layout.addWidget(lbl_aspect_warn)
        
        lbl_summary = QLabel(
            f"📊 <b>统计信息</b>：共 <b>{total_segments}</b> 个待生成视频片段{skipped_text}{end_stat_text}，"
            f"总需 <b>{total_points}</b> 积分。<br/>"
            f"每批次上限为 <b>{max_pts}</b> 积分，已拆为 <b>{len(self.batches)}</b> 个批次。<br/>"
            f"<span style='color: #0284C7;'>⚙️ <b>当前生成规则</b>：模式=<b>{default_mode_label}</b> | 尺寸=<b>{default_aspect}</b> | 模型=<b>{default_model_label}</b> | 任务间隔=<b>{task_interval}秒</b></span>"
        )
        lbl_summary.setStyleSheet("font-size: 13px; color: #5D4037;")
        layout.addWidget(lbl_summary)

        # Quick actions bar for plugin table integration
        quick_bar = QHBoxLayout()
        quick_bar.setSpacing(8)
        
        lbl_quick_hint = QLabel("💡 快捷导出：")
        lbl_quick_hint.setStyleSheet("font-size: 12px; color: #78350F; font-weight: bold;")
        quick_bar.addWidget(lbl_quick_hint)

        btn_copy_all_vids = QPushButton(f"🎬 复制全部任务 JSON (Vids 无积分限制 · 共 {total_segments} 条)")
        btn_copy_all_vids.setToolTip(
            f"Google Vids 没有 50 积分限制！\n"
            f"点击一键复制全部 {total_segments} 条待生成分镜的完整 JSON（自动保持原始时长不降级）。\n"
            "复制后切换到 Google Vids 页面点击悬浮胶囊的【🎬】按钮即可自动逐个上传图片、生成并下载视频！"
        )
        btn_copy_all_vids.setStyleSheet("""
            QPushButton {
                background-color: #2563EB;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #1D4ED8;
            }
        """)
        btn_copy_all_vids.clicked.connect(lambda: self.copy_all_vids_json(btn_copy_all_vids))
        quick_bar.addWidget(btn_copy_all_vids)
        
        btn_copy_all_end = QPushButton(f"🎬 复制全部待生成尾帧列 (共 {total_segments} 行)")
        btn_copy_all_end.setToolTip(
            f"将所有待生成的 {total_segments} 个分句尾帧按顺序整理为多行文本。\n"
            "在插件表格第1行的【尾帧图片名】单元格按 Ctrl+V 即可整列全部填满！"
        )
        btn_copy_all_end.setStyleSheet("""
            QPushButton {
                background-color: #D97706;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #B45309;
            }
        """)
        btn_copy_all_end.clicked.connect(lambda: self.copy_all_end_frames(btn_copy_all_end))
        quick_bar.addWidget(btn_copy_all_end)

        btn_copy_all_tsv = QPushButton(f"📊 复制全部表格数据 (TSV格式)")
        btn_copy_all_tsv.setToolTip(
            "按 [序号 \\t 首帧图名 \\t 尾帧图名 \\t 分镜名] 复制全部待生成数据。\n"
            "适用于支持多列批量粘贴的场景或 Excel 表格整理。"
        )
        btn_copy_all_tsv.setStyleSheet("""
            QPushButton {
                background-color: #0284C7;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0369A1;
            }
        """)
        btn_copy_all_tsv.clicked.connect(lambda: self.copy_all_tsv(btn_copy_all_tsv))
        quick_bar.addWidget(btn_copy_all_tsv)

        quick_bar.addStretch()
        layout.addLayout(quick_bar)
        
        # Scrollable area of batches
        self.list_batches = QListWidget()
        self.list_batches.setStyleSheet("""
            QListWidget {
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                background-color: #FAFAFA;
            }
        """)
        
        for idx, batch in enumerate(self.batches):
            item = QListWidgetItem(self.list_batches)
            
            widget = QWidget()
            widget_layout = QHBoxLayout(widget)
            widget_layout.setContentsMargins(12, 10, 12, 10)
            
            points = self.get_batch_points(batch)
            indices_str = ", ".join(str(t["_original_index"] + 1) for t in batch)
            batch_end_count = sum(1 for t in batch if t.get("end_image_name"))
            end_badge = f" | 🎬 尾帧: <b>{batch_end_count}</b> 个" if batch_end_count > 0 else ""
            
            info_text = (
                f"<b>第 {idx + 1} 批</b> (分镜序号: {indices_str})<br/>"
                f"📎 包含 {len(batch)} 个分句{end_badge} | ⚡ 消耗 <b>{points}</b> 积分"
            )
            lbl_info = QLabel(info_text)
            lbl_info.setStyleSheet("font-size: 12px; color: #5D4037;")
            widget_layout.addWidget(lbl_info, stretch=1)
            
            # Action buttons for this batch
            btns_layout = QHBoxLayout()
            btns_layout.setSpacing(6)
            
            btn_copy = QPushButton("📋 复制任务 JSON")
            btn_copy.setToolTip("复制本批次完整的 JSON 任务数据（包含提示词、时长、模式等），供插件导入")
            btn_copy.setStyleSheet("""
                QPushButton {
                    background-color: #8B5CF6;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #7C3AED;
                }
            """)
            btn_copy.clicked.connect(self.make_copy_callback(idx, btn_copy))
            btn_copy.setMinimumHeight(34)
            btn_copy.setMinimumWidth(130)
            btns_layout.addWidget(btn_copy)

            btn_copy_imgs = QPushButton("🖼️ 复制图片路径")
            btn_copy_imgs.setToolTip(
                f"复制本批 {len(batch)} 个分镜所用的图片完整路径，格式如：\n"
                "D:\\路径\\downloads\\\"01.jpeg\" \"02.jpeg\"\n"
                "可直接粘贴到 Flow 文件管理器中上传"
            )
            btn_copy_imgs.setStyleSheet("""
                QPushButton {
                    background-color: #059669;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #047857;
                }
            """)
            btn_copy_imgs.clicked.connect(self.make_copy_images_callback(idx, btn_copy_imgs))
            btn_copy_imgs.setMinimumHeight(34)
            btn_copy_imgs.setMinimumWidth(130)
            btns_layout.addWidget(btn_copy_imgs)
            
            widget_layout.addLayout(btns_layout)
            widget.setLayout(widget_layout)
            hint = widget.sizeHint()
            hint.setHeight(max(hint.height(), 64))
            item.setSizeHint(hint)
            self.list_batches.setItemWidget(item, widget)
            
        layout.addWidget(self.list_batches)
        
        # Close Button
        btn_close = QPushButton("关闭")
        btn_close.setStyleSheet("background-color: #E0A96D; color: white; padding: 7px; font-weight: bold; border-radius: 4px;")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)

    def refresh_workers_list(self):
        """No-op stub for backward compatibility."""
        pass

    def update_polling_ui(self):
        """No-op stub for backward compatibility."""
        pass

    def get_batch_points(self, batch):
        if self.cm:
            return sum(self.cm.get_points_for_duration(item.get("duration", item.get("_raw_duration", 6))) for item in batch)
        points_map = {10: 15, 8: 12, 6: 10, 4: 7}
        total = 0
        for item in batch:
            dur = item.get("duration", item.get("_raw_duration", 6))
            total += points_map.get(dur, 7)
        return total
        
    def make_copy_callback(self, batch_idx, button):
        return lambda: self.copy_batch(batch_idx, button)

    def make_copy_end_callback(self, batch_idx, button):
        return lambda: self.copy_end_frames_column(self.batches[batch_idx], button, desc=f"第 {batch_idx + 1} 批")

    def make_copy_tsv_callback(self, batch_idx, button):
        return lambda: self.copy_tsv_table(self.batches[batch_idx], button, desc=f"第 {batch_idx + 1} 批")

    def copy_batch(self, batch_idx, button):
        import json
        batch_data = self.batches[batch_idx]
        
        cleaned_batch = []
        for item in batch_data:
            c_item = {k: v for k, v in item.items() if not k.startswith("_")}
            cleaned_batch.append(c_item)
            
        try:
            json_str = json.dumps(cleaned_batch, indent=2, ensure_ascii=False)
            from PyQt6.QtGui import QGuiApplication
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(json_str)
            
            button.setText("✓ 已复制")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #10B981;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            self.copied_batches.add(batch_idx)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制批次失败: {e}")

    def copy_end_frames_column(self, batch_data, button, desc="本批"):
        """Copies newline-delimited end frame image names strictly aligned with batch tasks."""
        end_names = [item.get("end_image_name", "").strip() for item in batch_data]
        text_to_copy = "\n".join(end_names)
        
        try:
            from PyQt6.QtGui import QGuiApplication, QCursor
            from PyQt6.QtWidgets import QToolTip, QMessageBox
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(text_to_copy)
            
            button.setText("✓ 已复制尾帧列")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #059669;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            has_end = sum(1 for n in end_names if n)
            msg = f"✓ 已复制{desc} {len(end_names)} 行尾帧名（含 {has_end} 个已设置尾帧）！\n请切换到插件端，在表格【尾帧图片名】首行单元格按 Ctrl+V 即可整列粘贴。"
            QToolTip.showText(QCursor.pos(), msg, button)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制尾帧列失败: {e}")

    def copy_tsv_table(self, batch_data, button, desc="本批"):
        """Copies TSV formatted rows matching the plugin table structure."""
        tsv_lines = []
        for idx, item in enumerate(batch_data):
            orig_idx = item.get("_original_index", idx) + 1
            first_img = item.get("image_name", "").strip()
            end_img = item.get("end_image_name", "").strip()
            dl_path = item.get("download_path", "")
            dl_name = Path(dl_path).name if dl_path else f"{orig_idx:02d}.mp4"
            
            # Format matching plugin: 序号 \t 素材图/首帧-图片名 \t 尾帧图片名 \t 分镜片段名称
            line = f"{orig_idx}\t{first_img}\t{end_img}\t{dl_name}"
            tsv_lines.append(line)
            
        tsv_text = "\n".join(tsv_lines)
        try:
            from PyQt6.QtGui import QGuiApplication, QCursor
            from PyQt6.QtWidgets import QToolTip, QMessageBox
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(tsv_text)
            
            button.setText("✓ 已复制TSV")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #0284C7;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            msg = f"✓ 已复制{desc} {len(tsv_lines)} 行 TSV 表格数据！\n格式：[序号 \\t 首帧图名 \\t 尾帧图名 \\t 分镜名]\n支持在 Excel 或插件表格中批量粘贴。"
            QToolTip.showText(QCursor.pos(), msg, button)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制TSV表格失败: {e}")

    def copy_all_vids_json(self, button):
        """Copies all tasks across all batches as a single chronological JSON array for Google Vids (no 50-credit limit)."""
        import json
        all_tasks = [task for batch in self.batches for task in batch]
        all_tasks.sort(key=lambda t: t.get("_original_index", 0))

        cleaned_all = []
        for item in all_tasks:
            c_item = {k: v for k, v in item.items() if not k.startswith("_")}
            if "_raw_duration" in item:
                c_item["duration"] = item["_raw_duration"]
            cleaned_all.append(c_item)

        try:
            json_str = json.dumps(cleaned_all, indent=2, ensure_ascii=False)
            from PyQt6.QtGui import QGuiApplication, QCursor
            from PyQt6.QtWidgets import QToolTip
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(json_str)

            button.setText(f"✓ 已复制全部 {len(cleaned_all)} 条 (Vids)")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #10B981;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 12px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            msg = (
                f"✓ 已复制全部 {len(cleaned_all)} 条待生成任务 JSON（无 50 积分限制）！\n"
                "现在只需切换到 Google Vids 页面，点击插件悬浮胶囊的【🎬】按钮即可自动逐条上传图片、生成并下载视频！"
            )
            QToolTip.showText(QCursor.pos(), msg, button)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制全部 Vids 任务 JSON 失败: {e}")

    def copy_all_end_frames(self, button):
        all_tasks = [task for batch in self.batches for task in batch]
        self.copy_end_frames_column(all_tasks, button, desc="全部")

    def copy_all_tsv(self, button):
        all_tasks = [task for batch in self.batches for task in batch]
        self.copy_tsv_table(all_tasks, button, desc="全部")

    def make_copy_images_callback(self, batch_idx, button):
        return lambda: self.copy_image_paths(batch_idx, button)

    def copy_image_paths(self, batch_idx, button):
        """Copies deduplicated image file paths for a batch in the format:
        D:\\path\\downloads\\"01.jpeg" "02.jpeg" "03.jpeg"
        """
        batch = self.batches[batch_idx]
        
        # Collect unique image names while preserving order
        seen = set()
        unique_images = []
        for item in batch:
            img = item.get("image_name", "").strip()
            if img and img not in seen:
                seen.add(img)
                unique_images.append(img)
            # Also include end_image_name if present
            end_img = item.get("end_image_name", "").strip()
            if end_img and end_img not in seen:
                seen.add(end_img)
                unique_images.append(end_img)
        
        if not unique_images:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "本批次没有关联图片素材！")
            return
        
        # Get the downloads directory from any task's local_image_path or end_local_image_path
        downloads_dir = ""
        for item in batch:
            local_path = item.get("local_image_path", "") or item.get("end_local_image_path", "")
            if local_path:
                downloads_dir = str(Path(local_path).parent)
                break
        
        # Build the output string: D:\path\downloads\"01.jpeg" "02.jpeg"
        quoted_names = " ".join(f'"{img}"' for img in unique_images)
        result = f'{downloads_dir}\\{quoted_names}' if downloads_dir else quoted_names
        
        try:
            from PyQt6.QtGui import QGuiApplication, QCursor
            from PyQt6.QtWidgets import QToolTip
            clipboard = QGuiApplication.clipboard()
            clipboard.setText(result)
            
            button.setText("✓ 已复制路径")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #059669;
                    color: white;
                    border: none;
                    border-radius: 4px;
                    padding: 6px 10px;
                    font-size: 11px;
                    font-weight: bold;
                }
            """)
            msg = (f"✓ 已复制第 {batch_idx + 1} 批共 {len(unique_images)} 张图片路径！\n"
                   f"格式：{downloads_dir}\\\"图片名\" ...\n"
                   "可直接粘贴到 Flow 文件管理器地址栏上传")
            QToolTip.showText(QCursor.pos(), msg, button)
        except Exception as e:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "错误", f"复制图片路径失败: {e}")
