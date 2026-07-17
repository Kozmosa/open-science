---
aliases:
  - Frontend Client Deferred Acceptance
tags:
  - openscience
  - frontend
  - acceptance
  - deferred
---

# Frontend 客户端延期验收清单

本清单记录 F1–F10 的真实浏览器验收状态。2026-07-16 已在 headless Chrome for Testing + chrome-devtools MCP 会话中完成首轮 DOM、computed style、Network、focus、响应式和 production preview 检查，并据此修复 Sheet 焦点恢复、窄屏 Task 命中区域、Command combobox 名称、Appearance 保存文案与 Shell label-in-name。以下仅勾选已有终态浏览器证据的项目；未完整覆盖的权限组合、破坏性 mutation、长轮询边界、reduced-transparency、高缩放与大数据交互继续 deferred，不以 Vitest、HTTP smoke、legacy Playwright、Docker、shared staging 或 L2 代替。

## 验收环境记录

- [x] 先执行 `bash scripts/dev.sh doctor --profile full --browser`，记录 Chrome、Protocol、CDP 和 MCP config 结果。
- [x] 若配置存在但当前会话没有 browser tool，重启 Codex/OMP/Claude session 后再开始验收。
- [x] 记录客户端版本、操作系统、浏览器与窗口尺寸。
- [x] 记录验收 commit SHA，确保浏览器加载的 bundle hash 与该 commit 构建产物一致。
- [x] 确认使用独立测试用户，避免覆盖真实用户的 settings、sidebar 与卡片顺序偏好。
- [x] 保存失败项的 DOM、computed style、Network/Console 证据；不要仅用截图判断根因。

## F1 主题、字体与品牌

- [ ] 未认证首帧固定为 light，认证完成前不读取或闪现用户主题。
- [ ] 认证后在受保护 Shell 首次可见绘制前应用用户的 light/dark/system 设置，无二次闪烁。
- [ ] system 跟随操作系统主题实时切换，注销或切换用户后不串用设置。
- [ ] light/dark 下官方语义 token 的正文、弱化文本、边框、状态色与焦点环对比度可读。
- [x] Noto Sans 拉丁子集 400/500/600/700 均从本地资产加载，实际 computed font-weight 正确。
- [ ] 中文走系统字体，等宽内容走系统 monospace fallback。
- [x] Network 中没有 Google Fonts、preconnect 或其他运行时字体请求。
- [x] favicon、登录页与 Shell 品牌均显示 Open Orbit SVG，无旧品牌残留或损坏资源。

## F2 Overlay 与基础组件

- [ ] Dialog、ConfirmDialog、Sheet 打开后焦点进入浮层，Tab/Shift+Tab 被圈闭，Escape 关闭，关闭后恢复到触发器。
- [ ] DropdownMenu、Popover、Select、Command 可全键盘打开、移动、选择与关闭，读屏名称和状态完整。
- [ ] Toast 在成功、警告、失败场景可见且不抢走当前输入焦点。
- [ ] icon-only Button 有可访问名称；loading 前后尺寸稳定，重复提交被阻止。
- [ ] Checkbox、Radio、Switch、Tabs、FormField 的 label、错误信息、disabled 与 focus-visible 状态正确。
- [ ] 窄屏 Sheet 中的菜单、滚动和关闭路径没有嵌套浮层焦点丢失。

## F3 AppShell 与响应式导航

- [x] 宽屏展开侧栏、宽屏折叠侧栏、中等宽度和窄屏 Sheet 四种导航形态均可用。
- [ ] 侧栏偏好按 user ID 隔离；切换用户不继承另一用户的折叠状态。
- [x] Workspace Browser 不出现在一级导航，但 Command Palette 与深链仍可进入。
- [ ] 管理员专属路由只向管理员显示，普通用户直接访问时安全回退。
- [x] Command Palette 的英文关键词、当前语言标签、键盘选择与关闭焦点恢复正确。
- [ ] TopBar 不显示页面标题；检查 computed style 的 blur、实色 fallback 与 reduced-transparency 行为。
- [ ] main、PageShell、页面 root、SplitPane/SectionStack 的高度、`min-height` 与 overflow 边界正确，无双滚动条。

## F4 Resources

