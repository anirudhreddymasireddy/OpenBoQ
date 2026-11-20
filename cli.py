"""Command line entry point.

Examples
  python cli.py demo                               # build sample data, plant errors, analyse, write report
  python cli.py analyze LV.X84 --ifc model.ifc     # analyse your own files
  python cli.py analyze LV.X84 --llm               # + Claude semantic checks (needs ANTHROPIC_API_KEY)
  python cli.py eval --runs 100                    # precision / recall on planted errors
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from openboq.gaeb_parser import load_boq
from openboq.gaeb_writer import write_gaeb
from openboq.inject import inject
from openboq.pipeline import analyze
from openboq.report import eur, to_excel, write_html
from openboq.sample import make_sample_boq
from openboq.sample_ifc import make_sample_ifc

DATA = Path(__file__).parent / "data"
OUT = Path(__file__).parent / "out"


def cmd_demo(args):
    DATA.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    clean = make_sample_boq()
    write_gaeb(clean, DATA / "sample_clean.X84")
    buggy, truth = inject(clean, n_item=args.errors, n_lv=2, seed=args.seed)
    write_gaeb(buggy, DATA / "sample_buggy.X84")
    (DATA / "ground_truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False), encoding="utf-8")
    make_sample_ifc(DATA / "sample_model.ifc")
    boq = load_boq(DATA / "sample_buggy.X84")
    res = analyze(boq, ifc=DATA / "sample_model.ifc", use_llm=args.llm)
    write_html(res, OUT / "report.html")
    to_excel(res, OUT / "report.xlsx")
    print(f"{len(boq.items)} Positionen, LV-Summe {eur(boq.total)}")
    print(f"Nachtragsrisiko {eur(res.exposure)}  |  Befunde {res.by_severity()}  |  {res.seconds:.2f} s")
    print(f"Report: {OUT/'report.html'}")


def cmd_analyze(args):
    OUT.mkdir(exist_ok=True)
    boq = load_boq(args.file)
    res = analyze(boq, ifc=args.ifc, use_llm=args.llm)
    stem = Path(args.file).stem
    write_html(res, OUT / f"{stem}_report.html")
    to_excel(res, OUT / f"{stem}_report.xlsx")
    print(f"{len(boq.items)} Positionen, LV-Summe {eur(boq.total)}")
    print(f"Nachtragsrisiko {eur(res.exposure)}  |  Befunde {res.by_severity()}")
    for f in res.flags[: args.top]:
        print(f"  [{f.severity:6s}] {f.oz or 'LV':12s} {f.title}  ({eur(f.exposure_eur)})")


def cmd_eval(args):
    from openboq.evaluate import run
    r = run(n_runs=args.runs, n_item=args.errors)
    print(f"{r['runs']} Läufe, {r['planted_errors']} eingepflanzte Fehler")
    print(f"Recall {r['recall']:.1%}   Precision {r['precision']:.1%}   False Positives {r['false_positives']}")
    for k, v in r["per_type"].items():
        print(f"  {k:24s} {v['found']:4d}/{v['planted']:4d}  {v['recall']:.0%}")


def main():
    p = argparse.ArgumentParser(description="OpenBoQ – LV-Prüfung")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo"); d.add_argument("--errors", type=int, default=10); d.add_argument("--seed", type=int, default=1)
    d.add_argument("--llm", action="store_true"); d.set_defaults(fn=cmd_demo)
    a = sub.add_parser("analyze"); a.add_argument("file"); a.add_argument("--ifc"); a.add_argument("--llm", action="store_true")
    a.add_argument("--top", type=int, default=25); a.set_defaults(fn=cmd_analyze)
    e = sub.add_parser("eval"); e.add_argument("--runs", type=int, default=50); e.add_argument("--errors", type=int, default=10)
    e.set_defaults(fn=cmd_eval)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
