#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信文件自动归类 (wechat-file-organizer) — 无头版
扫描微信接收文件，按类型/月份归类、去重、生成报告。

本脚本与 GUI 应用 wechat-file-organizer-gui（main.py，v1.16.0）的扫描逻辑
保持一致，作为无头/定时任务/自动化场景的对应物。

设计原则：
- 零依赖：仅用 Python 标准库，无需 pip install。
- 安全优先：默认 dry-run（只读），绝不改动任何源文件；--apply 才是复制。
- 清理可恢复：--trash 只会把源文件移入回收站/废纸篓（可恢复），绝不永久删除。
- 可移植：路径全部运行时推导，无写死绝对路径；支持 Windows / macOS / Linux。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime

# 平台标识：win / mac / linux
PLATFORM = "mac" if sys.platform == "darwin" else (
    "win" if os.name == "nt" else "linux")

MB = 1024 * 1024

# 分类规则：扩展名 -> 类别
CATEGORIES = {
    "文档":   ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md",
               "csv", "rtf", "wps", "ofd", "pages", "key", "numbers", "epub", "mobi"],
    "图片":   ["png", "jpg", "jpeg", "gif", "bmp", "webp", "heic", "tiff", "tif", "svg"],
    "压缩包": ["zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst"],
    "视频":   ["mp4", "mov", "avi", "mkv", "wmv", "flv", "webm", "m4v"],
    "音频":   ["mp3", "wav", "m4a", "aac", "flac", "ogg", "wma"],
    "其他":   [],
}
EXT_TO_CAT = {}
for _cat, _exts in CATEGORIES.items():
    for _e in _exts:
        EXT_TO_CAT[_e] = _cat

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")

# 兼容模式（递归扫描）时跳过的微信系统/缓存目录
SYSTEM_DIRS = {
    "all_users", "db_storage", "apm_record", "business", "resource",
    "cache", "backup", "temp", "tmp", "logs", "log", "config", "mmkv",
    "thumb", "thumbs", ".thumbnails", "favorite", "emoticon", "sns",
    "xweb", "xeditor", "migrate", "InputTemp", "MsgAttach",
}

# 跳过的微信内部文件扩展名（非用户主动保存的文件）
SKIP_EXTS = {
    ".dat", ".db", ".db-wal", ".db-shm", ".mmkv", ".crc", ".kvdb",
    ".kvdb-wal", ".kvdb-shm", ".ini", ".lock", ".tmp", ".temp", ".bak",
    ".shm", ".wal", ".sqlite", ".sqlitedb",
}

# macOS 微信沙盒中 MessageTemp 下用户文件的类型子目录
MAC_FILE_SUBDIRS = {"File", "Image", "Video", "Audio"}
# 删除操作在 mac/linux 上的叫法（仅提示文案）
TRASH_LABEL = {"win": "回收站", "mac": "废纸篓", "linux": "废纸篓"}[PLATFORM]


# ---------- 中文宽度对齐 ----------
def wlen(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def wpad(s, width, fill=" "):
    s = str(s)
    return s + fill * max(0, width - wlen(s))


def human(n):
    if n >= 1024 ** 3:
        return "%.1f GB" % (n / 1024 ** 3)
    if n >= MB:
        return "%.1f MB" % (n / MB)
    if n >= 1024:
        return "%.1f KB" % (n / 1024)
    return "%d B" % n


def log(*a):
    print(*a)


def cat_of(path):
    ext = os.path.splitext(path)[1].lstrip(".").lower()
    return EXT_TO_CAT.get(ext, "其他")


def month_of(path):
    # 优先用 File/YYYY-MM 或 msg/file/YYYY-MM 父目录名
    parent = os.path.basename(os.path.dirname(path))
    m = MONTH_RE.match(parent)
    if m:
        return "%s-%s" % (m.group(1), m.group(2))
    try:
        t = os.path.getmtime(path)
        return datetime.fromtimestamp(t).strftime("%Y-%m")
    except OSError:
        return "未知"


def sha256_of(p, chunk=1 << 20):
    h = hashlib.sha256()
    try:
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(chunk), b""):
                h.update(b)
    except OSError:
        return "ERR"
    return h.hexdigest()


