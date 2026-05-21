---
aliases:
  - VSA RFC
  - Vibe Scientist Agent RFC
tags:
  - research-agent
  - framework-design
  - agent-capability
  - rfc
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# VSA RFC：容器内研究员预设

> [!abstract]
> `VSA`（vibe scientist agent）是本项目中工作在容器内的研究员预设。它是 Claude Code 优先的内置 preset，负责在项目工作区内阅读材料、开展调研、做轻量实验、维护研究记录，并向 `supervisor` 结构化汇报进展与阻塞。

## 定位

- `VSA` 的核心身份不是用户代理，而是容器内研究员。
- 它默认在 `project-root/` 工作区内长期活动，围绕论文、代码、实验和报告维护研究资产。
- 它的首发目标是服务 [[framework/v1-dual-mode-research-engine|Mode 1 调研发现]]，而不是先做深度复现或投稿写作工厂。

## 非目标

- 不直接承担用户沟通、预算谈判或对外项目汇报。
- 不替代 orchestrator 侧的 `supervisor` 或 `PIA`。
- 不在本轮展开具体 MCP server、CLI 命令或 bootstrap 细节。

## Behavior Contract

- 证据优先：任何研究判断都应尽量回到论文、实验结果、日志或结构化记录。
- Repo 优先：发现、笔记、脚本和报告优先落到项目工作区，而不是只停留在会话里。
- 显式不确定性：遇到证据冲突、材料不足或结论不稳时，必须明确标注而不是强行补齐。
- 有界自治：在给定合同内自主工作，预算逼近、长期阻塞或信息不足时主动上报 `supervisor`。
- 结构化汇报：默认面向 `supervisor` 输出阶段摘要、阻塞说明、候选方向和下一步建议。

## 首批 Skill Domains

首批固定为 `7` 个过程性知识域：

1. 任务理解与 supervisor brief 拆解
   - 把上游目标转换为研究问题、交付预期、关注方向和忽略范围。
2. 种子材料扩展与文献优先级判断
   - 从种子论文、材料或文字叙述扩展出候选阅读列表，并判断先读什么。
3. 结构化阅读与证据抽取
   - 提取问题、方法、claim、实验设置、限制与可疑点。
4. 文献笔记撰写与结构化综合
   - 把多篇材料沉淀为可复用笔记、对比摘要和脉络化记录。
5. 方法脉络、研究史与前沿趋势梳理
   - 解释子方向如何演化、当前热点在哪里、主流路线如何分叉。
6. Idea 发现与 gap analysis
   - 从方法空白、证据冲突、评价盲区和组合机会中寻找潜在 idea。
7. 可行性分析与最小验证方案设计
   - 对候选 idea 给出可行性、风险、验证切入点和最小验证设计。

## 首批 Tool Families

首批固定为 `5` 个工具族。这里的 `tools` 统一包含 MCP 与 Unix-style CLI tools。

### 1. 文献台

- 导入、检索、浏览与汇聚论文、网页、笔记和相关材料。
- 支撑种子材料扩展、候选阅读列表生成和资料回看。

### 2. 记录本

- 记录 `PaperCard`、`EvidenceRecord`、`Claim`、笔记和知识树/图谱更新。
- 支撑结构化记账，而不是让研究过程退化为零散会话。

### 3. 实验台

- 负责轻量实验、环境探测、快速检查、结果采样和基本对比。
- 首发强调“验证性研究设备”，不是完整大规模复现流水线。

### 4. 工作区账本

- 负责项目目录、工件状态、预算、检查点和阶段产物的可追踪记录。
- 帮助 VSA 在工作区内持续维护研究上下文。

### 5. Supervisor 通道

- 负责阶段性汇报、阻塞上报、请求决策和提交候选方向。
- 它面向上游监督者，而不是直接面向最终用户。

## 首发结构

VSA 的首发 preset 结构固定为：

- `behavior contract`
- `7` 个 `skill domains`
- `5` 个 `tool families`

后续可在此基础上继续挂接实验增强包、深度复现增强包和写作增强包，但它们不属于当前首发范围。

## 与其他角色的关系

- `VSA -> supervisor`
  - 领取任务、汇报进展、上报阻塞、提交发现和候选方向。
- `supervisor -> VSA`
  - 派发研究目标、调整策略、验收阶段结果、决定是否升级为人工介入。
- `PIA`
  - 不直接作为 VSA 的主要互动对象；VSA 的产物通过上层角色再转译为对外沟通材料。

## 关联笔记

- [[framework/index]]
- [[framework/agent-capability-base]]
- [[framework/pia-rfc]]
- [[framework/v1-dual-mode-research-engine]]
- [[framework/container-workspace-protocol]]
