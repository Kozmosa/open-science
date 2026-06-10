---
aliases:
  - 资源监控
  - Resource Monitoring
  - resources
tags:
  - ainrf
  - resources
  - monitoring
  - gpu
  - docs
  - obsidian-note
source_repo: scholar-agent
source_path: docs/ainrf/resources.md
last_local_commit: workspace aggregate
---

# 资源监控

> [!abstract]
> AINRF 资源监控页面提供计算资源的实时可视化，包括 GPU、CPU、内存和 AINRF 进程树，支持本地与远程（SSH）环境。

## ResourcesPage

路由：`/resources`

资源监控页面以 `CardGrid` 布局展示所有环境的资源快照。所有卡片（Token 用量、系统资源、AINRF 进程）位于同一个可拖拽网格中，支持自由排序（布局持久化至 `localStorage`）。卡片类型包括：

- **Token 用量卡**：汇总所有任务的 Token 消耗、总耗时、中位耗时，并列出 Top N 高消耗任务
- **系统资源卡**：GPU / CPU / 内存使用率
- **AINRF 进程卡**：以服务 PID 为根的进程树

## GPU 监控

通过 `nvidia-smi` 采集 GPU 指标：

- 查询命令：`nvidia-smi --query-gpu=index,name,utilization.gpu,memory.used,memory.total --format=csv`
- 采集字段：GPU 索引、型号名称（如 NVIDIA A100）、显存使用量（MiB）、显存总量（MiB）、利用率（百分比）
- 若无 `nvidia-smi` 命令可用，GPU 列表为空

## CPU 监控

通过 `ps` 采集进程级 CPU 数据：

- 查询命令：`ps -eo pid,ppid,pcpu,rss,etime,comm`
- 采集字段：PID、父 PID、CPU 百分比（单核）、RSS（KB，转换为 MB）、运行耗时、命令名
- 系统级 CPU 使用率 = 所有进程 CPU 百分比之和 / 逻辑核心数，归一化为 0-100%
- 通过 `os.cpu_count()` 获取核心数

## 内存监控

通过 `/proc/meminfo` 采集系统内存：

- 读取 `MemTotal` 和 `MemAvailable` 字段
- 计算：使用量 = MemTotal - MemAvailable
- 返回：总量（MB）、使用量（MB）、使用百分比
- 提供异步封装（`anyio.to_thread.run_sync` 避免阻塞事件循环）
- 读取异常时返回全零值

## 进程树

`ProcessTreeFilter` 以 AINRF 服务进程 PID 为根节点，递归收集所有子进程：

- 通过 `ps -eo pid,ppid,pcpu,rss,etime,comm` 获取全量进程快照
- 根据 PID-PPID 关系构建树，收集所有后代
- 返回 `ProcessInfo` 列表：pid、name、cpu_percent、memory_mb、runtime_seconds

根 PID 通过 `os.getpid()` 在 `LocalCollector` 初始化时记录。

## 轮询间隔

资源采集循环每 **2 秒**执行一次（`asyncio.sleep(2)`），每次循环遍历所有已注册环境，逐个采集快照。采集结果缓存在 `ResourceMonitorService._snapshots` 字典中，通过 API 返回给前端。

## 本地与远程环境

- **本地环境**（`env-localhost`）：使用 `LocalCollector`，直接在宿主机上执行 `nvidia-smi` / `ps` / `/proc/meminfo`
- **远程环境**（SSH）：使用 `RemoteCollector`，通过 `SSHExecutor` 在远端执行相同命令并解析输出

## 关联笔记

- [[index]]
