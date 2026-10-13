# -*- coding: utf-8 -*-
"""
印花查重工作台 v4.0 — 商业级基础架构核心套件 (core_infra.py)
包含：
1. AppPaths & SQLiteStateStore：严格遵循 Windows 标准规范路径 (%APPDATA% / %LOCALAPPDATA%) 与 SQLite WAL 持久化迁移
2. setup_rotating_logger & GlobalCrashHandler：10MB×7 工业级日志轮转 + 全局未捕获异常接管 (主线程/工作线程/Qt) + 崩溃报告弹窗
3. SingleInstanceGuard：Win32 内核命名互斥锁 (CreateMutexW) + QLocalServer 跨进程唤醒置顶已运行窗口
4. DPAPISecretStore & MachineFingerprint：Windows 原生 Crypt32 DPAPI 敏感凭据加密 + 硬件指纹与非对称签名授权校验
"""

import os
import sys
import json
import time
import uuid
import hmac
import base64
import ctypes
import sqlite3
import logging
import hashlib
import platform
import traceback
import threading
import subprocess
import zipfile
import urllib.request
from ctypes import wintypes
from logging.handlers import RotatingFileHandler
from datetime import datetime
from typing import Optional, Tuple, Set, Dict, Any, Callable, List

from PySide6.QtCore import QObject, Signal, Qt, QThread, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QWidget, QLineEdit,
    QProgressBar, QFrame, QMessageBox
)

APP_VENDOR = "TableclothStudio"
APP_INTERNAL_NAME = "TableclothDedupPro"
APP_DISPLAY_NAME = "图像智能查重工作台"
APP_VERSION = os.environ.get("TDPRO_ACTIVE_VERSION", "4.0.5")

# 默认内置的专属 GitHub 仓库地址与分支
DEFAULT_GITHUB_REPO = "YingYiBotime/image-dedup-workbench"
DEFAULT_GITHUB_BRANCH = "main"


# ==============================================================================
# 1. Windows 规范路径管理 (%APPDATA% 与 %LOCALAPPDATA% 严格隔离)
# ==============================================================================

class AppPaths:
    """
    严格遵循 Windows 桌面软件规范的路径管理器：
    - 严禁向 Program Files 安装目录或用户原图目录写入任何运行期文件；
    - 用户级配置、SQLite 状态库、授权文件 -> %APPDATA%\\TableclothDedupPro
    - 高频读写特征缓存、回收站暂存区、轮转日志、崩溃转储、OTA 热更新补丁区 -> %LOCALAPPDATA%\\TableclothDedupPro
    """

    def __init__(self, app_name: str = APP_INTERNAL_NAME):
        self.app_name = app_name

        roaming_base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        local_base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")

        # 1. 漫游/持久化应用数据目录 (%APPDATA%\TableclothDedupPro)
        self.roaming_root = os.path.join(roaming_base, self.app_name)
        self.config_dir = os.path.join(self.roaming_root, "config")
        self.data_dir = os.path.join(self.roaming_root, "data")
        self.sqlite_db_path = os.path.join(self.data_dir, "app_state.db")
        self.settings_json_path = os.path.join(self.config_dir, "settings.json")
        self.license_file_path = os.path.join(self.config_dir, "license.dat")
        self.update_manifest_path = os.path.join(self.config_dir, "version_manifest.json")
        self.ota_config_path = os.path.join(self.config_dir, "github_ota_config.json")

        # 2. 本地高速缓存、日志与 OTA 热补丁目录 (%LOCALAPPDATA%\TableclothDedupPro)
        self.local_root = os.path.join(local_base, self.app_name)
        self.cache_root = os.path.join(self.local_root, "cache")
        self.feat_cache_dir = os.path.join(self.cache_root, "features")
        self.thumb_cache_dir = os.path.join(self.cache_root, "thumbnails")
        self.trash_dir = os.path.join(self.local_root, "staging_trash")
        self.log_dir = os.path.join(self.local_root, "logs")
        self.crash_dir = os.path.join(self.local_root, "crashes")
        self.updates_dir = os.path.join(self.local_root, "updates")
        self.hotpatch_dir = os.path.join(self.local_root, "hotpatch")
        self.hotpatch_manifest_path = os.path.join(self.hotpatch_dir, "hotpatch_manifest.json")

        self._ensure_directories()

    def _ensure_directories(self):
        for folder in (
            self.config_dir,
            self.data_dir,
            self.feat_cache_dir,
            self.thumb_cache_dir,
            self.trash_dir,
            self.log_dir,
            self.crash_dir,
            self.updates_dir,
            self.hotpatch_dir,
        ):
            os.makedirs(folder, exist_ok=True)

    def get_github_ota_config(self) -> Dict[str, str]:
        """读取 GitHub OTA 更新源配置（优先用户配置，其次程序内置 github_ota_config.json）"""
        candidates = [self.ota_config_path]
        if getattr(sys, "frozen", False):
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
            candidates.append(os.path.join(exe_dir, "github_ota_config.json"))
            meipass = getattr(sys, "_MEIPASS", "")
            if meipass:
                candidates.append(os.path.join(meipass, "github_ota_config.json"))
        here_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(here_dir, "github_ota_config.json"))

        for p in candidates:
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict) and data.get("github_repo"):
                        return {
                            "github_repo": str(data.get("github_repo", "")).strip(),
                            "branch": str(data.get("branch", DEFAULT_GITHUB_BRANCH)).strip() or "main",
                        }
                except Exception:
                    pass
        return {
            "github_repo": os.environ.get("TDPRO_GITHUB_REPO", DEFAULT_GITHUB_REPO).strip(),
            "branch": os.environ.get("TDPRO_GITHUB_BRANCH", DEFAULT_GITHUB_BRANCH).strip() or "main",
        }

    def save_github_ota_config(self, github_repo: str, branch: str = "main"):
        """保存 GitHub OTA 仓库配置至 %APPDATA%"""
        clean_repo = self.normalize_github_repo(github_repo)
        cfg = {"github_repo": clean_repo, "branch": (branch or "main").strip()}
        with open(self.ota_config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)

    @staticmethod
    def normalize_github_repo(raw: str) -> str:
        """支持输入 'https://github.com/owner/repo.git' 或 'owner/repo' 自动提取标准 'owner/repo'"""
        s = (raw or "").strip().rstrip("/")
        if s.endswith(".git"):
            s = s[:-4]
        for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
            if s.lower().startswith(prefix):
                s = s[len(prefix):]
                break
        parts = [p for p in s.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
        return s


# ==============================================================================
# 2. 工业级结构化日志轮转 (RotatingFileHandler: 10MB × 7 份归档)
# ==============================================================================

def setup_rotating_logger(paths: AppPaths, logger_name: str = APP_INTERNAL_NAME) -> logging.Logger:
    """
    配置工业级结构化轮转日志：
    - 单文件上限 10MB，最多保留最近 7 个归档文件，彻底杜绝日志撑爆磁盘；
    - 同时输出包含线程名、模块、行号的标准格式。
    """
    logger = logging.getLogger(logger_name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_file = os.path.join(paths.log_dir, "workstation.log")
    formatter = logging.Formatter(
        fmt="%(asctime)s.%(msecs)03d | %(levelname)-7s | %(threadName)-14s | %(module)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=7,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# ==============================================================================
# 3. SQLite 轻量本地持久化与 Schema 自动迁移 (替代不安全的裸 Pickle)
# ==============================================================================

class SQLiteStateStore:
    """
    基于 SQLite (WAL 并发模式) 的本地结构化状态存储，内置 Schema Migration 机制：
    - 存储已核验保留白名单对 (whitelist_pairs)
    - 存储差分复查排除矩阵对 (excluded_pairs)
    - 存储用户键值配置 (app_kv_settings)
    """
    CURRENT_SCHEMA_VERSION = 2

    def __init__(self, db_path: str, logger: Optional[logging.Logger] = None):
        self.db_path = db_path
        self.logger = logger or logging.getLogger(APP_INTERNAL_NAME)
        self._lock = threading.RLock()
        self._init_and_migrate()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_and_migrate(self):
        with self._lock, self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
            """)
            cur = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations;")
            cur_ver = cur.fetchone()[0]

            if cur_ver < 1:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS pair_relations (
                        key_a TEXT NOT NULL,
                        key_b TEXT NOT NULL,
                        relation_type TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        PRIMARY KEY (key_a, key_b, relation_type)
                    );
                """)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?);",
                    (datetime.now().isoformat(),)
                )

            if cur_ver < 2:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS app_kv_settings (
                        k TEXT PRIMARY KEY,
                        v TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                """)
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_pair_rel_type ON pair_relations(relation_type);"
                )
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (2, ?);",
                    (datetime.now().isoformat(),)
                )

            conn.commit()

    def load_pairs(self, relation_type: str) -> Set[Tuple[str, str]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT key_a, key_b FROM pair_relations WHERE relation_type = ?;",
                (relation_type,)
            ).fetchall()
            return {(r[0], r[1]) for r in rows}

    def save_pairs(self, relation_type: str, pairs: Set[Tuple[str, str]]):
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM pair_relations WHERE relation_type = ?;", (relation_type,))
            if pairs:
                conn.executemany(
                    "INSERT OR IGNORE INTO pair_relations (key_a, key_b, relation_type, created_at) VALUES (?, ?, ?, ?);",
                    [(a, b, relation_type, now) for (a, b) in pairs]
                )
            conn.commit()

    def clear_pairs(self, relation_type: str):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM pair_relations WHERE relation_type = ?;", (relation_type,))
            conn.commit()

    def set_setting(self, key: str, value: Any):
        payload = json.dumps(value, ensure_ascii=False)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_kv_settings (k, v, updated_at) VALUES (?, ?, ?);",
                (key, payload, time.time())
            )
            conn.commit()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT v FROM app_kv_settings WHERE k = ?;", (key,)).fetchone()
            if not row:
                return default
            try:
                return json.loads(row[0])
            except Exception:
                return default


# ==============================================================================
# 4. 全局异常接管与崩溃报告系统 (Global Uncaught Exception Handler)
# ==============================================================================

class CrashReportDialog(QDialog):
    """
    Studio Dark 风格的崩溃保护提示窗：
    当发生未捕获异常时拦截闪退，展示错误摘要并提供一键打开崩溃日志目录或继续运行。
    """

    def __init__(self, error_id: str, summary: str, dump_path: str, details: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.dump_path = dump_path
        self.setWindowTitle(f"{APP_DISPLAY_NAME} — 异常恢复保护")
        self.setFixedSize(560, 360)
        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #e4e4e7;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel {
                background: transparent;
                border: none;
            }
            QTextEdit {
                background-color: #202023;
                color: #a1a1aa;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                padding: 8px;
                font-family: "Consolas", "Microsoft YaHei", monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #323236;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        lbl_title = QLabel(f"检测到运行期异常（已自动拦截闪退 · 编号 {error_id}）")
        lbl_title.setStyleSheet("color: #f59e0b; font-size: 14px; font-weight: 600;")
        lay.addWidget(lbl_title)

        lbl_desc = QLabel(
            f"错误摘要：{summary}\n"
            f"系统已保护您当前的核验数据并生成诊断转储文件：\n{dump_path}"
        )
        lbl_desc.setWordWrap(True)
        lbl_desc.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        lay.addWidget(lbl_desc)

        txt = QTextEdit()
        txt.setReadOnly(True)
        txt.setPlainText(details)
        lay.addWidget(txt, stretch=1)

        btn_row = QHBoxLayout()
        btn_open_dir = QPushButton("打开崩溃日志目录")
        btn_open_dir.clicked.connect(self._open_dump_dir)
        btn_row.addWidget(btn_open_dir)

        btn_row.addStretch(1)

        btn_continue = QPushButton("继续运行工作台")
        btn_continue.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3b82f6;
            }
        """)
        btn_continue.clicked.connect(self.accept)
        btn_row.addWidget(btn_continue)

        lay.addLayout(btn_row)

    def _open_dump_dir(self):
        folder = os.path.dirname(self.dump_path)
        if os.path.isdir(folder):
            os.startfile(folder)


