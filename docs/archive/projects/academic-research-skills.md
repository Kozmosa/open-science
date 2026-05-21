---
aliases:
  - Academic Research Skills
tags:
  - research-agent
  - repo-study
  - academic-pipeline
source_repo: academic-research-skills
source_path: /home/xuyang/code/scholar-agent/ref-repos/academic-research-skills
last_local_commit: 79dedce 2026-03-10 fix: version badge v2.7 → v4.0.3 (zh-TW)
---
# Academic Research Skills：从研究到发表的学术全流程管线

> [!abstract]
> 这个仓库最突出的不是“会写论文”，而是把学术产出当成一条需要 integrity check、peer review、revision coaching 和 final verification 的严肃流程来设计。它在本目录中最接近“投稿工厂”。

## 项目定位

- README 把它定义为“covering the full pipeline from research to publication”。
- 由 4 个主模块组成：`deep-research`、`academic-paper`、`academic-paper-reviewer`、`academic-pipeline`。
- 相比一般写作 skills，它非常强调 claim verification、reference integrity、两轮 review 和 Socratic coaching。

## 仓库构成

- 本地目录直接反映 4 段式结构，每个模块都有自己的 `agents/`、`examples/`、`references/`、`templates/`。
- 代理规模大：`deep-research` 13 个 agent，`academic-paper` 12 个，`academic-paper-reviewer` 7 个，`academic-pipeline` 3 个。
- `examples/showcase/` 提供真实产物，包含完整论文、integrity report、peer review report、response to reviewers 等。

## 核心工作流

```mermaid
flowchart LR
    A[Research] --> B[Write]
    B --> C[Integrity Check]
    C --> D[Review]
    D --> E[Socratic Coaching]
    E --> F[Revise]
    F --> G[Re-Review]
    G --> H[Re-Revise]
    H --> I[Final Integrity Check]
    I --> J[Finalize]
    J --> K[Process Summary]
```

## 研究生命周期覆盖

- 前期：`deep-research` 负责 systematic review、PRISMA、source verification、risk of bias、meta analysis。
- 中期：`academic-paper` 负责结构设计、论证、可视化、格式化、引用规范和 revision coaching。
- 后期：`academic-paper-reviewer` 与 `academic-pipeline` 负责编辑部视角、领域评审、魔鬼代言人、管线状态跟踪和 integrity verification。
- 这是一个典型“研究-写作-审稿-返修-定稿”闭环，不是轻量级助手。

## 集成与依赖面

- README 明确推荐 Claude Opus 4.6 + Max plan，并建议打开 Agent Team、Ralph Loop、skip permissions。
- 输出目标包含 MD、DOCX、LaTeX 以及用 tectonic 编译的 PDF，说明它默认面向正式交付。
- 许可证是 `CC BY-NC 4.0`，对非商业使用友好，但商业复用约束明显强于 MIT 仓库。

## 证据与样例

- 管线、功能、安装方式和 changelog 见 [academic-research-skills/README.md](../../ref-repos/academic-research-skills/README.md)。
- 各模块代理可从 [academic-research-skills/deep-research/agents](../../ref-repos/academic-research-skills/deep-research/agents) 与 [academic-research-skills/academic-paper/agents](../../ref-repos/academic-research-skills/academic-paper/agents) 观察。
- Showcase 产物见 [academic-research-skills/examples/showcase](../../ref-repos/academic-research-skills/examples/showcase)。
- 许可证见 [academic-research-skills/LICENSE](../../ref-repos/academic-research-skills/LICENSE)。
- 本地最近提交为 `79dedce`，日期 `2026-03-10`。

## 优势

- integrity 与 peer review 机制是显式的一等公民，非常适合严肃学术写作。
- 产物类型完整，能够落到 PDF、审稿意见和返修信。
- 代理角色设计细，覆盖偏差分析、伦理审查、元分析、编辑综合等高价值环节。

## 局限与风险

- token 和执行成本很高，README 明确提示端到端流程可能非常重。
- 对 Claude Code 生态依赖深，且默认假设用户接受较强自治权限。
- 更像正式写作管线，不是轻量的日常 research assistant。

## 适用场景

- 目标是把研究材料推进到“论文级交付”，且在乎 citation integrity 和 review quality。
- 需要结构化返修、response to reviewers、最终定稿产物。
- 可接受复杂流程和较高模型消耗，以换取严谨度。

## 关联笔记

- [[index]]
- [[summary/academic-research-agents-overview]]
- [[projects/auto-claude-code-research-in-sleep]]
- [[projects/awesome-claudecode-paper-proofreading]]
- [[projects/claude-scholar]]
