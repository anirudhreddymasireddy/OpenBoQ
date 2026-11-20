"""Precision / recall of the checker on planted errors."""
from __future__ import annotations

from collections import defaultdict

from .inject import inject
from .model import Flag
from .rules import run_rules
from .sample import make_sample_boq

COUNTED = ("high", "medium")


def match(flag: Flag, gt: dict) -> bool:
    if flag.rule_id != gt["rule"]:
        return False
    if gt["oz"]:
        return flag.oz == gt["oz"]
    return gt.get("match", "") in flag.title


def score(flags: list[Flag], truth: list[dict]):
    found = [any(match(f, g) for f in flags) for g in truth]
    injected_oz = {g["oz"] for g in truth if g["oz"]}
    fps = []
    for f in flags:
        if f.severity not in COUNTED:
            continue
        if any(match(f, g) for g in truth):
            continue
        if f.oz and f.oz in injected_oz:   # secondary finding caused by the same planted defect
            continue
        fps.append(f)
    tp_flags = sum(1 for f in flags if f.severity in COUNTED and any(match(f, g) for g in truth))
    return found, fps, tp_flags


def run(n_runs: int = 25, n_item: int = 10, n_lv: int = 2, check=run_rules):
    clean = make_sample_boq()
    per_type = defaultdict(lambda: [0, 0])
    total_found = total_truth = total_fp = total_tp_flags = 0
    fp_examples = []
    miss_examples = []
    for seed in range(n_runs):
        boq, truth = inject(clean, n_item=n_item, n_lv=n_lv, seed=seed)
        flags = check(boq)
        found, fps, tp_flags = score(flags, truth)
        for g, ok in zip(truth, found):
            per_type[g["type"]][0] += int(ok)
            per_type[g["type"]][1] += 1
            if not ok and len(miss_examples) < 10:
                miss_examples.append((seed, g))
        total_found += sum(found)
        total_truth += len(truth)
        total_fp += len(fps)
        total_tp_flags += tp_flags
        fp_examples.extend((seed, f.rule_id, f.oz, f.title) for f in fps[:3])
    recall = total_found / max(1, total_truth)
    precision = total_tp_flags / max(1, total_tp_flags + total_fp)
    return {
        "runs": n_runs,
        "planted_errors": total_truth,
        "recall": recall,
        "precision": precision,
        "false_positives": total_fp,
        "per_type": {k: {"found": v[0], "planted": v[1], "recall": v[0] / v[1]} for k, v in sorted(per_type.items())},
        "fp_examples": fp_examples[:10],
        "miss_examples": miss_examples,
    }
