"""API latency benchmarks using pytest-benchmark.

Usage:
  uv run pytest scripts/perf/backend/benchmark_api.py --benchmark-only
  uv run pytest scripts/perf/backend/benchmark_api.py --benchmark-only --benchmark-min-rounds=10 --benchmark-max-time=0.5 --benchmark-json=.cache/perf-report/YYYY-MM-DD/api-benchmark.json

Requires a running OpenScience server at http://127.0.0.1:8000 with a test admin user.
"""

from __future__ import annotations

import os

import httpx
import pytest

BASE_URL = os.environ.get("AINRF_PERF_BASE_URL", "http://127.0.0.1:8000")
ADMIN_USER = os.environ.get("AINRF_PERF_USER", "perf-admin")
ADMIN_PASS = os.environ.get("AINRF_PERF_PASS", "perf-test-pass")


def _admin_headers(client: httpx.Client) -> dict[str, str]:
    """Get admin JWT headers, registering the perf user if needed."""
    # Try login
    resp = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    if resp.status_code == 200:
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    # Register then try again
    client.post(
        f"{BASE_URL}/auth/register",
        json={
            "username": ADMIN_USER,
            "display_name": "Perf Admin",
            "password": ADMIN_PASS,
        },
    )
    resp2 = client.post(
        f"{BASE_URL}/auth/login",
        json={"username": ADMIN_USER, "password": ADMIN_PASS},
    )
    if resp2.status_code != 200:
        pytest.skip(
            f"Cannot authenticate perf user (server may require manual activation): {resp2.text}"
        )
    return {"Authorization": f"Bearer {resp2.json()['access_token']}"}


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=30) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    return _admin_headers(client)


# --- Auth endpoints ---


def test_login(benchmark, client):
    benchmark(
        lambda: client.post(
            f"{BASE_URL}/auth/login",
            json={"username": ADMIN_USER, "password": ADMIN_PASS},
        )
    )


def test_auth_me(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/auth/me", headers=auth_headers))


# --- Project endpoints ---


def test_list_projects(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/projects", headers=auth_headers))


def test_list_tasks(benchmark, client, auth_headers):
    benchmark(
        lambda: client.get(
            f"{BASE_URL}/projects/default/tasks", headers=auth_headers
        )
    )


def test_list_task_edges(benchmark, client, auth_headers):
    benchmark(
        lambda: client.get(
            f"{BASE_URL}/projects/default/task-edges", headers=auth_headers
        )
    )


# --- File endpoints ---


def test_file_list(benchmark, client, auth_headers):
    benchmark(
        lambda: client.get(
            f"{BASE_URL}/files/list?environment_id=env-localhost&path=/",
            headers=auth_headers,
        )
    )


# --- Session endpoints ---


def test_list_sessions(benchmark, client, auth_headers):
    benchmark(lambda: client.get(f"{BASE_URL}/sessions", headers=auth_headers))


# --- Task creation ---


def test_create_task_minimal(benchmark, client, auth_headers):
    payload = {
        "project_id": "default",
        "workspace_id": "workspace-default",
        "environment_id": "env-localhost",
        "task_profile": "claude-code",
        "task_input": "benchmark",
        "title": "perf-bench-task",
    }
    benchmark(
        lambda: client.post(
            f"{BASE_URL}/tasks", json=payload, headers=auth_headers
        )
    )
