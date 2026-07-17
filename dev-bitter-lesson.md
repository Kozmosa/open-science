# Development Bitter Lessons

这份文档记录在当前 AINRF 开发环境里已经反复踩过、而且会显著拖慢排查与交付效率的坑。目标不是复盘情绪，而是把代价高的经验转成固定检查项。

## 1. 前端部署是“双源”的，先确认浏览器到底在吃哪份静态资源

### 现象
- 代码已修改
- 容器里 `frontend/dist` 也是新的
- 浏览器 UI 仍然是旧的

### 根因
nginx 实际服务的是**宿主机挂载**的 `frontend/dist`，不是容器内 `/opt/ainrf/frontend/dist`。

- 容器内构建产物：给 `ainrf` 容器自己使用
- nginx 对外提供的静态文件：来自宿主机 `frontend/dist`

### 硬规则
前端改动后不要只做：

```bash
docker compose -f deploy/docker-compose.cpu.yml up -d --build ainrf
```

必须做：

```bash
cd frontend && npm run build && cd ..
docker compose -f deploy/docker-compose.cpu.yml up -d --build ainrf
docker compose -f deploy/docker-compose.cpu.yml restart nginx
```

### 部署顺序：前后端配套改动时，先发后端
nginx 挂载的是宿主机 `frontend/dist`，重建 dist 后**立即**对外提供新版前端。如果前端先上线、后端还是旧的，新前端调用旧后端没有的端点（例：新增 `PATCH /tasks/{id}` 重命名接口）会直接 404 / 功能不可用。

配套改动时固定顺序：

1. 先 `docker compose ... up -d --build ainrf`（后端，新端点先就位）
2. 再 `cd frontend && npm run build`（前端，此时后端已能接住新调用）
3. 必要时 `restart nginx`

### 最小验证
- 看 `frontend/dist/index.html` 里的 `index-*.js` hash
- 再看浏览器实际加载的是不是同一个 hash
- 两者不一致时，不要继续怀疑 React/Tailwind/缓存逻辑，先修部署链

## 2. 多租户 Linux 用户隔离下，`ainrf` 默认不能写 tenant 路径

### 现象
- 某些功能看起来“静默失败”
- 某些目录创建、symlink、临时文件读取在 default path 正常，换一个路径就 EPERM/EACCES

### 根因
当前权限模型是：

- 主进程：`ainrf` (uid=1000)
- 任务进程：`sudo -u ainrf_<tenant>`
- tenant home/workspace：tenant 用户自己拥有

这意味着：
- `ainrf` **不能假设自己能写** `/home/ainrf_tenants/<username>/...`
- `ainrf` 创建的文件也**不能假设 tenant 子进程能读**

### 硬规则
1. **tenant 会读取的临时文件**
   - `ainrf` 创建后必须显式 `chmod 0644` 或按需 `chown`
   - 例：MCP config temp file

2. **tenant 空间里的目录/文件/软链**
   - 必须通过 tenant 用户创建
   - 模式：

```python
subprocess.run(["sudo", "-u", tenant_user, "mkdir", "-p", path], ...)
```

3. **不要把 default workspace 正常运行当成权限模型正确**
   - 很多路径之所以不报错，只是因为 entrypoint 预创建了 `workspaces/default`
   - 非 default label、skills 注入、动态 symlink 才会暴露真实权限问题

## 3. “同样是切用户”不代表系统层实现等价

### 现象
- `claude-code` 引擎能跑
- `agent-sdk` 引擎却报 `Operation not permitted`

### 根因
- `claude-code`：`sudo -u tenant ...`
- `agent-sdk` 之前：`subprocess.Popen(user=tenant)` 这条路径底层要 `setuid`

后者依赖 `CAP_SETUID`，在当前容器模型下并不成立。

### 硬规则
只要遇到“切用户执行”的逻辑，不要只看 API 名称，要确认底层到底是：
- `sudo`
- `setuid`
- shell wrapper
- SDK 内部自己的 spawn 机制

只在当前环境里可证明可用的实现上复用，不要因为“语义一样”就替换。

## 4. Browser / DevTools 不可用时，前端排查成本会飙升

### 现象
- 猜 DOM 结构
- 猜 flex 问题在外层还是内层
- 猜浏览器是否还在加载旧 bundle

