# doc-pre-allinone-skill-0508

这是最终对外交付的便携 bundle。

如果你要把成果物交给别的项目、别的仓库、别的团队，应该交付的就是整个 `doc-pre-allinone-skill-0508/` 目录。

它内置了当前 `doc-pre` 的运行时，并且已经补上两件事：

1. block-level evidence / trace / relation candidates
2. 独立的 `agent-exec` readback 执行层，支持 `builtin` 和 `external-command` backend

当前 PDF 契约是 `text-first multimodal reconstruction`：

1. `source.md` 和页级文本抽取是正文主源
2. 页截图 / tile / region 只用于理解版面、流程、callout、图示和视觉关系
3. `final.md` 先保全文字，再用视觉证据修正结构和语义，而不是拿截图结果直接重写正文
4. 对结构稳定的宏观图页（例如信息架构、页面布局、显式流程图），会尝试并列输出 Mermaid 复刻；不稳定时保留视觉锚点而不硬编码图
5. 对演示页 / 流程页，页面关系可以概述，但说明文字优先引用原始抽取用词，不把界面占位文案当正文主体
6. 遇到演示页说明被整页 OCR 噪声淹没时，优先做局部分栏 / region 抽取，不默认升级为重型 agent 改写

`SKILL.md` + `skill.yaml` 是主入口，给 agent / skill 框架用；`run.ps1` 只是手工验证、CI 回归、或宿主环境暂时不能直接触发 skill 时的兜底适配器。

## 主调用方式

推荐的对外调用入口是 skill trigger `doc-markdown.pipeline`，查看 `SKILL.md`，传入 `inputFile` 和 `outputRoot`。

```markdown
/doc-markdown.pipeline
输入文件：@docs/source.pdf
输出目录：output/doc-markdown
格式：auto
Agent Review回读校验：true
Agent Exec模式：builtin
```

只有在手工验证或宿主不支持 skill 直调时，才使用脚本入口。

## 脚本兜底入口

终端验证入口：

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 -InputFile ".\docs\source.pdf" -OutputRoot ".\output\doc-markdown"
```

如果目标项目使用本地虚拟环境：

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 -InputFile ".\docs\source.docx" -OutputRoot ".\output\doc-markdown" -PythonExe ".\.venv\Scripts\python.exe"
```

也可以直接处理：

1. DOCX
2. PPTX
3. XLSX/XLS
4. CSV
5. PDF

其中 Excel 类输入现在会额外导出 CSV：

1. 单 sheet 文件会得到 `compatibility/<name>.csv` 风格的主 CSV 输出
2. 多 sheet 文件会得到多个 CSV 和一个 `compatibility/*-csv-exports.json` 索引
3. `final.md` 仍保留作 bundle 内统一阅读/追踪用途，但 spreadsheet 的主兼容产物改为 CSV

## 输出说明

运行后会得到两层产物：

1. `outputRoot/.pipeline-state.json` 和 `outputRoot/intake-validation-report.md`
2. `outputRoot/<document_id>/...` 下的正文、evidence、markdown、integrity 产物

关键验证文件：

1. `source.md`
2. `final.md`
3. `evidence/block-catalog.json`
4. `markdown/block-md-trace.md`
5. `markdown/agent-review-request.json`
6. `markdown/agent-review-response.json`
7. `markdown/agent-review-report.json`
8. `markdown-integrity-report.md`
9. `compatibility/*.csv` 或 `compatibility/*-csv-exports.json` 用于 spreadsheet 输入

说明：

1. PDF 输入会走 `text baseline -> multimodal semantic evidence -> text-first reconstruction -> selective Mermaid reconstruction -> agent review`，也就是文字主源 + 多模态校正的链路。
2. 对多截图演示页，重建时允许概述页面态和动作线索，但 `callout / 说明块` 应尽量直接引用原文抽取，而不是二次改写。
3. 当说明块与界面示例文案混杂时，优先依赖页内局部 region 抽取分离说明原文，再决定是否需要额外 readback。
4. 对非 PDF 输入，`agent-review-*` 这组 sidecar 会保留，但状态会写成 `skipped`，因为真正的多模态 readback 目前只对 PDF 路由启用。

## 对外部署

最小部署动作只有一个：把整个 `doc-pre-allinone-skill-0508/` 目录复制到目标项目根目录。

更完整的部署、调用、验收说明见 `DEPLOY.md`。

## 运行前提

1. 目标机器有 `python` 或 `py -3`，或者显式传入 `-PythonExe`
2. 首次运行会自动安装 `requirements.txt` 中的依赖
3. 当前便携承诺范围包括 PDF、DOCX、PPTX、XLSX、XLS 和通用文本/表格文件

## 当前状态

这个 bundle 已在当前仓库中用最难的 PDF 做开发验证，并补充了 DOCX、PPTX、XLSX 的便携运行校验。
