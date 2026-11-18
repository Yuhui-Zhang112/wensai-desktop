# 问赛 · 本地后端接口与联调手册

本手册面向文档解析、Agent、前端和测试同学。服务在本机运行，默认地址为 `http://127.0.0.1:8000`。先按项目根目录 README 的步骤启动服务。浏览器访问 `/docs` 可逐个试调 HTTP 接口，`/openapi.json` 提供机器可读的 HTTP 定义。Swagger UI 首次打开可能需要联网加载界面资源，安装依赖后也可用下方命令离线联调。WebSocket 的消息与重连方式见下文。

## 第一次跑通评审

在已启动的服务上，执行 `python scripts/demo.py` 即可使用随包样稿完成一次导入、评审和导出核对。需要查看每个请求时，使用下面的 Bash、Git Bash 或 WSL 命令。示例默认读取源码内的虚构竞赛方案，也可把 `FILE` 改为自己的测试文档路径。命令用 Python 读取接口返回的 ID，便于直接执行。请在源码根目录执行。每次演示都会创建独立项目并保留原始上传文件。

```bash
BASE=http://127.0.0.1:8000/api/v1
FILE="examples/campus-plan.docx"
curl -sS --fail http://127.0.0.1:8000/health

PROJECT_ID=$(curl -sS --fail -X POST "$BASE/projects" \
  -H 'Content-Type: application/json' -d '{"name":"校赛联调样例"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

IMPORT=$(curl -sS --fail -X POST "$BASE/projects/$PROJECT_ID/materials" \
  -F "file=@$FILE")
MATERIAL_ID=$(printf '%s' "$IMPORT" | python -c 'import json,sys; print(json.load(sys.stdin)["material_id"])')
VERSION_ID=$(printf '%s' "$IMPORT" | python -c 'import json,sys; print(json.load(sys.stdin)["version_id"])')

TASK_ID=$(curl -sS --fail -X POST "$BASE/tasks" \
  -H 'Content-Type: application/json' -d "{\"version_id\":\"$VERSION_ID\"}" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -sS --fail "$BASE/tasks/$TASK_ID"
curl -sS --fail "$BASE/tasks/$TASK_ID/events?after=0"
```

状态变为 `completed` 后读取结果，随后可把送评版本导出到自己指定的本地路径。

```bash
curl -sS --fail "$BASE/tasks/$TASK_ID/result"
curl -sS --fail "$BASE/versions/$VERSION_ID/export" -o "原始送评版.docx"
```

## 接口索引

表中的资源路径均以 `/api/v1` 开头，唯有健康检查直接访问 `GET /health`。客户端应保存服务器返回的资源 ID，通过 ID 关联项目、材料、版本和任务。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /health（根路径） | 检查服务是否已启动 |
| POST | /projects | 创建项目 |
| GET | /projects | 查询项目列表 |
| GET | /projects/{project_id} | 查询单个项目 |
| POST | /projects/{project_id}/materials | 上传材料并创建首个版本 |
| GET | /projects/{project_id}/materials | 列出项目材料 |
| GET | /materials/{material_id}/versions | 查询版本历史 |
| POST | /materials/{material_id}/versions | 接受修改，上传新版本 |
| GET | /versions/{version_id}/export | 下载指定版本文件 |
| POST | /tasks | 将某个材料版本送评 |
| GET | /tasks/{task_id} | 查询任务状态、尝试次数与错误信息 |
| POST | /tasks/{task_id}/cancel | 请求取消正在执行的任务 |
| POST | /tasks/{task_id}/retry | 重新排队失败或已取消的任务 |
| GET | /tasks/{task_id}/events | 按序号分页读取事件 |
| WS | /tasks/{task_id}/events/ws | 接收已持久化的历史与后续事件 |
| GET | /tasks/{task_id}/result | 读取一次成功评审的维度评分、问题和建议 |

## 材料和版本

创建项目使用 JSON。项目名称去除首尾空白后须为 1–160 字符，说明最多 2,000 字符。项目材料列表返回材料对象数组，每项含 `id, project_id, name, created_at, updated_at`。版本历史按版本号升序返回。文件导入和版本保存使用 multipart/form-data，请求参数 `file` 是一个文件对象。在浏览器中使用 `FormData` 时，让浏览器生成带 boundary 的 Content-Type。导出响应是二进制附件，文件名由 Content-Disposition 提供。