- [ ] 页面可见时按策略刷新；切到后台后暂停；重新可见立即刷新一次。
- [ ] last successful time、stale、partial、全局失败保留旧数据与单 Environment 失败隔离均符合状态。
- [ ] 三列/两列/单列布局中卡片尺寸稳定，拖拽后顺序只影响当前用户。
- [ ] 资源卡 loaded assets、长进程名、空数据和大量 Environment 下滚动正常。

## F5–F6 Task 流程与工作台

- [ ] global/project/workspace 三类 TaskCreateFlow 的来源锁定、Workspace 可执行筛选和 Environment 只读展示正确。
- [ ] 无可执行 Workspace 时注册/关联引导可达；提交 payload 不含独立 `environment_id` 或 legacy secret override。
- [ ] `/tasks?task=&drawer=` 的 details/attempts/context/closed 历史、刷新和浏览器前进后退正确；旧 `sidebar` 参数被规范化。
- [ ] 正常 stream 下不出现 15 秒轮询；断线或无 stream 且页面可见时才启用有界刷新。
- [ ] Attempt trigger、状态、时间、成本、Context Version 与 Runtime Session 摘要和长内容滚动正确。
- [ ] archive/unarchive/cancel/retry/move/fork 的菜单、确认、成功反馈与失败恢复完整。
- [ ] archived、cancelled、failed、launch_unknown 和各 stopped 状态视觉与动作权限明确区分。
- [ ] owner/admin/Project archived 条件下隐藏或禁用的执行动作与后端 projection 一致。
- [ ] 宽屏三栏、任务列表收缩、Drawer 打开和窄屏完整流程无内容遮挡。

## F7 Workspace Registry

- [x] Environment、canonical path、Git 状态、owner、Project links、Task 数、最近活动与执行原因均与 API 一致。
- [ ] Environment → path → label/context → attach/Primary 注册流程可全键盘完成。
- [x] “已关联但不可执行”与“可用于新 Task”的视觉和文案不混淆。
- [ ] 非 owner 不显示修改/注销动作；注销确认明确不删除磁盘目录，完成后文件仍存在。
- [ ] Workspace 详情进入文件浏览、终端和锁定来源 TaskCreateFlow 的深链参数正确。

## F8 Project 与 Context

- [ ] `/projects?project=&tab=&view=` 在刷新、前进后退和分享链接后保持相同视图。
- [ ] Overview/Tasks/Workspaces/Context/Settings 五标签的 DOM 与滚动边界稳定。
- [ ] Task list/关系图切换、relationship type、React Flow 拖拽和布局重置正确。
- [ ] attach/detach/set/replace Primary 的权限、解释和确认路径完整；无 Workspace 时禁止创建执行 Task。
- [ ] Draft、Active Version、历史、长 diff、Candidates accept/reject 与 publish 的焦点和错误反馈正确。
- [ ] viewer/editor/can_publish 成员管理只接受明确 user ID；default Project 永久无法 Archive。

## F9 Literature

- [ ] URL 中 section/view/topic/category/paper 在刷新和浏览器历史中稳定恢复。
- [ ] 紧凑论文条目在无 hover 条件下仍可完成已读、保存、详情与转研究任务。
- [ ] DetailDrawer 的版本、长摘要、用户状态、Task links 和焦点恢复正确。
- [ ] check/summary/intent 只在 active 状态按 5/10/20/30 秒轮询，进入终态立即停止。
- [ ] Literature Task payload 受限且 pending intent 在页面刷新后按 idempotency key 恢复。
- [ ] 大量论文、多个 topic badge、窄屏筛选和抽屉滚动没有布局溢出。

## F10 Today

- [x] `/today` 只读取 Overview Snapshot；页面加载和手动刷新不触发 arXiv、LLM、detect 或运行时动作。
- [ ] Attention 永远首位且不可拖动/隐藏；其他四卡排序按 user ID 隔离并在刷新后保持。
- [ ] 五类卡片分别正确显示 cutoff、ok/stale/partial/failed 与 error summary。
- [ ] 新用户无持久化数据时只显示起步卡，不显示五张空壳卡。
- [ ] 手动刷新复用稳定 job ID，按 1/2/4/8/10 秒查询；终态立即停止，60 秒后停止自动查询。
- [ ] settings v5 默认 Today；旧合法默认入口保持；缺失/非法入口迁为 Today。
- [ ] Overview capability 不可用且偏好为 Today 时，`/` 临时进入 Tasks，偏好本身不被改写。
- [ ] 桌面、窄屏和高缩放下五卡 DOM 顺序、卡片高度、拖拽手柄和页面滚动正确。

