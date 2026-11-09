# -*- coding: utf-8 -*-
"""
在线检查更新 / 一键下载安装。

- 通过 GitHub Releases 公共 API 获取最新版本（无需 token）
- 下载 FlowCue-Setup-x.y.z.exe 到临时目录，校验大小与来源域名
- 以 /SILENT 方式启动安装包：安装程序会自动关闭本程序、覆盖安装并重新启动；
  用户设置保存在 %APPDATA%，不受影响。
"""
import os
import re
import sys
import time
import hashlib
import tempfile
import subprocess
from urllib.parse import urlparse

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from version import __version__, GITHUB_REPO

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
FALLBACK_EXT_URL = f"https://github.com/{GITHUB_REPO}/releases/latest/download/FlowCue-Extension.7z"
ALLOWED_DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com",
                          "release-assets.githubusercontent.com", "api.github.com")
# 备用下载线路（国内 / VPN 环境下 GitHub 官方地址经常 504 / 超时）。
# 安全：镜像线路只在「发布页提供了 SHA-256」时才启用，下载完成后必须校验通过才会使用/安装，
# 因此即使镜像被篡改也无法让用户运行被替换的安装包。
MIRROR_PREFIXES = ("https://ghfast.top/", "https://gh-proxy.com/")
RETRIES_PER_ROUTE = 3
SETUP_RE = re.compile(r"^FlowCue-Setup-.*\.exe$", re.IGNORECASE)
EXT_RE = re.compile(r"^FlowCue-Extension.*\.(7z|zip)$", re.IGNORECASE)


def parse_version(v):
    """'v1.2.3' -> (1, 2, 3)；无法解析的部分按 0 处理。"""
    nums = re.findall(r"\d+", str(v or ""))
    t = tuple(int(n) for n in nums[:4])
    return t + (0,) * (3 - len(t)) if len(t) < 3 else t


def is_newer(remote, local=__version__):
    return parse_version(remote) > parse_version(local)


def _host_allowed(url):
    try:
        u = urlparse(url)
        host = (u.hostname or "").lower()
        return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in ALLOWED_DOWNLOAD_HOSTS)
    except Exception:
        return False


def _digest_sha256(asset):
    """GitHub 资源的 digest 形如 'sha256:abcd...'；没有则返回空串。"""
    d = str(asset.get("digest") or "")
    if d.lower().startswith("sha256:"):
        h = d.split(":", 1)[1].strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", h):
            return h
    return ""


class CheckUpdateThread(QThread):
    """结果: finished_signal(dict) —— {ok, error, has_update, version, notes, url, size, name, sha256, asset_id,
    ext_url, ext_size, ext_name, ext_sha256, ext_asset_id, page_url}"""
    finished_signal = pyqtSignal(dict)

    def run(self):
        res = {"ok": False, "error": "", "has_update": False, "version": "", "notes": "",
               "url": "", "size": 0, "name": "", "sha256": "", "asset_id": 0,
               "ext_url": FALLBACK_EXT_URL, "ext_size": 0, "ext_name": "FlowCue-Extension.7z",
               "ext_sha256": "", "ext_asset_id": 0, "page_url": RELEASES_PAGE_URL}
        try:
            r = None
            last_err = ""
            # VPN / 代理环境下偶发 502/503/504：重试几次；最后一次忽略系统代理再试一次
            for attempt in range(4):
                try:
                    sess = requests.Session()
                    if attempt == 3:
                        sess.trust_env = False
                    r = sess.get(API_URL, timeout=(10, 20),
                                 headers={"Accept": "application/vnd.github+json", "User-Agent": "FlowCue-Updater"})
                    if r.status_code < 500:
                        break
                    last_err = f"HTTP {r.status_code}"
                except Exception as e:
                    r = None
                    last_err = str(e)
                time.sleep(1.5 * (attempt + 1))
            if r is None:
                res["error"] = f"检查更新失败：{last_err}"
            elif r.status_code == 404:
                res["error"] = "未找到已发布的版本。"
            elif r.status_code != 200:
                res["error"] = f"GitHub 返回 HTTP {r.status_code}（可能是访问频率受限，请稍后再试）"
            else:
                data = r.json()
                tag = data.get("tag_name", "")
                res.update(ok=True, version=tag.lstrip("vV"), notes=data.get("body") or "",
                           page_url=data.get("html_url") or RELEASES_PAGE_URL)
                for a in data.get("assets", []):
                    aname = a.get("name", "")
                    if SETUP_RE.match(aname) and not res["url"]:
                        res.update(url=a.get("browser_download_url", ""), size=a.get("size", 0), name=aname,
                                   sha256=_digest_sha256(a), asset_id=a.get("id", 0))
                    elif EXT_RE.match(aname):
                        res.update(ext_url=a.get("browser_download_url", ""), ext_size=a.get("size", 0), ext_name=aname,
                                   ext_sha256=_digest_sha256(a), ext_asset_id=a.get("id", 0))
                res["has_update"] = is_newer(tag) and bool(res["url"])
                if is_newer(tag) and not res["url"]:
                    res["error"] = "发现新版本，但发布页没有安装包（FlowCue-Setup-*.exe）。"
        except Exception as e:
            res["error"] = f"检查更新失败：{e}"
        self.finished_signal.emit(res)

class _Cancelled(Exception):
    pass


class _RouteSkip(Exception):
    """该线路不可用（4xx 等），无需重试，直接换下一条。"""


