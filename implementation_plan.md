# 视频完整性核查与批量管理实现方案

本方案重构了视频完整性核查功能，明确以**应用设置的“总存储路径”**为基准，理顺了**归位前**与**归位后**的排查逻辑，并成功实现了**一键批量检查所有项目**功能。

---

## 💡 核心设计与排查逻辑

### 1. 明确双路径排查机制（以“总存储路径”为基准，绝不乱扫系统下载目录）
假设用户在应用顶部设置的 **总存储路径 (Base Storage Path)** 为 `BaseDir`（例如 `D:/MyProjects`）：

- **归位前路径（未归位视频存放处）**：
  `BaseDir/Flow/{project_id}/`（例如 `D:/MyProjects/Flow/01_衣服-flow/` 或 `D:/MyProjects/Flow/{project_id}/`）
  - 说明：这是 Flow 自动化插件或视频生成后默认保存到总存储路径 `Flow` 文件夹下的位置。
  - 如果视频存在于此路径，状态标识为：`⚠️ 待归位`（已生成但尚未移入项目目录）。

- **归位后路径（项目内置视频文件夹）**：
  `{project_path}/downloads/videos/`（即 `BaseDir/{project_folder}/downloads/videos/`）
  - 说明：这是项目归档与标准引用的内置视频存放位置。
  - 如果视频存在于此路径，状态标识为：`✅ 已归位`。

- **均未找到**：
  - 状态标识为：`❌ 缺失`。

> ⚠️ **重要保障**：排查范围严格限制在上述两个路径，绝对不会自动排查系统 `C:\Users\...\Downloads` 或其他无关目录。如需排查其他特殊路径，支持用户手动浏览选择。

---

### 2. 自动归位联动机制
- 当视频在 **`BaseDir/Flow/{project_id}/`** 被找到（`⚠️ 待归位`），点击 **“一键归位”** 后，系统会自动将文件移动（Move）至 **`{project_path}/downloads/videos/`**。
- 移动完成后重新刷新，视频状态自动转为 `✅ 已归位`。
- 完美解决“归位后原路径变空导致再次检查显示缺失”的矛盾痛点。

---

### 3. 一键批量检查所有项目（全部检查）
在主界面顶部工具栏新增 **“🔍 批量检查视频”** 按钮：
- 自动遍历总存储路径下的**所有工程项目**。
- 弹出 **全项目视频完整性概览面板**，表格直观展示每个项目的：
  - 项目序号与名称
  - 分句总片段数、已归位数量、待归位数量、缺失数量、完成度百分比（如 `85%`）
- 支持 **“📦 一键全部归位”**：批量将所有项目的待归位视频一次性移入各自的内置文件夹。
- 支持点击单个项目 **“🔍 查看明细”**，深入查看该项目逐句文案与对应视频文件。

---

## 🛠️ 修改与新增模块

### 1. [`services/video_checker.py`](file:///c:/Users/DELL/Desktop/python%E5%B7%A5%E7%A8%8B/flow/services/video_checker.py)
- 重构 `check_project_videos`：实现精确双路径排查（`✅ 已归位`、`⚠️ 待归位`、`❌ 缺失`）。
- 新增 `check_all_projects`：汇总扫描所有项目生成批量报告。
- 新增 `relocate_batch_videos`：支持一键批量归位。

### 2. [`views/video_check_dialog.py`](file:///c:/Users/DELL/Desktop/python%E5%B7%A5%E7%A8%8B/flow/views/video_check_dialog.py)
- 升级 `VideoCheckDialog`（单项目核查）：展示双路径信息、状态标签与一键归位按钮。
- 新增 `BatchVideoCheckDialog`（全项目批量核查）：全项目概览卡片、完成度列表、一键批量归位与单项目明细入口。

### 3. [`views/main_window.py`](file:///c:/Users/DELL/Desktop/python%E5%B7%A5%E7%A8%8B/flow/views/main_window.py)
- 顶部工具栏添加 **“🔍 批量检查视频”** 按钮。

### 4. [`views/project_detail_widget.py`](file:///c:/Users/DELL/Desktop/python%E5%B7%A5%E7%A8%8B/flow/views/project_detail_widget.py)
- 更新单项目完整性核查，关联总存储路径。
