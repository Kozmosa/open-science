# Literature Fetch Refactor & Enhancement Proposal

**Date:** 2026-06-15  
**Status:** Proposal / Pending approval  
**Scope:** `src/ainrf/literature/` + `src/ainrf/api/routes/literature.py` + DB migrations  

---

## 1. Background & Goals

当前 `src/ainrf/literature/fetcher.py` 与 `scheduler.py` 已经跑通了最小可用链路，但存在几个真实弱点：

- LLM 摘要直接走裸 `httpx`，没有利用官方 SDK 的重试、类型安全与连接池。
- `max_results=10` 写死、没有时间窗过滤，导致漏抓与无效抓取。
- 调度器是全局 6h 一次，未真正尊重 `daily/twice_daily/weekly` 频率语义。
- 去重是“按订阅去重”，同一篇论文会在不同 subscription 下重复保存、重复摘要。
- 缺少设计文档中声明的 Semantic Scholar 元数据补充、批量摘要、摘要缓存等能力。
- 异常被静默吞掉，失败不可观测。

本提案目标是把文献抓取从“最小可行”升级到“可长期运行、可观测、可扩展”的生产级实现，并补齐之前声明的功能。

### 1.1 已确认的决策

| 决策 | 结论 |
|------|------|
| LLM 端点 | 只支持 **Anthropic-compatible** 端点，使用官方 `anthropic` Python SDK |
| 凭证/端点 | 复用现有环境变量：`ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` / `ANTHROPIC_DEFAULT_*_MODEL`，并允许 `AINRF_LITERATURE_MODEL` 覆盖 |
| 去重 | 全局按 **arXiv paper_id** 去重 |
| 摘要缓存 | 任何 LLM 调用后“基本不变的结果”都做缓存；同一 paper_id 只摘要一次 |
| 调度 | 每个 subscription 拥有独立的 APScheduler job，真正按频率执行 |
| 功能范围 | 补齐 `docs/superpowers/specs/2026-05-21-literature-tracking-design.md` 中声明的能力 |

---

## 2. 模块拆分

把目前耦合在 `fetcher.py` 里的职责拆成独立模块：

```text
src/ainrf/literature/
├── __init__.py
├── models.py                    # 现有模型 + 新增字段微调
├── service.py                   # 数据访问 + 全局去重/缓存逻辑
├── arxiv_client.py              # arXiv 查询构造、调用、重试、解析
├── metadata_enricher.py         # Semantic Scholar 元数据补充（可选降级）
├── summarizer.py                # Anthropic SDK 批量摘要 + 缓存决策
├── scheduler.py                 # 每 subscription 一个 APScheduler job
├── fetcher.py                   # 编排：query → fetch → enrich → summarize → persist
└── api/routes/literature.py     # 手动触发 + 状态查询（清理已完成的任务）
```

### 2.1 `arxiv_client.py`

- 构造 arXiv 查询：关键词 `AND`、分类 `OR`、时间窗 `submittedDate:[{last_fetch} TO {now}]`。
- `max_results` 从 subscription 配置读取，默认 50，全局上限 100。
- 调用 `arxiv.Client` 时使用显式 `num_retries` 与超时；异常向上抛出，不吞掉。
- subscription 之间保留最小 3s 间隔，避免触发 arXiv 频率限制。

### 2.2 `summarizer.py`

- 使用 `anthropic.AsyncAnthropic`，读取环境变量初始化 `api_key`、`base_url`。
- 模型选择顺序：
  1. `AINRF_LITERATURE_MODEL`
  2. `ANTHROPIC_DEFAULT_SONNET_MODEL`
  3. `ANTHROPIC_DEFAULT_OPUS_MODEL`
  4. `ANTHROPIC_DEFAULT_HAIKU_MODEL`
  5. 硬编码兜底（如 `claude-sonnet-4-5`）
- 批量摘要：默认每批 5 篇，prompt 要求返回 JSON 数组：

```json
[
  {"title_zh": "...", "ai_summary": ["...", "...", "..."], "ai_practice_note": "..."},
  ...
]
```

- 摘要前检查全局缓存：若 `literature_papers.title_zh` 已存在且 `summary_version` 匹配当前 prompt/model 版本，则跳过。
- 失败重试：指数退避，单批失败则回退到单篇单 call（保证部分可用）。
- 通过 `ObservabilityReporter.record_generation` 记录 token 与成本。

### 2.3 `metadata_enricher.py`

