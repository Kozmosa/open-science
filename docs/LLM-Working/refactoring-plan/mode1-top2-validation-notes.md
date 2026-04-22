# Mode1 Top2 Idea Validation Notes

## Context

This note tracks the exploration milestones, design changes, and key findings while validating the top2 ideas selected from Mode1:
- DynHG-LLM
- FedST-LLM

The goal is traceability: every milestone, stop/go gate, and mechanism-level finding should remain reviewable after the session.

## Milestone Log

### M0: Planning and environment check
- Confirmed local environment has PyTorch, Transformers, CUDA, and 4 × A800 GPUs available.
- Confirmed Mode1 does not contain ready-to-run traffic benchmark code or dataset loaders.
- Decision: start from synthetic mechanism-level pilots before investing in real-data bridge work.

### M1: Initial experiment plan freeze
- Wrote claim-driven experiment roadmap in `refine-logs/EXPERIMENT_PLAN.md`.
- Split work into synthetic signal stage and later real-data bridge stage.
- Defined stop/go criteria:
  - DynHG must beat pairwise baseline while reducing communication.
  - FedST must beat FedAvg and stay near centralized upper bound.

### M2: First pilot implementation
- Implemented `experiments/run_top2_pilots.py`.
- Built synthetic generators:
  - DynHG synthetic environment with explicit higher-order interaction terms.
  - FedST synthetic environment with cross-client coupling and privacy-preserving aggregation.
- Added baselines for both ideas plus novelty-isolation variants.

### M3: First pilot findings
- DynHG result: communication collapsed to extreme sparsity and accuracy regressed.
- FedST result: positive signal over FedAvg and near centralized performance.
- Decision:
  - DynHG: do not move to real-data bridge yet.
  - FedST: continue strengthening mechanism and baselines.

### M4: Round-2 refinement direction
- DynHG changes planned:
  - controlled participation instead of unconstrained soft gating
  - residual hyperedge mixing
  - communication/accuracy balance target instead of pure sparsity push
- FedST changes planned:
  - stronger synthetic coupling
  - client-level hypergraph context in addition to pairwise client graph
  - stronger federated baseline (FedProx)
  - optional frontier encoder check

### M5: Second pilot execution and revised findings
- Re-ran pilots with the refined script and wrote `experiments/results/top2_pilot_results_round2.json` / `.md`.
- DynHG result worsened despite fixing the earlier near-zero communication collapse:
  - communication ratio moved from ~0.01 to ~0.17
  - MAE still regressed further to 0.3235 vs pairwise 0.2422
- Interpretation:
  - the original failure was not only sparsity collapse
  - the current local hyperedge aggregation path is likely misaligned with the synthetic task, so simply constraining participation is insufficient
- FedST result became more informative but also exposed a sharper limitation:
  - FedST improved over FedAvg by 15.0%
  - FedST improved over FedProx by only 1.45%
  - FedST remained far worse than centralized upper bound (gap ~174.9%)
- Interpretation:
  - client-level context is real signal, because removing context or replacing it with a larger head degrades performance
  - but the federated interface is still too weak to preserve the strong global coupling embedded in the harder synthetic task
- Decision:
  - DynHG remains blocked at mechanism level and should not proceed to real-data bridge before redesign
  - FedST remains promising but should be reframed as “better than plain FL baselines” rather than “near-centralized” until the interface improves

### M6: Third-round redesign and sweep
- DynHG redesign:
  - switched to non-overlapping canonical hyperedge families
  - made pairwise path the primary prediction path
  - changed hypergraph branch into a small residual correction instead of the main carrier
  - added `DynHG no-hyper correction` and `DynHG random mask` for direct novelty isolation
- FedST redesign:
  - reduced default coupling to a moderate regime for the main pilot
  - changed exchanged context from a single mixed vector to explicit pair-context + hyper-context parts
  - added coupling sweep across `0.2 / 0.3 / 0.4`
- Result summary:
  - DynHG nearly recovered to pairwise level but still failed to become positive
  - FedST became much more convincing in the moderate-coupling regime and nearly matched centralized

### M7: Go/hold consolidation and bridge preparation
- DynHG conclusion stabilized:
  - no longer catastrophic
  - still not better than pairwise or static hypergraph
  - should be treated as HOLD unless a future deterministic correction beats the current best baseline
