"""Fixed scenarios: duplicates, ties, anchors, emptying, persistence."""

from __future__ import annotations

from conftest import brute, create_project, set_anchors


def test_no_match_returns_empty(client):
    project = create_project(client, ["a", "b", "c"], ["x", "y"])
    assert project["result"] == []
    assert project["length"] == 0


def test_identical_scans_pair_diagonal(client):
    scans = ["a", "b", "c", "d"]
    project = create_project(client, scans, list(scans))
    assert project["result"] == [[0, 0], [1, 1], [2, 2], [3, 3]]


def test_duplicate_fingerprints_smallest_lex_pair(client):
    # Both "a"s on the left can pair with both on the right; length 2 has a
    # unique answer, but length-1 preferences must also be exercised below.
    project = create_project(client, ["a", "a"], ["a", "a"])
    assert project["result"] == [[0, 0], [1, 1]]


def test_tie_break_picks_smallest_pair(client):
    # Length 1: left[0]="x" matches right indices 1 (and also ...); the
    # smallest pair (0,1) must win over (1,0).
    project = create_project(client, ["x", "y"], ["y", "x"])
    assert project["result"] == [[0, 1]]
    assert brute(["x", "y"], ["y", "x"]) == [[0, 1]]


def test_repeated_values_lex_min_sequence(client):
    left = ["f", "f", "g"]
    right = ["g", "f", "f"]
    project = create_project(client, left, right)
    assert project["result"] == brute(left, right)
    assert project["result"] == [[0, 1], [1, 2]]


def test_case_sensitive_and_printable(client):
    project = create_project(client, ["A", "a~"], ["a", "A", "a~"])
    # "A" only matches "A" (1), "a~" matches "a~" (2): strict order works.
    assert project["result"] == [[0, 1], [1, 2]]


def test_get_project_roundtrip_and_restart_readable(client):
    project = create_project(client, ["p", "q"], ["q", "p", "r"])
    fetched = client.get(f"/api/projects/{project['id']}").json()
    assert fetched["result"] == project["result"]
    assert fetched["left"] == ["p", "q"]
    assert fetched["anchors"] == []


def test_get_unknown_project_404(client):
    assert client.get("/api/projects/999_999_999").status_code == 404


def test_anchor_is_included(client):
    left = ["a", "b", "a", "b"]
    right = ["b", "a", "b", "a"]
    project = create_project(client, left, right)
    global_len = project["length"]

    # Force the chain (0,1)->(1,2): left "a"(0)->right "a"(1), "b"(1)->"b"(2).
    response = set_anchors(client, project["id"], [[0, 1], [1, 2]])
    assert response.status_code == 200, response.text
    body = response.json()
    assert [0, 1] in body["result"]
    assert [1, 2] in body["result"]
    assert body["anchors"] == [[0, 1], [1, 2]]
    assert body["length"] <= global_len


def test_first_and_last_anchors(client):
    left = ["z", "a", "b", "z"]
    right = ["z", "b", "a", "z"]
    project = create_project(client, left, right)
    response = set_anchors(client, project["id"], [[0, 0], [3, 3]])
    assert response.status_code == 200
    body = response.json()
    assert body["result"][0] == [0, 0]
    assert body["result"][-1] == [3, 3]
    assert body["length"] == len(brute(left, right, [(0, 0), (3, 3)]))


def test_anchor_constrains_to_shorter_optimum(client):
    # Anchors (1,0) force "b" first; only length 2 remains via "c"/"d" tail.
    left = ["a", "b", "c"]
    right = ["b", "a", "c"]
    project = create_project(client, left, right)
    assert project["length"] == 2  # (0,1),(2,2)
    response = set_anchors(client, project["id"], [[1, 0]])
    assert response.status_code == 200
    body = response.json()
    assert body["length"] == 2
    assert body["result"][0] == [1, 0]
    assert body["result"] == [[1, 0], [2, 2]]
    assert body["result"] == brute(left, right, [(1, 0)])


def test_clearing_anchors_restores_global_optimum(client):
    left = ["a", "b", "a"]
    right = ["b", "a", "b"]
    project = create_project(client, left, right)
    global_result = project["result"]

    response = set_anchors(client, project["id"], [[1, 0]])
    assert response.status_code == 200
    assert response.json()["length"] <= project["length"]

    cleared = set_anchors(client, project["id"], [])
    assert cleared.status_code == 200
    assert cleared.json()["result"] == global_result
    assert cleared.json()["anchors"] == []


def test_anchors_unsorted_input_gets_canonicalised(client):
    left = ["a", "b", "c"]
    right = ["a", "b", "c"]
    project = create_project(client, left, right)
    response = set_anchors(client, project["id"], [[2, 2], [0, 0]])
    assert response.status_code == 200
    assert response.json()["anchors"] == [[0, 0], [2, 2]]


def test_illegal_anchors_422_and_state_unchanged(client):
    left = ["a", "b"]
    right = ["b", "a"]
    project = create_project(client, left, right)
    original = client.get(f"/api/projects/{project['id']}").json()

    # fingerprints differ
    r = set_anchors(client, project["id"], [[0, 0]])
    assert r.status_code == 422
    # crossed: same left index
    r = set_anchors(client, project["id"], [[0, 1], [0, 0]])
    assert r.status_code == 422
    # decreasing right index
    r = set_anchors(client, project["id"], [[0, 1], [1, 0]])
    assert r.status_code == 422
    # duplicate anchor pair
    r = set_anchors(client, project["id"], [[0, 1], [0, 1]])
    assert r.status_code == 422
    # out of bounds
    r = set_anchors(client, project["id"], [[0, 5]])
    assert r.status_code == 422
    r = set_anchors(client, project["id"], [[-1, 0]])
    assert r.status_code == 422
    # malformed
    r = client.put(
        f"/api/projects/{project['id']}/anchors", json={"anchors": [[1]]}
    )
    assert r.status_code == 422
    r = client.put(
        f"/api/projects/{project['id']}/anchors", json={"anchors": "nope"}
    )
    assert r.status_code == 422

    after = client.get(f"/api/projects/{project['id']}").json()
    assert after["result"] == original["result"]
    assert after["anchors"] == []


def test_legal_anchor_then_illegal_keeps_legal_state(client):
    left = ["a", "b", "c", "a"]
    right = ["c", "a", "b", "a"]
    project = create_project(client, left, right)
    ok = set_anchors(client, project["id"], [[1, 2]])
    assert ok.status_code == 200

    bad = set_anchors(client, project["id"], [[0, 0]])  # "a" != "c"
    assert bad.status_code == 422

    current = client.get(f"/api/projects/{project['id']}").json()
    assert current["anchors"] == [[1, 2]]
    assert current["result"] == ok.json()["result"]
