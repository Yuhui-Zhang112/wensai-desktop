# legacy/ 说明

这里的代码是项目早期的**云端版本后端**，不再是主线。

## 为什么归档

四份任务书最终确定的是**本地单机桌面形态**：Tauri 外壳 + 本地 FastAPI（127.0.0.1）+ SQLite，不引入账号体系与多租户。
`legacy/cloud-backend/` 是更早的云端实现（PostgreSQL + Redis + Celery + 工作区/额度/审批），
它提供了 B 的解析规则与 C 的 Agent 的**第一版实现**，这些模块后来被移植进 `wensai/`。

保留它的原因只有两个：

1. 历史可追溯（谁在什么时候写了什么）；
2. 需要时可以参考云端版的部署方式（`deploy/`、`docker-compose.yml`）。

## 它现在能跑吗

不能直接跑。它依赖 PostgreSQL、Redis 和一个外部 AgentSDK 服务，且根目录的 `wensai/` 与 `frontend/` 才是可运行的组合。
如果你不需要这段历史，可以直接删除本目录：

```bash
git rm -r legacy
```

删除不影响 `wensai/` 与 `frontend/` 的任何功能。
