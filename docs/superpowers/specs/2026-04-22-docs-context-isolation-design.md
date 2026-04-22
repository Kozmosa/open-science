# 文档上下文隔离与归档设计

日期：2026-04-22

## 背景

当前仓库的 `docs/` 同时承载了三类信息：

- 当前仍然有效的项目定位、运行入口和研究知识库。
- 仍值得保留的历史设计、旧路线图和决策背景。
- 会话级 planning / spec / worklog 等执行中间产物。

这三类材料同时留在主文档树里，已经开始产生上下文污染：

- 当前入口文档已经在努力区分“当前路径”和“历史材料”，但默认阅读路径仍会把 agent 引到 `LLM-Working/refactoring-plan/` 这一类阶段性 decision package。
- `docs/superpowers/plans/`、`docs/superpowers/specs/` 和 `docs/LLM-Working/worklog/` 这类过程性文档保留在 `docs/` 下，对追溯有价值，但不应继续和长期事实层竞争默认注意力。
- `docs/LLM-Working/refactoring-plan/` 中存在 `/Users/kozmosa/...` 这类陈旧 `source_path` 元数据，说明其中部分文档既是阶段性规划，又已经携带过时环境信息。
- 历史 `v1` / `webui-v1` 文档虽然已加“历史文档”提示，但仍散落在 `docs/framework/` 主目录，容易在按主题搜索时与当前框架文档混读。

如果不做结构隔离，agent 很容易把“仍可追溯的旧背景”与“当前必须遵守的事实层”混成同一个上下文集合。

## 目标

本次清理要实现四个目标：

1. 默认阅读路径只把 agent 引向“当前事实层”。
2. 历史背景材料继续可追溯，但不再和当前规范竞争同等入口地位。
3. 已闭合的 process 文档从 `docs/` 主树中降权，必要时打包为 zip 并移出知识库主目录。
4. 建立一套后续可持续执行的文档分层规则，避免新的上下文污染再次累积。

## 非目标

本次设计不做以下事情：

- 不重写全部研究笔记、项目调研或框架正文。
- 不删除 `worklog` 这一类按仓库规则必须保留的版本化记录。
- 不把历史设计全部压缩成不可读二进制；仍需保留可直接阅读的历史索引和摘要。
- 不借这次清理重新定义产品路线或下一版功能范围。
- 不改变 `docs/` 作为长期 Markdown 知识库主目录这一仓库级约束。

## 方案比较

### 方案 A：修订为主

做法：尽量不移动文件，只通过首页、索引页和 warning 文案重新解释当前 / 历史 / 工作中间产物的边界。

优点：

- 改动最小。
- 链接和站点结构变更少。

缺点：

- 原始噪声仍留在 `docs/` 主树。
- 对 agent 的检索噪声降低有限。
- 旧文档和过程文档仍然容易在搜索中与当前文档并列出现。

### 方案 B：隔离为主（采用）

做法：保留当前事实层在主入口；历史文档进入明确的 archive/history 区域；已闭合的 process 文档从 `docs/` 主树降权或打包为 zip 移出 `docs/`。

优点：

- 能真正把当前事实层从历史和中间产物中分离出来。
- 既保留追溯能力，也显著降低默认上下文污染。
- 适合持续治理，后续新增文档也能按层归位。

缺点：

- 需要一次性调整目录、索引和部分 wikilink。
- 需要补 archive manifest，维护成本高于单纯改文案。

### 方案 C：归档为主

做法：除极少数主文档外，把大部分旧规划、旧 spec 和中间产物直接打 zip 移出主树。

优点：

- 主上下文最干净。

缺点：

- 丢失大量可直接阅读的历史材料。
- 容易过度归档，把仍需在线阅读的决策背景一起移走。

## 采用方案

采用方案 B：隔离为主。

核心原则是“当前事实层前置、历史层可追溯、过程层退出主上下文”。这不是简单换目录，而是把文档生命周期显式化。

## 文档分层模型

### 第一层：当前事实层

定义：如果一个新 agent 需要回答“项目现在是什么、当前应遵守什么、当前能运行什么”，应优先读取这层文档。

这一层保留在 `docs/` 主入口，并允许进入主索引：

- `docs/index.md`
- `docs/framework/index.md`
- `docs/framework/ai-native-research-framework.md`
- `docs/ainrf/index.md`
- `docs/projects/` 与 `docs/summary/` 中仍有效的研究知识库内容

这一层的约束：

- 不把阶段性 planning 文档写成当前 requirement 入口。
- 不引用已退役设计作为默认推荐阅读顺序。
- 不保留明显陈旧的机器环境元数据，如错误的绝对 `source_path`。

### 第二层：历史与决策背景层

