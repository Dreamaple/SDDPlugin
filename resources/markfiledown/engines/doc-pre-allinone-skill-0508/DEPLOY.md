# Deploy, Call, Verify

## Deploy

把整个 `doc-pre-allinone-skill-0508/` 目录复制到目标项目根目录。

这是唯一需要对外交付的成果物目录。

不要只复制：

1. `run.ps1`
2. `pipeline_runner.py`
3. `runtime/doc_pre/`

因为这三者单拿出去都不是完整部署单元。

建议最小目录结构：

```text
target-project/
  doc-pre-allinone-skill-0508/
  docs/
    source.pdf
    sheet.xlsx
  output/
```

运行前提：

1. 目标机器可用 `python` 或 `py -3`
2. 或者显式传入 `-PythonExe`
3. 首次运行允许安装 `requirements.txt` 中的依赖

## Call

### Agent / Skill

使用 [SKILL.md](e:/xTest/0507-pre-00/doc-pre-allinone-skill-0508/SKILL.md) 作为主入口，传入：

1. `inputFile`
2. `outputRoot`
3. `enableAgentReviewValidation`
4. `agentExecMode`

示例：

```markdown
/doc-markdown.pipeline
输入文件：@docs/source.pdf
输出目录：output/doc-markdown
格式：auto
Agent Review回读校验：true
Agent Exec模式：builtin
```

如果你的宿主支持 skill / agent 触发，这就是应该对外暴露的调用方式。

### Terminal

只有在以下场景才建议直接用脚本：

1. 空项目手工验收
2. CI 回归
3. 宿主暂时不能直接消费 `SKILL.md` / `skill.yaml`

PDF：

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 -InputFile ".\docs\source.pdf" -OutputRoot ".\output\pdf-run"
```

Excel：

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 -InputFile ".\docs\sheet.xlsx" -OutputRoot ".\output\sheet-run"
```

指定解释器：

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 -InputFile ".\docs\source.pdf" -OutputRoot ".\output\pdf-run" -PythonExe ".\.venv\Scripts\python.exe"
```

外部 agent backend：

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 `
  -InputFile ".\docs\source.pdf" `
  -OutputRoot ".\output\pdf-run" `
  -AgentExecMode external-command `
  -AgentCommand "python .\my_agent.py {request} {response}"
```

也可以通过环境变量提供命令：

1. `DOC_PRE_AGENT_COMMAND`
2. 兼容旧名 `DOC_PRE_PDF_AGENT_COMMAND`

## Verify

先看根级状态文件：

1. `output/<run>/.pipeline-state.json`
2. `output/<run>/intake-validation-report.md`

### PDF 期望

1. `route` 为 PDF 路由，例如 `complex_visual_pdf_path`
2. `review_status` 通常为 `pass` 或 `needs-repair`
3. `markdown/agent-review-request.json` 存在
4. `markdown/agent-review-response.json` 存在
5. `markdown/agent-review-report.json` 存在
6. 这表示 PDF 已经过 `multimodal preparation + visual repair + agent review` 链路

### Excel 期望

1. `route` 为 `spreadsheet_pipeline`
2. `primary_output` 指向 `compatibility/*.csv` 或 `compatibility/*-csv-exports.json`
3. `review_status` 为 `skipped`
4. `artifacts/tables/*.csv` 存在
5. `compatibility/*.csv` 或 `compatibility/*-csv-exports.json` 存在

### 通用核对点

1. `source.md` 和 `final.md` 存在
2. `evidence/block-catalog.json` 存在
3. `markdown/block-md-trace.md` 存在
4. `markdown-integrity-report.md` 存在
5. `manifest.json` 里的 `compatibility_outputs` 与根级 `.pipeline-state.json` 的 `primary_output` 一致
