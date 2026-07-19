#!/usr/bin/env python3
"""Tier 0 deterministic manuscript checks (docs/ai-review-system.md S1).

Validates manuscripts/*.md (textbook drafts) and instructor-guides/*.md
against the machine-decidable subset of 付録C and the writing plan's
frozen hours. All checks here are deterministic — no LLM judgment.

  M1  metadata block present (単元ID/執筆基準時数/状態)
  M2  執筆基準時数 matches docs/writing-plan.md 2.3 (frozen per-file values)
  M3  per-volume hour sums match volume totals (R2/計画書2.2)
  S1  required sections present (第11章9部構成＋差異化/図版指示/セルフチェック、
      指導書は第16章の必置7項目)
  S2  アンプラグド代替: 小中はMUST(error)、高はSHOULD(warning)
  S3  指導書の評価事例集はG3実証への言及必須（作品例の捏造防止）
  G1  本文中の全目標IDが data/goals.json に実在
  F1  禁止表現（絶対安全/必ず安全、訳語「幻覚」、「サーバ」長音欠落）
      ※打ち消し・禁止の文脈はホワイトリストで除外
  A1  本文中の計算式（a+b+…=x、a÷b=x、a×b=x）の再計算
  L1  文長KPI（小≤60字/中高≤80字、本文のみ。表・見出し・目標転記〔…〕・
      図版指示・セルフチェック記録は対象外）

Usage: python3 tools/validate_manuscripts.py
Exit 1 on errors; warnings never fail the build.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAN = ROOT / "manuscripts"
GUIDES = ROOT / "instructor-guides"

# ---- frozen hours (docs/writing-plan.md 2.3) --------------------------------
EXPECTED_HOURS = {
    "E1-U1": 2, "E1-U2": 2, "E1-U3": 2, "E1-U4": 2, "E1-U5": 2, "E1-U6": 2,
    "E2-U1": 2, "E2-U2": 2, "E2-U3": 2, "E2-U4": 3, "E2-U5": 1, "E2-U6": 1, "E2-U7": 1,
    "E3-U1": 3, "E3-U2": 2, "E3-U3": 2, "E3-U4": 3, "E3-U5": 2, "E3-U6": 2, "E3-U7": 2,
    "E4-U1": 2, "E4-U2": 2, "E4-U3": 4, "E4-U4": 3, "E4-U5": 2, "E4-U6": 3,
    "E5-U1": 4, "E5-U2": 3, "E5-U3": 4, "E5-U4": 4, "E5-U5": 2, "E5-U6": 5,
    "E6-U1": 3, "E6-U2": 3, "E6-U3": 6, "E6-U4": 2, "E6-U5": 2, "E6-U6": 6,
    "J1-U1": 3, "J1-U2": 5, "J1-U3": 4, "J1-U4": 4, "J1-U5": 4, "J1-U6": 3, "J1-U7": 4, "J1-U8": 3,
    "J2-U1": 5, "J2-U2": 4, "J2-U3": 4, "J2-U4": 7, "J2-U5": 4, "J2-U6": 3, "J2-U7": 3,
    "J3-U1": 4, "J3-U2": 6, "J3-U3": 5, "J3-U4": 3, "J3-U5": 6, "J3-U6": 4, "J3-U7": 2,
    "H1-P1": 14, "H1-P2": 14, "H1-P3": 24, "H1-P4": 18, "H1-C11": 4,
    "H2-P1": 20, "H2-P2": 18, "H2-P3": 16, "H2-P4": 8, "H2-P5": 8,
    "H3-P1": 5, "H3-P2": 12, "H3-P3": 5, "H3-P4": 6, "H3-M1": 7, "H3-M2": 7, "H3-M3": 7,
}
# per-volume totals; H1-C11 is a detail view inside H1-P3 so it is excluded
VOLUME_TOTALS = {
    "E1": 12, "E2": 12, "E3": 16, "E4": 16, "E5": 22, "E6": 22,
    "J1": 30, "J2": 30, "J3": 30, "H1": 70, "H2": 70,
    "H3": 28 + 21,  # コア28＋選択モジュール7×3（発展は不割付）
}
SUM_EXCLUDE = {"H1-C11"}

UNIT_SECTIONS = ["とびら", "フック", "概念の核", "やってみよう", "深めよう",
                 "考えよう", "たしかめよう", "学びの記録", "差異化ルート",
                 "図版指示", "セルフチェック"]
GUIDE_SECTIONS = ["指導案", "誤概念カタログ", "予備知識ブリーフ",
                  "環境別実施ガイド", "評価事例集", "家庭・地域連携", "研修用資料"]

GOAL_ID = re.compile(r"\b(?:E[1-6]|J[1-3]|H[1-3])-(?:[ABCDE]|M[1-3])-\d{2}\b")
FORBIDDEN = [
    (re.compile(r"絶対に?安全|必ず安全|ぜったいに?\s*あんぜん"),
     re.compile(r"いわない|言わない|書かない|禁止|表現|とは|断定|誤解|誤概念|してしまう"),
     "断定的安全表現（C-026）"),
    (re.compile(r"幻覚"), re.compile(r"不使用|訳語"), "訳語「幻覚」は不使用（付録E）"),
    (re.compile(r"サーバ(?!ー)"), None, "長音「サーバー」に統一（付録E）"),
]
ARITH_SUM = re.compile(r"(?<![\d.万円年月])((?:\d+\s*[+＋]\s*)+\d+)\s*[=＝]\s*(\d+)(?![\d.])")
ARITH_DIV = re.compile(r"(?<![\d.])(\d+)\s*÷\s*(\d+)\s*[=＝]\s*(\d+)(?![\d.])")
ARITH_MUL = re.compile(r"(?<![\d.])(\d+)\s*×\s*(\d+)\s*[=＝]\s*(\d+)(?![\d.])")

SENT_SPLIT = re.compile(r"[。！？]")
SKIP_LINE = re.compile(r"^\s*(\||#|>|```|\d+\s*$)")
SENT_EXEMPT_SECTIONS = ("図版指示", "セルフチェック")


def meta_block(text: str) -> str:
    m = re.search(r"```\n(.*?)```", text, re.S)
    return m.group(1) if m else ""


def headings(text: str):
    return [ln for ln in text.splitlines() if ln.startswith("##")]


def prose_sentences(text: str):
    """Yield (lineno, sentence) for body prose, excluding non-紙面 material."""
    in_code = False
    exempt = False
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if ln.startswith("##"):
            exempt = any(k in ln for k in SENT_EXEMPT_SECTIONS)
            continue
        if exempt or SKIP_LINE.match(ln) or "〔" in ln:
            continue
        # 箇条書き項目は「文」ではない（文体は C-032 で別途規律）
        if ln.lstrip().startswith("- "):
            continue
        # 行頭の太字ラベル（「**発問:**」等）は見出し相当なので文長に含めない
        ln = re.sub(r"^\s*(?:\d+\.\s*)?\*\*[^*]+\*\*[:：]?\s*", "", ln)
        body = re.sub(r"[\s　]", "", ln)
        for s in SENT_SPLIT.split(body):
            if s:
                yield i, s


def check_file(path: Path, goal_ids: set, errors: list, warnings: list,
               sent_stats: dict):
    name = path.stem
    text = path.read_text(encoding="utf-8")
    meta = meta_block(text)
    is_guide = path.parent.name == "instructor-guides"
    stage = name[0]  # E / J / H

    # M1: metadata
    if not is_guide:
        for key in ("単元ID", "執筆基準時数", "状態"):
            if key not in meta:
                errors.append(f"{path.name}: メタ情報に「{key}」がない (M1)")
    elif "状態" not in meta:
        errors.append(f"{path.name}: メタ情報に「状態」がない (M1)")

    # M2: frozen hours
    if not is_guide:
        m = re.search(r"執筆基準時数[:：]\s*(\d+)", meta)
        if m and name in EXPECTED_HOURS:
            got, want = int(m.group(1)), EXPECTED_HOURS[name]
            if got != want:
                errors.append(
                    f"{path.name}: 執筆基準時数 {got} が計画書2.3の凍結値 {want} と不一致 (M2)")
        elif name not in EXPECTED_HOURS:
            errors.append(f"{path.name}: 計画書2.3に対応する執筆単位がない (M2)")

    # S1/S2: sections
    heads = " / ".join(headings(text))
    required = GUIDE_SECTIONS if is_guide else UNIT_SECTIONS
    for sec in required:
        if sec not in heads:
            errors.append(f"{path.name}: 必須セクション「{sec}」がない (S1)")
    if not is_guide:
        if "アンプラグド" not in heads:
            if stage in "EJ":
                errors.append(f"{path.name}: アンプラグド代替がない（小中はMUST・C-012） (S2)")
            else:
                warnings.append(f"{path.name}: アンプラグド代替がない（高はSHOULD） (S2)")

    # S3: guides must not fabricate student work
    if is_guide:
        m = re.search(r"##[^\n]*評価事例集[^\n]*\n(.*?)(?=\n## |\Z)", text, re.S)
        if m and "G3" not in m.group(1):
            errors.append(
                f"{path.name}: 評価事例集にG3実証への言及がない（実データ待ちの明示が必須） (S3)")

    # G1: goal IDs exist
    for gid in sorted(set(GOAL_ID.findall(text))):
        if gid not in goal_ids:
            errors.append(f"{path.name}: 目標ID {gid} が data/goals.json に存在しない (G1)")

    # F1: forbidden wording
    for i, ln in enumerate(text.splitlines(), 1):
        for pat, allow, label in FORBIDDEN:
            if pat.search(ln) and not (allow and allow.search(ln)):
                errors.append(f"{path.name}:{i}: {label} (F1): {ln.strip()[:60]}")

    # A1: arithmetic
    for i, ln in enumerate(text.splitlines(), 1):
        for m in ARITH_SUM.finditer(ln):
            terms = [int(t) for t in re.split(r"[+＋]", re.sub(r"\s", "", m.group(1)))]
            if sum(terms) != int(m.group(2)):
                errors.append(f"{path.name}:{i}: 計算不一致 {m.group(0)} (A1)")
        for m in ARITH_DIV.finditer(ln):
            a, b, c = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if b == 0 or a / b != c:
                errors.append(f"{path.name}:{i}: 計算不一致 {m.group(0)} (A1)")
        for m in ARITH_MUL.finditer(ln):
            if int(m.group(1)) * int(m.group(2)) != int(m.group(3)):
                errors.append(f"{path.name}:{i}: 計算不一致 {m.group(0)} (A1)")

    # L1: sentence length KPI (manuscripts only — 指導書は児童生徒向け紙面ではない)
    if not is_guide:
        limit = 60 if stage == "E" else 80
        total = long = 0
        for lineno, s in prose_sentences(text):
            total += 1
            if len(s) > limit:
                long += 1
                errors.append(
                    f"{path.name}:{lineno}: 文長{len(s)}字が上限{limit}字を超過 (L1/C-016): {s[:40]}…")
        sent_stats[path.name] = (total, long)


def main() -> int:
    goals = json.loads((ROOT / "data" / "goals.json").read_text(encoding="utf-8"))
    goal_ids = {g["id"] for g in goals["goals"]}

    errors, warnings, sent_stats, hours = [], [], {}, {}

    files = sorted(p for p in MAN.glob("*.md")
                   if p.stem not in ("README", "TEMPLATE"))
    guide_files = sorted(p for p in GUIDES.glob("*.md") if p.stem != "README")

    for p in files + guide_files:
        check_file(p, goal_ids, errors, warnings, sent_stats)

    # M3: volume sums
    for name, want in EXPECTED_HOURS.items():
        if name in SUM_EXCLUDE:
            continue
        hours.setdefault(name[:2], 0)
        hours[name[:2]] += want
    for vol, want in VOLUME_TOTALS.items():
        got = hours.get(vol, 0)
        if got != want:
            errors.append(f"{vol}: 巻内時数合計 {got} ≠ 巻総時数 {want} (M3)")

    # coverage: every expected unit has a manuscript
    present = {p.stem for p in files}
    for name in EXPECTED_HOURS:
        if name not in present:
            errors.append(f"{name}: 原稿ファイルがない (M2)")

    for w in warnings:
        print(f"WARN  {w}")
    for e in errors:
        print(f"ERROR {e}")

    total = sum(t for t, _ in sent_stats.values())
    long = sum(l for _, l in sent_stats.values())
    rate = (1 - long / total) * 100 if total else 100.0
    print(f"\nfiles={len(files) + len(guide_files)} sentences={total} "
          f"over-limit={long} 文長適合率={rate:.1f}% (KPI≥98%) "
          f"errors={len(errors)} warnings={len(warnings)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
