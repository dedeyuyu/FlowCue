# -*- coding: utf-8 -*-
"""检查更新对话框：检查 → 显示更新说明 → 一键下载并安装软件 / 一键下载最新浏览器插件。"""
import os
import subprocess
from pathlib import Path
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                             QProgressBar, QTextEdit, QMessageBox, QApplication, QFileDialog)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices

from version import __version__
from services.updater import CheckUpdateThread, DownloadUpdateThread, launch_installer, FALLBACK_EXT_URL, RELEASES_PAGE_URL


class UpdateDialog(QDialog):
    def __init__(self, parent=None, auto_check=True):
        super().__init__(parent)
        self.setWindowTitle("检查更新 & 下载最新插件")
        self.resize(640, 450)
        self.info = None
        self.check_thread = None
        self.dl_thread = None
        self.ext_dl_thread = None

        lay = QVBoxLayout(self)
        self.lbl_cur = QLabel(f"当前软件版本：v{__version__}")
        self.lbl_cur.setStyleSheet("font-size:13px;")
        self.lbl_status = QLabel("")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setStyleSheet("font-size:14px;font-weight:bold;")
        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setPlaceholderText("更新说明会显示在这里")
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        lay.addWidget(self.lbl_cur)
        lay.addWidget(self.lbl_status)
        lay.addWidget(self.txt_notes, 1)
        lay.addWidget(self.bar)

        row = QHBoxLayout()
        self.btn_check = QPushButton("🔄 重新检查")
        self.btn_download_ext = QPushButton("🧩 下载最新插件")
        self.btn_download_ext.setToolTip("直接从 GitHub 下载最新版本的浏览器插件压缩包 (FlowCue-Extension.7z)")
        self.btn_download_ext.setStyleSheet(
            "QPushButton{background:#7C3AED;color:white;font-weight:bold;padding:6px 14px;border-radius:4px;}"
            "QPushButton:hover{background:#6D28D9;}"
            "QPushButton:disabled{background:#9CA3AF;}"
        )
        self.btn_download_runtime = QPushButton("📦 下载必要插件 (FFmpeg+Reels)")
        self.btn_download_runtime.setToolTip(
            "手动一键下载并安装视频拼接所需的 FFmpeg 与批量Reels/素材快速审核运行环境\n"
            "自动安装到系统路径：%LOCALAPPDATA%\\FlowCue\\runtime"
        )
        self.btn_download_runtime.setStyleSheet(
            "QPushButton{background:#D97706;color:white;font-weight:bold;padding:6px 14px;border-radius:4px;}"
            "QPushButton:hover{background:#B45309;}"
            "QPushButton:disabled{background:#9CA3AF;}"
        )
        self.btn_update = QPushButton("⬇️ 立即更新软件")
        self.btn_update.setEnabled(False)
        self.btn_update.setStyleSheet(
            "QPushButton{background:#059669;color:white;font-weight:bold;padding:6px 14px;border-radius:4px;}"
            "QPushButton:hover{background:#047857;}"
            "QPushButton:disabled{background:#9CA3AF;}"
        )
        self.btn_browser = QPushButton("🌐 浏览器下载")
        self.btn_browser.setToolTip("软件内下载失败时，用浏览器打开 GitHub 发布页手动下载安装包 / 插件")
        self.btn_browser.setVisible(False)
        self.btn_close = QPushButton("关闭")
        row.addWidget(self.btn_check)
        row.addWidget(self.btn_download_ext)
        row.addWidget(self.btn_download_runtime)
        row.addStretch()
        row.addWidget(self.btn_browser)
        row.addWidget(self.btn_update)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self.btn_check.clicked.connect(self.start_check)
        self.btn_download_ext.clicked.connect(self.start_download_extension)
        self.btn_download_runtime.clicked.connect(self.start_download_runtime)
        self.btn_update.clicked.connect(self.start_update)
        self.btn_browser.clicked.connect(self._open_release_page)
        self.btn_close.clicked.connect(self.close)
        if auto_check:
            self.start_check()

    def _open_release_page(self):
        url = (self.info or {}).get("page_url") or RELEASES_PAGE_URL
        QDesktopServices.openUrl(QUrl(url))

    def _show_download_failed_hint(self):
        # 软件内下载失败（常见于 VPN / 代理网关超时）：露出「浏览器下载」按钮作为兜底
        self.btn_browser.setVisible(True)

    # ── 检查 ──
    def start_check(self):
        self.btn_check.setEnabled(False)
        self.btn_update.setEnabled(False)
        self.txt_notes.clear()
        self.lbl_status.setText("正在检查更新…")
        self.check_thread = CheckUpdateThread()
        self.check_thread.finished_signal.connect(self._on_checked)
        self.check_thread.start()

    def _on_checked(self, res):
        self.info = res
        self.btn_check.setEnabled(True)
        self.btn_download_ext.setEnabled(True)
        if not res["ok"]:
            self.lbl_status.setText(f"❌ {res['error']}")
            self._show_download_failed_hint()
        elif res["has_update"]:
            mb = f"（{res['size'] / 1048576:.1f} MB）" if res["size"] else ""
            self.lbl_status.setText(f"🎉 发现新版本 v{res['version']} {mb}")
            self.txt_notes.setPlainText(res["notes"] or "（无更新说明）")
            self.btn_update.setEnabled(True)
        else:
            ver_txt = res.get("version") or __version__
            self.lbl_status.setText(
                f"✅ 软件已是最新版本（v{__version__}）"
                + ("   |   💡 如需获取最新浏览器插件，请点击下方「🧩 下载最新插件」" if res.get("ext_url") else "")
                + (f"\n{res['error']}" if res["error"] else "")
            )
            if res.get("notes"):
                self.txt_notes.setPlainText(f"【当前最新插件与软件版本 v{ver_txt} 更新说明】\n\n{res['notes']}")

    # ── 下载最新插件 ──
    def _get_config_manager(self):
        mw = self.parent()
        return getattr(mw, "config_manager", None) if mw is not None else None

    def start_download_extension(self):
        ext_url = (self.info or {}).get("ext_url") or FALLBACK_EXT_URL
        ext_name = (self.info or {}).get("ext_name") or "FlowCue-Extension.7z"
        ext_size = (self.info or {}).get("ext_size") or 0

        from services.extension_sync import discover_local_extension_dirs, read_extension_version
        cm = self._get_config_manager()
        known_dirs = discover_local_extension_dirs(config_manager=cm)
        default_ext_dir = ""
        if cm and getattr(cm, "custom_extension_dir", ""):
            default_ext_dir = cm.custom_extension_dir
        elif known_dirs:
            default_ext_dir = str(known_dirs[0])

        cur_ext_hint = ""
        if default_ext_dir and Path(default_ext_dir).is_dir():
            cur_v = read_extension_version(default_ext_dir)
            cur_ext_hint = f"\n\n已检测到本地插件目录：\n{default_ext_dir}" + (f"（当前版本 v{cur_v}）" if cur_v else "")

        box = QMessageBox(self)
        box.setWindowTitle("更新 / 下载最新浏览器插件")
        box.setText(
            "请选择插件更新方式："
            f"{cur_ext_hint}\n\n"
            "• 推荐选择【📂 直接更新插件安装目录】：自动下载并解压覆盖到浏览器加载的插件文件夹，版本号立即变为最新！"
        )
        btn_dir = box.addButton("📂 直接更新插件安装目录（推荐）", QMessageBox.ButtonRole.AcceptRole)
        btn_archive = box.addButton("💾 另存为压缩包 (.7z)", QMessageBox.ButtonRole.ActionRole)
        btn_cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_dir)
        box.exec()

        clicked = box.clickedButton()
        if clicked is btn_cancel or clicked is None:
            return

        self._ext_unpack_target_dir = ""
        if clicked is btn_dir:
            start_browse = default_ext_dir if (default_ext_dir and Path(default_ext_dir).exists()) else str(Path.home() / "Desktop")
            chosen_dir = QFileDialog.getExistingDirectory(
                self,
                "选择浏览器已加载的 FlowCue 插件文件夹（将自动解压覆盖更新）",
                start_browse,
            )
            if not chosen_dir:
                return
            chosen_path = Path(chosen_dir)
            # 若用户选到了外层目录（如 D:\Antigravity\FlowCue\FlowCue 或 D:\Antigravity\FlowCue），而其下已有 FlowCue插件 子目录且外层自身没有 manifest.json，智能定位到插件子目录
            if not (chosen_path / "manifest.json").is_file():
                for sub_name in ("FlowCue插件", "extension"):
                    if (chosen_path / sub_name / "manifest.json").is_file():
                        chosen_path = chosen_path / sub_name
                        break
            self._ext_unpack_target_dir = str(chosen_path)
            if cm is not None:
                cm.custom_extension_dir = self._ext_unpack_target_dir
                cm.save()
            import tempfile
            save_path = str(Path(tempfile.gettempdir()) / f"FlowCue_Ext_Update_{os.getpid()}_{ext_name}")
        else:
            default_dir = Path.home() / "Downloads"
            if not default_dir.exists():
                default_dir = Path.home() / "Desktop"
            default_path = str(default_dir / ext_name)
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "选择最新插件压缩包保存位置",
                default_path,
                "压缩包文件 (*.7z *.zip);;所有文件 (*.*)"
            )
            if not save_path:
                return

        self.btn_download_ext.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.lbl_status.setText("正在下载最新浏览器插件…")
        self.ext_dl_thread = DownloadUpdateThread(
            ext_url, ext_name, ext_size, dest_path=save_path,
            sha256=(self.info or {}).get("ext_sha256", ""), asset_id=(self.info or {}).get("ext_asset_id", 0))
        self.ext_dl_thread.status_signal.connect(self._on_dl_status)
        self.ext_dl_thread.progress_signal.connect(self._on_ext_progress)
        self.ext_dl_thread.finished_signal.connect(self._on_ext_downloaded)
        self.ext_dl_thread.start()

    def _on_ext_progress(self, done, total):
        if total:
            self.bar.setMaximum(total)
            self.bar.setValue(done)
            self.lbl_status.setText(f"正在下载最新插件… {done / 1024:.1f} / {total / 1024:.1f} KB")
        else:
            self.bar.setMaximum(0)

    def _on_ext_downloaded(self, ok, msg):
        self.bar.setVisible(False)
        self.btn_check.setEnabled(True)
        self.btn_download_ext.setEnabled(True)
        unpack_dir = getattr(self, "_ext_unpack_target_dir", "")

        if not ok:
            # 若用户选择了直接更新本地插件目录，但 GitHub 下载超时，可用软件内置最新插件直接同步兜底！
            if unpack_dir:
                from services.extension_sync import get_bundled_extension_dir, sync_extension_files
                bundled = get_bundled_extension_dir()
                if bundled:
                    sync_ok, ver_or_err = sync_extension_files(bundled, unpack_dir, force_version=__version__)
                    if sync_ok:
                        self.lbl_status.setText(f"✅ 云端连接超时，已使用软件内置插件直接更新至 v{ver_or_err}：{unpack_dir}")
                        QMessageBox.information(
                            self,
                            "插件目录已更新",
                            f"GitHub 下载超时，已自动将本软件内置的最新插件（v{ver_or_err}）同步覆盖到：\n{unpack_dir}\n\n"
                            "📌 最后一步：\n"
                            "请打开浏览器 chrome://extensions 页面，点击 FlowCue 插件卡片右下角的 🔄「刷新」按钮，再刷新网页即可看到最新版本号！",
                        )
                        return
            self.lbl_status.setText(f"❌ 插件下载失败：{msg}")
            self._show_download_failed_hint()
            QMessageBox.warning(self, "下载失败", f"最新插件下载失败：\n{msg}\n\n可点击「🌐 浏览器下载」在 GitHub 发布页手动下载。")
            return

        if unpack_dir:
            from services.extension_sync import extract_extension_archive_to_dir
            ex_ok, ver_or_err = extract_extension_archive_to_dir(msg, unpack_dir)
            try:
                Path(msg).unlink(missing_ok=True)
            except Exception:
                pass
            if ex_ok:
                self.lbl_status.setText(f"✅ 插件目录已成功更新至 v{ver_or_err}：{unpack_dir}")
                QMessageBox.information(
                    self,
                    "插件自动更新完成",
                    f"🎉 已成功将最新插件（v{ver_or_err}）解压覆盖到：\n{unpack_dir}\n\n"
                    "软件已记住该插件路径，后续升级软件时也会自动为您同步最新版本号！\n\n"
                    "📌 最后一步：\n"
                    "请打开浏览器 chrome://extensions 页面，点击 FlowCue 插件卡片右下角的 🔄「刷新」按钮，再刷新一次 Flow / Vids 网页即可生效！",
                )
                return
            else:
                self.lbl_status.setText(f"❌ 解压更新插件目录失败：{ver_or_err}")
                QMessageBox.warning(self, "解压失败", f"插件压缩包已下载，但自动覆盖目录失败：\n{ver_or_err}")
                return

        self.lbl_status.setText(f"✅ 最新插件已下载至：{msg}")
        reply = QMessageBox.information(
            self,
            "插件下载完成",
            f"最新浏览器插件压缩包已成功下载到：\n{msg}\n\n"
            "📌 使用方法：\n"
            "1. 解压该压缩包覆盖您原来的插件文件夹（切勿新建不同目录而忘记切换浏览器加载路径）；\n"
            "2. 打开浏览器 chrome://extensions 页面，点击插件卡片右下角的 🔄 刷新按钮即可更新版本号！\n\n"
            "是否立即打开所在文件夹？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(msg)])
            except Exception:
                pass

    # ── 手动下载并安装必要插件/组件 (FFmpeg + VideoKit 批量Reels引擎) ──
    def start_download_runtime(self):
        from services.runtime_installer import (
            get_missing_runtime_components,
            get_runtime_base_dir,
            get_runtime_ffmpeg_bin_dir,
            get_runtime_videokit_dir,
            _is_valid_videokit_dir,
            RuntimeInstallDialog,
        )
        from services.ffmpeg_helper import FFmpegHelper

        missing = list(get_missing_runtime_components())
        runtime_ff_dir = get_runtime_ffmpeg_bin_dir()
        if "ffmpeg" not in missing and not ((runtime_ff_dir / "ffmpeg.exe").is_file() and (runtime_ff_dir / "ffprobe.exe").is_file()):
            missing.append("ffmpeg")
        if "videokit" not in missing and not _is_valid_videokit_dir(get_runtime_videokit_dir()):
            missing.append("videokit")

        target_components = missing
        if not target_components:
            reply = QMessageBox.question(
                self,
                "必要插件已安装",
                f"检测到当前电脑已安装全部必要运行组件：\n"
                f"• FFmpeg & FFprobe 音视频拼接引擎\n"
                f"• VideoKit 批量Reels & 素材快速审核渲染引擎\n\n"
                f"安装目录：{get_runtime_base_dir()}\n\n"
                f"是否强制重新下载并覆盖修复这两个必要组件？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            target_components = ["ffmpeg", "videokit"]

        dlg = RuntimeInstallDialog(target_components, parent=self, auto_start=True)
        if dlg.exec() == RuntimeInstallDialog.DialogCode.Accepted or dlg.install_succeeded:
            FFmpegHelper.clear_cache()
            self.lbl_status.setText(f"✅ 必要插件 (FFmpeg + 批量Reels引擎) 已成功安装至：{get_runtime_base_dir()}")
            mw = self.parent()
            if mw is not None:
                try:
                    if hasattr(mw, "batch_reels_tab") and mw.batch_reels_tab:
                        mw.batch_reels_tab.restart_engine()
                    if hasattr(mw, "visual_review_tab") and mw.visual_review_tab and mw.visual_review_tab.isVisible():
                        mw.visual_review_tab.ensure_engine_started()
                except Exception as e:
                    print(f"[UpdateDialog] restart reels engine after runtime install warning: {e}")
            QMessageBox.information(
                self,
                "必要插件安装完成",
                f"FFmpeg 与 批量Reels 渲染引擎已全部下载并安装到：\n{get_runtime_base_dir()}\n\n"
                "现在您可以直接正常使用「视频拼接」与「🎬 批量Reels / 👁️ 素材快速审核」功能！",
            )

    # ── 下载并安装软件 ──
    def start_update(self):
        if not self.info or not self.info.get("has_update"):
            return
        r = QMessageBox.question(
            self, "确认更新",
            f"将下载 v{self.info['version']} 并自动安装。\n\n安装时软件会自动关闭并在完成后重新打开。\n"
            "您的规则设置、模板预设等不会受影响。\n\n请确认当前没有正在进行的任务，是否继续？")
        if r != QMessageBox.StandardButton.Yes:
            return
        self.btn_update.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.btn_download_ext.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setValue(0)
        self.lbl_status.setText("正在下载更新…")
        self.dl_thread = DownloadUpdateThread(
            self.info["url"], self.info["name"], self.info["size"],
            sha256=self.info.get("sha256", ""), asset_id=self.info.get("asset_id", 0))
        self.dl_thread.status_signal.connect(self._on_dl_status)
        self.dl_thread.progress_signal.connect(self._on_progress)
        self.dl_thread.finished_signal.connect(self._on_downloaded)
        self.dl_thread.start()

    def _on_dl_status(self, text):
        # 显示当前下载线路 / 重试提示（进度条仍由 progress 信号驱动）
        self.lbl_status.setText(text)

    def _on_progress(self, done, total):
        if total:
            self.bar.setMaximum(total)
            self.bar.setValue(done)
            self.lbl_status.setText(f"正在下载更新… {done / 1048576:.1f} / {total / 1048576:.1f} MB（连接不稳定时会自动重试 / 续传）")
        else:
            self.bar.setMaximum(0)

    def _on_downloaded(self, ok, msg):
        if not ok:
            self.bar.setVisible(False)
            self.btn_check.setEnabled(True)
            self.btn_update.setEnabled(True)
            self.btn_download_ext.setEnabled(True)
            self.lbl_status.setText(f"❌ {msg}")
            self._show_download_failed_hint()
            return
        self.lbl_status.setText("下载完成，正在启动安装程序，软件即将自动重启…")
        try:
            launch_installer(msg)
        except Exception as e:
            self.lbl_status.setText(f"❌ 无法启动安装程序：{e}\n安装包位置：{msg}")
            self.btn_check.setEnabled(True)
            self.btn_download_ext.setEnabled(True)
            return
        QApplication.quit()

    def closeEvent(self, e):
        for t in (self.dl_thread, self.ext_dl_thread):
            if t and t.isRunning():
                t.requestInterruption()
                t.wait(2000)
        super().closeEvent(e)