### 根因
没有真实 DOM、computed style、loaded asset 证据链时，只靠读代码很容易误判。

### 硬规则
前端问题优先级：
1. 先运行 `bash scripts/dev.sh doctor --profile full --browser`，确认 Chrome、MCP 配置和 CDP 链路
2. 再确认当前 session 实际暴露 **chrome-devtools MCP / browser tool**；若未暴露，重启 session
3. 再看实际 DOM、class、computed style、network loaded assets
4. 最后才改代码

### 在当前环境里的额外注意
- snap chromium 是坏的，不要继续围绕它排查
- 当前稳定可用的是 Puppeteer 缓存的 Chrome for Testing
- OMP / Claude 的配置改完后，很多时候**需要重启 session 才会生效**
- headless 不等于“没有真实浏览器”：Chrome 可以通过 CDP 提供 DOM、computed style、Network、focus 和截图证据
- preflight 成功只证明主机工具链可用，不证明当前 agent session 已加载 browser tool

## 5. 配置改了不等于当前 session 生效了

### 现象
- `~/.omp/agent/config.yml` 改了
- `~/.claude/settings.json` 改了
- MCP 或浏览器行为还是旧的

### 根因
这类配置很多只在进程启动时读取一次。

### 硬规则
改完配置后必须明确回答这三个问题：
- 需要重启 **session** 吗？
- 需要重启 **容器** 吗？
- 需要重启 **nginx / 浏览器** 吗？

如果这三个问题没答清楚，不要把“改了配置但没生效”误判为代码问题。

开发栈本身使用 `scripts/dev.sh` 管理，不再通过 `lsof`、`pgrep` 或固定 5173/8000 端口清理未知进程。每个 worktree/profile 使用稳定派生端口和 repo 外状态；端口冲突时先看 `dev.sh status` 和 `dev.sh logs`，不要杀掉不属于当前 manifest 的进程。

## 6. 布局问题先量每一层，不要直接怪最外层容器

### 现象
页面看起来“没撑满高度/宽度”，很容易第一反应就去改 `PageShell`。

### 实际经验
很多问题不是 shell 尺寸错，而是内部某一层：
- 没有 `flex-1`
- 少了 `min-h-0`
- `SectionStack` / `SplitPane` / detail root 按自然内容高度收缩

### 硬规则
排查顺序固定为：
1. `main`
2. `PageShell`
3. page root
4. split/stack/chart/detail root
5. 最后才看更内层业务组件

只要 devtools 可用，就直接量：
- `getBoundingClientRect()`
- `flex-grow`
- `min-height`
- `overflow`

不要靠截图目测猜层级。

## 7. 高成本重建前，先建立证据链

### 现象
为了确认不是缓存问题，直接 `--no-cache` 重建，结果被 Dockerfile 里的外部下载步骤拖几分钟甚至更久。

### 硬规则
在做高成本操作前先验证：
- host `frontend/dist` hash
- 容器内 bundle hash
- 浏览器实际加载的 bundle hash
- 当前 session 是否读取了新配置

只有证据指向“确实是构建缓存/镜像层问题”，再做全量无缓存重建。

## 8. `data?.items[0]` 不是安全访问，空列表和缺字段要分开防

### 现象
- 接口请求成功返回了对象
- 页面还是在 render 阶段直接崩
- 控制台报的是 `Cannot read properties of undefined (reading '0')`

### 根因
`data?.items[0]` 只保护了 `data`，**没有保护 `items`**。

- `data === undefined`：安全
- `data.items === undefined`：仍然会炸

这类问题特别容易出现在：
- query 首帧未完成
- mock 数据不完整
- 后端返回 shape 变化或部分字段省略

### 硬规则
只要是列表首项默认值，一律写成：

```ts
const firstId = data?.items?.[0]?.id ?? ''
```

不要写：

```ts
const firstId = data?.items[0].id ?? ''
```

前者同时覆盖：
- query 未返回
- `items` 字段不存在
- `items` 是空数组

## 9. 前端高频流式性能优化，必须区分“逻辑正确”和“渲染成本”

### 现象
- 功能上没错
- 但 thinking / token delta 一多，详情页就开始频繁重排、重渲染

### 根因
“消息模型正确”不等于“UI 更新粒度合理”。

