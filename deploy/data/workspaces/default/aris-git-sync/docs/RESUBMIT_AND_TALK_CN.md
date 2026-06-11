# 🔁🎤 论文再投 & 会议报告流程(W5 / W6)

> [← 返回 README](../README_CN.md) · ARIS 的两个后期 workflow —— 跨 venue 移植论文(纯文本),以及把录用论文做成会议报告。

## 工作流 5：Resubmit Pipeline 🔁（跨 venue 移植论文，纯文本）

> **"论文在 venue A 投完了，要移植到 venue B。在硬约束下完成。"**

`/resubmit-pipeline` 把已经打磨好的论文从一个 venue 移植到另一个，硬约束：**不跑新实验、不改 bib、不动 framework、永远不覆盖先前的 submission 目录**。用于会议→期刊扩刊版、ML venue → 另一个 ML venue、非匿名 workshop 之后的匿名重投。不适合大改（大改用 `/paper-writing`）。

1. 📁 **物理隔离** — 复制到 `<NEW_VENUE_DIR>/`；原 submission 目录绝不动。
2. 🛡️ **5 层匿名检查** — 作者名、机构、自引用、GitHub / Overleaf 链接、行文中"我们"指代——任何破坏双盲的内容都会被标出。
3. 🔬 **审计（soft-only 模式）** — `/proof-checker`、`/paper-claim-audit`、`/citation-audit --soft-only`。`--soft-only` 把 `KEEP/FIX/REPLACE/REMOVE` 判决翻译成正文改写建议（bib 冻结）；幻觉引用走 `drop_cite_in_body_only` 动作。
4. ✏️ **微编辑** — `/auto-paper-improvement-loop --edit-whitelist <path>`（YAML schema：`allowed_paths` / `forbidden_paths` / `forbidden_operations`（如 `new_cite` / `new_theorem_env` / `numerical_claim`）/ `forbidden_deletions` / `max_edits_per_round`）+ 每轮 diff gate。
5. 🗡 **对抗 gate** — `/kill-argument` 终审 attack/adjudication；任何 critical 级 `still_unresolved` 拒绝放行。
6. 📤 **编译 + 推送** — `/paper-compile` + 可选 `/overleaf-sync push`。

<details>
<summary><b>展开工作流 5 的 resubmit 流程图</b> —— 隔离副本 → 5 层匿名 → soft-only 审计 → 白名单微编辑 → /kill-argument 对抗 gate → 编译 + Overleaf push</summary>

```
┌──────────────────────────────────────────────────────────────────────┐
│              工作流 5：纯文本 Resubmit                                │
│                                                                      │
│  已打磨论文                                                          │
│       │                                                              │
│       ▼                                                              │
│  隔离 → 匿名（5 层）→ 审计（--soft-only）                            │
│       │                                                              │
│       ▼                                                              │
│  微编辑（whitelist + diff gate）→ /kill-argument 对抗 gate           │
│       │                                                              │
│       ▼                                                              │
│  编译 + Overleaf push     →    <NEW_VENUE_DIR>/                      │
└──────────────────────────────────────────────────────────────────────┘
```

</details>

**涉及 skill：** `resubmit-pipeline`（orchestrator）、`auto-paper-improvement-loop --edit-whitelist`、`citation-audit --soft-only`、`proof-checker`、`paper-claim-audit`、`kill-argument`、`paper-compile`、`overleaf-sync`（可选）

**硬约束（不可覆盖）：**
- 🔒 **不跑新实验** —— 论文里每个数字必须已经存在于源 paper。
- 🔒 **不改 bib** —— 引用问题走 `--soft-only` 翻译为正文改写。
- 🔒 **不改 framework** —— theorem 环境、claim 形态、贡献范围全部冻结。
- 🔒 **永不覆盖先前 submission** —— 新 venue 单独目录。

**主 ledger：** `RESUBMIT_REPORT.json` 含 7 态失败模式表（含 `USER_DECISION` runtime 状态），符合 `shared-references/assurance-contract.md`。完整 feature 见 [2026-05-05 News 条目](#whats-new)。

## 工作流 6：Conference Talk Pipeline 🎤（论文 → slides → polish → audits）

> **"论文中了。现在准备会议演讲。"**

`/paper-talk` 是 `/paper-writing` 和 `/paper-poster-html` 的姊妹流水线，编排完整 talk 准备流程。`/slides-polish` 是内部调用的后处理打磨阶段——**不需要单独调**。

1. 📋 **大纲** —— 从 `paper/`（或 `NARRATIVE_REPORT.md`）抽取；每个贡献一个 slide 簇；段落映射到 talk beat。
2. 🎨 **生成** —— `/paper-slides` 出 Beamer 源码 + PPTX + 讲稿 + Q&A 准备。
3. 💎 **Polish** —— `/slides-polish` 对照 reference PDF 一页一页 Codex 审，套 fix-pattern catalog（PPTX 字号 1.5-1.8× 缩放保证投影可读、字号 bump 后 text frame resize、banner 用 tcolorbox、italic style 泄漏防御、em-dash 间距、中文 EA font 用 PingFang SC、anonymity placeholder 纪律）。
4. 🛡️ **审计**（当 `assurance: conference-ready`）—— `/paper-claim-audit` + `/citation-audit` 在合成 paper 目录上跑（slide 文字 + 讲稿 + 完整 script 物化成 `.aris/paper-talk/audit-input/sections/*.tex` + symlink 真实 `.bib` / `results/` / `figures/`），各输出 6 态 JSON verdict（见 `shared-references/assurance-contract.md`）；任何非 green 阻断 Final Report。

<details>
<summary><b>展开工作流 6 的 talk-prep 流程图</b> —— paper → outline → /paper-slides → /slides-polish → 可选 conference-ready 审计 gate</summary>

```
┌──────────────────────────────────────────────────────────────────────┐
│             工作流 6：会议演讲                                        │
│                                                                      │
│  paper/  →  outline  →  /paper-slides  (Beamer + PPTX + 讲稿)        │
│                                  │                                   │
│                                  ▼                                   │
│                         /slides-polish  (per-page Codex 打磨)        │
│                                  │                                   │
│                                  ▼                                   │
│               assurance: conference-ready ?                          │
│                 ├─ yes → /paper-claim-audit + /citation-audit        │
│                 │        在合成 paper staging adapter 上跑           │
│                 │        → 6 态 verdict 决定 Final Report 是否放行   │
│                 └─ no  → 直出 Final Report                           │
└──────────────────────────────────────────────────────────────────────┘
```

</details>

**涉及 skill：** `paper-talk`（orchestrator）、`paper-slides`、`slides-polish`、`paper-claim-audit` + `citation-audit`（仅 `assurance: conference-ready`）

**Assurance 阶梯**（与 `effort` 轴正交）：`draft / polished（默认）/ conference-ready`。合法组合：`— effort: lite, assurance: conference-ready` 意为「快流水线 + 每个 audit 必须出 verdict 才能 final」。

**单独使用 slide / poster 工具：** 只要 artifact 不要完整 orchestration，可直接 `/paper-slides "paper/"` 或 `/paper-poster-html "paper/"`，不经 `/paper-talk`。完整 feature 见 [2026-05-06 News 条目](#whats-new)。

<a id="-research-wiki--persistent-research-memory"></a>

