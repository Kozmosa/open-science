# Docs Directory Cleanup Design

## 目标

清理 `docs/` 目录中的过时内容、构建产物，并将不再活跃维护的历史文档归档到 `docs/archive/`。

## 删除清单

| 路径 | 原因 | 大小 |
|------|------|------|
| `presentation/ainrf-defense/node_modules/` | 构建产物，已 gitignored | 535 MB |
| `presentation/ainrf-defense/dist/` | 构建产物，已 gitignored | ~5 MB |
| `LLM-Working/refactoring-plan/` | 12 文件，零代码引用，重构已完成 | ~50 KB |
| `superpowers/specs/*/visual-companion/` | 4 个过期空/临时目录 | ~1 MB |

## 归档清单（移至 `docs/archive/`）

| 路径 | 原因 |
|------|------|
| `framework/` (14 文件) | V1 架构文档，已由 `superpowers/specs/` 取代 |
| `projects/` (10 文件) | 早期外部项目调研，2026-03 后未更新 |
| `summary/` (1 文件) | 跨项目综述，过时 |

## 保留清单

| 路径 | 原因 |
|------|------|
| `superpowers/specs/` | 活跃设计规范 |
| `superpowers/plans/` | 实施计划 |
| `ainrf/` | 当前产品文档 + 演示 |
| `LLM-Working/worklog/` | 工作日志 |
| `LLM-Working/` 根目录 `.md` 文件 | 摘要 |
| `assets/` | JS/CSS 资源 |
| `presentation/ainrf-defense/`（不含 node_modules/dist） | 演示 material |
| `index.md` | 站点入口 |

## 实施步骤

1. 创建 `docs/archive/` 目录
2. 移动 `framework/`、`projects/`、`summary/` 到 `archive/`
3. 删除 `presentation/ainrf-defense/node_modules/`、`dist/`
4. 删除 `LLM-Working/refactoring-plan/`
5. 删除 `superpowers/specs/*/visual-companion/`
6. 在 `archive/` 中放一个 `README.md` 说明这些是历史文档
7. 更新 `.gitignore` 确保 `node_modules/` 被忽略
8. 提交

## 验证

1. `mkdocs build` 或 `scripts/build.sh` 确认站点构建不受影响
2. `git status` 确认无意外变更
3. 确认 `docs/` 磁盘使用量从 ~550 MB 降到 ~15 MB
