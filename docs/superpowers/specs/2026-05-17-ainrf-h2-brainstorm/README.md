# AINRF ← Humanize2 Feature Brainstorm

Session: `ainrf-h2`, 2026-05-17

## Scope

对比 humanize2 与 AINRF 的架构异同，从 humanize2 借鉴功能方向。

## Priority Order

1. **Session Chain** — TaskAttempt + TaskSession 模型
2. **Token Track** — 按 Session 聚合 Token 用量与成本
3. **Timeline** — Gantt 风格的任务执行时间线可视化

## Visual Companion Pages

`visual-companion/` 目录保存了 brainstorming 过程中的可视化页面（HTML fragments，依赖 visual companion server 的 frame template 渲染）：

| File | Content |
|------|---------|
| `architecture-comparison.html` | Humanize2 vs AINRF 架构对比图 |
| `cartridge-session-token.html` | Cartridge / Session Chain / Token Track 概念解释 |
| `session-chain-approaches.html` | Session Chain 三种实现方案（A/B/C） |
| `design-data-model.html` | B 方案数据模型设计（ER 图、字段表、生命周期） |

## Current State

正在设计阶段，数据模型 section 已确认，下一步：API 设计。