# ---------- 路径发现 ----------
def _is_account_dir(d):
    """是否为单个微信账号目录（Windows 认 msg/FileStorage，mac 认 Message）。"""
    if PLATFORM == "mac":
        return os.path.isdir(os.path.join(d, "Message"))
    return (os.path.isdir(os.path.join(d, "msg"))
            or os.path.isdir(os.path.join(d, "FileStorage")))


def _mac_wechat_roots():
    """返回 macOS 微信沙盒账号目录列表（按版本号倒序）。非 mac 返回 []。"""
    if PLATFORM != "mac":
        return []
    base = os.path.expanduser(
        "~/Library/Containers/com.tencent.xinWeChat/Data/Library/"
        "Application Support/com.tencent.xinWeChat")
    if not os.path.isdir(base):
        return []
    roots = []
    try:
        for ver in sorted(os.listdir(base), reverse=True):
            vdir = os.path.join(base, ver)
            if not os.path.isdir(vdir):
                continue
            for acct in os.listdir(vdir):
                d = os.path.join(vdir, acct)
                if os.path.isdir(d) and os.path.isdir(os.path.join(d, "Message")):
                    if d not in roots:
                        roots.append(d)
    except OSError:
        pass
    return roots


def _scan_for_wechat_all(root, max_depth=4, limit=8):
    """在 root 下有限深度搜索所有微信文件根目录。"""
    found = []
    if not os.path.isdir(root):
        return found
    root = os.path.normpath(root)
    try:
        for dirpath, dirnames, _ in os.walk(root):
            depth = dirpath[len(root):].count(os.sep)
            if depth > max_depth:
                dirnames[:] = []
                continue
            if "FileStorage" in dirnames or "msg" in dirnames:
                p = os.path.dirname(dirpath) or dirpath
                if p not in found:
                    found.append(p)
                if len(found) >= limit:
                    break
    except OSError:
        pass
    return found


def find_all_wechat_dirs():
    """探测电脑上所有微信文件根目录（新版/旧版/自定义可并存）。"""
    out = []

    def add(p):
        if not p or not os.path.isdir(p):
            return
        p = os.path.normpath(p)
        low = p.lower()
        if all(low != x.lower() for x in out):
            out.append(p)

    env = os.environ.get("WECHAT_FILES_DIR")
    if env:
        add(env)
    if PLATFORM == "mac":
        for d in _mac_wechat_roots():
            add(d)
        return out
    home = os.path.expanduser("~")
    for name in ("WeChat Files", "Weixin Files", "xwechat_files"):
        add(os.path.join(home, "Documents", name))
        add(os.path.join(home, name))
    for p in _scan_for_wechat_all(os.path.join(home, "Documents"), max_depth=4):
        add(p)
    return out


def find_wechat_files_dir():
    """探测单个最优先的微信根目录（供 --source 未指定时使用）。"""
    env = os.environ.get("WECHAT_FILES_DIR")
    if env and os.path.isdir(env):
        return env
    dirs = find_all_wechat_dirs()
    return dirs[0] if dirs else None


def discover_account_dirs(root):
    """返回 root 下的微信账号目录列表（新旧结构均可，mac BFS 下探）。"""
    if not root or not os.path.isdir(root):
        return []
    root = os.path.normpath(root)
    if _is_account_dir(root):
        return [root]
    accounts = []
    if PLATFORM == "mac":
        from collections import deque
        q = deque([(root, 0)])
        seen = set()
        while q:
            d, depth = q.popleft()
            if d in seen:
                continue
            seen.add(d)
            if _is_account_dir(d):
                if d not in accounts:
                    accounts.append(d)
                continue
            if depth >= 6:
                continue
            try:
                for name in sorted(os.listdir(d)):
                    dd = os.path.join(d, name)
                    if os.path.isdir(dd):
                        q.append((dd, depth + 1))
            except OSError:
                pass
        return accounts
    try:
        for name in sorted(os.listdir(root)):
            d = os.path.join(root, name)
            if os.path.isdir(d) and _is_account_dir(d) and d not in accounts:
                accounts.append(d)
    except OSError:
        pass
    return accounts


