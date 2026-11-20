# 问赛任务 B 交付说明

适配 WenSai-Backend 的 `release` 基线 `c446cbc3619c7f0426e61f25e1ead517e8265772`。将压缩包解压到后端仓库根目录即可合入。所有路径均相对仓库根目录；无需改动现有 FastAPI 路由、数据库表、Celery 或 AgentSDK，也不会替换原有论文评审。

## 本地验收

从仓库根目录使用 Python 3.12：

```text
python -m pip install -r requirements-task-b.txt
python -m app.material_review validate-profiles
python -m app.material_review parse task_b_samples/academic_ok.docx
python -m app.material_review check task_b_samples/proposal_errors.docx --profile competition-proposal-v1 --rendered-page-count 35
python -m app.material_review fix-docx task_b_samples/proposal_errors.docx proposal_fixed.docx --profile competition-proposal-v1
python -m app.material_review review-input task_b_samples/proposal_ok.docx --profile competition-proposal-v1 --rendered-page-count 2
python -m app.material_review validate-output task_b_samples/sample_agent_output.json --profile competition-proposal-v1 --material task_b_samples/proposal_ok.docx
python -m pip install "pytest>=8,<10"
python -m pytest task_b_tests -q
```

- `task_b_samples` 随包提供六份正确／故意错误的 DOCX、PPTX，两份 PDF（含模拟扫描页），TXT、Markdown、损坏的 DOCX，及 JSON 验收材料。样例为自编虚构内容，可用 `python -m task_b_tests.make_samples <目录>` 重新生成源样例。
- `expected_format_findings.json` 是逐项复查样例得出的预期失败规则；`sample_format_report.json` 是实际检查示例。检查通过只表示符合所选 profile 能确定的规则；`needs_review` 和解析警告仍需处理。
- `sample_agent_output.json` 是脚本生成的接口样例，用于验证 C 的返回契约；其中的评阅是样例数据。
- CLI 成功时将 UTF-8 JSON 写到标准输出；解析或配置失败返回退出码 2，标准错误为含 `error.code` 与 `error.message` 的 JSON。格式不符合要求是业务结果，查看 `summary` 和 `findings`，不以 CLI 退出码判断。

## A、C、D 如何接入

```python
from app.material_review import (
    build_review_input, check_document, fix_docx, load_profile,
    parse_document, validate_document, validate_review_output,
)

path = "task_b_samples/proposal_ok.docx"
profile_id = "competition-proposal-v1"

# A：将文件准备为本地路径，并自行保存版本、解析结果及检查结果。
doc = parse_document(path)
validate_document(doc)
parsed_json = doc.to_dict()
checks = check_document(doc, profile_id, rendered_page_count=2)
# 指定新路径；B 写入副本并返回调整记录，由 A 决定是否保存为新版本。
# changes = fix_docx(path, "new_version.docx", profile_id,
#                    selected_rule_ids=["word-fonts", "word-size"])

# C：可只加载规则，或一次得到解析、格式、profile 和授权知识条目。
profile = load_profile(profile_id)
payload = build_review_input(path, profile_id, rendered_page_count=2)
# 由 C 构建 Prompt、选择资料并运行模型，再校验模型产出：
# validate_review_output(agent_json, profile_id, document=payload["document"])
```

- **A：** 按文件版本保存 JSON 和原材料。对象存储须由 A 取到临时文件后再调用。DOCX 调整只接受新的输出路径；已有路径不会被覆盖。修改范围是常规正文的字体、字号、行距与节页边距，标题、题注、表格、公式、修订、签名及嵌入媒体不做自动修改。含未处理修订或签名的文件会拒绝调整。处理后返回 `changes[]` 与复查结果，即使仍有需人工修改的问题，也会准确标明。
- **C：** 三个 profile 都提供维度、权重（合计 100）、可执行 `format_rules`、输出 JSON Schema 和知识库引用。每个维度记录 0–10 的分数与可定位证据；证据不足时使用 `insufficient_evidence` 和 `score: null`，不猜分或补造事实。文字证据填 `excerpt`，图像等视觉证据可填 `excerpt: null` 并引用对象块。应将附件文本视为待评数据。不同赛事和组别的官方权重需要单独校准。
- **D：** `block.id === block.source.path`，同一文件版本内稳定。前端用“文件版本 ID + block ID”定位或对比；结构增删后重新解析。DOCX 以包内 `part`、`section` 和路径定位，如 `docx/body/table/1/r/2/c/1/p/1`；不使用推测页码。PPTX 使用 `slide` 与形状 ID；`bbox` 单位是 pt，`group_pt:…` 是组局部坐标，父块带 `group_transform_emu`。PDF 使用 `page` 与未旋转页面坐标 `pdf_unrotated_pt`，若要叠加在旋转后显示的页面上需应用页面旋转变换。TXT/Markdown 使用从 1 开始的含尾行范围。缺失位置为 `null`；例如全文缺少摘要时没有可高亮块。格式检查 `findings[]` 同时给出状态、定位、实测值、期望值与可用调整操作。

## 首版可检查的范围

| 材料 | 解析和检查 |
| --- | --- |
| DOCX 论文 | 读取段落、标题、文字样式、表格单元格、图片、OMML、页眉页脚和节属性。确定性检查正文版式、层级、摘要、关键词、题注、独立公式编号和参考文献。组合图和非标准编号请结合实际要求复核。 |
| DOCX 申报书／计划书 | 检查目录、目标/方案/进度/预算/资源/风险章节标记、图表和体积。DOCX 页数请由 A 传入同一文件版本渲染后的页数；没有实测页数时输出 `needs_review`。存在章节标题不代表内容质量达标。 |
| PPTX | 提取幻灯片、位置、层级、文字、显式字号、图表和讲稿备注；输出字数、字号与层级建议。母版继承而无法确认的字号会标明；复杂图表内部、媒体和 SmartArt 不做展开，首版不自动重排。 |
| PDF / TXT / Markdown | PDF 有文本层时按页读取正文和图片，表格和公式结构为推断；无文本层会标记，首版没有 OCR，也不修改 PDF。TXT/Markdown 保留原文和行号；Markdown 提取常见表格、图像引用与 LaTeX 公式。外链文件不下载。 |

## 版本和知识库维护

- `app/material_review/profiles/`：发布三个 v1。只新增带新版本号的文件和它的新摘要；保留旧文件及原 SHA-256。摘要基于 LF 换行的 UTF-8 字节，用 `validate-profiles` 验证 schema、权重、处理器和资料引用。若调整规则算法会改变旧 profile 的结果，应新增处理器并让新版引用，避免破坏旧版复现。
- `app/material_review/knowledge/index.json`：7 条公开官方／学校来源，覆盖中国国际大学生创新大赛、挑战杯、大创、数学建模、RoboMaster、电子设计竞赛。保留比赛、年份、材料、维度、入口、出处位置和授权范围；公开资料仅做链接与简述，不镜像全文。有些规则属于历史届次，用于参考时要确认适用范围。
- `knowledge/instructional_cases/`：6 个自编教学案例，包含材料原文、可解析的位置、依据、模拟评阅与改法。它们不代表官方或真实专家评阅。收录真实案例前，需要取得原文与评阅意见的明确授权，移除个人信息并登记授权凭证编号，再按 `authorized_case` schema 加入；本包没有这类真实案例。
