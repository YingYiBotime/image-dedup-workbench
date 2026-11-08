# -*- coding: utf-8 -*-
"""
EVE_IDT 国际化中英双语管理模块 (i18n.py)
文件说明: Eve_image_dedup_tool
支持实时动态切换语言（zh_CN 简体中文 / en_US English），并自动持久化用户偏好。
"""

import os
import sys
import json
import locale
from typing import Dict, Optional
from PySide6.QtCore import QObject, Signal

LANG_ZH = "zh_CN"
LANG_EN = "en_US"

STRINGS = {
    LANG_ZH: {
        # 通用与品牌
        "app_title": "EVE_IDT",
        "app_subtitle": "Eve_image_dedup_tool",
        "lang_switch_tooltip": "切换语言 / Switch Language",
        "theme_toggle_dark": "切换为浅色模式",
        "theme_toggle_light": "切换为深色模式",
        "btn_help": "使用指南与说明",
        "btn_close": "关闭",
        "btn_minimize": "最小化",
        "btn_maximize": "最大化",
        "btn_restore": "还原",
        "btn_ok": "我知道了",
        "btn_cancel": "取消",
        "btn_confirm": "确认",

        # 模式切换
        "mode_single": "单文件夹查重",
        "mode_cross": "跨文件夹交叉比对",

        # 准备态 (Phase 1)
        "folder1_placeholder": "选择或拖入文件夹 1",
        "folder2_placeholder": "选择或拖入文件夹 2",
        "subfolders_chk": "包含子文件夹",
        "subfolders_optional": "包含子文件夹 (可选)",
        "drop_title_1": "目标图像文件夹",
        "drop_title_2": "对比图像文件夹",
        "drop_tip_single": "单文件夹内部查重",
        "drop_tip_cross": "跨文件夹交叉对比",
        "drop_browse_tip": "拖入文件夹或点击浏览",
        "btn_start_scan": "开始智能查重",
        "scanning_status": "正在全自动扫描并分析特征...",
        "scanning_sub": "正在提取高维特征向量并执行局部特征对齐比对，请稍候...",

        # 灵敏度预设
        "sens_label": "灵敏度档位",
        "sens_strict": "严格模式",
        "sens_standard": "标准模式",
        "sens_loose": "深度宽松",
        "sens_btn_balanced": "均衡推荐",
        "sens_btn_detail": "展开详情",
        "sens_desc_standard": "兼顾原图与局部变体：精准检出完全相同、尺寸缩放压缩，以及加水印/换字、局部微调或局部调色的相似图片。",
        "sens_desc_strict": "严格精确匹配：仅检出构图完全一致、仅存在无损/轻微压缩缩放的高置信度重图。",
        "sens_desc_loose": "深度变体容忍：深度容忍大范围裁剪、大比例变形拉伸、复杂背景替换及大幅度局部重绘修改。",

        # 审查工作台 (Phase 2)
        # 左栏分组列表
        "groups_title": "相似图片分组",
        "search_placeholder": "搜索文件名或路径...",
        "sort_similarity": "按相似度从高到低",
        "sort_size": "按体积差异从大到小",
        "filter_all": "全部 ({})",
        "filter_pending": "待裁决 ({})",
        "filter_processed": "已处理 ({})",
        "filter_whitelisted": "保留白名单 ({})",
        "group_label": "第 {} 组",
        "similarity_pct": "{:.1f}% 相似",
        "tag_dimension_diff": "尺寸差异",
        "tag_size_diff": "体积差异",
        "tag_format_diff": "格式差异",
        "tag_exact_match": "完全匹配",
        "tag_partial_diff": "局部变体",
        "tag_whitelisted": "已保留",
        "tag_resolved": "已处理",

        # 中栏视口与浮动胶囊
        "btn_reset_zoom": "1:1 复位",
        "btn_sync_zoom": "联动缩放/平移",
        "btn_diff_heatmap": "差异热图",
        "btn_curtain_mode": "滑动卷帘对比",
        "btn_side_by_side": "并排对比",
        "btn_zoom_in": "放大 (+)",
        "btn_zoom_out": "缩小 (-)",
        "viewport_left_label": "原始图 (A)",
        "viewport_right_label": "对比图 (B)",

        # 底部决策栏
        "btn_keep_left": "仅保留左图 (A)",
        "btn_keep_right": "仅保留右图 (B)",
        "btn_keep_both": "两张均保留 (白名单)",
        "btn_delete_left": "删除左图",
        "btn_delete_right": "删除右图",
        "btn_undo": "撤销 (Ctrl+Z)",
        "tip_decision_keys": "快捷键：[1] 保留左图  [2] 保留右图  [Space] 两张均保留  [Ctrl+Z] 撤销",

        # 右栏属性详细对比
        "prop_panel_title": "图像参数详细比对",
        "prop_filename": "文件名",
        "prop_resolution": "分辨率",
        "prop_filesize": "文件体积",
        "prop_format": "图像格式",
        "prop_mtime": "修改时间",
        "prop_path": "存储路径",
        "prop_diff_larger": "体积较大",
        "prop_diff_smaller": "体积较小",
        "prop_diff_higher_res": "分辨率更高",
        "prop_diff_lower_res": "分辨率较低",

        # 底栏 Dock
        "dock_progress_label": "处理进度：{}/{} 组 ({:.0f}%)",
        "btn_prev_group": "← 上一组",
        "btn_next_group": "下一组 →",
        "btn_export": "导出查重明细",
        "btn_open_trash_dock": "打开回收暂存区",

        # 菜单栏与帮助中心
        "menu_theme": "切换深色 / 浅色模式... [F2]",
        "menu_about": "使用指南与常见问题 (白名单 / 找回已删图)... [F1]",
        "menu_license": "商业授权与机器码管理 (RSA-2048)...",
        "menu_check_updates": "检查版本更新 (OTA)...",
        "menu_export_groups": "导出分组副本至文件夹...",
        "menu_back_import": "返回准备与导入态视图",
        "menu_open_trash": "打开已删除图片回收暂存区 (staging_trash)...",
        "menu_open_logs": "打开运行日志与缓存目录 (%LOCALAPPDATA%)...",
        "menu_clear_cache": "清空保留白名单与特征缓存...",
        "help_dlg_title": "使用指南与常见问题帮助中心 — EVE_IDT v{}",

        # 吐司消息 (Toast)
        "toast_delete_success": "已安全移除 {} 张图片",
        "toast_delete_sub": "图片已移入软件内置回收暂存区 (可随时按 Ctrl+Z 恢复)",
        "toast_undo_success": "已成功恢复 {} 张图片",
        "toast_undo_fail": "没有可撤销的操作",
        "toast_whitelist_added": "已将当前图片组合加入保留白名单",
        "toast_whitelist_sub": "下次查重扫描将不再将此组合判定为重复",
        "toast_cache_cleared": "已清空所有白名单与特征缓存",
        "toast_cache_cleared_sub": "下次扫描将重新对所有相似图片进行完整检出",
    },

    LANG_EN: {
        # General & Branding
        "app_title": "EVE_IDT",
        "app_subtitle": "Eve_image_dedup_tool",
        "lang_switch_tooltip": "Switch Language / 切换语言",
        "theme_toggle_dark": "Switch to Light Mode",
        "theme_toggle_light": "Switch to Dark Mode",
        "btn_help": "User Guide & Help",
        "btn_close": "Close",
        "btn_minimize": "Minimize",
        "btn_maximize": "Maximize",
        "btn_restore": "Restore",
        "btn_ok": "Got it",
        "btn_cancel": "Cancel",
        "btn_confirm": "Confirm",

        # Mode Selection
        "mode_single": "Single Folder Scan",
        "mode_cross": "Cross-Folder Compare",

        # Preparation Phase (Phase 1)
        "folder1_placeholder": "Select or drag folder 1 here",
        "folder2_placeholder": "Select or drag folder 2 here",
        "subfolders_chk": "Include subfolders",
        "subfolders_optional": "Include subfolders (optional)",
        "drop_title_1": "Target Image Folder",
        "drop_title_2": "Comparison Image Folder",
        "drop_tip_single": "Single folder internal scan",
        "drop_tip_cross": "Cross-folder cross comparison",
        "drop_browse_tip": "Drag folder here or click to browse",
        "btn_start_scan": "Start Deduplication",
        "scanning_status": "Scanning and extracting features automatically...",
        "scanning_sub": "Aligning high-dimensional feature vectors and computing pairwise similarities, please wait...",

        # Sensitivity Presets
        "sens_label": "Sensitivity Preset",
        "sens_strict": "Strict",
        "sens_standard": "Standard",
        "sens_loose": "Loose",
        "sens_btn_balanced": "Balanced",
        "sens_btn_detail": "Details",
        "sens_desc_standard": "Balanced for exact and variant images: accurately detects identical images, rescaled/compressed versions, watermarks, text swaps, and local recoloring.",
        "sens_desc_strict": "Strict exact match: only flags near-identical images with identical composition and lossless or very minor compression.",
        "sens_desc_loose": "High variant tolerance: tolerates aggressive cropping, large aspect-ratio stretching, background replacement, and major local inpainting.",

        # Review Workbench (Phase 2)
        # Left sidebar groups
        "groups_title": "Duplicate Groups",
        "search_placeholder": "Search filename or path...",
        "sort_similarity": "Highest Similarity First",
        "sort_size": "Largest Size Difference First",
        "filter_all": "All ({})",
        "filter_pending": "Pending ({})",
        "filter_processed": "Resolved ({})",
        "filter_whitelisted": "Whitelist ({})",
        "group_label": "Group {}",
        "similarity_pct": "{:.1f}% Similar",
        "tag_dimension_diff": "Dimension Diff",
        "tag_size_diff": "Size Diff",
        "tag_format_diff": "Format Diff",
        "tag_exact_match": "Exact Match",
        "tag_partial_diff": "Partial Variant",
        "tag_whitelisted": "Whitelisted",
        "tag_resolved": "Resolved",

        # Center viewport & floating pill
        "btn_reset_zoom": "1:1 Reset",
        "btn_sync_zoom": "Sync Zoom/Pan",
        "btn_diff_heatmap": "Diff Heatmap",
        "btn_curtain_mode": "Curtain Slider",
        "btn_side_by_side": "Side-by-Side",
        "btn_zoom_in": "Zoom In (+)",
        "btn_zoom_out": "Zoom Out (-)",
        "viewport_left_label": "Original (A)",
        "viewport_right_label": "Comparison (B)",

        # Bottom decision bar
        "btn_keep_left": "Keep Left (A)",
        "btn_keep_right": "Keep Right (B)",
        "btn_keep_both": "Keep Both (Whitelist)",
        "btn_delete_left": "Trash Left",
        "btn_delete_right": "Trash Right",
        "btn_undo": "Undo (Ctrl+Z)",
        "tip_decision_keys": "Shortcuts: [1] Keep Left  [2] Keep Right  [Space] Keep Both  [Ctrl+Z] Undo",

        # Right properties comparison
        "prop_panel_title": "Properties Comparison",
        "prop_filename": "Filename",
        "prop_resolution": "Resolution",
        "prop_filesize": "File Size",
        "prop_format": "Image Format",
        "prop_mtime": "Date Modified",
        "prop_path": "File Path",
        "prop_diff_larger": "Larger file",
        "prop_diff_smaller": "Smaller file",
        "prop_diff_higher_res": "Higher resolution",
        "prop_diff_lower_res": "Lower resolution",

        # Bottom dock
        "dock_progress_label": "Progress: {}/{} groups ({:.0f}%)",
        "btn_prev_group": "← Previous",
        "btn_next_group": "Next →",
        "btn_export": "Export Report",
        "btn_open_trash_dock": "Open Trash",

        # Menu bar & Help
        "menu_theme": "Toggle Dark / Light Mode... [F2]",
        "menu_about": "User Guide & FAQ (Whitelist / Trash)... [F1]",
        "menu_license": "Commercial License & Machine ID (RSA-2048)...",
        "menu_check_updates": "Check for Updates (OTA)...",
        "menu_export_groups": "Export Group Copies to Folder...",
        "menu_back_import": "Return to Setup & Import View",
        "menu_open_trash": "Open Staging Trash Folder (staging_trash)...",
        "menu_open_logs": "Open Logs & Cache Directory (%LOCALAPPDATA%)...",
        "menu_clear_cache": "Clear Whitelist & Feature Caches...",
        "help_dlg_title": "User Guide & Help Center — EVE_IDT v{}",

        # Toast notifications
        "toast_delete_success": "Safely removed {} image(s)",
        "toast_delete_sub": "Files moved to staging trash (press Ctrl+Z anytime to undo)",
        "toast_undo_success": "Successfully restored {} image(s)",
        "toast_undo_fail": "No actions to undo",
        "toast_whitelist_added": "Added pair to whitelist",
        "toast_whitelist_sub": "This pair will not be flagged as duplicates in future scans",
        "toast_cache_cleared": "Cleared all whitelists and caches",
        "toast_cache_cleared_sub": "Next scan will perform fresh detection on all similar images",
    }
}


