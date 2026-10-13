# -*- coding: utf-8 -*-
"""
图像智能查重与对比工作站 - 核心检索引擎 (engine.py)
包含：
1. 四层金字塔图像查重流水线（MD5 + 多尺度空间色彩/边缘矩阵 + SIFT/RANSAC几何校验 + 防膨胀聚类）
2. 单文件夹内查重 & 双文件夹跨目录二分交叉比对（Bipartite Matching）
3. 系统临时目录特征持久化缓存与差分排除矩阵（实现毫秒/秒级复查，零原图目录污染）
4. 已核验保留白名单管理（Inherited Approvals）
5. 安全删除暂存与多级撤销恢复（Undo Stack）
6. 像素级差异热力透视图生成 & 自动按组建夹分类导出
"""

import os
import sys
import time
import uuid
import shutil
import pickle
import hashlib
import tempfile
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Set, Optional, Callable
from collections import defaultdict

import cv2
import numpy as np

from core_infra import AppPaths, SQLiteStateStore, setup_rotating_logger

VALID_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff')


@dataclass
class ImageItem:
    filepath: str
    filename: str
    folder_tag: str  # "文件夹1" or "文件夹2" or folder basename
    source_idx: int  # 1 for Folder 1, 2 for Folder 2
    filesize: int = 0
    mtime: float = 0.0
    width: int = 0
    height: int = 0
    md5: str = ""
    deleted: bool = False

    @property
    def resolution_str(self) -> str:
        return f"{self.width} × {self.height}"

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def size_str(self) -> str:
        if self.filesize >= 1024 * 1024:
            return f"{self.filesize / (1024 * 1024):.2f} MB"
        return f"{self.filesize / 1024:.1f} KB"

    @property
    def unique_key(self) -> str:
        return os.path.normcase(os.path.abspath(self.filepath))


@dataclass
class MatchGroup:
    group_id: int
    match_type: str  # "完全相同 (MD5)", "像素级同款", "同款设计/变体"
    items: List[ImageItem] = field(default_factory=list)
    max_inliers: int = 0
    max_good: int = 0
    best_score: float = 0.0
    min_mad: float = 0.0
    whitelisted: bool = False
    resolved: bool = False  # True when user kept 1 or marked whitelisted

    @property
    def active_items(self) -> List[ImageItem]:
        return [it for it in self.items if not it.deleted and os.path.exists(it.filepath)]

    @property
    def is_pending(self) -> bool:
        if self.whitelisted:
            return False
        active = self.active_items
        return len(active) > 1

    @property
    def similarity_pct(self) -> float:
        if "MD5" in self.match_type:
            return 100.0
        if "像素级" in self.match_type:
            mad_penalty = min(1.8, self.min_mad * 0.04)
            return round(max(98.0, 99.9 - mad_penalty), 1)
        # 同款设计/变体：综合内点与 MAD 映射至 88.0% ~ 97.9%
        inl_boost = min(6.5, self.max_inliers * 0.18)
        mad_pen = min(4.5, max(0.0, self.min_mad - 15.0) * 0.08)
        return round(min(97.9, max(88.0, 92.0 + inl_boost - mad_pen)), 1)

    @property
    def similarity_str(self) -> str:
        return f"{self.similarity_pct:.1f}%"

    @property
    def size_diff_bytes(self) -> int:
        active = self.active_items or self.items
        if len(active) < 2:
            return 0
        sizes = [it.filesize for it in active]
        return max(sizes) - min(sizes)



@dataclass
class UndoRecord:
    action_name: str
    restored_items: List[Tuple[ImageItem, str]]  # (ImageItem, backup_filepath)
    group_id: int


def read_cv2_image(filepath: str, grayscale: bool = False) -> Optional[np.ndarray]:
    """支持中文及特殊字符路径、超大尺寸及 CMYK 色彩空间的稳健图像读取"""
    try:
        with open(filepath, 'rb') as f:
            b = f.read()
        if not b:
            return None
        mode = cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR
        arr = cv2.imdecode(np.frombuffer(b, dtype=np.uint8), mode)
        if arr is not None:
            return arr
    except Exception:
        pass
    try:
        from PySide6.QtGui import QImage
        qimg = QImage(filepath)
        if qimg.isNull():
            return None
        qimg = qimg.convertToFormat(QImage.Format.Format_RGB888)
        w, h = qimg.width(), qimg.height()
        bpl = qimg.bytesPerLine()
        ptr = qimg.constBits()
        rgb = np.frombuffer(ptr, dtype=np.uint8).reshape((h, bpl))[:, :w * 3].reshape((h, w, 3)).copy()
        if grayscale:
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    except Exception:
        return None


