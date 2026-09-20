"""LCS core: globally longest correspondence with lexicographically smallest
index-pair sequence, optionally forced through a validated anchor chain.

Problem
-------
Two film scans ``left`` and ``right`` are arrays of fingerprints (bytes are
compared case sensitively, no normalisation).  A correspondence is a sequence
of zero-based index pairs ``(i, j)`` with strictly increasing indices on both
sides and ``left[i] == right[j]``.

* Maximise the number of pairs (the LCS length).
* Ties are broken by the lexicographically smallest pair sequence (pairs are
  compared as ``(i, j)``).
* An anchor set, once validated, must be contained in the result.  The anchors
  split the problem into independent rectangular gaps; the same objective is
  applied to every gap.

Each fingerprint value appears at most 4 times on each side, so the number of
matching pairs is at most ``4 * n`` (<= 80_000).  Pairs are laid out in order
``(i ascending, j descending)``; an LIS on the j-values with a Fenwick tree
then yields the LCS in O(M log m).  Suffix best lengths let a greedy scan pick
the lexicographically smallest optimum.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence


class InvalidAnchors(ValueError):
    """Raised when the proposed anchor chain is not a legal correspondence."""


def validate_anchors(
    anchors: Sequence[Sequence[int]],
    left: Sequence[str],
    right: Sequence[str],
) -> list[tuple[int, int]]:
    """Validate an anchor set and return it sorted as a canonical chain.

    Legal conditions: every anchor is two integer indices inside the arrays,
    the fingerprints at those indices are equal, and after sorting by
    ``(i, j)`` both indices are strictly increasing (this also rejects
    duplicate pairs and crossed anchors).
    """

    n, m = len(left), len(right)
    chain: list[tuple[int, int]] = []
    for raw in anchors:
        if (
            not isinstance(raw, (list, tuple))
            or len(raw) != 2
            or isinstance(raw, bool)
        ):
            raise InvalidAnchors("each anchor must be a pair [i, j]")
        i, j = raw
        # bool is a subclass of int: reject it explicitly below.
        if isinstance(i, bool) or isinstance(j, bool):
            raise InvalidAnchors("anchor indices must be integers")
        if not isinstance(i, int) or not isinstance(j, int):
            raise InvalidAnchors("anchor indices must be integers")
        if not (0 <= i < n and 0 <= j < m):
            raise InvalidAnchors("anchor index out of bounds")
        if left[i] != right[j]:
            raise InvalidAnchors("anchor fingerprints do not match")
        chain.append((i, j))

    chain.sort()
    pi, pj = -1, -1
    for i, j in chain:
        if i == pi:
            raise InvalidAnchors("anchors must have strictly increasing left indices")
        if j <= pj:
            raise InvalidAnchors("anchors must have strictly increasing right indices")
        pi, pj = i, j
    return chain


class _GenFenwick:
    """Fenwick tree of prefix maxima with generation tags.

    ``tag`` increments on every logical clear, so resetting is O(1) instead
    of O(size).  Each cell stores ``(generation, value)``; stale cells are
    treated as zero.
    """

    __slots__ = ("size", "tag", "_val", "_gen")

    def __init__(self, size: int) -> None:
        self.size = size
        self.tag = 0
        self._val = [0] * (size + 1)
        self._gen = [-1] * (size + 1)

    def clear(self) -> None:
        self.tag += 1

    def update(self, pos: int, value: int) -> None:
        # Reverse coordinate: plain prefix-Max Fenwick over pos becomes a
        # suffix-Max over the original j when pos = size - j.
        k = self.size - pos
        gen = self.tag
        val, gen_arr = self._val, self._gen
        while k <= self.size:
            if gen_arr[k] != gen:
                gen_arr[k] = gen
                val[k] = value
            elif val[k] < value:
                val[k] = value
            k += k & -k

    def query(self, pos: int) -> int:
        """Maximum over original positions strictly greater than ``pos``.

        In reverse coordinate r = size - j, positions j > pos are
        r < size - pos; the largest such r is size - pos - 1.
        """
        k = self.size - pos - 1
        if k <= 0:
            return 0
        gen = self.tag
        val, gen_arr = self._val, self._gen
        best = 0
        while k > 0:
            if gen_arr[k] == gen and val[k] > best:
                best = val[k]
            k -= k & -k
        return best


def _build_positions(
    left: Sequence[str], right: Sequence[str]
) -> tuple[list[list[int]], dict[str, list[int]]]:
    """Return per-i lists of matching right indices (descending) and a
    fingerprint -> right indices map (descending)."""

    right_positions: dict[str, list[int]] = defaultdict(list)
    for j in range(len(right) - 1, -1, -1):
        right_positions[right[j]].append(j)

    by_i: list[list[int]] = [[] for _ in left]
    for i, fp in enumerate(left):
        hits = right_positions.get(fp)
        if hits:
            by_i[i] = list(hits)
    return by_i, right_positions


def solve(
    left: Sequence[str],
    right: Sequence[str],
    anchors: Sequence[Sequence[int]] | None = None,
) -> list[list[int]]:
    """Compute the optimal correspondence.

    ``anchors`` (already validated via :func:`validate_anchors` or supplied as
    an iterable that validates against the arrays) must all be included.
    """

    n, m = len(left), len(right)
    chain = (
        validate_anchors(anchors, left, right)
        if anchors is not None
        else []
    )

    by_i, _ = _build_positions(left, right)

    # Suffix LCS length of every matching pair, shared across all gaps.
    # A pair belongs to exactly the gap whose (lo_i, hi_i) window contains i.
    suf: dict[tuple[int, int], int] = {}
    fw = _GenFenwick(m)

    def fill_gap_suffix(lo_i: int, hi_i: int, lo_j: int, hi_j: int) -> None:
        """Fill ``suf`` for pairs with lo_i < i < hi_i and lo_j < j < hi_j.

        Iterates i downward; all queries for one i run before that i's pairs
        are inserted, so pairs sharing an i can never extend each other (left
        indices must stay strictly increasing).  The Fenwick tree indexes j in
        reverse and returns maxima over strictly larger j, enforcing the same
        strictness on the right.
        """

        fw.clear()
        for i in range(hi_i - 1, lo_i, -1):
            # All queries for one i must see the tree without that i's own
            # pairs, otherwise equal-i pairs extend each other (left indices
            # must stay strictly increasing).  Compute values first, insert
            # afterwards.  Right indices are processed in descending order so
            # that an equal-j pair written this round cannot leak into a
            # later one either (the query range ends at j-1 anyway).
            pending: list[tuple[int, int]] = []
            for j in by_i[i]:
                if not (lo_j < j < hi_j):
                    continue
                # Only pairs inside this gap were inserted (the tree is
                # cleared per gap); query(j) returns the best continuation
                # with a strictly larger right index (j' > j).
                pending.append((j, 1 + fw.query(j)))
            for j, length in pending:
                suf[(i, j)] = length
                fw.update(j, length)

    # Bounds of every gap (indices strictly between two consecutive anchors).
    bounds: list[tuple[int, int, int, int]] = []
    prev_i, prev_j = -1, -1
    for ai, aj in chain:
        bounds.append((prev_i, ai, prev_j, aj))
        prev_i, prev_j = ai, aj
    bounds.append((prev_i, n, prev_j, m))

    for lo_i, hi_i, lo_j, hi_j in bounds:
        fill_gap_suffix(lo_i, hi_i, lo_j, hi_j)

    # Greedy reconstruction per gap: at every step scan from the smallest i,
    # take the smallest j that can still complete a longest gap solution.
    result: list[list[int]] = []
    for gap_index, (lo_i, hi_i, lo_j, hi_j) in enumerate(bounds):
        # Gap length = best suffix among pairs in the gap.
        gap_len = 0
        for i in range(lo_i + 1, hi_i):
            for j in by_i[i]:
                if lo_j < j < hi_j:
                    length = suf[(i, j)]
                    if length > gap_len:
                        gap_len = length

        cur_i, cur_j, need = lo_i, lo_j, gap_len
        while need > 0:
            chosen: tuple[int, int] | None = None
            for i in range(cur_i + 1, hi_i):
                # by_i[i] stores right indices in descending order; scan them
                # and remember the last feasible j, i.e. the smallest j whose
                # suffix can complete the remaining chain (suf >= need).  The
                # next anchor (at hi_i/hi_j) is outside the gap window and
                # therefore never visible here; a longer suffix is cut by the
                # j > cur_j restriction in later rounds as needed.
                feasible: tuple[int, int] | None = None
                for j in by_i[i]:
                    if j <= cur_j or j >= hi_j:
                        continue
                    if suf[(i, j)] >= need:
                        feasible = (i, j)
                if feasible is not None:
                    chosen = feasible
                    break
            assert chosen is not None, "gap reconstruction failed"
            i, j = chosen
            result.append([i, j])
            cur_i, cur_j, need = i, j, need - 1

        if gap_index < len(chain):
            ai, aj = chain[gap_index]
            result.append([ai, aj])

    return result


def global_optimum(left: Sequence[str], right: Sequence[str]) -> list[list[int]]:
    """Compute the unanchored globally optimal correspondence."""
    return solve(left, right, anchors=None)