定义：用于回答“过去为什么这样设计”“旧版做过哪些判断”“哪些边界是从历史方案继承来的”。

这一层应进入明确的 archive/history 入口，典型候选包括：

- `docs/framework/v1-rfc.md`
- `docs/framework/v1-roadmap.md`
- `docs/framework/v1-implementation-status.md`
- `docs/framework/webui-v1-rfc.md`
- `docs/framework/webui-v1-roadmap.md`
- `docs/framework/v1-dual-mode-research-engine.md`
- `docs/framework/artifact-graph-architecture.md`
- `docs/framework/reference-mapping.md`
- `docs/LLM-Working/legacy-v1-summary.md`

这一层的规则：

- 保留可直接阅读的 Markdown，不强制打包成 zip。
- 必须通过 archive/history 索引进入，而不是继续挂在当前推荐路径上。
- 必须有显眼的“历史 / 不再作为当前规范入口”标识。

### 第三层：过程与中间产物层

定义：为完成某一轮设计、规划、实现或记录而生成的 working documents。它们对追溯有价值，但不应继续定义仓库当前事实。

典型候选包括：

- `docs/LLM-Working/refactoring-plan/`
- `docs/LLM-Working/worklog/`
- `docs/superpowers/plans/`
- 已闭合、且其结论已被吸收到长期文档中的 `docs/superpowers/specs/`

这一层的规则：

- `worklog` 继续保留在版本控制中，但不进入主索引，不作为当前规范引用。
- 仍在执行中的 spec 可临时保留在 `docs/superpowers/specs/`，因为 superpowers 工作流依赖该路径。
- 已闭合的 plans/specs/refactoring packages 在完成“结论提升”后，应从 `docs/` 主树移出，并按批次打 zip 归档到仓库根级 `archives/` 目录。

## 目标目录结构

采用“可读历史保留在 `docs/`，高噪声过程包移出 `docs/`”的混合结构。

### `docs/` 内保留

- 当前事实层文档。
- 可直接阅读的历史文档。
- `worklog` 这类按仓库规则必须留在 `docs/` 的记录。

### `docs/` 内新增

- `docs/archive/index.md`
  - 作为历史与归档入口。
- `docs/archive/history/`
  - 存放仍应在线阅读的历史设计文档或它们的索引页。
- `docs/archive/manifests/`
  - 记录 zip 归档包的来源、时间、替代入口和恢复方法。

### 仓库根目录新增

- `archives/docs/`
  - 存放 zip 归档包，不进入 MkDocs，不作为默认上下文源。

这样做的原因是：

- 历史背景仍适合被网页直接阅读，因此保留在 `docs/`。
- 过程包最容易污染检索，且通常只在追溯时需要，因此应移出 `docs/`。

## 文档生命周期与提升流程

这次清理不只处理现有文件，还要定义以后如何避免复发。

### 1. 创建阶段

- 新的长期说明文档，默认归入“当前事实层”。
- 新的 plan / spec / execution note，默认归入“过程层”。

### 2. 收敛阶段

- 当某轮 planning / spec 已经转化为稳定结论时，把结论提升到当前事实层文档。
- 如果仍有历史解释价值，则额外保留一份“历史背景层”摘要。

### 3. 归档阶段

- 原始 working documents 从主索引移除。
- 若需要批量保留原稿，则打包为 zip 放入 `archives/docs/`。
- 同时在 `docs/archive/manifests/` 写一份 manifest，记录来源路径、归档原因、替代入口和 zip 文件名。

这个“提升后归档”的流程，确保当前事实层不会长期背着已经完成使命的 planning 噪声。

## 元数据与索引规则

为避免以后再次混淆，给高影响文档增加一个轻量的上下文字段：

- `doc_state: current | historical | working`

使用规则：

- `current` 文档允许进入主索引与推荐阅读顺序。
- `historical` 文档必须带显眼 warning，且只允许从 archive/history 入口被推荐。
- `working` 文档默认不进入主索引；如因工作流约束暂留在 `docs/` 中，也只能通过局部路径访问。

同时增加两条索引规则：

1. `docs/index.md`、`docs/framework/index.md` 不再直接把 `LLM-Working/refactoring-plan/` 这类 working package 作为当前主入口。
2. `docs/LLM-Working/worklog/`、`docs/superpowers/plans/`、`docs/superpowers/specs/` 不出现在任何“当前推荐阅读顺序”中。

## 针对当前仓库的具体处理建议

### A. 保留并修订的当前事实层文档

- `docs/index.md`
  - 收缩为知识库首页与当前框架入口，不再承担 process 文档导航。
- `docs/framework/index.md`
  - 去掉把 `LLM-Working/refactoring-plan/` 作为当前有效入口的表述，改为指向清理后的 current-baseline 文档或 archive 入口。
