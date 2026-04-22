# 已实现 Runtime / WebUI Surface 设计归档

日期：2026-04-22

## 目的

`docs/superpowers/specs/` 中有一批设计稿来自早期的 runtime / WebUI 增量实现阶段。它们在当时帮助推进实现，但现在已经出现两个问题：

- 其中多份文档继续用“当前状态”措辞描述已经被后续实现覆盖的旧现实。
- 同一条实现线被拆成多个阶段性 design/spec 文档，容易让读者把它们误读成仍然有效的活规格。

本页用于把这批“已经完成使命的实现型 spec”合并归档到一个入口里，并明确当前的 source of truth。

## 当前 source of truth

对于已经落地的 runtime / WebUI surface，请优先参考：

- `docs/ainrf/index.md`
- `src/ainrf/README.md`
- `docs/LLM-Working/worklog/2026-04-21.md`
- `docs/LLM-Working/worklog/2026-04-22.md`

这几处才是当前实现状态、入口命令、API surface 和已完成切片的主记录。

## 已合并归档的过时 spec

以下设计稿已不再单独保留在活跃 `specs/` 集合中，因为它们的有效结论已经被上面的当前事实层文档吸收，或其“当前状态”叙述已明显落后于现状实现：

- `2026-04-13-terminal-bench-mvp-design.md`
- `2026-04-14-ainrf-usage-doc-design.md`
- `2026-04-14-code-server-managed-embedding-design.md`
- `2026-04-14-containers-page-design.md`
- `2026-04-14-webui-collapsible-sidebar-design.md`
- `2026-04-21-environments-containers-control-plane-design.md`
- `2026-04-21-webterminal-session-keepalive-user-binding-design.md`

这些文档的共同特征是：

- 它们描述的是已完成的实施切片，而不是当前仍待执行的规范。
- 其中不少“当前实现 / 当前 API / 当前前端结构”的描述已经被后续切片改写。
- 如果继续把它们散列保留为活跃 spec，容易制造上下文污染。

## 仍保留在 `specs/` 的文档

本轮没有一刀切删除 `specs/`；仍保留的文档应满足至少一条：

- 仍对应当前未完成的设计议题；
- 其内容没有被后续实现显著推翻；
- 它更像长期设计说明，而不是某个已完成切片的执行稿。

例如：

- `2026-04-06-ref-repos-submodules-design.md`
- `2026-04-13-ainrf-onboard-design.md`
- `2026-04-14-webui-style-loading-fix-design.md`
- `2026-04-22-docs-context-isolation-design.md`

## 维护规则

以后若某份 `docs/superpowers/specs/*.md` 已经完成使命，应优先按以下顺序收口：

1. 把仍然有效的结论提升到当前事实层文档。
2. 如果整篇文档已经被实现覆盖，就不要继续把它留在活跃 `specs/` 集合中。
3. 必要时把它并入这种“合并归档页”，而不是让多个过时 spec 长期并列。
