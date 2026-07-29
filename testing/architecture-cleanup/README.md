# TEMPORARY: local-only architecture cleanup P0-P6

This directory contains disposable development guards for the architecture cleanup and Release E.
It is intentionally outside `tests/`, the repository pytest `testpaths`, `scripts/test.sh`,
`scripts/ci.sh`, and GitHub Actions. It must be deleted in P6.

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
| `release_e_debt.json` | P1 | P1-A | P1-D/P6 | delete |
| `release_e_compatibility_budget.json` | P1 | P1-D | P4/P6 | delete |
| `test_release_e_inventory.py` | P1 | P1-A | P6 | delete |
| `pytest.ini` | P1 | P1-A | P6 | delete |

Rules in `release_e_debt.json` are monotonic ceilings: implementation may reduce matches, but may
not add new files or occurrences. When a debt item is removed, update its status and evidence in the
same change. Do not regenerate the baseline to accept growth.
