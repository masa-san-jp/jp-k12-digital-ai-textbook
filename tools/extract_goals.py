#!/usr/bin/env python3
"""Extract the attainment-goal database from docs/specification.md.

Reads the grade-design chapters (第5章〜第9章) and emits data/goals.json:
one record per goal ID with star flag, competency aspect (観点), goal text,
evaluation methods and prerequisite goal IDs.

Table layouts handled (see docs/specification.md):
- E*/J* unit tables:   | 単元 | 時数 | 領域/KC | 到達目標 | 評価 | 前提 |
  Goals are inline: "★E1-A-01【知】〔...〕／E1-A-02【思】〔...〕".
  The 前提 column is unit-level (R3), so its IDs attach to every goal in the row.
- H1/H2/H3 part tables: | 部 | 時数 | 到達目標 | 評価 |  (no 前提 column).
  A header note "すべて★" marks every inline goal in that table as core.
- ID-first tables (H2 additional / H3 core-additional):
  | ID | ★ | 観点 | 到達目標 | 所属 | 評価 | 前提 |
- H3 module table: | ID | 観点 | 到達目標 | 評価 |  (module prerequisite is
  "コアP1修了" prose, not an ID reference — recorded as no edges).

Usage: python3 tools/extract_goals.py [--spec docs/specification.md]
                                      [--out data/goals.json] [--check]
--check: verify the committed data/goals.json matches a fresh extraction
         (used by CI to catch spec/data drift). Exits 1 on mismatch.
"""
import argparse, json, re, sys
from pathlib import Path

ID_RE = re.compile(r"(?:E[1-6]|J[1-3]|H[1-3])-(?:[ABCDE]|M[1-3])-\d{2}")
GOAL_START_RE = re.compile(r"(★)?\s*(" + ID_RE.pattern + r")\s*【(知|思|学)】")
CHAPTER_RANGE = ("## 第5章", "## 9.4")  # goal definitions live here


def spec_definition_lines(text):
    lines = text.splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith(CHAPTER_RANGE[0]))
    end = next(i for i, l in enumerate(lines) if l.startswith(CHAPTER_RANGE[1]))
    return lines[start:end], start


def iter_tables(lines, offset):
    """Yield (header_cells, [(line_no, row_cells), ...], preceding_text)."""
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append((offset + i + 1, lines[i]))
                i += 1
            if len(block) >= 2:
                header = [c.strip() for c in block[0][1].strip().strip("|").split("|")]
                rows = []
                for no, raw in block[1:]:
                    cells = [c.strip() for c in raw.strip().strip("|").split("|")]
                    if all(re.fullmatch(r":?-+:?", c) for c in cells):
                        continue  # separator row
                    rows.append((no, cells))
                yield header, rows
        else:
            i += 1


def split_inline_goals(cell):
    """Split a goals cell into (star, id, kanten, text) tuples."""
    starts = list(GOAL_START_RE.finditer(cell))
    out = []
    for k, m in enumerate(starts):
        end = starts[k + 1].start() if k + 1 < len(starts) else len(cell)
        text = cell[m.end():end].strip().strip("／/").strip()
        out.append((bool(m.group(1)), m.group(2), m.group(3), text))
    return out


def parse_prereqs(cell):
    if not cell or cell in ("なし", "―", "-", ""):
        return []
    return ID_RE.findall(cell)


def extract(spec_path):
    text = Path(spec_path).read_text(encoding="utf-8")
    lines, offset = spec_definition_lines(text)
    goals = {}

    def add(gid, star, kanten, gtext, evaluation, prereqs, line_no):
        if gid in goals:
            sys.exit(f"duplicate goal definition: {gid} "
                     f"(lines {goals[gid]['line']} and {line_no})")
        goals[gid] = {"id": gid, "star": star, "kanten": kanten, "text": gtext,
                      "evaluation": evaluation, "prereqs": prereqs, "line": line_no}

    for header, rows in iter_tables(lines, offset):
        header_joined = "".join(header)
        all_star = "すべて★" in header_joined
        if header and header[0] == "ID":
            # ID-first table: ID / [★] / 観点 / 到達目標 / [所属] / 評価 / [前提]
            has_star_col = "★" in header
            idx = {name: k for k, name in enumerate(header)}
            for line_no, cells in rows:
                if len(cells) < len(header):
                    continue
                gid = cells[idx["ID"]]
                if not ID_RE.fullmatch(gid):
                    continue
                star = has_star_col and cells[idx["★"]].strip() == "★"
                kanten = cells[idx["観点"]]
                gtext = cells[idx[next(n for n in header if "到達目標" in n)]]
                evaluation = cells[idx["評価"]]
                prereqs = parse_prereqs(cells[idx["前提"]]) if "前提" in idx else []
                add(gid, star, kanten, gtext, evaluation, prereqs, line_no)
            continue
        # inline-goal table: locate the goals / evaluation / prerequisite columns
        goal_col = next((k for k, name in enumerate(header) if "到達目標" in name), None)
        if goal_col is None:
            continue
        eval_col = next((k for k, name in enumerate(header) if "評価" in name), None)
        prereq_col = next((k for k, name in enumerate(header) if "前提" in name), None)
        for line_no, cells in rows:
            if len(cells) <= goal_col:
                continue
            evaluation = cells[eval_col] if eval_col is not None and len(cells) > eval_col else ""
            prereqs = parse_prereqs(cells[prereq_col]) if prereq_col is not None and len(cells) > prereq_col else []
            for star, gid, kanten, gtext in split_inline_goals(cells[goal_col]):
                add(gid, star or all_star, kanten, gtext, evaluation, prereqs, line_no)

    return [goals[k] for k in sorted(goals)]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    p.add_argument("--spec", default=root / "docs" / "specification.md")
    p.add_argument("--out", default=root / "data" / "goals.json")
    p.add_argument("--check", action="store_true")
    args = p.parse_args()

    records = extract(args.spec)
    payload = json.dumps({"source": "docs/specification.md",
                          "goals": records}, ensure_ascii=False, indent=1)
    out = Path(args.out)
    if args.check:
        if not out.exists() or out.read_text(encoding="utf-8").strip() != payload.strip():
            sys.exit("data/goals.json is out of date — run tools/extract_goals.py")
        print(f"check OK: {len(records)} goals, data matches spec")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload + "\n", encoding="utf-8")
    stars = sum(1 for r in records if r["star"])
    print(f"extracted {len(records)} goals ({stars} core/★) -> {out}")


if __name__ == "__main__":
    main()
