# AINRF Settings Page Baseline 设计

日期：2026-04-23

## 背景

当前 AINRF 前端已经具备 `Terminal`、`Tasks`、`Workspaces`、`Containers` 四个主要页面，以及 `/settings` 这一条仍指向占位页的导航入口。

现状有两个与设置相关、已经明确下来的事实边界：

1. 前端访问后端所使用的 token 继续通过构建时环境变量 `VITE_AINRF_API_KEY` 注入，不进入本轮设置页范围。
2. 第一版设置页只做浏览器本地持久化，不引入后端设置 API，也不追求跨浏览器或跨设备同步。

同时，当前前端已经存在若干天然适合由设置页接管的默认行为：

- 根路由 `/` 当前固定跳转到 `/terminal`。
- 环境选择逻辑已经通过 `localStorage` 记忆当前 environment，但缺少统一设置入口。
- `Tasks` 页的创建表单目前总是从空值开始输入，尚未支持按 project/environment 预填 `title` 与 `task_input`。
- 当前 task workdir 由 `workspace.default_workdir` 或 `environment.default_workdir` 解析，前端没有 task-level workdir override。
- 终端展示参数当前写死在 `TerminalSessionConsole` 内部，没有可配置的字号入口。

因此，这一轮设置页的目标不是成为“运行时配置中心”，而是把前端默认行为收拢为一个最小、稳定、可落地的设置基线。

## 目标

本次设计要达成以下目标：

1. 为现有 `/settings` 路由提供一个可替代占位页的真实设置页面基线。
2. 明确区分全局 UI 偏好与当前项目下、按环境分组的操作默认值。
3. 只依赖浏览器本地存储完成持久化，不引入后端用户设置模型。
4. 让设置结果直接影响根路由跳转、环境默认选择、任务创建表单预填和终端显示行为。
5. 为后续扩展多项目设置保留数据结构余地，但第一版不做 project picker。

## 非目标

本次设计不做以下事情：

- 不把 API token、密钥、SSH 凭据或其他敏感信息放入设置页。
- 不接入后端设置接口、用户 profile API 或服务端偏好持久化。
- 不实现多浏览器同步、导入导出、云端备份或分享设置。
- 不把设置页扩展成 environment 编辑器、workspace 编辑器或 task template 管理器。
- 不在第一版引入复杂终端主题、快捷键映射、布局编排或高级通知系统。
- 不在第一版实现多项目切换；“项目级设置”只针对当前固定 project 上下文。

## 方案比较

### 方案 A：单页双分区设置（采用）

做法：

- 在一个设置页内分成 `General Preferences` 与 `Project Defaults` 两个主区块。
- 全局 UI 偏好统一保存。
- 当前项目的操作默认值按环境分卡片保存。

优点：

- 与“全局 UI 偏好 + 按项目/环境分组的操作默认值”这一用户要求完全对齐。
- 当前范围不大，但结构已经足够清楚，不需要为了分层再引入 tab。
- 能直接映射现有环境选择和任务创建表单逻辑。

缺点：

- 页面实现比纯长表单略复杂。

### 方案 B：扁平长表单

做法：

- 把所有设置放到一个长表单里，仅用标题分节，不区分环境级编辑卡片。

优点：

- 首版实现最快。

缺点：

- 环境级默认值一多就会变乱。
- 难以表达“同一 project 下，每个 environment 有不同任务默认值”的边界。

### 方案 C：标签页设置

做法：

- 使用 `General` / `Project Defaults` 两个 tab 分离设置面。

优点：

- 视觉结构清楚。

缺点：

- 对当前最小范围来说偏重。
- 会额外引入 tab 状态与页面组织复杂度，但实际字段量还不值得。

## 采用方案

采用方案 A：单页双分区设置。

核心原则是：

- 设置页只管理前端默认行为，不管理敏感运行时凭据。
- 全局偏好与项目/环境默认值分层，不混用一套字段。
- 项目级默认值先绑定到当前固定 project，但数据结构保留未来扩展到多个真实 project 的余地。
- 环境级任务默认值只作为前端覆盖层存在，不回写现有 environment 实体。

## 信息架构

设置页由两个主区块组成。

### 1. `General Preferences`

这一组保存全局 UI 偏好，对整个 WebUI 生效。

第一版最小字段：

- `defaultRoute`
- `terminal.fontSize`

其中：

- `defaultRoute` 允许用户选择根路由 `/` 默认跳转到 `Terminal`、`Tasks`、`Workspaces` 或 `Containers`。
- `terminal.fontSize` 用于控制终端组件字号。