def account_label_of(path, root):
    """判断文件属于哪个微信账号，返回账号目录名。"""
    r = os.path.normpath(root)
    p = os.path.normpath(path)
    if _is_account_dir(r):
        return os.path.basename(r)
    if p.lower().startswith(r.lower() + os.sep):
        parts = os.path.relpath(p, r).split(os.sep)
        if len(parts) > 1:
            return parts[0]
    return os.path.basename(r)


def discover_accounts(root):
    """返回所有『用户接收文件目录』（旧版 FileStorage / 新版 msg/file）。"""
    if os.path.basename(root).lower() == "filestorage":
        return [root]
    targets = []
    if not os.path.isdir(root):
        return targets
    if os.path.isdir(os.path.join(root, "File")):
        targets.append(root)
        return targets
    mf_self = os.path.join(root, "msg", "file")
    if os.path.isdir(mf_self):
        targets.append(mf_self)
    fs_self = os.path.join(root, "FileStorage")
    if os.path.isdir(fs_self):
        targets.append(fs_self)
    for name in os.listdir(root):
        d = os.path.join(root, name)
        if not os.path.isdir(d):
            continue
        fs = os.path.join(d, "FileStorage")
        if os.path.isdir(fs):
            targets.append(fs)
        mf = os.path.join(d, "msg", "file")
        if os.path.isdir(mf):
            targets.append(mf)
    return targets


def recursive_collect(root):
    """兼容模式：递归扫描整个目录，跳过微信系统目录与内部文件。"""
    files = []
    seen = set()
    for dirpath, dirnames, fnames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d.lower() not in SYSTEM_DIRS and not d.startswith(".")]
        for fn in fnames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXTS:
                continue
            p = os.path.join(dirpath, fn)
            if p in seen:
                continue
            seen.add(p)
            files.append(p)
    return files


def collect_mac_files(acct_dir, include_media=False):
    """收集 macOS 账号目录下 MessageTemp 中的用户文件（四类类型目录）。"""
    files = []
    msg_temp = os.path.join(acct_dir, "Message", "MessageTemp")
    if not os.path.isdir(msg_temp):
        return files
    keep = set(MAC_FILE_SUBDIRS) if include_media else {"File"}
    walked = set()

    def collect_under(p):
        try:
            for dp, _, fnames in os.walk(p):
                for fn in fnames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in SKIP_EXTS:
                        continue
                    files.append(os.path.join(dp, fn))
        except OSError:
            pass

    def descend(d):
        if d in walked:
            return
        walked.add(d)
        try:
            entries = sorted(os.listdir(d))
        except OSError:
            return
        for e in entries:
            p = os.path.join(d, e)
            if not os.path.isdir(p):
                continue
            if e in keep:
                collect_under(p)
            else:
                descend(p)

    descend(msg_temp)
    return files


