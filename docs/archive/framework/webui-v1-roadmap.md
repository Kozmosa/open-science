---
aliases:
  - AINRF WebUI V1 Roadmap
  - WebUI-v1 路线图
tags:
  - research-agent
  - framework-design
  - webui
  - gradio
  - roadmap
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# AINRF WebUI-v1 Roadmap（历史文档）

> [!warning]
> 本文档保留为历史 WebUI 路线图。它记录的是早期基于 Gradio 的 WebUI-v1 交付切片与阶段目标，不再代表当前控制面方向或现行前端计划。

> [!abstract]
> 这份路线图曾用于描述 WebUI-v1 如何在旧版 orchestrator 叙事下独立推进，并以 W0-W5 组织文档、表单、详情页、mock 面板和验证工作。随着项目从 WebUI-v1 路线退场，本文档现在只作为历史材料保留，用于追溯当时的切片方式和边界判断。

## Overview

> [!note]
> 与旧版 W-series `LLM-Working` 散档对应的遗留继承说明已统一收拢到 [[LLM-Working/legacy-v1-summary]]；以下阶段描述仅用于回顾 WebUI-v1 当时如何拆分交付切片，不再构成当前前端路线、实现步骤或可执行任务清单。

```mermaid
gantt
    title AINRF WebUI-v1 历史路线图
    dateFormat  YYYY-MM-DD
    axisFormat  %m-%d

    section 文档与骨架
    W0 WebUI RFC & IA         :w0, 2026-03-16, 1d
    W1 App Shell & Client     :w1, after w0, 2d

    section 配置与工作台
    W2 Project & Run Forms    :w2, after w1, 3d
    W3 Run Detail & Gates     :w3, after w2, 3d

    section Mock 与收口
    W4 Mode Mock Panels       :w4, after w3, 3d
    W5 Validation & Docs      :w5, after w4, 2d
```

## W0: WebUI RFC & Information Architecture（历史切片）

**当时计划交付物：**

- `[[framework/webui-v1-rfc]]`
- `[[framework/webui-v1-roadmap]]`
- 主 RFC、主 roadmap、framework index 的最小回链
- Project / Run / MockMode 的信息架构与配置分层决策

**当时验收口径：**

- 文档明确 Project 只是 UI 组织层，不是后端资源
- 文档明确 Gradio + API client 边界
- 文档明确 P1-P7 配置覆盖方式与 P8/P9 mock 边界

**历史依赖关系：** 无

## W1: App Shell & API Client（历史切片）

> [!note]
> 具体实施规划见 [[LLM-Working/legacy-v1-summary]]；以下条目记录的是当时曾计划交付的 WebUI-v1 runtime surface，现已作为 retired artifact 保留。

**当时计划交付物：**

- `src/ainrf/webui/` 包骨架
- `ainrf webui` 启动入口
- Gradio app shell 与导航框架
- 面向现有 FastAPI 的 typed client 封装
- 健康检查与 API 连通性探测

**当时验收口径：**

- `ainrf webui` 能启动本地界面
- API 配置错误时，界面能给出明确错误状态
- 健康检查能显示服务可达 / 不可达 / degraded

**历史依赖关系：** P4、P6

**历史风险记录：**

| 风险 | 影响 | 缓解策略 |
| --- | --- | --- |
| Gradio 与现有 CLI 入口耦合不清 | 启动方式混乱 | 单独新增 `ainrf webui`，避免塞进 `serve` |
| API 契约继续演进 | client 容易反复返工 | 先对齐现有 `schemas.py`，保持 client 层集中收口 |

## W2: Project & Run Forms（历史切片）

> [!note]
> 具体实施规划见 [[LLM-Working/legacy-v1-summary]]；以下内容描述的是已退役表单/页面 surface 的历史拆分，不应再作为当前执行步骤。

**当时计划交付物：**