第一版不纳入但可后续追加的字段：

- 终端主题。
- 快捷键映射。
- 通知开关。
- 页面列表轮询频率。

### 2. `Project Defaults`

这一组只针对当前固定 project 上下文。

页面结构建议分成两层：

1. 顶部的 `defaultEnvironmentId` 选择区。
2. 下方按 environment 展开的默认值卡片列表。

第一版最小字段：

- `defaultEnvironmentId`
- `environmentDefaults[environmentId].titleTemplate`
- `environmentDefaults[environmentId].taskInputTemplate`

边界如下：

- `defaultEnvironmentId` 表示当前 project 在前端里的默认运行环境。
- 每个 environment 卡片只编辑该环境下的新建 task 默认标题与默认 task input，不影响其他 environment。
- 第一版不新增 task-level `workingDirectory` 字段，因为当前后端 `TaskCreateRequest` 并不接受前端传入 workdir override，task 实际 workdir 由 `workspace.default_workdir` 或 `environment.default_workdir` 解析。
- 如果某个 environment 没有显式配置，则回退到内置默认空值。

## 数据模型与持久化

第一版由前端维护单一的浏览器本地设置文档。

建议结构如下：

```ts
interface WebUiSettingsDocument {
  version: 1;
  general: {
    defaultRoute: 'terminal' | 'tasks' | 'workspaces' | 'containers';
    terminal: {
      fontSize: number;
    };
  };
  projectDefaults: {
    default: {
      defaultEnvironmentId: string | null;
      environmentDefaults: Record<
        string,
        {
          titleTemplate: string;
          taskInputTemplate: string;
        }
      >;
    };
  };
}
```

设计理由如下：

- `general` 与 `projectDefaults` 分层，避免全局偏好和操作默认值混写。
- 当前 project 固定写作 `default`，让第一版不必引入 project picker。
- `environmentDefaults` 明确按 `environmentId` 建索引，防止跨环境串值。
- 文档带 `version` 字段，便于未来调整本地存储结构时做兼容和回退。

### 存储位置

- 使用单一 `localStorage` key 保存完整设置文档。
- 当前已有的 `selected-environment-id` 存储逻辑应被新设置文档统一接管，避免两个来源并存造成优先级混乱。

### 默认值

第一版建议默认值如下：

- `general.defaultRoute = 'terminal'`
- `general.terminal.fontSize = 13`
- `projectDefaults.default.defaultEnvironmentId = null`
- 所有 environment 的 `titleTemplate` / `taskInputTemplate` 默认空字符串

## 行为规则

### 根路由跳转

- 应用进入 `/` 时，不再固定跳转 `/terminal`。
- 路由层先读取 `general.defaultRoute`，再跳转到对应页面。
- 若本地设置缺失或无效，则回退到 `terminal`。

### 环境默认选择

当前 `useEnvironmentSelection` 里已经有一套优先级逻辑：

- project default reference
- remembered local choice
- localhost seed
- first available environment

第一版设置页接入后，应调整为：

1. 设置页中的当前项目默认环境。
2. 当前会话或最近一次显式用户选择。
3. seed environment。
4. 第一个可用 environment。

约束如下：

- 设置页控制的是“项目级默认环境”，高于临时 remembered local choice。
- 如果设置中记录的 environment 已不存在，应自动回退而不是报错阻断页面。

### 任务创建表单预填

`Tasks` 页创建 task 表单初始化时，应读取：

- 当前固定 project
- 当前选中的 environment
- 对应 environment 的默认标题与默认 task input

行为规则：

- 只有在表单首次进入或用户主动点击 reset 时，才从设置默认值重新灌入。
- 用户在表单里临时修改内容，不应被设置系统在编辑过程中反复覆盖。
- 切换 environment 时，可以重新加载目标 environment 的默认值。
- 第一版不在 task 表单里新增 workdir override；现有“Default workdir”继续只是只读展示当前 workspace 的默认工作目录。

### 终端显示偏好

`TerminalSessionConsole` 当前将 `fontSize = 13` 等展示参数写死在组件内部。

第一版设置接入后：

- `fontSize` 改为读取 `general.terminal.fontSize`。
- 第一版不把“自动换行”作为可承诺设置项写入基线。当前前端使用的 `xterm@5.3.0` 公开可配置项明确支持 `fontSize` 等外观参数，但没有稳定、直接的用户级 wrap 开关；终端换行仍以底层 PTY / xterm 自身行为为准。
- 第一版只允许少量稳定显示项进入设置页，不扩展到主题、配色和键位层。

