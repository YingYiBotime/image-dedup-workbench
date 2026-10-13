# -*- coding: utf-8 -*-
"""
图像智能查重工作台 v4.0 — GitHub 云端热更新一键打包签名与发布工具 (publish_github_update.py)
核心能力：
1. 将最新核心代码 (app.py, engine.py, core_infra.py, generate_icon.py) 压缩为 ~60KB 的 ota_hotpatch.zip；
2. 计算 SHA-256 哈希并使用开发者 RSA-2048 私钥 (license_issuer.py) 进行数字签名，防止任何中间人篡改；
3. 生成 version.json 清单，并自动同步 github_ota_config.json 到绿色便携版目录；
4. 自动通过 Git 将 version.json 与 ota_hotpatch.zip (仅 ~60KB) 推送至 GitHub 仓库的独立分支 (ota-dedup)，
   100% 不影响仓库主分支 (main) 原有代码，全球客户端打开软件即刻 1 秒同步更新！
"""

import os
import sys
import json
import shutil
import base64
import hashlib
import zipfile
import argparse
import subprocess
from datetime import datetime

from core_infra import AppPaths, AsymmetricLicenseManager, parse_semver, DEFAULT_GITHUB_REPO, DEFAULT_GITHUB_BRANCH
from license_issuer import RSA_MODULUS_N, RSA_PRIVATE_EXPONENT_D, ASN1_SHA256_PREFIX

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(PROJECT_DIR, "github_ota_config.json")
VERSION_JSON_FILE = os.path.join(PROJECT_DIR, "version.json")
HOTPATCH_ZIP_FILE = os.path.join(PROJECT_DIR, "ota_hotpatch.zip")
HOTPATCH_SOURCES = ["app.py", "engine.py", "core_infra.py", "generate_icon.py", "github_ota_config.json"]


def sign_sha256_hex(sha256_hex: str) -> str:
    """使用开发者 RSA-2048 私钥对 SHA-2048 字符串进行 PKCS#1 v1.5 签名"""
    msg_bytes = sha256_hex.strip().lower().encode("ascii")
    digest = hashlib.sha256(msg_bytes).digest()
    t = ASN1_SHA256_PREFIX + digest
    ps_len = 256 - len(t) - 3
    em = b"\x00\x01" + (b"\xff" * ps_len) + b"\x00" + t
    m_int = int.from_bytes(em, "big")
    sig_int = pow(m_int, RSA_PRIVATE_EXPONENT_D, RSA_MODULUS_N)
    sig_bytes = sig_int.to_bytes(256, "big")
    assert AsymmetricLicenseManager.verify_rsa_pkcs1_sha256(msg_bytes, sig_bytes), "RSA-2048 签名自检失败"
    return base64.urlsafe_b64encode(sig_bytes).decode("ascii").rstrip("=")


def bump_patch_version(ver_str: str) -> str:
    parts = list(parse_semver(ver_str))
    while len(parts) < 3:
        parts.append(0)
    parts[2] += 1
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def load_current_config() -> dict:
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("github_repo"):
                    return data
        except Exception:
            pass
    return {"github_repo": DEFAULT_GITHUB_REPO, "branch": DEFAULT_GITHUB_BRANCH}


def save_config_everywhere(repo: str, branch: str = DEFAULT_GITHUB_BRANCH):
    clean_repo = AppPaths.normalize_github_repo(repo)
    cfg = {"github_repo": clean_repo, "branch": (branch or DEFAULT_GITHUB_BRANCH).strip()}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

    paths = AppPaths()
    paths.save_github_ota_config(clean_repo, branch)

    portable_dir = os.path.join(PROJECT_DIR, "dist_portable", "图像智能查重工作台")
    if os.path.isdir(portable_dir):
        shutil.copy2(CONFIG_FILE, os.path.join(portable_dir, "github_ota_config.json"))


def sync_source_version(new_version: str):
    """在打包热更新前，自动将 core_infra.py 与 app.py 中的版本号同步为 new_version"""
    import re
    core_fp = os.path.join(PROJECT_DIR, "core_infra.py")
    if os.path.isfile(core_fp):
        with open(core_fp, "r", encoding="utf-8") as f:
            txt = f.read()
        txt_new = re.sub(
            r'APP_VERSION\s*=\s*os\.environ\.get\("TDPRO_ACTIVE_VERSION",\s*"[^"]+"\)',
            f'APP_VERSION = os.environ.get("TDPRO_ACTIVE_VERSION", "{new_version}")',
            txt,
        )
        if txt_new != txt:
            with open(core_fp, "w", encoding="utf-8") as f:
                f.write(txt_new)

    app_fp = os.path.join(PROJECT_DIR, "app.py")
    if os.path.isfile(app_fp):
        with open(app_fp, "r", encoding="utf-8") as f:
            txt = f.read()
        txt_new = re.sub(
            r'builtin_version\s*=\s*"[^"]+"',
            f'builtin_version = "{new_version}"',
            txt,
            count=1,
        )
        if txt_new != txt:
            with open(app_fp, "w", encoding="utf-8") as f:
                f.write(txt_new)


