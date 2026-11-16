# 问赛任务 B 和 C 交付包

本目录是已合入任务 B 和 C 的完整 WenSai-Backend 仓库，基于 release 分支的 c446cbc 提交。本地分支为 task-bc。

| 任务 | 内容 | 接入与验收 |
| --- | --- | --- |
| B 文件解析和评审规则 | app/material_review、三个 v1 profile、知识库、样例和测试 | [任务 B 接入与验收](TASK_B_README.md) |
| C Agent 和智能评审 | app/review_agent、Mock 和 DeepSeek 客户端、三个评审 Skill、样例和测试 | [任务 C 接入与验收](TASK_C_README.md) · [DeepSeek 实测和样例比对](task_c_samples/验收比对记录.md) |

从仓库根目录使用 Python 3.12 安装原后端、B 和 C 的依赖，并运行联合验收。

    python -m pip install -r requirements.txt -r requirements-task-c.txt
    python -m app.material_review validate-profiles
    python -m pytest task_b_tests task_c_tests -q

上述联合测试可离线运行。真实 DeepSeek 复测步骤见任务 C 接入说明。

启动原 FastAPI 服务所需的 PostgreSQL、Redis 和其他配置见 [仓库 README](README.md)。任务 C 的生产落库通过任务 A 提供的适配器接入。
