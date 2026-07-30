---
title: OpenScience Compatibility Telemetry Correctness Design
aliases:
  - OpenScience 兼容性遥测正确性设计
tags:
  - openscience
  - observability
  - compatibility
  - architecture-cleanup
doc_state: current
status: accepted
---

# OpenScience Compatibility Telemetry Correctness Design

**Status:** Accepted — 方向已由用户确认，等待实现

**Scope:** HTTP contract telemetry、compatibility field/config telemetry、Prometheus、结构化日志、Grafana、staging 验收

**Out of scope:** 拆分 root/`/v1` router、删除旧接口、修改 canonical HTTP 行为、完成 compatibility removal

## 1. 背景

OpenScience 架构清理 P0–P6 已完成代码结构、committed-v2 authority、generated transport 和前端分层收口，但保留的 compatibility surface 仍缺少可信的完整观察证据。

2026-07-30 的 production-mode staging 审计确认当前指标存在三类正确性问题：

- **误算**：`/api/projects`、`/api/workspaces`、`/api/environments` 等 canonical 请求也被标记为 deprecated；
- **漏算**：root 与 `/v1` 的 Task、Session 调用成功，但没有 deprecated header 或 deprecated counter；
- **混算**：`/api/projects`、`/projects`、`/v1/projects` 最终都被记录为 `path="/projects"`，deprecated 指标又只保留 `projects` 一级分组。

Task compatibility 还存在不同语义被混为一谈的问题：服务端发送 flat response 或 `new_task`，不等于客户端实际读取这些字段。当前实现却会在 canonical mutation 中无条件增加 deprecated counter，因此计数不能作为删除依据。

在遥测正确性修复前，任何缺失或非零指标都不能证明 compatibility caller 是否已经迁移，所有 removal 必须继续 fail-closed。

## 2. 决策摘要

本设计作出以下决策：

1. 优先建立长期有效的 HTTP contract telemetry；长期指标能够回答的问题，不新增 cleanup-only 指标。
2. cleanup-only 指标只用于长期指标无法表达的旧字段、旧配置、旧 CLI 或旧状态路径使用情况。
3. 长期与临时指标必须通过名称、registry metadata、dashboard 分组和文档明确区分。
4. 本轮只修复识别和统计正确性，不拆分现有 router，不删除 compatibility surface，不改变 response shape。
5. canonical、product compatibility 与 external compatible protocol 必须按真实请求区分，而不是根据共享 handler 猜测。
6. 服务端“发送旧响应字段”与客户端“消费旧响应字段”是不同事实，指标名称和删除证据不得混淆二者。
7. 临时指标采用“双重门禁”：对应 compatibility 已删除且稳定运行至少一个 release；并在两个 release 或 90 天内强制复审。
8. `ainrf` 是稳定内部 telemetry 命名空间。长期指标使用 `ainrf_*`，临时指标显式使用 `ainrf_cleanup_*`。

## 3. 目标与非目标

### 3.1 目标

- 对每次 HTTP 请求准确识别它属于 canonical、product compatibility、external compatible protocol 还是 non-product surface；
- 准确保留实际 prefix、稳定 operation、method 和 status class；
- 让 `/api`、root、`/v1` 的同一 handler 调用产生可区分的长期指标；
- 对旧 request field、query/body alias、config alias 等记录精确、低基数、可持久化的使用证据；
- 为 compatibility removal 提供不会漏算、误算或混算的 staging 与生产观察基础；
- 保持指标标签不包含 user、tenant、资源 ID、文件路径、prompt、token、idempotency key 或其他秘密；
- 让 Module 的 Interface 足够小，使未来拆 router 时无需重写遥测调用方。

### 3.2 非目标

- 不把 root 与 `/v1` router 拆成独立 compatibility adapter；
- 不删除或重命名任何现有 route、request field、response field、CLI 或 config alias；
- 不改变 FastAPI/Pydantic schema、generated transport 或 frontend adapter 行为；
- 不承诺 staging synthetic traffic 可以替代真实生产完整观察窗口；
- 不在本轮设计客户端埋点来证明 JavaScript 是否读取某个 response field；
- 不以大规模 tracing、日志平台替代 Prometheus 的有界 release gate。