### 个人终端工作台一致性

当前 `DashboardPage` 上的 personal terminal bench 也复用 `TerminalSessionConsole`，因此全局终端显示偏好应同时作用于：

- `Terminal` 页里的 task output / replay terminal。
- `Dashboard` 页里的 personal terminal bench。

第一版不引入“task terminal”和“personal terminal”两套独立显示配置，避免设置语义分裂。

## 页面交互设计

### 保存策略

设置页第一版不做自动保存，改为按分区显式保存：

- `General Preferences` 保存按钮只提交全局 UI 偏好。
- `Project Defaults` 顶部保存默认环境。
- 每个 environment 卡片有自己的保存按钮。

这样做的原因是：

- 全局与局部配置的修改范围不同。
- environment 级默认值天然适合局部保存与局部重置。
- 避免一个长页上的任意字段变动都触发整页持久化。

### 重置策略

所有设置都支持局部 `Reset`：

- `General Preferences` 重置回内置默认值。
- `Project Defaults` 的默认环境可单独清空。
- 每张 environment 卡片只重置该环境的 `titleTemplate`、`taskInputTemplate`。

### 损坏回退

如果本地设置文档损坏、字段缺失或版本不兼容，应采用以下策略：

1. 静默回退到默认值。
2. 不阻断应用主流程。
3. 在设置页顶部显示轻量提示，说明当前已回退到默认配置。

## 第一版范围冻结

### Must-have

- 可配置根路由默认跳转目标。
- 可配置终端字号。
- 可配置当前项目的默认环境。
- 可按 environment 配置 task 默认标题与默认 task input。
- 所有配置只保存在浏览器本地，并在刷新后继续生效。

### Deferred

- API token 管理。
- 后端用户设置 API。
- 多项目切换与真实 project picker。
- 多浏览器同步。
- 导入导出。
- 终端主题、自动换行开关、快捷键映射、布局预设。
- 更细粒度的轮询频率与通知设置。

## 对现有实现的影响约束

第一版应优先复用现有前端结构，不为设置页引入过度抽象。

需要直接接入的现有表面包括：

- `frontend/src/App.tsx` 的根路由跳转逻辑。
- `frontend/src/components/environment/useEnvironmentSelection.ts` 的环境解析优先级。
- `frontend/src/pages/TasksPage.tsx` 的创建表单默认值灌入逻辑。
- `frontend/src/components/terminal/TerminalSessionConsole.tsx` 的终端显示参数。
- `frontend/src/components/terminal/TerminalBenchCardView.tsx` 与 `frontend/src/pages/DashboardPage.tsx` 的 personal terminal bench 路径。
- `frontend/src/i18n/messages.ts` 的设置页文案和字段标签。

实现时不应：

- 回写后端 environment record。
- 新增设置专用后端 schema 或路由。
- 让 `/settings` 依赖 runtime telemetry 才能工作。

## 验收口径

第一版至少满足以下验收标准：

1. 刷新页面后，本地设置仍然生效。
2. 修改默认首页后，从 `/` 进入应用会跳转到目标页面。
3. 修改当前项目默认环境后，`Tasks`、`Workspaces`、`Terminal` 与 `Dashboard` 上的共享环境选择逻辑按新默认工作。
4. 修改某个 environment 的任务默认值后，在该 environment 下打开 `Tasks` 创建表单可以看到预填值，切换到其他 environment 不会串值。
5. 修改终端字号后，task terminal 与 personal terminal bench 都会一致更新显示。
6. 本地设置文档损坏或被手工删改后，应用仍能正常打开并回退到默认值。

## 后续实现建议

建议把实现拆成以下几个原子工作批次：

1. 建立 settings document、读写 hook 和默认值回退逻辑。
2. 用真实设置页替换 `/settings` 占位页，并接入全局偏好保存。
3. 接入默认首页与终端显示偏好。
4. 接入项目默认环境与按 environment 的任务默认值。
5. 补齐前端测试，覆盖持久化、回退和跨环境不串值。

## 结论

AINRF 设置页第一版应被定义为“前端默认行为控制面”，而不是运行时配置中心。

它的核心价值不是存更多字段，而是把已经散落在根路由、环境选择、任务创建和终端展示中的默认行为统一收口为一个稳定、最小、仅本地持久化的设置基线，并为后续多项目扩展保留明确的数据边界。
