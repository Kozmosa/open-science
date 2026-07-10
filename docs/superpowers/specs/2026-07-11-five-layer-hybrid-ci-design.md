# OpenScience 五层混合 CI 设计

**Goal:** 在开发与生产共用同一台服务器的约束下，建立低延迟、可复现、不会误伤生产的五层混合 CI；本轮先完整落地 L0 开发内循环与 L1 确定性门禁，并为后续本机容器集成、深度验证和发布验收定义稳定边界。

**Architecture:** GitHub-hosted runner 只执行不依赖 Docker、外部服务和设备状态的确定性检查；可信本机控制器负责容器、Linux 多租户、SSH/tmux 和候选发布验证。所有层级复用仓库内统一命令入口，未实现的层级必须明确失败或保持不可调用，禁止用“绿色占位”制造假信号。

**Tech Stack:** Bash, Python 3.13, uv, pytest, Ruff, ty, Node.js 22, npm, Vitest, Vite, GitHub Actions, Docker Compose（后续层级）

---

## 1. 设计原则

1. **信号真实**：命令名必须与实际触达的系统边界一致。进程内 ASGITransport 测试不得称为 staging 测试。
2. **同一入口**：agent、本地开发者和 GitHub Actions 调用同一组仓库脚本，避免本地与远端行为漂移。
3. **资源有界**：后端并行度固定为安全默认值，不根据宿主机 112 个线程自动扩张；重型层级必须进入本机队列。
4. **失败可定位**：每个 lane 独立退出并保留原始日志；禁止全局 rerun 掩盖首次失败。
5. **产物一致**：后续发布层级必须验收精确 SHA 的不可变镜像和前端 artifact，而不是可变 `latest` 或共享 `dist`。
6. **生产优先**：公开 PR 不得在生产同机的 Docker daemon 上执行；本机 CI 只接受可信维护者授权的 SHA。

## 2. 五层模型

| 层级 | 名称 | 运行位置 | 触发方式 | 主要边界 | 本轮状态 |
|---|---|---|---|---|---|
| L0 | Agent / developer inner loop | worktree 本地 | 每个修改批次、显式命令 | 快速静态检查与高价值快速测试 | 实现 |
| L1 | Deterministic gate | GitHub-hosted + 本机 | PR、push、pre-push/显式命令 | 完整静态检查、后端测试、前端 lint/build/Vitest、文档构建 | 实现 |
| L2 | Container integration | 本机隔离 CI cell | 可信待合并 SHA | 最小 backend + nginx + fake dependencies + browser/API contract | 设计 |
| L3 | Deep system verification | 本机串行 | 手动或夜间 | race、backup/restore、tenant UID/GID、SSH/tmux、完整 runtime、性能 | 设计 |
| L4 | Release acceptance | 固定 release staging + production | 候选发布、人工批准 | 同一 artifact 的 staging 验收、部署、只读 post-smoke 与回滚 | 设计 |

L0/L1 不启动 Docker，不访问外部 LLM、搜索服务或生产端口。L2–L4 由后续计划实现，并使用独立的运行身份、队列和资源限制。

## 3. L0：开发内循环

### 3.1 目标

- 在普通 agent 修改批次内提供 10–60 秒反馈。
- 不依赖全机共享服务。
- 默认最多使用 8 个 pytest worker 和 4 个 Vitest worker，可通过显式环境变量降低。
- 避免执行已知串行敏感的 concurrency/db-race 测试。

### 3.2 命令契约

统一入口：

```text
bash scripts/ci.sh l0
```

L0 包含：

- Ruff lint（仅 Python 产品与测试目录）。
- Ruff format check。
- 后端 fast marker 集合，排除 `concurrent` 与 `db_race`。
- frontend lint。
- frontend Vitest，排除独立 perf 目录。

L0 不包含：

- `ty check` 全量分析。
- frontend production build。
- 后端完整测试。
- Playwright、Docker、staging 或性能审计。

如果某次变更只涉及单一子系统，开发者仍可直接调用 `scripts/test.sh <lane>` 或对应 npm 命令；L0 是跨子系统修改后的统一快速收口入口。

## 4. L1：确定性门禁

### 4.1 目标

- 在 GitHub-hosted runner 和本机产生一致结果。
- 无 Docker、无外部网络服务依赖、无 GPU 依赖。
- 作为未来 master required check 的稳定基础。

### 4.2 后端 lane

```text
bash scripts/ci.sh l1-backend
```

顺序执行：

1. `ruff check src tests scripts`
2. `ruff format --check src tests scripts`
3. `ty check`
4. 后端完整测试的并行安全集合（默认 `-n 8`）
5. `concurrent or db_race` 串行集合（`-n 0`）

完整测试按 marker 分区，保证每项测试只运行一次。默认不启用 rerun；需要重试的测试必须单独登记并解释原因。

### 4.3 前端 lane

```text
bash scripts/ci.sh l1-frontend
```

顺序执行：

1. `npm --prefix frontend run lint`
2. `npm --prefix frontend run test:run`，排除 perf suite
3. `npm --prefix frontend run build`

