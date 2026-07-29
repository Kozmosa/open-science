# TEMPORARY: local-only architecture cleanup P0-P6

This directory contains disposable development guards for the architecture cleanup and Release E.
It is intentionally outside `tests/`, the repository pytest `testpaths`, `scripts/test.sh`,
`scripts/ci.sh`, and GitHub Actions. It must be deleted in P6.

- **Owner:** architecture cleanup P0-P6
- **Current phase:** P5 entry; P4 generated transport is closed and retained compatibility is
  explicitly handed to P5 pending canonical-client migration and reviewed zero-traffic evidence
- **Maximum lifetime:** through P6 only; delete the entire directory before P6 exits
- **Final deletion condition:** P6 architecture/documentation audit is complete and no normal test,
  CI entrypoint, workflow, or required check refers to these assets

## Run locally

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest \
  -c testing/architecture-cleanup/pytest.ini \
  testing/architecture-cleanup \
  -m architecture_cleanup \
  -n 0
```

## Lifecycle

| Asset | Owner | Introduced | Removal | Final state |
| --- | --- | --- | --- | --- |
| `architecture_baseline.json` | P0/P3 | P0 | P6 | delete |
| `backend_api_import_allowlist.json` | P2 | P0 | P2/P6 | delete |
| `frontend_layer_allowlist.json` | P5 | P0 | P5/P6 | delete |
| `transport_snapshot.json` | P4 | P0 | P6 | delete |
| `compatibility_inventory.json` | P0-P6 | P0 | P6 | delete |
| `compatibility_fields.json` | P4/P5 | P0 | P5/P6 | delete |
| `deletion_candidates.json` | P2 | P0 | P2/P6 | delete |
| `deprecated_contract_allowlist.json` | P4/P5 | P0 | P5/P6 | delete |
| `release_evidence.json` | P0/P1 | P0 | P6 | delete |
| `release_e_debt.json` | P1 | P1-A | P1-D/P6 | delete |
| `release_e_compatibility_budget.json` | P1/P4/P5 | P1-D | P5/P6 | delete |
| `support/` | P0-P6 | P0 | P6 | delete |
| `test_architecture_baseline.py` | P0-P3 | P0 | P6 | delete |
| `test_frontend_layers.py` | P0/P5 | P0 | P6 | delete |
| `test_transport_inventory.py` | P0/P4 | P0 | P6 | delete |
| `test_compatibility_inventory.py` | P0-P6 | P0 | P6 | delete |
| `test_local_only_contract.py` | P0-P6 | P0 | P6 | delete |
| `test_release_e_inventory.py` | P1 | P1-A | P6 | delete |
| `pytest.ini` | P1 | P1-A | P6 | delete |

Rules in `release_e_debt.json` are monotonic ceilings: implementation may reduce matches, but may
not add new files or occurrences. When a debt item is removed, update its status and evidence in the
same change. Do not regenerate the baseline to accept growth.

The backend and frontend allowlists are also monotonic: remove entries as dependencies are fixed,
and never add or rebase entries to make a regression pass. Import graph, public Interface, OpenAPI,
and route snapshots may change during an intentional cleanup slice, but the same review must explain
the delta and update the snapshot explicitly. Snapshot changes are not a substitute for expanding an
allowlist.

P4 intentionally retains compatibility fields and route aliases for the first generated-contract
cut. Their existing owner, telemetry, deadline, and removal evidence remain recorded in the
compatibility inventories; generated adoption does not authorize deleting them in the same slice.
The generated contract and normal CI drift gate live outside this local-only directory under
`frontend/src/generated/transport/` and `scripts/ci.sh`.

P5 owns the retained protocol surfaces after that first cut. A generated type existing is not
removal evidence: callers and mock adapters must use the canonical operation, and release telemetry
must prove zero deprecated route/field usage for a reviewed observation window. The production gaps
in `release_evidence.json` therefore remain fail-closed deletion blockers, not implied zero traffic.
