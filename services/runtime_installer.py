# -*- coding: utf-8 -*-
"""
FlowCue 运行环境一次性自动安装与管理服务 (Runtime Installer Service)

解决痛点：
1. 新用户电脑没有安装 FFmpeg / FFprobe，导致无法合并拼接视频或极速提取音频。
2. 新用户电脑没有 VideoKit Electron 运行环境，导致打不开「🎬 批量Reels」与「👁️ 素材快速审核」。
3. 开发者每次发布 FlowCue 新版本时，无需重复上传庞大的 FFmpeg 与 Electron 运行时：
   - 底层运行环境一次性托管在 GitHub 永久 Release 标签 `runtime-v1` 下：
     • `FlowCue-FFmpeg-win64.zip`
     • `FlowCue-VideoKit-Runtime-win64.zip`
   - 用户的电脑在首次打开 FlowCue 时会自动检测 `%LOCALAPPDATA%\\FlowCue\\runtime`：
     • 若未安装，自动弹窗下载并解压安装到 `%LOCALAPPDATA%\\FlowCue\\runtime`（与软件安装目录分离）；
     • 若之前已安装过（无论软件后续升级多少个版本），直接秒过，绝不重复下载安装！
"""
import os
import sys
import time
import shutil
import zipfile
import tempfile
import subprocess
from pathlib import Path
import requests

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QMessageBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

RUNTIME_RELEASE_TAG = "runtime-v1"
GITHUB_REPO = "dedeyuyu/FlowCue"

FFMPEG_ASSET_NAME = "FlowCue-FFmpeg-win64.zip"
VIDEOKIT_ASSET_NAME = "FlowCue-VideoKit-Runtime-win64.zip"

FFMPEG_DIRECT_URL = f"https://github.com/{GITHUB_REPO}/releases/download/{RUNTIME_RELEASE_TAG}/{FFMPEG_ASSET_NAME}"
VIDEOKIT_DIRECT_URL = f"https://github.com/{GITHUB_REPO}/releases/download/{RUNTIME_RELEASE_TAG}/{VIDEOKIT_ASSET_NAME}"

# 国内/海外多线路自动加速与回退列表
MIRROR_PREFIXES = [
    "",  # GitHub 官方直连
    "https://ghfast.top/",
    "https://gh-proxy.com/",
]


def _safe_is_dir(p) -> bool:
    """Safely checks if p is an existing directory, catching all OSError (e.g. WinError 87 on invalid drives)."""
    try:
        return bool(p) and os.path.isdir(str(p))
    except Exception:
        return False


def _safe_is_file(p) -> bool:
    """Safely checks if p is an existing file, catching all OSError (e.g. WinError 87 on invalid drives)."""
    try:
        return bool(p) and os.path.isfile(str(p))
    except Exception:
        return False


def get_runtime_base_dir() -> Path:
    """返回用户级永久运行时目录 (%LOCALAPPDATA%\\FlowCue\\runtime)，重装或升级软件绝不丢失"""
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    base = Path(local_appdata) / "FlowCue" / "runtime"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return base


def get_runtime_ffmpeg_bin_dir() -> Path:
    return get_runtime_base_dir() / "ffmpeg" / "bin"


def get_runtime_videokit_dir() -> Path:
    return get_runtime_base_dir() / "videokit"


def _is_valid_videokit_dir(p: Path) -> bool:
    try:
        if not p or not _safe_is_dir(p):
            return False
        electron_exe = p / "node_modules" / "electron" / "dist" / "electron.exe"
        index_html = p / "src" / "index.html"
        main_js = p / "electron" / "main.js"
        return _safe_is_file(electron_exe) and _safe_is_file(index_html) and _safe_is_file(main_js)
    except Exception:
        return False