首次上传后，客户端保存返回的 `material_id` 和 `version_id`。接受一次修改时，上传修改后的完整文件，并随请求给出作为修改起点的 `source_version_id`。修改稿应与原材料格式一致。用第一次修改返回的版本 ID 再次保存，即可形成三版历史。

```bash
curl -sS --fail -X POST "$BASE/materials/$MATERIAL_ID/versions" \
  -F "source_version_id=$VERSION_ID" -F "file=@/path/to/修改稿.docx"
curl -sS --fail "$BASE/materials/$MATERIAL_ID/versions"
```

任务绑定具体版本。创建后上传新稿，历史任务仍指向创建时的输入版本。比对原始稿和修改稿时，分别使用对应版本的导出接口。

## 任务状态和事件

```text
pending → queued → running → completed
                     ├────→ failed ─────────→ queued
                     └────→ cancelling → cancelled → queued
```

队列和事件使用 SQLite 持久化。普通 HTTP 请求只需提交任务或读取数据。Worker 在后台执行评审，前端通过状态查询、事件接口或 WebSocket 跟踪进度。取消是协作式操作，收到 `cancelling` 后继续等待终态。若任务已结束，先读取当前状态，再决定后续动作。

事件序号 `seq` 属于单个任务。把最后已处理的序号随任务 ID 保存，断线后从该序号继续，避免重复显示旧事件。

```javascript
// 在 Vite 页面中调用。将返回的清理函数用于组件卸载。
function watchTask(taskId, onEvent) {
  const key = "wensai:last-seq:" + taskId;
  let after = Number(sessionStorage.getItem(key) || 0);
  let socket, timer, closed = false;
  function connect() {
    const path = "/api/v1/tasks/" + encodeURIComponent(taskId) + "/events/ws";
    socket = new WebSocket("ws://127.0.0.1:8000" + path + "?after=" + after);
    socket.onmessage = ({data}) => {
      const event = JSON.parse(data);
      if (event.seq <= after) return;
      onEvent(event);
      after = event.seq;
      sessionStorage.setItem(key, String(after));
    };
    socket.onclose = (e) => {
      if (!closed && ![1008, 4404].includes(e.code)) timer = setTimeout(connect, 1500);
    };
  }
  connect();
  return () => { closed = true; clearTimeout(timer); socket.close(); };
}
```

仅需 HTTP 时调用 `GET /tasks/{id}/events?after=<上次序号>&limit=100`。响应形如 `{"items":[...],"next_after":3}`，使用 `next_after` 获取下一页。每页可取 1–500 条。序号从 1 开始，`after=0` 包含第一条事件。重试沿用 task_id，事件序号也继续递增。

## 请求与响应字段

| 操作 | 提交字段 | 响应要点 |
| --- | --- | --- |
| 创建项目 | JSON 必填 `name`，可选 `description` | 201。返回 `id, name, description, created_at, updated_at` |
| 查询项目 | 路径填服务器生成的 ID | 列表接口返回数组，详情接口返回单个项目对象 |
| 导入材料 | multipart 字段 `file` | 201。响应中含 `project_id, material_id, version_id, version_no, source_version_id, file_id, original_name, mime_type, size_bytes, sha256, created_at, updated_at` |
| 查询版本 | 路径填 `material_id` | 返回版本对象数组。第 1 版的来源为 null |
| 保存修改 | multipart 字段 `file` 和 `source_version_id` | 201。新版本号递增。`source_version_id` 指向前一版。多人同时保存时，先成功的一份成为最新版本 |
| 导出 | 路径填 `version_id` | 200。二进制附件。可将下载字节的 SHA-256 与版本元数据对比 |
| 创建任务 | JSON 必填 `version_id`，可选 `profile_id`，默认为 `default` | 201。保留 `id` 用于查询、订阅和重试 |
| 查询 / 取消 / 重试 | 查询用 GET，操作用无请求体的 POST | 返回 `id, version_id, profile_id, status, attempt, error_code, error_message, created_at, updated_at` |
| 读取事件 | `after` 为已处理的最大序号，可选 `limit` | 单个事件含 `id, task_id, seq, status, message, created_at, updated_at`，HTTP 与 WebSocket 使用相同的事件字段 |
| 读取报告 | 路径填 `task_id` | 包含 `id, task_id, version_id, profile_id, overall_score, summary, dimensions, findings, created_at, updated_at` |

