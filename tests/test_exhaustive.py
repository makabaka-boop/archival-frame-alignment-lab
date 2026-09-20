"""Randomised small cases verified by exhaustive DP, including anchors."""

from __future__ import annotations

import random

from conftest import brute, create_project, set_anchors

ALPHABET = ["a", "b", "c", "d", "e", "A", "B", "~", " "]


def _scan(rng: random.Random) -> list[str]:
    size = rng.randint(1, 9)
    # Pick from a pool so duplicates arise naturally, then enforce the
    # at-most-4 rule by rejection sampling.
    while True:
        scan = [rng.choice(ALPHABET) for _ in range(size)]
        if all(scan.count(v) <= 4 for v in set(scan)):
            return scan


def _valid_anchor_chain(
    rng: random.Random, result: list[list[int]]
) -> list[tuple[int, int]]:
    """Return either an empty chain or a subsequence of an optimal pairing.

    Pairs of an existing correspondence always satisfy the legal conditions,
    so this only produces valid anchor sets.
    """

    if not result or rng.random() < 0.3:
        return []
    k = rng.randint(1, len(result))
    return [tuple(p) for p in rng.sample(result, k)]


def test_random_cases_match_brute_force(client):
    rng = random.Random(20260920)
    for case in range(60):
        left, right = _scan(rng), _scan(rng)
        project = create_project(client, left, right)
        expected_global = brute(left, right)
        assert project["result"] == expected_global, (
            f"case {case}: {left} vs {right}"
        )

        anchors = _valid_anchor_chain(rng, expected_global)
        response = set_anchors(client, project["id"], [list(a) for a in anchors])
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["result"] == brute(left, right, anchors), (
            f"case {case}: {left} vs {right} anchors={anchors}"
        )
        for anchor in anchors:
            assert list(anchor) in body["result"]
        # Length is maximal under the anchor constraint.
        assert body["length"] == len(brute(left, right, anchors))


def test_random_full_anchor_subchains(client):
    # Anchors that themselves cover long forced stretches across many gaps.
    rng = random.Random(777)
    for _ in range(15):
        left = [rng.choice("abc") for _ in range(12)]
        right = [rng.choice("abc") for _ in range(12)]
        project = create_project(client, left, right)
        result = project["result"]
        if len(result) >= 2:
            # Anchor every other pair of the optimum.
            anchors = [tuple(p) for p in result[::2]]
            response = set_anchors(
                client, project["id"], [list(a) for a in anchors]
            )
            assert response.status_code == 200
            assert response.json()["result"] == brute(left, right, anchors)
