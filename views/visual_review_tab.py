# -*- coding: utf-8 -*-
"""
「👁️ 素材快速审核」完整工作台 (Visual Review Tab)
直接原封不动嵌入 VideoKit 原生「素材快速审核」工作台（100% Chromium WebCodecs/HTML5 Video 极速预览管线，秒出画面，绝不黑屏），
同时与 FlowCue 现有任务（📋 项目管理 & 🚀 批量生成）深度联动：
- 支持在顶部直接选择任意 FlowCue 任务一键载入审核，或点击「📚 载入全部任务总目录（按项目分套审核）」将所有任务按套送入左侧列表
- 100% 保留 VideoKit 原生功能：
  • 按名字分组 / 按文件夹分组
  • 组内多版本 4x 静音齐播对比、鼠标悬停倍速预览（0.5x ~ 10x，含悬停声音开关）、双击原速/大图滚轮无级缩放
  • 三态打标（✓ 合格 / △ 勉强 / ✕ 淘汰，快捷键 1 / 2 / 3）与自动持久化 `review.json`
  • 查看已选二次检查弹窗、删除淘汰、移动已选/淘汰、审核报告弹窗（含一键复制飞书/Excel TSV）、批量重命名与定额抽取导出（含智能防相邻打散）
"""
import os
import sys
import socket
import ctypes
from ctypes import wintypes
import subprocess
from pathlib import Path
import requests
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QMessageBox, QFrame, QStackedWidget
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QObject, QEvent, QSocketNotifier
from PyQt6.QtGui import QWindow


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


class _VisualReviewControlWorker(QThread):
    """后台发送 HTTP 控制指令给 reels_electron_bootstrap.js (visual-review 模式)，避免阻塞 PyQt 主线程"""
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