对高频流式数据，如果每个 delta 都：
- 进 React state
- 触发 message merge
- 触发 markdown / block render

那么即使最终展示是折叠的，也已经白白付出了渲染成本。

### 硬规则
做流式性能优化时，检查顺序固定为：
1. **这个流式更新在折叠态是否根本不该渲染？**
2. **相邻碎片是否可以先在数据层合并成一个逻辑块？**
3. **纯 thinking delta 是否可以短时间批量 flush，而不是逐条 setState？**

先减更新次数，再谈组件 memo。

## 10. 手动验证需要临时 harness，但 harness 必须是“用完即删”的工具

### 现象
- 真实页面数据链路太长
- 想验证高频 streaming / 展开折叠 / 边界状态
- 直接在生产页上做很慢，也不稳定

### 有效做法
临时做一个最小 harness 页面是对的，因为它能：
- 可控地产生高频 delta
- 快速验证 collapsed / expanded / completed 三个状态
- 直接观察“一个逻辑块”是否被维持

### 硬规则
但 harness 只能是**一次性测试工具**：
- 为了验证而建
- 验证完立即删除
- 不把临时页面、临时代码、临时入口留在主分支里

否则它会从“验证工具”退化成“没人维护的灰色功能”。

## 11. 行为变化后，必须重新审计 response schema 的可选性

### 现象
- retry 功能改完
- `pytest tests/` 508 全绿
- 推到 staging 点 retry，直接 `Internal Server Error`（500）

### 根因
`retry_task()` 从“永远新建 task”改成“agent-sdk 复用同一 task”。返回体里的 `archived_task_id` 以前一定有值，新逻辑下 agent-sdk 路径是 `None`。但 schema 没跟着改：

```python
class TaskRetryResponse(BaseModel):
    archived_task_id: str   # ← 非 Optional，但新路径会传 None
```

Pydantic v2 对非 Optional 字段**严格拒绝 `None`**，在构造 response 时抛 `ValidationError` → 500。

### 为什么单测没抓到
service 层单测只验证 `retry_task()` 返回的 `Task` 对象正确，**完全不经过 response schema 序列化**。`None` 路径只有走到“真实 HTTP 响应构造”那一步才会触发，而这一步单测覆盖不到。

### 硬规则
当某个行为从“必然产生 X”变成“条件性产生 X”（或反过来）：

1. **立刻重新审计所有受影响 response schema 的字段可选性**
2. 只要新逻辑下某字段可能为 `None`，类型就写 `X | None`，不要保留旧的 `X`
3. 这种 bug 只能在 staging 用真实 HTTP 请求跑一遍才暴露 —— 新功能的“完整链路验证”不能只靠 pytest

### 最小验证
新功能上线前，至少在 staging 上跑一次“会触发条件分支”的真实请求（本文档的 case：触发 same-task 复用路径），而不是只 curl 一个 happy path。

## 12. structlog 和 stdlib logger 不能混用 kwargs

### 现象
- agent-sdk task retry / follow-up 一律失败
- stderr 报 `Logger._log() got an unexpected keyword argument 'task_id'`
- task 被 `run_task` 的 except 捕获后标 FAILED
- **每次 retry 都重新踩一遍同一颗雷**，task 永久卡死在 failed

### 根因
两处用了 `logging.getLogger()`（**stdlib**），却传了 structlog 风格的关键字参数：

```python
# ❌ 错：stdlib logger 不认这些 kwargs
logger = logging.getLogger(__name__)
logger.warning("session_resume_failed_retrying_fresh", task_id=..., session_id=...)
# → TypeError: Logger._log() got an unexpected keyword argument 'task_id'
```

stdlib `Logger._log()` 只认自己的签名，多传一个 kwarg 就 TypeError。这个异常又被任务循环当成“任务失败”吞掉，于是表现为业务功能挂掉而不是日志层报错。

### 硬规则
传结构化字段前，先确认这个 logger 是哪一种：

```python
# stdlib (logging.getLogger / logging.getLogger(__name__))
#   → 只能用 %-format 位置参数
logger.warning("retry task_id=%s session=%s", task_id, session_id)

# structlog (structlog.get_logger() / 模块级 `log = structlog.get_logger(...)`)
#   → 可以直接传结构化 kwargs
log.warning("session_resume_failed_retrying_fresh", task_id=task_id, session_id=session_id)
```