- FedST conclusion stabilized:
  - in moderate coupling (`0.3`), FedST beats both FedAvg and FedProx
  - centralized gap shrinks to about `2.54%`
  - this is now strong enough to justify bridge planning
- Added `experiments/bridge_plan.md` to define the next real-data bridge protocol for client partitioning on traffic datasets.

### M8: FedST bridge utility and 5-seed confidence run
- Implemented `experiments/prepare_fedst_bridge.py`.
- Generated first bridge artifacts under `experiments/results/bridge/`:
  - `client_partitions.json`
  - `client_graph.json`
  - `client_hypergraph.json`
  - `locality_partition_placeholder.json`
- Ran a higher-confidence 5-seed validation for FedST at moderate coupling (`0.3`).
- Result summary:
  - FedST vs FedAvg: `+6.62%`
  - FedST vs FedProx: `+3.94%`
  - FedST gap to centralized: `2.86%`
- Interpretation:
  - the scoped FedST story holds under more seeds
  - current evidence is strong enough to move from synthetic-only validation toward real-data smoke tests

### M9: Real-data smoke path activated
- User provided real traffic H5 files:
  - `test/Mode1/metr-la.h5`
  - `test/Mode1/pems-bay.h5`
- Confirmed both files are valid HDF5 traffic tables and readable with pandas.
- Upgraded `experiments/run_fedst_bridge_smoke.py` to support raw H5 input directly.
- Executed smoke runs on both real datasets.
- Result summary:
  - the bridge path is now operational on real data
  - but the current smoke baseline is too weak, and the method deltas are nearly identical across local/FedAvg/FedProx/FedST
- Decision:
  - FedST remains promising
  - but the next necessary step is no longer plumbing, it is a stronger learned real-data bridge experiment

### M10: Learned real-data bridge result
- Implemented `experiments/run_fedst_bridge_learned.py`.
- First GPU attempt failed due to OOM, then the runner was refactored into a lighter CPU-safe version.
- Ran learned real-data validation on:
  - `metr-la.h5`
  - `pems-bay.h5`
- Result summary:
  - On METR-LA, FedST lost to both FedAvg and FedProx.
  - On PEMS-BAY, FedST also lost to both FedAvg and FedProx.
- Interpretation:
  - the earlier synthetic advantage does not transfer under the current learned real-data bridge design
  - this is the first stronger evidence against immediate real-data viability of the current FedST formulation
- Decision:
  - FedST is no longer in a simple GO state
  - it should be treated as **REVISE BEFORE SCALE-UP**

### M11: Deep correction and revised real-data test
- Researched corrective directions and revised the paper story toward locality-aware personalized federated traffic forecasting.
- Updated bridge preparation to support `correlation-balanced` partitions from H5 traffic data.
- Re-ran the learned bridge on `METR-LA` with the revised locality-aware partition.
- Result summary:
  - revised FedST still lost to both FedAvg and FedProx on real `METR-LA`
- Interpretation:
  - the failure is deeper than random partitioning alone
  - even after correcting the client definition and relation sparsity, the current idea family still does not produce a positive real-data result
- Decision:
  - stop scaling the current FedST family
  - archive it as a negative result unless a substantially different mechanism is proposed

## Hypotheses Under Test

### DynHG-LLM
- H1: higher-order local hyperedges help on data with explicit group interactions.
- H2: controlled participation can reduce communication without destroying hypergraph benefit.
- Failure mode to watch: mask collapse or over-pruning.
- New evidence after M5: even after reducing over-pruning, the current hyperedge message path still harms prediction, so the issue is likely architectural rather than purely regularization-related.
- New evidence after M6: once hypergraph is reduced to a correction path, performance returns near pairwise level, which suggests the hypergraph branch is no longer harmful but still not uniquely useful.
- New evidence after M8/M9/M10/M11: no new positive evidence; DynHG remains out of the main execution path.

### FedST-LLM
- H1: client-level spatial context helps beyond plain FedAvg.
- H2: the gain is not explained by a bigger head alone.
- Failure mode to watch: context interface too weak to outperform stronger FL baselines.
- New evidence after M5: H1 and H2 still look positive, but “near centralized” is not currently supported under stronger cross-client coupling.
- New evidence after M6: H1 and H2 remain positive, and near-centralized behavior is recovered in a moderate-coupling regime, but not uniformly across all coupling strengths.
- New evidence after M8: the moderate-coupling result remains stable under 5 seeds and still beats both FedAvg and FedProx.
- New evidence after M9: real-data smoke path works, but current smoke formulation is too weak to produce decisive deltas.
- New evidence after M10: a stronger learned real-data bridge currently fails to beat FedAvg / FedProx on both METR-LA and PEMS-BAY.
- New evidence after M11: even the revised locality-aware partition / sparse-region formulation still fails on real METR-LA.