`frontend/__tests__/perf/` 不进入普通 Vitest gate；性能检查需要独立阈值、版本化基线和专门 lane 后才能恢复阻塞能力。

### 4.4 文档 lane

```text
bash scripts/ci.sh l1-docs
```

使用锁定依赖构建 `docs-site/` 的 Astro + Starlight 站点，确保产品文档在进入 `master` 前即可验证，而不是等 GitHub Pages 部署阶段才发现破坏。

### 4.5 聚合命令

```text
bash scripts/ci.sh l1
```

本地聚合命令依次执行 backend、frontend 与 docs lane，返回第一个失败状态。GitHub Actions 将三个 lane 拆成并行 jobs，缩短冷启动后的总耗时。

## 5. GitHub-hosted workflow

新增 `L1 Deterministic Gate` workflow：

- `pull_request` 与对 `master` 的 `push` 触发。
- 使用 concurrency 按 PR/branch 取消旧运行。
- backend job 使用 Python 3.13、官方 uv setup、`uv sync --locked`；dev group 按 uv 默认规则安装。
- frontend job 使用 Node.js 22、`npm ci` 和 `frontend/package-lock.json` 缓存键。
- docs job 使用 Node.js 22、`npm ci` 和 `docs-site/package-lock.json` 缓存键。
- permissions 仅授予 `contents: read`。
- 不传递生产 secrets，不启动 Docker，不访问 localhost 上的部署服务。
- jobs 直接调用 `scripts/ci.sh l1-backend`、`scripts/ci.sh l1-frontend` 与 `scripts/ci.sh l1-docs`。

workflow 自身不使用 production 同机 self-hosted runner。未来本机 L2–L4 结果如需回写 GitHub，只允许可信 controller 针对批准 SHA 上传状态。

## 6. 纠正现有假信号

### 6.1 staging

- `scripts/test.sh staging` 不再启动并在 EXIT 时销毁共享 staging。
- 进程内 `pytest -m integration` 明确命名为 production-contract，而不是 staging。
- `scripts/staging.sh test` 不得继续用生命周期管理和进程内测试冒充“against staging”；本轮提供非破坏性 GET smoke，要求测试 lane 指定候选 SHA，并验证 staging identity、真实 URL、健康状态与生产模式。健康端点会更新请求指标并执行临时文件/SSH readiness probe，因此不称为严格只读。
- staging 生命周期命令与对已运行实例的 smoke 必须分离。

### 6.2 performance

- 退役当前 GitHub performance workflow，保留 `scripts/perf/` 作为本地 experimental 工具。
- Lighthouse、DB、profiler、benchmark 的目标、认证、状态断言和基线恢复前，不在 GitHub 上产生自动化状态。
- 修复后的性能体系属于 L3，不进入 L1 required checks。

## 7. pytest 与前端测试策略

### 7.1 pytest

全局 `addopts` 只保留与机器规模无关的确定性选项，例如 quiet 与 timeout。并行度由 `scripts/test.sh` / `scripts/ci.sh` 显式控制：

```text
OPENSCIENCE_PYTEST_WORKERS=8
```

允许设置为较低正整数；不允许 `auto` 作为仓库默认值。

### 7.2 Vitest

默认 include 仅包含 correctness tests。`*.perf.ts(x)` 移入单独配置或由显式命令运行，避免普通 gate 打印无阈值性能数字。

### 7.3 Playwright

Playwright 不进入首轮 L1。它将在 L2 进入隔离 browser contract lane，并要求：

- 未处理网络请求失败。
- `pageerror` 失败。
- 非 allowlist console error 失败。
- mock payload 与后端 schema 有 contract 校验。

## 8. 后续 L2–L4 边界

### L2 test cell

- 唯一 Compose project/image tag/run ID。
- 无固定 `container_name`，使用 bridge network 和独立 tmpfs/volume。
- fake LLM/agent/search；不挂 Docker socket、生产卷或生产 `.env`。
- CPU、memory、pids 硬限制；失败按 label 精确清理。

### L3 deep verification

- 全机单实例队列。
- 真实 tenant UID/GID、`sudo -u`、PTY、SSH/tmux、backup/restore、历史迁移 fixture。
- 完整 runtime、真实性能基线和故障注入。

### L4 release acceptance

- staging 使用 production mode、不可变候选 artifact，不 bind mount 源码。
- 验证 frontend/backend SHA 一致。
- 生产发布需要人工批准、全局部署锁、只读 post-smoke 和自动回滚 artifact。

## 9. 验收标准

本轮完成时必须满足：

1. `scripts/ci.sh l0` 与 L1 子命令具有稳定、测试覆盖的命令契约。
2. pytest 默认不再使用 `-n auto` 或全局 rerun。
3. 普通 Vitest 不再执行伪性能 suite。
4. GitHub Actions 自动运行 backend/frontend/docs 确定性 jobs。
5. staging/perf 旧入口不再产生“测试了真实环境”的假象。
6. 新增 workflow 不请求写权限、不使用 self-hosted runner、不接触 Docker。
7. 当前 L1 质量基线通过；若存在无法在本轮安全修复的历史问题，必须显式列出并使对应 gate 状态真实可见，不能静默成功。
