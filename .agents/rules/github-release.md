---
trigger: always_on
description: GitHub Release 发布规范：每次发布必须同时包含软件安装包与浏览器插件压缩包
---

# GitHub Release 发布规范

每当用户要求将 FlowCue 更新到 GitHub（创建或更新 GitHub Release）时，**必须同时构建并上传以下两个 Release Assets**：

1. **软件安装包**：`FlowCue-Setup-<version>.exe`（由 `pyinstaller flow_tool.spec --noconfirm` + `ISCC.exe installer.iss /DAppVersion=<version>` 生成）。
2. **浏览器插件压缩包**：`FlowCue-Extension.7z`（将 `extension/` 目录下的所有文件打包为 `dist/FlowCue-Extension.7z`）。

**重要原则**：
- 即使某次更新只修改了软件而没有修改插件（或只修改了插件而没有修改软件），发布 GitHub Release 时也**必须同时上传软件安装包 (`FlowCue-Setup-<version>.exe`) 和插件压缩包 (`FlowCue-Extension.7z`)**。
- 如果插件未修改，直接将当前 `extension/` 目录打包为 `FlowCue-Extension.7z` 一并上传，确保用户在 GitHub 最新 Release 页面始终能同时下载到软件安装包和最新插件，且软件内的「⬆️ 检查更新 -> 🧩 下载最新插件」功能始终能从 `releases/latest` 检测到并下载 `FlowCue-Extension.7z`。
