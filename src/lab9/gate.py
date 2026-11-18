"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []

    # 1. NaN or inf in pr["metrics"]
    for k, v in pr.get("metrics", {}).items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            problems.append(f"metric {k} is NaN or inf")

    # 2. Row count mismatch with manifest
    manifest = pr.get("manifest", {})
    expected_rows = manifest.get("items", 0) * len(manifest.get("seeds", []))
    if expected_rows > 0 and len(pr.get("rows", [])) != expected_rows:
        problems.append(f"row count {len(pr.get('rows', []))} != manifest {expected_rows}")

    # 3. (item_id, seed) set of PR differs from baseline
    pr_keys = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows", [])}
    base_keys = {(r.get("item_id"), r.get("seed")) for r in base.get("rows", [])}
    if pr_keys != base_keys:
        problems.append("PR (item_id, seed) set differs from baseline (cherry-picked or missing)")

    # 4. evaluator_failures or None values for graded spec metrics in rows
    if pr.get("evaluator_failures"):
        problems.append(f"evaluator_failures non-empty: {len(pr['evaluator_failures'])} failure(s)")
    spec_metrics = [m["id"] for m in spec.get("metrics", [])]
    for r in pr.get("rows", []):
        for mid in spec_metrics:
            if mid in r and r[mid] is None:
                problems.append(f"row {r.get('item_id')} seed {r.get('seed')} has None for metric {mid}")
                break

    # 5. base_spec ratchet check
    if base_spec and spec.get("eval_set_version") == base_spec.get("eval_set_version"):
        base_m_map = {m["id"]: m for m in base_spec.get("metrics", [])}
        spec_m_map = {m["id"]: m for m in spec.get("metrics", [])}

        # A metric in base_spec may not disappear
        for mid in base_m_map:
            if mid not in spec_m_map:
                problems.append(f"metric {mid} disappeared from spec")

        for mid, bm in base_m_map.items():
            sm = spec_m_map.get(mid)
            if not sm:
                continue
            # A blocking metric may not become non-blocking
            if bm.get("blocking") and not sm.get("blocking"):
                problems.append(f"metric {mid} became non-blocking")

            b_th = bm.get("threshold", {})
            s_th = sm.get("threshold", {})

            if "min" in b_th and s_th.get("min", float("-inf")) < b_th["min"]:
                problems.append(f"metric {mid} min threshold loosened: {s_th.get('min')} < {b_th['min']}")
            if "max" in b_th and s_th.get("max", float("inf")) > b_th["max"]:
                problems.append(f"metric {mid} max threshold loosened: {s_th.get('max')} > {b_th['max']}")
            if "max_increase" in b_th and s_th.get("max_increase", float("inf")) > b_th["max_increase"]:
                problems.append(f"metric {mid} max_increase loosened")
            if b_th.get("no_significant_drop") and not s_th.get("no_significant_drop"):
                problems.append(f"metric {mid} dropped no_significant_drop")

        # Same ratchet check for slices
        base_slices = {s["name"]: s for s in base_spec.get("slices", [])}
        spec_slices = {s["name"]: s for s in spec.get("slices", [])}
        for name, bs in base_slices.items():
            if name not in spec_slices:
                problems.append(f"slice {name} disappeared from spec")
                continue
            ss = spec_slices[name]
            if bs.get("blocking") and not ss.get("blocking"):
                problems.append(f"slice {name} became non-blocking")
            if "min" in bs and ss.get("min", float("-inf")) < bs["min"]:
                problems.append(f"slice {name} min loosened: {ss.get('min')} < {bs['min']}")
            if bs.get("no_significant_drop") and not ss.get("no_significant_drop"):
                problems.append(f"slice {name} dropped no_significant_drop")

    # 6. Item slice tags differ from baseline
    pr_slice_map = {(r.get("item_id"), r.get("seed")): tuple(sorted(r.get("slices") or [])) for r in pr.get("rows", [])}
    base_slice_map = {(r.get("item_id"), r.get("seed")): tuple(sorted(r.get("slices") or [])) for r in base.get("rows", [])}
    for k in base_slice_map:
        if k in pr_slice_map and pr_slice_map[k] != base_slice_map[k]:
            problems.append(f"slice tags for {k} changed: {pr_slice_map[k]} != {base_slice_map[k]}")
            break

    return problems


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    slices = spec.get("slices") or []
    bs = spec.get("bootstrap", {})

    for sl in slices:
        name = sl["name"]
        metric = sl["metric"]
        min_val = sl.get("min")
        blocking = sl.get("blocking", False)
        no_drop = sl.get("no_significant_drop", False)

        a = per_item(pr, metric, slice_name=name)
        b = per_item(base, metric, slice_name=name)
        if not a:
            continue
        val = round(sum(a.values()) / len(a), 4)
        verdict, note = "ok", ""

        if min_val is not None and val < min_val:
            verdict = "fail"
        if no_drop and b:
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap(
                [a[k] for k in keys], [b[k] for k in keys],
                n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027)
            )
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"

        slice_id = f"slice:{name}/{metric}"
        if verdict != "ok" and blocking:
            blocked.append(slice_id)
        label = {"ok": "ok"}.get(verdict, "BLOCK" if blocking else "warn")
        lines.append(f"  {slice_id:<22} {val!s:<8} {json.dumps(sl):<40} {note:<28} {label}")

    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    spec = load_spec(Path(args.spec))
    blocked, lines = check(pr, base, spec, base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    for line in lines:
        print(line)
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
