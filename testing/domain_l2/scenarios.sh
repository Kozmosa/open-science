#!/usr/bin/env bash
# Scenario choreography for the trusted L2 recovery cell.
#
# The scenario image is an immutable, separately-built test artifact.  It
# must expose `/opt/openscience-l2/run-scenario <scenario> <phase>` and fail
# when its assertions are not actually executed.  Keeping test logic in that
# image prevents a source bind mount from turning L2 into a mutable staging
# environment.

set -euo pipefail

readonly L2_SCENARIOS=(
  "backup-migration-restart-reconcile-restore"
  "importer-crash-resume"
  "double-dispatcher-claim-expiry"
  "launch-after-crash"
  "literature-saga-crash-recovery"
  "prior-frontend-artifact-contract"
)

l2_run_scenario() {
  local scenario="$1"
  local phase="$2"
  l2_compose exec -T scenario-runner \
    /opt/openscience-l2/run-scenario "${scenario}" "${phase}"
}

l2_mark_scenario_passed() {
  local scenario="$1"
  printf '%s\tpassed\n' "${scenario}" >> "${OPENSCIENCE_L2_SCENARIO_RESULTS}"
}

run_l2_scenarios() {
  # The runner creates only synthetic/de-identified legacy state.  It verifies
  # that a backup can migrate, survive a service restart, reconcile, and be
  # restored into a new generation before declaring this scenario passed.
  l2_run_scenario "backup-migration-restart-reconcile-restore" "prepare"
  l2_compose restart api domain-worker
  l2_run_scenario "backup-migration-restart-reconcile-restore" "verify"
  l2_mark_scenario_passed "backup-migration-restart-reconcile-restore"

  # The runner causes a deliberate importer interruption after a committed
  # checkpoint, then verifies a fresh process resumes the same run.
  l2_run_scenario "importer-crash-resume" "run"
  l2_mark_scenario_passed "importer-crash-resume"

  # Scaling only the no-port worker service exercises CAS/lease recovery.
  # No host process, shared staging service, or Docker socket participates.
  l2_compose up -d --scale domain-worker=2
  l2_run_scenario "double-dispatcher-claim-expiry" "run"
  l2_compose up -d --scale domain-worker=1
  l2_mark_scenario_passed "double-dispatcher-claim-expiry"

  # The scenario arms a deterministic launch key, kills only this cell's
  # worker, then asserts probe/adopt or terminal launch_unknown — never a
  # blind replacement runtime.
  l2_run_scenario "launch-after-crash" "prepare"
  l2_compose kill domain-worker
  l2_compose up -d --scale domain-worker=1
  l2_run_scenario "launch-after-crash" "verify"
  l2_mark_scenario_passed "launch-after-crash"

  # B9 must survive the cross-database boundary after Task creation and before
  # Literature link completion.  `prepare` creates a synthetic research-task
  # intent and arms a deterministic crash at that boundary; recovery is only
  # allowed to reuse the original idempotency key/Task.  The verify phase must
  # prove exactly one Task, a completed Literature link, and no pending intent
  # or outbox item after the replacement worker starts.
  l2_run_scenario "literature-saga-crash-recovery" "prepare"
  l2_compose kill domain-worker
  l2_compose up -d --scale domain-worker=1
  l2_run_scenario "literature-saga-crash-recovery" "verify"
  l2_mark_scenario_passed "literature-saga-crash-recovery"

  # The actual previous-production frontend artifact is served through the
  # immutable same-origin gateway.  The runner verifies its embedded artifact
  # SHA, requests its real /api route through that gateway, and validates the
  # candidate backend response rather than accepting a mocked old client.
  l2_run_scenario "prior-frontend-artifact-contract" "run"
  l2_mark_scenario_passed "prior-frontend-artifact-contract"
}
