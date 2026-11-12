# -*- coding: utf-8 -*-
"""浏览器插件目录版本同步与自动覆盖解压工具。

确保用户本地「加载已解压的扩展程序」所使用的插件文件夹（如 FlowCue插件 / 自定义目录）
始终与软件内置最新插件或从 GitHub 下载的最新插件保持一致，manifest.json 版本号始终最新。
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from version import __version__


def _ver_tuple(v: str) -> tuple:
    parts = []
    for seg in str(v or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts or [0])


def get_bundled_extension_dir() -> Path | None:
    """定位当前软件内置的 extension 源目录（兼容源码运行、PyInstaller 与 Inno Setup 安装目录）。"""
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parent.parent / "extension")
    except Exception:
        pass
    try:
        candidates.append(Path(sys.executable).resolve().parent / "extension")
    except Exception:
        pass
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        try:
            candidates.append(Path(meipass) / "extension")
        except Exception:
            pass

    for c in candidates:
        try:
            if c.is_dir() and (c / "manifest.json").is_file() and (c / "injects" / "ui.js").is_file():
                return c.resolve()
        except Exception:
            continue
    return None


def read_extension_version(ext_dir: Path | str) -> str:
    """读取指定插件目录 manifest.json 中的 version 字段。"""
    try:
        mf = Path(ext_dir) / "manifest.json"
        if not mf.is_file():
            return ""
        data = json.loads(mf.read_text(encoding="utf-8"))
        return str(data.get("version") or "").strip()
    except Exception:
        return ""


def is_flowcue_extension_dir(ext_dir: Path | str) -> bool:
    """判断某个目录是否是已解压的 FlowCue 浏览器插件目录。"""
    try:
        d = Path(ext_dir)
        mf = d / "manifest.json"
        if not d.is_dir() or not mf.is_file():
            return False
        data = json.loads(mf.read_text(encoding="utf-8"))
        name = str(data.get("name") or "")
        desc = str(data.get("description") or "")
        if "FlowCue" in name or "FlowCue" in desc or "Flow 批量" in name:
            return True
        return (d / "injects" / "ui.js").is_file() and (d / "background.js").is_file()
    except Exception:
        return False


def sync_extension_files(src_dir: Path | str, dst_dir: Path | str, force_version: str = "") -> tuple[bool, str]:
    """把 src_dir 下的全部插件文件同步覆盖到 dst_dir，并确保 manifest.json 版本号为最新。"""
    try:
        src = Path(src_dir).resolve()
        dst = Path(dst_dir).resolve()
        if not src.is_dir() or not (src / "manifest.json").is_file():
            return False, "插件源目录不完整（缺少 manifest.json）"
        if src == dst:
            # 仅确保版本号同步
            ver = _ensure_manifest_version(dst, force_version)
            return True, ver

        dst.mkdir(parents=True, exist_ok=True)
        for root, dirs, files in os.walk(src):
            rel = Path(root).relative_to(src)
            # 跳过隐藏目录或备份目录
            dirs[:] = [dn for dn in dirs if not dn.startswith(".") and dn != "__pycache__"]
            target_sub = dst / rel
            target_sub.mkdir(parents=True, exist_ok=True)
            for fn in files:
                if fn.startswith(".") or fn.endswith((".pyc", ".tmp")):
                    continue
                s_file = Path(root) / fn
                d_file = target_sub / fn
                shutil.copy2(s_file, d_file)

        ver = _ensure_manifest_version(dst, force_version)
        return True, ver
    except Exception as e:
        return False, str(e)


def _ensure_manifest_version(ext_dir: Path, force_version: str = "") -> str:
    """读取并在需要时更新 manifest.json 的 version，返回最终版本号。"""
    mf = Path(ext_dir) / "manifest.json"
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
        cur_ver = str(data.get("version") or "").strip()
        target_ver = str(force_version or "").strip()
        if target_ver and _ver_tuple(target_ver) > _ver_tuple(cur_ver):
            data["version"] = target_ver
            mf.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return target_ver
        return cur_ver or target_ver or __version__
    except Exception:
        return force_version or __version__


def _find_manifest_root(staging_dir: Path) -> Path | None:
    """在解压临时目录中定位包含 manifest.json 的根目录（兼容平铺压缩包与带一层子目录的压缩包）。"""
    if (staging_dir / "manifest.json").is_file():
        return staging_dir
    for p in staging_dir.rglob("manifest.json"):
        if p.is_file() and (p.parent / "background.js").is_file():
            return p.parent
    for p in staging_dir.rglob("manifest.json"):
        if p.is_file():
            return p.parent
    return None


def extract_extension_archive_to_dir(archive_path: Path | str, target_dir: Path | str) -> tuple[bool, str]:
    """将下载的 FlowCue-Extension.7z / .zip 自动解压覆盖到指定的插件安装目录。
    成功返回 (True, 最新版本号)，失败返回 (False, 错误原因)。
    """
    arc = Path(archive_path)
    dst = Path(target_dir)
    if not arc.is_file():
        return False, f"未找到压缩包文件：{arc}"

    # 若用户不小心选到了插件内部的 injects 子目录，自动向上修正为插件根目录
    if dst.name.lower() == "injects" and (dst.parent / "manifest.json").is_file():
        dst = dst.parent

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    with tempfile.TemporaryDirectory(prefix="flowcue_ext_") as tmp_str:
        tmp_dir = Path(tmp_str)
        extracted = False
        errors = []

        suffix = arc.suffix.lower()
        if suffix == ".zip":
            try:
                with zipfile.ZipFile(arc, "r") as zf:
                    zf.extractall(tmp_dir)
                extracted = True
            except Exception as e:
                errors.append(f"zip 解压失败: {e}")

        if not extracted:
            # 1. 尝试 7-Zip
            seven_zip_candidates = [
                shutil.which("7z"),
                r"C:\Program Files\7-Zip\7z.exe",
                r"C:\Program Files (x86)\7-Zip\7z.exe",
            ]
            for sz in seven_zip_candidates:
                if sz and os.path.isfile(sz):
                    try:
                        proc = subprocess.run(
                            [sz, "x", str(arc), f"-o{tmp_dir}", "-y"],
                            capture_output=True, text=True, timeout=30, creationflags=creationflags,
                        )
                        if proc.returncode == 0 and _find_manifest_root(tmp_dir):
                            extracted = True
                            break
                        errors.append(f"7z 返回码 {proc.returncode}")
                    except Exception as e:
                        errors.append(f"7z 异常: {e}")

        if not extracted:
            # 2. 尝试 Windows 10/11 系统自带 bsdtar (tar.exe 原生支持 .7z 与 .zip)
            tar_candidates = [
                r"C:\Windows\System32\tar.exe",
                shutil.which("tar"),
            ]
            for tar_bin in tar_candidates:
                if tar_bin and os.path.isfile(tar_bin):
                    try:
                        proc = subprocess.run(
                            [tar_bin, "-xf", str(arc), "-C", str(tmp_dir)],
                            capture_output=True, text=True, timeout=30, creationflags=creationflags,
                        )
                        if proc.returncode == 0 and _find_manifest_root(tmp_dir):
                            extracted = True
                            break
                        errors.append(f"tar 返回码 {proc.returncode}")
                    except Exception as e:
                        errors.append(f"tar 异常: {e}")

        if extracted:
            ext_root = _find_manifest_root(tmp_dir)
            if ext_root:
                return sync_extension_files(ext_root, dst, force_version=__version__)

        # 3. 兜底：若系统无解压工具，直接从当前软件内置的 extension 目录同步
        bundled = get_bundled_extension_dir()
        if bundled:
            return sync_extension_files(bundled, dst, force_version=__version__)

        return False, "；".join(errors) or "无法解压插件压缩包"


def discover_local_extension_dirs(config_manager=None) -> list[Path]:
    """扫描用户已记住或常见同级目录中的已解压 FlowCue 浏览器插件文件夹。"""
    bundled = get_bundled_extension_dir()
    candidates = []

    if config_manager:
        custom = str(getattr(config_manager, "custom_extension_dir", "") or "").strip()
        if custom:
            p = Path(custom)
            candidates.append(p)
            # 若用户填的是外层目录（如 D:\Antigravity\FlowCue\FlowCue 或 D:\Antigravity\FlowCue），顺带检查其下的插件子目录
            if p.is_dir():
                candidates.append(p / "FlowCue插件")
                candidates.append(p / "extension")

    # 扫描软件/工作区周边的常见插件解压目录
    roots_to_probe = set()
    try:
        repo_root = Path(__file__).resolve().parent.parent
        roots_to_probe.add(repo_root.parent)
        if repo_root.parent.parent != repo_root.parent:
            roots_to_probe.add(repo_root.parent.parent / "FlowCue")
    except Exception:
        pass
    try:
        app_root = Path(sys.executable).resolve().parent
        roots_to_probe.add(app_root)
        roots_to_probe.add(app_root.parent)
    except Exception:
        pass
    if config_manager:
        bp = str(getattr(config_manager, "base_path", "") or "").strip()
        if bp:
            try:
                roots_to_probe.add(Path(bp).parent)
            except Exception:
                pass
    roots_to_probe.add(Path(r"D:\Antigravity\FlowCue"))

    for r in roots_to_probe:
        try:
            if not r or not r.is_dir():
                continue
            for sub_name in ("FlowCue插件", "FlowCue", "extension"):
                candidates.append(r / sub_name)
            for child in r.iterdir():
                if child.is_dir() and ("flow" in child.name.lower() or "插件" in child.name or "extension" in child.name.lower()):
                    candidates.append(child)
                    candidates.append(child / "FlowCue插件")
        except Exception:
            continue

    found = []
    seen = set()
    for c in candidates:
        try:
            if not c.is_dir():
                continue
            rc = c.resolve()
            key = str(rc).lower()
            if key in seen:
                continue
            if bundled and rc == bundled:
                continue
            if is_flowcue_extension_dir(rc):
                seen.add(key)
                found.append(rc)
        except Exception:
            continue
    return found


def auto_sync_local_extension_dirs(config_manager=None) -> list[tuple[Path, str, str]]:
    """启动时静默检查本地已安装的 FlowCue 解压版插件目录；若版本落后或文件未同步则自动更新至当前内置最新版。
    返回 [(目录路径, 旧版本号, 新版本号), ...]
    """
    bundled = get_bundled_extension_dir()
    if not bundled:
        return []
    # 先确保内置目录自身的 manifest.json 版本与 __version__ 一致
    _ensure_manifest_version(bundled, __version__)
    src_ver = read_extension_version(bundled) or __version__
    src_ui = bundled / "injects" / "ui.js"
    src_ui_bytes = src_ui.read_bytes() if src_ui.is_file() else b""

    updated = []
    for target in discover_local_extension_dirs(config_manager=config_manager):
        try:
            old_ver = read_extension_version(target)
            if _ver_tuple(old_ver) > _ver_tuple(src_ver):
                # 目标目录版本比当前软件内置更高（用户刚从云端下载了更新的插件），绝不倒退覆盖
                continue
            dst_ui = target / "injects" / "ui.js"
            same_ver = (old_ver == src_ver)
            same_ui = dst_ui.is_file() and (dst_ui.read_bytes() == src_ui_bytes)
            if same_ver and same_ui:
                continue
            ok, new_ver = sync_extension_files(bundled, target, force_version=src_ver)
            if ok:
                updated.append((target, old_ver or "未知", new_ver))
        except Exception as e:
            print(f"[ExtensionSync] auto sync {target} warning: {e}")
    return updated
