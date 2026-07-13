"""TaskAttempt admission boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainrf.domain import AttemptService
from ainrf.domain_control import DomainCutoverError

pytestmark = [pytest.mark.unit, pytest.mark.db_race]


def test_attempt_repository_has_no_public_attempt_creation_path() -> None:
    """Only TaskApplicationService may create Tasks, Attempts, and outbox rows."""

    assert not hasattr(AttemptService, "create_attempt")


def test_attempt_repository_rejects_direct_claims_before_v2_cutover(state_root: Path) -> None:
    attempts = AttemptService(state_root)

    with pytest.raises(DomainCutoverError, match="committed v2 artifact and cutover fuse"):
        attempts.claim_next("direct-legacy-dispatcher")