def get_file_md5(filepath: str) -> str:
    h = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def compute_diff_visualization(path1: str, path2: str, size: Tuple[int, int] = (600, 600)) -> Optional[np.ndarray]:
    """
    生成两张图片的像素差异高亮透视图（BGR格式）：
    背景为半透明融合灰度图，差异显著区域以醒目的洋红/亮青色热力高亮显示。
    """
    im1 = read_cv2_image(path1, grayscale=False)
    im2 = read_cv2_image(path2, grayscale=False)
    if im1 is None or im2 is None:
        return None

    h, w = size[1], size[0]
    im1_r = cv2.resize(im1, (w, h), interpolation=cv2.INTER_AREA)
    im2_r = cv2.resize(im2, (w, h), interpolation=cv2.INTER_AREA)

    # 计算絕對差异
    diff = cv2.absdiff(im1_r, im2_r)
    diff_gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)

    # 抑制微小噪点，突出结构/文字差异
    _, mask = cv2.threshold(diff_gray, 25, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=1)

    # 底图：两张图灰度均值并调暗
    g1 = cv2.cvtColor(im1_r, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(im2_r, cv2.COLOR_BGR2GRAY)
    base_gray = ((g1.astype(np.float32) + g2.astype(np.float32)) * 0.25).astype(np.uint8)
    base_bgr = cv2.cvtColor(base_gray, cv2.COLOR_GRAY2BGR)

    # 热力映射
    heatmap = cv2.applyColorMap(np.clip(diff_gray * 2.5, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
    result = np.where(mask[:, :, None] > 0, heatmap, base_bgr)
    return result


class DedupEngine:
    """
    核心图像查重与跨文件夹交叉比对引擎（商业版架构）：
    - 用户状态与白名单持久化：%APPDATA%\\TableclothDedupPro\\data\\app_state.db (SQLite WAL)
    - 高速特征缓存与回收暂存区：%LOCALAPPDATA%\\TableclothDedupPro\\cache / staging_trash
    - 严禁污染用户原图目录或 Program Files 安装目录
    """

    def __init__(self, paths: Optional[AppPaths] = None):
        self.paths = paths or AppPaths()
        self.logger = setup_rotating_logger(self.paths)
        self.state_store = SQLiteStateStore(self.paths.sqlite_db_path, self.logger)

        self.app_cache_root = self.paths.local_root
        self.feat_cache_dir = self.paths.feat_cache_dir
        self.trash_dir = self.paths.trash_dir

        # 自动迁移旧版 %TEMP% 下的 .pkl 白名单数据至 SQLite
        self._migrate_legacy_temp_pickles()

        self.whitelist_pairs: Set[Tuple[str, str]] = self.state_store.load_pairs("whitelist")
        self.excluded_pairs: Set[Tuple[str, str]] = self.state_store.load_pairs("exclusion")
        self.undo_stack: List[UndoRecord] = []
        self.logger.info(
            f"DedupEngine initialized | whitelist={len(self.whitelist_pairs)} pairs | "
            f"excluded={len(self.excluded_pairs)} pairs | db={self.paths.sqlite_db_path}"
        )

    def _migrate_legacy_temp_pickles(self):
        if self.state_store.get_setting("legacy_temp_migrated", False):
            return
        legacy_root = os.path.join(tempfile.gettempdir(), "TableclothDedupWorkstation")
        legacy_wl = os.path.join(legacy_root, "verified_whitelist.pkl")
        legacy_ex = os.path.join(legacy_root, "verified_exclusions.pkl")
        for rel_type, fpath in (("whitelist", legacy_wl), ("exclusion", legacy_ex)):
            if os.path.exists(fpath):
                try:
                    with open(fpath, 'rb') as f:
                        data = pickle.load(f)
                    if isinstance(data, set) and data:
                        existing = self.state_store.load_pairs(rel_type)
                        self.state_store.save_pairs(rel_type, existing | data)
                        self.logger.info(f"Migrated {len(data)} {rel_type} pairs from legacy %TEMP% pickle to SQLite.")
                except Exception as e:
                    self.logger.warning(f"Failed to migrate legacy {rel_type} pickle: {e}")
        self.state_store.set_setting("legacy_temp_migrated", True)

    @staticmethod
    def make_pair_key(key1: str, key2: str) -> Tuple[str, str]:
        return (key1, key2) if key1 <= key2 else (key2, key1)

    def add_group_to_whitelist(self, group: MatchGroup):
        """将某组内所有当前存活的图片对加入已核验白名单（写入 SQLite）"""
        active = group.active_items
        for i in range(len(active)):
            for j in range(i + 1, len(active)):
                pk = self.make_pair_key(active[i].unique_key, active[j].unique_key)
                self.whitelist_pairs.add(pk)
        group.whitelisted = True
        group.resolved = True
        self.state_store.save_pairs("whitelist", self.whitelist_pairs)
        self.logger.info(f"Group #{group.group_id} added to whitelist (total pairs: {len(self.whitelist_pairs)})")

    def remove_group_from_whitelist(self, group: MatchGroup):
        """将某组从白名单中移除（同步更新 SQLite）"""
        for i in range(len(group.items)):
            for j in range(i + 1, len(group.items)):
                pk = self.make_pair_key(group.items[i].unique_key, group.items[j].unique_key)
                self.whitelist_pairs.discard(pk)
        group.whitelisted = False
        group.resolved = False
        self.state_store.save_pairs("whitelist", self.whitelist_pairs)
        self.logger.info(f"Group #{group.group_id} removed from whitelist")

    def clear_whitelist(self):
        self.whitelist_pairs.clear()
        self.state_store.clear_pairs("whitelist")
        self.logger.info("All whitelist pairs cleared from SQLite.")

    def clear_all_caches(self):
        self.excluded_pairs.clear()
        self.state_store.clear_pairs("exclusion")
        removed = 0
        for fn in os.listdir(self.feat_cache_dir):
            try:
                os.remove(os.path.join(self.feat_cache_dir, fn))
                removed += 1
            except Exception as e:
                self.logger.warning(f"Failed to remove cache file {fn}: {e}")
        self.logger.info(f"Cleared all feature caches ({removed} files) and exclusion matrix.")

    def delete_items(self, items: List[ImageItem], group_id: int, action_name: str = "删除图片") -> Tuple[bool, str]:
        """
        安全删除指定图片（移至内部回收暂存区以支持 100% 瞬间撤销恢复）
        """
        restored_list = []
        for item in items:
            if item.deleted or not os.path.exists(item.filepath):
                continue
            try:
                ext = os.path.splitext(item.filename)[1]
                backup_name = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}{ext}"
                backup_path = os.path.join(self.trash_dir, backup_name)
                shutil.move(item.filepath, backup_path)
                item.deleted = True
                restored_list.append((item, backup_path))
            except Exception as e:
                return False, f"删除文件 {item.filename} 失败: {str(e)}"

        if restored_list:
            self.undo_stack.append(UndoRecord(
                action_name=action_name,
                restored_items=restored_list,
                group_id=group_id
            ))
            return True, f"已安全移除 {len(restored_list)} 张图片（可随时按 Ctrl+Z 撤销）"
        return False, "没有可删除的文件"

    def undo_last_delete(self) -> Tuple[bool, str, Optional[int]]:
        """撤销最近一次删除操作，将文件原路恢复"""
        if not self.undo_stack:
            return False, "当前没有可撤销的删除操作", None

        record = self.undo_stack.pop()
        restored_count = 0
        for item, backup_path in record.restored_items:
            if os.path.exists(backup_path):
                try:
                    os.makedirs(os.path.dirname(item.filepath), exist_ok=True)
                    shutil.move(backup_path, item.filepath)
                    item.deleted = False
                    restored_count += 1
                except Exception as e:
                    return False, f"恢复文件 {item.filename} 失败: {str(e)}", record.group_id

        return True, f"已成功恢复 {restored_count} 张图片 ({record.action_name})", record.group_id

    def _get_folder_cache_path(self, folder_path: str) -> str:
        norm_p = os.path.normcase(os.path.abspath(folder_path))
        h = hashlib.md5(norm_p.encode('utf-8')).hexdigest()[:16]
        return os.path.join(self.feat_cache_dir, f"folder_{h}.pkl")

    def _extract_single_feature(self, filepath: str) -> Optional[Dict]:
        im = read_cv2_image(filepath, grayscale=False)
        if im is None or im.size == 0:
            return None
        orig_h, orig_w = im.shape[:2]
        im_std = cv2.resize(im, (256, 256), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(im_std, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(im_std, cv2.COLOR_BGR2GRAY)

        # 1. 3x3 全图空间网格 HSV 直方图 (9 * 64 = 576 维)
        grid_hists = []
        for r in range(3):
            for c in range(3):
                sub = hsv[r * 85:(r + 1) * 85, c * 85:(c + 1) * 85]
                sh = cv2.calcHist([sub], [0, 1, 2], None, [4, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
                sh /= (sh.sum() + 1e-7)
                grid_hists.append(sh)
        gh = np.concatenate(grid_hists).astype(np.float32)

        # 2. 中心 75% 核心区 2x2 空间 HSV 直方图 (4 * 64 = 256 维，抵抗上下/左右裁切或长宽比拉伸)
        hsv_core = hsv[32:224, 32:224]
        core_hists = []
        for r in range(2):
            for c in range(2):
                sub = hsv_core[r * 96:(r + 1) * 96, c * 96:(c + 1) * 96]
                sh = cv2.calcHist([sub], [0, 1, 2], None, [4, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
                sh /= (sh.sum() + 1e-7)
                core_hists.append(sh)
        c_gh = np.concatenate(core_hists).astype(np.float32)

        # 3. 2D-DCT 低频感知向量 (63 维连续 pHash，对 10倍以上跨分辨率缩放与 10%~20% 比例拉伸高度鲁棒)
        g32 = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
        dct_mat = cv2.dct(g32)
        dct_vec = dct_mat[:8, :8].flatten()[1:]
        dct_norm = (dct_vec / (np.linalg.norm(dct_vec) + 1e-7)).astype(np.float32)

        # 4. 水平+垂直双向梯度结构特征 (128 维连续 dHash)
        g9 = cv2.resize(gray, (9, 9), interpolation=cv2.INTER_AREA).astype(np.float32)
        dh = (g9[:8, 1:9] - g9[:8, 0:8]).flatten()
        dv = (g9[1:9, :8] - g9[0:8, :8]).flatten()
        dhash_vec = np.concatenate([dh, dv])
        dhash_norm = (dhash_vec / (np.linalg.norm(dhash_vec) + 1e-7)).astype(np.float32)

        # 5. Sobel 梯度能量 + 高斯空间池化轮廓 (1024 维，避免单像素 Canny 在长宽比变化时错位失配)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        mag = cv2.magnitude(gx, gy)
        mag_blur = cv2.GaussianBlur(mag, (9, 9), 0)
        edges_small = cv2.resize(mag_blur, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32).flatten()
        edges_zm = edges_small - edges_small.mean()
        edges_norm = (edges_zm / (np.linalg.norm(edges_zm) + 1e-7)).astype(np.float32)

        # 6. 低频灰度 32x32 (1024 维)
        g_small = g32.flatten()
        g_zm = g_small - g_small.mean()
        g_norm = (g_zm / (np.linalg.norm(g_zm) + 1e-7)).astype(np.float32)

        # 7. 缩略像素图用于对齐 MAD 计算 (128x128x3) 与 SIFT 预缩放灰度缓存 (避免重复从磁盘解码 8000px 大图)
        thumb_mad = cv2.resize(im_std, (128, 128), interpolation=cv2.INTER_AREA)
        im_400 = cv2.resize(im, (400, 400), interpolation=cv2.INTER_AREA)
        gray_400 = cv2.cvtColor(im_400, cv2.COLOR_BGR2GRAY)
        ok_enc, sift_buf = cv2.imencode('.jpg', gray_400, [int(cv2.IMWRITE_JPEG_QUALITY), 92])

        return {
            'ver': 3,
            'width': orig_w,
            'height': orig_h,
            'gh': gh,
            'c_gh': c_gh,
            'dct': dct_norm,
            'dhash': dhash_norm,
            'edges': edges_norm,
            'gray': g_norm,
            'thumb_mad': thumb_mad,
            'sift_jpg': sift_buf if ok_enc else None
        }

    @staticmethod
    def _folder_has_subdirs(folder_path: str) -> bool:
        skip_dirs = {'.cache_finder', '__pycache__', '$RECYCLE.BIN', 'System Volume Information', '.git'}
        try:
            for d in os.listdir(folder_path):
                if not d.startswith('.') and d not in skip_dirs:
                    if os.path.isdir(os.path.join(folder_path, d)):
                        return True
        except Exception:
            pass
        return False

    def load_or_extract_folder(
        self,
        folder_path: str,
        folder_tag: str,
        source_idx: int,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        include_subfolders: bool = False
    ) -> Tuple[List[ImageItem], Dict[str, Dict]]:
        """
        加载或增量提取文件夹内图像的特征（默认仅扫描当前顶层目录；开启 include_subfolders 时递归扫描子文件夹）
        """
        legacy_cache = os.path.join(folder_path, ".cache_finder")
        if os.path.isdir(legacy_cache):
            try:
                shutil.rmtree(legacy_cache, ignore_errors=True)
            except Exception:
                pass

        all_entries: List[Tuple[str, str]] = []
        skip_dirs = {'.cache_finder', '__pycache__', '$RECYCLE.BIN', 'System Volume Information', '.git'}
        if include_subfolders:
            for root, dirs, files in os.walk(folder_path):
                dirs[:] = [d for d in dirs if not d.startswith('.') and d not in skip_dirs]
                for f in files:
                    if os.path.splitext(f)[1].lower() in VALID_EXTS:
                        fp = os.path.join(root, f)
                        if os.path.isfile(fp):
                            rel_fn = os.path.relpath(fp, folder_path)
                            all_entries.append((rel_fn, fp))
        else:
            try:
                for f in os.listdir(folder_path):
                    if os.path.splitext(f)[1].lower() in VALID_EXTS:
                        fp = os.path.join(folder_path, f)
                        if os.path.isfile(fp):
                            all_entries.append((f, fp))
            except Exception:
                pass

        all_entries.sort(key=lambda x: x[0])

        cache_path = self._get_folder_cache_path(folder_path)
        cached_data: Dict[str, Dict] = {}
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    cached_data = pickle.load(f)
            except Exception:
                cached_data = {}

        items: List[ImageItem] = []
        features: Dict[str, Dict] = {}
        new_Cache: Dict[str, Dict] = dict(cached_data) if isinstance(cached_data, dict) else {}
        dirty = False
        total = len(all_entries)

        for idx, (rel_fn, fp) in enumerate(all_entries):
            try:
                st = os.stat(fp)
                fsize = st.st_size
                fmtime = st.st_mtime
            except Exception:
                continue

            if progress_cb and (idx % 12 == 0 or idx == total - 1):
                progress_cb(idx + 1, total, f"正在扫描特征 [{folder_tag}]: {rel_fn} ({idx + 1}/{total})")

            rec = cached_data.get(rel_fn)
            if (
                rec
                and rec.get('filesize') == fsize
                and abs(rec.get('mtime', 0.0) - fmtime) < 1e-3
                and isinstance(rec.get('feat'), dict)
                and rec['feat'].get('ver') == 3
            ):
                feat = rec['feat']
                md5_val = rec.get('md5') or get_file_md5(fp)
                new_Cache[rel_fn] = rec
            else:
                feat = self._extract_single_feature(fp)
                if feat is None:
                    continue
                md5_val = get_file_md5(fp)
                new_Cache[rel_fn] = {
                    'filesize': fsize,
                    'mtime': fmtime,
                    'md5': md5_val,
                    'feat': feat
                }
                dirty = True

            item = ImageItem(
                filepath=fp,
                filename=rel_fn,
                folder_tag=folder_tag,
                source_idx=source_idx,
                filesize=fsize,
                mtime=fmtime,
                width=feat['width'],
                height=feat['height'],
                md5=md5_val
            )
            items.append(item)
            features[item.unique_key] = feat

        if dirty:
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump(new_Cache, f)
            except Exception:
                pass

        return items, features

    @staticmethod
    def _zero_mean_unit_rows(mat: np.ndarray) -> np.ndarray:
        zm = mat - mat.mean(axis=1, keepdims=True)
        return zm / (np.linalg.norm(zm, axis=1, keepdims=True) + 1e-7)

    def _compute_similarity_matrices(
        self,
        keys_a: List[str],
        feats_a: Dict[str, Dict],
        keys_b: List[str],
        feats_b: Dict[str, Dict]
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """计算多尺度感知相似度矩阵：(综合得分 comp, 最佳色彩 best_gh, 边缘能量 sim_ed, 最佳结构 best_struct)"""
        GH_a = self._zero_mean_unit_rows(np.array([feats_a[k]['gh'] for k in keys_a], dtype=np.float32))
        GH_b = self._zero_mean_unit_rows(np.array([feats_b[k]['gh'] for k in keys_b], dtype=np.float32))
        sim_gh = np.dot(GH_a, GH_b.T)

        CGH_a = self._zero_mean_unit_rows(np.array([feats_a[k]['c_gh'] for k in keys_a], dtype=np.float32))
        CGH_b = self._zero_mean_unit_rows(np.array([feats_b[k]['c_gh'] for k in keys_b], dtype=np.float32))
        sim_cgh = np.dot(CGH_a, CGH_b.T)

        best_gh = np.maximum(sim_gh, sim_cgh)

        ED_a = np.array([feats_a[k]['edges'] for k in keys_a], dtype=np.float32)
        ED_b = np.array([feats_b[k]['edges'] for k in keys_b], dtype=np.float32)
        sim_ed = np.dot(ED_a, ED_b.T)

        GR_a = np.array([feats_a[k]['gray'] for k in keys_a], dtype=np.float32)
        GR_b = np.array([feats_b[k]['gray'] for k in keys_b], dtype=np.float32)
        sim_gr = np.dot(GR_a, GR_b.T)

        DCT_a = np.array([feats_a[k]['dct'] for k in keys_a], dtype=np.float32)
        DCT_b = np.array([feats_b[k]['dct'] for k in keys_b], dtype=np.float32)
        sim_dct = np.dot(DCT_a, DCT_b.T)

        DH_a = np.array([feats_a[k]['dhash'] for k in keys_a], dtype=np.float32)
        DH_b = np.array([feats_b[k]['dhash'] for k in keys_b], dtype=np.float32)
        sim_dh = np.dot(DH_a, DH_b.T)

        best_struct = np.maximum(sim_dct, sim_dh)
        comp = 0.40 * best_gh + 0.25 * np.maximum(sim_gr, sim_dct) + 0.20 * sim_ed + 0.15 * best_struct
        return comp, best_gh, sim_ed, best_struct

    @staticmethod
    def _compute_aligned_mad(
        t1: np.ndarray,
        t2: np.ndarray,
        H_400: Optional[np.ndarray] = None
    ) -> float:
        """
        计算抵抗长宽比拉伸(Ratio 90%)、边缘裁切与平移错位的最小有效像素差 (Effective MAD)：
        1. 原始全局 MAD
        2. 若存在 SIFT 单应性矩阵 H_400，将其映射至 128x128 空间对齐后计算重叠区 MAD
        3. 中心窗口多方向平移与上下/左右 10% 裁切重采样对齐 MAD
        """
        best_mad = float(np.mean(np.abs(t1 - t2)))

        # 单应性几何配准后的重叠区像素差
        if H_400 is not None:
            try:
                S = np.array([[128.0 / 400.0, 0.0, 0.0], [0.0, 128.0 / 400.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
                S_inv = np.array([[400.0 / 128.0, 0.0, 0.0], [0.0, 400.0 / 128.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
                H_128 = S @ H_400 @ S_inv
                warped_t1 = cv2.warpPerspective(t1, H_128, (128, 128), flags=cv2.INTER_LINEAR)
                ones_mask = np.ones((128, 128), dtype=np.uint8)
                valid_mask = cv2.warpPerspective(ones_mask, H_128, (128, 128), flags=cv2.INTER_NEAREST)
                valid_inner = valid_mask[4:124, 4:124] > 0
                if int(np.sum(valid_inner)) >= 4200:
                    diff_inner = np.abs(warped_t1[4:124, 4:124] - t2[4:124, 4:124])
                    h_mad = float(np.mean(diff_inner[valid_inner]))
                    if h_mad < best_mad:
                        best_mad = h_mad
            except Exception:
                pass

        # 上下或左右裁切 ~10% (对应 Ratio 90% 长宽比差异) 的重采样对齐检测
        for y0, y1 in ((12, 128), (0, 116), (6, 122)):
            t1_crop = cv2.resize(t1[y0:y1, :], (128, 128), interpolation=cv2.INTER_AREA)
            best_mad = min(best_mad, float(np.mean(np.abs(t1_crop - t2))))
            t2_crop = cv2.resize(t2[y0:y1, :], (128, 128), interpolation=cv2.INTER_AREA)
            best_mad = min(best_mad, float(np.mean(np.abs(t1 - t2_crop))))

        # 中心核心区 [20:108, 20:108] 平移搜索
        c1 = t1[20:108, 20:108]
        for dy in (-12, -6, 0, 6, 12):
            for dx in (-8, 0, 8):
                if dy == 0 and dx == 0:
                    continue
                sub2 = t2[20 + dy:108 + dy, 20 + dx:108 + dx]
                c_mad = float(np.mean(np.abs(c1 - sub2)))
                if c_mad < best_mad:
                    best_mad = c_mad

        return best_mad

    def run_scan(
        self,
        folder1: str,
        folder2: Optional[str] = None,
        sensitivity: str = "standard",  # "strict", "standard", "deep" / "loose"
        is_recheck: bool = False,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        include_subfolders: bool = False
    ) -> Tuple[List[MatchGroup], Dict]:
        """
        执行单文件夹或跨文件夹比对（默认仅扫描当前文件夹顶层图片；include_subfolders=True 时递归扫描子文件夹）
        返回: (groups, stats_dict)
        """
        t_start = time.time()
        is_cross = bool(folder2 and os.path.isdir(folder2))

        if not is_recheck:
            # 全新扫描时清空非相似排除矩阵，但保留用户已确认的白名单
            self.excluded_pairs.clear()

        tag1 = f"文件夹1({os.path.basename(folder1.rstrip('/\\'))})" if is_cross else os.path.basename(folder1.rstrip('/\\'))
        items1, feats1 = self.load_or_extract_folder(
            folder1, tag1, 1, progress_cb, include_subfolders=include_subfolders
        )
        has_subdirs = self._folder_has_subdirs(folder1)

        items2: List[ImageItem] = []
        feats2: Dict[str, Dict] = {}
        if is_cross and folder2:
            tag2 = f"文件夹2({os.path.basename(folder2.rstrip('/\\'))})"
            items2, feats2 = self.load_or_extract_folder(
                folder2, tag2, 2, progress_cb, include_subfolders=include_subfolders
            )
            has_subdirs = has_subdirs or self._folder_has_subdirs(folder2)

        all_feats = {**feats1, **feats2}
        all_items_map: Dict[str, ImageItem] = {it.unique_key: it for it in (items1 + items2)}

        # 参数预设（兼容 UI 层的 "deep" 与旧版 "loose" 标识）
        if sensitivity == "strict":
            comp_thresh = 0.82
            gh_thresh = 0.94
            dct_thresh = 0.88
            inlier_thresh = 10
        elif sensitivity in ("deep", "loose"):
            comp_thresh = 0.62
            gh_thresh = 0.80
            dct_thresh = 0.72
            inlier_thresh = 5
        else:  # standard
            comp_thresh = 0.72
            gh_thresh = 0.88
            dct_thresh = 0.80
            inlier_thresh = 7

        verified_links: List[Dict] = []
        md5_matched_pairs: Set[Tuple[str, str]] = set()

        # ==================== 第一阶段：MD5 精确匹配 ====================
        if progress_cb:
            progress_cb(30, 100, "正在执行第一层：MD5 字节级精确比对...")

        if not is_cross:
            md5_groups = defaultdict(list)
            for it in items1:
                if it.md5:
                    md5_groups[it.md5].append(it)
            for m_val, grp in md5_groups.items():
                if len(grp) > 1:
                    for i in range(len(grp)):
                        for j in range(i + 1, len(grp)):
                            if grp[i].unique_key == grp[j].unique_key:
                                continue
                            pk = self.make_pair_key(grp[i].unique_key, grp[j].unique_key)
                            md5_matched_pairs.add(pk)
                            if pk not in self.whitelist_pairs:
                                verified_links.append({
                                    'k1': grp[i].unique_key,
                                    'k2': grp[j].unique_key,
                                    'inliers': 999,
                                    'good': 999,
                                    'mad': 0.0,
                                    'score': 1.0,
                                    'is_md5': True
                                })
        else:
            md5_map2 = defaultdict(list)
            for it2 in items2:
                if it2.md5:
                    md5_map2[it2.md5].append(it2)
            for it1 in items1:
                if it1.md5 and it1.md5 in md5_map2:
                    for it2 in md5_map2[it1.md5]:
                        if it1.unique_key == it2.unique_key:
                            continue
                        pk = self.make_pair_key(it1.unique_key, it2.unique_key)
                        md5_matched_pairs.add(pk)
                        if pk not in self.whitelist_pairs:
                            verified_links.append({
                                'k1': it1.unique_key,
                                'k2': it2.unique_key,
                                'inliers': 999,
                                'good': 999,
                                'mad': 0.0,
                                'score': 1.0,
                                'is_md5': True
                            })

        # ==================== 第二阶段：多尺度感知特征矩阵点乘 ====================
        if progress_cb:
            progress_cb(50, 100, "正在执行第二层：多尺度空间色彩、DCT感知与梯度矩阵高速交叉比对...")

        candidates = []
        if not is_cross and len(items1) >= 2:
            keys1 = [it.unique_key for it in items1]
            comp, best_gh, sim_ed, best_struct = self._compute_similarity_matrices(keys1, feats1, keys1, feats1)
            triu_i, triu_j = np.triu_indices(len(keys1), k=1)

            c_comp = comp[triu_i, triu_j]
            c_gh = best_gh[triu_i, triu_j]
            c_ed = sim_ed[triu_i, triu_j]
            c_st = best_struct[triu_i, triu_j]

            mask = (
                (c_comp >= comp_thresh) |
                ((c_gh >= gh_thresh) & (c_ed >= 0.50)) |
                ((c_st >= dct_thresh) & (c_gh >= (gh_thresh - 0.08))) |
                ((c_ed >= 0.75) & (c_gh >= 0.80))
            )
            cand_idx = np.where(mask)[0]
            for idx in cand_idx:
                i, j = triu_i[idx], triu_j[idx]
                k1, k2 = keys1[i], keys1[j]
                if k1 == k2:
                    continue
                pk = self.make_pair_key(k1, k2)
                if pk in md5_matched_pairs or pk in self.whitelist_pairs:
                    continue
                if is_recheck and pk in self.excluded_pairs:
                    continue
                candidates.append((k1, k2, float(c_comp[idx]), float(c_gh[idx]), float(c_ed[idx]), float(c_st[idx])))

        elif is_cross and len(items1) >= 1 and len(items2) >= 1:
            keys1 = [it.unique_key for it in items1]
            keys2 = [it.unique_key for it in items2]
            comp, best_gh, sim_ed, best_struct = self._compute_similarity_matrices(keys1, feats1, keys2, feats2)

            mask = (
                (comp >= comp_thresh) |
                ((best_gh >= gh_thresh) & (sim_ed >= 0.50)) |
                ((best_struct >= dct_thresh) & (best_gh >= (gh_thresh - 0.08))) |
                ((sim_ed >= 0.75) & (best_gh >= 0.80))
            )
            r_idx, c_idx = np.where(mask)
            for idx in range(len(r_idx)):
                r, c = r_idx[idx], c_idx[idx]
                k1, k2 = keys1[r], keys2[c]
                if k1 == k2:
                    continue
                pk = self.make_pair_key(k1, k2)
                if pk in md5_matched_pairs or pk in self.whitelist_pairs:
                    continue
                if is_recheck and pk in self.excluded_pairs:
                    continue
                candidates.append((k1, k2, float(comp[r, c]), float(best_gh[r, c]), float(sim_ed[r, c]), float(best_struct[r, c])))

        # ==================== 第三阶段：SIFT + RANSAC 几何配准与对齐像素差校验 ====================
        unique_cand_keys = sorted(list(set([c[0] for c in candidates] + [c[1] for c in candidates])))
        sift = cv2.SIFT_create(nfeatures=1200, contrastThreshold=0.03)
        bf = cv2.BFMatcher(cv2.NORM_L2)
        sift_cache: Dict[str, Tuple] = {}

        total_u = len(unique_cand_keys)
        for idx, uk in enumerate(unique_cand_keys):
            if progress_cb and (idx % 10 == 0 or idx == total_u - 1):
                fn_disp = all_items_map[uk].filename
                progress_cb(60 + int(30 * (idx + 1) / max(1, total_u)), 100, f"正在提取 SIFT 几何关键点 ({idx + 1}/{total_u}): {fn_disp}")

            g_res = None
            sift_buf = all_feats[uk].get('sift_jpg')
            if sift_buf is not None:
                try:
                    g_res = cv2.imdecode(sift_buf, cv2.IMREAD_GRAYSCALE)
                except Exception:
                    g_res = None
            if g_res is None:
                g = read_cv2_image(all_items_map[uk].filepath, grayscale=True)
                if g is not None:
                    g_res = cv2.resize(g, (400, 400), interpolation=cv2.INTER_AREA)
            if g_res is not None:
                sift_cache[uk] = sift.detectAndCompute(g_res, None)

        for k1, k2, score, gh, ed, st_sim in candidates:
            kp1, des1 = sift_cache.get(k1, (None, None))
            kp2, des2 = sift_cache.get(k2, (None, None))

            good = []
            inliers = 0
            H_mat = None

            if des1 is not None and des2 is not None and len(des1) >= 4 and len(des2) >= 4:
                raw_matches = bf.knnMatch(des1, des2, k=2)
                good = [pair[0] for pair in raw_matches if len(pair) == 2 and pair[0].distance < 0.78 * pair[1].distance]

                if len(good) >= 4:
                    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
                    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
                    H_mat, mask_r = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 6.0)
                    if mask_r is not None:
                        inliers = int(np.sum(mask_r))

            t1 = all_feats[k1]['thumb_mad'].astype(np.float32)
            t2 = all_feats[k2]['thumb_mad'].astype(np.float32)
            mad = self._compute_aligned_mad(t1, t2, H_mat)

            # 多维几何与对齐像素双重判定（兼容 10x 极端分辨率差距、90% 长宽比变形与边缘裁切，同时杜绝异图误报）
            is_valid_match = False
            if inliers >= 14:
                is_valid_match = True
            elif inliers >= inlier_thresh and (mad <= 38.0 or score >= (comp_thresh + 0.03) or gh >= 0.90 or st_sim >= 0.84):
                is_valid_match = True
            elif inliers >= max(4, inlier_thresh - 2) and mad <= 26.0 and (gh >= 0.86 or st_sim >= 0.82):
                is_valid_match = True
            elif len(good) >= 24 and mad <= 30.0 and gh >= 0.92:
                is_valid_match = True
            elif mad <= 15.0 and st_sim >= 0.90 and gh >= 0.90:
                is_valid_match = True
            elif sensitivity in ("deep", "loose") and inliers >= 4 and (mad <= 34.0 or st_sim >= 0.80) and gh >= 0.82:
                is_valid_match = True

            pk = self.make_pair_key(k1, k2)
            if is_valid_match:
                verified_links.append({
                    'k1': k1,
                    'k2': k2,
                    'inliers': inliers,
                    'good': len(good),
                    'mad': mad,
                    'score': score,
                    'is_md5': False
                })
            else:
                self.excluded_pairs.add(pk)

        self.state_store.save_pairs("exclusion", self.excluded_pairs)
        self.logger.info(
            f"Scan SIFT stage finished | items1={len(items1)} | items2={len(items2)} | "
            f"candidates={len(candidates)} | verified_links={len(verified_links)} | excluded={len(self.excluded_pairs)}"
        )

        # ==================== 第四阶段：防传递性链式膨胀聚类 ====================
        if progress_cb:
            progress_cb(95, 100, "正在执行第四层：构建精准同款聚类分组...")

        groups = self._cluster_verified_links(verified_links, all_items_map)

        elapsed = time.time() - t_start
        stats = {
            'elapsed': elapsed,
            'count1': len(items1),
            'count2': len(items2),
            'is_cross': is_cross,
            'include_subfolders': include_subfolders,
            'has_subdirs': has_subdirs,
            'total_groups': len(groups),
            'total_images_in_groups': sum(len(g.items) for g in groups),
            'candidates_checked': len(candidates)
        }
        if progress_cb:
            progress_cb(100, 100, f"扫描完成！耗时 {elapsed:.2f} 秒，共检出 {len(groups)} 组相似/重复图片。")

        return groups, stats

    def _cluster_verified_links(self, links: List[Dict], items_map: Dict[str, ImageItem]) -> List[MatchGroup]:
        """
        防传递性链式膨胀的图聚类算法：
        按照匹配强度（MD5 -> 高内点 -> 低MAD）从高到低合并，
        限制单组无强连接时的无限传递扩张。
        """
        if not links:
            return []

        links.sort(key=lambda x: (-int(x['is_md5']), -x['inliers'], x['mad'], -x['score']))

        adj: Dict[Tuple[str, str], Dict] = {}
        for lk in links:
            pk = self.make_pair_key(lk['k1'], lk['k2'])
            if pk not in adj or lk['inliers'] > adj[pk]['inliers']:
                adj[pk] = lk

        node_to_cluster: Dict[str, List[str]] = {}
        clusters: List[List[str]] = []

        for lk in links:
            k1, k2 = lk['k1'], lk['k2']
            c1 = node_to_cluster.get(k1)
            c2 = node_to_cluster.get(k2)

            if c1 is None and c2 is None:
                new_c = [k1, k2]
                clusters.append(new_c)
                node_to_cluster[k1] = new_c
                node_to_cluster[k2] = new_c
            elif c1 is not None and c2 is None:
                # 检查 k2 是否与 c1 中至少一半节点有连接，或者当前边极强 (inliers >= 16)
                if len(c1) < 6 and (lk['inliers'] >= 16 or self._has_strong_tie(k2, c1, adj)):
                    c1.append(k2)
                    node_to_cluster[k2] = c1
            elif c2 is not None and c1 is None:
                if len(c2) < 6 and (lk['inliers'] >= 16 or self._has_strong_tie(k1, c2, adj)):
                    c2.append(k1)
                    node_to_cluster[k1] = c2
            elif c1 is not c2 and c1 is not None and c2 is not None:
                if len(c1) + len(c2) <= 6 and lk['inliers'] >= 18:
                    c1.extend(c2)
                    for k in c2:
                        node_to_cluster[k] = c1
                    clusters.remove(c2)

        match_groups: List[MatchGroup] = []
        for idx, cl_keys in enumerate(clusters):
            if len(cl_keys) < 2:
                continue
            grp_items = [items_map[k] for k in cl_keys if k in items_map]
            grp_items.sort(key=lambda it: (it.source_idx, it.filename))

            # 统计组内最高匹配参数
            max_inl = 0
            max_gd = 0
            best_sc = 0.0
            min_md = 999.0
            has_md5 = False

            for i in range(len(cl_keys)):
                for j in range(i + 1, len(cl_keys)):
                    pk = self.make_pair_key(cl_keys[i], cl_keys[j])
                    if pk in adj:
                        info = adj[pk]
                        max_inl = max(max_inl, info['inliers'])
                        max_gd = max(max_gd, info['good'])
                        best_sc = max(best_sc, info['score'])
                        min_md = min(min_md, info['mad'])
                        if info['is_md5']:
                            has_md5 = True

            if has_md5:
                m_type = "完全相同 (MD5)"
            elif max_inl >= 20 or min_md <= 22.0:
                m_type = "像素级同款"
            else:
                m_type = "同款设计/变体"

            match_groups.append(MatchGroup(
                group_id=idx + 1,
                match_type=m_type,
                items=grp_items,
                max_inliers=max_inl,
                max_good=max_gd,
                best_score=best_sc,
                min_mad=min_md if min_md < 900 else 0.0
            ))

        # 排序：完全相同 -> 像素级同款 -> 同款变体
        type_order = {"完全相同 (MD5)": 0, "像素级同款": 1, "同款设计/变体": 2}
        match_groups.sort(key=lambda g: (type_order.get(g.match_type, 3), -g.max_inliers, g.min_mad))
        for i, g in enumerate(match_groups):
            g.group_id = i + 1

        return match_groups

    def _has_strong_tie(self, candidate_key: str, cluster_keys: List[str], adj: Dict[Tuple[str, str], Dict]) -> bool:
        links_count = 0
        for ck in cluster_keys:
            pk = self.make_pair_key(candidate_key, ck)
            if pk in adj:
                links_count += 1
        return links_count >= max(1, (len(cluster_keys) + 1) // 2)

    def export_groups_to_folder(self, groups: List[MatchGroup], dest_root: str, is_cross: bool = False) -> Tuple[int, int, str]:
        """
        将检出的分组自动按组创建子文件夹并拷贝图片
        返回: (导出组数, 导出文件总数, 目标路径)
        """
        os.makedirs(dest_root, exist_ok=True)
        exported_groups = 0
        exported_files = 0

        for grp in groups:
            active = grp.active_items
            if len(active) < 2:
                continue
            exported_groups += 1
            safe_type = grp.match_type.replace(" ", "").replace("/", "_").replace("(", "").replace(")", "")
            sub_name = f"第{grp.group_id:02d}组_{safe_type}_{len(active)}张"
            sub_dir = os.path.join(dest_root, sub_name)
            os.makedirs(sub_dir, exist_ok=True)

            for it in active:
                safe_fn = it.filename.replace("\\", "_").replace("/", "_")
                if is_cross:
                    dst_fn = f"[{it.folder_tag}]_{safe_fn}"
                else:
                    dst_fn = safe_fn
                dst_path = os.path.join(sub_dir, dst_fn)
                try:
                    shutil.copy2(it.filepath, dst_path)
                    exported_files += 1
                except Exception:
                    pass

        return exported_groups, exported_files, dest_root
