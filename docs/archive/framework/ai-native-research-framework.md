---
aliases:
  - AI-Native Research Framework
tags:
  - research-agent
  - framework-design
  - system-note
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# AI-Native Research Framework

> [!abstract]
> `scholar-agent` 当前不再把自己定义为“跨领域、全天候、完整自治的研究引擎”，也不再把早期 orchestrator / WebUI-v1 蓝图当作现阶段主路径。现在更准确的定位是：一个单用户优先、agent-driven、evidence-grounded 的 research dashboard 项目；它关注 bounded discovery / bounded reproduction task 的启动、观察、回看与归档，而不是继续放大“未来态自动科研系统”的叙事。

## 当前定位

- 一句话定位：`scholar-agent` 是一个单用户优先的 agent-driven research dashboard 项目。
- 当前首要目标不是证明“系统可以完全替代研究者”，而是把典型、简单、定义明确的研究支持任务稳定跑起来。
- 当前最重要的产品优先级是：dashboard、stability、observability。
- 系统价值来自 task、artifacts、milestones、workspace context 和结果回看被组织成一个可理解的控制面，而不是来自宏大的自治承诺。

## 为什么要重写定位

- 旧版框架文档把项目叙述成 bounded-autonomous research engine，并把双模式 orchestrator、artifact graph、Gradio WebUI-v1 等方案作为主线入口。
- 这种写法对理解长期愿景有帮助，但会把新读者直接带入已经退役的实现方向。
- 当前项目需要优先解决的是 next release 的 requirements / expectations 收敛，而不是继续累积面向未来态的系统承诺。
- 因此，framework 主文档现在应承担“解释项目现在是什么、当前优先级是什么、什么不再是当前路径”的职责。

## 当前要强化的叙事

- 单用户优先，而不是多用户平台想象。
- task-centric operator control plane，而不是完整研究运营平台。
- evidence-grounded workflow，而不是会话驱动的模糊自动化。
- ready-for-use、robustness、observability，而不是为了愿景而继续扩大 scope。
- a simple but genuinely helpful tool，而不是 fancy but fragile research demo。

## 当前要弱化或移除的叙事

- 跨所有学科门类的通用研究自动化。
- “general AI-driven fully autonomous 24x7 researcher” 式承诺。
- 把完整论文工厂、开放式自治探索或从零高精度复现写成 next release 默认目标。
- 把早期 orchestrator / WebUI-v1 规格继续包装成当前实现主线。

## Next Release 的工作定义

当前 next release 的中心不是“完整研究引擎”，而是一个可用的 research dashboard baseline：

- 用户能启动 bounded discovery 或 bounded reproduction task。
- 用户能看到当前任务进度、最近完成任务、最近工件和基础资源状态。
- 任务必须有 milestone / checkpoint，而不只是散落日志。
- 失败、取消、阻塞和提前结束都必须成为正式结果。
- 系统输出必须能围绕 artifacts 被回看，而不是只留在一次 agent 会话里。

更细的要求以以下文档为准：

- [[LLM-Working/refactoring-plan/project-realignment-manifesto-plan]]
- [[LLM-Working/refactoring-plan/next-release-realignment-roadmap]]
- [[LLM-Working/refactoring-plan/mode-baseline-spec]]
- [[LLM-Working/refactoring-plan/dashboard-baseline-spec]]
- [[LLM-Working/refactoring-plan/architecture-baseline-plan]]

## 对 Mode 1 / Mode 2 的当前理解

- Mode 1 当前应理解为 `bounded discovery baseline`，不是完整自治文献探索系统。
- Mode 2 当前应理解为 `bounded reproduction baseline`，不是完整高精度深度复现承诺。
- 两种模式的最小要求是：可启动、可观察、可终止、可归档、可在 dashboard 中稳定展示。
- 它们的 next release 基线以 [[LLM-Working/refactoring-plan/mode-baseline-spec]] 为准，而不是以旧版双模式蓝图文档为准。

## 文档职责边界

### 当前有效职责

- 本文档负责解释项目定位、范围、优先级和非目标。
- `LLM-Working/refactoring-plan/` 负责 next release 的 requirements、baseline 和 architecture realignment。
- 代码与运行时 README 负责描述当前仍然存在的运行时表面，而不是保留已经退役的产品路线。

### 历史文档职责

以下文档保留为历史设计材料，用于追溯术语和判断来源，但不再是当前路径入口：

- [[framework/v1-rfc]]
- [[framework/v1-roadmap]]
- [[framework/webui-v1-rfc]]
- [[framework/webui-v1-roadmap]]
- [[framework/v1-implementation-status]]
- [[framework/v1-dual-mode-research-engine]]
- [[framework/artifact-graph-architecture]]
- [[framework/reference-mapping]]

## 非目标

- 不把 next release 定义成完整研究自动化平台。
- 不把 dashboard 反向扩张成复杂多用户协作产品。
- 不承诺完整 artifact graph 浏览器、复杂 telemetry 平台或全局运营分析。
- 不承诺投稿级写作、paper factory 工作流或稳定完成完整高精度复现。

## 读者指南

- 如果你想知道“项目现在应该做什么”，从 [[framework/index]] 和 `LLM-Working/refactoring-plan/` 文档集进入。
- 如果你想知道“旧设计当时为什么这样想”，再回读历史文档。
- 如果你看到某篇文档仍在把 orchestrator / WebUI-v1 描述成当前主线，应优先把它理解为历史材料，除非有更新文档明确覆盖。

## 关联笔记

- [[framework/index]]
- [[LLM-Working/refactoring-plan/index]]
- [[LLM-Working/refactoring-plan/project-realignment-manifesto-plan]]
- [[LLM-Working/refactoring-plan/mode-baseline-spec]]
- [[LLM-Working/refactoring-plan/dashboard-baseline-spec]]
- [[summary/academic-research-agents-overview]]
