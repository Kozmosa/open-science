---
aliases:
  - AI-Native Research Framework 索引
tags:
  - research-agent
  - framework-design
  - obsidian-note
  - index
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# AINRF 设计与架构索引

> [!abstract]
> 本页汇总 AINRF 当前产品设计、架构约束与历史方案追溯材料。它是 `docs/ainrf/index.md` 的补充入口，而不是默认的产品使用入口：如果你的目标是启动、联调或直接使用当前 AINRF，先回到 [[ainrf/index]]。

## cleanup-first freeze / 当前状态

> [!warning]
> 仓库当前处于 cleanup-first realignment 冻结期。现阶段优先级是先完成旧叙事、旧入口与遗留实现面的清理和对齐，再重新确认 next release 的实现边界；在 cleanup 明确结束之前，新的实现扩写、重新包装旧 orchestrator/WebUI-v1 方向，或把残留运行时代码解释为已确认产品能力，都不属于当前允许路径。

> [!success]
> Cleanup gate passed：退役的 orchestrator-era product center 已从当前代码主路径移除。后续工作应从清理后的 daemon/runtime shell 与 health-only frontend shell 出发，而不是恢复旧 task/WebUI 路径。

- 当前 status：文档入口、runtime README 与遗留实现面都在向 dashboard-first baseline 收敛。
- 当前要求：如果要判断“现在该实现什么”，必须先以 `LLM-Working/refactoring-plan/` 文档集和 cleanup 后仍保留的代码现实为准。
- 明确冻结：任何新的实现承诺、范围扩写或体系化重建，都必须等待 cleanup 完成后再进入下一轮 realignment 决策。

## 当前推荐阅读顺序

- 先读 [[ainrf/index]]，确认当前 AINRF 产品面与运行入口。
- 再读 [[framework/ai-native-research-framework]]，确认项目当前定位、长期方向、当前范围和非目标。
- 然后读 [[LLM-Working/refactoring-plan/index]]，进入本轮 requirements / expectations 重对齐文档集。
- 接着读 [[LLM-Working/refactoring-plan/project-realignment-manifesto-plan]]，理解项目为什么从旧叙事收缩为 dashboard-first。
- 然后读 [[LLM-Working/refactoring-plan/mode-baseline-spec]] 与 [[LLM-Working/refactoring-plan/dashboard-baseline-spec]]，确认 next release 真正承诺的 Mode 1 / Mode 2 baseline 与 dashboard baseline。
- 如果要落到实现边界，再读 [[LLM-Working/refactoring-plan/architecture-baseline-plan]] 以及 3 份 contract 文档。
- 如果需要追溯旧版 orchestrator / WebUI-v1 方案，再进入下方“历史文档”部分。

## 当前有效入口

- 产品使用与当前运行入口：[[ainrf/index]]
- 项目定位与边界：[[framework/ai-native-research-framework]]
- 重构规划索引：[[LLM-Working/refactoring-plan/index]]
- manifesto / 定位收缩：[[LLM-Working/refactoring-plan/project-realignment-manifesto-plan]]
- next release 范围冻结：[[LLM-Working/refactoring-plan/next-release-realignment-roadmap]]
- Mode 1 / Mode 2 baseline：[[LLM-Working/refactoring-plan/mode-baseline-spec]]
- dashboard baseline：[[LLM-Working/refactoring-plan/dashboard-baseline-spec]]
- architecture baseline：[[LLM-Working/refactoring-plan/architecture-baseline-plan]]

## 如何理解当前框架文档

- `docs/framework/` 现在主要承担两类职责：
  - 仍然有效的高层定位文档。
  - 已退役方案的历史归档与设计追溯。
- next release 的 requirements 不再直接由旧版 `v1-rfc`、`v1-roadmap`、`webui-v1-rfc` 等文档驱动。
- 凡是仍在描述“完整 orchestrator”“完整双模式自治引擎”“Gradio WebUI-v1”的文档，都应默认视为历史设计，而不是当前实现承诺。

## 历史文档入口

> [!warning]
> 以下文档保留是为了追溯设计来源、术语和历史判断，不应再被当作当前路径或 next release 规范入口。

- [[framework/v1-rfc]]
- [[framework/v1-roadmap]]
- [[framework/webui-v1-rfc]]
- [[framework/webui-v1-roadmap]]
- [[framework/v1-implementation-status]]
- [[framework/v1-dual-mode-research-engine]]
- [[framework/artifact-graph-architecture]]
- [[framework/reference-mapping]]

## 仍可作为背景材料的文档

- 容器与工作区约定：[[framework/container-workspace-protocol]]
- agent 能力与角色背景：[[framework/agent-capability-base]]、[[framework/vsa-rfc]]、[[framework/pia-rfc]]

## 使用说明

- 如果你的目标是“启动或使用当前 AINRF”，先读 [[ainrf/index]]，不要从本页开始。
- 如果你的目标是理解“项目现在应该做什么”，请不要从旧版 RFC / roadmap 开始。
- 如果你的目标是理解“为什么以前会形成那些设计”，再去读历史文档。
- 如果你的目标是推进实现切片，应以 `LLM-Working/refactoring-plan/` 下的文档和当前代码现实为准。

## 关联笔记

- [[index]]
- [[summary/academic-research-agents-overview]]
- [[projects/ai-research-skills]]
- [[projects/auto-claude-code-research-in-sleep]]
