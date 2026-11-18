# 问赛 · A 模块｜本地后端与数据管理

这是《A 本地后端和数据管理任务说明》对应的可运行工程。前端通过本地 HTTP / WebSocket 接口创建项目、导入材料、提交评审和读取报告。每次评审都绑定一个确定的材料版本，既可导出当时送评的原稿，也可追踪任务中断、取消和重试的过程。

**默认使用离线 Mock Agent**，每次返回固定的 75 分、两项维度和一条带建议的问题。评审功能接入 B 的文档解析器与 C 的真实 Agent 后，才会产生基于材料内容的实际评分。随包的校园节能方案是虚构的联调样稿。

## 五分钟启动与演示

准备 Python 3.10 或更新版本，推荐使用本次验收的 Python 3.12。解压后进入包含本 README 的 `wensai` 目录。首次安装依赖需要可用的 Python 软件源。

**Windows PowerShell**。以下命令直接使用虚拟环境中的解释器，无需更改 PowerShell 执行策略。

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m app.db
.\.venv\Scripts\python.exe -m app
```

**macOS 或 Linux**。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m app.db
.venv/bin/python -m app
```

打开 `http://127.0.0.1:8000/health`，应得到 `{"status":"ok"}`。保持服务运行，在第二个终端进入同一源码目录，运行对应的演示命令。

| 平台 | 演示命令 |
| --- | --- |
| Windows PowerShell | `.\.venv\Scripts\python.exe scripts/demo.py` |
| macOS / Linux | `.venv/bin/python scripts/demo.py` |

演示会新建项目，导入 `examples/campus-plan.docx`，提交任务并打印带序号的状态事件。看到 `completed` 后，脚本读取评分和建议，导出原版本，逐字节核对下载文件并打印 SHA-256。项目和结果保留在本地，下次启动可以继续查询。按 Ctrl+C 关闭服务。

## 联调与复验

- **D 前端**　业务前缀为 `/api/v1`。开发环境默认允许 Vite 的 `http://localhost:5173` 和 `http://127.0.0.1:5173`。中文接口手册给出了上传、保存修改、WebSocket 重连以及错误码处理示例。[接口与联调手册](docs/API.md)
- **B/C 适配器**　在 `app/agent.py` 查看 `DocumentParser`、`ReviewAgent`、`ReviewOutput`。通过 `create_app(settings, parser=..., agent=...)` 注入实现。Worker 在后台调用解析器，按材料版本与解析器标识缓存结构化 JSON，再把内容交给评审器。`tests/test_adapters.py` 包含可执行的接入示例。
- **E 验收**　在源码目录、已激活的虚拟环境中运行以下命令。也可以把 `python` 替换成上文使用的虚拟环境解释器。测试使用临时数据库、临时端口和临时文件根目录，实际传输 100 MiB 文件，需预留约 600 MiB 临时磁盘空间。

```bash
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

本次在 Linux / Python 3.12.14 上通过全部 12 项自动测试，覆盖三种文件格式、100 MiB 与多 1 字节的边界、跨项目路径拒绝、连续两次修订、并发保存冲突、后台任务、取消重试、强制重启、事件补读、解析缓存、适配器无效输出与结果持久化。运行中的服务提供 `/openapi.json` 接口定义，`/docs` 可交互调试（界面使用 CDN）。安装依赖后，演示、测试和 Markdown 手册均可离线使用。

## 配置与数据

`app/config.py` 统一读取以下环境变量。默认路径相对于源码根目录。存储建议使用本机磁盘，并让数据库路径与文件根目录始终配对使用。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `WENSAI_ENV` | `development` | `production` 会固定监听 `127.0.0.1`，仅允许同源网页访问 |
| `WENSAI_HOST` / `WENSAI_PORT` | `127.0.0.1` / `8000` | 官方启动命令的监听地址与端口 |
| `WENSAI_DB_PATH` | `data/wensai.sqlite3` | SQLite 库，启用 WAL 和外键约束 |
| `WENSAI_FILE_ROOT` | `data/projects` | 项目的原始文件、修改稿和导出临时副本 |
| `WENSAI_LOG_LEVEL` | `info` | 服务日志级别 |
| `WENSAI_CORS_ORIGINS` | 上述两个 Vite 来源 | 开发时使用，多个来源用英文逗号分隔 |
| `WENSAI_MOCK_STEP_SECONDS` | `0.15` | 调整模拟评审时长，便于演示取消和重试 |

首版接收 DOCX、PPTX 和未加密 PDF，单文件上限按 100 MiB（104,857,600 字节）实现。每个项目都有 `raw/`、`working/`、`output/`。数据库保存相对路径、原文件名、类型、大小、摘要和版本关系。导出副本在传输结束后清理，送评的原文件始终保留。

`python -m app.db` 负责初始化和迁移，也支持用 `--db` 指定数据库。启动服务时会自动补齐未执行的迁移；以后的表结构修改应新增顺序编号的 SQL 文件。迁移或搬迁前，停止服务，将数据库所在目录和项目文件目录一起备份。每套数据运行一个服务进程，由操作系统文件锁防止重复启动。

## 目录

| 路径 | 用途 |
| --- | --- |
| `app/` | FastAPI 服务、SQLite 会话、文件与版本管理、Worker 和适配器协议 |
| `migrations/` | 11 张业务表的初始化及解析结果字段迁移 |
| `docs/API.md` | 中文 HTTP / WebSocket 接口、状态机、错误码和协作说明 |
| `docs/问赛-A模块交付与验收说明.docx` | 三页 Word 交付说明，含启动步骤、团队边界和验收结果 |
| `examples/` 和 `scripts/demo.py` | 随包材料及演示客户端 |
| `tests/` | 可复跑的验收与适配器测试 |