`dimensions[]` 中每项含 `name` 与数值 `score`。每个 `findings[]` 元素含 `id, category, severity, location, description, suggestions`。问题下的每条 `suggestions[]` 含 `id, content`。时间字段是带 UTC 时区的 ISO 8601 字符串，前端可在展示时转换成本地时间。

以默认 Mock 为例，报告总分为 75，维度数组包含「论证完整性（模拟）」70 分和「表达清晰度（模拟）」80 分。一条 medium 级问题附带一条建议。可用这组固定值检查雷达图、问题定位和建议卡片的绑定。

## 文件存放与数据库迁移

- 加密 PDF 请先导出为未加密版本。单文件上限为 104,857,600 字节（100 MiB）。支持 `.docx`、`.pptx` 和 `.pdf`。Office 旧格式 `.doc`、`.ppt` 请先另存为相应 OOXML 格式再上传。扩展名、文件内容和接收字节数都会校验，Office 文件需通过 ZIP 签名、内容清单、主部件关系和主 XML 格式检查。每份包元数据解压上限 4 MiB，主 XML 解压上限 256 MiB。PDF 需有可读的文档目录及页面树。
- 每个项目有独立的 `raw/`、`working/`、`output/`。首版入原始区，修改稿创建新版本。导出时将指定版本复制到 output，核对 SHA-256，然后以原文件名返回。响应结束后释放这份临时副本。API 只接收上传文件和资源 ID。存储层在当前项目范围内验证托管路径，再执行相应文件操作。
- SQLite 保存文件相对路径、大小、识别类型和 SHA-256。材料与文件通过版本关联。任务经 `review_runs → review_findings → suggestions` 保存结果层次。普通请求使用独立的数据库连接，启用外键和 WAL。
- 新部署或升级时运行 `python -m app.db`。迁移按 `migrations/` 中的数字版本顺序执行，SQLite 的 `user_version` 记录进度。新增数据结构应提交下一份迁移文件并通过初始化命令升级。默认库位置为 `data/wensai.sqlite3`，默认文件根目录为 `data/projects/`，均位于源码根目录下。

## 服务重启与任务恢复

| 服务中断时记录的状态 | 重启后行为 | 前端操作 |
| --- | --- | --- |
| pending | 恢复到 queued | 接续读取状态和事件 |
| queued | 等待 Worker 领取 | 保留原任务 ID |
| running | 标为 failed，记录 WORKER_INTERRUPTED | 检查原因后调用 retry |
| cancelling | 转为 cancelled 并记录事件 | 需要重做时调用 retry |
| completed、failed、cancelled | 保留原终态 | 可读取历史、已完成的报告或显式重试 |

创建时记录 pending 和 queued 两条事件。响应快照中的 attempt=1，每次重试入队加一。无效状态下的取消或重试返回 409。短时前端断网只会中断订阅。Worker 仍可执行本地 Mock，前端重连后按 seq 补读。服务进程中断时由恢复逻辑记录结果。启动和联调均使用单个服务进程，避免多个执行器竞争同一本地工作区。

## B、C、D、E 的对接位置