不要因为“看起来都是记日志”就把 structlog 的调用风格复制到 stdlib logger 上。

### 最小验证
改动涉及日志时，grep 当前文件的 logger 来源：

```bash
grep -nE "logging\.getLogger|structlog\.get_logger|^\s*log\s*=" path/to/file.py
```

确认传参风格和 logger 类型一致。

## 13. 可重配置的全局对象不能保留陈旧实例

### 现象
- 定向测试单独运行通过，完整测试按不同顺序运行却失败
- 日志、指标、配置或 SDK client 看似已重新配置，但仍输出到旧的 sink 或读取旧值
- `capture_logs()`、mock 或临时环境变量只对部分调用生效

### 根因
模块级 logger、client 或 registry 在第一次使用后被缓存。后续全局重配置虽然替换了默认 factory/processor/配置对象，旧实例仍持有旧引用。测试顺序一变，问题便从“偶发”变成稳定失败。

### 硬规则
1. 任何支持运行期重配置的全局设施都必须定义重建或 reset 策略
2. 不要缓存会捕获可替换配置的实例；必须缓存时，要在重配置时显式失效
3. 测试不能只跑单文件：至少覆盖“先配置 A、执行一次、再配置 B”的顺序

### 最小验证
对日志、指标、配置和 SDK 等全局对象，增加跨配置生命周期回归；完整 L1 必须作为最终判定，不能用单文件通过替代。

## 14. 不可信内容的安全边界在最终渲染处，而不是业务正则处

### 现象
- 修复了 URL 路由或 Markdown link token，raw HTML、实体编码或图片属性仍可能绕过
- 业务层已经拒绝若干危险 scheme，但 `dangerouslySetInnerHTML` 仍直接接收生成的 HTML

### 根因
链接重写、token 过滤和 denylist 只能覆盖已知输入形态；HTML parser、浏览器实体解码和 raw HTML 是另一条输入路径。安全性不能依赖业务层“恰好看到了这个 token”。

### 硬规则
1. 任何进入 `dangerouslySetInnerHTML` 的内容，必须在最终 HTML 边界经成熟 sanitizer 清洗
2. URI 使用 allowlist，而不是只维护 `javascript:` 等 denylist
3. sanitizer 必须是直接依赖并锁定版本，不能隐式依赖某个 transitive package 恰好被 hoist

### 最小验证
同一组件至少覆盖普通 HTTPS、相对/in-app 路径、raw HTML、事件属性、危险 URI、非允许 scheme 和实体编码等输入。

## 15. 验证结论必须有终态证据，且不同验证层不能互相替代

### 现象
- 看到进度条大部分为绿点，误以为命令已经通过
- 手动 E2E 正常，就把 deterministic CI、构建或类型检查视为已完成
- 测试清理阶段超时或被人工中止，却被表述为“基本通过”

### 根因
部分日志只说明过程曾推进，不能证明命令以 `exit 0` 结束；单测、L1、staging 和手动验证分别覆盖代码、可重复集成、部署装配和真实交互，证据维度不同。

### 硬规则
1. 每个验证结论都记录命令、最终 exit code、范围和失败/超时状态
2. timeout、hang、runner 被中止一律记为未完成，不得折算为通过
3. 定向测试、L1、staging 和手动 E2E 分别报告，禁止用其中一个替代另一个

### 最小验证
工具会话分段输出时，保留 session id 并轮询到终态；提交或发布说明只引用已完成的那一层证据。

## 16. 前端命令的工作目录是构建契约

### 现象
`npm --prefix frontend run test:run -- frontend/__tests__/...` 报“找不到测试”，但文件实际存在。

### 根因
`--prefix frontend` 会让 npm script 在 `frontend/` 内执行；传给 Vitest、TypeScript、Vite 的相对路径都以这个目录为根，不是仓库根。

### 硬规则
1. 前端命令统一使用 `npm --prefix frontend ...` 或明确 `cd frontend`
2. 使用 `--prefix` 时，测试过滤路径写为 `__tests__/...` 或 `src/...`
3. 命令失败先核对 cwd 与过滤路径，再判断为测试发现或代码问题

