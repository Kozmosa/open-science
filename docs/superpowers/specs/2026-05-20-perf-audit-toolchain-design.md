# Performance Audit Toolchain Design

> [!warning] Status: experimental / retired from CI
> 该文档记录历史性能工具链设计，不再代表当前 CI contract。2026-07-11 审计确认 Lighthouse、API benchmark、DB analyzer 与 profiler 存在目标、认证、状态断言和运行环境漂移；对应 GitHub workflow 已退役。工具脚本暂保留为本地实验输入，待五层混合 CI 的 L3 deep verification 重新建立可运行 harness、版本化基线与阻塞阈值后再恢复自动化。当前架构以 [[2026-07-11-five-layer-hybrid-ci-design]] 为准。

## 目标

为 scholar-agent 项目建立可持续的全栈性能审计工具链，覆盖后端 API、数据库、前端 bundle、React 渲染四个维度。支持手动一键执行和 CI 调用，每次运行产出版本化报告，支持历史对比。

## 优先级

1. 用户感知延迟 > 2. 资源效率 > 3. 开发者体验

## 工具链架构

```
scripts/perf/
├── run-all.py          # 主入口：一键跑全栈，或按 --target 选择子系统
├── _common.py          # 共享工具：计时、报告格式化、路径解析
├── backend/
│   ├── benchmark_api.py    # pytest-benchmark 测试套件
│   ├── profile_hot.py      # py-spy 采样脚本
│   └── analyze_db.py       # SQLite EXPLAIN QUERY PLAN 索引检查
├── frontend/
│   ├── lighthouse.js       # lhci 配置 + 自定义收集脚本
│   └── bundle_report.mjs   # rollup-plugin-visualizer 包装 + 异常扫描
├── react/
│   └── profiler_report.py  # 解析 React.Profiler 导出数据
└── reports/
    └── (gitignored)        # .cache/perf-report/ 软链接到此
```

### 设计原则

- 每个子工具可独立运行，也可通过 `run-all.py` 一键聚合
- 所有报告输出到 `.cache/perf-report/YYYY-MM-DD/`
- 每次执行覆盖同日报告，保留不同日期的历史对比
- `--ci` 模式输出 JSON 摘要，默认模式输出终端彩色表格 + HTML 报告

---

## 后端性能测量

### API 延迟基准 (`backend/benchmark_api.py`)

使用 `pytest-benchmark` 对每个路由测量 p50/p95/p99 延迟。

覆盖端点分组：

| 组 | 端点 | 关注指标 |
|------|------|------|
| 认证 | `/auth/login`, `/auth/register`, `/auth/refresh` | bcrypt 哈希、JWT 签发延迟 |
| 项目 | `/projects`, `/projects/{id}/tasks`, `/projects/{id}/task-edges` | 列表查询、索引退化 |
| 任务创建 | `POST /tasks` | 端到端延迟（schema 写入 + 引擎启动） |
| 文件 | `/files/read`, `/files/list` | 大文件 I/O、目录枚举 |
| WebSocket | `/terminal/attach` | 连接建立延迟 |
| 会话 | `/sessions`, `/sessions/{id}/attempts` | 历史查询性能 |

每端点 3 轮 × 50 次调用，产出 `api-benchmark.json`。

### 热点函数采样 (`backend/profile_hot.py`)

向运行中的服务进程 attach `py-spy`，采样 30 秒：

```bash
py-spy record -o .cache/perf-report/YYYY-MM-DD/flamegraph.svg \
  --pid $(cat .ainrf/server.pid) --duration 30
```

采样窗口内用预置 curl 脚本触发典型负载（创建 task、浏览 files、打开 terminal）。产出 `flamegraph.svg`。

### 数据库查询分析 (`backend/analyze_db.py`)

对每个 `.sqlite3` 文件：
1. 读取所有表 schema，检查每列是否有索引
2. 对核心查询运行 `EXPLAIN QUERY PLAN`，标记全表扫描
3. 产出一份缺失索引报告 `db-index-report.md`

---

## 前端性能测量

### Bundle 分析 (`frontend/bundle_report.mjs`)

