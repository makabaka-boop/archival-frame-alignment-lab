"""Shared pytest configuration and brute-force oracle.

The acceptance suite talks to the API exclusively over HTTP (no imports from
the application), mirroring how a restorer would use it.  Small cases are
cross-checked against an independent, deliberately straightforward O(n*m)
dynamic program that also implements the lexicographic tie-break.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import httpx
import pytest

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
TIMEOUT = httpx.Timeout(30.0)


@pytest.fixture(scope="session")
def client() -> httpx.Client:
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as c:
        yield c


@pytest.fixture(scope="session", autouse=True)
def _wait_for_api(client: httpx.Client) -> None:
    last: Exception | None = None
    for _ in range(60):
        try:
            response = client.get("/health")
            if response.status_code == 200:
                return
        except httpx.TransportError as exc:
            last = exc
    raise RuntimeError(f"API at {BASE_URL} never became healthy: {last}")


def create_project(client: httpx.Client, left: list[str], right: list[str]) -> dict:
    response = client.post("/api/projects", json={"left": left, "right": right})
    assert response.status_code == 201, response.text
    return response.json()


def set_anchors(
    client: httpx.Client, project_id: int, anchors: list[list[int]]
) -> httpx.Response:
    return client.put(
        f"/api/projects/{project_id}/anchors", json={"anchors": anchors}
    )


# ---------------------------------------------------------------------------
# Brute-force oracle
# ---------------------------------------------------------------------------


def _best_gap(
    left: Sequence[str],
    right: Sequence[str],
    lo_i: int,
    hi_i: int,
    lo_j: int,
    hi_j: int,
) -> list[tuple[int, int]]:
    """Optimal pairs with lo_i < i < hi_i and lo_j < j < hi_j.

    Standard LCS DP; when extending, keep the lexicographically smallest pair
    sequence among equal-length alternatives.
    """

    rows = hi_i - lo_i - 1
    cols = hi_j - lo_j - 1
    # dp[r][c] = best pair list for first r left slots / c right slots.
    dp: list[list[list[tuple[int, int]]]] = [
        [[] for _ in range(cols + 1)] for _ in range(rows + 1)
    ]
    for r in range(1, rows + 1):
        i = lo_i + r
        for c in range(1, cols + 1):
            j = lo_j + c
            if left[i] == right[j]:
                candidate = dp[r - 1][c - 1] + [(i, j)]
            else:
                candidate = []
            up, left_cell = dp[r - 1][c], dp[r][c - 1]
            best = max(
                (candidate, up, left_cell),
                key=lambda seq: (len(seq), _neg_lex(seq)),
            )
            dp[r][c] = list(best)
    return dp[rows][cols]


def _neg_lex(seq: list[tuple[int, int]]) -> tuple:
    # max() wants a key; prefer longer then lexicographically smaller list.
    return tuple(-p for pair in seq for p in pair)


def brute(
    left: Sequence[str],
    right: Sequence[str],
    anchors: Sequence[tuple[int, int]] | None = None,
) -> list[list[int]]:
    """Reference solution using the gap decomposition explicitly."""

    chain = sorted(anchors or [])
    bounds: list[tuple[int, int, int, int]] = []
    prev_i, prev_j = -1, -1
    for ai, aj in chain:
        bounds.append((prev_i, ai, prev_j, aj))
        prev_i, prev_j = ai, aj
    bounds.append((prev_i, len(left), prev_j, len(right)))

    out: list[list[int]] = []
    for idx, (lo_i, hi_i, lo_j, hi_j) in enumerate(bounds):
        for i, j in _best_gap(left, right, lo_i, hi_i, lo_j, hi_j):
            out.append([i, j])
        if idx < len(chain):
            out.append([chain[idx][0], chain[idx][1]])
    return out
