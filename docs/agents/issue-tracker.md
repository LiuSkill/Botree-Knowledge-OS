# Issue tracker: GitHub

本仓库的 Issues 和 PRD 存放在 GitHub Issues 中，所有操作使用 `gh` CLI。

## 常用操作

- 创建：`gh issue create --title "..." --body "..."`
- 查看：`gh issue view <number> --comments`
- 列表：`gh issue list --state open`
- 评论：`gh issue comment <number> --body "..."`
- 添加标签：`gh issue edit <number> --add-label "..."`
- 移除标签：`gh issue edit <number> --remove-label "..."`
- 关闭：`gh issue close <number> --comment "..."`

仓库由当前目录的 Git remote 自动确定：
`https://github.com/LiuSkill/Botree-Knowledge-OS.git`

## Pull requests as a triage surface

PRs as a request surface: no.

## Skill 约定

- “publish to the issue tracker”：创建 GitHub Issue。
- “fetch the relevant ticket”：执行 `gh issue view <number> --comments`。
- `/wayfinder` 使用一个带 `wayfinder:map` 标签的 Issue 作为任务地图。
- 子任务优先使用 GitHub sub-issues；不支持时使用任务列表和 `Part of #<map>`。
- 阻塞关系优先使用 GitHub 原生 issue dependencies。
- 领取任务时使用 `gh issue edit <number> --add-assignee @me`。