## 4. 设计原则

### 4.1 长期优先，临时例外

只要长期 HTTP contract 指标可以准确回答问题，就不得增加对应 cleanup-only counter。例如 root/`/v1` route alias 调用量应由长期 contract 指标表达，不再为每组 route 单独创建临时 deprecated counter。

临时指标只允许覆盖长期请求级指标无法观察的事实，例如请求 body 中是否出现 `environment_id`，或进程启动时是否读取 `AINRF_*` alias。

### 4.2 记录事实，不推断客户端行为

指标名称必须描述服务端实际观察到的事实：

- `request_field_observed` 表示服务端收到字段；
- `response_field_emitted` 表示服务端发送字段；
- 不允许使用 `response_field_used`、`caller_consumed` 等无法由服务端证明的语义。

响应字段删除必须同时依赖 caller 静态迁移、已发布客户端版本证据和完整观察窗口，不能只依赖 emitted counter。

### 4.3 分类集中，调用方简单

建立一个深的 telemetry Module。HTTP middleware、字段 compatibility helper 和配置解析只提交少量事实；Module 内部负责：

- surface 分类；
- operation 归一化；
- 标签 allowlist；
- 高基数拒绝；
- Prometheus 写入；
- durable event 写入；
- 结构化日志；
- legacy metric 过渡。

未来拆 router 时，只替换分类输入来源，不改变指标 contract。

### 4.4 不让指标改变产品行为

遥测失败不得把成功请求变成 5xx，也不得绕过权限、维护模式或 durable mutation fence。持久化失败必须通过 bounded failure latch 和结构化日志显式暴露，不能静默吞掉。

## 5. 统一分类模型

### 5.1 Surface class

每个已匹配请求恰好归入一个稳定类别：

| `surface` | 含义 | 示例 |
| --- | --- | --- |
| `canonical` | OpenScience 当前产品 contract | `/api/projects` |
| `compat_root` | root product compatibility alias | `/projects` |
| `compat_v1` | `/v1` product compatibility alias | `/v1/projects` |
| `external_compatible` | 第三方协议要求的兼容 endpoint | `/v1/models`、`/v1/messages` |
| `non_product` | health、metrics、静态文件或 unmatched | `/health`、`/metrics` |

分类顺序必须优先识别显式 external-compatible allowlist，避免把 `/v1/models` 错记为 OpenScience product alias。

### 5.2 Operation

长期指标使用稳定 operation ID，而不是原始 URL 或资源一级 group。

operation 来源优先级：

1. FastAPI route 的稳定 operation ID；
2. 明确注册的 bounded fallback；
3. `unmatched`。

动态资源 ID、query string 和用户输入不得进入 operation label。

### 5.3 实际 prefix

分类必须读取原始请求路径，而不能只读取 FastAPI matched route template。共享 handler 可以继续存在，但 `/api/projects`、`/projects`、`/v1/projects` 必须分别得到 `canonical`、`compat_root`、`compat_v1`。

## 6. 长期指标 contract

### 6.1 HTTP contract 请求计数

新增长期指标：

```text
ainrf_http_contract_requests_total{
  surface,
  operation,
  method,
  status_class
}
```

约束：

- `surface` 使用第 5.1 节固定枚举；
- `operation` 只能来自启动时冻结的 route inventory；
- `method` 使用 bounded HTTP method allowlist；
- `status_class` 只允许 `2xx|3xx|4xx|5xx`，不使用完整错误文本；
- 不增加 `path`、user、tenant、resource ID、client-provided name 等高基数标签。

该指标长期保留，用于：

- canonical 与 compatibility 流量比例；
- API 迁移趋势；
- external-compatible protocol 流量；
- 按 operation 的错误率；
- compatibility removal 的 route-level 观察证据。

