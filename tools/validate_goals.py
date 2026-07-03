#!/usr/bin/env python3
"""Validate data/goals.json against the machine-check rules of 付録A.1
and the published series totals of 9.4.

Checks (A.1 検証規則):
  1. every goal ID matches ^(E[1-6]|J[1-3]|H[1-3])-([ABCDE]|M[1-3])-\\d{2}$
  2. every prerequisite reference resolves to a defined goal (未定義参照=0)
  3. the prerequisite graph is acyclic (循環=0)
  4. prerequisite grade gap does not exceed 2 grades — WARNING only, because
     A.1 allows committee-approved exceptions that this script cannot see
  5. every goal has at least one evaluation method (評価未割付=0)
Plus: totals must equal 9.4 (小57/★30, 中36/★25, 高55/★27, 計148/★82).

Exit code 1 if any hard check fails.
"""
import json, re, sys
from pathlib import Path

ID_RE = re.compile(r"^(E[1-6]|J[1-3]|H[1-3])-([ABCDE]|M[1-3])-\d{2}$")
GRADE_INDEX = {g: i for i, g in enumerate(
    ["E1", "E2", "E3", "E4", "E5", "E6", "J1", "J2", "J3", "H1", "H2", "H3"], 1)}
EXPECTED = {"小": (57, 30), "中": (36, 25), "高": (55, 27)}  # 9.4 機械集計
MAX_GRADE_GAP = 2  # A.1 rule 4


def stage(goal_id):
    return {"E": "小", "J": "中", "H": "高"}[goal_id[0]]


def find_cycle(graph):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    def visit(n, path):
        color[n] = GRAY
        for m in graph[n]:
            if m not in graph:
                continue
            if color[m] == GRAY:
                return path + [n, m]
            if color[m] == WHITE:
                found = visit(m, path + [n])
                if found:
                    return found
        color[n] = BLACK
        return None
    for n in graph:
        if color[n] == WHITE:
            found = visit(n, [])
            if found:
                return found
    return None


def main():
    root = Path(__file__).resolve().parent.parent
    goals = json.loads((root / "data" / "goals.json").read_text(encoding="utf-8"))["goals"]
    by_id = {g["id"]: g for g in goals}
    errors, warnings = [], []

    # rule 1: ID format
    for g in goals:
        if not ID_RE.match(g["id"]):
            errors.append(f"[A.1-1] ID書式違反: {g['id']} (line {g['line']})")

    # rule 2: undefined references
    for g in goals:
        for p in g["prereqs"]:
            if p not in by_id:
                errors.append(f"[A.1-2] 未定義参照: {g['id']} -> {p} (line {g['line']})")

    # rule 3: cycles
    graph = {g["id"]: [p for p in g["prereqs"] if p in by_id] for g in goals}
    cycle = find_cycle(graph)
    if cycle:
        errors.append(f"[A.1-3] 前提グラフに循環: {' -> '.join(cycle)}")

    # rule 4: grade gap (warning — committee exceptions possible per A.1)
    for g in goals:
        gi = GRADE_INDEX[g["id"][:2]]
        for p in g["prereqs"]:
            if p not in by_id:
                continue
            pi = GRADE_INDEX[p[:2]]
            if pi >= gi and p != g["id"]:
                # same-grade prerequisites are allowed (先行単元); forward refs are not
                if pi > gi:
                    errors.append(f"[A.1-4] 前方参照（後の学年が前提）: {g['id']} -> {p}")
            elif gi - pi > MAX_GRADE_GAP:
                warnings.append(f"[A.1-4] 学年差{gi - pi} (> {MAX_GRADE_GAP}): "
                                f"{g['id']} -> {p} — 監修委員会承認記録の確認が必要")

    # rule 5: evaluation assigned
    for g in goals:
        if not g["evaluation"].strip():
            errors.append(f"[A.1-5] 評価未割付: {g['id']} (line {g['line']})")

    # 9.4 totals
    for st, (want_n, want_star) in EXPECTED.items():
        n = sum(1 for g in goals if stage(g["id"]) == st)
        s = sum(1 for g in goals if stage(g["id"]) == st and g["star"])
        if (n, s) != (want_n, want_star):
            errors.append(f"[9.4] {st}: 実測 {n}目標/★{s} ≠ 公表 {want_n}/★{want_star}")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")
    total = len(goals)
    stars = sum(1 for g in goals if g["star"])
    print(f"\ngoals={total} core(★)={stars} "
          f"errors={len(errors)} warnings={len(warnings)}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
