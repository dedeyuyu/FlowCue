# -*- coding: utf-8 -*-
"""右侧「片段属性配置」面板与分句图片解析相关方法。

由 ProjectDetailWidget 通过多重继承组合使用，方法内的 self 即 ProjectDetailWidget 实例。"""
from views.project_detail.common import *  # noqa: F401,F403
from views.project_detail.common import logger  # noqa: F401
from PyQt6.QtCore import QThread, pyqtSignal


def _decode_small_qimage(file_path, size=24):
    """线程安全：用 PIL 解码并缩放成小图，返回 QImage（QImage 可跨线程传递，QPixmap/QIcon 不行）。"""
    from PyQt6.QtGui import QImage
    try:
        from PIL import Image
        with Image.open(file_path) as pil_img:
            pil_img.draft("RGB", (size * 2, size * 2))
            pil_img.thumbnail((size, size))
            rgba = pil_img.convert("RGBA")
            w, h = rgba.size
            return QImage(rgba.tobytes("raw", "RGBA"), w, h, QImage.Format.Format_RGBA8888).copy()
    except Exception:
        return None


class _IconDecodeThread(QThread):
    decoded = pyqtSignal(object, object)  # cache_key(tuple), QImage|None

    def __init__(self, keys, parent=None):
        super().__init__(parent)
        self.keys = list(keys)

    def run(self):
        for key in self.keys:
            if self.isInterruptionRequested():
                return
            self.decoded.emit(key, _decode_small_qimage(key[0]))


