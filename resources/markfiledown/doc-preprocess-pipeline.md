# Step 0 Document Preprocess — Pipeline

> **定位**: Step 0 的执行层说明，负责把原始文档转成干净的 Markdown  
> **推荐触发**: `@speckit-kit/skills/mark-file-down/SKILL.md`

---

## 适用场景

当用户提供的是原始 PDF / DOCX / PPTX / XLSX，而不是已经处理好的 Markdown 时，先执行本流程，再进入 Step 1。

## 推荐提示词

```markdown
功能名称：<功能名称>
原始文档：@文档1 @文档2 ...
输出目录：specs/NNN-feature-name
请按 @speckit-kit/skills/mark-file-down/SKILL.md 的标准处理原始文档，
确保每份文档都产出一份干净的 final.md。
```

## 执行顺序

1. 用 mark-file-down skill 处理每份原始文档。
2. 验收：每份文档的输出目录中有 `final.md`，且内容干净（无 decision header、无引擎对比）。
3. 将 `final.md` 交给 Step 1 使用。

## 说明

- mark-file-down 负责原始文档转换；本文件仅说明如何调用和验收。
- 转换完成的判定标准以 `SKILL.md` 的 Completion Standard 为准。