class VisualReviewTabWidget(QWidget):
    """
    👁️ 素材快速审核 完整工作台（直接把 VideoKit 原版「素材快速审核」100% 搬过来使用，并与 FlowCue 项目列表联动）
    """

    project_review_updated = pyqtSignal(str)
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
        self._pending_folders = []
        self._active_workers = []
        self._saved_win_style = None
        self._attached_tid = 0
        self._project_entries = []
        self._auto_loaded_initial = False

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
            print(f"[VisualReviewTab] UDP focus listener warning: {e}")

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
            print(f"[VisualReviewTab] focus_embedded_electron_hwnd warning: {e}")

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
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

        # 顶部 FlowCue <-> VideoKit 素材快速审核 联动工具栏
        top_bar = QFrame()
        top_bar.setStyleSheet(
            "QFrame { background-color: #FFFDF9; border: 1px solid #E6CCB2; border-radius: 8px; }"
        )
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 6, 10, 6)
        top_layout.setSpacing(6)

        self.status_badge = QLabel("⚪ 素材快速审核引擎待命（切换到此标签页自动启动）")
        self.status_badge.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: #7F4F24; padding: 3px 8px; "
            "background: #EDE0D4; border-radius: 4px; border: none;"
        )
        top_layout.addWidget(self.status_badge)

        top_layout.addSpacing(4)
        lbl_proj = QLabel("📋 选择FlowCue任务:")
        lbl_proj.setStyleSheet("font-size: 12px; font-weight: bold; color: #5C3D2E; border: none;")
        top_layout.addWidget(lbl_proj)

        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(260)
        self.project_combo.setStyleSheet(
            "QComboBox { padding: 4px 8px; border: 1px solid #D4A373; border-radius: 4px; background: #FFFFFF; font-size: 12px; color: #5D4037; }"
        )
        self.project_combo.activated.connect(self._on_project_combo_activated)
        top_layout.addWidget(self.project_combo)

        btn_refresh = QPushButton("🔄")
        btn_refresh.setToolTip("刷新 FlowCue 项目任务列表")
        btn_refresh.setFixedWidth(28)
        btn_refresh.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; border: 1px solid #D4A373; border-radius: 4px; padding: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        btn_refresh.clicked.connect(self.refresh_flowcue_tasks)
        top_layout.addWidget(btn_refresh)

        self.btn_load_selected = QPushButton("📥 载入选中任务素材")
        self.btn_load_selected.setToolTip("将当前下拉框选中的 FlowCue 任务文件夹载入 VideoKit 原版「素材快速审核」")
        self.btn_load_selected.setStyleSheet(
            "QPushButton { background-color: #6C5CE7; color: white; font-weight: bold; font-size: 12px; padding: 5px 10px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background-color: #5A4AD1; }"
        )
        self.btn_load_selected.clicked.connect(self._on_load_selected_project)
        top_layout.addWidget(self.btn_load_selected)

        self.btn_load_all_suites = QPushButton("📚 载入全部任务总目录 (按项目分套审核)")
        self.btn_load_all_suites.setToolTip(
            "将 FlowCue 的总存储目录一键导入 VideoKit「素材快速审核」：\n"
            "每个项目文件夹会自动识别为左侧的独立一「套」，可直接在左侧点击切换不同项目审核！"
        )
        self.btn_load_all_suites.setStyleSheet(
            "QPushButton { background-color: #0984E3; color: white; font-weight: bold; font-size: 12px; padding: 5px 10px; border-radius: 5px; border: none; }"
            "QPushButton:hover { background-color: #0770C2; }"
        )
        self.btn_load_all_suites.clicked.connect(self._on_load_all_projects_root)
        top_layout.addWidget(self.btn_load_all_suites)

        top_layout.addStretch()

        self.btn_toggle_nav = QPushButton("🧭 完整导航栏")
        self.btn_toggle_nav.setToolTip("切换纯净「素材快速审核」模式与完整 VideoKit 顶部/侧边导航栏")
        self.btn_toggle_nav.setStyleSheet(
            "QPushButton { background: #EDE0D4; color: #5C3D2E; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: 1px solid #D4A373; }"
            "QPushButton:hover { background: #E6CCB2; }"
        )
        self.btn_toggle_nav.clicked.connect(lambda: self._send_ctrl_command("toggle_header", "POST", "/toggle-header"))
        top_layout.addWidget(self.btn_toggle_nav)

        self.btn_dock_toggle = QPushButton("🗖 独立窗口弹出")
        self.btn_dock_toggle.setToolTip("将素材快速审核弹出为独立最大化窗口，或重新嵌回此标签页")
        self.btn_dock_toggle.setStyleSheet(
            "QPushButton { background: #2A9D8F; color: white; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
            "QPushButton:hover { background: #21867A; }"
        )
        self.btn_dock_toggle.clicked.connect(self._toggle_dock_mode)
        top_layout.addWidget(self.btn_dock_toggle)

        self.btn_restart = QPushButton("🔄 重启引擎")
        self.btn_restart.setToolTip("重新启动素材快速审核渲染引擎")
        self.btn_restart.setStyleSheet(
            "QPushButton { background: #E76F51; color: white; font-size: 12px; font-weight: bold; padding: 4px 10px; border-radius: 4px; border: none; }"
        )
        self.btn_restart.clicked.connect(self.restart_engine)
        top_layout.addWidget(self.btn_restart)

        layout.addWidget(top_bar)

        # 主工作区 Stack
        self.stack = QStackedWidget()
        self.placeholder_page = QWidget()
        ph_layout = QVBoxLayout(self.placeholder_page)
        ph_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.placeholder_label = QLabel(
            "👁️ 正在启动 VideoKit 原版「素材快速审核」极速引擎...\n\n"
            "包含：按名字/文件夹分组 · 组内4x静音齐播对比 · 悬停0.5x~10x倍速预览 · 双击大图滚轮无级缩放 · ✓合格/△勉强/✕淘汰打标 · 定额抽取与防相邻打散导出"
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

        self.refresh_flowcue_tasks()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_flowcue_tasks()
        if not self._is_process_alive():
            self.ensure_engine_started()
        elif self._engine_ready:
            QTimer.singleShot(150, self.focus_embedded_electron_hwnd)

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

        self.vite_port = _pick_free_port(preferred=5181)
        self.ctrl_port = _pick_free_port(preferred=5182)
        self._engine_ready = False
        self.embedded_hwnd = 0

        env = os.environ.copy()
        env["VIDEOKIT_ROOT"] = self.VIDEOKIT_ROOT
        env["VITE_PORT"] = str(self.vite_port)
        env["FLOWCUE_CTRL_PORT"] = str(self.ctrl_port)
        env["FLOWCUE_FOCUS_UDP_PORT"] = str(self.focus_udp_port)
        env["FLOWCUE_WORKBENCH_MODE"] = "visual-review"
        env.pop("ELECTRON_RUN_AS_NODE", None)

        self.status_badge.setText("⏳ 正在启动 素材快速审核 引擎...")
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
            self.status_badge.setText("🔴 素材快速审核引擎已停止")
            return

        worker = _VisualReviewControlWorker(self.ctrl_port, "poll_status", "GET", "/status", parent=self)
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
        worker = _VisualReviewControlWorker(self.ctrl_port, action, method, endpoint, payload, parent=self)
        worker.finished_signal.connect(self._on_ctrl_finished)
        self._active_workers.append(worker)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        worker.start()

    def _on_ctrl_finished(self, action: str, ok: bool, data: dict, err: str):
        if action == "poll_status":
            if ok and data.get("ready") and data.get("hwnd"):
                self._poll_timer.stop()
                self._engine_ready = True
                hwnd = int(data["hwnd"])
                if self.is_docked and hwnd != self.embedded_hwnd:
                    self._embed_hwnd(hwnd)
                self.status_badge.setText("🟢 素材快速审核已就绪 (VideoKit 原生极速预览引擎)")
                self.status_badge.setStyleSheet(
                    "font-size: 12px; font-weight: bold; color: #065F46; padding: 3px 8px; "
                    "background: #D1FAE5; border-radius: 4px; border: none;"
                )
                self._flush_pending_folders()
                # 首次启动完成后，如果没有待加载目录，默认自动把 FlowCue 总目录按套加载进去
                if not self._auto_loaded_initial:
                    self._auto_loaded_initial = True
                    base_p = self.storage_manager.get_base_path() if self.storage_manager else None
                    if base_p and os.path.isdir(str(base_p)):
                        self.load_folder_in_visual_review(str(base_p))
        elif action == "load_folder":
            if ok:
                fp = data.get("folderPath") or ""
                self.status_badge.setText(f"🟢 已载入目录: {os.path.basename(fp) or fp}")
            else:
                QMessageBox.warning(self, "载入提示", f"载入目录到素材快速审核时发生错误:\n{err}")

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
        except Exception as e:
            print(f"[VisualReviewTab] embed_hwnd error: {e}")

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
                    "🗖 「素材快速审核」当前已弹出为独立最大化窗口。\n\n"
                    "点击右上方「📥 重新嵌回标签页」可随时将其重新嵌入此标签页内。"
                )
                self.stack.setCurrentWidget(self.placeholder_page)
            except Exception as e:
                print(f"[VisualReviewTab] undock error: {e}")
        else:
            hwnd = self.embedded_hwnd
            self.embedded_hwnd = 0
            self._embed_hwnd(hwnd)

    def refresh_flowcue_tasks(self):
        """扫描所有 FlowCue 项目任务与批量生成任务，填充顶部任务下拉框"""
        cur_data = self.project_combo.currentData()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        entries = []

        if not self.storage_manager:
            main_win = self.window()
            self.storage_manager = getattr(main_win, "storage_manager", None)

        try:
            if self.storage_manager:
                for p in self.storage_manager.list_projects():
                    p_path = str(p.get("path", "") if isinstance(p, dict) else p)
                    if not p_path or not os.path.isdir(p_path):
                        continue
                    idx_str = p.get("index_str", "") if isinstance(p, dict) else ""
                    col1 = p.get("col1", "") if isinstance(p, dict) else ""
                    col7 = p.get("col7", "") if isinstance(p, dict) else ""
                    title = f"{idx_str} {col1}".strip()
                    if col7:
                        title += f" - {col7}"
                    if not title:
                        title = os.path.basename(p_path)
                    entries.append({
                        "label": f"📋 {title}",
                        "path": p_path,
                    })
        except Exception as e:
            print(f"[VisualReviewTab] refresh_flowcue_tasks warning: {e}")

        self._project_entries = entries
        if not entries:
            self.project_combo.addItem("（暂无项目任务）", "")
            self.btn_load_selected.setEnabled(False)
        else:
            restore_idx = 0
            for idx, item in enumerate(entries):
                self.project_combo.addItem(item["label"], item["path"])
                if cur_data and os.path.normcase(cur_data) == os.path.normcase(item["path"]):
                    restore_idx = idx
            self.project_combo.setCurrentIndex(restore_idx)
            self.btn_load_selected.setEnabled(True)

        self.project_combo.blockSignals(False)

    def _on_project_combo_activated(self, _index: int):
        folder_path = self.project_combo.currentData()
        if folder_path and os.path.isdir(str(folder_path)):
            self.load_folder_in_visual_review(str(folder_path))

    def _on_load_selected_project(self):
        folder_path = self.project_combo.currentData()
        if not folder_path or not os.path.isdir(str(folder_path)):
            QMessageBox.information(self, "提示", "请先选择一个有效的 FlowCue 任务。")
            return
        self.load_folder_in_visual_review(str(folder_path))

    def _on_load_all_projects_root(self):
        if not self.storage_manager:
            main_win = self.window()
            self.storage_manager = getattr(main_win, "storage_manager", None)
        base_path = self.storage_manager.get_base_path() if self.storage_manager else None
        if not base_path or not os.path.isdir(str(base_path)):
            QMessageBox.information(self, "提示", "尚未设置 FlowCue 总存储路径。")
            return
        self.load_folder_in_visual_review(str(base_path))

    def select_project_by_path(self, project_path):
        """供 MainWindow.open_in_visual_review(project_path) 调用，直接定位并加载对应项目"""
        if not project_path:
            return
        target = str(project_path)
        self.refresh_flowcue_tasks()
        for i in range(self.project_combo.count()):
            data_p = self.project_combo.itemData(i)
            if data_p and os.path.normcase(str(data_p)) == os.path.normcase(target):
                self.project_combo.setCurrentIndex(i)
                break
        self._auto_loaded_initial = True
        self.load_folder_in_visual_review(target)

    def load_folder_in_visual_review(self, folder_path: str):
        if not folder_path or not os.path.isdir(folder_path):
            return
        self._auto_loaded_initial = True
        if not self._is_process_alive():
            self._pending_folders.append(folder_path)
            self.ensure_engine_started()
            return
        if not self._engine_ready:
            self._pending_folders.append(folder_path)
            return
        self._send_ctrl_command(
            "load_folder",
            "POST",
            "/load-visual-review-folder",
            {"folder_path": folder_path}
        )

    def _flush_pending_folders(self):
        while self._pending_folders:
            fp = self._pending_folders.pop(0)
            self._send_ctrl_command(
                "load_folder",
                "POST",
                "/load-visual-review-folder",
                {"folder_path": fp}
            )

    def stop_all_video_previews(self):
        """兼容 MainWindow 切页钩子"""
        pass

    def restart_engine(self):
        self.shutdown()
        QTimer.singleShot(300, self.ensure_engine_started)

    def cleanup(self):
        self.shutdown()

    def shutdown(self):
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