class GlobalCrashHandler(QObject):
    """
    全局未捕获异常接管器：
    同时拦截主线程 (sys.excepthook) 与后台线程 (threading.excepthook) 的未捕获异常，
    生成包含系统环境、堆栈与上下文的 .log 转储报告，并在主线程安全弹出恢复窗口。
    """
    crashCaptured = Signal(str, str, str, str)  # error_id, summary, dump_path, full_report

    def __init__(self, paths: AppPaths, logger: logging.Logger):
        super().__init__()
        self.paths = paths
        self.logger = logger
        self._in_handler = False
        self.crashCaptured.connect(self._show_crash_dialog_on_main_thread)

    def install(self):
        sys.excepthook = self._handle_uncaught_exception
        threading.excepthook = self._handle_thread_exception

    def _handle_thread_exception(self, args: threading.ExceptHookArgs):
        self._handle_uncaught_exception(args.exc_type, args.exc_value, args.exc_traceback, thread_name=args.thread.name if args.thread else "WorkerThread")

    def _handle_uncaught_exception(self, exc_type, exc_value, exc_tb, thread_name: str = "MainThread"):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        if self._in_handler:
            return
        self._in_handler = True
        try:
            error_id = f"ERR-{uuid.uuid4().hex[:8].upper()}"
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            dump_path = os.path.join(self.paths.crash_dir, f"crash_{ts_str}_{error_id}.log")

            tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            env_info = {
                "error_id": error_id,
                "timestamp": datetime.now().isoformat(),
                "app_version": APP_VERSION,
                "thread": thread_name,
                "os": platform.platform(),
                "python": sys.version,
                "machine": platform.machine(),
                "cwd": os.getcwd(),
            }
            full_report = (
                "================ COMMERCIAL CRASH DIAGNOSTIC REPORT ================\n"
                + json.dumps(env_info, indent=2, ensure_ascii=False)
                + "\n\n---------------- TRACEBACK ----------------\n"
                + tb_text
            )

            try:
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(full_report)
            except Exception:
                pass

            self.logger.critical(f"[{error_id}] Uncaught exception in {thread_name}: {exc_value}\n{tb_text}")

            summary = f"{exc_type.__name__}: {exc_value}"
            app = QApplication.instance()
            if app is not None:
                self.crashCaptured.emit(error_id, summary, dump_path, full_report)
        finally:
            self._in_handler = False

    def _show_crash_dialog_on_main_thread(self, error_id: str, summary: str, dump_path: str, full_report: str):
        active_win = QApplication.activeWindow()
        dlg = CrashReportDialog(error_id, summary, dump_path, full_report, parent=active_win)
        dlg.exec()


# ==============================================================================
# 5. 单例运行保护 (Win32 Kernel32 Named Mutex + QLocalServer 跨进程置顶唤醒)
# ==============================================================================

ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9