- Project List 与 Project Detail 两级视图
- Project 默认配置表单
- Run 创建表单，覆盖 P1-P7 对应配置项
- Project 默认值 -> Run 覆盖值 -> `TaskCreateRequest` 的映射逻辑

**当时验收口径：**

- 可以创建、编辑、读取 Project 默认配置
- Mode 1 / Mode 2 能生成不同的 run 表单
- 表单提交时能构造合法 `POST /tasks` 请求

**历史依赖关系：** W1、P4、P5

## W3: Run Detail, Gates & Event Timeline（历史切片）

> [!note]
> 具体实施规划见 [[LLM-Working/legacy-v1-summary]]；这里保留的是 retired run-detail / gate / event surface 的原始规划语义。

**当时计划交付物：**

- Run Detail 页面
- gate waiting / resolved 状态展示
- approve / reject UI 操作
- artifact 摘要和事件时间线视图
- SSE 优先、轮询降级的观察面

**当时验收口径：**

- 对真实 waiting gate，界面可触发 approve / reject
- 对终态 run，可稳定回放历史事件
- SSE 不可用时，轮询降级不改变主要页面结构

**历史依赖关系：** W2、P5、P6

## W4: Mode 1 / Mode 2 Interactive Mock（历史切片）

**当时计划交付物：**

- Mode 1 mock 面板：需求澄清、候选论文池、方法脉络、占位图谱、发现卡片与 idea 方向
- Mode 2 mock 面板：实现阶段、baseline、目标表格、偏差分析、质量评估
- mock data adapter，与真实 API client 分层隔离
- mock / real 数据源的显式标识

**当时验收口径：**

- 未实现的 mode 能完整走通创建 -> 详情 -> 占位推进 -> 结束态
- mock 状态不会污染真实 task payload
- 页面能稳定呈现成功、等待审批、失败三类占位结果

**历史依赖关系：** W3、P7

## W5: Validation, Demo Readiness & Documentation（历史切片）

**当时计划交付物：**

- smoke tests：启动、表单映射、API client 错误处理、mock flow
- WebUI 使用说明和演示路径
- 与主 RFC/roadmap 的最终回链
- `LLM-Working` 实施/复盘文档

**当时验收口径：**

- 关键 happy path 和降级路径均有 smoke coverage
- 文档明确区分真实能力与 mock 能力
- 演示时能够从 Project 进入 Run 并完成一次审批或 mock 完成流程

**历史依赖关系：** W4

## Cross-Cutting Historical Risks

| 风险类别 | 具体风险 | 影响范围 | 概率 | 缓解策略 |
| --- | --- | --- | --- | --- |
| 产品边界 | Project 与 task 边界不清，导致 UI 假设固化错误 | W2-W5 | 中 | 在 RFC 中把 Project 明确限制为 UI 组织层 |
| 前后端契约 | 现有 task API 无法覆盖全部 UI 预期字段 | W1-W3 | 中 | 先以现有接口为准，额外字段只停留在 UI 本地状态 |
| 技术选型 | Gradio 对复杂工作台支持有限 | W1-W4 | 中 | v1 控制页面数量和状态复杂度，避免过度交互 |
| 能力缺口 | P8/P9 未实现导致演示失真 | W4-W5 | 高 | 用 interactive mock 固定流程，同时显式标记占位能力 |

## Historical Exit Criteria

> [!note]
> 以下退出条件仅表示 WebUI-v1 路线在历史上曾以这些条目作为收口判断，不表示当前仓库仍应恢复或继续这些 runtime surface。
- WebUI 能作为独立入口启动。
- 至少具备 Project List、Project Detail、Run Detail 三个页面。
- 能通过 UI 创建 run、查看真实 task/gate/event 状态，并在未实现能力处展示明确 mock。
- 文档与实现都不把 UI 内部 `Project` 误写为后端一等对象。

## 关联笔记

- [[framework/index]]
- [[framework/v1-roadmap]]
- [[framework/webui-v1-rfc]]
- [[framework/v1-rfc]]
