"""Command line entry point.

Examples
  python cli.py demo                               # build sample data, plant errors, analyse, write report
  python cli.py analyze LV.X84 --ifc model.ifc     # analyse your own files
  python cli.py analyze LV.X84 --llm               # + Claude semantic checks (needs ANTHROPIC_API_KEY)
  python cli.py analyze LV.pdf --lang en           # report and findings in English
  python cli.py batch dataset --lang en            # analyse every file in a folder (one report each in out/)
  python cli.py adduser anirudh "Anirudh R."       # dashboard login (asks for the password)
  python cli.py learn dataset                      # learn unit prices from priced files (data/price_db.json)
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
from openboq.i18n import T
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
    L = args.lang
    res = analyze(boq, ifc=DATA / "sample_model.ifc", use_llm=args.llm, lang=L, prices=None)
    write_html(res, OUT / "report.html", L)
    to_excel(res, OUT / "report.xlsx", L)
    print(f"{len(boq.items)} {T('items', L)}, {T('lv_sum', L)} {eur(boq.total, L)}")
    print(f"{T('cli_risk', L)} {eur(res.exposure, L)}  |  {T('cli_findings', L)} {res.by_severity()}  |  {res.seconds:.2f} s")
    print(f"Report: {OUT/'report.html'}")


def cmd_analyze(args):
    OUT.mkdir(exist_ok=True)
    boq = load_boq(args.file)
    L = args.lang
    res = analyze(boq, ifc=args.ifc, use_llm=args.llm, lang=L, source=Path(args.file).name)
    stem = Path(args.file).name.replace(".", "_")   # keep extension: X.pdf and X.D84 must not overwrite each other
    write_html(res, OUT / f"{stem}_report.html", L)
    to_excel(res, OUT / f"{stem}_report.xlsx", L)
    print(f"{Path(args.file).name}: {len(boq.items)} {T('items', L)}, {T('lv_sum', L)} {eur(boq.total, L)}")
    print(f"{T('cli_risk', L)} {eur(res.exposure, L)}  |  {T('cli_findings', L)} {res.by_severity()}")
    for f in res.flags[: args.top]:
        print(f"  [{f.severity:6s}] {f.oz or 'LV':12s} {f.txt(L)[0]}  ({eur(f.exposure_eur, L)})")


def cmd_adduser(args):
    import getpass
    from openboq import auth
    pw = getpass.getpass(f"Password for {args.username}: ")
    if pw != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return
    auth.add_user(args.username, pw, args.name or args.username)
    print(f"User '{args.username}' saved -> {auth.USERS_PATH}")


def cmd_batch(args):
    """Analyse every BoQ file in a folder in one process (much faster than one call per file)."""
    import glob
    import time
    OUT.mkdir(exist_ok=True)
    L = args.lang
    files = sorted({f for ext in ("pdf", "x8?", "X8?", "d8?", "D8?", "xlsx", "csv")
                    for f in glob.glob(str(Path(args.folder) / "**" / f"*.{ext}"), recursive=True)})
    t0 = time.time()
    rows = []
    for f in files:
        try:
            boq = load_boq(f)
            res = analyze(boq, lang=L, source=Path(f).name)
        except Exception as e:                     # one broken file must not stop the batch
            print(f"  ! {Path(f).name}: {e}")
            continue
        stem = Path(f).name.replace(".", "_")
        try:
            write_html(res, OUT / f"{stem}_report.html", L)
            to_excel(res, OUT / f"{stem}_report.xlsx", L)
        except Exception as e:
            print(f"  ! {Path(f).name}: report not written ({e})")
        sev = res.by_severity()
        rows.append((Path(f).name, len(boq.items), sev["high"], sev["medium"]))
        print(f"{Path(f).name[:48]:48s} {len(boq.items):5d} {T('items', L)} | high {sev['high']:3d} | medium {sev['medium']:3d}")
    print(f"{len(rows)} files, {sum(r[1] for r in rows)} items in {time.time() - t0:.0f} s -> {OUT}")


def cmd_learn(args):
    import glob
    from openboq.prices import build_db, evaluate_leave_one_out, save_db
    files = [f for ext in ("pdf", "x8?", "X8?", "d8?", "D8?", "xlsx", "csv")
             for f in glob.glob(str(Path(args.folder) / "**" / f"*.{ext}"), recursive=True)]
    rows = build_db(sorted(set(files)))
    path = save_db(rows)
    ev = evaluate_leave_one_out(rows)
    print(f"{len(rows)} priced items from {len({r['source'] for r in rows})} files "
          f"({len({r['project'] for r in rows})} projects) -> {path}")
    if ev["covered"]:
        print(f"Cross-project check: {ev['covered']} items ({ev['coverage']:.0%}) found comparable items in other projects; "
              f"median error {ev['median_abs_pct_error']:.0%}, {ev['within_50pct']:.0%} within ±50 %")


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
    d.add_argument("--llm", action="store_true"); d.add_argument("--lang", choices=["de", "en"], default="de")
    d.set_defaults(fn=cmd_demo)
    a = sub.add_parser("analyze"); a.add_argument("file"); a.add_argument("--ifc"); a.add_argument("--llm", action="store_true")
    a.add_argument("--top", type=int, default=25); a.add_argument("--lang", choices=["de", "en"], default="de")
    a.set_defaults(fn=cmd_analyze)
    au = sub.add_parser("adduser", help="create or update a dashboard login")
    au.add_argument("username"); au.add_argument("name", nargs="?", default=""); au.set_defaults(fn=cmd_adduser)
    bt = sub.add_parser("batch", help="analyse all BoQ files in a folder")
    bt.add_argument("folder"); bt.add_argument("--lang", choices=["de", "en"], default="de"); bt.set_defaults(fn=cmd_batch)
    lr = sub.add_parser("learn", help="learn unit prices from priced BoQs in a folder")
    lr.add_argument("folder"); lr.set_defaults(fn=cmd_learn)
    e = sub.add_parser("eval"); e.add_argument("--runs", type=int, default=50); e.add_argument("--errors", type=int, default=10)
    e.set_defaults(fn=cmd_eval)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
