# Task Harness v1 设计

日期：2026-04-23

## 背景

当前仓库已经逐步形成以 `task-centric dashboard` 为中心的控制面方向，也已经存在 `workspace`、`environment`、code-server、任务 read model 等相关模块与规格约束。

下一轮 feats 需要开始落真正的 `task` 功能，而不是继续停留在抽象 dashboard 或历史 WebUI 叙事层。用户提出的第一版目标很明确：

1. web 端实时监控 task 的输出。
2. web 端启动新的 task。
3. web 端查看已有 task 的完成情况与终态。

同时，这一版 task 不能被设计成孤立对象，而必须与现有 `workspace`、`environment` 模块结合：

- 创建 task 时必须显式绑定一个已有 `workspace`。
- 创建 task 时必须显式绑定一个已有 `environment`。
- `environment` 的职责是描述 Claude Code 所运行机器的环境画像，而不是任务模板。
- task 启动前必须完成 prompt 合成，并把 `workspace` / `environment` 纳入 prompt stack。

用户还明确要求第一版只覆盖 harness 自己启动的 task，不引入中途控制、外部会话接入或更高层 workflow 抽象。

## 目标

本次设计要达成以下目标：

1. 定义一个 `Task Harness v1`，用于管理由 web harness 启动的 Claude Code 会话型 task。
2. 固定 task 与 `workspace`、`environment` 的绑定关系和最小状态模型。
3. 定义可审计的 prompt composition contract，支撑 task 启动前的静态 prompt 合成。
4. 定义任务创建、列表、详情、输出回放与实时流的后端 contract。
5. 让 v1 成为一个薄控制面，先稳定支持 start + read-only monitoring 的闭环。

## 非目标

本次设计不做以下事情：

- 不把 task 设计成更高层 workflow、任务队列或多会话 orchestration 对象。
- 不引入 planner / coder / reviewer 多 agent pipeline。
- 不支持 `terminate`、`cancel`、`retry`、`resume`、`takeover`、`attach terminal`。
- 不接入外部已有 Claude Code 会话或扫描机器上所有相关进程。
- 不在 v1 中引入 runtime probe 参与 environment prompt 生成。
- 不在 web 端提供 prompt 编辑器、environment/workspace 编辑器或任务模板系统。
- 不重写现有 `workspace`、`environment` 模块自身定义。

## 参考取舍

本次设计参考 `https://github.com/zclllyybb/multi-agent-todo.git` 的方式来思考 harness 形态，但只继承其中两个对当前目标有价值的方向：

- `task` 作为 dashboard 的一级对象。
- web 端直接暴露运行中任务输出和终态结果。

以下能力明确不作为 v1 目标：

- daemon 驱动的多任务调度。
- planner → coder → reviewer 的自动循环。
- worktree 并行执行体系。
- 更平台化的多 agent 编排能力。

因此，`Task Harness v1` 是 thin control plane，而不是 `multi-agent-todo` 风格的 orchestrator baseline。

## 采用方案

采用 `Task Harness Thin Control Plane` 方案。

核心原则是：

- `task` 是一级对象，但仅代表一个 harness-managed Claude Code 会话。
- `workspace` 与 `environment` 是 task 的显式绑定对象，不在本次设计中被提升为新的产品中心。
- web 端第一版只负责 launch、list、detail、output monitoring。
- prompt composition 使用静态 profile 与固定模板合成，不依赖 runtime 自动探测。
- 所有状态、输出和终态都由 harness 自己持久化，而不是依赖外部进程发现。

## 核心对象模型

### `task`

`task` 是 v1 的一级对象，也是前后端 contract 的中心。一个 `task` 对应一次由 harness 启动的 Claude Code 会话 / 进程。

最低字段建议分成 5 个区块：

1. `identity`
2. `binding`
3. `prompt_snapshot`
4. `runtime`
5. `result`

最小字段清单：

