# 项目文件指南

[English](PROJECT_FILES_GUIDE.md) | 中文版

> ARIS 科研工作流中的项目级状态文件规范 — 每个文件的定位、写入时机、以及相互关系。

## 问题

ARIS 工作流会在多个阶段产出大量信息：idea、实验计划、结果、审稿反馈、决策。如果没有清晰的文件规范，这些信息会散落在聊天记录中，在上下文压缩或新会话时丢失。

本指南建立一套分层文件体系，每个文件有明确的定位、更新触发条件和与其他文件的关系。

## 文件总览

```
project/
├── CLAUDE.md                              # 仪表盘 — Pipeline Status + 项目约束
├── findings.md                            # 轻量级发现日志（实验 + debug）
├── MANIFEST.md                            # 产出追踪清单（自动维护）
│
├── idea-stage/                            # W1: Idea Discovery 产出
│   ├── IDEA_REPORT.md                     # brainstorm 原始产出（来自 /idea-creator）
│   ├── IDEA_CANDIDATES.md                 # 经评审筛选的可行 idea 候选池
│   ├── REF_PAPER_SUMMARY.md              # 参考论文摘要（设置 REF_PAPER 时生成）
│   └── docs/
│       └── research_contract.md           # 当前 idea 的聚焦上下文
│
├── refine-logs/                           # W1.5: 实验规划与精炼
│   ├── EXPERIMENT_PLAN.md                 # 实验设计（claim + blocks）
│   ├── EXPERIMENT_TRACKER.md              # 执行清单（TODO → DONE）
│   ├── EXPERIMENT_RESULTS.md              # 收集的实验结果
│   ├── EXPERIMENT_LOG.md                  # 所有实验的完整记录
│   ├── FINAL_PROPOSAL.md                 # 最终精炼提案
│   ├── PIPELINE_SUMMARY.md               # 流水线执行摘要
│   ├── REFINE_STATE.json                  # 精炼恢复状态
│   └── round_N_*.md                       # 每轮审稿/提案文件
│
├── review-stage/                          # W2: Auto Review 产出
│   ├── AUTO_REVIEW.md                     # 审稿循环日志（来自 /auto-review-loop）
│   └── REVIEW_STATE.json                  # 审稿循环恢复状态
│
├── paper/                                 # W3: 论文写作产出
│   ├── main.tex                           # LaTeX 源文件
│   └── roundN/                            # 每轮 PDF 快照
│
└── research-wiki/                         # 持久化知识库
    ├── papers/ ideas/ experiments/ claims/
    └── graph/
```

### ARIS 已有文件（不变）

| 文件 | 创建者 | 定位 |
|------|--------|------|
| `idea-stage/IDEA_REPORT.md` | `/idea-creator` | brainstorm 原始产出：全部 8-12 个 idea + pilot 结果 + 被 kill 的 idea |
| `refine-logs/EXPERIMENT_PLAN.md` | `/experiment-plan` | 实验设计：claim 映射、实验块、执行顺序、算力预算 |
| `refine-logs/EXPERIMENT_TRACKER.md` | `/experiment-plan` | 执行清单：run ID、状态（TODO→DONE）、一句话 notes |
| `review-stage/AUTO_REVIEW.md` | `/auto-review-loop` | 审稿循环累积日志：评分、reviewer 原始响应、采取的行动 |
| `review-stage/REVIEW_STATE.json` | `/auto-review-loop` | 上下文压缩恢复状态 |

### 新增文件（本指南）

| 文件 | 定位 | 模板 |
|------|------|------|
| `idea-stage/IDEA_CANDIDATES.md` | 评审后存活的可行 idea 候选池 — idea 失败时从这里选下一个 | [`IDEA_CANDIDATES_TEMPLATE_CN.md`](../templates/IDEA_CANDIDATES_TEMPLATE_CN.md) |
| `findings.md` | 轻量级发现日志 — 实验异常、debug 根因、关键决策 | [`FINDINGS_TEMPLATE.md`](../templates/FINDINGS_TEMPLATE.md) |
| `refine-logs/EXPERIMENT_LOG.md` | 完整实验记录 — 详细结果、配置、复现命令 | [`EXPERIMENT_LOG_TEMPLATE.md`](../templates/EXPERIMENT_LOG_TEMPLATE.md) |
| `idea-stage/docs/research_contract.md` | 当前 idea 的聚焦工作文档（见[会话恢复指南](SESSION_RECOVERY_GUIDE_CN.md)） | [`RESEARCH_CONTRACT_TEMPLATE.md`](../templates/RESEARCH_CONTRACT_TEMPLATE.md) |

## 文件之间的关系

### Idea 流