### 6.2 HTTP contract 时延

新增长期 histogram：

```text
ainrf_http_contract_request_duration_seconds{
  surface,
  operation,
  method
}
```

它与请求 counter 使用同一个分类结果，避免计数和时延采用不同路径语义。

### 6.3 客户端类别与版本

客户端信息不直接加入主请求 counter，避免任意 User-Agent 或版本字符串形成高基数。

允许增加单独的长期 counter：

```text
ainrf_http_client_contract_requests_total{
  surface,
  client_family,
  contract_generation
}
```

其中：

- `client_family` 仅允许 `webui|cli|external_tool|unknown`；
- `contract_generation` 仅允许仓库定义的 bounded generation，例如 `current|previous|legacy|unknown`；
- 信息来自受控 header 或 internal caller metadata；任意原始版本号只进入脱敏日志，不进入 Prometheus label；
- 未提供可信 metadata 时必须归为 `unknown`，不得根据不稳定 User-Agent 猜测。

该指标属于长期能力，但其实现可以在主 contract counter 正确后分阶段落地。

### 6.4 长期 durable evidence

Prometheus 用于趋势和告警，durable compatibility observation 用于跨进程、跨重启和发布窗口审计。Module 应以 bounded key 持久记录至少：

- observation date/release window；
- surface；
- operation；
- method；
- count；
- first_seen_at；
- last_seen_at；
- optional bounded client family/generation。

不得为每个请求写一条无限增长记录。实现应按固定时间桶和 bounded dimension 聚合，并定义 retention/compaction。

Prometheus process restart 后可以从零开始，但 release removal evidence 必须来自 durable aggregate 或持久化监控系统，不能依赖单进程 counter 值。

## 7. Cleanup-only 指标 contract

### 7.1 允许使用的情况

只有下列事实无法由长期 HTTP contract 指标回答时，才允许使用 cleanup-only 指标：

- deprecated request body/query field 被观察到；
- deprecated response field 被服务端发送；
- legacy config/environment alias 被读取；
- legacy CLI entrypoint 被启动；
- legacy state path 被选择；
- read-only migration/audit surface 需要独立于普通 route traffic 的删除判断。

### 7.2 指标名称

统一使用：

```text
ainrf_cleanup_compatibility_observations_total{
  item,
  observation
}
```

允许的 `observation`：

- `request_field_observed`
- `response_field_emitted`
- `config_alias_read`
- `cli_alias_invoked`
- `state_alias_selected`
- `audit_surface_called`

`item` 必须来自代码内冻结的 registry，例如 `task.create.environment_id`；不得直接使用任意字段名或用户输入。

如果某类事实已经能由长期 contract 指标准确表达，不得在此 registry 中重复登记。

### 7.3 临时 registry metadata

每个 cleanup item 必须在单一 registry 中声明：

- stable item key；
- owner；
- observed fact；
- replacement；
- related compatibility surface；
- introduced release；
- review deadline；
- removal conditions；
- evidence required after removal。

registry 是 Module Implementation 的内部数据和文档生成来源，不向普通调用方暴露复杂 Interface。

### 7.4 双重删除门禁

cleanup item 只有同时满足以下条件才可删除：

1. 对应 compatibility surface 已删除，并经过至少一个稳定发布周期，没有回滚或恢复需求；
2. 从指标引入开始，最迟在两个 release 或 90 天达到强制复审点。

到达复审点不代表自动删除 compatibility。若 compatibility 仍需保留，必须显式更新 owner、原因、证据缺口和下一次复审时间；不得静默延期。

compatibility 与指标删除应尽量在同一 cleanup change 中完成。若必须分开，指标只能比 compatibility 多保留一个稳定发布周期。

## 8. Telemetry Module 设计

### 8.1 Seam

Module 位于中立 observability/telemetry 层。它不得依赖 FastAPI route implementation、领域 Module 或 frontend generated code。

HTTP Adapter 负责从 Request/Response 提取 transport facts；配置和 CLI Adapter 负责提交 alias observation。Prometheus 与 durable store 是 Module 的内部 Adapter。

