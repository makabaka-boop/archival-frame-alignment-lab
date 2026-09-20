"""Worst-case performance and validation limits (3-second contract)."""

from __future__ import annotations

import time

from conftest import create_project, set_anchors

N = 20_000
LIMIT_SECONDS = 3.0


def test_max_size_identical_scans_under_three_seconds(client):
    scans = [f"fp{i}" for i in range(N)]
    start = time.perf_counter()
    project = create_project(client, scans, list(scans))
    elapsed = time.perf_counter() - start
    assert elapsed < LIMIT_SECONDS, f"took {elapsed:.2f}s"
    assert project["length"] == N
    assert project["result"][0] == [0, 0]
    assert project["result"][-1] == [N - 1, N - 1]


def test_max_size_four_way_duplicates_under_three_seconds(client):
    # Only 5000 distinct values, each appearing exactly 4 times per side:
    # 80_000 matching pairs, the densest possible instance.
    values = [f"v{i}" for i in range(N // 4)]
    scans = [v for v in values for _ in range(4)]
    assert len(scans) == N

    start = time.perf_counter()
    project = create_project(client, scans, list(reversed(scans)))
    elapsed = time.perf_counter() - start
    assert elapsed < LIMIT_SECONDS, f"took {elapsed:.2f}s"
    assert 1 <= project["length"] <= N

    # Replacing with a large anchor chain must also meet the contract.
    full = create_project(client, scans, list(scans))
    anchors = [[4 * k, 4 * k] for k in range(N // 4)]
    start = time.perf_counter()
    response = set_anchors(client, full["id"], anchors)
    elapsed = time.perf_counter() - start
    assert response.status_code == 200, response.text
    assert elapsed < LIMIT_SECONDS, f"anchoring took {elapsed:.2f}s"
    body = response.json()
    for pair in anchors:
        assert pair in body["result"]
    assert body["length"] == N


def test_repeated_longest_common_block(client):
    # Four identical runs on each side => 80_000 pairs and length N.
    block = [f"x{i}" for i in range(5000)]
    scans = block * 4
    project = create_project(client, scans, list(scans))
    assert project["length"] == N
    assert project["result"] == [[i, i] for i in range(N)]


def test_input_limits_rejected(client):
    good = ["a"]
    empty: list[str] = []
    assert client.post(
        "/api/projects", json={"left": empty, "right": good}
    ).status_code == 422

    too_big = ["a"] * (N + 1)
    assert client.post(
        "/api/projects", json={"left": too_big, "right": good}
    ).status_code == 422

    # fingerprint longer than 32 chars
    assert client.post(
        "/api/projects", json={"left": ["a" * 33], "right": good}
    ).status_code == 422
    # empty fingerprint
    assert client.post(
        "/api/projects", json={"left": [""], "right": good}
    ).status_code == 422
    # non-printable / non-ascii
    assert client.post(
        "/api/projects", json={"left": ["a\t"], "right": good}
    ).status_code == 422
    assert client.post(
        "/api/projects", json={"left": ["aé"], "right": good}
    ).status_code == 422
    # value appearing 5 times on one side
    assert client.post(
        "/api/projects", json={"left": ["z"] * 5, "right": good}
    ).status_code == 422
    # missing field / wrong types
    assert client.post("/api/projects", json={"left": good}).status_code == 422
    assert client.post(
        "/api/projects", json={"left": "ab", "right": good}
    ).status_code == 422
    assert client.post(
        "/api/projects", json={"left": [1, 2], "right": good}
    ).status_code == 422
    assert client.post("/api/projects", content=b"not json",
                       headers={"content-type": "application/json"}
                       ).status_code == 422