## 17. package override、直接依赖和 lockfile 必须一致

### 现象
新增直接依赖后，`npm install --package-lock-only` 因 `EOVERRIDE` 失败，或本机可 import、CI 的 `npm ci` 却失败。

### 根因
`package.json` 的直接依赖、`overrides` 和 lockfile 共同定义可安装图。范围版本与精确 override 不一致时，npm 会拒绝解析；本机被 hoist 的 transitive package 又会掩盖这种问题。

### 硬规则
1. 新增依赖前先检查 `overrides`、lockfile 中的已有版本和许可边界
2. 被精确 override 的直接依赖使用相同精确版本，除非同时有意调整 override
3. 依赖变更后必须验证 lockfile 安装，而不是只验证本机 `node_modules`

### 最小验证
运行 `npm --prefix frontend install --package-lock-only --ignore-scripts`，再运行 lint、测试和 production build。

## 18. Worktree 清理必须同时审计 Git 图、工作区状态和协作状态

### 现象
- PR 已 squash merge，但 feature commit 不是 `master` 的祖先
- 分支看似已合并，worktree 中却仍有未提交文件
- locked worktree 可能仍属于活跃会话，旧基线上的同名 worklog 又会在 rebase 时发生 add/add 冲突

### 根因
Git 提交图只描述已提交历史；squash merge、未提交改动、worktree lock 和并发工作记录属于不同状态面，单看 `git branch --merged` 会误判。

### 硬规则
1. 清理前同时检查 PR 状态、`master` 内容、`git worktree list --porcelain`、每个 worktree 的 `git status` 与活跃协作会话
2. 对已 merge 的 temporary worktree，先确认干净再 unlock/remove；不触碰未知或活跃的 locked worktree
3. 同名 worklog 冲突时保留主线全部历史并追加分支记录，绝不覆盖或丢弃另一侧日志

### 最小验证
合并前跑 `git diff --check`、合并后核对 `master...origin/master`；清理后再检查目标 worktree、临时分支和远程引用均已消失。

## 19. 建议固定成每次开发的检查清单

### 前端改动前后
- [ ] devtools/browser tool 可用
- [ ] `scripts/dev.sh doctor --browser` 已确认 Chrome/MCP/CDP；配置变化后已重启 session
- [ ] 当前工作使用 worktree/profile 隔离的 `scripts/dev.sh`，没有复用 production/shared staging
- [ ] 确认浏览器加载的 bundle hash
- [ ] 宿主机 `frontend/dist` 已重建
- [ ] nginx 已重启
- [ ] 前后端配套改动时，先发后端再发前端（见 §1）
- [ ] `npm --prefix frontend` 的测试过滤路径是否以 `frontend/` 为根（见 §16）
- [ ] Markdown/HTML/富文本是否在最终渲染边界清洗，且 URI 为 allowlist（见 §14）

### 多租户/权限改动前后
- [ ] 明确文件/目录是谁创建的
- [ ] 明确最终由谁读取/写入
- [ ] 跨用户边界时是否做了 chmod/chown
- [ ] tenant 路径内创建动作是否通过 `sudo -u tenant`

### 配置改动后
- [ ] 是否需要重启 session
- [ ] 是否需要重启容器
- [ ] 是否需要重启 nginx / 浏览器

### 行为 / 接口改动后
- [ ] 行为从“必然产生 X”变成“条件性产生 X”了吗？是 → 审计 response schema 可选性（见 §11）
- [ ] 改动涉及日志吗？是 → 确认 logger 是 stdlib 还是 structlog，传参风格匹配（见 §12）
- [ ] 单测绿之后，是否在 staging 用真实 HTTP 请求跑过会触发条件分支的路径？（见 §11）
- [ ] 是否改动了可重配置的全局对象？是 → 覆盖重配置顺序与 reset 行为（见 §13）
- [ ] 每项验证是否已有最终 exit code 和对应验证层的证据？（见 §15）

### 依赖 / Git worktree 改动后
- [ ] 新依赖是否与 `overrides`、lockfile 一致，并已验证可安装？（见 §17）
- [ ] 清理前是否同时审计 PR、Git 图、dirty 状态、lock 和活跃会话？（见 §18）

如果未来再踩到类似坑，优先补这份文档，而不是把经验散落在聊天记录里。
