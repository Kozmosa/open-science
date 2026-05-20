---
aliases:
  - AINRF WebUI V1 RFC
  - WebUI-v1 实现规格
tags:
  - research-agent
  - framework-design
  - webui
  - gradio
  - rfc
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# AINRF WebUI-v1 RFC（历史文档）

> [!warning]
> 本文档保留为历史 WebUI 方案归档。它描述的是早期基于 Gradio 的 WebUI-v1 设计，不再代表当前产品方向，也不应继续被当作 next release 的前端入口文档。

> [!abstract]
> WebUI-v1 RFC 记录的是项目曾经如何设想一个建立在 API-first orchestrator 之上的 Gradio 工作台：Project List、Project Detail、Run Detail、interactive mock，以及对 P8/P9 未落地能力的占位呈现。随着项目重定位，这条路线已经退役；当前项目不再把 Gradio WebUI-v1 作为现行路径，而转向围绕 task-centric dashboard baseline 重新定义控制面。

## 当前状态说明

- Gradio WebUI-v1 是历史方案，不再是当前主线。
- 本文档里的 `Project` 组织层、Run 详情结构、mock strategy 和 W0-W5 交付假设，都应按历史材料理解。
- 新读者不应再从本文档进入项目，也不应把这里的内容误读为当前前端 requirements。
- 当前 dashboard 的真正边界应以 `LLM-Working/refactoring-plan/` 下的文档为准。

## 当前应优先阅读的替代入口

如果你的目标是理解项目现在的控制面方向，请优先阅读：

- [[framework/ai-native-research-framework]]
- [[LLM-Working/refactoring-plan/index]]
- [[LLM-Working/refactoring-plan/next-release-realignment-roadmap]]
- [[LLM-Working/refactoring-plan/dashboard-baseline-spec]]
- [[LLM-Working/refactoring-plan/architecture-baseline-plan]]

## 本文档仍然保留的价值

- 记录“项目工作台”这一想法在仓库里曾经如何被具体化。
- 保留早期 Project / Run / mock panel / gate visualization 等信息架构讨论。
- 为理解后续为何要从 WebUI-v1 退场、转向 dashboard baseline 提供历史上下文。
- 方便将当前控制面需求与旧版 WebUI 叙事进行对照。

## 阅读注意事项

- 文中关于“Gradio + API client”“Project 只是 UI 组织层”“Mode 1 / Mode 2 interactive mock”的描述，都是历史方案的内部约束。
- 它们不应继续作为当前实现计划、产品优先级或文档索引主线。
- 如果你在代码或旧工作日志中看到 `webui-v1`、`ProjectView`、`MockModeSession` 等术语，可以回到本文理解其来源，但不应据此继续扩展旧设计。

## 与其他文档的关系

- [[framework/v1-rfc]] 记录的是与该 WebUI 路线配套的早期 orchestrator RFC。
- [[framework/webui-v1-roadmap]] 记录的是这套历史 WebUI 方案当时的阶段计划。
- 当前 dashboard baseline 不再由这两份文档约束，而由 `LLM-Working/refactoring-plan/` 下的规格与架构规划约束。

## 历史主题索引

- Gradio 工作台的三页式信息架构
- 历史 `Project` 组织层与 `Run` 映射方式
- gate / event / artifact 的旧版可视化设想
- 早期 mock panel 与未实现能力占位策略

## 关联笔记

- [[framework/index]]
- [[framework/ai-native-research-framework]]
- [[framework/v1-rfc]]
- [[framework/webui-v1-roadmap]]
- [[LLM-Working/refactoring-plan/dashboard-baseline-spec]]
