---
aliases:
  - 容器工作区协议
tags:
  - research-agent
  - framework-design
  - infrastructure
source_repo: scholar-agent
source_path: /home/xuyang/code/scholar-agent
last_local_commit: workspace aggregate
---
# 容器工作区协议

> [!abstract]
> 框架的执行平面运行在隔离容器上。本文档定义容器的接入假设、每个研究项目的目录结构、论文解析入口、本地同步协议和资源跟踪约定。容器生命周期管理不在框架范围内。

## 容器接入假设

- 通过 SSH 接入，本地已配置好密钥，agent 可直接连接。
- 容器具有 GPU 资源和完全 root 权限。
- 容器与宿主机良好隔离（独立网络和文件系统），不需要在框架层面额外处理安全问题。
- 容器的创建、启动、停止和销毁由外部管理，不属于框架职责。
- 容器上应预装基础工具链：Python 3.10+、CUDA toolkit、git、常用系统包。具体研究项目的依赖在项目初始化阶段安装。

## 每项目工作区结构

每个研究项目在容器上是一个独立的 git repo。目录布局约定如下：

```
project-root/
├── papers/              # MinerU 解析后的 Markdown 论文
│   ├── seed/            # 种子论文（用户提供的 PDF 经 MinerU 转换）
│   └── explored/        # Mode 1 递归探索中发现并解析的论文
├── src/                 # 实现代码（Mode 2 从零实现；Mode 1 可选的小型分析脚本或图谱构建脚本）
├── experiments/         # ExperimentRun 产物
│   └── run-YYYYMMDD-HHMMSS/
│       ├── config.json  # 运行配置
│       ├── logs/        # 训练/推理日志
│       ├── metrics/     # 指标数据
│       ├── checkpoints/ # 模型检查点（可选，大文件不同步）
│       └── result.json  # 运行结果摘要
├── reports/             # 生成的报告
│   ├── discovery/       # 调研发现报告、领域图景与 idea 机会分析
│   ├── quality/         # 论文质量评估报告（Mode 2）
│   └── exploration/     # 探索报告与下一步建议（Mode 1）
├── artifacts/           # 序列化的一等工件
│   ├── paper-cards/     # PaperCard JSON
│   ├── evidence/        # EvidenceRecord JSON
│   ├── claims/          # Claim JSON
│   └── exploration-graph.json  # ExplorationGraph 状态（Mode 1）
├── workspace.json       # WorkspaceManifest：环境、依赖、GPU 配置、资源消耗
└── README.md            # 项目概述（agent 自动生成并维护）
```

## MinerU 论文解析

- 用户提供的种子论文 PDF 通过 MinerU API 解析为 Markdown 格式，存入 `papers/seed/`。
- 解析产物包括：正文 Markdown、提取的图表（如有）、元数据（标题、作者、摘要）。
- 对于 Mode 1 递归探索中引用链上的论文，agent 按需调用 MinerU 解析并存入 `papers/explored/`。
- 解析失败（PDF 结构无法提取）应记录为 `EvidenceRecord`，标注失败原因，不阻塞整体流程。

## 本地同步协议

研究产物需要从容器同步到用户本地环境：

- **主通道 — git**：每个项目是 git repo，agent 在关键节点（阶段性报告产出、实验完成）执行 commit 和 push。本地机器通过 git pull 获取报告、代码和轻量级工件。
- **大文件通道 — rsync/scp**：模型检查点、大型数据集和完整训练日志等二进制大文件不进入 git，通过 rsync 或 scp 按需传输。`workspace.json` 记录哪些路径包含大文件及其容器上的位置。
- **同步频率**：agent 在以下时机触发 git commit + push：
  - 每个 ExperimentRun 完成或失败后
  - 每个 PaperCard 完成结构化阅读后
- Mode 1 每轮调研迭代结束时
  - Mode 2 每个主要实现里程碑后
- **冲突处理**：容器是唯一写入方，本地只读取，因此不存在合并冲突。

## 资源跟踪

agent 在 `workspace.json` 中持续记录资源消耗：

```json
{
  "project_id": "example-2025-03",
  "container": {
    "host": "gpu-server-01",
    "gpu": "A100-80G x 1",
    "cuda": "12.4"
  },
  "budget": {
    "gpu_hours_limit": 24,
    "gpu_hours_used": 6.5,
    "api_cost_limit_usd": 50,
    "api_cost_used_usd": 12.3,
    "wall_clock_limit_hours": 48,
    "wall_clock_used_hours": 8.2
  },
  "environment": {
    "python": "3.11.7",
    "torch": "2.3.0",
    "key_packages": ["transformers==4.40.0", "einops==0.8.0"]
  },
  "large_files": [
    {"path": "experiments/run-20250315-143000/checkpoints/best.pt", "size_gb": 2.1}
  ]
}
```

当任意预算维度达到上限时，agent 停止执行并在报告中说明终止原因。

## 多项目隔离

- 同一容器上的多个研究项目各自独立 git repo，互不干扰。
- 共享的基础环境（Python、CUDA）由容器预装；项目特有的依赖在各自 venv 或 conda env 中管理。
- `workspace.json` 中的 `project_id` 确保资源计量按项目独立统计。

## 关联笔记

- [[framework/index]]
- [[framework/ai-native-research-framework]]
- [[framework/artifact-graph-architecture]]
- [[framework/v1-dual-mode-research-engine]]
