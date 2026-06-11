# Vast.ai On-Demand GPU Integration

> 🇨🇳 中文版：[VAST_GPU_GUIDE_CN.md](VAST_GPU_GUIDE_CN.md)
> Part of the ARIS [GPU Server Setup](../../README.md#%EF%B8%8F-setup) options. Use this when you don't own a GPU server.

ARIS supports renting GPUs on demand from [Vast.ai](https://vast.ai) — the cheapest spot-rental marketplace for ML hardware. When you run `/run-experiment`, ARIS **analyzes your training task** (model size, dataset, estimated time), searches for the cheapest GPU that fits the workload, and presents options ranked by **estimated total cost** (not just $/hr). After you pick, it handles everything: rent → setup → run → collect results → destroy.

## When to use this vs. `gpu: remote` / `gpu: local`

| Option | When | Cost model |
|--------|------|------------|
| `gpu: remote` | You own (or your lab provides) a fixed SSH-accessible server | Sunk cost; ARIS treats it as free |
| `gpu: local` | You're already on the GPU host | Sunk cost; no SSH overhead |
| `gpu: vast` | No GPU, or you need bigger hardware than what you own for one experiment | Per-hour rental, auto-billed by Vast.ai |

Vast.ai works for one-off ablations, baseline reruns, or scaling up to A100/H100 for a single experiment. Not ideal for week-long training jobs — at that point a dedicated server is cheaper.

## Prerequisites

1. **Create a Vast.ai account** at https://cloud.vast.ai/ and add billing (credit card or crypto).

2. **Install the `vastai` CLI** (requires **Python ≥ 3.10**):
   ```bash
   pip install vastai
   ```
   If your Python is older (check with `python --version`), use a virtual environment with Python ≥ 3.10 (e.g., `conda create`, `pyenv`, `uv venv`).

3. **Set your API key** — get it from https://cloud.vast.ai/cli/:
   ```bash
   vastai set api-key YOUR_API_KEY
   ```

4. **Upload your SSH public key** at https://cloud.vast.ai/manage-keys/ — this is **required before renting any instance** (keys are baked in at creation time). If you don't have one:
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   cat ~/.ssh/id_ed25519.pub   # copy this to Vast.ai
   ```

5. **Verify setup** — test that search works:
   ```bash
   vastai search offers 'gpu_ram>=24 reliability>0.95' -o 'dph+' --limit 3
   ```

## Tell ARIS to use Vast.ai

Add to your project's `CLAUDE.md`:

```markdown
## Vast.ai
- gpu: vast                  # rent on-demand GPU from vast.ai
- auto_destroy: true         # auto-destroy after experiment completes (default)
- max_budget: 5.00           # optional: warn if estimated cost exceeds this
```

That's it — no GPU model or hardware config needed. ARIS reads your experiment scripts/plan, estimates VRAM and training time, then presents options:

```
| # | GPU       | VRAM  | $/hr  | Est. Hours | Est. Total | Offer ID |
|---|-----------|-------|-------|------------|------------|----------|
| 1 | RTX 4090  | 24 GB | $0.28 | ~4h        | ~$1.12     | 6995713  |  ← best value
| 2 | A100 SXM  | 80 GB | $0.95 | ~2h        | ~$1.90     | 7023456  |  ← fastest
```

Pick a number and ARIS handles the rest.

## Manual control

For one-off rentals outside the `/run-experiment` flow, use the dedicated skill:

```
/vast-gpu                          # interactive — search, pick, rent
/vast-gpu list                     # list your current rented instances
/vast-gpu destroy <instance-id>    # tear down manually
```

`auto_destroy: true` will tear instances down after `/run-experiment` finishes; `false` leaves them up so you can SSH in and inspect. Always run `vastai show instances` (or `/vast-gpu list`) after a session to confirm nothing is silently billing you.

## Cost expectations

Typical ARIS workloads with Vast.ai:

- Small ablation (single-GPU, 1–4 hours): **~$0.30 – $2 / run** on RTX 3090/4090
- Bigger baseline rerun (40–80 GB VRAM, multi-hour): **~$2 – $10 / run** on A100/H100
- Spot-prices fluctuate; `vastai search offers` reflects live market rates

Set `max_budget` in `CLAUDE.md` to get a warning when ARIS's estimate exceeds your comfort zone — it doesn't hard-block, just confirms before renting.

## Fallback: no server at all

The review and rewriting skills (`/auto-review-loop`, `/research-review`, `/paper-writing`, `/paper-compile`) still work without GPU access. Only experiment-related fixes will be skipped (flagged for manual follow-up).

## Related skills

- [`/vast-gpu`](../../skills/vast-gpu/SKILL.md) — direct rental control
- [`/run-experiment`](../../skills/run-experiment/SKILL.md) — auto-deploy via `gpu: vast`
- [`/monitor-experiment`](../../skills/monitor-experiment/SKILL.md) — collect results from running rentals
