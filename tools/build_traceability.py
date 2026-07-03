#!/usr/bin/env python3
"""Generate docs/traceability.md from data/goals.json.

The spec manages goals by ID (3.3) and promises full cross-volume
traceability (付録A). This renders the goal database into a browsable view:
  - per-grade summary (goal counts, core counts)
  - per-domain prerequisite graphs (Mermaid) across all 12 grades
  - a full goal index with prerequisites and reverse dependencies
  - the long-gap (3+ grades) disclosure list from A.3

Usage: python3 tools/build_traceability.py [--check]
--check: verify docs/traceability.md is up to date (CI drift guard).
"""
import argparse, json, sys
from collections import defaultdict
from pathlib import Path

GRADES = ["E1", "E2", "E3", "E4", "E5", "E6", "J1", "J2", "J3", "H1", "H2", "H3"]
GRADE_INDEX = {g: i for i, g in enumerate(GRADES, 1)}
GRADE_LABEL = {"E1": "小1", "E2": "小2", "E3": "小3", "E4": "小4", "E5": "小5",
               "E6": "小6", "J1": "中1", "J2": "中2", "J3": "中3",
               "H1": "高1", "H2": "高2", "H3": "高3"}
# domain names per spec 3.1 (5領域モデル); M = H3 elective modules (9.3)
DOMAIN_LABEL = {"A": "A コンピューティングとプログラミング", "B": "B データとAI",
                "C": "C 情報デザインとコミュニケーション",
                "D": "D デジタル・シティズンシップと倫理",
                "E": "E 探究と社会実装", "M": "M 高3選択モジュール"}


def domain(goal_id):
    d = goal_id.split("-")[1]
    return "M" if d.startswith("M") else d


def build(goals):
    by_id = {g["id"]: g for g in goals}
    dependents = defaultdict(list)
    for g in goals:
        for p in g["prereqs"]:
            if p in by_id:
                dependents[p].append(g["id"])

    out = ["# 到達目標トレーサビリティ（自動生成）", "",
           "`data/goals.json` から `tools/build_traceability.py` が生成する閲覧用ビュー。"
           "**手編集しない**こと（単元表の変更 → `extract_goals.py` → 本スクリプトの順で再生成）。", ""]

    # per-grade summary
    out += ["## 学年別サマリー", "",
            "| 学年 | 目標数 | ★コア | 被参照（後続学年から前提として参照される数） |",
            "|---|---|---|---|"]
    for gr in GRADES:
        gs = [g for g in goals if g["id"].startswith(gr)]
        refs = sum(len([d for d in dependents[g["id"]]
                        if not d.startswith(gr)]) for g in gs)
        out.append(f"| {GRADE_LABEL[gr]} ({gr}) | {len(gs)} | "
                   f"{sum(1 for g in gs if g['star'])} | {refs} |")
    out.append("")

    # per-domain mermaid graphs (edges only; isolated goals listed below)
    out += ["## 領域別 前提関係グラフ", "",
            "矢印は「前提 → 目標」。★はコア目標。領域をまたぐ前提は両方の領域の図に現れる。", ""]
    for dom in ["A", "B", "C", "D", "E", "M"]:
        edges = []
        nodes = {g["id"] for g in goals if domain(g["id"]) == dom}
        for g in goals:
            for p in g["prereqs"]:
                if p in by_id and (domain(g["id"]) == dom or domain(p) == dom):
                    edges.append((p, g["id"]))
                    nodes.update((p, g["id"]))
        out += [f"### {DOMAIN_LABEL[dom]}", ""]
        if not edges:
            # e.g. H3 modules: prerequisite is "core P1 completion" prose (9.3),
            # not goal-ID references — show the standalone nodes with that note
            out += ["前提のID参照を持たない独立目標のみ（高3モジュールの前提は「コアP1修了」＝9.3参照）。", ""]
        out += ["```mermaid", "graph LR"]
        for n in sorted(nodes, key=lambda x: (GRADE_INDEX[x[:2]], x)):
            star = "★" if by_id[n]["star"] else ""
            out.append(f'  {n.replace("-", "_")}["{star}{n}"]')
        for p, c in sorted(set(edges)):
            out.append(f"  {p.replace('-', '_')} --> {c.replace('-', '_')}")
        out += ["```", ""]

    # long-gap disclosure (A.3)
    out += ["## 学年差3以上の前提参照（付録A.3の開示対象）", "",
            "スパイラル構造上の意図した積み上げ。該当単元は接続欄（3.4）で前提を再活性化する。", "",
            "| 目標 | 前提 | 学年差 |", "|---|---|---|"]
    for g in goals:
        for p in g["prereqs"]:
            if p in by_id:
                gap = GRADE_INDEX[g["id"][:2]] - GRADE_INDEX[p[:2]]
                if gap >= 3:
                    out.append(f"| {g['id']} | {p} | {gap} |")
    out.append("")

    # full index
    out += ["## 全目標インデックス", "",
            "| ID | ★ | 観点 | 評価 | 前提 | この目標を前提とする目標 |",
            "|---|---|---|---|---|---|"]
    for g in sorted(goals, key=lambda x: (GRADE_INDEX[x["id"][:2]], x["id"])):
        out.append(f"| {g['id']} | {'★' if g['star'] else ''} | {g['kanten']} | "
                   f"{g['evaluation']} | {', '.join(g['prereqs']) or '―'} | "
                   f"{', '.join(sorted(dependents[g['id']])) or '―'} |")
    out.append("")
    return "\n".join(out) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    goals = json.loads((root / "data" / "goals.json").read_text(encoding="utf-8"))["goals"]
    rendered = build(goals)
    target = root / "docs" / "traceability.md"
    if args.check:
        if not target.exists() or target.read_text(encoding="utf-8") != rendered:
            sys.exit("docs/traceability.md is out of date — run tools/build_traceability.py")
        print("check OK: traceability view matches goal database")
        return
    target.write_text(rendered, encoding="utf-8")
    print(f"wrote {target}")


if __name__ == "__main__":
    main()
