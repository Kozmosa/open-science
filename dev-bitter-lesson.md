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
1. 先保证 **chrome-devtools MCP / browser tool 可用**
2. 再看实际 DOM、class、computed style、network loaded assets
3. 最后才改代码

### 在当前环境里的额外注意
- snap chromium 是坏的，不要继续围绕它排查
- 当前稳定可用的是 Puppeteer 缓存的 Chrome for Testing
- OMP / Claude 的配置改完后，很多时候**需要重启 session 才会生效**

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

## 11. 建议固定成每次开发的检查清单

### 前端改动前后
- [ ] devtools/browser tool 可用
- [ ] 确认浏览器加载的 bundle hash
- [ ] 宿主机 `frontend/dist` 已重建
- [ ] nginx 已重启

### 多租户/权限改动前后
- [ ] 明确文件/目录是谁创建的
- [ ] 明确最终由谁读取/写入
- [ ] 跨用户边界时是否做了 chmod/chown
- [ ] tenant 路径内创建动作是否通过 `sudo -u tenant`

### 配置改动后
- [ ] 是否需要重启 session
- [ ] 是否需要重启容器
- [ ] 是否需要重启 nginx / 浏览器

如果未来再踩到类似坑，优先补这份文档，而不是把经验散落在聊天记录里。