```
IDEA_REPORT.md                    （12 个 idea，brainstorm 原始产出）
  ↓ novelty-check + review 筛选
IDEA_CANDIDATES.md                （3-5 个可行 idea，带评分）
  ↓ 选一个
idea-stage/docs/research_contract.md         （当前 idea，聚焦上下文）
  ↓ idea 失败？
IDEA_CANDIDATES.md → 选下一个 → 更新 contract
```

**为什么三个文件？** 防止上下文污染。每次会话都加载 12 个原始 idea 浪费 LLM 工作记忆。候选池精简（3-5 条），contract 聚焦（一个 idea）。恢复时 LLM 只读 contract，不读完整 report。

### 实验流

```
EXPERIMENT_PLAN.md                （跑什么 — 设计）
  ↓
EXPERIMENT_TRACKER.md             （执行状态 — TODO/RUNNING/DONE）
  ↓ 实验完成
EXPERIMENT_LOG.md                 （跑出了什么 — 完整结果 + 复现命令）
  ↓ 发现异常
findings.md                       （一句话记录 — 异常、根因、决策）
```

**为什么 tracker 和 log 分开？** 受众不同。Tracker 是执行管理（"还剩什么没跑"），Log 是知识保存（"跑了什么、学到了什么"）。Tracker 切 idea 时可以重置；Log 是永久记录。

### 写入时机

| 文件 | 什么时候写 | 更新频率 |
|------|----------|----------|
| `IDEA_CANDIDATES.md` | `/idea-discovery` 完成后创建；idea kill/selection 时更新 | 每次 idea 切换 |
| `findings.md` | 实验/debug/分析中发现非预期现象 | 随时追加 |
| `EXPERIMENT_LOG.md` | 任何实验结束后（成功或失败都记） | 每个实验完成后 |
| `idea-stage/docs/research_contract.md` | 选定 idea 时；baseline 复现后；重大结果产出后 | 每个阶段里程碑 |

### 会话恢复优先级

新会话或压缩后，按以下顺序读取：

1. `CLAUDE.md` → Pipeline Status（30 秒定位）
2. `idea-stage/docs/research_contract.md`（当前 idea 上下文）
3. `findings.md` 最近条目（最近发现了什么）
4. `refine-logs/EXPERIMENT_LOG.md`（按需：跑过什么实验）

**不要**在非切换 idea 时读 `IDEA_REPORT.md` 或 `IDEA_CANDIDATES.md`。

## 分工原则

| 问题 | 答案 |
|------|------|
| brainstorm 的 idea 放哪？ | `IDEA_REPORT.md`（原始）→ `IDEA_CANDIDATES.md`（筛选后） |
| 当前 idea 的完整上下文放哪？ | `idea-stage/docs/research_contract.md` |
| "实验 X 正在跑"放哪？ | `EXPERIMENT_TRACKER.md` |
| "实验 X 准确率 95.2"放哪？ | `EXPERIMENT_LOG.md` |
| "lr=1e-4 在数据集 X 上发散"放哪？ | `findings.md` |
| "reviewer 说加 ablation"放哪？ | `review-stage/AUTO_REVIEW.md` |
| "选方案 A 而不是 B，因为 Z"放哪？ | `findings.md` |
| "当前阶段是 training"放哪？ | `CLAUDE.md` Pipeline Status |

## 产出版本控制

ARIS 技能使用带时间戳的文件名保留历史。每次产出写入两份：

1. **带时间戳文件**：`{FILENAME}_{YYYYMMDD_HHmmss}.md` — 永久历史记录
2. **固定名文件**：`{FILENAME}.md` — 最新副本，供下游技能读取

```
idea-stage/
├── IDEA_REPORT_20250615_143022.md    ← 第一次运行
├── IDEA_REPORT_20250616_090015.md    ← 第二次运行
├── IDEA_REPORT.md                    ← 最新副本（= 20250616 版本）
```

**不带时间戳的文件**：追加式文件（`findings.md`）、每轮文件（`round_N_*.md`）、仪表盘（`CLAUDE.md`）、清单（`MANIFEST.md`）。

详见 [shared-references/output-versioning.md](../skills/shared-references/output-versioning.md)。

## 产出清单

项目根目录的 `MANIFEST.md` 追踪每个技能写入的每个文件：

| 时间戳 | 技能 | 文件 | 阶段 | 描述 |
|--------|------|------|------|------|
| 2025-06-15 14:30 | /idea-creator | idea-stage/IDEA_REPORT.md | idea | 从"LLM reasoning"生成 12 个 idea |

技能在每次写入后追加此文件。它作为所有研究产物的中央索引，并支持预检查（例如 `/experiment-bridge` 可在启动前验证 `refine-logs/EXPERIMENT_PLAN.md` 是否存在）。

详见 [shared-references/output-manifest.md](../skills/shared-references/output-manifest.md)。
