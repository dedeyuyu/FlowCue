# -*- coding: utf-8 -*-
import os
import json
from pathlib import Path


# 预设卡片专属浅色调色板（用于「批量选择预设」可视化卡片背景高亮）
# 若某个预设未指定颜色 (color == "")，当任务卡片单独使用该预设时，默认显示为「浅粉红色」
PRESET_COLOR_PALETTE = [
    {
        "key": "",
        "name": "🌸 默认浅粉红 (未指定时默认)",
        "short": "🌸浅粉红",
        "bg": "#FCE7F3",
        "border": "#F472B6",
        "tag_bg": "#FBCFE8",
        "tag_fg": "#9D174D",
        "dark_bg": "#3B182B",
        "dark_border": "#EC4899",
    },
    {
        "key": "pink",
        "name": "🌸 浅粉红色",
        "short": "🌸浅粉红",
        "bg": "#FCE7F3",
        "border": "#F472B6",
        "tag_bg": "#FBCFE8",
        "tag_fg": "#9D174D",
        "dark_bg": "#3B182B",
        "dark_border": "#EC4899",
    },
    {
        "key": "green",
        "name": "🌿 浅绿色",
        "short": "🌿浅绿色",
        "bg": "#DCFCE7",
        "border": "#4ADE80",
        "tag_bg": "#BBF7D0",
        "tag_fg": "#166534",
        "dark_bg": "#133223",
        "dark_border": "#22C55E",
    },
    {
        "key": "blue",
        "name": "💧 浅蓝色",
        "short": "💧浅蓝色",
        "bg": "#DBEAFE",
        "border": "#60A5FA",
        "tag_bg": "#BFDBFE",
        "tag_fg": "#1E40AF",
        "dark_bg": "#172554",
        "dark_border": "#3B82F6",
    },
    {
        "key": "yellow",
        "name": "🌼 浅黄色",
        "short": "🌼浅黄色",
        "bg": "#FEF9C3",
        "border": "#FACC15",
        "tag_bg": "#FEF08A",
        "tag_fg": "#854D0E",
        "dark_bg": "#382E12",
        "dark_border": "#EAB308",
    },
    {
        "key": "purple",
        "name": "🔮 浅紫色",
        "short": "🔮浅紫色",
        "bg": "#F3E8FF",
        "border": "#C084FC",
        "tag_bg": "#E9D5FF",
        "tag_fg": "#6B21A8",
        "dark_bg": "#2E1944",
        "dark_border": "#A855F7",
    },
    {
        "key": "orange",
        "name": "🍊 浅橙色",
        "short": "🍊浅橙色",
        "bg": "#FFEDD5",
        "border": "#FB923C",
        "tag_bg": "#FED7AA",
        "tag_fg": "#9A3412",
        "dark_bg": "#3B2112",
        "dark_border": "#F97316",
    },
    {
        "key": "cyan",
        "name": "🧊 浅青色",
        "short": "🧊浅青色",
        "bg": "#CFFAFE",
        "border": "#22D3EE",
        "tag_bg": "#A5F3FC",
        "tag_fg": "#155E75",
        "dark_bg": "#11323B",
        "dark_border": "#06B6D4",
    },
    {
        "key": "rose",
        "name": "🌹 浅玫瑰色",
        "short": "🌹浅玫瑰",
        "bg": "#FFE4E6",
        "border": "#FB7185",
        "tag_bg": "#FECDD3",
        "tag_fg": "#9F1239",
        "dark_bg": "#3D1620",
        "dark_border": "#F43F5E",
    },
    {
        "key": "teal",
        "name": "🍃 浅薄荷色",
        "short": "🍃浅薄荷",
        "bg": "#CCFBF1",
        "border": "#2DD4BF",
        "tag_bg": "#99F6E4",
        "tag_fg": "#115E59",
        "dark_bg": "#113330",
        "dark_border": "#14B8A6",
    },
    {
        "key": "lime",
        "name": "🍋 浅柠檬绿",
        "short": "🍋浅柠檬",
        "bg": "#ECFCCB",
        "border": "#A3E635",
        "tag_bg": "#D9F99D",
        "tag_fg": "#3F6212",
        "dark_bg": "#233312",
        "dark_border": "#84CC16",
    },
]