## Key Findings So Far

### DynHG-LLM
- Positive findings:
  - The communication lever is controllable.
  - A pairwise-main + hyperedge-correction architecture removes most of the earlier degradation.
- Negative findings:
  - Current DynHG pilot still underperforms pairwise baseline by about `1.2%`.
  - Static hypergraph and no-hyper correction remain slightly better than the learned DynHG correction branch.
- Current conclusion:
  - DynHG is no longer catastrophically broken, but it still lacks a positive mechanism signal.
  - The current evidence does not justify a real-data bridge yet.

### FedST-LLM
- Positive findings:
  - FedST > FedAvg in synthetic moderate-coupling settings
  - FedST > FedProx in synthetic moderate-coupling settings
  - FedST > no-context ablation
  - FedST > bigger-head-no-context ablation
  - Real traffic H5 data has been verified and is bridge-compatible.
- Negative findings:
  - The benefit is sensitive to coupling regime even in synthetic data.
  - In the first learned real-data bridge, FedST loses to both FedAvg and FedProx on METR-LA and PEMS-BAY.
  - In the revised locality-aware real-data bridge, FedST still loses to both FedAvg and FedProx on METR-LA.
- Current conclusion:
  - FedST remains an interesting research direction, but the current family of implementations is **not supported by real-data evidence**.
  - The strongest honest statement now is: synthetically promising, real-data negative under multiple increasingly realistic tests.

## Current Stop/Go Decisions

### DynHG-LLM
- Status: **HOLD**
- Reason:
  - no positive mechanism win yet
  - real-data bridge would be premature
- Next gate:
  - only continue if a redesign can beat pairwise and static hypergraph on synthetic data first

### FedST-LLM
- Status: **STOP CURRENT FAMILY**
- Reason:
  - synthetic results are promising
  - but both the original and corrected real-data bridges currently fail against strong FL baselines
- Next gate:
  - only revisit if proposing a materially different mechanism, not another small tweak

## Next Redesign Directions

### DynHG next redesign
- Try a deterministic, hand-crafted correction path first:
  - fixed top-k participation
  - no learned gate
  - direct comparison against current learned correction branch
- If still negative, pause DynHG and do not spend more real-data budget on it yet.

### FedST next redesign
- Only continue with a truly different mechanism family, for example:
  - hierarchical FL with explicit region coordinators
  - boundary-edge message passing rather than client-summary exchange
  - personalization without explicit region graph sharing
- Do not continue scaling the current FedST family.

## Traceability Pointers

- Experiment plan: `refine-logs/2026-04-22_experiment_plan.md`
- Experiment tracker: `refine-logs/2026-04-22_experiment_tracker.md`
- First pilot summary: `refine-logs/2026-04-22_pilot_results.md`
- Second pilot raw results: `experiments/results/top2_pilot_results_round2.json`
- Third pilot raw results: `experiments/results/top2_pilot_results_round3.json`
- 5-seed FedST summary: `refine-logs/2026-04-22_fedst_multiseed_round5.md`
- Real-data smoke summary: `refine-logs/2026-04-22_fedst_realdata_smoke.md`
- Learned real-data summary: `refine-logs/2026-04-22_fedst_learned_bridge_results.md`
- Revised-method memo: `refine-logs/2026-04-22_fedst_revision_memo.md`
- Revised experiment plan: `refine-logs/2026-04-22_fedst_revised_experiment_plan.md`
- Revised real-data result: `refine-logs/2026-04-23_fedst_revised_realdata_results.md`
- Bridge prep note: `experiments/bridge_plan.md`
- Bridge utility: `experiments/prepare_fedst_bridge.py`
- Real-data smoke runner: `experiments/run_fedst_bridge_smoke.py`
- Learned real-data runner: `experiments/run_fedst_bridge_learned.py`
- Executable synthetic script: `experiments/run_top2_pilots.py`

## Working Rules for Further Exploration

- Every milestone change must be appended here before or alongside new pilot runs.
- Every result used for a decision must be written both as raw artifact and as interpreted note.
- Real-data bridge should only start after synthetic stop/go gates become clearly positive.