- 调用 Semantic Scholar API（`https://api.semanticscholar.org/graph/v1/paper/ARXIV:{id}`）补充：
  - `journal` / `venue`
  - `citationCount`
  - `openAccessPdf`
  - 更完整的作者信息
- 失败时降级：仅使用 arXiv 原始元数据，不影响主流程。

---

## 3. 数据模型变更

### 3.1 `literature_subscriptions`

新增字段：

```sql
ALTER TABLE literature_subscriptions
ADD COLUMN max_results INTEGER NOT NULL DEFAULT 50,
ADD COLUMN next_fetch_at TEXT;
```

- `max_results`: 该订阅每次抓取的最大论文数，允许用户在 UI/API 调整。
- `next_fetch_at`: 下次调度时间，便于前端展示“下次刷新”。

### 3.2 `literature_papers` — 改为全局表

主键从 `(paper_id, subscription_id)` 改为 `paper_id`。

```sql
CREATE TABLE literature_papers_new (
    paper_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    title_zh TEXT,
    authors_json TEXT NOT NULL DEFAULT '[]',
    abstract TEXT NOT NULL DEFAULT '',
    journal TEXT,
    published_at TEXT NOT NULL DEFAULT '',
    arxiv_category TEXT NOT NULL DEFAULT '',
    ai_summary TEXT,
    ai_practice_note TEXT,
    summary_version TEXT,          -- 用于缓存失效
    summary_model TEXT,
    citation_count INTEGER,
    pdf_url TEXT,
    created_at TEXT NOT NULL
);
```

迁移策略：

1. 创建新表。
2. 按 `paper_id` 去重迁移旧数据：若多篇重复，保留已有摘要的；都有摘要则保留最新 `created_at`。
3. 删除旧表，重命名新表。

### 3.3 新增 `literature_subscription_papers` 关联表

```sql
CREATE TABLE literature_subscription_papers (
    subscription_id TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    is_converted_to_task INTEGER NOT NULL DEFAULT 0,
    task_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (subscription_id, paper_id),
    FOREIGN KEY (subscription_id) REFERENCES literature_subscriptions(subscription_id),
    FOREIGN KEY (paper_id) REFERENCES literature_papers(paper_id)
);
```

这样：

- 论文全局唯一，消除数据冗余。
- 同一 paper 可被多个订阅关联，但只摘要一次。
- “已读 / 已转 task” 状态按订阅隔离，符合产品语义。

---

## 4. 调度策略

### 4.1 每个 subscription 独立 job

`LiteratureScheduler` 不再只有一个全局 job，而是维护：`subscription_id → APScheduler job` 映射。

- 启动时：为所有 active subscription 创建/更新 job。
- subscription 创建/更新/删除时：动态 add / reschedule / remove。
- job trigger：
  - `daily` → `IntervalTrigger(hours=24)`
  - `twice_daily` → `IntervalTrigger(hours=12)`
  - `weekly` → `IntervalTrigger(weeks=1)`
- 首次 next_run_time 计算：`last_fetched_at + frequency_delta`，避免服务重启后立即重抓。

### 4.2 单次抓取互斥

每个 subscription 在内存中维护 `asyncio.Lock`，保证：

- 调度任务与手动触发不会并发执行。
- 如果某次抓取超时或卡住，下一次调度不会叠加。

### 4.3 `last_fetched_at` / `next_fetch_at` 更新语义

- 仅当 arXiv 抓取成功（无论是否有新论文）且摘要阶段未出现不可恢复错误时，才更新 `last_fetched_at` 与 `next_fetch_at`。
- 任何阶段失败：记录失败指标、保留旧时间，下次调度继续尝试。

---

## 5. 抓取流水线

```text
run_fetch_for_subscription(sub_id)
    │
    ▼
[claim lock for sub_id]
    │
    ▼
build arxiv query (keywords + categories + submittedDate window)
    │
    ▼
fetch papers from arxiv (with retry)
    │
    ▼
for each paper:
    - upsert global literature_papers (paper_id PK)
    - upsert literature_subscription_papers (sub_id, paper_id)
    │
    ▼
optional: Semantic Scholar enrichment (best-effort)
    │
    ▼
collect papers without summary (or summary_version mismatch)
    │
    ▼
batch summarize via Anthropic SDK
    │
    ▼
update literature_papers with title_zh / ai_summary / etc.
    │
    ▼
emit metrics + update last_fetched_at / next_fetch_at
    │
    ▼
[release lock]
```

---

## 6. API 与前端影响

### 6.1 新增/调整字段