def collect_files(roots, include_media=False, scan_all=False, recursive=False):
    """扫描多个微信根目录，返回 (path, account) 列表（已去重）。"""
    out = []
    seen = set()
    if isinstance(roots, str):
        roots = [roots]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        if PLATFORM == "mac":
            for acct in (discover_account_dirs(root) or [root]):
                for p in collect_mac_files(acct, include_media or scan_all):
                    key = os.path.normcase(p)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((p, os.path.basename(acct)))
            continue
        if recursive:
            files = recursive_collect(root)
            if not include_media:
                files = [f for f in files
                         if os.path.splitext(f)[1].lower() != ".dat"]
            for p in files:
                key = os.path.normcase(p)
                if key in seen:
                    continue
                seen.add(key)
                out.append((p, account_label_of(p, root)))
            continue
        targets = discover_accounts(root)
        if not targets:
            targets = [root]
        for target in targets:
            dirs_to_walk = []
            if os.path.basename(target).lower() == "filestorage":
                file_dir = os.path.join(target, "File")
                if os.path.isdir(file_dir):
                    dirs_to_walk.append(file_dir)
                if scan_all:
                    for sub in ("Image", "Video", "Voice", "Attachment",
                                "CustomEmotion", "Fav"):
                        sd = os.path.join(target, sub)
                        if os.path.isdir(sd):
                            dirs_to_walk.append(sd)
            else:
                dirs_to_walk.append(target)
            for t in dirs_to_walk:
                for dirpath, _, fnames in os.walk(t):
                    for fn in fnames:
                        ext = os.path.splitext(fn)[1].lower()
                        if ext in SKIP_EXTS:
                            continue
                        if not include_media and ext == ".dat":
                            continue
                        p = os.path.join(dirpath, fn)
                        key = os.path.normcase(p)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append((p, account_label_of(p, root)))
    return out


