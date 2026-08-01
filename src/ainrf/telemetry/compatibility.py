"""Bounded compatibility telemetry behind a small observation Interface."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

import structlog

from ainrf.telemetry.metrics import inc_counter, observe_histogram, set_gauge

Surface = Literal["canonical", "compat_root", "compat_v1", "external_compatible", "non_product"]
_LOG = structlog.get_logger("compatibility_telemetry")
_SURFACES: Final = frozenset(
    {"canonical", "compat_root", "compat_v1", "external_compatible", "non_product"}
)
_METHODS: Final = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})
_EXTERNAL_COMPATIBLE_PATHS: Final = frozenset({"/v1/models", "/v1/messages"})
_NON_PRODUCT_PATHS: Final = frozenset(
    {"/health", "/metrics", "/api/metrics", "/v1/metrics", "/docs", "/redoc", "/openapi.json"}
)
_RETENTION_DAYS: Final = 180


@dataclass(frozen=True, slots=True)
class HttpContractObservation:
    actual_path: str
    operation: str
    method: str
    status: int
    duration_seconds: float
    allowed_operations: frozenset[str]
    state_root: Path
    request_id: str | None = None


def classify_surface(path: str) -> Surface:
    if path in _EXTERNAL_COMPATIBLE_PATHS:
        return "external_compatible"
    if path.startswith("/api/"):
        return "canonical"
    if path.startswith("/v1/"):
        return "compat_v1"
    if path in _NON_PRODUCT_PATHS or path.startswith(("/assets/", "/static/")):
        return "non_product"
    if path.startswith("/") and path != "/":
        return "compat_root"
    return "non_product"


def status_class(status: int) -> str:
    value = status // 100
    return f"{value}xx" if value in {2, 3, 4, 5} else "unknown"


def observe_http_contract(observation: HttpContractObservation) -> None:
    method = observation.method.upper()
    if method not in _METHODS:
        method = "OTHER"
    operation = (
        observation.operation
        if observation.operation in observation.allowed_operations
        else "unmatched"
    )
    surface = classify_surface(observation.actual_path)
    if operation == "unmatched" and surface != "external_compatible":
        surface = "non_product"
    labels = {
        "surface": surface,
        "operation": operation,
        "method": method,
        "status_class": status_class(observation.status),
    }
    try:
        inc_counter("ainrf_http_contract_requests_total", labels)
        observe_histogram(
            "ainrf_http_contract_request_duration_seconds",
            observation.duration_seconds,
            {key: labels[key] for key in ("surface", "operation", "method")},
        )
    except Exception as exc:  # telemetry must not alter the response
        _latch_failure(observation.state_root, "prometheus_update", exc)
    try:
        _persist_http_observation(observation.state_root, labels)
        set_gauge(
            "ainrf_http_contract_telemetry_delivery_failure_latched",
            1 if _failure_latch_path(observation.state_root).exists() else 0,
        )
    except Exception as exc:
        _latch_failure(observation.state_root, "durable_aggregate", exc)
    _LOG.info(
        "http_contract_observed",
        request_id=observation.request_id,
        surface=surface,
        operation=operation,
        method=method,
        status_class=labels["status_class"],
    )


def durable_http_observations(state_root: Path) -> list[dict[str, object]]:
    path = _store_path(state_root)
    if not path.is_file():
        return []
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT bucket_date, surface, operation, method, status_class, count, "
            "first_seen_at, last_seen_at FROM http_contract_daily ORDER BY bucket_date, surface, operation"
        ).fetchall()
    return [dict(row) for row in rows]


def _store_path(state_root: Path) -> Path:
    return state_root / "runtime" / "compatibility_telemetry.sqlite3"


def _failure_latch_path(state_root: Path) -> Path:
    return state_root / "runtime" / "compatibility_telemetry_delivery_failure.json"


def _connect(state_root: Path) -> sqlite3.Connection:
    runtime = state_root / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(_store_path(state_root), timeout=5.0, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS http_contract_daily (
            bucket_date TEXT NOT NULL,
            surface TEXT NOT NULL,
            operation TEXT NOT NULL,
            method TEXT NOT NULL,
            status_class TEXT NOT NULL,
            count INTEGER NOT NULL CHECK (count >= 0),
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            PRIMARY KEY(bucket_date, surface, operation, method, status_class)
        );
        """
    )
    return connection


def _persist_http_observation(state_root: Path, labels: dict[str, str]) -> None:
    now = datetime.now(UTC)
    cutoff = (now - timedelta(days=_RETENTION_DAYS)).date().isoformat()
    with _connect(state_root) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """INSERT INTO http_contract_daily
            (bucket_date, surface, operation, method, status_class, count, first_seen_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(bucket_date, surface, operation, method, status_class) DO UPDATE SET
              count = count + 1, last_seen_at = excluded.last_seen_at""",
            (now.date().isoformat(), *labels.values(), now.isoformat(), now.isoformat()),
        )
        connection.execute("DELETE FROM http_contract_daily WHERE bucket_date < ?", (cutoff,))
        connection.commit()


def _latch_failure(state_root: Path, stage: str, error: Exception) -> None:
    try:
        runtime = state_root / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        _failure_latch_path(state_root).write_text(
            json.dumps(
                {
                    "latched_at": datetime.now(UTC).isoformat(),
                    "stage": stage,
                    "error_type": type(error).__name__,
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
    set_gauge("ainrf_http_contract_telemetry_delivery_failure_latched", 1)
    _LOG.error(
        "compatibility_telemetry_delivery_failed", stage=stage, error_type=type(error).__name__
    )
