#!/usr/bin/env bash
# 微信文件归类 skill 一键安装（含自检）
# 支持：Windows(Git Bash/msys)、macOS、Linux
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_SRC="$SCRIPT_DIR/wechat-file-organizer"

# 选 Python：优先 managed python，其次系统 python3/python
PY="$(command -v python3 || command -v python || true)"
# Git Bash/MSYS 下 $HOME 形如 /c/Users/x，直接传给原生 python.exe 会被拼成 C:\c\Users\x
if [ -n "${HOME:-}" ] && [[ "$HOME" == /* ]] && command -v cygpath >/dev/null 2>&1; then
  WIN_HOME="$(cygpath -w "$HOME" 2>/dev/null || echo "$HOME")"
else
  WIN_HOME="${HOME:-$SCRIPT_DIR}"
fi
MB_PY="$WIN_HOME/.workbuddy/binaries/python/versions/3.13.12/python.exe"
if [ -x "$MB_PY" ]; then PY="$MB_PY"; fi
if [ -z "$PY" ]; then echo "未找到 Python，请先安装 Python 3.8+"; exit 1; fi

DEST_PARENT="${WORKBUDDY_SKILLS_DIR:-$WIN_HOME/.workbuddy/skills}"
DEST="$DEST_PARENT/wechat-file-organizer"

mkdir -p "$DEST_PARENT"
if [ -d "$DEST" ]; then
  stamp="$(date +%Y%m%d%H%M%S)"
  backup="$WIN_HOME/.workbuddy/skill-backups/wechat-file-organizer.$stamp"
  mkdir -p "$(dirname "$backup")"
  mv "$DEST" "$backup"
  echo "已备份旧版本到: $backup"
fi

cp -R "$SKILL_SRC" "$DEST"
echo "已安装到: $DEST"

# 自检：能正常打印帮助即视为可用
if "$PY" -u "$DEST/scripts/organize.py" --help >/dev/null 2>&1; then
  echo "自检通过：脚本可正常运行"
else
  echo "自检失败，请检查 Python 环境"
  exit 1
fi
