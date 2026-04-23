---
aliases:
  - AINRF 文档与参考索引
tags:
  - ainrf
  - docs
  - index
  - obsidian-note
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# AINRF 文档与参考索引

> [!abstract]
> `scholar-agent` 当前的中心是 `ainrf` 前后端产品面：CLI、后端 API、WebUI，以及围绕 environment / terminal / task / workspace browser 的运行时能力。`docs/` 里保留的大量调研笔记、历史框架稿和参考仓库索引，主要用于产品设计输入与追溯，不再是仓库默认主线。

## 当前产品入口

- 使用与运行入口：[[ainrf/index]]
- 当前产品定位与边界：[[framework/ai-native-research-framework]]
- 设计/架构与历史索引：[[framework/index]]

## 适合什么场景

- 如果你的目标是“直接启动或联调 AINRF”，先读 [[ainrf/index]]。
- 如果你的目标是“理解当前产品边界、架构取舍与历史演进”，再读 [[framework/index]]。
- 如果你的目标是“回看外部项目、比较参考方案或追溯早期想法”，再进入 `projects/`、`summary/` 和历史框架文档。

## 默认阅读顺序

1. [[ainrf/index]]
2. [[framework/ai-native-research-framework]]
3. [[framework/index]]

## 参考材料入口

- 外部项目调研：[[projects/ai-research-skills]]、[[projects/argusbot]]、[[projects/claude-scholar]]、[[projects/everything-claude-code]]
- 综述与矩阵：[[summary/academic-research-agents-overview]]
- 历史框架与 RFC：从 [[framework/index]] 的“历史文档入口”进入

## 边界

- `docs/projects/`、`docs/summary/` 与 `ref-repos/` 主要提供参考输入，不直接定义 AINRF 当前 product contract。
- `docs/LLM-Working/` 主要承载计划、worklog 与实现追溯，不是默认产品入口。
- 若文档中的历史设计与当前实现冲突，以当前 `ainrf` 代码表面、产品文档和 worklog 收口记录为准。
