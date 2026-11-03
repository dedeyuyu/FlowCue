# -*- coding: utf-8 -*-
import os
import sys
import json
import socket
import ctypes
from ctypes import wintypes
import subprocess
from pathlib import Path
import requests
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QFrame, QStackedWidget, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QEvent, QSocketNotifier, QUrl
from PyQt6.QtGui import QWindow, QDesktopServices


def _pick_free_port(preferred: int = 0) -> int:
    if preferred > 0:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", preferred))
                return preferred
        except OSError:
            pass
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _ReelsControlWorker(QThread):
    """后台发送 HTTP 控制指令给 reels_electron_bootstrap.js，避免阻塞 PyQt 主线程"""
    finished_signal = pyqtSignal(str, bool, dict, str)

    def __init__(self, ctrl_port: int, action: str, method: str = "POST", endpoint: str = "/status", payload: dict = None, parent=None):
        super().__init__(parent)
        self.ctrl_port = ctrl_port
        self.action = action
        self.method = method.upper()
        self.endpoint = endpoint
        self.payload = payload or {}

    def run(self):
        url = f"http://127.0.0.1:{self.ctrl_port}{self.endpoint}"
        try:
            if self.method == "GET":
                resp = requests.get(url, timeout=3.0)
            else:
                resp = requests.post(url, json=self.payload, timeout=30.0)
            data = resp.json() if resp.content else {}
            ok = resp.status_code == 200 and data.get("ok", False)
            self.finished_signal.emit(self.action, ok, data, "" if ok else data.get("error", f"HTTP {resp.status_code}"))
        except Exception as e:
            self.finished_signal.emit(self.action, False, {}, str(e))