class I18nManager(QObject):
    """
    全局国际化语言管理器 (单例模式)
    负责存储当前语言状态、翻译查找、发射语言切换信号并自动持久化。
    """
    languageChanged = Signal(str)

    _instance = None

    @classmethod
    def get_instance(cls) -> "I18nManager":
        if cls._instance is None:
            cls._instance = I18nManager()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._current_lang = LANG_ZH
        self._settings_path = ""
        self._detect_initial_language()

    def set_settings_path(self, path: str):
        self._settings_path = path
        self._load_saved_language()

    def _detect_initial_language(self):
        """探测系统语言：如果系统为英文环境，则默认以英文启动"""
        try:
            sys_lang, _ = locale.getdefaultlocale()
            if sys_lang and "en" in sys_lang.lower():
                self._current_lang = LANG_EN
            else:
                self._current_lang = LANG_ZH
        except Exception:
            self._current_lang = LANG_ZH

    def _load_saved_language(self):
        if not self._settings_path or not os.path.isfile(self._settings_path):
            return
        try:
            with open(self._settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                lang = data.get("language")
                if lang in (LANG_ZH, LANG_EN):
                    self._current_lang = lang
        except Exception:
            pass

    def get_language(self) -> str:
        return self._current_lang

    def is_english(self) -> bool:
        return self._current_lang == LANG_EN

    def set_language(self, lang: str):
        if lang not in (LANG_ZH, LANG_EN) or lang == self._current_lang:
            return
        self._current_lang = lang
        self._save_language()
        self.languageChanged.emit(self._current_lang)

    def toggle_language(self) -> str:
        new_lang = LANG_EN if self._current_lang == LANG_ZH else LANG_ZH
        self.set_language(new_lang)
        return new_lang

    def _save_language(self):
        if not self._settings_path:
            return
        try:
            data = {}
            if os.path.isfile(self._settings_path):
                with open(self._settings_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            data["language"] = self._current_lang
            os.makedirs(os.path.dirname(self._settings_path), exist_ok=True)
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def t(self, key: str, *args, **kwargs) -> str:
        lang_dict = STRINGS.get(self._current_lang, STRINGS[LANG_ZH])
        template = lang_dict.get(key, STRINGS[LANG_ZH].get(key, key))
        if args or kwargs:
            try:
                return template.format(*args, **kwargs)
            except Exception:
                return template
        return template


# 全局便捷函数
def tr(key: str, *args, **kwargs) -> str:
    return I18nManager.get_instance().t(key, *args, **kwargs)


def get_current_lang() -> str:
    return I18nManager.get_instance().get_language()


def set_current_lang(lang: str):
    I18nManager.get_instance().set_language(lang)


def toggle_lang() -> str:
    return I18nManager.get_instance().toggle_language()
