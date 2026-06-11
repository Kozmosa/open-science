# Vast.ai 按需 GPU 集成

> 🇬🇧 English: [VAST_GPU_GUIDE.md](VAST_GPU_GUIDE.md)
> ARIS [GPU 服务器配置](../../README_CN.md#%EF%B8%8F-安装)的三种模式之一。没有自己的 GPU 服务器时用这个。

ARIS 支持从 [Vast.ai](https://vast.ai)（最便宜的 ML 硬件 spot 租赁市场）按需租 GPU。当你跑 `/run-experiment` 时，ARIS **分析你的训练任务**（模型大小、数据集、预估时间），搜索能放下这个负载的最便宜 GPU，然后按**总成本**（不是 $/hr）排序展示给你。你选一个，ARIS 全自动：租 → 配环境 → 跑 → 收结果 → 销毁。

## 什么时候用 vs. `gpu: remote` / `gpu: local`

| 选项 | 适用场景 | 成本模型 |
|------|---------|----------|
| `gpu: remote` | 你自己有（或实验室提供）固定的 SSH 服务器 | 沉没成本，ARIS 当免费用 |
| `gpu: local` | 你已经在 GPU 主机上 | 沉没成本，省 SSH |
| `gpu: vast` | 没 GPU，或者偶尔需要比自己拥有的更大的硬件跑单次实验 | 按小时计费，Vast.ai 自动扣款 |

Vast.ai 适合一次性消融实验、跑 baseline、或者为某个单独实验临时上 A100/H100。不适合需要一周以上的训练——那种情况自购服务器更便宜。

## 准备工作

1. **注册 Vast.ai 账号** https://cloud.vast.ai/ 并充值（信用卡或加密货币）。

2. **安装 `vastai` CLI**（需要 **Python ≥ 3.10**）：
   ```bash
   pip install vastai
   ```
   Python 版本较旧时（用 `python --version` 检查），需要先建个 ≥ 3.10 的虚拟环境（`conda create`、`pyenv`、`uv venv` 任选）。

3. **设置 API key** —— 在 https://cloud.vast.ai/cli/ 获取：
   ```bash
   vastai set api-key YOUR_API_KEY
   ```

4. **上传 SSH 公钥** https://cloud.vast.ai/manage-keys/ —— **租任何实例前必须先做**（key 在实例创建时就写死了）。还没有的话：
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   cat ~/.ssh/id_ed25519.pub   # 复制到 Vast.ai
   ```

5. **验证配置** —— 测试搜索能不能跑：
   ```bash
   vastai search offers 'gpu_ram>=24 reliability>0.95' -o 'dph+' --limit 3
   ```

## 告诉 ARIS 用 Vast.ai

在项目 `CLAUDE.md` 加：

```markdown
## Vast.ai
- gpu: vast                  # 从 vast.ai 按需租 GPU
- auto_destroy: true         # 实验跑完自动销毁（默认）
- max_budget: 5.00           # 可选：估算成本超过这个数会警告
```

不需要指定 GPU 型号或硬件配置。ARIS 读你的实验脚本/计划，估算 VRAM 和训练时间，然后给你这样的选项：

```
| # | GPU       | VRAM  | $/hr  | 预估时长 | 预估总价 | Offer ID |
|---|-----------|-------|-------|----------|----------|----------|
| 1 | RTX 4090  | 24 GB | $0.28 | ~4h      | ~$1.12   | 6995713  |  ← 性价比最高
| 2 | A100 SXM  | 80 GB | $0.95 | ~2h      | ~$1.90   | 7023456  |  ← 速度最快
```

选个数字，剩下的 ARIS 全包。

## 手动控制

如果想在 `/run-experiment` 流程之外单独租 GPU，用专门的 skill：

```
/vast-gpu                          # 交互式：搜索、挑选、租用
/vast-gpu list                     # 列出当前所有租用中的实例
/vast-gpu destroy <instance-id>    # 手动销毁
```

`auto_destroy: true` 让 `/run-experiment` 跑完后自动销毁实例；`false` 让实例保留，方便你 SSH 进去看结果。每次用完之后 `vastai show instances`（或 `/vast-gpu list`）确认一下没有静默扣费的实例。

## 大致花费

ARIS + Vast.ai 的典型工作负载：

- 小型消融实验（单 GPU，1–4 小时）：**~$0.30 – $2 / 次**，RTX 3090/4090
- 大点的 baseline 重跑（40–80 GB VRAM，多小时）：**~$2 – $10 / 次**，A100/H100
- Spot 价波动较大；`vastai search offers` 反映实时市场价

在 `CLAUDE.md` 设置 `max_budget`，ARIS 估算超过这个数会警告——不是硬阻断，而是租之前再确认。

## 没有服务器怎么办

Review 和改写类 skill（`/auto-review-loop`、`/research-review`、`/paper-writing`、`/paper-compile`）不受影响。只有需要跑实验的修复会跳过（标记为"需人工跟进"）。

## 相关 skill

- [`/vast-gpu`](../../skills/vast-gpu/SKILL.md) —— 直接租用控制
- [`/run-experiment`](../../skills/run-experiment/SKILL.md) —— 通过 `gpu: vast` 自动部署
- [`/monitor-experiment`](../../skills/monitor-experiment/SKILL.md) —— 从租用中的实例收集结果