def _iter_potential_runtime_roots() -> list[Path]:
    """返回用户电脑上所有可能存放 runtime (ffmpeg / videokit) 的根目录（兼容 Local、Roaming、软件安装目录等）"""
    roots = []
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    roaming_appdata = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")

    for base_str in (local_appdata, roaming_appdata):
        if base_str:
            b = Path(base_str)
            roots.extend([
                b / "FlowCue" / "runtime",
                b / "FlowCue",
                b / "videokit",
                b / "Programs" / "FlowCue" / "runtime",
                b / "Programs" / "FlowCue",
            ])

    if getattr(sys, "frozen", False):
        try:
            exe_dir = Path(sys.executable).resolve().parent
            roots.extend([
                exe_dir / "runtime",
                exe_dir / "vendor",
                exe_dir,
                exe_dir / "_internal" / "runtime",
                exe_dir / "_internal" / "vendor",
            ])
        except Exception:
            pass
    else:
        try:
            code_root = Path(__file__).resolve().parent.parent
            roots.extend([
                code_root / "runtime",
                code_root / "vendor",
                code_root,
                code_root.parent,
            ])
        except Exception:
            pass

    # 去重同时保持优先级顺序
    unique_roots = []
    seen = set()
    for r in roots:
        key = str(r).lower()
        if key not in seen and _safe_is_dir(r):
            seen.add(key)
            unique_roots.append(r)
    return unique_roots