# ---------- 回收站（可恢复删除） ----------
def send_to_recycle_bin(paths):
    """把文件移入系统回收站（可恢复）。返回 (ok, failures)。

    Windows: SHFileOperationW；macOS: osascript Finder delete；Linux: 跳过。
    任何平台删除失败都只计入 failures，绝不静默回退为永久删除。
    """
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        return 0, []

    if PLATFORM == "linux":
        return 0, [(p, "Linux 暂不支持移入%s，已跳过（未删除任何文件）" % TRASH_LABEL)
                   for p in paths]

    if PLATFORM == "mac":
        def esc(s):
            return s.replace("\\", "\\\\").replace('"', '\\"')

        def run_osa(script):
            try:
                r = subprocess.run(["osascript", "-e", script],
                                   capture_output=True, text=True)
                return r.returncode == 0, (r.stderr or r.stdout).strip()
            except Exception as e:
                return False, str(e)

        items = ", ".join('POSIX file "%s"' % esc(p) for p in paths)
        ok_all, _err = run_osa('tell application "Finder" to delete {%s}' % items)
        if ok_all:
            return len(paths), []
        ok = 0
        failures = []
        for p in paths:
            ok_one, err_one = run_osa(
                'tell application "Finder" to delete POSIX file "%s"' % esc(p))
            if ok_one:
                ok += 1
            else:
                failures.append((p, "移入%s失败: %s" % (TRASH_LABEL, err_one[:200])))
        return ok, failures

    import ctypes
    from ctypes import wintypes
    try:
        shell32 = ctypes.windll.shell32
    except Exception:
        return 0, [(p, "无法调用系统%s，已跳过（未删除任何文件）" % TRASH_LABEL)
                   for p in paths]

    class SHFILEOPSTRUCT(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.UINT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_NOERRORUI = 0x0400
    FOF_SILENT = 0x0004

    from_str = "\0".join(paths) + "\0\0"
    op = SHFILEOPSTRUCT()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = from_str
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    rc = shell32.SHFileOperationW(ctypes.byref(op))
    if rc == 0 and not op.fAnyOperationsAborted:
        return len(paths), []
    failures = [(p, "仍存在于磁盘 (rc=%r)" % rc) for p in paths if os.path.exists(p)]
    return len(paths) - len(failures), failures


def dest_path(dest_root, scheme, cat, month, fname, used):
    if scheme == "month":
        rel = os.path.join(month, fname)
    elif scheme == "type-month":
        rel = os.path.join(cat, month, fname)
    else:  # type
        rel = os.path.join(cat, fname)
    base, ext = os.path.splitext(fname)
    cand = rel
    i = 1
    while os.path.join(dest_root, cand) in used or os.path.exists(os.path.join(dest_root, cand)):
        cand = os.path.join(os.path.dirname(rel), "%s_%d%s" % (base, i, ext))
        i += 1
    used.add(os.path.join(dest_root, cand))
    return os.path.join(dest_root, cand)


def main():
    ap = argparse.ArgumentParser(
        description="微信文件自动归类（零依赖，默认只读 dry-run，与 GUI 版扫描逻辑一致）")
    ap.add_argument("--source", help="微信根目录；默认自动探测本机所有微信目录（多账号合并）")
    ap.add_argument("--dest", help="归类输出目录；默认在 source 同级建 WeChatFiles_Organized")
    ap.add_argument("--scheme", choices=["type", "month", "type-month"], default="type",
                    help="归类方式（默认 type：按类型）")
    ap.add_argument("--apply", action="store_true",
                    help="真正复制归类（默认仅 dry-run 报告，不改动任何文件）")
    ap.add_argument("--trash", action="store_true",
                    help="配合 --apply：复制成功后把源文件移入%s（可恢复），Linux 跳过" % TRASH_LABEL)
    ap.add_argument("--dedupe", action="store_true",
                    help="去重：相同内容的文件只保留一份（配合 --apply 生效）")
    ap.add_argument("--include-media", action="store_true",
                    help="连 Image/Video 里的 .dat 也处理（默认跳过）")
    ap.add_argument("--scan-all", action="store_true",
                    help="扫描 FileStorage 全部子目录（含图片/视频/语音等）")
    ap.add_argument("--top", type=int, default=10,
                    help="报告里列出最大的前 N 个文件（默认 10，0 关闭）")
    ap.add_argument("--old-days", type=int, default=365,
                    help="超过该天数的文件计为“老旧”（默认 365）")
    ap.add_argument("--json", action="store_true",
                    help="输出 JSON（便于脚本/定时任务消费）")
    args = ap.parse_args()

    roots = [args.source] if args.source else find_all_wechat_dirs()
    roots = [r for r in roots if r and os.path.isdir(r)]
    if not roots:
        msg = {"ok": False, "error": "找不到微信文件目录",
               "hint": "请用 --source 指定微信目录，或设置 WECHAT_FILES_DIR 环境变量"}
        log(json.dumps(msg, ensure_ascii=False) if args.json else
            "[FAIL] 找不到微信文件目录。请用 --source 指定，或设置 WECHAT_FILES_DIR。")
        return 2

    files = collect_files(roots, include_media=args.include_media,
                          scan_all=args.scan_all)
    if not files:
        msg = {"ok": True, "files": 0, "note": "未发现可归类的文件"}
        log(json.dumps(msg, ensure_ascii=False) if args.json else "[SKIP] 未发现可归类的文件。")
        return 0

    records = []
    for p, acct in files:
        try:
            st = os.stat(p)
            records.append({
                "path": p, "account": acct, "cat": cat_of(p), "month": month_of(p),
                "size": st.st_size, "hash": sha256_of(p), "mtime": st.st_mtime,
            })
        except OSError:
            continue

    total = len(records)
    total_size = sum(r["size"] for r in records)
    accounts = sorted({r["account"] for r in records})

    by_cat = {}
    for r in records:
        c = by_cat.setdefault(r["cat"], [0, 0])
        c[0] += 1
        c[1] += r["size"]

    groups = {}
    for r in records:
        groups.setdefault(r["hash"], []).append(r)
    dupes = {h: rs for h, rs in groups.items() if len(rs) > 1}
    dup_count = sum(len(rs) - 1 for rs in dupes.values())
    dup_recover = sum(max(x["size"] for x in rs) * (len(rs) - 1) for rs in dupes.values())

    now = datetime.now().timestamp()
    old = [r for r in records if now - r["mtime"] > args.old_days * 86400]
    top = sorted(records, key=lambda r: r["size"], reverse=True)[:max(0, args.top)]

    copied = skipped_dup = trashed = 0
    trash_failures = []
    if args.apply:
        dest = args.dest or os.path.join(
            os.path.dirname(os.path.abspath(roots[0])), "WeChatFiles_Organized")
        os.makedirs(dest, exist_ok=True)
        used = set()
        seen_hash = set()
        to_trash = []
        for r in records:
            if args.dedupe and r["hash"] in seen_hash:
                skipped_dup += 1
                continue
            seen_hash.add(r["hash"])
            dp = dest_path(dest, args.scheme, r["cat"], r["month"],
                           os.path.basename(r["path"]), used)
            try:
                os.makedirs(os.path.dirname(dp), exist_ok=True)
                shutil.copy2(r["path"], dp)
                copied += 1
                if args.trash:
                    to_trash.append(r["path"])
            except OSError as e:
                log("[WARN] 复制失败 %s: %s" % (r["path"], e))
        if args.trash and to_trash:
            trashed, trash_failures = send_to_recycle_bin(to_trash)
            for p, reason in trash_failures:
                log("[WARN] 移入%s失败 %s: %s" % (TRASH_LABEL, p, reason))

    if args.json:
        out = {
            "ok": True, "applied": bool(args.apply), "scheme": args.scheme,
            "platform": PLATFORM, "sources": roots,
            "accounts": accounts, "account_count": len(accounts),
            "total_files": total, "total_size": total_size,
            "by_category": {k: {"count": v[0], "size": v[1]} for k, v in by_cat.items()},
            "duplicates": {"groups": len(dupes), "extra_files": dup_count,
                           "recoverable_bytes": dup_recover},
            "old_files": len(old),
            "top_files": [{"path": r["path"], "size": r["size"],
                           "cat": r["cat"], "account": r["account"]} for r in top],
        }
        if args.apply:
            out["result"] = {"dest": dest, "copied": copied,
                             "skipped_duplicates": skipped_dup,
                             "trashed": trashed,
                             "trash_failures": len(trash_failures)}
        log(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    log("=" * 50)
    log("微信文件归类报告  (%s)" % ("APPLY 已执行" if args.apply else "DRY-RUN 只读"))
    log("源目录: %s" % (roots[0] if len(roots) == 1 else
                   "%d 个微信目录（已合并扫描）" % len(roots)))
    if len(accounts) > 1:
        log("微信账号: %d 个（%s）" % (len(accounts), "、".join(accounts)))
    log("-" * 50)
    log("%s: %d" % (wpad("文件总数", 12), total))
    log("%s: %s" % (wpad("总大小", 12), human(total_size)))
    log("-" * 50)
    log("按类型:")
    for cat in CATEGORIES:
        if cat in by_cat:
            c = by_cat[cat]
            log("  %s  %5d 个  %s" % (wpad(cat, 8), c[0], human(c[1])))
    log("-" * 50)
    log("%s: %d 组, 重复文件 %d 个, 可节省 %s"
        % (wpad("重复文件", 12), len(dupes), dup_count, human(dup_recover)))
    log("%s: %d 个 (超过 %d 天)" % (wpad("老旧文件", 12), len(old), args.old_days))
    if top:
        log("-" * 50)
        log("最大的 %d 个文件:" % len(top))
        for r in top:
            acct = ("[%s] " % r["account"]) if len(accounts) > 1 else ""
            log("  %s  %s%s" % (wpad(human(r["size"]), 10), acct, r["path"]))
    log("=" * 50)

    if args.apply:
        log("[OK] 已归类到: %s" % dest)
        extra = "，去重跳过 %d 个" % skipped_dup if args.dedupe else ""
        log("      复制 %d 个文件%s" % (copied, extra))
        if args.trash:
            log("      移入%s %d 个（失败 %d 个）" % (TRASH_LABEL, trashed,
                                                len(trash_failures)))
    else:
        log("[DRY-RUN] 未做任何改动。加 --apply 才真正复制归类。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