- `docs/framework/ai-native-research-framework.md`
  - 保留当前定位说明，但补充更明确的“当前事实层 / 历史层边界”。
- `docs/ainrf/index.md`
  - 保留为当前 CLI / WebUI 使用说明，并同步修正元数据一致性。

### B. 迁入历史层的文档

- `docs/framework/v1-rfc.md`
- `docs/framework/v1-roadmap.md`
- `docs/framework/v1-implementation-status.md`
- `docs/framework/webui-v1-rfc.md`
- `docs/framework/webui-v1-roadmap.md`
- `docs/framework/v1-dual-mode-research-engine.md`
- `docs/framework/artifact-graph-architecture.md`
- `docs/framework/reference-mapping.md`
- `docs/LLM-Working/legacy-v1-summary.md`

这些文档应保留可读性，但不再停留在当前框架主目录的默认阅读路径上。

### C. 优先压缩为 zip 的过程包

- `docs/superpowers/plans/` 中已闭合的 plan 文档。
- `docs/superpowers/specs/` 中已完成实现且结论已被吸收到长期文档的旧 spec。
- `docs/LLM-Working/refactoring-plan/` 中已经完成使命、且已可被一份 curated summary 替代的 planning cluster。

归档前置条件：

- 当前结论已经被提升到长期文档。
- 当前主索引已不再依赖原始 working files。
- 已准备 manifest，说明 zip 包与替代入口的对应关系。

### D. 保留但降权的记录

- `docs/LLM-Working/worklog/`

处理方式：

- 继续留在原目录，满足仓库 append-only 记录规则。
- 从首页、框架索引、AINRF 使用文档中移除直接推荐链接。
- 明确标记其用途是审计和追溯，不是当前 requirement 文档。

### E. 需要统一修订的元数据问题

- `docs/LLM-Working/refactoring-plan/` 中 `/Users/kozmosa/...` 形式的 `source_path` 应统一修正。
- 高影响文档里的 `workspace aggregate`、阶段冻结术语和带时间性的 realignment 话语，要么明确转入历史层，要么改写成当前仍成立的表述。

## 风险与边界

### 1. 过度归档

如果把仍有阅读价值的历史设计也一起打包成 zip，会降低追溯效率。因此历史层应优先保留 Markdown，只把高噪声过程包打 zip。

### 2. 误归档活跃 spec

superpowers 工作流要求新的设计文档保存在 `docs/superpowers/specs/`。因此只有当某份 spec 的实现周期结束、且结论已经被提升或已明确退役时，才允许把它移出主树。

### 3. 链接断裂

移动历史文档或压缩工作包会影响现有 wikilink，因此必须在实施时同步修正主索引和替代入口，不能只移动文件。

### 4. 清理后仍缺少统一入口

如果只移动文件、不新增 archive/index 和 manifest，用户会失去历史材料的入口。因此“隔离”必须同时包含新的入口设计。

## 验证要求

实施完成后至少要验证以下几点：

1. `uv run python scripts/build_html_notes.py build` 通过，确认移动后 wikilink 没有失效。
2. `docs/index.md` 和 `docs/framework/index.md` 的推荐阅读路径不再直接指向 working packages。
3. `rg -n "/Users/kozmosa" docs` 返回空，确认陈旧绝对路径已被清理。
4. `docs/archive/index.md` 与对应 manifest 能解释每个 zip 归档包的来源和替代入口。
5. `docs/LLM-Working/worklog/` 仍保留，但不再作为当前规范入口被推荐。

## 实施顺序

建议按四步推进：

1. 先建立分层入口和归档位置。
   - 新增 `docs/archive/index.md`
   - 确定 `archives/docs/` 和 manifest 规则

2. 再修当前事实层入口。
   - 修订 `docs/index.md`
   - 修订 `docs/framework/index.md`
   - 必要时补一个专门的 current-baseline / document-map 文档

3. 然后迁移历史层与过程层。
   - 迁移历史框架文档
   - 为 `refactoring-plan` 生成 curated summary
   - 打包关闭的 plans/specs/refactoring bundles

4. 最后补治理规则。
   - 给高影响文档补 `doc_state`
   - 固定“提升后归档”的维护流程
   - 把这套规则回写到相关索引或仓库约束文档中

## 预期结果

清理完成后，仓库文档应形成如下行为：

- agent 默认进入的是当前事实层，而不是历史规划或会话中间产物。
- 历史文档仍可读、可查、可回溯，但不会继续冒充当前规范。
- 过程文档被控制在有限窗口内停留于 `docs/`，闭合后及时提升结论并归档原稿。
- 以后即使继续用 agent 产出 spec / plan / worklog，也不会再不断抬高主文档树的噪声密度。