for _c in PRESET_COLOR_PALETTE:
    _c["label"] = _c["name"]

_PRESET_COLOR_MAP = {c["key"]: c for c in PRESET_COLOR_PALETTE}


def get_preset_color_info(color_key: str) -> dict:
    """根据预设的 color 字段返回对应的浅色配置；未指定时默认返回浅粉红色。"""
    k = str(color_key or "").strip().lower()
    return _PRESET_COLOR_MAP.get(k, PRESET_COLOR_PALETTE[0])


class TemplateManager:
    """Manages prompt templates and camera motion presets in the app root directory."""
    
    TEMPLATES_FILE = "prompt_templates.json"
    MOTIONS_FILE = "camera_motions.json"
    BATCH_TEMPLATES_FILE = "batch_templates.json"
    BATCH_CATEGORIES_FILE = "batch_categories.json"
    TEMPLATE_GROUPS_FILE = "template_groups.json"
    MOTION_GROUPS_FILE = "motion_groups.json"
    
    def __init__(self, workspace_dir):
        self.workspace_dir = Path(workspace_dir)
        self.templates_path = self.workspace_dir / self.TEMPLATES_FILE
        self.motions_path = self.workspace_dir / self.MOTIONS_FILE
        self.batch_templates_path = self.workspace_dir / self.BATCH_TEMPLATES_FILE
        self.batch_categories_path = self.workspace_dir / self.BATCH_CATEGORIES_FILE
        self.template_groups_path = self.workspace_dir / self.TEMPLATE_GROUPS_FILE
        self.motion_groups_path = self.workspace_dir / self.MOTION_GROUPS_FILE
        
        self.templates = []
        self.motions = []
        self.batch_templates = []
        self.batch_categories = []
        self.template_groups = []
        self.motion_groups = []
        
        self.load_all()

    def load_all(self):
        self.load_templates()
        self.load_motions()
        self.load_batch_templates()
        self.load_batch_categories()
        self.load_template_groups()
        self.load_motion_groups()

    def load_templates(self):
        """Loads prompt templates from file. Initializes defaults if missing."""
        if self.templates_path.exists():
            try:
                with open(self.templates_path, "r", encoding="utf-8") as f:
                    self.templates = json.load(f)
                if not self.templates:
                    self.init_default_templates()
            except Exception as e:
                print(f"Error loading templates: {e}")
                self.init_default_templates()
        else:
            self.init_default_templates()

    def save_templates(self):
        """Saves prompt templates to file."""
        try:
            with open(self.templates_path, "w", encoding="utf-8") as f:
                json.dump(self.templates, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving templates: {e}")
            return False

    def load_motions(self):
        """Loads camera motion presets. Initializes defaults if missing."""
        if self.motions_path.exists():
            try:
                with open(self.motions_path, "r", encoding="utf-8") as f:
                    self.motions = json.load(f)
                if not self.motions:
                    self.init_default_motions()
            except Exception as e:
                print(f"Error loading motions: {e}")
                self.init_default_motions()
        else:
            self.init_default_motions()

    def save_motions(self):
        """Saves camera motion presets to file."""
        try:
            with open(self.motions_path, "w", encoding="utf-8") as f:
                json.dump(self.motions, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving motions: {e}")
            return False

    def init_default_templates(self):
        """Creates the default prompt templates."""
        self.templates = [
            {
                "id": "tpl_stage",
                "name": "舞台类",
                "content": (
                    "视频不要穿帮，人物站在讲台上讲道,电子屏幕的人物和讲台的人说话嘴型保持一致"
                    "（绝对不能在屏幕上出现两个同样的人物）人物手部有大浮度动作,动作铿锵有力."
                    "人物可以在讲台上来回走动.人物富有强烈感情的用西班牙语说：“{spanish_text}”"
                    "（话要说完整说准确,富有强烈感情，铿锵有力。） {camera_motion}。"
                    "镜头运动时不模糊虚化. 人物眼部： \"Subtle flickering "
                    "of eyelashes\"（睫毛微颤）。 人物超真实皮肤毛孔、强烈的面部微表情。 "
                    "现代 4K 数字电影质感，超清晰锐利对焦。极度纯净的镜头，无胶片颗粒，无漏光，"
                    "无闪烁。鲜艳自然的色彩，高清晰度。 没有背景音乐.有环境音效(观众的掌声、"
                    "欢呼声、喊阿门的声音). 话筒一直在人物手上拿着.禁止出现两个话筒.禁止话筒"
                    "悬在半空中,禁止出现第三只手.禁止话筒突然消失，禁止人物穿过讲台。"
                )
            },
            {
                "id": "tpl_closed_eyes",
                "name": "闭眼祷告",
                "content": (
                    "人物紧闭双眼，禁止改变人物的手部动作，人物说话富有感情，说：“{spanish_text}”"
                    "（话要说完整说准确，说的有感情。） {camera_motion} 侧面镜头，镜头可以稳定"
                    "线性轨道相机运动特写人物侧脸，但不要模糊虚化.不叠化。 人物眼部： \"Subtle flickering of eyelashes\""
                    "（睫毛微颤）。 人物超真实皮肤毛孔、面部微表情。 现代 4K 数字电影质感，"
                    "超清晰锐利对焦。极度纯净的镜头，无胶片颗粒，无漏光，无闪烁。鲜艳自然的色彩，"
                    "高清晰度。禁止改变人物的手部动作，交错的手指保持静止且坚硬。一直保持图片"
                    "中手的姿势不变动，不要放下手。"
                )
            },
            {
                "id": "tpl_general",
                "name": "普通类",
                "content": (
                    "视频不要穿帮，这个人物面部表情自然，微笑、和蔼一点声音干净自然的音频，"
                    "没有电子噪音，没有机器人声音，没有合成音，没有失真，逼真的录音效果，"
                    "用西班牙语说，下面所有的都要张口说包括数字：“{spanish_text}” {camera_motion}。"
                    "背景不要改变，但是还是可以有运动镜头的，面部微表情要自然。现代4K数字电影质感,超清晰锐利对焦。"
                    "极度纯净的镜头,无胶片颗粒, 无漏光,无闪烁。鲜艳自然的色彩,高清晰度。 "
                    "禁止添加字幕，禁止背景音乐. 禁止手上出现戒指，禁止头上出现天主教的小圆帽，"
                    "禁止随意添加单词或者句子，禁止漏掉单词或句子，和给的原文保持一致。禁止出现"
                    "第三只手。禁止手里的东西撒手、悬空。禁止皱眉头。"
                )
            },
            {
                "id": "tpl_walking",
                "name": "走路类",
                "content": (
                    "禁止改变图中人物的形象和装饰品，人物缓缓往前走，镜头缓缓向后移动，"
                    "人物面带笑容的看着镜头说话，禁止皱眉头，有一些手部动作，有感情的说：“{spanish_text}”"
                    "（话要说完整说准确，说的有感情。） {camera_motion}。不加转场,不模糊虚化.不叠化。 "
                    "人物眼部： \"Subtle flickering of eyelashes\"（睫毛微颤）。 "
                    "人物超真实皮肤毛孔、强烈的面部微表情。 现代 4K 数字电影质感，超清晰锐利对焦。"
                    "极度纯净的镜头，无胶片颗粒，无漏光，无闪烁。鲜艳自然的色彩，高清晰度。"
                )
            }
        ]
        self.save_templates()

    def init_default_motions(self):
        """Creates default camera motion presets."""
        self.motions = [
            {
                "id": "motion_default",
                "name": "带镜头运动 (默认)",
                "content": "带镜头运动，镜头多角度多景别，但运动幅度不要太大, 真实摄影机拍摄"
            },
            {
                "id": "motion_fixed",
                "name": "固定一镜到底",
                "content": "固定镜头，不要有景别切换，不要运动镜头，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_panning",
                "name": "摇移镜头",
                "content": "可以加一些摇移镜头，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_variations",
                "name": "微幅镜头变化",
                "content": "镜头可以有一些变化，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_slow_push",
                "name": "慢速推进镜头",
                "content": "镜头可以有一些慢速推进的变化，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_fast_push",
                "name": "快速推进镜头",
                "content": "镜头加个快速推进，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_closeup",
                "name": "特写镜头切换",
                "content": "镜头可以切特写，真实摄影机拍摄"
            },
            {
                "id": "motion_smooth_zoom",
                "name": "平滑运镜 (含缩放)",
                "content": "镜头多角度多景别，平滑运镜，加些缩放镜头，真实摄影机拍摄"
            },
            {
                "id": "motion_fixed_minor_pan",
                "name": "固定微平移推进",
                "content": "固定镜头，镜头可以有一些轻微左右推进的变化，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_oral_breathing",
                "name": "【口播类】轻微手持呼吸感",
                "content": "轻微手持相机微幅抖动，自然的呼吸感，主体面部微表情清晰稳定，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_oral_dolly_zoom",
                "name": "【口播类】滑动变焦一镜到底",
                "content": "慢速滑动变焦(Dolly Zoom)，背景轻微透视压缩但人物保持清晰居中，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_stage_tracking",
                "name": "【舞台类】横向追踪摇镜",
                "content": "镜头缓慢水平横向平移，追踪舞台上演讲者走动，保持讲台和人在画面内，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_stage_medium_close",
                "name": "【舞台类】中景到特写缓推",
                "content": "镜头缓慢从中景推进到紧凑的特写，捕捉演讲者肢体手势与情绪，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_prayer_linear",
                "name": "【闭眼祷告类】线性轨道平移",
                "content": "稳定线性轨道相机水平移动，特写人物侧脸，保持双手和交错的手指静止，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            },
            {
                "id": "motion_walking_follow",
                "name": "【走路类】人物前移镜头后退",
                "content": "人物缓缓往前走，镜头缓缓向后移动追踪，人物面带笑容看着镜头，一镜到底，不切镜头，不跳帧，不加转场，真实摄影机拍摄"
            }
        ]
        self.save_motions()

    def get_template(self, tpl_id):
        for t in self.templates:
            if t["id"] == tpl_id:
                return t
        return None

    def get_motion(self, motion_id):
        for m in self.motions:
            if m["id"] == motion_id:
                return m
        return None

    def export_all(self, export_path):
        """Exports all templates, motions, groups, and batch templates to a single JSON file."""
        try:
            data = {
                "templates": self.templates,
                "motions": self.motions,
                "template_groups": self.template_groups,
                "motion_groups": self.motion_groups,
                "batch_templates": self.batch_templates,
                "batch_categories": self.get_batch_categories(),
            }
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            return True, "导出成功"
        except Exception as e:
            return False, f"导出失败: {e}"

    def import_all(self, import_path):
        """Imports templates and motions from a single JSON file by ADDING/MERGING without replacing existing presets."""
        import uuid
        try:
            with open(import_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            added_tpl = 0
            added_mot = 0
            added_bt = 0
            skipped_dup = 0

            if "templates" in data and isinstance(data["templates"], list):
                existing_ids = {str(t.get("id", "")).strip() for t in self.templates}
                existing_pairs = {
                    (str(t.get("name", "")).strip(), str(t.get("content", "")).strip())
                    for t in self.templates
                }
                for item in data["templates"]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    content = str(item.get("content", "")).strip()
                    color = str(item.get("color", "") or "").strip()
                    if not name and not content:
                        continue
                    if (name, content) in existing_pairs:
                        skipped_dup += 1
                        continue
                    new_id = str(item.get("id", "")).strip()
                    if not new_id or new_id in existing_ids:
                        new_id = f"tpl_{uuid.uuid4().hex[:8]}"
                    existing_ids.add(new_id)
                    existing_pairs.add((name, content))
                    self.templates.append({
                        "id": new_id,
                        "name": name or "导入提示词模板",
                        "content": content,
                        "color": color,
                    })
                    added_tpl += 1

            if "motions" in data and isinstance(data["motions"], list):
                existing_ids = {str(m.get("id", "")).strip() for m in self.motions}
                existing_pairs = {
                    (str(m.get("name", "")).strip(), str(m.get("content", "")).strip())
                    for m in self.motions
                }
                for item in data["motions"]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    content = str(item.get("content", "")).strip()
                    color = str(item.get("color", "") or "").strip()
                    if not name and not content:
                        continue
                    if (name, content) in existing_pairs:
                        skipped_dup += 1
                        continue
                    new_id = str(item.get("id", "")).strip()
                    if not new_id or new_id in existing_ids:
                        new_id = f"motion_{uuid.uuid4().hex[:8]}"
                    existing_ids.add(new_id)
                    existing_pairs.add((name, content))
                    self.motions.append({
                        "id": new_id,
                        "name": name or "导入运镜预设",
                        "content": content,
                        "color": color,
                    })
                    added_mot += 1

            if "template_groups" in data and isinstance(data["template_groups"], list):
                existing_gnames = {str(g.get("name", "")).strip() for g in self.template_groups}
                existing_gids = {str(g.get("id", "")).strip() for g in self.template_groups}
                for g in data["template_groups"]:
                    if not isinstance(g, dict):
                        continue
                    gname = str(g.get("name", "")).strip()
                    pids = [str(x).strip() for x in (g.get("preset_ids") or []) if str(x).strip()]
                    if not gname or gname in existing_gnames:
                        continue
                    gid = str(g.get("id", "")).strip()
                    if not gid or gid in existing_gids:
                        gid = f"tgrp_{uuid.uuid4().hex[:8]}"
                    existing_gids.add(gid)
                    existing_gnames.add(gname)
                    self.template_groups.append({"id": gid, "name": gname, "preset_ids": pids})
                self.save_template_groups()

            if "motion_groups" in data and isinstance(data["motion_groups"], list):
                existing_gnames = {str(g.get("name", "")).strip() for g in self.motion_groups}
                existing_gids = {str(g.get("id", "")).strip() for g in self.motion_groups}
                for g in data["motion_groups"]:
                    if not isinstance(g, dict):
                        continue
                    gname = str(g.get("name", "")).strip()
                    pids = [str(x).strip() for x in (g.get("preset_ids") or []) if str(x).strip()]
                    if not gname or gname in existing_gnames:
                        continue
                    gid = str(g.get("id", "")).strip()
                    if not gid or gid in existing_gids:
                        gid = f"mgrp_{uuid.uuid4().hex[:8]}"
                    existing_gids.add(gid)
                    existing_gnames.add(gname)
                    self.motion_groups.append({"id": gid, "name": gname, "preset_ids": pids})
                self.save_motion_groups()

            if "batch_categories" in data and isinstance(data["batch_categories"], list):
                for c in data["batch_categories"]:
                    cat_str = str(c or "").strip()
                    if cat_str and cat_str not in self.batch_categories:
                        self.batch_categories.append(cat_str)
                self.save_batch_categories()

            if "batch_templates" in data and isinstance(data["batch_templates"], list):
                existing_ids = {str(t.get("id", "")).strip() for t in self.batch_templates}
                existing_triples = {
                    (
                        str(t.get("name", "")).strip(),
                        str(t.get("content", "")).strip(),
                        str(t.get("category", "")).strip(),
                    )
                    for t in self.batch_templates
                }
                for item in data["batch_templates"]:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    content = str(item.get("content", "")).strip()
                    category = str(item.get("category", "") or "").strip()
                    if not name and not content:
                        continue
                    if (name, content, category) in existing_triples:
                        skipped_dup += 1
                        continue
                    new_id = str(item.get("id", "")).strip()
                    if not new_id or new_id in existing_ids:
                        new_id = f"bt-{uuid.uuid4().hex[:8]}"
                    existing_ids.add(new_id)
                    existing_triples.add((name, content, category))
                    self.batch_templates.append({
                        "id": new_id,
                        "name": name or "导入批量模板",
                        "content": content,
                        "category": category,
                    })
                    added_bt += 1
                self.save_batch_templates()

            self._sync_categories_from_templates()
            self.save_templates()
            self.save_motions()
            summary = (
                f"已保留原有全部预设，并成功新增导入：\n"
                f"• 提示词模板：{added_tpl} 条\n"
                f"• 运镜预设：{added_mot} 条\n"
                f"• 批量模板：{added_bt} 条"
            )
            if skipped_dup > 0:
                summary += f"\n（自动跳过 {skipped_dup} 条完全相同的重复预设）"
            return True, summary
        except Exception as e:
            return False, f"导入失败: {e}"

    def load_template_groups(self):
        """加载提示词模板组合列表 [{"id": str, "name": str, "preset_ids": [str, ...]}]"""
        self.template_groups = []
        if self.template_groups_path.exists():
            try:
                with open(self.template_groups_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    for g in raw:
                        if isinstance(g, dict) and g.get("id") and g.get("name"):
                            self.template_groups.append({
                                "id": str(g["id"]),
                                "name": str(g["name"]),
                                "preset_ids": [str(x) for x in (g.get("preset_ids") or []) if x],
                            })
            except Exception as e:
                print(f"Error loading template groups: {e}")

    def save_template_groups(self):
        try:
            with open(self.template_groups_path, "w", encoding="utf-8") as f:
                json.dump(self.template_groups, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving template groups: {e}")
            return False

    def get_template_group(self, group_id: str):
        for g in self.template_groups:
            if g.get("id") == group_id:
                return g
        return None

    def load_motion_groups(self):
        """加载运镜预设组合列表 [{"id": str, "name": str, "preset_ids": [str, ...]}]"""
        self.motion_groups = []
        if self.motion_groups_path.exists():
            try:
                with open(self.motion_groups_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, list):
                    for g in raw:
                        if isinstance(g, dict) and g.get("id") and g.get("name"):
                            self.motion_groups.append({
                                "id": str(g["id"]),
                                "name": str(g["name"]),
                                "preset_ids": [str(x) for x in (g.get("preset_ids") or []) if x],
                            })
            except Exception as e:
                print(f"Error loading motion groups: {e}")

    def save_motion_groups(self):
        try:
            with open(self.motion_groups_path, "w", encoding="utf-8") as f:
                json.dump(self.motion_groups, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error saving motion groups: {e}")
            return False

    def get_motion_group(self, group_id: str):
        for g in self.motion_groups:
            if g.get("id") == group_id:
                return g
        return None

    def load_batch_templates(self):
        if self.batch_templates_path.exists():
            try:
                with open(self.batch_templates_path, 'r', encoding='utf-8') as f:
                    self.batch_templates = json.load(f)
                if not self.batch_templates:
                    self.init_default_batch_templates()
                for t in self.batch_templates:
                    if "category" not in t:
                        t["category"] = ""
            except Exception as e:
                print(f'Error loading batch templates: {e}')
                self.init_default_batch_templates()
        else:
            self.init_default_batch_templates()

    def save_batch_templates(self):
        try:
            with open(self.batch_templates_path, 'w', encoding='utf-8') as f:
                json.dump(self.batch_templates, f, ensure_ascii=False, indent=2)
            self._sync_categories_from_templates()
            return True
        except Exception as e:
            print(f'Error saving batch templates: {e}')
            return False

    def init_default_batch_templates(self):
        self.batch_templates = [
            {
                'id': 'bt-01',
                'name': '默认批量模板',
                'content': 'A high quality image.',
                'category': ''
            }
        ]
        self.save_batch_templates()

    def load_batch_categories(self):
        if self.batch_categories_path.exists():
            try:
                with open(self.batch_categories_path, 'r', encoding='utf-8') as f:
                    cats = json.load(f)
                if isinstance(cats, list):
                    self.batch_categories = [str(c).strip() for c in cats if str(c).strip()]
            except Exception as e:
                print(f'Error loading batch categories: {e}')
                self.batch_categories = []
        self._sync_categories_from_templates()

    def _sync_categories_from_templates(self):
        changed = False
        for t in self.batch_templates:
            cat = str(t.get("category", "") or "").strip()
            if cat and cat not in self.batch_categories:
                self.batch_categories.append(cat)
                changed = True
        if changed:
            self.save_batch_categories()

    def save_batch_categories(self):
        try:
            with open(self.batch_categories_path, 'w', encoding='utf-8') as f:
                json.dump(self.batch_categories, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f'Error saving batch categories: {e}')
            return False

    def get_batch_categories(self):
        self._sync_categories_from_templates()
        return list(self.batch_categories)

    def add_batch_category(self, category_name: str):
        cat = (category_name or "").strip()
        if not cat:
            return False
        if cat not in self.batch_categories:
            self.batch_categories.append(cat)
            self.save_batch_categories()
        return True

    def delete_batch_category(self, category_name: str):
        cat = (category_name or "").strip()
        if not cat:
            return False
        if cat in self.batch_categories:
            self.batch_categories.remove(cat)
        for t in self.batch_templates:
            if (t.get("category") or "").strip() == cat:
                t["category"] = ""
        self.save_batch_templates()
        self.save_batch_categories()
        return True
