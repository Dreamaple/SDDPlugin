# PDF Multimodal Reconstruction Skill — 说明

## 是什么

处理**纯图片PDF**（无内嵌文本）的多模态Markdown重建skill。通过两步工作流：
1. 管线提取 OCR baseline + 页面截图 + region 切片
2. Agent 逐页读图，产出带 ASCII 布局还原的 Markdown

## 怎么用

```markdown
/pdf-multimodal-reconstruct
输入文件：@docs/设置UE.pdf
输出目录：output1
```

## 和 markfiledown-0509 的区别

| 维度 | markfiledown-0509 | pdf-multimodal-reconstruct-0610 |
|------|-------------------|--------------------------------|
| 适用场景 | 通用PDF（有文本层/混合） | 纯图片PDF（设计稿/扫描件） |
| 输出 | final.md（文字为主） | 完整Markdown（OCR证据 + ASCII还原 + 结构说明） |
| 布局还原 | 简单 ASCII | 精细 ASCII，逐编号标注区域 |
| OCR修正 | 不产出对照表 | 文档末尾附OCR-视觉修正对照表 |
| 读图策略 | 自动 | Agent按region优先策略逐页读图 |
