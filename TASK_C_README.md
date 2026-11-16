# 问赛任务 C 接入与验收

任务 C 是本地评审 Agent，适配 WenSai-Backend 的 `release` 基线 `c446cbc` 与任务 B 的三个 v1 profile。先将任务 B 交付包装入仓库根目录，再将本包装入同一目录；C 不改旧版论文评审、路由或数据库表。A 在同一个接口下选择 Mock 或 DeepSeek。

## 先跑离线验收

使用 Python 3.12，从仓库根目录运行：

```powershell
python -m pip install -r requirements-task-c.txt
python -m pip install "pytest>=8,<10"
python -m pytest task_c_tests -q
```

`task_c_samples/` 提供 DOCX 论文、双页 PDF 计划书、带内嵌图的 PPTX、局部选择 JSON、示例输出、基线比对记录以及仅供联网验收的自编 Markdown 样例。样例无个人资料。重新生成原始测试材料：`python -m task_c_tests.samples <目录>`。展开某个 Skill 完整约定：`python -m app.review_agent skill academic-paper-v1`；另外两个可用 ID 为 `competition-proposal-v1` 和 `ppt-defense-v1`。

使用 CLI 手动完成一次 Mock 闭环：

```powershell
$material = "task_c_samples/live-check.md"
$profile = "academic-paper-v1"
$selection = "task_c_samples/live-check-selection.json"
$scope = python -m app.review_agent preview $material --profile $profile --selection $selection | ConvertFrom-Json
$scope.text | Format-List
python -m app.review_agent run $material --profile $profile --selection $selection --text-digest $scope.text_digest
```

Mock 仅在命中固定教学样例时给出预设意见；不联网、不读密钥，并使用与 DeepSeek 相同的 JSON、证据和保存校验。没有样例命中时用“证据不足”标记。CLI 的终态 JSON 交给调用者；正式应用由 A 的适配器持久化，CLI 不接数据库。

## DeepSeek 实测

2026 年 11 月 16 日已用随包的自编 Markdown 样例完成一次真实调用：`deepseek-flash` 返回 HTTP 200，两条意见都通过结构与原文证据校验，并写入本地参考适配器。另见 `task_c_samples/验收比对记录.md`。首次实测暴露了标准编号歧义，本包已明确列出各维度的可用编号，并在校验失败时定向提示重试。

实测前先在当前系统用户的密钥管理器中配置专用测试凭据。进入交互终端，执行：

```powershell
python -m app.review_agent configure-key
python -m app.review_agent key-status
```

命令输入不回显。凭据只存于 Windows Credential Manager、macOS Keychain 或 Linux Secret Service 的专用服务 `WenSai.DeepSeek`（账户 `api_key`）。不要把 Key 粘贴到聊天、Shell 参数、配置或 SQLite。Linux 桌面须先解锁密钥服务。没有凭据时退出为 `credential_missing`，不会发请求。

运行上一节三行变量及 `preview` 命令，查看 `$scope.text`。**只有明确同意把显示的自编样例选段发送至 DeepSeek 后**，才带上其摘要运行：

```powershell
python -m app.review_agent run $material --profile $profile --selection $selection --text-digest $scope.text_digest --provider deepseek --config task_c_samples/test-config.json
```

核对输出 `meta.status` 为 `completed`，`audit` 中有请求时间、状态，且评语问题引用第 3 行的原句；模型可能给出与 Mock 不同的措辞，按原文回查。正式集成须再用 A 的适配器确认终态与校验后的 JSON 同一事务写入。测试无 Key 时，只能用模拟 HTTP 验证请求结构、错误状态和保存接口；不能据此认定真实 API 验收通过。

默认模型是 `deepseek-flash`，接入 [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) 的 [JSON 模式](https://api-docs.deepseek.com/guides/json_mode/)。配置文件可设置模型、超时、任务总时限、最大输出 token、温度、重试次数及分段上限。文本请求可选 `deepseek-v4-pro`。需要图片时使用支持视觉的 [deepseek-flash](https://api-docs.deepseek.com/guides/vision/)，在 `selection.images` 中列出 PPT 内嵌 PNG/JPEG 的 block ID，从本地演示稿对照确认图片后，另传 `--image-digest $scope.image_digest`。默认 `images` 为空。每张图单独提交；不调用 Files API、不传图片外链、不上传整份文档。模型不会收到未选段的原文、文件名或本地路径。

## A / B / D 对接

A 保持身份、原文件版本、任务状态和保存控制；C 只使用 A 提供的任务快照并回写结果。B 提供解析结构、证据位置和版本化 profile；D 展示确认页面、评审问题和建议修改操作。

1. A 将 B 的 `build_review_input(...)["document"]` 与不可变原文件版本一同保存，生成内部 `TaskInput(task_id, revision_id, profile_id, document, selection)`。选择以块的 ID 与代码点范围 `[start,end)` 表达；不选择的材料不纳入输出上下文。 `inspect` 可查看可选块的本地预览。
2. D 调用 `preview_scope(task)` 展示**完整已选文字**、目标服务、可选图片本身（从同版本材料获取）、分别对应的摘要。A 只在当前任务所有者确认后写入 `Approval(text_digest, image_digest)`；不能在服务器自动确认或仅依据前端提供的 task ID。修改选择/原文版本后，应重新预览和确认。
3. A 实现 `TaskGateway`：`load` 返回可信快照；`claim` 必须原子比较任务版本和授权、把待处理的任务转为 `running`，并保存初始元数据；`audit` 记录尝试；`complete` / `fail` 原子写入对应终态。保存和取消请求在 A 侧加时限，终态保存应按任务 ID 幂等。重试整个失败任务时由 A 建新的待执行记录或按应用协议重新入队，避免重复保存。
4. `await ReviewAgent(gateway, MockProvider()).run(task_id)` 可在断网时执行；替换为 `DeepSeekProvider(AgentConfig(...))` 即切换真实客户端。需要图片时传入只读的 `image_reader`；参考适配器是 `LocalPptxImages`。返回的 `Failure` 可安全展示，不包含远程响应或正文；失败不保存部分评审。
5. D 使用 `issues[].location.source` 的页码、段落号、幻灯片或行号定位，与 `location.char_start/end` 对应 B 的文字块。 `severity` 由 C 从影响级别确定；`criterion` 和 `review_standard` 使用 B 当前 profile。 `edit_suggestion(result, issue_id, text)` 生成包含前后内容和版本的草稿；不修改原件或已保存评审。用户采纳后，由 A 保存草稿/版本并调用本地规则程序应用可支持的调整。

`review` 内层与 B 的 `output_schema` 相容；C 另加 `issues`、`meta` 与条件总分。没有直接证据的维度标成 `insufficient_evidence` 且分数为 `null`；只有所有维度有据时才计算加权总分。分段证据必须在该段的批准范围中逐字匹配；合并时去掉跨段重复问题。PPT 的证据可精确引用确认过的图片，原文引文留空，不能把模型推测当作 OCR 文字。当前首版不会推测未提供的演讲稿、未选择的幻灯片或格式属性。

评审流程只执行内置解析、检索、评审和状态保存接口。外部请求不带工具定义，不跟随重定向，日志只记任务、配置版本、模型、时间、状态、大小和错误码，不记原文、图片、密钥、请求体或未通过校验的模型输出。外部接口的服务端数据处理仍以服务商条款及使用方审批为准。