## 完成记录

每次客户端验收后在对应条目勾选，并在本节追加日期、commit SHA、浏览器、结论与未解决问题。browser preflight、HTTP smoke 或 production preview 不能替代这些交互证据；所有未勾选项继续视为 deferred。

### 2026-07-16 首轮 Chrome DevTools 验收

- 环境：Linux headless，Chrome for Testing `149.0.7827.22`，CDP Protocol `1.3`；窗口覆盖 `1440×900`、`900×800`、`390×844`。验收使用 marker-owned `full` fixture 的 `frontend-owner`，未连接 Docker、shared staging、production 或 legacy Playwright。
- 代码与产物：dev 模式完成 HMR/real API 检查；production preview 实际加载 `/assets/index-*.js` 等 hashed assets，无 `/src/` 或 `@vite` 请求。Settings 曾确认 backend/frontend build commit 一致；最终浏览器修复基线为 `3b38301` 及其祖先提交。
- 安全：认证后 Network 不再请求 `/api/settings/codex-defaults`；user-scoped settings 未含 host Codex config/auth 字段。验收期间为避免把随机密码写进工具参数，仅在 synthetic fixture 中临时切换测试密码，并在 dev/preview 两次检查后恢复 credentials 文件中的原密码。
- 主题与资产：未认证首屏为 light；`system` 在模拟 dark/light media query 时实时切换 `data-osci-theme` 与 body 背景，最后恢复 light。四个 Noto Sans 字重均由本机 Vite/preview 资产加载，无外部字体或资源请求；登录品牌与 favicon 的 Open Orbit SVG 正常。
- Shell 与 overlay：宽屏侧栏可在 `56px`/`240px` 间切换，中宽保持 collapsed rail，窄屏使用 Sheet；移动导航与 Task inspector 均验证 focus trap、Escape 和触发器焦点恢复。TaskCreateFlow Dialog 验证 Shift+Tab 圈闭与关闭后恢复到 New task。
- Tasks：窄屏 list-first → detail → inspector 路径可用；修复后 Task detail 高度约 `537.5px`，textarea 不再覆盖 header，`Task actions`/`Show details` 中心 hit-test 命中自身。桌面三栏在 `1440×900` 下显示两个 separator、`320px` 左右栏且无横向溢出。
- 路由与页面：Command Palette combobox 有名称，`browser` 英文关键词通过 Enter 进入 `/workspace-browser`；Projects Context、Workspaces projection、Literature all/detail、Resources 与 Today 的主要 DOM、URL 参数和滚动边界可见，页面切换期间未见 4xx/5xx 或 JS console error。
- Today：五卡 DOM 顺序为 attention、progress、literature、continue、resources；手动 refresh 复用返回的 job URL并进入 `succeeded`，随后重新读取 snapshot。Network 只出现 Overview snapshot/refresh/job 请求，没有 arXiv、LLM 或 environment detect。
- fault profiles：每次均先 down/reset 并用相同 profile 启动。`latency` 为约 `0.765s` 且带 `latency:0.75s`；`transient` 同一路径首次 `503`、第二次 `200`；`resources` 仅 `/resources` 与 `/tasks/token-usage` 返回 `503`，Project/health 正常；`offline` 保留 health/auth 路径，领域 Project 返回 `503/offline:unavailable`。
- preview 与审计：`dev.sh smoke --mode preview` exit 0，真实登录、Today 五卡、Settings 文案与 build metadata 可用。最终 Lighthouse snapshot 为 Accessibility `100`、Best Practices `100`、SEO `100`，label-in-name 已清零；唯一失败项是私有认证控制面刻意 no-crawl 的 `llms.txt` 不符合通用 agentic crawling 建议，不作为产品缺陷处理。
- 继续 deferred：多用户 sidebar/card preference 隔离、admin/viewer/editor 权限矩阵、ConfirmDialog/Popover/Select/Toast 全组合、真实 mutation 成功/失败恢复、长轮询 60 秒边界、background visibility refresh、reduced-transparency、高缩放、大列表/DnD 和所有破坏性注销/归档流程。Chrome 仍报告非认证 Settings 控件缺少 `id/name` 的 autofill 建议，但当前 Lighthouse Accessibility 为 100；后续若统一增强 FormField autofill contract，应另开独立批次。