### 8.2 外部 Interface

目标 Interface 保持为两个概念操作：

```python
observe_http_contract(observation: HttpContractObservation) -> None
observe_cleanup_compatibility(observation: CleanupCompatibilityObservation) -> None
```

调用方不负责：

- 拼接 metric name；
- 选择 label；
- 推断 route group；
- 决定是否 durable；
- 写日志；
- 维护 Prometheus registry；
- 处理 retention。

### 8.3 分类 Adapter

HTTP Adapter 在 response 完成后提交：

- actual request path；
- matched operation ID；
- method；
- status；
- explicit external-compatible marker；
- optional trusted client metadata。

Module 根据冻结规则生成 classification。不要要求每个 route handler 手工调用 `mark_deprecated()` 来识别 prefix。

本轮可以保留现有 deprecation response header 行为，但 header 与 metric classification 必须解耦：header 是否返回不能决定请求属于哪个 surface。

### 8.4 错误处理

- Prometheus 更新失败：记录 bounded internal error，不能改变业务 response；
- durable aggregate 写入失败：设置 delivery failure latch，并记录结构化错误；
- unknown operation/surface：归入 bounded `unknown`/`unmatched`，同时产生内部告警；
- registry 外 cleanup item：开发和测试环境 fail fast，生产环境拒绝高基数写入并设置 failure latch。

## 9. 现有指标迁移

当前指标：

- `ainrf_http_requests_total`
- `ainrf_http_request_duration_seconds`
- `ainrf_deprecated_route_calls_total`
- `ainrf_deprecated_contract_calls_total`

迁移策略：

1. 新指标先与旧指标并行输出一个 release；
2. dashboard 和 removal evidence 只使用新指标；
3. 对同一 staging probe 建立新旧结果对照，显式证明旧指标的误算、漏算和混算；
4. 新指标通过完整观察验收后，旧 deprecated 指标标记为 superseded；
5. 旧指标不得继续作为 compatibility deletion gate；
6. 旧指标的最终删除由后续 implementation plan 安排，不在本设计中隐式删除。

旧 HTTP 总量指标若仍有通用 dashboard caller，可以保留；但必须明确它只用于粗粒度 HTTP 健康观察，不用于 prefix migration 或 compatibility removal。

## 10. Grafana 与日志

### 10.1 长期 dashboard

长期 dashboard 至少展示：

- canonical、compat_root、compat_v1、external_compatible 请求趋势；
- 每个 compatibility operation 的最近调用时间与窗口累计；
- canonical 与 compatibility 的 4xx/5xx；
- unknown/unmatched 分类；
- telemetry delivery failure latch。

### 10.2 Cleanup dashboard

cleanup-only panel 必须在标题和说明中显示：

```text
TEMPORARY — Architecture cleanup compatibility evidence
```

并显示 registry owner、review deadline 和 removal gate。cleanup panel 不得与长期 API health panel 混排成无法辨识的永久监控。

### 10.3 结构化日志

日志可包含：

- request ID；
- surface；
- stable operation；
- method/status；
- bounded client family/generation；
- cleanup item/observation。

日志不得包含 token、password、prompt、raw body、idempotency key、用户路径或任意资源内容。

## 11. 验证策略

### 11.1 Module Interface 测试

通过 Module Interface 验证：

- path classification；
- external-compatible precedence；
- operation allowlist；
- status class；
- cleanup registry rejection；
- Prometheus output；
- durable aggregation；
- restart/restore；
- delivery failure latch；
- 无高基数和秘密标签。

不复制 Prometheus client 或 SQLite helper 的内部实现测试。

### 11.2 HTTP contract matrix

至少覆盖：