- `task_id`
- `title`
- `task_profile`
- `workspace_id`
- `environment_id`
- `status`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`
- `exit_code`
- `error_summary`

### `workspace`

`workspace` 是 task 的必填绑定对象，用于提供该 task 所属工作目录和工作区上下文。

v1 对 `workspace` 的要求只有三点：

- 创建 task 时必须显式选择已有 `workspace`。
- task 启动时使用该 `workspace` 的上下文来构造 launch contract。
- `workspace` 相关提示词通过 `workspace prompt` 注入到 prompt stack 中。

v1 不负责定义 `workspace` 的生命周期管理、自动创建策略或编辑界面。

### `environment`

`environment` 是 task 的必填绑定对象，用于描述 Claude Code 运行机器的环境画像。

用户已经明确：`environment` 不是任务模板，而是对运行时机器环境的描述，至少包括：

- 操作系统。
- 算力条件。
- 常用工具链与软件包的访问命令。
- 是否可访问 GitHub / Hugging Face / Google 等网络资源。
- 网络不可达时的替代方式。

v1 对 `environment` 的约束：

- 创建 task 时必须显式选择已有 `environment`。
- `environment prompt` 以人工维护的 environment profile 为事实源。
- v1 不依赖 runtime probe 自动生成首版 environment prompt。

### `task_profile`

`task_profile` 对应 prompt stack 中的 `mode/task-type` 层。

用户要求第一版使用“通用 Claude Code task”模式，因此：

- v1 可以只提供一个默认 `task_profile = claude-code`。
- 该字段仍然必须保留在 contract 中。
- 保留该字段的原因是后续可能扩展不同的 prompt profile，但 v1 不把它发展成复杂任务模板系统。

## 生命周期模型

v1 的 task 生命周期压成最小闭环：

- `queued`
- `starting`
- `running`
- `succeeded`
- `failed`

约束如下：

- `queued` 表示 task 记录已创建，但实际会话尚未开始启动。
- `starting` 表示正在完成 prompt 合成、launch payload 构造和 Claude Code 进程拉起。
- `running` 表示 Claude Code 会话已经成功进入运行态，stdout/stderr 开始可观测。
- `succeeded` 表示 Claude Code 进程正常退出，且 harness 成功记录终态。
- `failed` 表示启动失败或运行期异常退出。

v1 明确不引入：

- `cancelled`
- `terminated`
- `retrying`
- `paused`
- `blocked`

原因是第一版控制面边界已经被限制为 `start + read-only monitoring`，不应为了未来动作提前膨胀状态机。

## Task 创建与绑定策略

### 创建表单最小字段

web 端创建 task 的最小输入字段为：

- `workspace_id`
- `environment_id`
- `task_profile`
- `task_input`
- `title`

约束如下：

- `workspace_id` 必填，且必须来自已有 `workspace`。
- `environment_id` 必填，且必须来自已有 `environment`。
- `task_profile` 在 v1 可以只有默认值 `claude-code`，但仍保持显式字段。
- `task_input` 是最终提交给 Claude Code 的任务文本输入。
- `title` 可选；缺失时允许从 `task_input` 派生出列表展示摘要。

### 创建语义

采用“同步创建记录，异步启动会话”的语义：

1. web 表单提交最小 task 输入。
2. harness 校验 `workspace`、`environment`、`task_profile` 是否存在且可供启动。
3. 创建 task 记录，状态为 `queued`。
4. 进入 `starting`，执行 prompt compose、snapshot 固化和 launch payload 构造。
5. 只有在 snapshot 落盘成功后，才允许真正启动 Claude Code 会话。
6. 成功拉起后转为 `running`。

这意味着 task 的事实源始终是 harness registry，而不是运行中的外部进程本身。

## Prompt Composition Contract

### 目标

v1 必须正式引入 prompt composition，而不是把 task input 直接裸传给 Claude Code。

prompt composition 的目标不是做一个通用模板引擎，而是把启动 task 所依赖的上下文层次显式化、可审计化，并固定其顺序。

### 固定顺序

prompt stack 的固定顺序为：

1. `global harness/system prompt`
2. `workspace prompt`
3. `environment prompt`
4. `task_profile prompt`
5. `task input`

该顺序由用户明确确认，v1 中不允许任意重排。

### 各层职责

#### `global harness/system prompt`

负责提供 harness 级别的统一行为约束，例如：

- 当前 harness 的总体角色。
- task 运行时必须遵守的全局边界。
- 控制面所依赖的统一协作方式。

#### `workspace prompt`

负责注入工作区级上下文，例如：

- 当前 repository / working directory。
- 工作区级协作约束。
- 与当前 workspace 直接相关的固定上下文。

#### `environment prompt`

负责注入运行机器画像，只描述环境，不描述业务任务。至少应覆盖：

- OS 和资源情况。
- 工具链与软件包的访问命令。
- 网络可达性。
- 不可达资源的替代访问路径。

事实源是人工维护的 environment profile 文档，而不是运行时探测结果。

#### `task_profile prompt`

负责描述“这是一类怎样的 Claude Code task”。

v1 中可以非常薄，只承担通用 Claude Code task 的行为包装，不承担 environment 或 workspace 的职责。

#### `task input`

负责表达本次 task 的实际请求，是启动表单提交的用户输入。

### Snapshot 要求

为了让 prompt composition 成为可审计合同，task 启动前必须至少固化三类产物：

1. `binding_snapshot`
2. `prompt_layer_manifest`
3. `resolved_launch_payload`

#### `binding_snapshot`

记录启动时绑定的：

- `workspace`
- `environment`
- `task_profile`

并保存稳定标识和展示摘要，确保后续 detail 页能回答“这个 task 是基于什么绑定启动的”。

#### `prompt_layer_manifest`

记录：

- 五层 prompt 的来源。
- 拼接顺序。
- 渲染后文本快照。
- 版本或更新时间等轻量元数据。

#### `resolved_launch_payload`

记录最终提交给 Claude Code 的解析后输入和 launch 相关参数，作为后续回放和排障依据。

### 失败约束

如果以下任一环节失败：

- `workspace prompt` 缺失。
- `environment profile` 不完整。
- `task_profile prompt` 无法解析。
- 模板渲染报错。

则 task 必须直接进入 `failed`，并记录明确的 `startup_error`。v1 不允许静默降级、跳过某一层继续启动，避免 task 的实际上下文与页面展示不一致。

## 运行时模块边界

v1 后端建议拆成 4 个薄模块：

1. `TaskRegistry`
2. `PromptComposer`
3. `TaskLauncher`
4. `TaskOutputStore`

### `TaskRegistry`

负责：

- 保存 harness-managed task 元数据。
- 驱动状态迁移。
- 维护列表页和详情页所需摘要。

不负责：

- 外部进程扫描。
- 高层队列编排。
- 多 agent 调度。

### `PromptComposer`

负责：

- 按五层顺序合成 prompt。
- 生成 `binding_snapshot`、`prompt_layer_manifest`、`resolved_launch_payload`。
- 对 compose 失败进行明确报错。

### `TaskLauncher`

负责：

- 把 `workspace + environment + resolved launch payload` 转化为一次 Claude Code 启动。
- 管理一次 task 与一个 Claude Code 会话 / 进程的映射。
- 在进程退出时写入终态和 runtime summary。

### `TaskOutputStore`

负责：

- 持续接收 stdout / stderr。
- 为 task 生成 append-only transcript。
- 支撑历史回放与实时 SSE 推送。

关键约束：实时输出不能只存在内存里，必须在运行过程中就持久化。否则页面刷新或服务重启后将丢失 v1 的核心价值之一。

## API Contract

### 最小 API 集合

v1 建议提供以下最小 surface：

1. `POST /tasks`
2. `GET /tasks`
3. `GET /tasks/{id}`
4. `GET /tasks/{id}/output`
5. `GET /tasks/{id}/stream`

### `POST /tasks`

职责：创建并启动一个 harness-managed task。

输入至少包括：

- `workspace_id`
- `environment_id`
- `task_profile`
- `task_input`
- `title`

行为约束：

- 成功创建后返回 task 基础信息和初始状态。
- 创建后由 harness 自己推进到 `starting` / `running` / `failed`。

### `GET /tasks`

职责：返回 harness 自己创建的 task 列表。

注意：用户已经明确确认，列表只显示通过这个 web harness 启动的 task，而不是当前机器上的全部 Claude Code 相关会话。

列表页最小字段：

- `task_id`
- `title`
- `workspace_summary`
- `environment_summary`
- `status`
- `created_at`
- `updated_at`
- `finished_at`
- `exit_code`
- `error_summary`

### `GET /tasks/{id}`

职责：返回单个 task 的详情。

建议 detail 页围绕 4 个区块组织：

1. binding summary
2. prompt composition summary
3. runtime summary
4. output viewer

### `GET /tasks/{id}/output`

职责：按 cursor 或 `after_seq` 回放 stdout / stderr transcript。

要求：

- 支持页面刷新后的增量补拉。
- 输出是 append-only 的稳定序列，而不是即时拼装的临时流。

### `GET /tasks/{id}/stream`

职责：通过 SSE 推送新增输出和生命周期事件。

v1 推荐使用 `REST + SSE`，而不是直接引入 websocket。原因是：

- 列表与详情摘要更适合普通 REST 读取。
- 实时输出只需要单向追加事件。
- SSE 足够支撑 v1 的 read-only monitoring，不需要更重的双向控制通道。

## 输出与实时流模型

### 统一事件形态

建议 `output` 与 `stream` 共用统一的 append-only event shape，至少包含：

- `seq`
- `timestamp`
- `stream`
- `text`

其中 `stream` 允许的最小值：

- `stdout`
- `stderr`
- `system`
- `lifecycle`

### 页面行为

前端进入 detail 页时，建议按以下顺序拉取数据：

1. `GET /tasks/{id}` 获取详情摘要。
2. `GET /tasks/{id}/output?after_seq=...` 获取历史尾部 transcript。
3. `GET /tasks/{id}/stream` 订阅新增事件。

这样做的原因是：

- 页面刷新后可以依赖持久化 transcript 重建当前视图。
- 即使 SSE 中断，也可以通过 output replay 恢复缺失片段。
- 不需要依赖“一直连着的那条流”才能理解 task 发生了什么。

## 列表页与详情页基线

### 列表页

列表页只需要回答：

- 有哪些 harness-managed tasks。
- 它们分别绑定了哪个 `workspace` 和 `environment`。
- 当前状态是什么。
- 已经完成还是失败。

因此列表页不应直接暴露完整 prompt manifest 或全量 transcript。

### 详情页

详情页需要回答：

1. 这个 task 是什么。
2. 它绑定了哪个 `workspace` 和 `environment`。
3. 它的 prompt stack 是怎么组成的。
4. 它运行到哪一步了。
5. 它输出了什么。
6. 它为什么结束。

推荐区块如下：

1. `Task Summary`
2. `Binding Summary`
3. `Prompt Composition Summary`
4. `Runtime Summary`
5. `Output Viewer`
6. `Result / Error Summary`

其中 `Prompt Composition Summary` 在 v1 不需要做成可编辑器，只需要可读、可审计即可。

## 失败语义

v1 的失败语义分成两层：

1. `startup failure`
2. `runtime failure`

### `startup failure`

指真正拉起 Claude Code 前就失败，例如：

- `workspace` / `environment` / `task_profile` 缺失。
- prompt compose 失败。
- launch payload 构造失败。

这类 task 会进入 `failed`，但 runtime summary 必须明确标记“未成功进入 running”。

### `runtime failure`

指 Claude Code 进程已经启动，但运行中异常退出或以非零退出码结束。

这类 task 同样进入 `failed`，并保留：

- 完整输出尾部。
- 退出码。
- failure summary。

### 输出链路失败

如果输出持久化链路不可写，launcher 不应继续把 task 当成健康运行。原因是：

- v1 的核心价值之一就是实时观察和事后回放输出。
- 如果进程仍在跑，但 transcript 已不可持久化，dashboard 实际上已经丧失主要功能。

因此这类情况应视作 harness 自身失败并尽快收口为 `failed`。

## Deferred

以下能力明确延期，不纳入 v1：

- `terminate` / `cancel`
- `retry` / `resume`
- `takeover` / `attach terminal`
- 外部已有 task 的只读接入
- runtime probe 参与 environment prompt 生成
- web 端 prompt 编辑器
- environment / workspace 的创建与编辑界面
- 多 task 编排、复杂 queue、worktree orchestration
- 更高层 workflow / multi-agent pipeline

写清这些 deferred 的目的，是确保 v1 聚焦于“启动一个受控会话并可靠观察它”的最小闭环，而不是提前滑向完整 orchestrator。

## 验证口径

### 1. 后端 contract tests

至少覆盖：

- `PromptComposer` 五层顺序正确。
- task 生命周期转移正确。
- output `seq` / cursor 追加规则正确。
- `startup failure` 与 `runtime failure` 分类正确。

### 2. API tests

至少覆盖：

- `POST /tasks`
- `GET /tasks`
- `GET /tasks/{id}`
- `GET /tasks/{id}/output`
- `GET /tasks/{id}/stream`

同时覆盖 happy path 和失败路径。

### 3. 前端黄金路径验收

至少验证一次完整闭环：

1. 从 web 表单选择已有 `workspace` 和 `environment`。
2. 提交一个 harness task。
3. 页面看到 task 进入 `starting` / `running`。
4. detail 页持续追加 stdout / stderr。
5. task 最终进入 `succeeded` 或 `failed`。
6. 刷新页面后仍能回放已持久化 transcript。

只要这条路径稳定跑通，就可以认为 v1 的控制面闭环成立。

## 推荐实现切片

为了避免实现期再次 scope 膨胀，建议按以下切片推进：

1. `Task registry + lifecycle baseline`
2. `Prompt composition contract + snapshot persistence`
3. `Claude Code launcher + runtime binding`
4. `Output store + replay + SSE`
5. `Task list / detail web surface`
6. `Golden path validation`

这样可以先固定后端事实源和启动路径，再接前端读模型，而不是一上来堆 UI。

## 与现有模块的关系

- `workspace` 与 `environment` 继续作为现有模块存在，本 spec 只规定 task 如何绑定并消费它们。
- 已有 code-server / workspace browser 能力不属于 v1 task harness 的核心 contract，但可以作为后续 detail 页增强能力参考。
- 当前 task-centric dashboard 相关既有文档，尤其 task read model、workspace/session/container summary、dashboard baseline，应被视作本 spec 的上层背景；但 `Task Harness v1` 更聚焦于“启动与监控 Claude Code 会话”这一条闭环。

## 结论

`Task Harness v1` 的正确定位不是完整 orchestrator，而是一个围绕 harness-managed Claude Code 会话建立的薄控制面。

它的最小价值闭环是：

1. 在 web 端基于已有 `workspace` 和 `environment` 启动 task。
2. 在启动前完成可审计的五层 prompt 合成。
3. 在运行中持续持久化并展示 stdout / stderr。
4. 在完成后保留可回放的终态与输出记录。

只要这个闭环稳定成立，后续再往 `terminate`、`retry`、`takeover`、richer metadata 和外部 task 接入扩展，边界就会清晰得多。
