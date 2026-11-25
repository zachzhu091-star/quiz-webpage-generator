#!/usr/bin/env python3
"""校验趣味测试网页的题库数据 + 模拟结果分布。

用法:
    python3 validate_quiz.py path/to/quiz.html [--sims 5000]

做四件事:
1. 抽取出页面里的 <script type="application/json" id="quiz-data"> 并解析
2. 结构校验: 字段完整性、结果 id 引用、每题选项数、重复文案
3. 可达性校验: 每个结果能否被"一路选它"答出来（避免死类型）
4. 随机作答模拟: 均匀随机选 5000 次, 看结果分布是否失衡
"""
import argparse
import json
import random
import re
import sys
from collections import Counter

DATA_RE = re.compile(
    r'<script[^>]*type="application/json"[^>]*id="quiz-data"[^>]*>(.*?)</script>',
    re.S,
)

REQUIRED_META = ["title"]
REQUIRED_RESULT = ["id", "name"]
WARN_MIN, WARN_MAX = 0.04, 0.40


def load(path):
    with open(path, encoding="utf-8") as f:
        html = f.read()
    m = DATA_RE.search(html)
    if not m:
        sys.exit("✗ 找不到 <script type=\"application/json\" id=\"quiz-data\">")
    try:
        return json.loads(m.group(1)), html
    except json.JSONDecodeError as e:
        sys.exit(f"✗ quiz-data JSON 语法错误 (行 {e.lineno} 列 {e.colno}): {e.msg}")


def score_picks(data, picks):
    """picks: 每题选项下标列表 -> (分数表, 排序列表)
    与页面引擎一致: 并列时看最近 6 题倾向, 再并列按 results 顺序。
    """
    ids = [r["id"] for r in data["results"]]
    totals = {i: 0 for i in ids}
    recent = {i: 0 for i in ids}
    start = max(0, len(picks) - 6)
    for qi, oi in enumerate(picks):
        opt = data["questions"][qi]["options"][oi]
        for k, v in (opt.get("s") or {}).items():
            totals[k] = totals.get(k, 0) + v
            if qi >= start:
                recent[k] = recent.get(k, 0) + v
    order = {rid: n for n, rid in enumerate(ids)}
    ranked = sorted(ids, key=lambda rid: (-totals[rid], -recent[rid], order[rid]))
    return totals, [(rid, totals[rid]) for rid in ranked]


