# Domain Docs

本仓库采用 single-context 领域文档布局。

## 开始探索代码前

按需读取：

- 根目录 `CONTEXT.md`
- `docs/adr/` 中与当前任务相关的 ADR

文件不存在时直接继续，不需要主动创建或报告缺失。
`/domain-modeling`、`/grill-with-docs` 等 skills 会在实际需要时创建它们。

## 文件结构

```text
/
├── CONTEXT.md
├── docs/
│   └── adr/
├── backend/
└── frontend/
```

## 领域语言

Issue、重构方案、测试名称和实现代码应使用 `CONTEXT.md` 定义的领域术语，避免引入含义重复的同义词。

如果所需概念未在领域词汇表中定义，应判断它是错误用词还是需要通过 `/domain-modeling` 补充的新概念。

## ADR 冲突

如果方案与现有 ADR 冲突，必须明确指出冲突，不得静默覆盖已有架构决策。
