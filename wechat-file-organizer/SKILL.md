---
name: wechat-file-organizer
version: 1.0.0
description: 微信文件自动归类——扫描微信 FileStorage/File 目录，按类型/月份归类、去重、生成报告。零依赖、默认只读（dry-run）、绝不改动源文件。
type: skill
---

# 微信文件自动归类 (wechat-file-organizer)

## 何时使用

当用户表达以下意图时加载本 skill：
- 「整理微信接收的文件」「微信文件太乱了」「微信文件归类」
- 「微信里重复文件好多」「清理微信下载的文件」
- 「帮我看看微信都收了些什么文件 / 占了多少空间」

本 skill 调用随附的 `scripts/organize.py` 完成，无需安装任何第三方依赖。

## 核心特性

- **零依赖**：仅用 Python 标准库，无 `pip install`。
- **安全优先**：默认 `dry-run`（只读），**绝不改动任何源文件**；只有显式加 `--apply` 才复制。
- **可移植**：所有路径运行时推导，无写死绝对路径；支持 `WECHAT_FILES_DIR` 环境变量覆盖。
- **实用能力**：按类型/月份归类、内容去重（sha256）、最大文件排行、老旧文件统计、JSON 输出。

## 如何运行

脚本位置：`scripts/organize.py`（本 skill 目录内）。

```bash
# 1) 先看报告（默认只读，安全）
python scripts/organize.py

# 2) 按「类型 + 月份」归类并复制（不动源文件，复制到新目录）
python scripts/organize.py --apply --scheme type-month

# 3) 去重后归类（相同内容只留一份）
python scripts/organize.py --apply --dedupe

# 4) 机器可读输出（定时任务/脚本消费）
python scripts/organize.py --json

# 指定目录（不自动探测时）
python scripts/organize.py --source "/path/to/WeChat Files" --apply
```

### 参数速查

| 参数 | 说明 |
|---|---|
| `--source DIR` | 微信 `WeChat Files` 或 `FileStorage` 目录；默认自动探测 `~/Documents/WeChat Files` |
| `--dest DIR` | 归类输出目录；默认在 source 同级建 `WeChatFiles_Organized` |
| `--scheme` | `type`（默认）/ `month` / `type-month` |
| `--apply` | 真正复制归类（**不加则只出报告**） |
| `--dedupe` | 去重，相同内容只保留一份（配合 `--apply`） |
| `--include-media` | 连 Image/Video 的 `.dat` 也处理（默认跳过） |
| `--scan-all` | 扫描 FileStorage 全部子目录（图片/视频/语音等） |
| `--top N` | 列出最大的前 N 个文件（默认 10，0 关闭） |
| `--old-days N` | 超过 N 天的文件计为老旧（默认 365） |
| `--json` | 输出 JSON |

## 路径发现逻辑

1. 若设了 `WECHAT_FILES_DIR` 且存在，直接用。
2. 否则探测 `~/Documents/WeChat Files`（`os.path.expanduser`）。
3. 在其下找含 `FileStorage` 的账号目录（如 `wxid_xxx/FileStorage`），扫描其中的 `File/` 子目录。
4. 多账号会全部处理。

> 微信把接收的文件按 `File/YYYY-MM/文件名` 平铺存放，所有发送者混在一起，这正是本 skill 要解决的痛点。图片/视频在 `Image/`、`Video/` 里是加密的 `.dat`，默认跳过（可用 `--include-media` / `--scan-all` 纳入）。

## 故障处置

| 现象 | 原因 / 处理 |
|---|---|
| `[FAIL] 找不到微信文件目录` | 微信不在默认位置，用 `--source` 指定，或设 `WECHAT_FILES_DIR` |
| 报告里没有图片/视频 | 默认跳过 `.dat`；加 `--scan-all` 或 `--include-media` |
| 想真正移动（而非复制）以腾空间 | 本 skill 只做**复制**以确保安全；如需移动，先 `--apply` 归类，确认无误后手动删除源目录 |
| 源文件被误改？ | 不会发生——`--apply` 也是复制，源目录始终只读 |

## 安全与隐私

- 完全本地运行，**不上网、不读任何凭据、不访问微信账号**。
- 只读扫描 + 复制输出，任何模式下都不会删除或覆盖源文件。
- 适合在任何环境下分发使用。

## 复建依据

若 `scripts/organize.py` 丢失，本 SKILL.md 已完整描述接口与参数；但最稳妥的方式是从源仓库重新安装（见 README 的 `install.sh` / `install.ps1`）。