def match_pct(ranked):
    top, second = ranked[0][1], (ranked[1][1] if len(ranked) > 1 else 0)
    if top <= 0:
        return 72
    return max(72, min(99, round(72 + 27 * (1 - second / top))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--sims", type=int, default=5000)
    args = ap.parse_args()

    data, html = load(args.path)
    errors, warns = [], []

    results = data.get("results") or []
    questions = data.get("questions") or []
    meta = data.get("meta") or {}
    ids = [r.get("id") for r in results]

    # ---- 结构 ----
    for k in REQUIRED_META:
        if not meta.get(k):
            errors.append(f"meta.{k} 缺失")
    if not 3 <= len(results) <= 10:
        errors.append(f"结果类型 {len(results)} 个，建议 4-8 个")
    if len(set(ids)) != len(ids):
        errors.append(f"结果 id 有重复: {ids}")
    for r in results:
        for k in REQUIRED_RESULT:
            if not r.get(k):
                errors.append(f"结果 {r.get('id')} 缺字段 {k}")
        if len(r.get("traits") or []) < 2:
            warns.append(f"结果 {r['id']} 的 traits 少于 2 条，结果页会显得单薄")
        for k in ("quote", "match", "edge", "egg", "tag", "emoji"):
            if not r.get(k):
                warns.append(f"结果 {r['id']} 缺字段 {k}")
    if not 10 <= len(questions) <= 60:
        errors.append(f"题目 {len(questions)} 道，建议 15-40 道")
    if not data.get("theme", {}).get("accent"):
        warns.append("theme.accent 未设置，将用默认金色")

    seen_q = Counter()
    for i, q in enumerate(questions, 1):
        if not q.get("q"):
            errors.append(f"第 {i} 题缺题干")
        seen_q[q.get("q")] += 1
        opts = q.get("options") or []
        if len(opts) not in (2, 3, 4, 5):
            errors.append(f"第 {i} 题有 {len(opts)} 个选项，建议 4 个")
        for j, o in enumerate(opts):
            if not o.get("t"):
                errors.append(f"第 {i} 题选项 {'ABCDE'[j] if j < 5 else j} 缺文案")
            s = o.get("s")
            if not s or not isinstance(s, dict):
                errors.append(f"第 {i} 题选项 {j + 1} 缺 s 权重")
                continue
            for rid, v in s.items():
                if rid not in ids:
                    errors.append(f"第 {i} 题选项 {j + 1} 引用了不存在的结果 id: {rid}")
                if not isinstance(v, (int, float)) or v <= 0:
                    errors.append(f"第 {i} 题选项 {j + 1} 的 {rid} 权重须为正数")
    dup_q = [q for q, c in seen_q.items() if c > 1]
    if dup_q:
        warns.append(f"有重复题干: {dup_q[:3]}")

    if errors:
        print("✗ 结构校验未通过")
        for e in errors:
            print("  -", e)
        sys.exit(1)

    # ---- 可达性：每个结果都要有"顺着它选"的路径能拿第一 ----
    print("【可达性】每个结果一路偏向自己作答时的得分：")
    unreachable = []
    for rid in ids:
        picks = []
        for q in questions:
            best, best_v = 0, -1
            for j, o in enumerate(q["options"]):
                v = (o.get("s") or {}).get(rid, 0)
                if v > best_v:
                    best, best_v = j, v
            picks.append(best)
        totals, ranked = score_picks(data, picks)
        top = ranked[0][0]
        ok = top == rid
        print(f"  {'✓' if ok else '✗'} {rid:<12} 得分 {totals[rid]:>3}  →  第一名 {top}")
        if not ok:
            unreachable.append((rid, tot1 := top, totals[rid], totals[top]))
    for rid, top, mine, theirs in unreachable:
        errors.append(
            f"结果 {rid} 无法通过顺选达成（它 {mine} 分，{top} {theirs} 分）——该类型是死类型"
        )

    # ---- 随机模拟 ----
    random.seed(7)
    dist = Counter()
    tie = 0
    pcts = []
    for _ in range(args.sims):
        picks = [random.randrange(len(q["options"])) for q in questions]
        totals, ranked = score_picks(data, picks)
        dist[ranked[0][0]] += 1
        if ranked[0][1] == ranked[1][1]:
            tie += 1
        pcts.append(match_pct(ranked))

    print(f"\n【随机作答 {args.sims} 次的结果分布】")
    for rid in ids:
        c = dist[rid]
        share = c / args.sims
        flag = ""
        if share < WARN_MIN:
            flag = "  ← 偏冷门"
            warns.append(f"结果 {rid} 随机命中率仅 {share:.1%}，用户很少测到它")
        elif share > WARN_MAX:
            flag = "  ← 偏集中"
            warns.append(f"结果 {rid} 随机命中率 {share:.1%}，会显得千篇一律")
        print(f"  {rid:<12} {c:>5}  {share:6.1%}  {'█' * int(share * 60)}{flag}")
    tie_rate = tie / args.sims
    print(f"\n分数并列比例: {tie_rate:.1%}（并列由最近 6 题倾向决定，属正常现象）")
    if tie_rate > 0.30:
        warns.append("并列比例过高，建议给选项补 1 分的次权重，拉开分差")
    print(f"匹配度区间: {min(pcts)}%-{max(pcts)}%（72% 起，随领先幅度升高）")

    # ---- 附加检查 ----
    if "quiz-template" not in html:
        pass  # 用户改过的页面，不强求
    if len(html) > 900_000:
        warns.append("页面超过 900KB，手机上首屏可能偏慢")

    print()
    if errors:
        print("✗ 存在问题")
        for e in errors:
            print("  -", e)
        sys.exit(1)
    if warns:
        print("⚠ 通过，但有建议：")
        for w in warns:
            print("  -", w)
    else:
        print("✓ 全部通过，可以直接交付")


if __name__ == "__main__":
    main()