class PropertyPanelMixin:
    def init_property_panel(self):
        panel_layout = QVBoxLayout(self.property_panel)
        panel_layout.setContentsMargins(10, 0, 10, 0)
        panel_layout.setSpacing(10)
        
        # Title and End Frame Toggle Row
        title_row = QHBoxLayout()
        lbl_title = QLabel("⚙️ 片段属性配置")
        lbl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #5D4037;")
        title_row.addWidget(lbl_title)
        title_row.addStretch()
        
        self.chk_enable_end_frame = QCheckBox("启用尾帧")
        self.chk_enable_end_frame.setToolTip("开启后，支持为每句配置尾帧，并将尾帧自动联动为下一句的首帧。")
        self.chk_enable_end_frame.setStyleSheet("font-size: 12px; color: #5D4037; font-weight: bold;")
        self.chk_enable_end_frame.toggled.connect(self.on_enable_end_frame_toggled)
        title_row.addWidget(self.chk_enable_end_frame)
        panel_layout.addLayout(title_row)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("color: #D7CCC8;")
        panel_layout.addWidget(line)
        
        # Selected Segment Info
        self.lbl_prop_index = QLabel("当前句：无选择")
        self.lbl_prop_index.setStyleSheet("color: #8D6E63; font-weight: bold;")
        panel_layout.addWidget(self.lbl_prop_index)
        
        self.txt_prop_text = QTextEdit()
        self.txt_prop_text.setReadOnly(True)
        self.txt_prop_text.setMaximumHeight(80)
        self.txt_prop_text.setStyleSheet("""
            QTextEdit {
                background-color: #F5F5F5;
                color: #5D4037;
                border: 1px solid #E0D7D3;
                font-size: 12px;
            }
        """)
        panel_layout.addWidget(self.txt_prop_text)
        
        # 1. First Image selector
        self.lbl_prop_first_image = QLabel("📸 首帧图片素材:")
        panel_layout.addWidget(self.lbl_prop_first_image)
        self.combo_prop_image = QComboBox()
        self.combo_prop_image.setMaxVisibleItems(12)
        self.combo_prop_image.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_image.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_image.currentIndexChanged.connect(self.on_prop_image_changed)
        panel_layout.addWidget(self.combo_prop_image)
        
        # First Image preview
        self.lbl_prop_preview = QLabel("无首帧预览")
        self.lbl_prop_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prop_preview.setMinimumHeight(120)
        self.lbl_prop_preview.setMaximumHeight(160)
        self.lbl_prop_preview.setStyleSheet("""
            QLabel {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #8D6E63;
                font-size: 11px;
                font-weight: normal;
            }
        """)
        panel_layout.addWidget(self.lbl_prop_preview)
        
        # 2. End Image selector & preview (in togglable container)
        self.container_end_image = QWidget()
        end_img_layout = QVBoxLayout(self.container_end_image)
        end_img_layout.setContentsMargins(0, 0, 0, 0)
        end_img_layout.setSpacing(6)
        
        self.lbl_prop_end_image = QLabel("🎬 尾帧图片素材 (下一句首帧自动跟随):")
        end_img_layout.addWidget(self.lbl_prop_end_image)
        
        self.combo_prop_end_image = QComboBox()
        self.combo_prop_end_image.setMaxVisibleItems(12)
        self.combo_prop_end_image.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_end_image.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_end_image.currentIndexChanged.connect(self.on_prop_end_image_changed)
        end_img_layout.addWidget(self.combo_prop_end_image)
        
        self.lbl_prop_end_preview = QLabel("无尾帧预览")
        self.lbl_prop_end_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_prop_end_preview.setMinimumHeight(120)
        self.lbl_prop_end_preview.setMaximumHeight(160)
        self.lbl_prop_end_preview.setStyleSheet("""
            QLabel {
                background-color: #EFEBE9;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                color: #8D6E63;
                font-size: 11px;
                font-weight: normal;
            }
        """)
        end_img_layout.addWidget(self.lbl_prop_end_preview)
        
        panel_layout.addWidget(self.container_end_image)
        self.container_end_image.setVisible(self.enable_end_frame)
        
        # Segment-specific template selector
        panel_layout.addWidget(QLabel("📐 片段专属模板:"))
        self.combo_prop_template = NoWheelComboBox()
        self.combo_prop_template.setMaxVisibleItems(12)
        self.combo_prop_template.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_template.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_template.currentIndexChanged.connect(self.on_prop_template_changed)
        panel_layout.addWidget(self.combo_prop_template)
        
        # Segment-specific motion selector
        panel_layout.addWidget(QLabel("🎥 片段专属运镜:"))
        self.combo_prop_motion = NoWheelComboBox()
        self.combo_prop_motion.setMaxVisibleItems(12)
        self.combo_prop_motion.view().setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.combo_prop_motion.setStyleSheet("""
            QComboBox {
                combobox-popup: 0;
                background-color: white;
                border: 1px solid #D7CCC8;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                border: 1px solid #D7CCC8;
                background-color: white;
                selection-background-color: #FFE0B2;
                selection-color: #5D4037;
                outline: none;
            }
        """)
        self.combo_prop_motion.currentIndexChanged.connect(self.on_prop_motion_changed)
        panel_layout.addWidget(self.combo_prop_motion)

        # Mode selector
        panel_layout.addWidget(QLabel("⚙️ 生成模式:"))
        self.combo_prop_mode = NoWheelComboBox()
        self.combo_prop_mode.addItem("-- 遵循规则设置 --", "")
        self.combo_prop_mode.addItem("帧模式 (First Frame)", "VIDEO_FRAMES")
        self.combo_prop_mode.addItem("素材模式 (Reference)", "VIDEO_REFERENCES")
        self.combo_prop_mode.currentIndexChanged.connect(self.on_prop_mode_changed)
        panel_layout.addWidget(self.combo_prop_mode)
        
        panel_layout.addStretch()
        
        # Disable properties by default until a row is selected
        self.property_panel.setEnabled(False)

    def on_enable_end_frame_toggled(self, checked):
        """Toggles end frame capability for current project."""
        self.enable_end_frame = checked
        if self.project_model:
            self.project_model.enable_end_frame = checked
            self.project_model.save()
        if hasattr(self, "container_end_image"):
            self.container_end_image.setVisible(checked)
        # Refresh all row index labels in table to update 🎬 emojis
        for r in range(self.table_segments.rowCount()):
            self.refresh_table_row_index_label(r)

    def _list_project_images(self, use_cache=False):
        """Returns sorted image Path list in downloads/ (cached during a single table populate pass)."""
        if use_cache and getattr(self, "_img_list_cache", None) is not None:
            return self._img_list_cache
        if not self.project_path:
            return []
        downloads_dir = self.project_path / "downloads"
        if not downloads_dir.exists():
            return []
        img_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        try:
            all_imgs = [item for item in downloads_dir.iterdir() if item.is_file() and item.suffix.lower() in img_extensions]
            all_imgs.sort(key=lambda x: x.name)
        except Exception:
            return []
        if use_cache:
            self._img_list_cache = all_imgs
        return all_imgs

    def resolve_segment_image_and_data(self, idx, seg, with_data=True, use_cache=False):
        """
        智能解析分句关联的图片文件名、绝对路径以及 Base64 Data URL：
        1. 优先检查 seg 中显式绑定的 image_name 是否真实存在于 downloads/；
        2. 按分句序号智能精准匹配 downloads/ 下的文件（如 01.png, 01.jpg, 1.png, 1.jpg, 01_*.png 等）；
        3. 若工程内仅有 1 张图片，所有分句自动共用该图片；
        4. 若工程内有多张图片，按文件名升序排序后，自动关联第 idx 张；
        5. 若图片数量少于分句数，循环取模取用或使用首张；
        6. 自动将图片文件读取并编码为 base64 data url (如 data:image/png;base64,xxxx)，确保浏览器能 100% 自动上传！
           （with_data=False 时跳过读取与编码，仅用于界面刷新 / 拆批，避免卡顿）
        """
        if not self.project_path:
            return "", "", ""

        downloads_dir = self.project_path / "downloads"
        all_imgs = self._list_project_images(use_cache=use_cache)

        if not all_imgs:
            return "", "", ""

        chosen_img_obj = None

        # 1. 优先检查 seg 中的显式绑定
        explicit_name = seg.get("image_name", "").strip() if isinstance(seg, dict) else ""
        if explicit_name:
            if use_cache:
                for img in all_imgs:
                    if img.name == explicit_name:
                        chosen_img_obj = img
                        break
            else:
                cand = downloads_dir / explicit_name
                if cand.exists() and cand.is_file():
                    chosen_img_obj = cand

        # 2. 按序号匹配 (1.jpg, 01.jpg, 1_*.jpg 等)
        if not chosen_img_obj:
            idx_str1 = f"{idx + 1}"
            idx_str2 = f"{idx + 1:02d}"
            for img in all_imgs:
                stem = img.stem
                if stem == idx_str1 or stem == idx_str2 or stem.startswith(f"{idx_str1}_") or stem.startswith(f"{idx_str2}_") or stem.startswith(f"{idx_str1}-") or stem.startswith(f"{idx_str2}-"):
                    chosen_img_obj = img
                    break

        # 3. 若只有 1 张图片，全工程共用
        if not chosen_img_obj and len(all_imgs) == 1:
            chosen_img_obj = all_imgs[0]

        # 4. 若有多张图片，按顺序对齐第 idx 张（若超出则取模或首张）
        if not chosen_img_obj:
            if idx < len(all_imgs):
                chosen_img_obj = all_imgs[idx]
            else:
                chosen_img_obj = all_imgs[idx % len(all_imgs)]

        if not chosen_img_obj or (not use_cache and not chosen_img_obj.exists()):
            return "", "", ""

        chosen_name = chosen_img_obj.name
        chosen_path = str(chosen_img_obj.resolve())

        # 同步回写进 seg 中
        if isinstance(seg, dict):
            seg["image_name"] = chosen_name

        if not with_data:
            return chosen_name, chosen_path, ""

        # 5. 编码为 Base64 Data URL
        import base64
        import mimetypes
        mime_type, _ = mimetypes.guess_type(chosen_path)
        if not mime_type:
            mime_type = "image/png"

        data_url = ""
        try:
            with open(chosen_img_obj, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode("utf-8")
                data_url = f"data:{mime_type};base64,{b64_str}"
        except Exception as e:
            logger.warning(f"读取图片 Base64 失败 [{chosen_name}]: {e}")

        return chosen_name, chosen_path, data_url

    def resolve_segment_end_image_and_data(self, idx, seg, with_data=True):
        """
        解析分句关联的尾帧图片文件名、绝对路径以及 Base64 Data URL：
        1. 仅当启用尾帧功能时生效；
        2. 检查 seg 中显式绑定的 end_image_name 是否真实存在于 downloads/；
        3. 若存在，自动读取并编码为 base64 data url；
        4. 若未开启或未指定，返回 ("", "", "")。
        """
        if not getattr(self, "enable_end_frame", False) or not self.project_path:
            return "", "", ""

        downloads_dir = self.project_path / "downloads"
        if not downloads_dir.exists():
            return "", "", ""

        end_name = seg.get("end_image_name", "").strip() if isinstance(seg, dict) else ""
        if not end_name:
            return "", "", ""

        cand = downloads_dir / end_name
        if not cand.exists() or not cand.is_file():
            return "", "", ""

        end_path = str(cand.resolve())
        if not with_data:
            return end_name, end_path, ""

        import base64
        import mimetypes
        mime_type, _ = mimetypes.guess_type(end_path)
        if not mime_type:
            mime_type = "image/png"

        data_url = ""
        try:
            with open(cand, "rb") as f:
                b64_str = base64.b64encode(f.read()).decode("utf-8")
                data_url = f"data:{mime_type};base64,{b64_str}"
        except Exception as e:
            logger.warning(f"读取尾帧图片 Base64 失败 [{end_name}]: {e}")

        return end_name, end_path, data_url

    def get_project_single_image(self):
        """Returns the filename of the single image in downloads directory, or None if 0 or >1 images."""
        if not self.project_path:
            return None
        downloads_dir = self.project_path / "downloads"
        if not downloads_dir.exists():
            return None
        img_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        try:
            images = [item.name for item in downloads_dir.iterdir() if item.is_file() and item.suffix.lower() in img_extensions]
            if len(images) == 1:
                return images[0]
        except Exception:
            pass
        return None

    def on_table_selection_changed(self, current, previous):
        if not self.project_model or current is None:
            self.current_prop_row = -1
            self.lbl_prop_index.setText("当前句：无选择")
            self.txt_prop_text.clear()
            self.combo_prop_image.blockSignals(True)
            self.combo_prop_image.setCurrentIndex(0)
            self.combo_prop_image.blockSignals(False)
            if hasattr(self, "combo_prop_end_image"):
                self.combo_prop_end_image.blockSignals(True)
                self.combo_prop_end_image.setCurrentIndex(0)
                self.combo_prop_end_image.blockSignals(False)
            if hasattr(self, "lbl_prop_end_preview"):
                self.lbl_prop_end_preview.clear()
                self.lbl_prop_end_preview.setText("无尾帧预览")
            self.combo_prop_template.blockSignals(True)
            self.combo_prop_template.setCurrentIndex(0)
            self.combo_prop_template.blockSignals(False)
            self.combo_prop_motion.blockSignals(True)
            self.combo_prop_motion.setCurrentIndex(0)
            self.combo_prop_motion.blockSignals(False)
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("无首帧预览")
            self.combo_prop_mode.blockSignals(True)
            self.combo_prop_mode.setCurrentIndex(0)
            self.combo_prop_mode.blockSignals(False)
            self.property_panel.setEnabled(False)
            return
            
        row = current.row()
        if row < 0 or row >= len(self.project_model.spanish_segments):
            self.current_prop_row = -1
            self.property_panel.setEnabled(False)
            return
            
        self.current_prop_row = row
        self.property_panel.setEnabled(True)
        
        # Block signals to prevent infinite update loop
        self.combo_prop_image.blockSignals(True)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(True)
        self.combo_prop_template.blockSignals(True)
        self.combo_prop_motion.blockSignals(True)
        self.combo_prop_mode.blockSignals(True)
        
        # Populate selected segment data
        seg = self.project_model.spanish_segments[row]
        self.lbl_prop_index.setText(f"当前句：第 {row + 1} 句")
        self.txt_prop_text.setPlainText(seg.get("text", ""))
        
        # Refresh combo lists & placeholders
        self.refresh_prop_image_combo_items()
        self.refresh_prop_template_motion_combos()
        
        # Select current image (首帧)
        image_name = seg.get("image_name", "")
        img_idx = self.combo_prop_image.findData(image_name)
        if img_idx >= 0:
            self.combo_prop_image.setCurrentIndex(img_idx)
        else:
            self.combo_prop_image.setCurrentIndex(0)

        # Select current end image (尾帧)
        end_image_name = seg.get("end_image_name", "")
        if hasattr(self, "combo_prop_end_image"):
            end_img_idx = self.combo_prop_end_image.findData(end_image_name)
            if end_img_idx >= 0:
                self.combo_prop_end_image.setCurrentIndex(end_img_idx)
            else:
                self.combo_prop_end_image.setCurrentIndex(0)

        # Select current segment template
        seg_tpl_id = seg.get("template_id", "")
        tpl_idx = self.combo_prop_template.findData(seg_tpl_id)
        if tpl_idx >= 0:
            self.combo_prop_template.setCurrentIndex(tpl_idx)
        else:
            self.combo_prop_template.setCurrentIndex(0)
            
        # Select current segment motion
        seg_motion_id = seg.get("motion_id", "")
        motion_idx = self.combo_prop_motion.findData(seg_motion_id)
        if motion_idx >= 0:
            self.combo_prop_motion.setCurrentIndex(motion_idx)
        else:
            self.combo_prop_motion.setCurrentIndex(0)
            
        # Select current mode (only if explicitly overridden via mode_overridden)
        if seg.get("mode_overridden") and seg.get("mode"):
            mode = seg.get("mode", "")
        else:
            mode = ""
        mode_idx = self.combo_prop_mode.findData(mode)
        if mode_idx >= 0:
            self.combo_prop_mode.setCurrentIndex(mode_idx)
        else:
            self.combo_prop_mode.setCurrentIndex(0)
            
        # Update preview
        self.update_prop_image_preview(image_name)
        if hasattr(self, "update_prop_end_image_preview"):
            self.update_prop_end_image_preview(end_image_name)
        
        self.combo_prop_image.blockSignals(False)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(False)
        self.combo_prop_template.blockSignals(False)
        self.combo_prop_motion.blockSignals(False)
        self.combo_prop_mode.blockSignals(False)

    def refresh_prop_image_combo_items(self):
        self.combo_prop_image.blockSignals(True)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(True)
            
        current_data = self.combo_prop_image.currentData()
        current_end_data = self.combo_prop_end_image.currentData() if hasattr(self, "combo_prop_end_image") else None
        
        self.combo_prop_image.clear()
        self.combo_prop_image.addItem("-- 无首帧 --", "")
        
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.clear()
            self.combo_prop_end_image.addItem("-- 无尾帧 --", "")
        
        if self.project_path:
            downloads_dir = self.project_path / "downloads"
            if downloads_dir.exists():
                # Supported image extensions
                img_extensions = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
                for item in sorted(downloads_dir.iterdir()):
                    if item.is_file() and item.suffix.lower() in img_extensions:
                        # Add item with a small icon preview!
                        icon = self.get_small_image_icon(item)
                        self.combo_prop_image.addItem(icon, item.name, item.name)
                        if hasattr(self, "combo_prop_end_image"):
                            self.combo_prop_end_image.addItem(icon, item.name, item.name)
                        
        # Restore index if it was previously set
        if current_data:
            idx = self.combo_prop_image.findData(current_data)
            if idx >= 0:
                self.combo_prop_image.setCurrentIndex(idx)
        if current_end_data and hasattr(self, "combo_prop_end_image"):
            idx_end = self.combo_prop_end_image.findData(current_end_data)
            if idx_end >= 0:
                self.combo_prop_end_image.setCurrentIndex(idx_end)
                
        self.combo_prop_image.blockSignals(False)
        if hasattr(self, "combo_prop_end_image"):
            self.combo_prop_end_image.blockSignals(False)

    def get_small_image_icon(self, file_path, sync=False):
        """
        下拉框用的小缩略图。已缓存直接返回；未缓存时默认交给后台线程解码（先返回空图标，
        解码完成后自动回填到下拉框），避免首次打开图片很多的项目时界面卡住。
        sync=True 时在当前线程直接解码（用于弹窗等一次性场景）。
        """
        from PyQt6.QtGui import QIcon, QPixmap
        # 缩略图缓存：避免每次点击分句都重新解码全部图片
        if not hasattr(self, "_icon_cache"):
            self._icon_cache = {}
        try:
            st = os.stat(file_path)
            cache_key = (str(file_path), st.st_mtime_ns, st.st_size)
        except Exception:
            return QIcon()
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]
        if not sync:
            self._queue_icon_decode(cache_key)
            return QIcon()
        qimg = _decode_small_qimage(file_path)
        if qimg is None:
            return QIcon()
        icon = QIcon(QPixmap.fromImage(qimg))
        if len(self._icon_cache) > 2000:
            self._icon_cache.clear()
        self._icon_cache[cache_key] = icon
        return icon

    def _queue_icon_decode(self, cache_key):
        if not hasattr(self, "_icon_pending"):
            self._icon_pending = set()
            self._icon_queue = []
        if cache_key in self._icon_pending:
            return
        self._icon_pending.add(cache_key)
        self._icon_queue.append(cache_key)
        # 合并同一轮事件循环内的请求，一次性交给后台线程
        QTimer.singleShot(0, self._start_icon_decode_thread)

    def _start_icon_decode_thread(self):
        th = getattr(self, "_icon_thread", None)
        if th is not None and th.isRunning():
            return  # 当前线程结束后会再次检查队列
        if not getattr(self, "_icon_queue", None):
            return
        keys, self._icon_queue = self._icon_queue, []
        th = _IconDecodeThread(keys, self)
        th.decoded.connect(self._on_icon_decoded)
        th.finished.connect(self._start_icon_decode_thread)
        self._icon_thread = th
        th.start()

    def _on_icon_decoded(self, cache_key, qimg):
        from PyQt6.QtGui import QIcon, QPixmap
        cache_key = tuple(cache_key)
        self._icon_pending.discard(cache_key)
        if qimg is None or qimg.isNull():
            return
        icon = QIcon(QPixmap.fromImage(qimg))
        self._icon_cache[cache_key] = icon
        name = os.path.basename(cache_key[0])
        for combo_name in ("combo_prop_image", "combo_prop_end_image"):
            combo = getattr(self, combo_name, None)
            if combo is None:
                continue
            idx = combo.findData(name)
            if idx >= 0:
                combo.setItemIcon(idx, icon)

    def update_prop_image_preview(self, image_name):
        if not image_name:
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("无首帧")
            return
            
        file_path = self.project_path / "downloads" / image_name
        if not file_path.exists():
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("图片不存在")
            return
            
        try:
            from PIL import Image
            from PyQt6.QtGui import QImage, QPixmap
            with Image.open(file_path) as pil_img:
                pil_img.thumbnail((220, 150))
                pil_img_rgba = pil_img.convert("RGBA")
                width, height = pil_img_rgba.size
                raw_data = pil_img_rgba.tobytes("raw", "RGBA")
                qimg = QImage(raw_data, width, height, QImage.Format.Format_RGBA8888).copy()
                pixmap = QPixmap.fromImage(qimg)
            self.lbl_prop_preview.setPixmap(pixmap)
        except Exception as e:
            print(f"Error loading preview: {e}")
            self.lbl_prop_preview.clear()
            self.lbl_prop_preview.setText("预览失败")

    def update_prop_end_image_preview(self, image_name):
        if not hasattr(self, "lbl_prop_end_preview"):
            return
        if not image_name:
            self.lbl_prop_end_preview.clear()
            self.lbl_prop_end_preview.setText("无尾帧")
            return
            
        file_path = self.project_path / "downloads" / image_name
        if not file_path.exists():
            self.lbl_prop_end_preview.clear()
            self.lbl_prop_end_preview.setText("图片不存在")
            return
            
        try:
            from PIL import Image
            from PyQt6.QtGui import QImage, QPixmap
            with Image.open(file_path) as pil_img:
                pil_img.thumbnail((220, 150))
                pil_img_rgba = pil_img.convert("RGBA")
                width, height = pil_img_rgba.size
                raw_data = pil_img_rgba.tobytes("raw", "RGBA")
                qimg = QImage(raw_data, width, height, QImage.Format.Format_RGBA8888).copy()
                pixmap = QPixmap.fromImage(qimg)
            self.lbl_prop_end_preview.setPixmap(pixmap)
        except Exception as e:
            print(f"Error loading end preview: {e}")
            self.lbl_prop_end_preview.clear()
            self.lbl_prop_end_preview.setText("预览失败")

    def on_prop_image_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        image_name = self.combo_prop_image.currentData()
        self.project_model.spanish_segments[row]["image_name"] = image_name if image_name else ""
        
        # Update large preview
        self.update_prop_image_preview(image_name)
        
        # Refresh the index cell text to display the camera emoji if selected
        self.refresh_table_row_index_label(row)

    def on_prop_end_image_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        end_image_name = self.combo_prop_end_image.currentData() if hasattr(self, "combo_prop_end_image") else ""
        self.project_model.spanish_segments[row]["end_image_name"] = end_image_name if end_image_name else ""
        
        # Update large preview
        self.update_prop_end_image_preview(end_image_name)
        
        # 联动逻辑：若当前启用了尾帧，且当前句设置了有效的尾帧图片，
        # 则自动将下一句（第 row + 2 句）的首帧设置为该尾帧图片！
        if getattr(self, "enable_end_frame", False) and end_image_name:
            next_row = row + 1
            if next_row < len(self.project_model.spanish_segments):
                self.project_model.spanish_segments[next_row]["image_name"] = end_image_name
                self.refresh_table_row_index_label(next_row)
                
        # 刷新当前行图标与保存
        self.refresh_table_row_index_label(row)
        self.project_model.save()

    def on_prop_mode_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        mode = self.combo_prop_mode.currentData()
        if mode:
            self.project_model.spanish_segments[row]["mode"] = mode
            self.project_model.spanish_segments[row]["mode_overridden"] = True
        else:
            default_mode = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
            self.project_model.spanish_segments[row]["mode"] = default_mode
            self.project_model.spanish_segments[row]["mode_overridden"] = False
        self.project_model.save()

    def refresh_table_row_index_label(self, row):
        if not self.project_model or row < 0 or row >= len(self.project_model.spanish_segments):
            return
        seg = self.project_model.spanish_segments[row]
        has_image = bool(seg.get("image_name"))
        has_end_image = bool(seg.get("end_image_name")) if getattr(self, "enable_end_frame", False) else False
        has_custom = bool(seg.get("template_id")) or bool(seg.get("motion_id"))
        index_label = str(row + 1)
        if has_image:
            index_label += " 📷"
        if has_end_image:
            index_label += " 🎬"
        if has_custom:
            index_label += " ⚙️"
        
        self.table_segments.blockSignals(True)
        item = self.table_segments.item(row, 0)
        if item:
            item.setText(index_label)
        self.table_segments.blockSignals(False)

    def get_effective_template_and_motion(self, row):
        """Returns (tpl, motion) dicts for specified row, resolving segment overrides or global fallbacks."""
        if not self.project_model or not self.template_manager:
            return None, None
        if row < 0 or row >= len(self.project_model.spanish_segments):
            return None, None
            
        seg = self.project_model.spanish_segments[row]
        
        # 1. Template resolution
        tpl_id = seg.get("template_id", "")
        if not tpl_id:
            tpl_id = self.combo_templates.currentData()
        tpl = self.template_manager.get_template(tpl_id)
        
        # 2. Motion resolution
        motion_id = seg.get("motion_id", "")
        if not motion_id:
            motion_id = self.combo_motions.currentData()
        motion = self.template_manager.get_motion(motion_id)
        
        return tpl, motion

    def refresh_prop_template_motion_combos(self):
        """Populates the property panel template and motion dropdowns with dynamic fallback label."""
        if not hasattr(self, "combo_prop_template") or not self.template_manager:
            return
            
        self.combo_prop_template.blockSignals(True)
        self.combo_prop_motion.blockSignals(True)
        
        current_tpl = self.combo_prop_template.currentData()
        current_motion = self.combo_prop_motion.currentData()
        
        self.combo_prop_template.clear()
        self.combo_prop_motion.clear()
        
        # Get current global names for default item text
        global_tpl_id = self.combo_templates.currentData()
        global_tpl = self.template_manager.get_template(global_tpl_id)
        global_tpl_name = global_tpl["name"] if global_tpl else "未选择"
        
        global_motion_id = self.combo_motions.currentData()
        global_motion = self.template_manager.get_motion(global_motion_id)
        global_motion_name = global_motion["name"] if global_motion else "未选择"
        
        self.combo_prop_template.addItem(f"-- 遵循统一设置 ({global_tpl_name}) --", "")
        self.combo_prop_motion.addItem(f"-- 遵循统一设置 ({global_motion_name}) --", "")
        
        for t in self.template_manager.templates:
            self.combo_prop_template.addItem(t["name"], t["id"])
        for m in self.template_manager.motions:
            self.combo_prop_motion.addItem(m["name"], m["id"])
            
        if current_tpl:
            idx = self.combo_prop_template.findData(current_tpl)
            if idx >= 0:
                self.combo_prop_template.setCurrentIndex(idx)
        if current_motion:
            idx = self.combo_prop_motion.findData(current_motion)
            if idx >= 0:
                self.combo_prop_motion.setCurrentIndex(idx)
                
        self.combo_prop_template.blockSignals(False)
        self.combo_prop_motion.blockSignals(False)
        
        if hasattr(self, "combo_prop_mode") and self.combo_prop_mode.count() > 0:
            default_mode_code = getattr(self.config_manager, "default_generation_mode", "VIDEO_FRAMES") if self.config_manager else "VIDEO_FRAMES"
            default_mode_name = "素材模式" if default_mode_code == "VIDEO_REFERENCES" else "帧模式"
            self.combo_prop_mode.setItemText(0, f"-- 遵循规则设置 ({default_mode_name}) --")

    def on_prop_template_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        tpl_id = self.combo_prop_template.currentData()
        self.project_model.spanish_segments[row]["template_id"] = tpl_id if tpl_id else ""
        self.update_segment_row_prompt(row)
        self.project_model.save()

    def on_prop_motion_changed(self):
        row = getattr(self, "current_prop_row", -1)
        if row < 0 or not self.project_model or row >= len(self.project_model.spanish_segments):
            return
            
        motion_id = self.combo_prop_motion.currentData()
        self.project_model.spanish_segments[row]["motion_id"] = motion_id if motion_id else ""
        self.update_segment_row_prompt(row)
        self.project_model.save()

    def update_segment_row_prompt(self, row):
        """Re-computes prompt and updates cell items for a specific segment row."""
        if not self.project_model or row < 0 or row >= self.table_segments.rowCount():
            return
            
        if row >= len(self.project_model.spanish_segments):
            return
            
        seg = self.project_model.spanish_segments[row]
        text_item = self.table_segments.item(row, 1)
        raw_text = text_item.text().strip() if text_item else seg.get("text", "")
        text = TextProcessor.remove_punctuation(raw_text)
        
        tpl, motion = self.get_effective_template_and_motion(row)
        template_content = tpl["content"] if tpl else "{spanish_text}"
        motion_content = motion["content"] if motion else ""
        
        final_prompt = template_content.replace("{spanish_text}", text)
        final_prompt = final_prompt.replace("{camera_motion}", motion_content)
        final_prompt = re.sub(r' +', ' ', final_prompt).strip()
        
        self.table_segments.blockSignals(True)
        
        # Update index & icons
        self.refresh_table_row_index_label(row)
        
        # Update prompt cell
        prompt_item = QTableWidgetItem(final_prompt)
        prompt_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table_segments.setItem(row, 4, prompt_item)
        
        # Re-apply row color if copied
        if hasattr(self, 'copied_rows') and row in self.copied_rows:
            self.change_row_color(row, copied=True, persist=False)
            
        self.table_segments.blockSignals(False)