Vite 构建时注入 `rollup-plugin-visualizer`，产出：
- `bundle-treemap.html` — 交互式模块大小树状图
- `bundle-stats.json` — 各 chunk 原始大小 / gzip 大小

自定义检查规则（构建后扫描）：
- 任一 chunk > 500KB → 警告
- 重复模块跨 chunk（去重失败）
- 未 tree-shaken 的全量导出

### 首屏加载 (`frontend/lighthouse.js`)

使用 `lhci` CLI 对关键页面审计：

```bash
lhci collect --url http://localhost:5173/login
lhci collect --url http://localhost:5173/projects
lhci collect --url http://localhost:5173/tasks
lhci assert --preset=recommended
```

产出 `lighthouse.json`（FCP / LCP / TBT / CLS）。

### React 渲染性能 (`react/profiler_report.py`)

在 `App.tsx` 中预置 `<React.Profiler>`（仅 `VITE_PROFILE=true` 时激活），收集每个路由页面的挂载耗时、更新耗时、渲染提交次数。通过 `performance.measure` API 收集数据并 post 到本地收集端点，产出 `react-render.json`。

---

## 执行方式

### 手动执行

```bash
# 全栈一键测量
uv run python scripts/perf/run-all.py

# 单独跑某个子系统
uv run python scripts/perf/run-all.py --target backend
uv run python scripts/perf/run-all.py --target frontend
uv run python scripts/perf/run-all.py --target db

# 对比最新两次报告
uv run python scripts/perf/run-all.py --diff
```

### CI 调用

```bash
uv run python scripts/perf/run-all.py --ci --threshold backend=800ms frontend=2s
```

- `--ci`：产出 JSON 摘要，退出码表示是否超阈值
- `--threshold`：各子系统退化红线（可选，超阈值退出码非 0）
- CI workflow 为手动触发（`workflow_dispatch`），不强制集成到 CI/CD 流水线

---

## 报告输出结构

```
.cache/perf-report/2026-05-20/
├── summary.json          # 全栈汇总（供 --diff 历史对比）
├── api-benchmark.json    # API 延迟 p50/p95/p99 数据
├── flamegraph.svg        # py-spy 热点采样
├── db-index-report.md    # 数据库索引分析与建议
├── bundle-stats.json     # bundle chunk 大小
├── bundle-treemap.html   # 交互式树状图
├── lighthouse.json       # Lighthouse FCP/LCP/TBT 分数
└── react-render.json     # React 组件渲染耗时排行
```

### 历史对比

`--diff` 模式自动对比最近两次不同日期的 `summary.json`，输出各指标的 delta 百分比表：

```
Metric                        2026-05-19    2026-05-20    Delta
────────────────────────────────────────────────────────────────
API login p50                 12.3ms        14.1ms        +14.6%
API create_task p95           840ms         920ms         +9.5%
Bundle main chunk (gzip)      78KB          82KB          +5.1%
Lighthouse LCP (projects)     1.8s          1.6s          -11.1%
```

---

## 新建依赖

### Python (pyproject.toml)
- `pytest-benchmark` — API 微基准
- `py-spy` — 采样 profiler（系统级安装：`pip install py-spy` 或 `cargo install py-spy`）

### Node (frontend/package.json devDependencies)
- `rollup-plugin-visualizer` — bundle 分析（已有 `vite-bundle-visualizer` 备选）
- `@lhci/cli` — Lighthouse 审计

### 系统
- `py-spy` 需要 Linux perf 权限（`echo 0 > /proc/sys/kernel/perf_event_paranoid` 或 `CAP_SYS_ADMIN`）

---

## 验证

1. `uv run python scripts/perf/run-all.py --target db` 产出索引报告
2. `uv run python scripts/perf/run-all.py --target backend` 启动服务 → 跑 benchmark → 产出 flamegraph
3. `cd frontend && npm run build` 后 `node scripts/perf/frontend/bundle_report.mjs` 产出 treemap
4. `cd frontend && VITE_PROFILE=true npm run dev` 后加载页面，验证 React profiler 数据收集
