# WeChat 文件自动归类 (wechat-file-organizer)

扫描微信接收的文件目录，按 **类型 / 月份** 归类、**去重**、生成占用报告。
**零依赖、默认只读（dry-run）、绝不改动你的源文件。**

> 微信把所有人发来的文件平铺在 `FileStorage/File/YYYY-MM/` 里，混作一团、还充满重复。
> 这个 skill 一键把它们整理清楚——先看报告，确认后再复制归类。

---

## 效果演示

```
==================================================
微信文件归类报告  (DRY-RUN 只读)
源目录: C:/Users/you/Documents/WeChat Files
--------------------------------------------------
文件总数    : 1287
总大小      : 3.4 GB
--------------------------------------------------
按类型:
  文档      612 个  1.8 GB
  图片      401 个  820 MB
  压缩包    144 个  640 MB
  视频       88 个  210 MB
  其他       42 个  12 MB
--------------------------------------------------
重复文件    : 53 组, 重复文件 73 个, 可节省 410 MB
老旧文件    : 210 个 (超过 365 天)
--------------------------------------------------
最大的 10 个文件:
   210 MB   .../FileStorage/File/2025-12/培训录像.mp4
   ...
==================================================
[DRY-RUN] 未做任何改动。加 --apply 才真正复制归类。
```

---

## 安装

### 方式一：一键安装脚本（推荐）

```bash
# Windows (Git Bash / WSL)
bash install.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File install.ps1

# macOS / Linux
bash install.sh
```

脚本会：
1. 把 `wechat-file-organizer/` 复制到 `~/.workbuddy/skills/`（可用 `WORKBUDDY_SKILLS_DIR` 覆盖）。
2. 若已存在旧版本，先备份到 `~/.workbuddy/skill-backups/`。
3. 运行 `organize.py --help` 自检。

### 方式二：手动

把 `wechat-file-organizer/` 整个目录复制到你的 skills 目录即可：

```bash
cp -R wechat-file-organizer ~/.workbuddy/skills/
```

> 也可用本项目式的「项目级 skill」：复制到任意项目的 `.workbuddy/skills/`。

---

## 用法

```bash
cd wechat-file-organizer/wechat-file-organizer
python scripts/organize.py                 # 看报告（默认只读，安全）
python scripts/organize.py --apply         # 按类型复制归类
python scripts/organize.py --apply --scheme type-month   # 类型+月份
python scripts/organize.py --apply --dedupe               # 去重后归类
python scripts/organize.py --json          # 机器可读输出
```

### 参数

| 参数 | 说明 |
|---|---|
| `--source DIR` | 微信 `WeChat Files` 或 `FileStorage` 目录（默认自动探测 `~/Documents/WeChat Files`） |
| `--dest DIR` | 输出目录（默认 source 同级 `WeChatFiles_Organized`） |
| `--scheme` | `type`（默认）/ `month` / `type-month` |
| `--apply` | 真正复制归类（**不加只出报告**） |
| `--dedupe` | 相同内容只留一份（配合 `--apply`） |
| `--include-media` | 连 `.dat` 媒体也处理（默认跳过） |
| `--scan-all` | 扫描 FileStorage 全部子目录 |
| `--top N` | 列出最大的前 N 个文件（默认 10，0 关闭） |
| `--old-days N` | 超过 N 天计为老旧（默认 365） |
| `--json` | 输出 JSON |

### 环境变量

| 变量 | 作用 |
|---|---|
| `WECHAT_FILES_DIR` | 覆盖微信文件目录探测 |
| `WORKBUDDY_SKILLS_DIR` | 覆盖 skill 安装目标目录（安装脚本用） |

---

## 定时任务（可选）

想每周自动出一份占用报告？在 WorkBuddy 里建一个**每 7 天**的定时任务，prompt 写：

> 运行 wechat-file-organizer skill，执行 `python scripts/organize.py --json`，
> 把输出里的文件总数、总大小、重复可节省空间、老旧文件数汇报给我。

（脚本幂等、只读，定期跑零风险。）

---

## 原理

1. 自动探测 `~/Documents/WeChat Files`，找含 `FileStorage` 的账号目录。
2. 遍历 `FileStorage/File/`，按扩展名分类（文档/图片/压缩包/视频/音频/其他）。
3. 用 sha256 对内容去重，统计重复组与可节省空间。
4. 按 `YYYY-MM` 父目录名（回退到文件修改时间）归月。

分类扩展名表与去重逻辑见 `wechat-file-organizer/scripts/organize.py`，纯标准库实现。

---

## 安全与隐私

- 完全本地运行，**不上网、不读凭据、不碰微信账号**。
- 默认只读；`--apply` 也是**复制**到新目录，源目录永不被修改或删除。
- 想腾空间：先 `--apply` 归类，人工确认输出无误后再手动清理源目录。

---

## 免责声明

本工具仅用于整理**你本人**微信客户端本地已接收的文件，不改变微信任何行为、不绕过任何限制。
请遵守微信软件许可及当地法律法规。

---

## License

[MIT](LICENSE)
