---
aliases:
  - OpenScience 文档与参考索引
tags:
  - openscience
  - docs
  - index
  - obsidian-note
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
---
# OpenScience 文档与参考索引

> [!abstract]
> `scholar-agent` 仓库当前的核心产品是 **OpenScience**：CLI、后端 API、WebUI，以及围绕 environment / terminal / task / workspace browser 的运行时能力。`docs/` 里保留的大量调研笔记、历史框架稿和参考仓库索引，主要用于产品设计输入与追溯，不再是仓库默认主线。

## 当前产品入口

- **[OpenScience Docs](https://kozmosa.github.io/scholar-agent/)**（产品文档站点，Astro + Starlight，源码在 `docs-site/`）
- 设计规范：`docs/superpowers/specs/`（最新的架构与功能设计）
- 历史文档：`docs/archive/`（V1 框架 RFC、外部项目调研、跨项目综述）

## 适合什么场景

- 如果你的目标是"直接启动或联调 OpenScience"，访问 [OpenScience Docs](https://kozmosa.github.io/scholar-agent/)。
- 如果你的目标是"理解当前产品设计与架构取舍"，读 `docs/superpowers/specs/` 下的最新规范。
- 如果你的目标是"回看历史框架、外部项目比较或早期想法"，进入 `docs/archive/`。

## 默认阅读顺序

1. [OpenScience Docs](https://kozmosa.github.io/scholar-agent/)
2. `docs/superpowers/specs/`（最新设计规范）
3. `docs/archive/`（历史参考）

## 参考材料入口

- 历史框架与 RFC：`docs/archive/framework/`
- 外部项目调研：`docs/archive/projects/`
- 综述与矩阵：`docs/archive/summary/`

## 边界

- `docs/` 与 `ref-repos/` 主要提供历史参考，不直接定义 OpenScience 当前 product contract。
- `docs/LLM-Working/worklog/` 承载开发工作日志，不是产品入口。
- 若历史设计与当前实现冲突，以当前 OpenScience 代码表面和最新 `superpowers/specs/` 规范为准。
