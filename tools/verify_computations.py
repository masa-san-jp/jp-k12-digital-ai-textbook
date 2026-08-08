#!/usr/bin/env python3
"""Tier 1 computational verification harness (docs/ai-review-system.md S2).

Verifies manuscripts/*.md by recomputation and execution — everything here
is decidable by running the numbers, so a failure is a real defect (or a
stale annotation), never a matter of judgment.

  P1  紙面予算 が執筆計画書2.3の凍結値と一致
  P2  見出しのページ配分合計が紙面予算±2p以内（計画書3.2の巻内調整幅）
  Z1  図版番号: 見出しの図版参照が図版指示表の行1〜Nと過不足なく一致
  A2  本文中の計算式の再計算（＋−×÷の混在・連鎖に対応。Tier 0のA1を包含）
  X1  擬似言語コード例を実行し、直後の検証注記 <!-- 検証: ... --> と照合
      （C-051/C-052。注記のないコード例はエラー＝未検証の実行例を禁止）
  Q1  選択式設問の正答マーカーが設問ごとに1つだけ存在
  R1  前提参照の方向性（メタ情報「前提:」は上流の巻・単元・目標のみ参照可）
  T1  到達目標の転記整合（★・観点・目標文が data/goals.json と完全一致。
      末尾の（…）補足のみ許容）

Usage: python3 tools/verify_computations.py
Exit 1 on errors; warnings never fail the build.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAN = ROOT / "manuscripts"

# ---- frozen page budgets (docs/writing-plan.md 2.3) -------------------------
EXPECTED_PAGES = {
    "E1-U1": 8, "E1-U2": 8, "E1-U3": 8, "E1-U4": 8, "E1-U5": 8, "E1-U6": 8,
    "E2-U1": 8, "E2-U2": 8, "E2-U3": 8, "E2-U4": 12, "E2-U5": 4, "E2-U6": 4, "E2-U7": 4,
    "E3-U1": 14, "E3-U2": 10, "E3-U3": 10, "E3-U4": 16, "E3-U5": 10, "E3-U6": 10, "E3-U7": 10,
    "E4-U1": 10, "E4-U2": 10, "E4-U3": 20, "E4-U4": 14, "E4-U5": 10, "E4-U6": 16,
    "E5-U1": 14, "E5-U2": 12, "E5-U3": 14, "E5-U4": 14, "E5-U5": 8, "E5-U6": 18,
    "E6-U1": 10, "E6-U2": 12, "E6-U3": 20, "E6-U4": 8, "E6-U5": 8, "E6-U6": 22,
    "J1-U1": 12, "J1-U2": 20, "J1-U3": 16, "J1-U4": 16, "J1-U5": 16, "J1-U6": 12, "J1-U7": 18, "J1-U8": 14,
    "J2-U1": 22, "J2-U2": 16, "J2-U3": 16, "J2-U4": 28, "J2-U5": 16, "J2-U6": 12, "J2-U7": 14,
    "J3-U1": 16, "J3-U2": 24, "J3-U3": 20, "J3-U4": 12, "J3-U5": 24, "J3-U6": 18, "J3-U7": 10,
    "H1-P1": 32, "H1-P2": 32, "H1-P3": 56, "H1-P4": 40, "H1-C11": 12,
    "H2-P1": 50, "H2-P2": 44, "H2-P3": 40, "H2-P4": 20, "H2-P5": 18,
    "H3-P1": 18, "H3-P2": 36, "H3-P3": 16, "H3-P4": 22, "H3-M1": 16, "H3-M2": 16, "H3-M3": 16,
}
PAGE_TOLERANCE = 2.0  # 計画書3.2: ±2p（1見開き）の巻内調整幅

VOL_ORDER = {v: i for i, v in enumerate(
    ["E1", "E2", "E3", "E4", "E5", "E6", "J1", "J2", "J3", "H1", "H2", "H3"])}

GOAL_ID = r"(?:E[1-6]|J[1-3]|H[1-3])-(?:[ABCDE]|M[1-3])-\d{2}"
KANTEN = "知思学"


def meta_block(text: str) -> str:
    m = re.search(r"^```\n(.*?)\n```", text, re.S | re.M)
    return m.group(1) if m else ""


def strip_code_blocks(text: str):
    """Yield (lineno, line) for lines outside fenced code blocks."""
    in_code = False
    for i, ln in enumerate(text.splitlines(), 1):
        if ln.startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            yield i, ln


# ---- expression evaluation (shared by A2 and the pseudo-language runner) ----
_OP_MAP = {"＋": "+", "−": "-", "×": "*", "÷": "/", "≧": ">=", "≦": "<=", "≠": "!="}


def _normalize_expr(expr: str) -> str:
    for a, b in _OP_MAP.items():
        expr = expr.replace(a, b)
    return expr


def eval_expr(expr: str, env: dict) -> float:
    """Evaluate an arithmetic/comparison expression with 1-indexed arrays."""
    expr = _normalize_expr(expr)
    # NAME[idx] -> __idx(NAME, idx)  (1-indexed array access)
    expr = re.sub(r"([A-Za-z_]\w*)\s*\[([^\]]+)\]", r"__idx(\1,\2)", expr)
    scope = {"__builtins__": {}, "__idx": lambda a, i: a[int(i) - 1]}
    scope.update(env)
    return eval(expr, scope)  # noqa: S307 — repo-local deterministic checker


# ---- pseudo-language interpreter (仕様: H1-C11 3.2の記法) --------------------
class PseudoError(Exception):
    pass


def run_pseudo(code: str, fills: dict):
    """Execute a pseudo-language block; return (env, outputs)."""
    for k, v in fills.items():
        code = code.replace(k, v)
    if "【" in code:
        raise PseudoError("穴埋め記号が未解決（検証注記に代入値がない）")
    lines = [ln for ln in code.splitlines() if ln.strip()]
    env, out = {}, []

    def indent(ln):
        return len(ln) - len(ln.lstrip(" "))

    def block_end(i, base):
        j = i + 1
        while j < len(lines) and indent(lines[j]) > base:
            j += 1
        return j

    def exec_range(i0, i1):
        i = i0
        while i < i1:
            ln = lines[i]
            s = ln.strip()
            base = indent(ln)
            m = re.match(r"(\w+)\s*=\s*\[(.*)\]$", s)
            if m:
                env[m.group(1)] = [eval_expr(x, env) for x in m.group(2).split(",")]
                i += 1
                continue
            m = re.match(r"(\w+)\s*←\s*(.+)$", s)
            if m:
                env[m.group(1)] = eval_expr(m.group(2), env)
                i += 1
                continue
            m = re.match(r"表示する\((.+)\)$", s)
            if m:
                out.append(eval_expr(m.group(1), env))
                i += 1
                continue
            m = re.match(r"(\w+)\s*を\s*(.+?)\s*から\s*(.+?)\s*まで\s*1\s*ずつ増やしながら繰り返す[:：]$", s)
            if m:
                var, a, b = m.group(1), eval_expr(m.group(2), env), eval_expr(m.group(3), env)
                end = block_end(i, base)
                for v in range(int(a), int(b) + 1):
                    env[var] = v
                    exec_range(i + 1, end)
                i = end
                continue
            m = re.match(r"もし\s*(.+?)\s*ならば[:：]$", s)
            if m:
                cond = eval_expr(m.group(1), env)
                end = block_end(i, base)
                els = None
                if end < i1 and lines[end].strip().startswith("そうでなければ"):
                    els = end
                    end = block_end(els, indent(lines[els]))
                if cond:
                    exec_range(i + 1, els if els is not None else end)
                elif els is not None:
                    exec_range(els + 1, end)
                i = end
                continue
            raise PseudoError(f"解釈できない行: {s!r}")

    exec_range(0, len(lines))
    return env, out


def parse_expect(comment: str):
    """Parse '<!-- 検証: k=v; ... -->' into (fills, expects, displays)."""
    body = re.search(r"検証[:：]\s*(.*?)\s*-->", comment, re.S).group(1)
    fills, expects, displays = {}, {}, None
    for item in re.split(r"[;；]", body):
        item = item.strip()
        if not item:
            continue
        k, _, v = item.partition("=")
        k, v = k.strip(), v.strip()
        if k.startswith("【"):
            fills[k] = v
        elif k == "表示":
            displays = [x.strip() for x in re.split(r"[,、]", v)]
        else:
            expects[k] = v
    return fills, expects, displays


# ---- per-check implementations ----------------------------------------------
def check_pages(name, text, meta, err):
    m = re.search(r"紙面予算[:：]\s*([0-9.]+)p", meta)
    if not m:
        err(f"P1 紙面予算がメタ情報にない")
        return
    budget = float(m.group(1))
    exp = EXPECTED_PAGES.get(name)
    if exp is not None and budget != exp:
        err(f"P1 紙面予算{budget:g}pが執筆計画書2.3の凍結値{exp}pと不一致")
    marks = []
    for _, ln in strip_code_blocks(text):
        if ln.startswith("## "):
            marks += [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)p", ln)]
    total = sum(marks)
    if abs(total - budget) > PAGE_TOLERANCE:
        err(f"P2 見出しページ配分の合計{total:g}pが紙面予算{budget:g}pの±{PAGE_TOLERANCE:g}p外")


def check_figures(name, text, err):
    refs = set()
    for _, ln in strip_code_blocks(text):
        if not ln.startswith("## "):
            continue
        for a, b in re.findall(r"図版(\d+)〜(\d+)", ln):
            refs.update(range(int(a), int(b) + 1))
        for m in re.findall(r"図版(\d+)(?![\d〜])", ln):
            refs.add(int(m))
    sec = re.search(r"^## 図版指示\n(.*?)(?=\n## |\Z)", text, re.S | re.M)
    rows = 0
    if sec:
        rows = len([l for l in sec.group(1).splitlines() if re.match(r"\|\s*\d+\s*\|", l)])
    if refs != set(range(1, rows + 1)):
        err(f"Z1 見出しの図版参照{sorted(refs)}と図版指示表の行数{rows}が不一致")


ARITH = re.compile(
    r"(?<![\d.〜])(\d+(?:\.\d+)?(?:\s*[+＋×÷/]\s*\d+(?:\.\d+)?)+)\s*[=＝]\s*(\d+(?:\.\d+)?)")


def check_arithmetic(name, text, err):
    for i, ln in strip_code_blocks(text):
        if "約" in ln or "…" in ln or "検証" in ln:
            continue
        for m in ARITH.finditer(ln):
            expr, stated = m.group(1), m.group(2)
            val = eval_expr(expr, {})
            if "." in stated:
                ok = round(val, len(stated.split(".")[1])) == float(stated)
            else:
                ok = abs(val - float(stated)) < 1e-9
            if not ok:
                err(f"A2 L{i} 計算不一致: {expr.strip()} = {stated}（再計算値 {val:g}）")


def check_pseudo_code(name, text, err):
    blocks = re.findall(r"^```\n(.*?)\n```\n?((?:\s*<!--.*?-->)?)", text, re.S | re.M)
    for idx, (code, trail) in enumerate(blocks):
        if "単元ID:" in code:
            continue
        if "検証" not in trail:
            err(f"X1 コード例{idx}に検証注記 <!-- 検証: ... --> がない（C-051未検証）")
            continue
        fills, expects, displays = parse_expect(trail)
        try:
            env, out = run_pseudo(code, fills)
        except PseudoError as e:
            err(f"X1 コード例{idx}の実行に失敗: {e}")
            continue
        for k, v in expects.items():
            want = eval_expr(v, {})
            got = env.get(k)
            if got is None or abs(got - want) > 1e-9:
                err(f"X1 コード例{idx}: 変数{k}の実行結果{got}が検証注記{v}と不一致")
        if displays is not None:
            want = [eval_expr(v, {}) for v in displays]
            if len(out) != len(want) or any(abs(a - b) > 1e-9 for a, b in zip(out, want)):
                err(f"X1 コード例{idx}: 表示出力{out}が検証注記{displays}と不一致")


CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def check_answer_keys(name, text, err):
    lines = [(i, ln) for i, ln in strip_code_blocks(text)
             if not ln.strip().startswith("※")]  # 誤答解説の注記行は対象外
    # 1行に選択肢が並ぶ形式（①…②…）: その行に正答マーカーがちょうど1つ
    for i, ln in lines:
        n_opts = sum(ln.count(c) for c in CIRCLED)
        if n_opts >= 3:
            n_ans = len(re.findall(r"[（(]正答", ln))
            if n_ans != 1:
                err(f"Q1 L{i} 選択肢行の正答マーカーが{n_ans}個（1個であるべき）")
    # 番号付きリスト形式（1. … 2. …）: 正答を含む連続ブロックで1つだけ
    run = []
    for i, ln in lines + [(0, "")]:
        if re.match(r"^\d+\.\s", ln.strip()):
            run.append((i, ln))
            continue
        if len(run) >= 2:
            n_ans = sum(len(re.findall(r"[（(]正答", l)) for _, l in run)
            if n_ans > 1:
                err(f"Q1 L{run[0][0]} 選択肢ブロックに正答マーカーが{n_ans}個（1個であるべき）")
        run = []


def unit_rank(vol: str, unit: str):
    """Order units within a volume; H1のCnn章は所属する部の直後に置く。"""
    kind, num = unit[0], int(unit[1:])
    if kind == "M":
        return 100 + num  # 選択モジュールは全コアPの後
    if kind == "C" and vol == "H1":
        part = 1 if num <= 5 else 2 if num <= 9 else 3 if num <= 14 else 4
        return part + 0.5
    return num


def check_prereqs(name, text, meta, own_goals, goals, goal_home, err):
    m = re.search(r"^前提[:：]\s*(.+)$", meta, re.M)
    if not m:
        return
    line = m.group(1)
    vol, unit = name.split("-", 1)
    my_rank = unit_rank(vol, unit)
    rest = line
    for gid in re.findall(GOAL_ID, line):
        rest = rest.replace(gid, " ")
        gvol = gid.split("-")[0]
        if gid not in goals:
            err(f"R1 前提の目標{gid}がgoals.jsonに存在しない")
        elif gvol == vol:
            # 同巻参照は「自単元の目標への注記」か「上流単元の目標」のみ正当
            if gid not in own_goals and not (
                    gid in goal_home and goal_home[gid] < my_rank):
                err(f"R1 前提の同巻目標{gid}が上流単元の目標でない")
        elif VOL_ORDER[gvol] >= VOL_ORDER[vol]:
            err(f"R1 前提の目標{gid}が下流の巻を参照している")
    for uvol, uref in re.findall(r"\b([EJH]\d)-(U\d+|P\d|M\d|C\d+)\b", rest):
        rest = rest.replace(f"{uvol}-{uref}", " ")
        if uvol == vol:
            if unit_rank(vol, uref) >= my_rank:
                err(f"R1 前提の{uvol}-{uref}が同巻の下流単元を参照している")
        elif VOL_ORDER[uvol] >= VOL_ORDER[vol]:
            err(f"R1 前提の{uvol}-{uref}が下流の巻を参照している")
    for uref in re.findall(r"(?<![\w－-])([PUMC]\d+)(?!\d)", rest):
        if unit_rank(vol, uref) >= my_rank:
            err(f"R1 前提の{uref}が同巻の下流単元を参照している")


def check_goal_transcription(name, text, meta, goals, err):
    ids = set()
    for ln in meta.splitlines():
        m = re.match(rf"\s*(★?)({GOAL_ID})【([{KANTEN}])】(.*)$", ln)
        if not m:
            continue
        star, gid, kanten, body = bool(m.group(1)), m.group(2), m.group(3), m.group(4).strip()
        ids.add(gid)
        rec = goals.get(gid)
        if rec is None:
            err(f"T1 到達目標{gid}がgoals.jsonに存在しない")
            continue
        if star != rec["star"]:
            err(f"T1 {gid}の★印がgoals.json（star={rec['star']}）と不一致")
        if kanten != rec["kanten"]:
            err(f"T1 {gid}の観点【{kanten}】がgoals.json（【{rec['kanten']}】）と不一致")
        t = rec["text"]
        if body != t and not (body.startswith(t)
                              and body[len(t):].startswith("（") and body.endswith("）")):
            err(f"T1 {gid}の目標文がgoals.jsonの正文と不一致（転記のみの原則に違反）: {body!r}")
    return ids


def main() -> int:
    with open(ROOT / "data" / "goals.json", encoding="utf-8") as f:
        goals = {g["id"]: g for g in json.load(f)["goals"]}
    files = [(p.stem, p.read_text(encoding="utf-8")) for p in sorted(MAN.glob("[EJH]*.md"))]
    # goal_home[gid] = その目標を到達目標に持つ単元の巻内順位（最小値）
    goal_home = {}
    for name, text in files:
        vol, unit = name.split("-", 1)
        rank = unit_rank(vol, unit)
        for gid in re.findall(rf"({GOAL_ID})【", meta_block(text)):
            goal_home[gid] = min(goal_home.get(gid, rank), rank)
    errors, n_files, n_code = [], 0, 0
    for name, text in files:
        meta = meta_block(text)
        n_files += 1
        n_code += sum("単元ID:" not in c for c in re.findall(r"^```\n(.*?)\n```", text, re.S | re.M))

        def err(msg, name=name):
            errors.append(f"{name}: {msg}")

        check_pages(name, text, meta, err)
        check_figures(name, text, err)
        check_arithmetic(name, text, err)
        check_pseudo_code(name, text, err)
        check_answer_keys(name, text, err)
        own = check_goal_transcription(name, text, meta, goals, err)
        check_prereqs(name, text, meta, own, goals, goal_home, err)

    for e in errors:
        print(f"ERROR {e}")
    print(f"files={n_files} code_examples={n_code} errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