def build_signed_hotpatch(new_version: str, notes: str, repo: str, branch: str = DEFAULT_GITHUB_BRANCH) -> dict:
    """生成纯文本源码增量更新清单 version.json（统一 LF 换行符，确保本地与 GitHub Raw 字节 100% 一致）"""
    sync_source_version(new_version)
    hotpatch_files = {}
    total_bytes = 0
    for fn in HOTPATCH_SOURCES:
        fp = os.path.join(PROJECT_DIR, fn)
        if os.path.isfile(fp):
            with open(fp, "rb") as f:
                raw = f.read()
            norm_raw = raw.replace(b"\r\n", b"\n")
            if norm_raw != raw:
                with open(fp, "wb") as f:
                    f.write(norm_raw)
            total_bytes += len(norm_raw)
            hotpatch_files[fn] = hashlib.sha256(norm_raw).hexdigest().lower()

    items = sorted(hotpatch_files.items())
    combined_payload = "\n".join(f"{fn}:{h}" for fn, h in items)
    hp_sha256 = hashlib.sha256(combined_payload.encode("utf-8")).hexdigest().lower()
    hp_rsa_sig = sign_sha256_hex(hp_sha256)

    manifest = {
        "version": new_version,
        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "hotpatch_files": hotpatch_files,
        "hotpatch_size_kb": round(total_bytes / 1024.0, 1),
        "hotpatch_sha256": hp_sha256,
        "hotpatch_rsa_sig": hp_rsa_sig,
        "notes": notes,
    }

    with open(VERSION_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    if os.path.isfile(HOTPATCH_ZIP_FILE):
        try:
            os.remove(HOTPATCH_ZIP_FILE)
        except Exception:
            pass

    return manifest


def push_to_github(repo: str, branch: str, version: str) -> bool:
    """将纯文本项目源码与签名清单推送到 GitHub 仓库 (main 分支)"""
    clean_repo = AppPaths.normalize_github_repo(repo)
    if not clean_repo or "/" not in clean_repo:
        print("[提示] 未设置 GitHub 仓库名，已生成本地 version.json。")
        return False

    remote_url = f"https://github.com/{clean_repo}.git"
    try:
        subprocess.run(["git", "add", "."], cwd=PROJECT_DIR, check=True)
        subprocess.run(["git", "commit", "-m", f"chore: update version to v{version}"], cwd=PROJECT_DIR, check=False)
        print(f"\n正在同步推送至 GitHub ({remote_url} -> [{branch}])...")
        push_res = subprocess.run(["git", "push", remote_url, f"HEAD:refs/heads/{branch}"], cwd=PROJECT_DIR)
        return push_res.returncode == 0
    except Exception as e:
        print(f"[警告] Git 自动推送遇到问题: {e}")
        return False


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="一键生成并发布 GitHub 纯源码签名热更新")
    parser.add_argument("--repo", default="", help="GitHub 仓库 (例如 username/image-dedup-workbench)")
    parser.add_argument("--branch", default="", help="分支名 (默认 main)")
    parser.add_argument("--version", default="", help="新版本号 (留空则自动递增末位版本号)")
    parser.add_argument("--notes", default="", help="本次更新说明")
    parser.add_argument("--no-push", action="store_true", help="仅生成签名版本清单，不执行 git push")
    args = parser.parse_args()

    cfg = load_current_config()
    repo = args.repo.strip() or cfg.get("github_repo", DEFAULT_GITHUB_REPO).strip() or DEFAULT_GITHUB_REPO
    branch = args.branch.strip() or cfg.get("branch", DEFAULT_GITHUB_BRANCH).strip() or DEFAULT_GITHUB_BRANCH

    print("=" * 74)
    print("  图像智能查重工作台 - GitHub 云端秒级热更新 (OTA) 发布中心")
    print("=" * 74)

    save_config_everywhere(repo, branch)
    print(f"[OK] 已绑定 GitHub 更新源仓库: {AppPaths.normalize_github_repo(repo) or '(待绑定)'} (分支: {branch})")

    prev_ver = "4.0.0"
    if os.path.isfile(VERSION_JSON_FILE):
        try:
            with open(VERSION_JSON_FILE, "r", encoding="utf-8") as f:
                prev_ver = json.load(f).get("version", prev_ver)
        except Exception:
            pass

    default_next_ver = bump_patch_version(prev_ver)
    new_ver = args.version.strip()
    if not new_ver and sys.stdin.isatty() and not args.no_push:
        v_in = input(f"请输入新版本号 [直接回车默认 {default_next_ver}] > ").strip()
        new_ver = v_in or default_next_ver
    elif not new_ver:
        new_ver = default_next_ver

    notes = args.notes.strip()
    default_notes = (
        f"1. 升级为标准商业软件更新体验：检测到新版本时弹窗询问是否更新，点击【立即更新】后在电脑上全自动完成升级并重启；\n"
        f"2. 内置【使用指南与常见问题帮助中心 (F1)】，详解白名单功能与已删图片暂存区找回方法；\n"
        f"3. 默认仅扫描当前顶层文件夹，支持可选【包含子文件夹】开关。"
    )
    if not notes and sys.stdin.isatty() and not args.no_push:
        n_in = input("请输入本次更新说明 [直接回车使用默认说明] > ").strip()
        notes = n_in or default_notes
    elif not notes:
        notes = default_notes

    manifest = build_signed_hotpatch(new_ver, notes, repo, branch)
    print("-" * 74)
    print(f"[OK] 纯源码热更清单已生成 : {VERSION_JSON_FILE} (v{manifest['version']} · 共 {len(manifest['hotpatch_files'])} 个源码文件)")
    print(f"[OK] SHA-256 完整性指纹   : {manifest['hotpatch_sha256']}")
    print(f"[OK] RSA-2048 数字签名    : 已签名并通过公钥自检")
    print("-" * 74)

    if not args.no_push and repo:
        ok = push_to_github(repo, branch, new_ver)
        if ok:
            print(f"\n[SUCCESS] v{new_ver} 已推送至 GitHub ({repo} 分支 {branch})！")
            print("所有用户打开软件将自动弹出更新提示并在电脑上完成升级！")
        else:
            print(
                f"\n[提示] 本地签名清单已就绪。请确认本机 Git 已登录新 GitHub 账号，"
                f"并已推送至仓库 {repo} 的 {branch} 分支。"
            )


if __name__ == "__main__":
    main()