| 实际请求 | 预期 surface | 预期 operation |
| --- | --- | --- |
| `/api/projects` | `canonical` | Projects list operation |
| `/projects` | `compat_root` | 同一稳定 operation |
| `/v1/projects` | `compat_v1` | 同一稳定 operation |
| `/api/tasks` | `canonical` | Tasks list operation |
| `/tasks` | `compat_root` | 同一稳定 operation |
| `/v1/tasks` | `compat_v1` | 同一稳定 operation |
| `/v1/models` | `external_compatible` | Models compatibility operation |

Project、Workspace、Environment、Session、Task 都必须执行三 prefix matrix，证明不再误算或漏算。

### 11.3 Field observation matrix

Task create/retry/fork 至少验证：

- canonical request 不携带旧字段时 cleanup counter 不增加；
- body/query alias 出现时只增加对应 item；
- flat response 与 `new_task` 只记录 `response_field_emitted`；
- emitted 指标不被描述为 caller consumption；
- header `Idempotency-Key` 不被记成 body alias；
- 一个请求不会被 route、request field、response field 重复解释成同一个事实。

### 11.4 Staging 验收

在 production-mode staging 执行：

1. 记录基线；
2. 每个 prefix/operation 只调用一次；
3. 对比精确 delta；
4. 重启 staging backend；
5. 验证 durable release evidence 连续；
6. 验证 Grafana 查询与 raw metrics 一致；
7. 验证 production 容器、端口、volume 和数据完全未触碰。

Synthetic staging 只证明识别正确性，不作为完整生产零流量窗口。

## 12. 验收标准

本设计实现完成必须满足：

1. `/api`、root、`/v1` 同 handler 请求可被准确区分；
2. canonical `/api` 不再增加 compatibility route traffic；
3. Task、Session root/`/v1` 调用不再漏算；
4. Project、Workspace、Environment 不再把三种 prefix 混成一个 compatibility count；
5. operation 不再压缩为单一资源 group；
6. external-compatible `/v1` 不被算作 product compatibility；
7. request field、response emission、route traffic 使用不同且准确的事实语义；
8. 长期指标可回答 route alias 使用问题时，不存在重复 cleanup metric；
9. 所有 cleanup item 都有 registry metadata 和双重门禁；
10. 指标 label 有固定枚举与高基数测试；
11. telemetry failure 不改变产品 response，并有 failure latch；
12. staging matrix、backend restart 和 durable aggregate 验证通过；
13. 现有 route、schema、generated transport 和 frontend 行为无变化；
14. 旧指标明确标记为非 removal authority；
15. 生产完整观察窗口仍作为后续独立验收，不被 staging 替代。

## 13. 分阶段实施建议

### Phase T0：冻结分类和 registry

- 冻结 surface、operation 和 cleanup item inventory；
- 为现有指标建立 staging 基线；
- 建立高基数与秘密标签 guard。

### Phase T1：长期 HTTP contract telemetry

- 实现统一分类 Module 和 HTTP Adapter；
- 输出长期 counter/histogram；
- 建立 durable aggregate；
- 完成三 prefix 与 external-compatible matrix。

### Phase T2：精确 cleanup observation

- 迁移 request field/config/CLI/state alias 观察；
- 修正 response emission 语义；
- 清除长期指标已经覆盖的重复 cleanup item。

### Phase T3：dashboard 与 staging acceptance

- 更新 Grafana；
- 执行 production-mode staging delta/restart 验证；
- 标记旧 deprecated 指标为 superseded；
- 记录后续完整生产观察窗口的起始条件。

每个 phase 使用 replace-don't-layer：新 Interface 测试建立后删除只验证旧 helper 转发或旧错误分组的测试，不长期保留两套 removal gate。

## 14. 后续工作

本设计完成后再规划：

- 将 root 与 `/v1` 拆为显式 compatibility adapter；
- 使用上一生产版客户端验证新后端；
- 建立完整 release telemetry 观察窗口；
- 按逐项证据删除 compatibility route、field、config 和 CLI alias；
- 在 compatibility cleanup 后删除 `ainrf_cleanup_*` registry、metric 和 dashboard panel。

拆 router 是后续结构重构，不是本轮遥测正确性实现的前置条件。