- `POST /literature/subscriptions` / `PUT ...` 接受可选 `max_results`（整数，1–100）。
- 订阅响应增加 `next_fetch_at`。
- 论文响应增加 `journal`、`citation_count`、`pdf_url`。

### 6.2 手动触发

保持现有 `POST /literature/subscriptions/{id}/fetch` 202 + `GET .../fetch-status`。

改进：

- 手动触发也走 `run_fetch_for_subscription`，与调度任务共享加锁与指标。
- 任务完成后 5 分钟从 `app.state._literature_tasks` 中清理（避免内存泄漏）。
- 应用 shutdown 时取消未完成的 `asyncio.Task`。

---

## 7. 指标与可观测性

保留现有 Prometheus 指标，并做以下调整：

- `ainrf_literature_fetch_total{subscription_id, status}` 保持，但失败时记录 `status=failed` 而不是吞掉。
- `ainrf_literature_summarize_total{status}` 保持，新增 `batch_size` 维度（可选）。
- 新增 `ainrf_literature_enrich_failed_total{source}`（Semantic Scholar 失败计数）。
- 新增 `ainrf_literature_papers_deduped_total`（因全局缓存跳过摘要的次数）。
- 保留 `record_generation` 调用以对接外部可观测性后端。

> 注意：`subscription_id` 作为 label 仍存在高基数风险。若订阅数持续增长，后续应评估是否改用 `user_id` 或固定 bucket。

---

## 8. 测试策略

| 层级 | 覆盖点 |
|------|--------|
| 单元 | arxiv 查询字符串构造（空关键词、特殊字符、时间窗） |
| 单元 | 批量摘要 JSON 解析与单篇 fallback |
| 单元 | 全局去重/缓存决策逻辑 |
| 单元 | 调度器 job add/reschedule/remove |
| API | 订阅 CRUD 含 `max_results`、手动触发 202、状态轮询 |
| 集成 | mock arxiv + mock Anthropic SDK，验证端到端指标与落库 |
| 迁移 | 旧表 `(paper_id, subscription_id)` 数据正确迁移到全局表 + 关联表 |

---

## 9. 实施阶段

建议分 3 个 PR 落地，每个 PR 可独立 review 与回滚。

### Phase 1：核心重构（优先）

- 引入 `anthropic` 依赖。
- 拆分 `arxiv_client.py`、`summarizer.py`、`fetcher.py`。
- 实现批量摘要 + 摘要缓存（仍用现有表结构，新增 `summary_version`、`summary_model` 字段）。
- arXiv 时间窗查询、重试、错误传播。
- 更新测试。

### Phase 2：全局模型与独立调度

- 数据迁移：全局 `literature_papers` + `literature_subscription_papers`。
- 每个 subscription 独立 APScheduler job。
- `max_results`、`next_fetch_at` API 支持。
- 手动触发任务清理与并发锁。

### Phase 3：元数据增强

- Semantic Scholar enrichment。
- 前端展示 `journal`、`citation_count`、`pdf_url`。
- Seed paper diffusion（可选，依赖 S2 recommendations API 或 arxiv `id_list` 扩散）。

---

## 10. 风险与回滚

| 风险 | 缓解 |
|------|------|
| 数据迁移失败 | 迁移脚本先创建新表、再复制数据、最后原子 rename；失败可手动回滚到旧表 |
| Anthropic SDK 与现有 env 不兼容 | 复用完全相同的 env key；兼容 DeepSeek Anthropic-compatible 端点 |
| 批量摘要 JSON 不稳定 | 失败自动 fallback 到单篇单 call |
| 调度 job 过多 | 仅对 active subscription 创建；job 数 = active 订阅数，可控 |
| 摘要成本超预期 | `max_results` 默认 50、批量 5 篇/次；后续可加单用户预算上限 |

---

## 11. 待确认项（需要你拍板）

1. **批量大小默认值**：建议 5 篇/批次，是否接受？
2. **`max_results` 默认值与上限**：默认 50、上限 100，是否合适？
3. **Semantic Scholar 是否进入 Phase 2 还是延后到 Phase 3？** 建议 Phase 3，因为它不是阻塞主链路的能力。
4. **seed paper diffusion**：当前 `seed_paper_ids` 字段是空的，是否在本次实现，还是继续 TODO？
5. **摘要缓存失效策略**：当前方案以 `(model + prompt_version)` 作为 `summary_version`；若你未来会频繁调整 prompt，是否需要额外的“强制重摘要”管理命令？

确认后，我会按 Phase 1 开始给出详细代码改动与迁移脚本。
