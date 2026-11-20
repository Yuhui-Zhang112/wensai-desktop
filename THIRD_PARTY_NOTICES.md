# 第三方组件与许可说明

本项目为课程/竞赛用途，但下面这一条会影响**对外分发**，请务必先读。

## ⚠️ PyMuPDF（AGPL-3.0）

`wensai/requirements.txt` 依赖 `PyMuPDF`，用于 PDF 文本、图片与页面布局提取。

PyMuPDF 采用 **AGPL-3.0**（另有 Artifex 商业授权）。这意味着：

- 只在本机自用、不对外分发 → 没有问题
- 把打包好的程序（安装包、exe、桌面应用）发给别人使用 → AGPL 要求你**以 AGPL 公开全部源码**
- 不想开源 → 需要向 Artifex 购买商业授权

**建议**：在正式对外发布前，把 `app/material_review/pdf.py` 换成
`pypdf` 或 `pdfplumber`（MIT / BSD 许可），并同步替换 `task_b_tests/make_samples.py`
与 `task_c_tests/samples.py` 中的样例生成逻辑。项目已依赖 `pypdf`，替换成本主要在图片与版面提取。

## 其他主要组件

| 组件 | 许可 | 用途 |
|---|---|---|
| FastAPI / Starlette / Uvicorn | MIT / BSD | HTTP 服务 |
| Pydantic | MIT | 数据校验 |
| SQLite | Public Domain | 本地数据库 |
| python-docx | MIT | DOCX 读写 |
| python-pptx | MIT | PPTX 读取 |
| pypdf | BSD-3-Clause | PDF 读取（可替代 PyMuPDF） |
| jsonschema | MIT | profile 校验 |
| React / Vite | MIT | 前端 |
| Tauri | MIT / Apache-2.0 | 桌面外壳 |
| DeepSeek API | 服务条款 | 模型调用（可选，默认 Mock） |

## 数据与隐私

- 仓库内不含真实学生论文、个人信息或未授权的竞赛资料
- `wensai/data/`、`uploads/`、`*.sqlite3` 已被 `.gitignore` 排除
- 默认只发送用户确认范围内的文本；PPT 图片分析需单独授权