- **B（解析与规则）** 实现 `app/agent.py` 的 `DocumentParser` 协议，提供非空的 `parser_key` 并实现 `parse(request, checkpoint)`，返回 JSON 对象，键须为字符串，数值须为有限数，允许空对象。B 决定页码、段落、表格和规则字段。Worker 将解析结果、解析时间和解析器标识保存在材料版本上。相同版本再次送评且标识相同时，会复用结果。格式或规则变化后更新标识，例如从 `team-b:v1` 改为 `team-b:v2`，下次送评时重新解析。版本列表仅返回文件与版本元数据。
- **C（Agent）** 实现 `ReviewAgent.review(request, checkpoint)`，由服务装配代码通过 `app.main.create_app(parser=解析器实例, agent=评审实例)` 注入。C 从 `request.parsed_content` 读取 B 的结果，使用默认配置单独联调 Mock 时该字段为空。适配器返回 `ReviewOutput`，A 负责把报告、问题、建议和任务完成状态一起提交。
  - 输入 `ReviewRequest` 还包含任务、尝试次数、项目、版本、受管文件路径、原始文件名、类型、SHA-256、配置 ID 和配置字典。
  - 评分取 0–100，问题严重度 `severity` 取 `low`、`medium` 或 `high`。适配器以字符串数组传入每个问题的建议，持久化后由 A 分配建议 ID。
  - B 和 C 都应在耗时步骤间执行 `checkpoint()` 以响应取消或关闭，外部服务调用需设置超时。
- **D（前端）** 用版本号与 ID 展示历史、导出和创建评审。雷达图采用 `dimensions`，问题面板采用 `findings`，建议卡片采用每个问题下的 `suggestions`。生产模式由 `python -m app` 固定监听 127.0.0.1 并仅接收同源网页请求。默认开发来源为 `http://localhost:5173` 与 `http://127.0.0.1:5173`。
- **E（测试）** 从 `tests/` 下的自动验收开始，重点检查同一任务的状态与事件是否一致、跨重启是否能继续补读、同一来源同时保存时是否只接受一个最新版本。Mock 评分仅用于验证接口与持久化。

## 错误处理

HTTP 错误使用 JSON 对象。按 `error.code` 决定界面行为，向用户显示 `error.message`。有字段校验信息时还会附带 `error.details`。例如，在 Worker 完成前读取报告将得到 HTTP 409 与以下响应。

```json
{"error":{"code":"RESULT_NOT_READY","message":"任务完成后可读取评审结果。"}}
```

| HTTP | 常见 code | 处理方式 |
| --- | --- | --- |
| 400 | INVALID_FILENAME、UNSAFE_PATH | 提交不带目录的原始文件名，使用 API 返回的资源 ID |
| 403 | LOCAL_ACCESS_DENIED | 使用本机服务地址和已允许的前端来源 |
| 404 | PROJECT_NOT_FOUND、MATERIAL_NOT_FOUND、TASK_NOT_FOUND、VERSION_NOT_FOUND、PROFILE_NOT_FOUND | 检查 ID 及使用的服务实例，默认评审配置可省略 |
| 409 | VERSION_CONFLICT | 重新获取对应材料的版本列表，基于最新版本合并修改后再保存 |
| 409 | INVALID_TASK_STATE、RESULT_NOT_READY | 重新读取当前状态，满足状态条件后再操作 |
| 409 | FILE_MISSING、FILE_CHANGED | 检查本地存储是否与数据库对应，核对版本的 SHA-256 |
| 413 | FILE_TOO_LARGE、REQUEST_TOO_LARGE | 将材料大小控制在 100 MiB 以内 |
| 415 | VERSION_TYPE_MISMATCH | 使用原材料的文件格式保存修改稿 |
| 415 | UNSUPPORTED_FILE_TYPE、INVALID_FILE_CONTENT、ENCRYPTED_DOCUMENT | 按支持格式重新导出，确认可正常打开后再上传 |
| 422 | VALIDATION_ERROR | 查看 details 数组中每项的 field 和 message，修正字段再提交 |
| 503 | DATABASE_BUSY | 稍后重新查询状态，确认操作结果后再提交 |

PARSER_FAILED 表示解析器运行失败或未返回合规 JSON 对象。MATERIAL_UNAVAILABLE 表示 Worker 无法读取送评材料，AGENT_FAILED 表示适配器失败或返回无效结果，WORKER_INTERRUPTED 表示服务中断。任务执行错误单独保存在任务对象的 `error_code` 和 `error_message`。HTTP 查询返回 200 说明状态已成功读取，评审是否成功由 `status` 决定。进入下一次尝试时，当前错误字段清空，历史仍见事件接口。