class DownloadUpdateThread(QThread):
    """可靠下载：多线路 + 自动重试 + 断点续传 + SHA-256 校验。

    线路顺序：GitHub 官方直连 → GitHub API 资源地址 → 忽略系统代理直连 → 镜像线路（仅当有 SHA-256 时）。
    VPN / 代理常见的 502 / 503 / 504 / 超时会自动重试并从已下载位置继续，不必从头开始。
    """
    progress_signal = pyqtSignal(int, int)      # downloaded, total
    finished_signal = pyqtSignal(bool, str)     # success, path_or_error
    status_signal = pyqtSignal(str)             # 当前线路 / 重试提示

    def __init__(self, url, name, expected_size=0, dest_path=None, sha256="", asset_id=0):
        super().__init__()
        self.url, self.name, self.expected_size = url, name, expected_size
        self.dest_path = dest_path
        self.sha256 = (sha256 or "").lower()
        self.asset_id = asset_id

    # ── 线路表 ──
    def _routes(self):
        routes = []
        if _host_allowed(self.url):
            routes.append(("GitHub 官方直连", self.url, {}, True, True))
        if self.asset_id:
            api = f"https://api.github.com/repos/{GITHUB_REPO}/releases/assets/{self.asset_id}"
            routes.append(("GitHub 资源接口", api, {"Accept": "application/octet-stream"}, True, True))
        if _host_allowed(self.url):
            routes.append(("官方直连（不使用系统代理）", self.url, {}, False, True))
        if self.sha256 and _host_allowed(self.url):
            for i, prefix in enumerate(MIRROR_PREFIXES, 1):
                routes.append((f"备用线路 {i}", prefix + self.url, {}, True, False))
        return routes

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.isInterruptionRequested():
                raise _Cancelled()
            time.sleep(0.2)

    def _sha256_of(self, path):
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def _fetch_into(self, part, url, extra_headers, trust_env, host_check):
        """向 part 追加下载（支持断点续传）；失败抛异常。"""
        existing = os.path.getsize(part) if os.path.exists(part) else 0
        if self.expected_size and existing > self.expected_size:
            os.remove(part)
            existing = 0
        headers = {"User-Agent": "FlowCue-Updater"}
        headers.update(extra_headers)
        if existing:
            headers["Range"] = f"bytes={existing}-"
        sess = requests.Session()
        sess.trust_env = trust_env
        with sess.get(url, stream=True, timeout=(15, 60), headers=headers, allow_redirects=True) as r:
            if r.status_code == 416:      # 已下载位置无效：删掉从头来
                os.remove(part)
                raise RuntimeError("续传位置无效，将重新下载")
            if 400 <= r.status_code < 500:
                raise _RouteSkip(f"HTTP {r.status_code}")
            r.raise_for_status()          # 5xx（含 504）→ 抛出，由外层重试
            if host_check and not _host_allowed(r.url):
                raise _RouteSkip("重定向到了不允许的域名")
            resumed = existing > 0 and r.status_code == 206
            if existing and not resumed:  # 服务器不支持续传，从头写
                existing = 0
            total = self.expected_size or (int(r.headers.get("Content-Length") or 0) + (existing if resumed else 0))
            done = existing
            with open(part, "ab" if resumed else "wb") as f:
                for chunk in r.iter_content(256 * 1024):
                    if self.isInterruptionRequested():
                        raise _Cancelled()
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        self.progress_signal.emit(done, total)

    def _verify(self, part):
        size = os.path.getsize(part)
        if self.expected_size and size != self.expected_size:
            raise RuntimeError(f"文件大小不一致（{size} / {self.expected_size}）")
        if self.sha256 and self._sha256_of(part) != self.sha256:
            raise RuntimeError("SHA-256 校验失败，文件可能损坏或被篡改")

    def run(self):
        if self.dest_path:
            dest = self.dest_path
            os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        else:
            dest_dir = os.path.join(tempfile.gettempdir(), "FlowCue_update")
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, os.path.basename(self.name))
        part = dest + ".part"

        routes = self._routes()
        if not routes:
            self.finished_signal.emit(False, "下载地址不在允许的域名范围内，已拒绝。")
            return

        errors = []
        try:
            for label, url, extra, trust_env, host_check in routes:
                skip_route = False
                for attempt in range(1, RETRIES_PER_ROUTE + 1):
                    if self.isInterruptionRequested():
                        raise _Cancelled()
                    self.status_signal.emit(f"正在下载（{label}，第 {attempt}/{RETRIES_PER_ROUTE} 次）…")
                    try:
                        self._fetch_into(part, url, extra, trust_env, host_check)
                        self._verify(part)
                        os.replace(part, dest)
                        self.finished_signal.emit(True, dest)
                        return
                    except _Cancelled:
                        raise
                    except _RouteSkip as e:
                        errors.append(f"{label}：{e}")
                        skip_route = True
                    except Exception as e:
                        msg = str(e)
                        # 校验失败 = 文件已不可信：删掉重来；其它错误保留 .part 以便续传
                        if "校验失败" in msg or "大小不一致" in msg:
                            try:
                                os.remove(part)
                            except OSError:
                                pass
                        if attempt == RETRIES_PER_ROUTE:
                            errors.append(f"{label}：{msg}")
                        else:
                            self.status_signal.emit(f"{label} 连接不稳定（{msg[:60]}），{2 * attempt} 秒后重试并继续下载…")
                            self._sleep(2 * attempt)
                            continue
                    if skip_route or attempt == RETRIES_PER_ROUTE:
                        break
        except _Cancelled:
            try:
                os.remove(part)
            except OSError:
                pass
            self.finished_signal.emit(False, "已取消")
            return
        try:
            os.remove(part)
        except OSError:
            pass
        detail = "；".join(errors[-4:]) if errors else "未知错误"
        self.finished_signal.emit(False, f"下载失败（已尝试全部线路）：{detail}")

def launch_installer(path):
    """启动安装包（静默覆盖安装，完成后自动重启软件）。调用后应立即退出本程序。"""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