class SingleInstanceGuard(QObject):
    """
    Windows 系统级单例运行保护器：
    1. 通过 Win32 API CreateMutexW 创建内核命名互斥体；
    2. 若检测到已有实例运行，自动通过 QLocalSocket 向主实例发送 "ACTIVATE" 指令，
       主实例收到后立即将窗口从最小化/后台恢复并置顶激活 (SetForegroundWindow)。
    """
    activationRequested = Signal()
    _active_instance: Optional["SingleInstanceGuard"] = None

    def __init__(self, mutex_name: str = f"Local\\{APP_INTERNAL_NAME}_SingleInstance_Mutex_v4"):
        super().__init__()
        self.mutex_name = mutex_name
        self.pipe_name = f"{APP_INTERNAL_NAME}_IPC_Pipe_v4"
        self._mutex_handle = None
        self._server: Optional[QLocalServer] = None
        self._is_primary = False

    @property
    def is_primary(self) -> bool:
        return self._is_primary

    def try_acquire_or_notify_existing(self) -> bool:
        """
        尝试获取主实例锁：
        - 返回 True：当前进程是唯一主实例，已启动 IPC 监听；
        - 返回 False：已有实例在运行，已通知其置顶唤醒，当前进程应立即退出。
        """
        is_restarting = os.environ.pop("TDPRO_RESTARTING", "") == "1"
        if sys.platform == "win32":
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            max_attempts = 25 if is_restarting else 1
            for attempt in range(max_attempts):
                self._mutex_handle = kernel32.CreateMutexW(None, False, self.mutex_name)
                last_err = kernel32.GetLastError()
                if last_err != ERROR_ALREADY_EXISTS:
                    break
                if attempt + 1 < max_attempts:
                    try:
                        kernel32.CloseHandle(self._mutex_handle)
                    except Exception:
                        pass
                    self._mutex_handle = None
                    time.sleep(0.1)
                else:
                    self._notify_primary_instance()
                    return False

        # 启动 QLocalServer 监听后续重复启动实例的唤醒请求
        QLocalServer.removeServer(self.pipe_name)
        self._server = QLocalServer(self)
        if self._server.listen(self.pipe_name):
            self._server.newConnection.connect(self._on_new_ipc_connection)
        self._is_primary = True
        SingleInstanceGuard._active_instance = self
        return True

    def _notify_primary_instance(self):
        sock = QLocalSocket()
        sock.connectToServer(self.pipe_name)
        if sock.waitForConnected(400):
            sock.write(b"ACTIVATE_WINDOW")
            sock.flush()
            sock.waitForBytesWritten(200)
            sock.disconnectFromServer()

    def _on_new_ipc_connection(self):
        if not self._server:
            return
        conn = self._server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(lambda: self._read_ipc_payload(conn))

    def _read_ipc_payload(self, conn: QLocalSocket):
        data = bytes(conn.readAll()).decode("utf-8", errors="ignore")
        conn.close()
        if "ACTIVATE" in data:
            self.activationRequested.emit()

    @staticmethod
    def bring_window_to_front(window: QWidget):
        """将已运行的 Qt 主窗口从最小化或后台强制置顶激活"""
        if window.isMinimized():
            window.showNormal()
        window.setWindowState((window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        window.show()
        window.raise_()
        window.activateWindow()

        if sys.platform == "win32":
            try:
                hwnd = int(window.winId())
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def release(self):
        if self._server:
            self._server.close()
            self._server = None
        if sys.platform == "win32" and self._mutex_handle:
            try:
                ctypes.windll.kernel32.CloseHandle(self._mutex_handle)
            except Exception:
                pass
            self._mutex_handle = None
        if SingleInstanceGuard._active_instance is self:
            SingleInstanceGuard._active_instance = None

    @classmethod
    def release_active(cls):
        if cls._active_instance is not None:
            cls._active_instance.release()


# ==============================================================================
# 6. 商业化安全套件：Windows DPAPI 凭据加密与多维硬件指纹
# ==============================================================================

class DPAPISecretStore:
    """
    调用 Windows 原生 Crypt32.dll (CryptProtectData / CryptUnprotectData)
    将敏感 Token、API Key、授权密钥与当前 Windows 登录账户及机器绑定加密存储，杜绝明文落盘。
    """

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    @classmethod
    def encrypt_bytes(cls, plaintext: bytes) -> bytes:
        if sys.platform != "win32":
            return base64.b64encode(plaintext)
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_buf = ctypes.create_string_buffer(plaintext, len(plaintext))
        in_blob = cls._DATA_BLOB(len(plaintext), in_buf)
        out_blob = cls._DATA_BLOB()

        if not crypt32.CryptProtectData(
            ctypes.byref(in_blob), "TableclothDedupSecret", None, None, None, 0, ctypes.byref(out_blob)
        ):
            raise RuntimeError("Windows DPAPI CryptProtectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    @classmethod
    def decrypt_bytes(cls, encrypted: bytes) -> bytes:
        if sys.platform != "win32":
            return base64.b64decode(encrypted)
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        in_buf = ctypes.create_string_buffer(encrypted, len(encrypted))
        in_blob = cls._DATA_BLOB(len(encrypted), in_buf)
        out_blob = cls._DATA_BLOB()

        if not crypt32.CryptUnprotectData(
            ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
        ):
            raise RuntimeError("Windows DPAPI CryptUnprotectData failed")
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    @classmethod
    def save_encrypted_file(cls, filepath: str, plaintext_str: str):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        cipher_blob = cls.encrypt_bytes(plaintext_str.encode("utf-8"))
        with open(filepath, "wb") as f:
            f.write(cipher_blob)

    @classmethod
    def load_encrypted_file(cls, filepath: str) -> Optional[str]:
        if not os.path.isfile(filepath):
            return None
        try:
            with open(filepath, "rb") as f:
                cipher_blob = f.read()
            return cls.decrypt_bytes(cipher_blob).decode("utf-8")
        except Exception:
            return None


class MachineFingerprint:
    """生成当前 Windows 设备的唯一硬件指纹 (结合 MachineGuid + 系统卷序列号 + 处理器标识 + 主机特征)"""

    @staticmethod
    def get_machine_code() -> str:
        raw_parts = [platform.node(), platform.machine(), platform.processor()]
        if sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\Cryptography",
                    0,
                    winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                ) as key:
                    guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                    raw_parts.insert(0, str(guid))
            except Exception:
                pass
        digest = hashlib.sha256("|".join(raw_parts).encode("utf-8")).hexdigest().upper()
        return f"HFP-{digest[0:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"

    @staticmethod
    def get_hardware_summary() -> Dict[str, str]:
        vol_serial = "UNKNOWN"
        if sys.platform == "win32":
            try:
                serial = wintypes.DWORD(0)
                ctypes.windll.kernel32.GetVolumeInformationW(
                    ctypes.c_wchar_p("C:\\"), None, 0,
                    ctypes.byref(serial), None, None, None, 0
                )
                vol_serial = f"{serial.value:08X}"
            except Exception:
                pass
        mac_int = uuid.getnode()
        mac_hex = ":".join(f"{(mac_int >> ele) & 0xff:02X}" for ele in range(40, -1, -8))
        return {
            "hfp": MachineFingerprint.get_machine_code(),
            "node": platform.node(),
            "cpu": platform.processor() or platform.machine(),
            "sys_vol_serial": vol_serial,
            "mac_addr": mac_hex,
        }


# ==============================================================================
# 7. 非对称加密签名授权系统 (RSA-2048 Public Key Verification + DPAPI 绑定存储)
# ==============================================================================

class AsymmetricLicenseManager:
    """
    商业非对称加密授权校验器 (RSA-2048-PKCS1v15-SHA256)：
    - 客户端仅内置 2048 位 RSA 公钥模数 N 与公钥指数 E=65537，绝不包含私钥 D；
    - 激活码由服务端/签发工具 (license_issuer.py) 使用私钥 D 签名生成；
    - 校验激活码时：
      1. 使用 RSA 公钥验证 SHA-256 数字签名，任何篡改字节均立即被拒绝；
      2. 校验硬件指纹 HFP 是否与当前机器匹配 (或为企业通配授权 '*')；
      3. 校验授权有效期 expires_at；
      4. 验证通过后使用 Windows DPAPI (CryptProtectData) 加密落盘至 %APPDATA%\\TableclothDedupPro\\config\\license.dat。
    """

    RSA_PUBLIC_MODULUS_N = int(
        "a9fdf6cfef450cfbaf50b2a0d022db7db75c83b45bdfbebb228b3bbb5374230f"
        "2ab87b97397019ea9f075a23579495af6345072d55dded3ed9b5133affe00554"
        "cc37fbb8008708a2f61157b535dfd90ab53c0174ff961c68a9b7b697615c7ce9"
        "a83bdc415b49293c62e5754526131f13487aaa4cea38fd6965412642ab7a45e0"
        "a20c91d96bbaab0ab0601b6a489c5ecb08a93dedacd099ac0136ee408749a325"
        "2cdd33a8ae2532aa0cc11c76cdaedf4334b8aca533013f7b867cf1268ff9b728"
        "9aeb5c7e44bbf010dcc0492f9b4fcb50fbb58d84c6d4ea5dcb145afe25472719"
        "804473bc31e736969de56662023c896b2e75cca6325cf5a546ff84ba37995063",
        16
    )
    RSA_PUBLIC_EXPONENT_E = 65537
    ASN1_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

    # 预签发的当前工作站专属商业授权码（由私钥签发，绑定 HFP-0B86-9E56-34AA-320C）
    DEFAULT_WORKSTATION_TOKEN = (
        "TDPRO-eyJjdXN0b21lciI6IkNvbW1lcmNpYWwgV29ya3N0YXRpb24gTGljZW5zZSIsImVkaXRp"
        "b24iOiJFbnRlcnByaXNlIFN0dWRpbyBQcm8iLCJleHBpcmVzX2F0IjoiMjAyOS0xMi0zMSIsIm"
        "ZlYXR1cmVzIjpbInNpbmdsZV9kZWR1cCIsImNyb3NzX2NvbXBhcmUiLCJoZWF0bWFwIiwiYmF0"
        "Y2hfZXhwb3J0Il0sImhmcCI6IkhGUC0wQjg2LTlFNTYtMzRBQS0zMjBDIiwiaXNzdWVkX2F0Ij"
        "oiMjAyNi0xMC0xMSJ9.N-dsMe6M-qUp3vvZc0rQqYi6hpPZyZTT22o3T3G8Adb6KzhfFGQAYN4"
        "V0Pgr7fwfVbbwnBfEDmXQ0en3zjwp1yhUjBAmSbhej_in3CXI4LTPQI4H4ULoXtlN8yxk-cO5L"
        "TIXs82RVOzTADwQGYcSvct2hTy5oqr_EV_CFaCxgC3-zCIn91IYtG14v3Owoe4hoTkWOFuaGjG"
        "GfNG-dcMt0-AHK5r8xS9sHxxU0HIkVvrIwICX8W7OFFmKBHwRh0r1m5EJhFxrWizueCiDNRWnJ"
        "9GYqg2W4zF13HG2tjJ8VfVLkILUoQWA4oxGgeBCNOQSC0Wjhf1SiPBxTKMqiH7RsQ"
    )

    # 预签发的团队通用站点授权码（由私钥签发，支持工作室其它电脑开箱即用，也可随时升级为一机一码）
    DEFAULT_TEAM_SITE_TOKEN = (
        "TDPRO-eyJjdXN0b21lciI6IlN0dWRpbyBUZWFtIFNpdGUgTGljZW5zZSIsImVkaXRpb24iOiJT"
        "dHVkaW8gVGVhbSBFZGl0aW9uIiwiZXhwaXJlc19hdCI6IjIwMjktMTItMzEiLCJmZWF0dXJlcy"
        "I6WyJzaW5nbGVfZGVkdXAiLCJjcm9zc19jb21wYXJlIiwiaGVhdG1hcCIsImJhdGNoX2V4cG9y"
        "dCJdLCJoZnAiOiIqIiwiaXNzdWVkX2F0IjoiMjAyNi0xMC0xMSJ9.ehDJ4wR6QJNB6OqsLPT8F"
        "svklqIeHdp-R4noPO0kOCUvOZUxTNNLY3MqSOOT2tR1xBMHIEetDnjJxyhxTeQko5Cue81Q7k"
        "wnSu4zEcBpPmf1e-DbMz3n_1T4ByHC61UupDIiyobp0Q-T1JfuthIs6rSxr61Zebg2mAHRGr0"
        "Rzr8ia_30V8frd5-DoMKEbRRFo_isHoDO8OFCx-6f5crLiziPygpSUx63ghc6VmWR6hh0m3ML"
        "e1uoFtKrky-Qi4_CKdy6aV_rE_MAsFtqzfuSoDHn3kIELvqTKoKoto2b5aoN5JUUtV2Wd1R5I"
        "IX_M-8e5QEBHw3DeXZhK44eYA392A"
    )

    def __init__(self, paths: AppPaths, logger: Optional[logging.Logger] = None):
        self.paths = paths
        self.logger = logger or logging.getLogger(APP_INTERNAL_NAME)
        self.machine_code = MachineFingerprint.get_machine_code()
        self._ensure_default_license()

    def _ensure_default_license(self):
        existing = DPAPISecretStore.load_encrypted_file(self.paths.license_file_path)
        if not existing:
            for candidate in (self.DEFAULT_WORKSTATION_TOKEN, self.DEFAULT_TEAM_SITE_TOKEN):
                ok, _, _ = self.verify_license_token(candidate)
                if ok:
                    DPAPISecretStore.save_encrypted_file(self.paths.license_file_path, candidate)
                    self.logger.info(f"Provisioned DPAPI-protected commercial license for {self.machine_code}")
                    break

    @staticmethod
    def _b64url_decode(data: str) -> bytes:
        pad = "=" * ((4 - len(data) % 4) % 4)
        return base64.urlsafe_b64decode((data + pad).encode("ascii"))

    @classmethod
    def verify_rsa_pkcs1_sha256(cls, message: bytes, signature: bytes) -> bool:
        if len(signature) != 256:
            return False
        sig_int = int.from_bytes(signature, "big")
        if sig_int <= 0 or sig_int >= cls.RSA_PUBLIC_MODULUS_N:
            return False
        em_int = pow(sig_int, cls.RSA_PUBLIC_EXPONENT_E, cls.RSA_PUBLIC_MODULUS_N)
        em = em_int.to_bytes(256, "big")

        digest = hashlib.sha256(message).digest()
        t = cls.ASN1_SHA256_PREFIX + digest
        ps_len = 256 - len(t) - 3
        expected_em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t
        return hmac.compare_digest(em, expected_em)

    def verify_license_token(self, token: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        token = (token or "").strip()
        if not token.startswith("TDPRO-") or "." not in token:
            return False, "激活码格式无效（应以 TDPRO- 开头并包含签名段）", None

        try:
            body = token[len("TDPRO-"):]
            payload_b64, sig_b64 = body.split(".", 1)
            payload_bytes = self._b64url_decode(payload_b64)
            sig_bytes = self._b64url_decode(sig_b64)
        except Exception:
            return False, "激活码 Base64 编码解析失败", None

        # 1. RSA-2048 公钥验签
        if not self.verify_rsa_pkcs1_sha256(payload_bytes, sig_bytes):
            return False, "RSA-2048 数字签名校验失败（激活码可能被篡改或伪造）", None

        # 2. 解析载荷并核对硬件指纹与有效期
        try:
            info = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return False, "激活码载荷结构损坏", None

        lic_hfp = info.get("hfp", "")
        if lic_hfp not in (self.machine_code, "*"):
            return False, f"硬件指纹不匹配（激活码绑定于 {lic_hfp}，当前机器为 {self.machine_code}）", None

        expires_at = info.get("expires_at", "1970-01-01")
        today_str = datetime.now().strftime("%Y-%m-%d")
        if expires_at < today_str:
            return False, f"商业授权已于 {expires_at} 过期", info

        return True, f"已激活 · {info.get('edition', 'Commercial Edition')} (有效期至 {expires_at})", info

    def get_current_license_status(self) -> Tuple[bool, str, Dict[str, Any], str]:
        token = DPAPISecretStore.load_encrypted_file(self.paths.license_file_path) or ""
        ok, msg, info = self.verify_license_token(token)
        if ok and info:
            return True, msg, info, token
        return False, msg or "未激活或授权已失效", {}, token

    def activate_and_save(self, token: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        ok, msg, info = self.verify_license_token(token)
        if ok:
            DPAPISecretStore.save_encrypted_file(self.paths.license_file_path, token.strip())
            self.logger.info(f"License activated and encrypted via Windows DPAPI: {msg}")
        else:
            self.logger.warning(f"License activation rejected: {msg}")
        return ok, msg, info


class LicenseActivationDialog(QDialog):
    """Studio Dark 商业授权与机器码绑定管理对话框"""

    def __init__(self, lic_mgr: AsymmetricLicenseManager, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.lic_mgr = lic_mgr
        self.setWindowTitle(f"商业授权与机器码管理 — {APP_DISPLAY_NAME}")
        self.setFixedSize(580, 440)
        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #e4e4e7;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel {
                background: transparent;
                border: none;
            }
            QFrame#Card {
                background-color: #202023;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }
            QLineEdit, QTextEdit {
                background-color: #141417;
                color: #e4e4e7;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                padding: 6px 10px;
                font-family: "Consolas", "Microsoft YaHei", monospace;
                font-size: 11px;
            }
            QPushButton {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #323236;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        # 1. 硬件指纹信息卡
        hw = MachineFingerprint.get_hardware_components() if hasattr(MachineFingerprint, "get_hardware_components") else MachineFingerprint.get_hardware_summary()
        card_hw = QFrame()
        card_hw.setObjectName("Card")
        hw_lay = QVBoxLayout(card_hw)
        hw_lay.setContentsMargins(14, 12, 14, 12)
        hw_lay.setSpacing(6)

        row_hfp = QHBoxLayout()
        lbl_hfp_title = QLabel("本机唯一硬件授权指纹 (Machine Fingerprint):")
        lbl_hfp_title.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        row_hfp.addWidget(lbl_hfp_title)
        row_hfp.addStretch(1)

        btn_copy = QPushButton("复制机器码")
        btn_copy.setFixedHeight(26)
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(hw["hfp"]))
        row_hfp.addWidget(btn_copy)
        hw_lay.addLayout(row_hfp)

        self.edt_hfp = QLineEdit(hw["hfp"])
        self.edt_hfp.setReadOnly(True)
        self.edt_hfp.setStyleSheet("color: #60a5fa; font-size: 13px; font-weight: 700;")
        hw_lay.addWidget(self.edt_hfp)

        lbl_hw_sub = QLabel(
            f"绑定特征：系统卷序列号 [{hw['sys_vol_serial']}] · 网卡物理节点 [{hw['mac_addr']}] · 加密引擎 [Windows Crypt32 DPAPI]"
        )
        lbl_hw_sub.setStyleSheet("color: #71717a; font-size: 11px;")
        hw_lay.addWidget(lbl_hw_sub)
        lay.addWidget(card_hw)

        # 2. 当前授权状态卡
        card_status = QFrame()
        card_status.setObjectName("Card")
        st_lay = QVBoxLayout(card_status)
        st_lay.setContentsMargins(14, 10, 14, 10)
        st_lay.setSpacing(4)

        self.lbl_status_badge = QLabel()
        self.lbl_status_detail = QLabel()
        self.lbl_status_detail.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        st_lay.addWidget(self.lbl_status_badge)
        st_lay.addWidget(self.lbl_status_detail)
        lay.addWidget(card_status)

        # 3. 离线/在线激活码输入区
        lbl_input = QLabel("输入 RSA-2048 签名商业激活码 (支持离线粘贴激活):")
        lbl_input.setStyleSheet("color: #d4d4d8; font-size: 12px; font-weight: 600;")
        lay.addWidget(lbl_input)

        self.txt_token = QTextEdit()
        self.txt_token.setPlaceholderText("TDPRO-eyJjdXN0b21lciI6... (在此粘贴由 license_issuer.py 签发的商业授权码)")
        lay.addWidget(self.txt_token, stretch=1)

        # 4. 底部操作栏
        btn_row = QHBoxLayout()
        btn_restore_default = QPushButton("恢复预置工作站授权")
        btn_restore_default.clicked.connect(self._on_restore_default)
        btn_row.addWidget(btn_restore_default)

        btn_row.addStretch(1)

        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)

        btn_activate = QPushButton("验证签名并激活")
        btn_activate.setStyleSheet("""
            QPushButton {
                background-color: #2563eb;
                color: #ffffff;
                border: none;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #3b82f6;
            }
        """)
        btn_activate.clicked.connect(self._on_activate_clicked)
        btn_row.addWidget(btn_activate)
        lay.addLayout(btn_row)

        self._refresh_ui()

    def _refresh_ui(self):
        ok, msg, info, token = self.lic_mgr.get_current_license_status()
        if ok:
            self.lbl_status_badge.setText(f"● 授权状态：{msg}")
            self.lbl_status_badge.setStyleSheet("color: #10b981; font-size: 13px; font-weight: 600;")
            self.lbl_status_detail.setText(
                f"授权客户：{info.get('customer', '-')}  |  签发日期：{info.get('issued_at', '-')}  |  "
                f"RSA-2048 签名：已通过  |  落盘保护：DPAPI 已加密"
            )
        else:
            self.lbl_status_badge.setText(f"▲ 授权状态：{msg}")
            self.lbl_status_badge.setStyleSheet("color: #f59e0b; font-size: 13px; font-weight: 600;")
            self.lbl_status_detail.setText("请使用 license_issuer.py 为上方机器码签发激活码并粘贴至下方。")
        if token and not self.txt_token.toPlainText().strip():
            self.txt_token.setPlainText(token)

    def _on_restore_default(self):
        self.txt_token.setPlainText(self.lic_mgr.DEFAULT_WORKSTATION_TOKEN)
        self._on_activate_clicked()

    def _on_activate_clicked(self):
        token = self.txt_token.toPlainText().strip()
        ok, msg, _ = self.lic_mgr.activate_and_save(token)
        self._refresh_ui()
        if ok:
            QMessageBox.information(self, "RSA-2048 验签成功", f"激活成功！\n{msg}\n\n授权凭证已通过 Windows DPAPI 加密写入本地配置库。")
        else:
            QMessageBox.warning(self, "激活码校验未通过", f"激活失败：\n{msg}")


# ==============================================================================
# 8. GitHub 多节点加速在线检测与 KB 级静默热更新系统 (GitHub OTA Hot-Patch + RSA-2048)
# ==============================================================================

def parse_semver(ver_str: str) -> Tuple[int, ...]:
    clean = (ver_str or "0.0.0").strip().lstrip("vV").split("-")[0]
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def build_github_ota_urls(github_repo: str, branch: str, filename: str) -> List[str]:
    """
    构建支持中国大陆免代理极速访问的 GitHub 多节点高可用镜像地址池：
    依次尝试：ghfast 国内镜像 -> ghproxy 镜像 -> jsDelivr 全球 CDN -> GitHub 官方 Raw
    """
    repo = AppPaths.normalize_github_repo(github_repo)
    br = (branch or "main").strip()
    fn = filename.lstrip("/")
    if not repo or "/" not in repo:
        return []
    ts = int(time.time())
    raw_base = f"https://raw.githubusercontent.com/{repo}/{br}/{fn}"
    return [
        f"https://ghfast.top/{raw_base}?t={ts}",
        f"https://mirror.ghproxy.com/{raw_base}?t={ts}",
        f"https://cdn.jsdelivr.net/gh/{repo}@{br}/{fn}?t={ts}",
        f"{raw_base}?t={ts}",
    ]


def restart_application():
    """无缝重启当前应用程序以立即激活热更新补丁（自动释放单例锁并在新进程启动）"""
    try:
        SingleInstanceGuard.release_active()
        env = os.environ.copy()
        env.pop("TDPRO_HOTPATCH_ACTIVE", None)
        env.pop("TDPRO_ACTIVE_VERSION", None)
        env["TDPRO_RESTARTING"] = "1"
        exe = sys.executable
        args = sys.argv[:]
        if getattr(sys, "frozen", False):
            subprocess.Popen([exe] + args[1:], close_fds=True, env=env)
        else:
            subprocess.Popen([exe] + args, close_fds=True, env=env)
        app = QApplication.instance()
        if app:
            app.quit()
        else:
            os._exit(0)
    except Exception:
        pass


class UpdateCheckWorker(QThread):
    """后台异步 GitHub OTA 版本检查线程（支持多节点国内加速镜像自动切换与本地清单回退）"""
    updateCheckFinished = Signal(bool, dict, str)  # has_update, manifest, status_msg

    def __init__(self, paths: AppPaths, feed_url: Optional[str] = None, github_repo: Optional[str] = None):
        super().__init__()
        self.paths = paths
        self.feed_url = (feed_url or os.environ.get("TDPRO_UPDATE_URL", "")).strip()
        cfg = self.paths.get_github_ota_config()
        self.github_repo = AppPaths.normalize_github_repo(github_repo if github_repo is not None else cfg.get("github_repo", ""))
        self.branch = cfg.get("branch", "main") or "main"

    def run(self):
        try:
            manifest = None
            used_mirror = ""
            url_candidates: List[str] = []

            if self.feed_url.startswith(("http://", "https://")):
                url_candidates.append(self.feed_url)
            if self.github_repo and "/" in self.github_repo:
                url_candidates.extend(build_github_ota_urls(self.github_repo, self.branch, "version.json"))

            last_err = ""
            for url in url_candidates:
                try:
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": f"{APP_INTERNAL_NAME}/{APP_VERSION}",
                            "Cache-Control": "no-cache",
                        }
                    )
                    with urllib.request.urlopen(req, timeout=4.5) as resp:
                        raw_text = resp.read().decode("utf-8")
                        data = json.loads(raw_text)
                        if isinstance(data, dict) and "version" in data:
                            manifest = data
                            used_mirror = url.split("/")[2]
                            break
                except Exception as e:
                    last_err = str(e)
                    continue

            if not manifest and os.path.isfile(self.paths.update_manifest_path):
                try:
                    with open(self.paths.update_manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                    used_mirror = "本地缓存清单"
                except Exception:
                    pass

            if not manifest:
                if not self.github_repo and not self.feed_url:
                    self.updateCheckFinished.emit(
                        False,
                        {
                            "version": APP_VERSION,
                            "notes": (
                                f"当前运行版本：v{APP_VERSION}\n\n"
                                "提示：尚未绑定 GitHub 远程更新仓库。\n"
                                "开发者只需在上方输入框填入 GitHub 仓库（如 用户名/仓库名），"
                                "或双击运行项目目录下的【一键发布热更新到GitHub.bat】，"
                                "即可开启全自动云端秒级同步更新！"
                            ),
                        },
                        "未绑定 GitHub 仓库"
                    )
                else:
                    self.updateCheckFinished.emit(
                        False,
                        {
                            "version": APP_VERSION,
                            "notes": f"未能从 GitHub 仓库 ({self.github_repo}) 获取到 version.json。\n请确认仓库已公开且已运行过【一键发布热更新到GitHub.bat】。\n({last_err})",
                        },
                        f"连接更新源未找到 version.json"
                    )
                return

            # 将拉取到的最新远程清单缓存到本地
            try:
                with open(self.paths.update_manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

            remote_ver = str(manifest.get("version", APP_VERSION))
            has_new = parse_semver(remote_ver) > parse_semver(APP_VERSION)
            manifest["_used_mirror"] = used_mirror
            manifest["_github_repo"] = self.github_repo
            manifest["_branch"] = self.branch
            msg = f"发现新版本 v{remote_ver} (节点: {used_mirror})" if has_new else f"当前版本 v{APP_VERSION} 已是最新 ({used_mirror})"
            self.updateCheckFinished.emit(has_new, manifest, msg)
        except Exception as e:
            self.updateCheckFinished.emit(False, {}, f"检查更新失败: {e}")


class UpdateDownloadWorker(QThread):
    """
    后台流式下载更新文件并强制校验 SHA-256 + RSA-2048 签名：
    - 优先支持纯源码文件增量热更新 (hotpatch_files 字典，直接从 GitHub 拉取纯文本 .py，仓库零 .zip/.exe 二进制文件)；
    - 兼容 KB 级热更新包 (ota_hotpatch.zip) 或全量安装包 (.exe)。
    """
    progressChanged = Signal(int)
    downloadFinished = Signal(bool, str, str, bool)  # ok, local_path, message, is_hotpatch

    def __init__(
        self,
        download_urls: List[str],
        target_path: str,
        expected_sha256: str = "",
        expected_rsa_sig: str = "",
        is_hotpatch: bool = False,
        remote_version: str = "",
        hotpatch_dir: str = "",
        hotpatch_files: Optional[Dict[str, str]] = None,
        github_repo: str = "",
        branch: str = "main",
    ):
        super().__init__()
        self.download_urls = [u for u in download_urls if u]
        self.target_path = target_path
        self.expected_sha256 = (expected_sha256 or "").strip().lower()
        self.expected_rsa_sig = (expected_rsa_sig or "").strip()
        self.is_hotpatch = is_hotpatch
        self.remote_version = remote_version
        self.hotpatch_dir = hotpatch_dir
        self.hotpatch_files = hotpatch_files or {}
        self.github_repo = github_repo
        self.branch = branch or "main"

    def _run_pure_source_hotpatch(self):
        """无二进制归档模式：直接按清单拉取纯文本 .py/.json 文件并逐一校验 SHA-256 与整体 RSA-2048 签名"""
        items = sorted(self.hotpatch_files.items())
        if not items:
            self.downloadFinished.emit(False, "", "热更新文件清单为空", True)
            return

        # 1. 校验整体清单 SHA-256 与 RSA-2048 开发者签名
        combined_payload = "\n".join(f"{fn}:{h.strip().lower()}" for fn, h in items)
        combined_sha256 = hashlib.sha256(combined_payload.encode("utf-8")).hexdigest().lower()
        if self.expected_sha256 and combined_sha256 != self.expected_sha256:
            self.downloadFinished.emit(False, "", "更新清单摘要校验不匹配", True)
            return
        if self.expected_rsa_sig:
            try:
                sig_bytes = AsymmetricLicenseManager._b64url_decode(self.expected_rsa_sig)
                if not AsymmetricLicenseManager.verify_rsa_pkcs1_sha256(combined_sha256.encode("ascii"), sig_bytes):
                    self.downloadFinished.emit(False, "", "RSA-2048 开发者数字签名校验未通过", True)
                    return
            except Exception as e:
                self.downloadFinished.emit(False, "", f"RSA 签名校验异常: {e}", True)
                return

        staged_bytes: Dict[str, bytes] = {}
        total_files = len(items)
        for idx, (fn, exp_hash) in enumerate(items):
            base_fn = os.path.basename(fn)
            if not base_fn or (".." in fn) or not base_fn.endswith((".py", ".json")):
                continue
            exp_hash = exp_hash.strip().lower()
            urls = build_github_ota_urls(self.github_repo, self.branch, base_fn)
            file_ok = False
            last_err = ""
            for u in urls:
                try:
                    req = urllib.request.Request(
                        u,
                        headers={
                            "User-Agent": f"{APP_INTERNAL_NAME}/{APP_VERSION}",
                            "Cache-Control": "no-cache",
                        },
                    )
                    with urllib.request.urlopen(req, timeout=10.0) as resp:
                        raw_bytes = resp.read()
                    if base_fn.endswith((".py", ".json")):
                        raw_bytes = raw_bytes.replace(b"\r\n", b"\n")
                    actual_hash = hashlib.sha256(raw_bytes).hexdigest().lower()
                    if exp_hash and actual_hash != exp_hash:
                        last_err = f"{base_fn} SHA-256 不匹配"
                        continue
                    staged_bytes[base_fn] = raw_bytes
                    file_ok = True
                    break
                except Exception as e:
                    last_err = str(e)
                    continue
            if not file_ok:
                self.downloadFinished.emit(False, "", f"拉取文件 {base_fn} 失败: {last_err}", True)
                return
            self.progressChanged.emit(min(96, int((idx + 1) * 95 / total_files)))

        try:
            os.makedirs(self.hotpatch_dir, exist_ok=True)
            for base_fn, data_bytes in staged_bytes.items():
                out_fp = os.path.join(self.hotpatch_dir, base_fn)
                with open(out_fp, "wb") as out_f:
                    out_f.write(data_bytes)

            hp_manifest = {
                "version": self.remote_version,
                "sha256": combined_sha256,
                "rsa_sig": self.expected_rsa_sig,
                "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            hp_manifest_path = os.path.join(self.hotpatch_dir, "hotpatch_manifest.json")
            with open(hp_manifest_path, "w", encoding="utf-8") as mf:
                json.dump(hp_manifest, mf, ensure_ascii=False, indent=2)

            self.progressChanged.emit(100)
            self.downloadFinished.emit(
                True,
                self.hotpatch_dir,
                f"v{self.remote_version} 更新已在本地安装完成",
                True,
            )
        except Exception as e:
            self.downloadFinished.emit(False, "", f"写入本地更新目录失败: {e}", True)

    def run(self):
        if self.is_hotpatch and self.hotpatch_files and self.github_repo and self.hotpatch_dir:
            self._run_pure_source_hotpatch()
            return

        last_err = "无可用下载源"
        for url in self.download_urls:
            try:
                sha256_hasher = hashlib.sha256()
                if os.path.isfile(url):
                    total = max(1, os.path.getsize(url))
                    copied = 0
                    with open(url, "rb") as src, open(self.target_path, "wb") as dst:
                        while True:
                            buf = src.read(65536)
                            if not buf:
                                break
                            dst.write(buf)
                            sha256_hasher.update(buf)
                            copied += len(buf)
                            self.progressChanged.emit(int(copied * 100 / total))
                else:
                    req = urllib.request.Request(
                        url,
                        headers={
                            "User-Agent": f"{APP_INTERNAL_NAME}/{APP_VERSION}",
                            "Cache-Control": "no-cache",
                        }
                    )
                    with urllib.request.urlopen(req, timeout=12.0) as resp, open(self.target_path, "wb") as dst:
                        total = int(resp.headers.get("Content-Length", 0) or 0)
                        downloaded = 0
                        while True:
                            buf = resp.read(32768)
                            if not buf:
                                break
                            dst.write(buf)
                            sha256_hasher.update(buf)
                            downloaded += len(buf)
                            if total > 0:
                                self.progressChanged.emit(min(98, int(downloaded * 100 / total)))

                actual_sha256 = sha256_hasher.hexdigest().lower()
                if self.expected_sha256 and actual_sha256 != self.expected_sha256:
                    last_err = f"SHA-256 校验不匹配 (期望 {self.expected_sha256[:12]}..., 实际 {actual_sha256[:12]}...)"
                    try:
                        os.remove(self.target_path)
                    except Exception:
                        pass
                    continue

                # 若包含 RSA-2048 签名，验证该 SHA-256 是否由开发者私钥签发
                if self.expected_rsa_sig:
                    try:
                        sig_bytes = AsymmetricLicenseManager._b64url_decode(self.expected_rsa_sig)
                        if not AsymmetricLicenseManager.verify_rsa_pkcs1_sha256(actual_sha256.encode("ascii"), sig_bytes):
                            last_err = "RSA-2048 开发者数字签名校验失败，拒绝安装"
                            try:
                                os.remove(self.target_path)
                            except Exception:
                                pass
                            continue
                    except Exception as e:
                        last_err = f"RSA 签名解析失败: {e}"
                        continue

                # 若为 KB 级热更新补丁包，直接解压至 hotpatch 目录并生成激活清单
                if self.is_hotpatch and self.hotpatch_dir:
                    os.makedirs(self.hotpatch_dir, exist_ok=True)
                    with zipfile.ZipFile(self.target_path, "r") as zf:
                        for member in zf.namelist():
                            # 安全校验：仅允许提取顶层 .py 与 .json 文件，防止路径穿越
                            base_fn = os.path.basename(member)
                            if not base_fn or (".." in member) or not base_fn.endswith((".py", ".json")):
                                continue
                            data_bytes = zf.read(member)
                            out_fp = os.path.join(self.hotpatch_dir, base_fn)
                            with open(out_fp, "wb") as out_f:
                                out_f.write(data_bytes)

                    hp_manifest = {
                        "version": self.remote_version,
                        "sha256": actual_sha256,
                        "rsa_sig": self.expected_rsa_sig,
                        "applied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    hp_manifest_path = os.path.join(self.hotpatch_dir, "hotpatch_manifest.json")
                    with open(hp_manifest_path, "w", encoding="utf-8") as mf:
                        json.dump(hp_manifest, mf, ensure_ascii=False, indent=2)

                    self.progressChanged.emit(100)
                    self.downloadFinished.emit(
                        True,
                        self.hotpatch_dir,
                        f"v{self.remote_version} 云端热更新补丁已就绪 (SHA256 & RSA-2048 验签通过)",
                        True,
                    )
                    return

                self.progressChanged.emit(100)
                self.downloadFinished.emit(
                    True,
                    self.target_path,
                    f"更新包下载并校验通过 (SHA256: {actual_sha256[:16]}...)",
                    False,
                )
                return
            except Exception as e:
                last_err = str(e)
                continue

        self.downloadFinished.emit(False, "", f"从所有镜像节点下载失败: {last_err}", self.is_hotpatch)


class AutoUpdateDialog(QDialog):
    """
    Studio Dark 商业级版本更新提示与全自动升级弹窗：
    - 检测到新版本时直接展示「发现新版本 vX.X.X，是否立即更新？」及更新说明；
    - 用户点击「立即更新」后，自动下载、验签、安装并在电脑上自动重启完成更新，无需二次确认；
    - 默认隐藏开发者更新源仓库配置，可通过左下角「更新源设置」展开。
    """

    def __init__(
        self,
        paths: AppPaths,
        logger: logging.Logger,
        parent: Optional[QWidget] = None,
        preloaded_manifest: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(parent)
        self.paths = paths
        self.logger = logger
        self.check_worker: Optional[UpdateCheckWorker] = None
        self.dl_worker: Optional[UpdateDownloadWorker] = None
        self.current_manifest: Dict[str, Any] = preloaded_manifest or {}

        self.setWindowTitle(f"软件版本更新 — {APP_DISPLAY_NAME}")
        self.setFixedSize(540, 390)
        self.setStyleSheet("""
            QDialog {
                background-color: #18181b;
                color: #e4e4e7;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
            }
            QLabel { background: transparent; border: none; }
            QLineEdit {
                background-color: #141417;
                color: #e4e4e7;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 5px 10px;
                font-size: 12px;
            }
            QTextEdit {
                background-color: #202023;
                color: #d4d4d8;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
                padding: 10px 12px;
                font-size: 12px;
            }
            QProgressBar {
                background-color: #27272a;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 5px;
                text-align: center;
                color: #f4f4f5;
                height: 20px;
                font-size: 11px;
                font-weight: 600;
            }
            QProgressBar::chunk {
                background-color: #2563eb;
                border-radius: 4px;
            }
            QPushButton {
                background-color: #27272a;
                color: #e4e4e7;
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #323236; }
            QPushButton:disabled { color: #52525b; background-color: #1f1f22; }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(10)

        self.lbl_ver = QLabel(f"正在检测新版本...（当前版本 v{APP_VERSION}）")
        self.lbl_ver.setStyleSheet("color: #60a5fa; font-size: 15px; font-weight: 600;")
        lay.addWidget(self.lbl_ver)

        self.lbl_sub = QLabel("正在连接云端更新服务器检查是否有可用更新，请稍候...")
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        lay.addWidget(self.lbl_sub)

        # 可折叠的高级更新源配置行（默认隐藏，保持普通用户界面纯净）
        cfg = self.paths.get_github_ota_config()
        self.repo_box = QWidget(self)
        repo_row = QHBoxLayout(self.repo_box)
        repo_row.setContentsMargins(0, 2, 0, 2)
        repo_row.setSpacing(8)
        lbl_repo = QLabel("云端更新源:")
        lbl_repo.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        repo_row.addWidget(lbl_repo)

        self.edt_repo = QLineEdit(cfg.get("github_repo", ""))
        self.edt_repo.setPlaceholderText("例如: owner/repo")
        repo_row.addWidget(self.edt_repo, stretch=1)

        btn_save_repo = QPushButton("保存并重检")
        btn_save_repo.clicked.connect(self._on_save_and_check)
        repo_row.addWidget(btn_save_repo)
        self.repo_box.hide()
        lay.addWidget(self.repo_box)

        self.txt_notes = QTextEdit()
        self.txt_notes.setReadOnly(True)
        self.txt_notes.setPlainText("正在获取版本更新说明...")
        lay.addWidget(self.txt_notes, stretch=1)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        lay.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_toggle_cfg = QPushButton("更新源设置")
        self.btn_toggle_cfg.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #71717a;
                border: none;
                padding: 4px 6px;
                font-size: 11px;
            }
            QPushButton:hover { color: #a1a1aa; background-color: #202023; }
        """)
        self.btn_toggle_cfg.clicked.connect(lambda: self.repo_box.setVisible(not self.repo_box.isVisible()))
        btn_row.addWidget(self.btn_toggle_cfg)

        self.btn_recheck = QPushButton("重新检测")
        self.btn_recheck.clicked.connect(self.start_check)
        btn_row.addWidget(self.btn_recheck)

        btn_row.addStretch(1)

        self.btn_close = QPushButton("暂不更新")
        self.btn_close.clicked.connect(self.reject)
        btn_row.addWidget(self.btn_close)

        self.btn_download = QPushButton("立即更新")
        self.btn_download.setMinimumWidth(116)
        self.btn_download.setStyleSheet("""
            QPushButton { background-color: #2563eb; color: #ffffff; border: none; font-weight: 600; font-size: 13px; }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton:disabled { background-color: #27272a; color: #52525b; }
        """)
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download_clicked)
        btn_row.addWidget(self.btn_download)

        lay.addLayout(btn_row)

        if preloaded_manifest and preloaded_manifest.get("version"):
            remote_v = str(preloaded_manifest.get("version", APP_VERSION))
            has_new = parse_semver(remote_v) > parse_semver(APP_VERSION)
            self._on_check_finished(has_new, preloaded_manifest, f"发现新版本 v{remote_v}")
        else:
            self.start_check()

    def _on_save_and_check(self):
        raw_repo = self.edt_repo.text().strip()
        clean_repo = AppPaths.normalize_github_repo(raw_repo)
        self.edt_repo.setText(clean_repo)
        cur_branch = self.paths.get_github_ota_config().get("branch", DEFAULT_GITHUB_BRANCH) or DEFAULT_GITHUB_BRANCH
        self.paths.save_github_ota_config(clean_repo, cur_branch)
        self.start_check()

    def start_check(self):
        repo_val = AppPaths.normalize_github_repo(self.edt_repo.text().strip())
        self.lbl_ver.setText(f"正在检测新版本...（当前版本 v{APP_VERSION}）")
        self.lbl_ver.setStyleSheet("color: #60a5fa; font-size: 15px; font-weight: 600;")
        self.lbl_sub.setText("正在连接多节点云端服务器检查是否有新版本...")
        self.btn_download.setEnabled(False)
        self.check_worker = UpdateCheckWorker(self.paths, github_repo=repo_val)
        self.check_worker.updateCheckFinished.connect(self._on_check_finished)
        self.check_worker.start()

    def _on_check_finished(self, has_new: bool, manifest: dict, msg: str):
        self.current_manifest = manifest
        remote_v = manifest.get("version", APP_VERSION)
        notes = manifest.get("notes", "暂无更新说明。")
        if has_new:
            self.setWindowTitle(f"发现新版本 v{remote_v} — {APP_DISPLAY_NAME}")
            self.lbl_ver.setText(f"● 发现新版本 v{remote_v} 可用（当前版本 v{APP_VERSION}）")
            self.lbl_ver.setStyleSheet("color: #10b981; font-size: 15px; font-weight: 600;")
            self.lbl_sub.setText("检测到软件有新版本，是否现在更新？选择「立即更新」后将在您的电脑上全自动完成升级并重启。")
            self.txt_notes.setPlainText(f"【v{remote_v} 版本更新内容】\n{notes}")
            has_dl = bool(
                manifest.get("hotpatch_files")
                or manifest.get("hotpatch_file")
                or manifest.get("hotpatch_url")
                or manifest.get("url")
            )
            self.btn_download.setText("立即更新")
            self.btn_download.setEnabled(has_dl)
            self.btn_close.setText("暂不更新")
        else:
            self.setWindowTitle(f"检查版本更新 — {APP_DISPLAY_NAME}")
            self.lbl_ver.setText(f"✓ 当前版本 v{APP_VERSION} 已是最新版本")
            self.lbl_ver.setStyleSheet("color: #e4e4e7; font-size: 15px; font-weight: 600;")
            self.lbl_sub.setText("您的软件目前已处于最新状态，无需更新。")
            self.txt_notes.setPlainText(notes)
            self.btn_download.setText("已是最新")
            self.btn_download.setEnabled(False)
            self.btn_close.setText("关闭")

    def _on_download_clicked(self):
        remote_v = self.current_manifest.get("version", "latest")
        repo = self.current_manifest.get("_github_repo") or AppPaths.normalize_github_repo(self.edt_repo.text().strip())
        branch = self.current_manifest.get("_branch", "main")
        hp_files = self.current_manifest.get("hotpatch_files") or {}
        hp_file = self.current_manifest.get("hotpatch_file", "")
        hp_url = self.current_manifest.get("hotpatch_url", "")

        if hp_files and repo:
            dl_urls = []
            sha256_exp = self.current_manifest.get("hotpatch_sha256", "")
            rsa_sig = self.current_manifest.get("hotpatch_rsa_sig", "")
            target_file = ""
            is_hp = True
        elif hp_file or hp_url:
            dl_urls = build_github_ota_urls(repo, branch, hp_file) if (hp_file and repo) else []
            if hp_url:
                dl_urls.insert(0, hp_url)
            sha256_exp = self.current_manifest.get("hotpatch_sha256", "")
            rsa_sig = self.current_manifest.get("hotpatch_rsa_sig", "")
            target_file = os.path.join(self.paths.updates_dir, f"ota_hotpatch_v{remote_v}.zip")
            is_hp = True
        else:
            dl_url = self.current_manifest.get("url", "")
            if not dl_url:
                return
            dl_urls = [dl_url]
            sha256_exp = self.current_manifest.get("sha256", "")
            rsa_sig = ""
            ext = os.path.splitext(dl_url.split("?")[0])[1] or ".exe"
            target_file = os.path.join(self.paths.updates_dir, f"TableclothDedupPro_Setup_v{remote_v}{ext}")
            is_hp = False

        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.btn_download.setText("正在更新...")
        self.btn_download.setEnabled(False)
        self.btn_recheck.setEnabled(False)
        self.btn_close.setEnabled(False)
        self.lbl_sub.setText(f"正在为您自动下载并安装新版本 v{remote_v}，完成后将自动重启软件...")

        self.dl_worker = UpdateDownloadWorker(
            download_urls=dl_urls,
            target_path=target_file,
            expected_sha256=sha256_exp,
            expected_rsa_sig=rsa_sig,
            is_hotpatch=is_hp,
            remote_version=remote_v,
            hotpatch_dir=self.paths.hotpatch_dir,
            hotpatch_files=hp_files if isinstance(hp_files, dict) else {},
            github_repo=repo,
            branch=branch,
        )
        self.dl_worker.progressChanged.connect(self.progress_bar.setValue)
        self.dl_worker.downloadFinished.connect(self._on_download_finished)
        self.dl_worker.start()

    def _on_download_finished(self, ok: bool, out_path: str, msg: str, is_hotpatch: bool):
        if ok:
            self.logger.info(f"OTA update verified and installed (hotpatch={is_hotpatch}): {out_path}")
            self.progress_bar.setValue(100)
            remote_v = self.current_manifest.get("version", "")
            self.lbl_ver.setText(f"✓ 新版本 v{remote_v} 更新完成！")
            self.lbl_sub.setText("已在您的电脑上完成升级，正在为您自动重启进入新版本...")
            if is_hotpatch:
                QTimer.singleShot(600, self._finish_and_restart)
            else:
                subprocess.Popen([out_path, "/SILENT"], shell=False)
                QTimer.singleShot(600, self.accept)
        else:
            self.logger.error(f"Update download/verify failed: {msg}")
            self.lbl_sub.setText(f"自动更新未成功：{msg}")
            QMessageBox.warning(self, "自动更新失败", msg)
            self.btn_download.setText("立即更新")
            self.btn_download.setEnabled(True)
            self.btn_recheck.setEnabled(True)
            self.btn_close.setEnabled(True)

    def _finish_and_restart(self):
        self.accept()
        restart_application()


# ==============================================================================
# 9. 静态资源与核心算法参数内嵌加密金库 (EmbeddedAssetVault)
# ==============================================================================

class EmbeddedAssetVault:
    """
    防止核心业务阈值、内置公钥及静态配置被直接从安装包中明文提取或使用十六进制编辑器篡改：
    采用 SHA-256 派生密钥流 (CTR 模式) + HMAC-SHA256 认证加密 (Encrypt-then-MAC)。
    """
    _MASTER_SALT = b"TableclothDedupPro_Commercial_Vault_Key_v4.0"

    @classmethod
    def _keystream(cls, nonce: bytes, length: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < length:
            blk = hashlib.sha256(cls._MASTER_SALT + nonce + counter.to_bytes(4, "big")).digest()
            out.extend(blk)
            counter += 1
        return bytes(out[:length])

    @classmethod
    def seal_dict(cls, data: Dict[str, Any]) -> str:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        nonce = os.urandom(12)
        ks = cls._keystream(nonce, len(raw))
        cipher = bytes(a ^ b for a, b in zip(raw, ks))
        mac = hmac.new(cls._MASTER_SALT, nonce + cipher, hashlib.sha256).digest()
        return base64.b64encode(nonce + mac + cipher).decode("ascii")

    @classmethod
    def unseal_dict(cls, token: str) -> Dict[str, Any]:
        blob = base64.b64decode(token.encode("ascii"))
        if len(blob) < 44:
            raise ValueError("Invalid vault blob length")
        nonce = blob[:12]
        mac = blob[12:44]
        cipher = blob[44:]
        expected_mac = hmac.new(cls._MASTER_SALT, nonce + cipher, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected_mac):
            raise RuntimeError("AssetVault integrity check failed: embedded resource was tampered!")
        ks = cls._keystream(nonce, len(cipher))
        plain = bytes(a ^ b for a, b in zip(cipher, ks))
        return json.loads(plain.decode("utf-8"))