class BatchReelsTabWidget(QWidget):
    """
    🎬 批量Reels 完整工作台（零删减集成 VideoKit 批量Reels 全部功能，并与 FlowCue 深度联动）：
    - 80+ 字幕样式参数、18+ 逐字/逐词动画预设、字体管理与 Google Fonts
    - 6 类媒体卡片/覆层（文字卡片 textcard、纯色蒙版 solid_mask、贴纸图片 image、画中画视频 video、自由文本 text、滚动字幕 scroll）
    - B-Roll 插入素材轨 (insertClips)、可视化多轨时间线编辑器、预设/模板管理、多模板矩阵导出、WYSIWYG/硬件加速导出
    - 支持单条或批量从 FlowCue「🎬 视频与文案比对」导入已合并拼接的成片 + SRT + 逐词精确时间轴
    """

    VIDEOKIT_ROOT = r"D:\Antigravity\videokit"

    def __init__(self, storage_manager=None, config_manager=None, parent=None):
        super().__init__(parent)
        self.storage_manager = storage_manager
        self.config_manager = config_manager
        self.electron_proc = None
        self.vite_port = 0
        self.ctrl_port = 0
        self.focus_udp_port = 0
        self._focus_udp_sock = None
        self._focus_notifier = None
        self.embedded_hwnd = 0
        self.embedded_qwindow = None
        self.embedded_container = None
        self.is_docked = True
        self._engine_ready = False
        self._pending_tasks = []
        self._pending_batch_tasks = []
        self._active_workers = []
        self._saved_win_style = None
        self._attached_tid = 0
        self._found_found_items = []

        self._setup_focus_udp_listener()
        self._init_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(450)
        self._poll_timer.timeout.connect(self._poll_engine_status)

        app = QApplication.instance()
        if app:
            app.installEventFilter(self)

    def _setup_focus_udp_listener(self):
        """建立毫秒级本地 UDP 通道，当用户在嵌入的 Electron 内点击输入框时，立即切换 Win32 键盘焦点到 Chromium"""
        try:
            self._focus_udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._focus_udp_sock.bind(("127.0.0.1", 0))
            self._focus_udp_sock.setblocking(False)
            self.focus_udp_port = int(self._focus_udp_sock.getsockname()[1])
            self._focus_notifier = QSocketNotifier(
                self._focus_udp_sock.fileno(),
                QSocketNotifier.Type.Read,
                self
            )
            self._focus_notifier.activated.connect(self._on_focus_udp_packet)
        except Exception as e:
            print(f"[BatchReelsTab] UDP focus listener warning: {e}")

    def _on_focus_udp_packet(self):
        if not self._focus_udp_sock:
            return
        try:
            while True:
                data, _ = self._focus_udp_sock.recvfrom(64)
                if not data:
                    break
        except BlockingIOError:
            pass
        except Exception:
            pass
        self.focus_embedded_electron_hwnd()

    def _find_chromium_render_hwnd(self, parent_hwnd: int) -> int:
        """枚举 Electron BrowserWindow 下的子窗口，定位真正接收键盘输入的 Chrome_RenderWidgetHostHWND"""
        if not parent_hwnd or sys.platform != "win32":
            return parent_hwnd
        user32 = ctypes.windll.user32
        found = [0]
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd, _lparam):
            buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, buf, 128)
            cls_name = buf.value or ""
            if "Chrome_RenderWidgetHostHWND" in cls_name:
                found[0] = int(hwnd)
                return False
            if found[0] == 0 and "Intermediate D3D Window" not in cls_name:
                found[0] = int(hwnd)
            return True

        try:
            user32.EnumChildWindows(wintypes.HWND(parent_hwnd), WNDENUMPROC(_enum_cb), 0)
        except Exception:
            pass
        return found[0] if found[0] else parent_hwnd

    def focus_embedded_electron_hwnd(self):
        """将 Win32 键盘焦点赋予嵌入式的 Electron Chromium 渲染窗口（解决有竖杠但无法打字/Ctrl+V的问题）"""
        if sys.platform != "win32" or not self.embedded_hwnd or not self.is_docked:
            return
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            qt_tid = kernel32.GetCurrentThreadId()
            elec_tid = user32.GetWindowThreadProcessId(wintypes.HWND(self.embedded_hwnd), None)
            if elec_tid and elec_tid != qt_tid:
                user32.AttachThreadInput(elec_tid, qt_tid, True)
                user32.AttachThreadInput(qt_tid, elec_tid, True)
                self._attached_tid = elec_tid

            target_hwnd = self._find_chromium_render_hwnd(self.embedded_hwnd)
            if target_hwnd and elec_tid and elec_tid != qt_tid:
                child_tid = user32.GetWindowThreadProcessId(wintypes.HWND(target_hwnd), None)
                if child_tid and child_tid != qt_tid:
                    user32.AttachThreadInput(child_tid, qt_tid, True)
                    user32.AttachThreadInput(qt_tid, child_tid, True)

            user32.SetFocus(wintypes.HWND(target_hwnd or self.embedded_hwnd))
        except Exception as e:
            print(f"[BatchReelsTab] focus_embedded_electron_hwnd warning: {e}")

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """当用户点击 FlowCue 自身界面（非嵌入的 Electron 容器）时，将 Win32 键盘焦点归还给 PyQt 主窗口"""
        if event.type() == QEvent.Type.MouseButtonPress and sys.platform == "win32":
            if self.embedded_hwnd and self.is_docked and isinstance(obj, QWidget):
                if self.embedded_container is not None:
                    if obj is self.embedded_container or self.embedded_container.isAncestorOf(obj):
                        QTimer.singleShot(10, self.focus_embedded_electron_hwnd)
                        return super().eventFilter(obj, event)
                try:
                    top_win = self.window()
                    if top_win and top_win.isAncestorOf(obj):
                        user32 = ctypes.windll.user32
                        user32.SetFocus(wintypes.HWND(int(top_win.winId())))
                except Exception:
                    pass
        return super().eventFilter(obj, event)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # 顶部 FlowCue <-> 批量Reels 联动工具栏
        top_bar = QFrame()
        top_bar.setStyleSheet(
            "QFrame { background-color: #FFFDF9; border: 1px solid #E6CCB2; border-radius: 8px; }"
        )
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 6, 10, 6)
        top_layout.setSpacing(6)

        self.status_badge = QLabel("⚪ 批量Reels 引擎待命（切换到此标签页自动启动）")
        self.status_badge.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #7F4F24; padding: 3px 8px; "
            "background: #EDE0D4; border-radius: 4px; border: none;"
        )
        top_layout.addWidget(self.status_badge)

        top_layout.addSpacing(4)
        lbl_import = QLabel("🔗 已合并成片:")
        lbl_import.setStyleSheet("font-size: 12px; font-weight: bold; color: #5C3D2E; border: none;")
        top_layout.addWidget(lbl_import)

        self.merged_project_combo = QComboBox()
        self.merged_project_combo.setMinimumWidth(220)
        self.merged_project_combo.setStyleSheet(
            "QComboBox { padding: 4px 8px; border: 1px solid #D4A373; border-radius: 4px; background: #FFFFFF; font-size: 12px; color: #5D4037; }"
        )
        top_layout.addWidget(self.merged_project_combo)

        btn_refresh_projects = QPushButton("🔄")
        btn_refresh_projects.setToolTip("刷新 FlowCue 中已生成合并成片的项目列表")
        btn_refresh_projects.setFixedWidth(28)
        btn_refresh_projects.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; border: 1px solid #D4A373; border-radius: 4px; padding: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        btn_refresh_projects.clicked.connect(self.refresh_merged_projects_list)
        top_layout.addWidget(btn_refresh_projects)

        self.btn_import_merged = QPushButton("📥 导入选中成片")
        self.btn_import_merged.setToolTip("将下拉框选中的 FlowCue 成片 (.mp4) + 字幕 (.srt) + 逐词时间轴加入批量Reels")
        self.btn_import_merged.setStyleSheet(
            "QPushButton { background-color: #6C5CE7; color: white; font-weight: bold; font-size: 12px; padding: 5px 10px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background-color: #5A4AD1; }"
        )
        self.btn_import_merged.clicked.connect(self._on_import_selected_merged_project)
        top_layout.addWidget(self.btn_import_merged)

        self.btn_import_all_merged = QPushButton("📚 导入全部已合成片")
        self.btn_import_all_merged.setToolTip("将下拉列表中所有已合成的成片一键全部送入批量Reels")
        self.btn_import_all_merged.setStyleSheet(
            "QPushButton { background-color: #0984E3; color: white; font-weight: bold; font-size: 12px; padding: 5px 10px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background-color: #0770C2; }"
        )
        self.btn_import_all_merged.clicked.connect(self._on_import_all_merged_projects)
        top_layout.addWidget(self.btn_import_all_merged)

        # 导出自动调速开关（不超过3分钟 / ≤2分58秒，SRT同步）
        self.chk_limit_3min = QCheckBox("⏱️ 自动调速/不超过3分钟 (≤2分58秒，SRT字幕同步)")
        self.chk_limit_3min.setChecked(True)
        self.chk_limit_3min.setToolTip(
            "勾选后：\n"
            "• 若成片时长 ≤ 2分58秒 (178秒)：保持 1.0x 原速导出；\n"
            "• 若成片时长 > 2分58秒：导出前自动计算倍速将视频压缩至 ≤2分58秒（如 2分57.5秒），\n"
            "  且所有核对好的 SRT 字幕与逐词卡拉OK时间轴也会按完全相同的倍率同步加速，绝不串行！"
        )
        self.chk_limit_3min.setStyleSheet(
            "QCheckBox { font-size: 12px; font-weight: bold; color: #047857; background: #ECFDF5; "
            "border: 1px solid #10B981; border-radius: 5px; padding: 4px 10px; }"
            "QCheckBox:hover { background: #D1FAE5; }"
        )
        self.chk_limit_3min.toggled.connect(self._on_toggle_limit_3min)
        top_layout.addWidget(self.chk_limit_3min)

        top_layout.addStretch()

        self.btn_preset_dir = QPushButton("📂 预设存放目录")
        self.btn_preset_dir.setToolTip(
            "查看字幕预设与覆层预设的永久存放目录（自动双备份，软件更新绝不丢失）：\n"
            "• 主目录: %APPDATA%\\videokit\\videokit-presets\\local-storage-presets.json\n"
            "• 自动备份: %APPDATA%\\FlowCue\\reels-presets-backup\\local-storage-presets.json"
        )
        self.btn_preset_dir.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #D4A373; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        self.btn_preset_dir.clicked.connect(self._open_presets_directory)
        top_layout.addWidget(self.btn_preset_dir)

        self.btn_fit_canvas = QPushButton("📐 适应画布")
        self.btn_fit_canvas.setToolTip("让 9:16 预览画布自动居中适应当前窗口大小")
        self.btn_fit_canvas.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #D4A373; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        self.btn_fit_canvas.clicked.connect(lambda: self._send_ctrl_command("fit", "POST", "/fit-preview"))
        top_layout.addWidget(self.btn_fit_canvas)

        self.btn_toggle_nav = QPushButton("🧭 完整导航栏")
        self.btn_toggle_nav.setToolTip("切换纯净「批量Reels」模式与完整 VideoKit 顶部标签栏（含设置、TTS、SRT工具等）")
        self.btn_toggle_nav.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #D4A373; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        self.btn_toggle_nav.clicked.connect(lambda: self._send_ctrl_command("toggle_header", "POST", "/toggle-header"))
        top_layout.addWidget(self.btn_toggle_nav)

        self.btn_dock_toggle = QPushButton("🗖 独立窗口弹出")
        self.btn_dock_toggle.setToolTip("将批量Reels弹出为独立大窗口（适合双屏精调字幕与时间线），或重新嵌回此标签页")
        self.btn_dock_toggle.setStyleSheet(
            "QPushButton { background: #2A9D8F; color: white; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #21867A; }"
        )
        self.btn_dock_toggle.clicked.connect(self._toggle_dock_mode)
        top_layout.addWidget(self.btn_dock_toggle)

        self.btn_restart = QPushButton("🔄 重启引擎")
        self.btn_restart.setToolTip("重新启动批量Reels渲染引擎")
        self.btn_restart.setStyleSheet(
            "QPushButton { background: #E76F51; color: white; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #D65A3F; }"
        )
        self.btn_restart.clicked.connect(self.restart_engine)
        top_layout.addWidget(self.btn_restart)

        layout.addWidget(top_bar)

        # 主工作区 Stack（加载中提示页 vs 嵌入式原生窗口容器）
        self.stack = QStackedWidget()
        self.placeholder_page = QWidget()
        ph_layout = QVBoxLayout(self.placeholder_page)
        ph_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.placeholder_label = QLabel(
            "🎬 正在启动「批量Reels」全功能渲染引擎...\n\n"
            "包含：80+ 动态字幕样式与预设 · 18+ 逐词/逐字动画 · 6大类媒体卡片与覆层 · B-Roll 插入素材轨 · 多轨时间线精修 · 硬件加速/WYSIWYG导出"
        )
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; color: #7F4F24; background: #FFF8F0; "
            "border: 2px dashed #D4A373; border-radius: 12px; padding: 40px;"
        )
        ph_layout.addWidget(self.placeholder_label)

        self.host_page = QWidget()
        self.host_layout = QVBoxLayout(self.host_page)
        self.host_layout.setContentsMargins(0, 0, 0, 0)
        self.host_layout.setSpacing(0)

        self.stack.addWidget(self.placeholder_page)
        self.stack.addWidget(self.host_page)
        layout.addWidget(self.stack, 1)

        self.refresh_merged_projects_list()

    def _open_presets_directory(self):
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        primary_dir = Path(appdata) / "videokit" / "videokit-presets"
        backup_dir = Path(appdata) / "FlowCue" / "reels-presets-backup"
        templates_dir = Path(appdata) / "videokit" / "videokit-templates"
        primary_dir.mkdir(parents=True, exist_ok=True)
        backup_dir.mkdir(parents=True, exist_ok=True)

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(primary_dir)))
        QMessageBox.information(
            self,
            "📂 字幕与覆层预设永久保存位置",
            f"您的【字幕预设】与【覆层预设】保存在系统 AppData 独立目录中（与软件安装目录完全分离，更新或重装软件绝不会丢失）：\n\n"
            f"1️⃣ 主预设目录（已为您打开）：\n{primary_dir}\\local-storage-presets.json\n\n"
            f"2️⃣ FlowCue 自动双保险备份目录：\n{backup_dir}\\local-storage-presets.json\n\n"
            f"3️⃣ 项目模板目录：\n{templates_dir}\n\n"
            f"💡 每次启动和保存预设时，系统都会自动将字幕预设与覆层预设同步备份到上述两个目录！"
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_merged_projects_list()
        if not self._is_process_alive():
            self.ensure_engine_started()
        elif self._engine_ready:
            QTimer.singleShot(150, lambda: self._send_ctrl_command("fit", "POST", "/fit-preview"))
            QTimer.singleShot(200, self.focus_embedded_electron_hwnd)

    def _is_process_alive(self) -> bool:
        return self.electron_proc is not None and self.electron_proc.poll() is None

    def _get_electron_exe(self) -> str:
        candidates = [
            os.path.join(self.VIDEOKIT_ROOT, "node_modules", "electron", "dist", "electron.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c
        return ""

    def _get_bootstrap_script(self) -> str:
        candidates = []
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, "services", "reels_electron_bootstrap.js"))
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidates.append(os.path.join(base_dir, "services", "reels_electron_bootstrap.js"))
        candidates.append(r"D:\Antigravity\FlowCue\Flow口播工具\services\reels_electron_bootstrap.js")
        for c in candidates:
            if os.path.isfile(c):
                return c
        return candidates[-1]

    def ensure_engine_started(self):
        if self._is_process_alive():
            return

        electron_exe = self._get_electron_exe()
        bootstrap_js = self._get_bootstrap_script()

        if not electron_exe or not os.path.isfile(electron_exe):
            self.status_badge.setText("❌ 未找到 VideoKit Electron 运行时")
            self.placeholder_label.setText(
                f"⚠️ 未找到 Electron 可执行文件:\n{os.path.join(self.VIDEOKIT_ROOT, 'node_modules', 'electron', 'dist', 'electron.exe')}"
            )
            return

        if not os.path.isfile(bootstrap_js):
            self.status_badge.setText("❌ 未找到 reels_electron_bootstrap.js")
            return

        # 优先使用固定端口 5179，确保 localStorage 的 Origin (http://localhost:5179) 永久固定
        self.vite_port = _pick_free_port(preferred=5179)
        self.ctrl_port = _pick_free_port(preferred=5180)
        self._engine_ready = False
        self.embedded_hwnd = 0

        env = os.environ.copy()
        env["VIDEOKIT_ROOT"] = self.VIDEOKIT_ROOT
        env["VITE_PORT"] = str(self.vite_port)
        env["FLOWCUE_CTRL_PORT"] = str(self.ctrl_port)
        env["FLOWCUE_FOCUS_UDP_PORT"] = str(self.focus_udp_port)
        env.pop("ELECTRON_RUN_AS_NODE", None)

        self.status_badge.setText("⏳ 正在启动 批量Reels 渲染引擎...")
        self.status_badge.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #B45309; padding: 3px 8px; "
            "background: #FEF3C7; border-radius: 4px; border: none;"
        )
        self.stack.setCurrentWidget(self.placeholder_page)

        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            self.electron_proc = subprocess.Popen(
                [electron_exe, bootstrap_js],
                cwd=self.VIDEOKIT_ROOT,
                env=env,
                creationflags=creationflags,
            )
            self._poll_timer.start()
        except Exception as e:
            self.status_badge.setText(f"❌ 启动失败: {e}")

    def _poll_engine_status(self):
        if not self._is_process_alive():
            self._poll_timer.stop()
            self.status_badge.setText("🔴 批量Reels 引擎已停止")
            return

        worker = _ReelsControlWorker(self.ctrl_port, "poll_status", "GET", "/status", parent=self)
        worker.finished_signal.connect(self._on_ctrl_finished)
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _cleanup_worker(self, w):
        if w in self._active_workers:
            self._active_workers.remove(w)

    def _send_ctrl_command(self, action: str, method: str, endpoint: str, payload: dict = None):
        if not self._is_process_alive() or not self.ctrl_port:
            return
        worker = _ReelsControlWorker(self.ctrl_port, action, method, endpoint, payload, parent=self)
        worker.finished_signal.connect(self._on_ctrl_finished)
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _on_toggle_limit_3min(self, checked: bool):
        self._send_ctrl_command("set_limit_3min", "POST", "/set-limit-under-3min", {"checked": bool(checked)})

    def _on_ctrl_finished(self, action: str, ok: bool, data: dict, err: str):
        if action == "poll_status":
            if ok and data.get("ready") and data.get("hwnd"):
                self._poll_timer.stop()
                self._engine_ready = True
                hwnd = int(data["hwnd"])
                if self.is_docked and hwnd != self.embedded_hwnd:
                    self._embed_hwnd(hwnd)
                if "limitUnder3Min" in data:
                    self.chk_limit_3min.blockSignals(True)
                    self.chk_limit_3min.setChecked(bool(data["limitUnder3Min"]))
                    self.chk_limit_3min.blockSignals(False)
                self._on_toggle_limit_3min(self.chk_limit_3min.isChecked())
                self.status_badge.setText("🟢 批量Reels 引擎已就绪 (100% 原生画布 + FFmpeg/GPU 管线)")
                self.status_badge.setStyleSheet(
                    "font-size: 12px; font-weight: bold; color: #065F46; padding: 3px 8px; "
                    "background: #D1FAE5; border-radius: 4px; border: none;"
                )
                self._sync_flowcue_api_keys()
                self._flush_pending_tasks()
        elif action == "load_task":
            if ok:
                file_name = data.get("fileName") or "成片"
                seg_count = data.get("segmentCount", 0)
                self.status_badge.setText(f"🟢 已载入任务: {file_name} ({seg_count} 句字幕)")
            else:
                QMessageBox.warning(self, "导入提示", f"导入任务到批量Reels时发生错误:\n{err}")
        elif action == "load_tasks_batch":
            if ok:
                cnt = data.get("count", 0)
                total = data.get("totalTasks", cnt)
                self.status_badge.setText(f"🟢 已批量载入 {cnt} 个成片任务 (当前队列共 {total} 个任务)")
            else:
                QMessageBox.warning(self, "批量导入提示", f"批量导入任务到批量Reels时发生错误:\n{err}")

    def _embed_hwnd(self, hwnd: int):
        if not hwnd:
            return
        try:
            if sys.platform == "win32":
                user32 = ctypes.windll.user32
                GWL_STYLE = -16
                WS_CAPTION = 0x00C00000
                WS_THICKFRAME = 0x00040000
                WS_MINIMIZEBOX = 0x00020000
                WS_MAXIMIZEBOX = 0x00010000
                WS_SYSMENU = 0x00080000
                cur_style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                if self._saved_win_style is None:
                    self._saved_win_style = cur_style
                new_style = cur_style & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU)
                user32.SetWindowLongW(hwnd, GWL_STYLE, new_style)

            if self.embedded_container is not None:
                self.host_layout.removeWidget(self.embedded_container)
                self.embedded_container.deleteLater()
                self.embedded_container = None

            self.embedded_hwnd = hwnd
            self.embedded_qwindow = QWindow.fromWinId(hwnd)
            self.embedded_container = QWidget.createWindowContainer(
                self.embedded_qwindow,
                self.host_page,
                Qt.WindowType.Widget
            )
            self.embedded_container.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.host_layout.addWidget(self.embedded_container)
            self.stack.setCurrentWidget(self.host_page)
            self.is_docked = True
            self.btn_dock_toggle.setText("🗖 独立窗口弹出")
            QTimer.singleShot(200, self.focus_embedded_electron_hwnd)
            QTimer.singleShot(250, lambda: self._send_ctrl_command("fit", "POST", "/fit-preview"))
        except Exception as e:
            print(f"[BatchReelsTab] embed_hwnd error: {e}")

    def _toggle_dock_mode(self):
        if not self._engine_ready or not self.embedded_hwnd:
            return
        if self.is_docked:
            try:
                if self.embedded_container is not None:
                    self.host_layout.removeWidget(self.embedded_container)
                    self.embedded_container.setParent(None)
                    self.embedded_container.deleteLater()
                    self.embedded_container = None
                self.embedded_qwindow = None

                if sys.platform == "win32":
                    user32 = ctypes.windll.user32
                    GWL_STYLE = -16
                    WS_OVERLAPPEDWINDOW = 0x00CF0000
                    WS_VISIBLE = 0x10000000
                    user32.SetParent(self.embedded_hwnd, 0)
                    restore_style = (self._saved_win_style or WS_OVERLAPPEDWINDOW) | WS_OVERLAPPEDWINDOW | WS_VISIBLE
                    user32.SetWindowLongW(self.embedded_hwnd, GWL_STYLE, restore_style)
                    user32.ShowWindow(self.embedded_hwnd, 3)  # SW_MAXIMIZE
                    user32.SetForegroundWindow(self.embedded_hwnd)

                self.is_docked = False
                self.btn_dock_toggle.setText("📥 重新嵌回标签页")
                self.placeholder_label.setText(
                    "🗖 「批量Reels」当前已弹出为独立最大化窗口。\n\n"
                    "点击右上方「📥 重新嵌回标签页」可随时将其重新嵌入此标签页内。"
                )
                self.stack.setCurrentWidget(self.placeholder_page)
                QTimer.singleShot(250, lambda: self._send_ctrl_command("fit", "POST", "/fit-preview"))
            except Exception as e:
                print(f"[BatchReelsTab] undock error: {e}")
        else:
            hwnd = self.embedded_hwnd
            self.embedded_hwnd = 0
            self._embed_hwnd(hwnd)

    def _sync_flowcue_api_keys(self):
        try:
            cfg = self.config_manager
            if not cfg:
                main_win = self.window()
                cfg = getattr(main_win, "config_manager", None)
            if cfg and getattr(cfg, "gladia_keys", None):
                keys = [k.strip() for k in cfg.gladia_keys if k and k.strip()]
                if keys:
                    self._send_ctrl_command("sync_keys", "POST", "/sync-keys", {"gladia_keys": keys})
        except Exception:
            pass

    def refresh_merged_projects_list(self):
        """扫描所有已生成合并成片 (<project>_成片.mp4) 的 FlowCue 项目"""
        self.merged_project_combo.clear()
        found_items = []

        if not self.storage_manager:
            main_win = self.window()
            self.storage_manager = getattr(main_win, "storage_manager", None)

        def _check_folder(title: str, folder: str, tag: str):
            if not folder or not os.path.isdir(folder):
                return
            merged_dir = os.path.join(folder, "merged_output")
            if not os.path.isdir(merged_dir):
                return
            for fname in sorted(os.listdir(merged_dir)):
                if fname.lower().endswith("_成片.mp4") or fname.lower().endswith(".mp4"):
                    v_path = os.path.join(merged_dir, fname)
                    base_stem = os.path.splitext(fname)[0]
                    srt_path = os.path.join(merged_dir, f"{base_stem}.srt")
                    if not os.path.isfile(srt_path):
                        continue
                    proj_name = base_stem.replace("_成片", "")
                    # 兼容 <base_stem>-工程 与 <proj_name>-工程 两种目录命名
                    cand_manifests = [
                        os.path.join(merged_dir, f"{base_stem}-工程", "处理片段", "处理片段清单.json"),
                        os.path.join(merged_dir, f"{proj_name}-工程", "处理片段", "处理片段清单.json"),
                    ]
                    manifest_path = ""
                    for cm in cand_manifests:
                        if os.path.isfile(cm):
                            manifest_path = cm
                            break

                    segments = []
                    merged_words = []
                    duration = 0.0
                    if manifest_path:
                        try:
                            with open(manifest_path, "r", encoding="utf-8") as f:
                                m_data = json.load(f)
                            duration = float(m_data.get("total_duration") or m_data.get("output_duration") or 0.0)
                            segments = m_data.get("clips", [])
                            merged_words = m_data.get("merged_words", [])
                        except Exception:
                            pass
                    found_items.append({
                        "label": f"[{tag}] {title} ({fname})",
                        "project_name": proj_name,
                        "video_path": v_path,
                        "srt_path": srt_path,
                        "manifest_path": manifest_path,
                        "output_dir": merged_dir,
                        "duration": duration,
                        "segments": segments,
                        "words": merged_words,
                    })

        try:
            if self.storage_manager:
                for p in self.storage_manager.list_projects():
                    p_path = p.get("path", "") if isinstance(p, dict) else str(p)
                    p_id = p.get("id", os.path.basename(p_path)) if isinstance(p, dict) else os.path.basename(p_path)
                    _check_folder(p_id, p_path, "项目")
        except Exception:
            pass

        self._found_found_items = found_items
        if not found_items:
            self.merged_project_combo.addItem("（暂无已合并成片 — 请先在「视频与文案比对」中点击合并拼接）", None)
            self.btn_import_merged.setEnabled(False)
            self.btn_import_all_merged.setEnabled(False)
        else:
            for item in found_items:
                self.merged_project_combo.addItem(item["label"], item)
            self.btn_import_merged.setEnabled(True)
            self.btn_import_all_merged.setEnabled(True)

    def _on_import_selected_merged_project(self):
        payload = self.merged_project_combo.currentData()
        if not payload or not isinstance(payload, dict):
            QMessageBox.information(self, "提示", "请先在「🎬 视频与文案比对」中点击「🎬 一键合并拼接成片 (+SRT)」生成成片。")
            return
        self.load_flowcue_merged_task(payload)

    def _on_import_all_merged_projects(self):
        if not self._found_found_items:
            QMessageBox.information(self, "提示", "暂无已合成的成片项目。")
            return
        self.load_flowcue_merged_tasks_batch(self._found_found_items)

    def load_flowcue_merged_task(self, payload: dict):
        """确保引擎启动并将单条成片 + SRT + 逐词时间轴直接推入批量Reels。"""
        if not payload:
            return
        self.refresh_merged_projects_list()
        if not self._is_process_alive():
            self._pending_tasks.append(payload)
            self.ensure_engine_started()
            return
        if not self._engine_ready:
            self._pending_tasks.append(payload)
            return
        self._send_ctrl_command("load_task", "POST", "/load-task", payload)

    def load_flowcue_merged_tasks_batch(self, payloads: list):
        """确保引擎启动并将多条成片 + SRT + 逐词时间轴一次性批量推入批量Reels。"""
        valid = [p for p in (payloads or []) if isinstance(p, dict) and p.get("video_path")]
        if not valid:
            return
        self.refresh_merged_projects_list()
        if not self._is_process_alive():
            self._pending_batch_tasks.extend(valid)
            self.ensure_engine_started()
            return
        if not self._engine_ready:
            self._pending_batch_tasks.extend(valid)
            return
        self._send_ctrl_command("load_tasks_batch", "POST", "/load-tasks-batch", {"tasks": valid})

    def _flush_pending_tasks(self):
        if self._pending_batch_tasks:
            batch_items = list(self._pending_batch_tasks)
            self._pending_batch_tasks.clear()
            self._send_ctrl_command("load_tasks_batch", "POST", "/load-tasks-batch", {"tasks": batch_items})
        while self._pending_tasks:
            task_payload = self._pending_tasks.pop(0)
            self._send_ctrl_command("load_task", "POST", "/load-task", task_payload)

    def restart_engine(self):
        self.shutdown()
        QTimer.singleShot(300, self.ensure_engine_started)

    def shutdown(self):
        """在 FlowCue 关闭或重启引擎时安全清理 Electron 子进程"""
        self._poll_timer.stop()
        if self.embedded_container is not None:
            try:
                self.host_layout.removeWidget(self.embedded_container)
                self.embedded_container.setParent(None)
                self.embedded_container.deleteLater()
            except Exception:
                pass
            self.embedded_container = None
        self.embedded_qwindow = None
        self.embedded_hwnd = 0
        self._engine_ready = False

        if self.electron_proc is not None:
            try:
                if self.electron_proc.poll() is None:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(self.electron_proc.pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                    else:
                        self.electron_proc.terminate()
            except Exception:
                pass
            self.electron_proc = None
