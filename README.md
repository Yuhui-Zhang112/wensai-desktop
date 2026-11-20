# 问赛 · 竞赛文档智评系统

[![ci](https://github.com/Yuhui-Zhang112/wensai-desktop/actions/workflows/ci.yml/badge.svg)](https://github.com/Yuhui-Zhang112/wensai-desktop/actions/workflows/ci.yml)

本地运行的竞赛材料智能评审工具。导入 DOCX / PPTX / PDF / TXT / Markdown，
用「确定性规则 + 大模型」混合评审，输出能定位到段落、页码、幻灯片的问题、原文证据和修改建议；
采纳建议后生成新版本，**原文件永不覆盖**。

面向大创、挑战杯、中国国际大学生创新大赛、数学建模、RoboMaster 等场景的
论文、计划书与答辩 PPT。

## 为什么不是"把文档直接丢给大模型"

| 做法 | 问题 |
|---|---|
| 全交给模型 | 字体、字号、行距、页边距这类硬指标会被"猜到"，同一份文档两次结果不一致，无法验收 |
| 全用规则 | 创新性、研究方法、逻辑密度这类语义维度根本写不出规则 |

所以这里做的是分层：

- **硬性格式** → 确定性规则判断，可复现、可解释
- **语义维度** → 大模型评审，但必须给出原文证据
- **证据缺失的问题直接丢弃**，不允许只返回笼统评价
- 模型输出经 Pydantic 校验，**校验失败不落库**，任务标记失败而不是存入坏数据

## 架构

```
frontend/  (React + Tauri 外壳)
     │  HTTP / WebSocket
     ▼
wensai/    (FastAPI · 127.0.0.1 · SQLite WAL)
     ├─ 文件生命周期   raw / working / output，版本只增不改
     ├─ 任务状态机     pending → queued → running → completed|failed|cancelled
     ├─ 事件通道       先落库再推送，断线按 seq 补拉
     ├─ 解析层         DOCX / PPTX / PDF / TXT / MD → 统一 block 结构
     ├─ 规则层         确定性格式检查 + 三套 versioned profile
     └─ Agent 层       Mock / DeepSeek，结构化输出 + 证据校验
```

## 目录

```
wensai/          本地后端（FastAPI + SQLite），可独立运行
  app/           路由、存储、任务、Worker、Agent 适配
  app/material_review/   文档解析、格式规则、评审 profile、知识库
  app/review_agent/      评审 Agent、Provider、授权范围、证据校验
  migrations/    SQLite 迁移（001 → 004）
  tests/         桌面整合、目标 Agent、适配器测试
  task_b_tests/ task_c_tests/   解析与 Agent 的验收用例与样例
frontend/        桌面端（React 19 + Vite + Tauri 2），含 src-tauri
legacy/          早期云端版本后端，仅作历史保留，不再维护
```

## 快速开始

需要 Python 3.12、Node.js 22。

```bash
# 1. 后端
cd wensai
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m app.db          # 初始化 SQLite
python serve.py           # 8765 端口

# 2. 前端
cd ../frontend
npm ci
npm run build             # 产出 dist，serve.py 会自动挂载
npm run dev               # 或开发模式：http://127.0.0.1:5173
```

打开 `http://127.0.0.1:8765/health` 应返回 `{"status":"ok"}`。
Windows 用户可以直接双击根目录的 `安装环境.cmd` → `启动问赛.cmd`。

默认使用**离线 Mock Agent**，不联网也能跑通完整链路；接入真实模型需要在本机凭据管理器保存 DeepSeek Key：

```bash
cd wensai && python -m app.review_agent configure-key
```

## 测试

```bash
cd wensai
pip install -r requirements-test.txt
python -m pytest tests/test_desktop.py tests/test_goal_agent.py \
  tests/test_adapters.py task_b_tests task_c_tests -q
```

覆盖：三种文件格式解析、100 MiB 上限与多 1 字节边界、跨项目路径拒绝、
连续两次修订、并发保存冲突、任务取消与重试、进程强制重启后的恢复、
事件补读、解析结果缓存、适配器无效输出、评审结果持久化。

注意：测试会真实传输 100 MiB 文件，需要约 600 MB 临时磁盘。

## 打包与发布

Windows 安装包由 GitHub Actions 产出，不需要本地 Windows 机器：

- 手动构建：Actions → `windows-build` → Run workflow
- 打 tag 自动发布：`git tag v0.1.0 && git push origin v0.1.0`，安装包会挂到 Release 页面

安装包 = PyInstaller 打包的后端 sidecar（`review-api.exe`）+ Tauri 外壳 + 前端静态资源，约 50 MB。
首次启动较慢（onefile 需要解压），运行数据存放在 `%LOCALAPPDATA%\WenSai`。
未做代码签名，Windows 会提示「未知发布者」，需要用户手动选择「仍要运行」。

## 现状

| 模块 | 状态 |
|---|---|
| 本地后端（文件生命周期、任务状态机、事件通道） | 已完成 |
| 文档解析（DOCX / PPTX / PDF / TXT / MD） | 已完成 |
| 确定性格式规则 + 三套评审 profile | 已完成 |
| 评审 Agent（Mock / DeepSeek，结构化输出与证据校验） | 已完成 |
| 桌面端（项目、材料、预览、建议处理、版本对比） | 已完成 |
| Windows 安装包与自动更新 | 未完成 |
| 评审报告导出（PDF / Word） | 未完成 |

## 第三方组件与许可

见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。其中 **PyMuPDF 采用 AGPL-3.0**，
对外分发二进制前需要替换或购买商业授权，详见该文件。

## 分工

| 角色 | 范围 |
|---|---|
| A | 本地后端、SQLite、文件生命周期、任务调度 |
| B | 文档解析、格式规则、评审 profile、知识库 |
| C | Agent 编排、模型接入、结构化输出与校验 |
| D | Tauri 桌面外壳、React 界面、预览与差异对比 |
| E | 契约、集成、验收与发布 |