def get_videokit_root() -> str:
    """
    智能解析可用的 VideoKit 运行时根目录：
    1. 环境变量 FLOWCUE_VIDEOKIT_ROOT
    2. 用户级永久运行时目录 %LOCALAPPDATA%\\FlowCue\\runtime\\videokit（以及解压产生的一层或多层嵌套子目录）
    3. %APPDATA%\\FlowCue、软件安装目录等同级或子目录
    4. 开发者本机目录（仅在安全检测存在时使用，绝不在无 D 盘的电脑上抛出 WinError 87）
    若均未安装，默认返回 %LOCALAPPDATA%\\FlowCue\\runtime\\videokit（供自动安装器落盘）。
    """
    candidates = []
    env_root = os.environ.get("FLOWCUE_VIDEOKIT_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root))

    runtime_dir = get_runtime_videokit_dir()
    candidates.append(runtime_dir)

    for root in _iter_potential_runtime_roots():
        candidates.extend([
            root / "videokit",
            root / "videokit" / "videokit",
            root / "FlowCue-VideoKit-Runtime-win64",
            root / "FlowCue-VideoKit-Runtime-win64" / "videokit",
            root / "videokit" / "FlowCue-VideoKit-Runtime-win64",
            root,
        ])
        # 自动扫描一层子目录（防止用户手动右键“解压到当前文件夹/同名文件夹”导致多嵌套一层）
        try:
            for sub in root.iterdir():
                if _safe_is_dir(sub) and ("videokit" in sub.name.lower() or "runtime" in sub.name.lower()):
                    candidates.append(sub)
                    candidates.append(sub / "videokit")
        except Exception:
            pass

    # 仅在最后安全检查开发机目录（_is_valid_videokit_dir 内部使用 _safe_is_dir 捕获一切 WinError 87）
    if not getattr(sys, "frozen", False):
        candidates.append(Path(r"D:\Antigravity\videokit"))

    seen = set()
    for c in candidates:
        key = str(c).lower()
        if key in seen:
            continue
        seen.add(key)
        if _is_valid_videokit_dir(c):
            return str(c)

    return str(runtime_dir)


def is_videokit_runtime_installed() -> bool:
    return _is_valid_videokit_dir(Path(get_videokit_root()))


def is_ffmpeg_runtime_installed() -> bool:
    from services.ffmpeg_helper import FFmpegHelper
    FFmpegHelper.clear_cache()
    return FFmpegHelper.is_available() and FFmpegHelper.is_ffprobe_available()


def sync_ffmpeg_into_videokit_vendor():
    """
    确保 VideoKit 运行时内部 vendor/windows/ffmpeg/bin 也能直接访问到已安装的 ffmpeg.exe 和 ffprobe.exe
    （优先使用硬链接节省磁盘空间，跨盘则自动复制）。
    """
    try:
        from services.ffmpeg_helper import FFmpegHelper
        ffmpeg_p = Path(FFmpegHelper.get_ffmpeg_path())
        ffprobe_p = Path(FFmpegHelper.get_ffprobe_path())
        if not _safe_is_file(ffmpeg_p) or not _safe_is_file(ffprobe_p):
            return

        vk_dir = Path(get_videokit_root())
        if not _safe_is_dir(vk_dir):
            return

        target_bin = vk_dir / "vendor" / "windows" / "ffmpeg" / "bin"
        target_bin.mkdir(parents=True, exist_ok=True)
        for src_exe in (ffmpeg_p, ffprobe_p):
            dst_exe = target_bin / src_exe.name
            if _safe_is_file(dst_exe) and dst_exe.stat().st_size == src_exe.stat().st_size:
                continue
            if _safe_is_file(dst_exe):
                try:
                    dst_exe.unlink()
                except Exception:
                    pass
            try:
                os.link(src_exe, dst_exe)
            except Exception:
                shutil.copy2(src_exe, dst_exe)
    except Exception as e:
        print(f"[RuntimeInstaller] sync_ffmpeg_into_videokit_vendor warning: {e}")


def get_missing_runtime_components() -> list[str]:
    """
    检查当前机器缺失的底层运行组件：
    返回值可能包含: 'ffmpeg', 'videokit'
    """
    missing = []
    if not is_ffmpeg_runtime_installed():
        missing.append("ffmpeg")
    if not is_videokit_runtime_installed():
        missing.append("videokit")
    else:
        sync_ffmpeg_into_videokit_vendor()
    return missing


class _RuntimeInstallWorker(QThread):
    """后台下载并解压安装缺失的运行环境组件"""
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)  # (percent 0-100, detail_text)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, components: list[str], parent=None):
        super().__init__(parent)
        self.components = list(components)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _build_candidate_urls(self, direct_url: str) -> list[str]:
        urls = []
        for prefix in MIRROR_PREFIXES:
            if not prefix:
                urls.append(direct_url)
            else:
                urls.append(f"{prefix}{direct_url}")
        return urls

    def _download_with_fallback(self, direct_url: str, dest_zip: Path, title_label: str, step_idx: int, total_steps: int) -> bool:
        # 每条线路尝试 2 次（VPN / 代理网关偶发 502 / 504 / 超时，重试一次通常即可恢复）
        candidate_urls = [u for u in self._build_candidate_urls(direct_url) for _ in range(2)]
        last_err = ""
        headers = {"User-Agent": "FlowCue-Runtime-Installer/1.0"}

        for attempt_idx, url in enumerate(candidate_urls):
            if self._cancelled:
                return False
            route_idx = attempt_idx // 2
            route_name = "GitHub 官方直连" if route_idx == 0 else f"高速镜像线路 {route_idx}"
            if attempt_idx % 2 == 1:
                time.sleep(2)
            self.status_signal.emit(f"[{step_idx}/{total_steps}] 正在连接 {route_name} 下载 {title_label}...")
            try:
                with requests.get(url, headers=headers, stream=True, timeout=(10, 30), allow_redirects=True) as resp:
                    resp.raise_for_status()
                    total_bytes = int(resp.headers.get("content-length", 0))
                    downloaded = 0
                    t0 = time.time()
                    last_ui_t = 0.0

                    with open(dest_zip, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=256 * 1024):
                            if self._cancelled:
                                return False
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            now = time.time()
                            if now - last_ui_t >= 0.12 or (total_bytes and downloaded >= total_bytes):
                                last_ui_t = now
                                elapsed = max(0.001, now - t0)
                                speed_mb = (downloaded / (1024 * 1024)) / elapsed
                                dl_mb = downloaded / (1024 * 1024)
                                if total_bytes > 0:
                                    tot_mb = total_bytes / (1024 * 1024)
                                    pct = min(90, int(downloaded * 85 / total_bytes))
                                    self.progress_signal.emit(
                                        pct,
                                        f"[{step_idx}/{total_steps}] 正在下载 {title_label} ({route_name})：{dl_mb:.1f} MB / {tot_mb:.1f} MB  ({speed_mb:.2f} MB/s)"
                                    )
                                else:
                                    self.progress_signal.emit(
                                        45,
                                        f"[{step_idx}/{total_steps}] 正在下载 {title_label} ({route_name})：已下载 {dl_mb:.1f} MB  ({speed_mb:.2f} MB/s)"
                                    )
                # 校验文件大小与 ZIP 完整性
                if dest_zip.is_file() and dest_zip.stat().st_size > 1024 * 100 and zipfile.is_zipfile(dest_zip):
                    return True
                last_err = "下载的文件不完整或非有效 ZIP 压缩包"
            except Exception as e:
                last_err = str(e)
                try:
                    if dest_zip.exists():
                        dest_zip.unlink()
                except Exception:
                    pass
                continue

        raise RuntimeError(f"下载 {title_label} 失败（已尝试全部线路）：{last_err}")

    def _extract_zip_with_progress(self, zip_path: Path, target_dir: Path, title_label: str, step_idx: int, total_steps: int):
        target_dir.mkdir(parents=True, exist_ok=True)
        self.status_signal.emit(f"[{step_idx}/{total_steps}] 正在解压安装 {title_label}...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            total_m = max(1, len(members))
            for i, member in enumerate(members):
                if self._cancelled:
                    return
                zf.extract(member, target_dir)
                if i % 25 == 0 or i == total_m - 1:
                    pct = 85 + int((i + 1) * 15 / total_m)
                    self.progress_signal.emit(
                        min(100, pct),
                        f"[{step_idx}/{total_steps}] 正在解压安装 {title_label}：{i + 1} / {total_m} 个文件"
                    )

    def run(self):
        try:
            total_steps = len(self.components)
            step_idx = 0

            for comp in self.components:
                if self._cancelled:
                    self.finished_signal.emit(False, "已取消安装")
                    return
                step_idx += 1
                self.progress_signal.emit(0, f"准备安装组件 ({step_idx}/{total_steps})...")

                if comp == "ffmpeg":
                    title = "FFmpeg 音视频合成与极速转写引擎"
                    tmp_zip = Path(tempfile.gettempdir()) / f"flowcue_ffmpeg_{os.getpid()}.zip"
                    try:
                        self._download_with_fallback(FFMPEG_DIRECT_URL, tmp_zip, title, step_idx, total_steps)
                        if self._cancelled:
                            self.finished_signal.emit(False, "已取消安装")
                            return
                        ffmpeg_root = get_runtime_base_dir() / "ffmpeg"
                        self._extract_zip_with_progress(tmp_zip, ffmpeg_root, title, step_idx, total_steps)
                    finally:
                        try:
                            if tmp_zip.exists():
                                tmp_zip.unlink()
                        except Exception:
                            pass

                elif comp == "videokit":
                    title = "批量Reels 与素材快速审核渲染引擎"
                    tmp_zip = Path(tempfile.gettempdir()) / f"flowcue_videokit_runtime_{os.getpid()}.zip"
                    try:
                        self._download_with_fallback(VIDEOKIT_DIRECT_URL, tmp_zip, title, step_idx, total_steps)
                        if self._cancelled:
                            self.finished_signal.emit(False, "已取消安装")
                            return
                        vk_root = get_runtime_videokit_dir()
                        self._extract_zip_with_progress(tmp_zip, vk_root, title, step_idx, total_steps)
                    finally:
                        try:
                            if tmp_zip.exists():
                                tmp_zip.unlink()
                        except Exception:
                            pass

            # 安装完成后清理缓存并同步 FFmpeg 到 VideoKit vendor
            from services.ffmpeg_helper import FFmpegHelper
            FFmpegHelper.clear_cache()
            sync_ffmpeg_into_videokit_vendor()

            self.progress_signal.emit(100, "✅ 所有运行环境组件已安装就绪！")
            self.finished_signal.emit(True, "")
        except Exception as e:
            self.finished_signal.emit(False, str(e))


class RuntimeInstallDialog(QDialog):
    """首次运行环境自动安装弹窗"""

    def __init__(self, missing_components: list[str], parent=None, auto_start: bool = True):
        super().__init__(parent)
        self.missing_components = list(missing_components)
        self.worker = None
        self.install_succeeded = False

        self.setWindowTitle("📦 FlowCue 运行环境自动配置（仅首次使用需安装一次）")
        self.setMinimumWidth(560)
        self.setModal(True)
        self._init_ui()

        if auto_start:
            self.start_install()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        names = []
        if "ffmpeg" in self.missing_components:
            names.append("• <b>FFmpeg 音视频引擎</b>（用于视频合并拼接、自动切气口与音频极速提取）")
        if "videokit" in self.missing_components:
            names.append("• <b>批量Reels & 素材快速审核引擎</b>（用于批量Reels字幕/覆层渲染与素材极速审核）")

        info_box = QFrame()
        info_box.setStyleSheet(
            "QFrame { background-color: #FFF8F0; border: 1px solid #E6CCB2; border-radius: 8px; padding: 10px; }"
        )
        info_layout = QVBoxLayout(info_box)
        info_layout.setContentsMargins(10, 8, 10, 8)
        info_layout.setSpacing(6)

        title_lbl = QLabel("🚀 检测到首次在此电脑使用，正在为您自动配置底层运行环境：")
        title_lbl.setStyleSheet("font-size: 14px; font-weight: bold; color: #7F4F24; border: none;")
        info_layout.addWidget(title_lbl)

        comp_lbl = QLabel("<br>".join(names))
        comp_lbl.setStyleSheet("font-size: 13px; color: #5C3D2E; border: none;")
        comp_lbl.setWordWrap(True)
        info_layout.addWidget(comp_lbl)

        note_lbl = QLabel(
            "💡 <b>说明</b>：运行环境将永久安装在您的用户目录 (<code>%LOCALAPPDATA%\\FlowCue\\runtime</code>)，"
            "<b>仅首次使用需自动安装一次</b>，后续更新 FlowCue 版本时将直接复用，无需再次下载！"
        )
        note_lbl.setStyleSheet("font-size: 12px; color: #047857; border: none;")
        note_lbl.setWordWrap(True)
        info_layout.addWidget(note_lbl)

        layout.addWidget(info_box)

        self.status_lbl = QLabel("⏳ 正在准备下载...")
        self.status_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #5D4037;")
        layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setMinimumHeight(24)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #D4A373; border-radius: 6px; text-align: center; background: #FAF3E0; font-weight: bold; color: #5D4037; }"
            "QProgressBar::chunk { background-color: #10B981; border-radius: 5px; }"
        )
        layout.addWidget(self.progress_bar)

        self.detail_lbl = QLabel("")
        self.detail_lbl.setStyleSheet("font-size: 12px; color: #6D4C41;")
        self.detail_lbl.setWordWrap(True)
        layout.addWidget(self.detail_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.btn_retry = QPushButton("🔄 重试下载")
        self.btn_retry.setStyleSheet(
            "QPushButton { background-color: #2563EB; color: white; font-weight: bold; padding: 6px 16px; border-radius: 5px; }"
            "QPushButton:hover { background-color: #1D4ED8; }"
        )
        self.btn_retry.clicked.connect(self.start_install)
        self.btn_retry.hide()
        btn_row.addWidget(self.btn_retry)

        self.btn_cancel = QPushButton("稍后安装")
        self.btn_cancel.setStyleSheet(
            "QPushButton { background-color: #E5E7EB; color: #374151; font-weight: bold; padding: 6px 16px; border-radius: 5px; }"
            "QPushButton:hover { background-color: #D1D5DB; }"
        )
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_row.addWidget(self.btn_cancel)

        layout.addLayout(btn_row)

    def start_install(self):
        if self.worker and self.worker.isRunning():
            return
        self.btn_retry.hide()
        self.btn_cancel.setText("取消")
        self.progress_bar.setValue(0)
        self.status_lbl.setText("⏳ 正在连接服务器下载运行环境...")
        self.detail_lbl.setText("")

        self.worker = _RuntimeInstallWorker(self.missing_components, parent=self)
        self.worker.status_signal.connect(self._on_status)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()

    def _on_status(self, text: str):
        self.status_lbl.setText(text)

    def _on_progress(self, pct: int, detail: str):
        self.progress_bar.setValue(pct)
        self.detail_lbl.setText(detail)

    def _on_finished(self, ok: bool, err: str):
        if ok:
            self.install_succeeded = True
            self.status_lbl.setText("✅ 运行环境自动安装完成！")
            self.detail_lbl.setText("所有组件已就绪，正在为您激活功能...")
            self.accept()
        else:
            if err == "已取消安装":
                self.reject()
                return
            self.status_lbl.setText("❌ 自动安装遇到网络问题")
            self.detail_lbl.setText(f"错误详情：{err}\n请检查网络连接后点击「🔄 重试下载」。")
            self.btn_retry.show()
            self.btn_cancel.setText("稍后安装")

    def _on_cancel_clicked(self):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(1500)
        self.reject()
