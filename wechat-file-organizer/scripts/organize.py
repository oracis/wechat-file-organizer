#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微信文件自动归类 (wechat-file-organizer)
扫描微信 FileStorage/File 目录，按类型/月份归类、去重、生成报告。

设计原则：
- 零依赖：仅用 Python 标准库，无需 pip install。
- 安全优先：默认 dry-run（只读），绝不改动任何源文件；--apply 才是复制。
- 可移植：路径全部运行时推导，无写死的绝对路径。
- 中文对齐：用 east-asian width 修正 %-10s 之类的中文错位。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import datetime

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
    # 优先用 File/YYYY-MM 父目录名
    parent = os.path.basename(os.path.dirname(path))
    m = MONTH_RE.match(parent)
    if m:
        return "%s-%s" % (m.group(1), m.group(2))
    # 其次用文件修改时间
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
def find_wechat_files_dir():
    env = os.environ.get("WECHAT_FILES_DIR")
    if env and os.path.isdir(env):
        return env
    base = os.path.expanduser(os.path.join("~", "Documents", "WeChat Files"))
    if os.path.isdir(base):
        return base
    return None


def discover_accounts(root):
    """返回所有含 FileStorage 的账号目录列表（绝对路径）。"""
    if os.path.basename(root).lower() == "filestorage":
        return [root]
    accounts = []
    if os.path.isdir(root):
        for name in os.listdir(root):
            d = os.path.join(root, name)
            if os.path.isdir(d) and os.path.isdir(os.path.join(d, "FileStorage")):
                accounts.append(os.path.join(d, "FileStorage"))
    if not accounts and os.path.isdir(os.path.join(root, "File")):
        accounts = [root]
    return accounts


def collect_sources(root, include_media=False, scan_all=False):
    files = []
    targets = []
    for fs in discover_accounts(root):
        file_dir = os.path.join(fs, "File")
        if os.path.isdir(file_dir):
            targets.append(file_dir)
        if scan_all:
            for sub in ("Image", "Video", "Voice", "Attachment", "CustomEmotion", "Fav"):
                sd = os.path.join(fs, sub)
                if os.path.isdir(sd):
                    targets.append(sd)
    seen = set()
    for t in targets:
        for dirpath, _, fnames in os.walk(t):
            for fn in fnames:
                p = os.path.join(dirpath, fn)
                # 默认跳过微信的加密媒体文件（.dat），避免无意义归类
                if not include_media and os.path.splitext(fn)[1].lower() == ".dat":
                    continue
                if p in seen:
                    continue
                seen.add(p)
                files.append(p)
    return files


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
        description="微信文件自动归类（零依赖，默认只读 dry-run）")
    ap.add_argument("--source", help="微信 WeChat Files 目录或 FileStorage 目录；默认自动探测")
    ap.add_argument("--dest", help="归类输出目录；默认在 source 同级建 WeChatFiles_Organized")
    ap.add_argument("--scheme", choices=["type", "month", "type-month"], default="type",
                    help="归类方式（默认 type：按类型）")
    ap.add_argument("--apply", action="store_true",
                    help="真正复制归类（默认仅 dry-run 报告，不改动任何文件）")
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

    root = args.source or find_wechat_files_dir()
    if not root or not os.path.isdir(root):
        msg = {"ok": False, "error": "找不到微信文件目录",
               "hint": "请用 --source 指定 WeChat Files 路径，或设置 WECHAT_FILES_DIR 环境变量"}
        log(json.dumps(msg, ensure_ascii=False) if args.json else
            "[FAIL] 找不到微信文件目录。请用 --source 指定，或设置 WECHAT_FILES_DIR。")
        return 2

    files = collect_sources(root, include_media=args.include_media, scan_all=args.scan_all)
    if not files:
        msg = {"ok": True, "files": 0, "note": "未发现可归类的文件"}
        log(json.dumps(msg, ensure_ascii=False) if args.json else "[SKIP] 未发现可归类的文件。")
        return 0

    records = []
    for p in files:
        try:
            st = os.stat(p)
            records.append({
                "path": p, "cat": cat_of(p), "month": month_of(p),
                "size": st.st_size, "hash": sha256_of(p), "mtime": st.st_mtime,
            })
        except OSError:
            continue

    total = len(records)
    total_size = sum(r["size"] for r in records)

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

    copied = skipped_dup = 0
    if args.apply:
        dest = args.dest or os.path.join(
            os.path.dirname(os.path.abspath(root)), "WeChatFiles_Organized")
        os.makedirs(dest, exist_ok=True)
        used = set()
        seen_hash = set()
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
            except OSError as e:
                log("[WARN] 复制失败 %s: %s" % (r["path"], e))

    if args.json:
        out = {
            "ok": True, "applied": bool(args.apply), "scheme": args.scheme,
            "source": root, "total_files": total, "total_size": total_size,
            "by_category": {k: {"count": v[0], "size": v[1]} for k, v in by_cat.items()},
            "duplicates": {"groups": len(dupes), "extra_files": dup_count,
                           "recoverable_bytes": dup_recover},
            "old_files": len(old),
            "top_files": [{"path": r["path"], "size": r["size"], "cat": r["cat"]} for r in top],
        }
        if args.apply:
            out["result"] = {"dest": args.dest or os.path.join(
                os.path.dirname(os.path.abspath(root)), "WeChatFiles_Organized"),
                "copied": copied, "skipped_duplicates": skipped_dup}
        log(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    log("=" * 50)
    log("微信文件归类报告  (%s)" % ("APPLY 已执行" if args.apply else "DRY-RUN 只读"))
    log("源目录: %s" % root)
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
            log("  %s  %s" % (wpad(human(r["size"]), 10), r["path"]))
    log("=" * 50)

    if args.apply:
        log("[OK] 已归类到: %s" % (args.dest or os.path.join(
            os.path.dirname(os.path.abspath(root)), "WeChatFiles_Organized")))
        extra = "，去重跳过 %d 个" % skipped_dup if args.dedupe else ""
        log("      复制 %d 个文件%s" % (copied, extra))
    else:
        log("[DRY-RUN] 未做任何改动。加 --apply 才真正复制归类。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
