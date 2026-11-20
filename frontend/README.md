# 问赛 D 部分源码（当前版本单独提取）

本包只提取当前版本的 D：桌面界面与编辑交互代码，不包含 A/B/C 后端，也不包含新增 Python 智能体运行时。此次只是拆分交付，未继续改功能；不表示当前设计已满足你最终想要的产品形态。

## 先看界面

Edge 或 Chrome 打开「智能体界面演示.html」，无需安装。该页是固定样例/固定执行记录，不执行真实工具或模型，刷新后重置。

## 开发

需要 Node.js 22 LTS：

```powershell
npm ci
npm run dev
```

浏览器访问 http://127.0.0.1:5173 。默认调用真实本地 API（8765端口）；此包不提供该服务，所以单独启动 real 模式会提示连接失败。

只做前端演示可在本目录新建 .env.local：

```dotenv
VITE_DATA_MODE=mock
VITE_AGENT_PREVIEW=1
```

然后重启开发服务。Mock 仅固定数据，不能据此证明智能体自主决策。切回真实服务前删除这两个配置或改为 real。

测试：npm test。构建：npm run build:portable。dist 已包含真实接口版生产文件，不能直接双击它使用后端。

## 主要源码

- src/App.tsx：工作台、项目/材料、预览、建议处理、任务/版本页。
- src/AgentConsole.tsx：当前版本的目标输入、公开执行记录、补充要求和停止入口。
- src/ScopeApproval.tsx：文字范围、任务目标、模型/历史摘要确认。
- src/services/http.ts：HTTP/WebSocket 适配。
- src/services/mock.ts：明确标注的内存示例。
- src/VersionActions.tsx、src/FormatReport.tsx：版本上传/下载和本地规则检查入口。
- src/platform.ts：浏览器/Tauri 文件选择保存适配。
- src/styles.css、src/integration.css：样式。
- src-tauri：旧桌面壳开发骨架，不含已打包 sidecar 或可用 Windows 安装包。
- tests：前端测试源码。

## 联调依赖必须说明

当前 HTTP 层使用 /api/v1/desktop，是此前整合时新增的适配接口，不是原始 A/B/C 压缩包直接提供的全部接口。目标驱动评审还依赖此前新增的 agent_runtime.py（本包不含）。

因此，仅把本包交给原始 A/B/C 工程并不会自动联通；对接人员需要提供 docs/接口对接.md 中的协议，或修改 src/services/http.ts 适配团队最终协议。docs/智能体设计.md 是整合设计参考，不代表后端代码包含在 D 内。

docs/验收记录.md 是此前整合工程验证背景，其中后端测试和浏览器端到端验证不属于本源码包独立可运行的测试。此包可独立运行的是前端测试与固定界面演示。

D 提供人机交互，不独自实现模型自主决策、知识检索或评审工具。最终智能体运行逻辑属于后端。当前不提供自动 Office 改稿、原版 PDF/PPT 渲染、OCR 或 EXE 安装包。
