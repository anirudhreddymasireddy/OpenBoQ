"""Human in the loop: reviewers confirm or dismiss findings; OpenBoQ remembers and learns.

Stored per decision (SQLite, data/feedback.db – git-ignored):
  flag     rule, title, severity, category
  item     OZ, text, unit, trade (section heading), context
  project  name, client, public/private, date, project type
  decision confirmed/dismissed, reason, reviewer, timestamp
  outcome  later, optional: "dispute" | "clarified" | "no_issue"  ("troublemaker data")

Learning, deliberately simple and visible:
  1. Memory       – same finding on the same item text decided before -> same decision is pre-filled
                    (auto-dismissed findings leave the counts but stay viewable, with who/when/why).
  2. Calibration  – a rule dismissed >= 80 % of the time (>= 5 decisions) for a trade or client is lowered
                    one severity level, with the reason shown.
  Safety: calibration never lowers contract-risk or security findings (R20, S01, S02).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re
import sqlite3
from pathlib import Path

from .model import BoQ, Flag

# NR_FEEDBACK_DB lets a team share one decisions file (e.g. on a shared drive)
DB_PATH = Path(os.environ.get("NR_FEEDBACK_DB") or Path(__file__).resolve().parent.parent / "data" / "feedback.db")
MIN_DECISIONS = 5
MIN_OUTCOMES = 3
MIN_SIMILAR = 2          # similar past items (by short + long text) needed for a content-based weight
SIM_THRESHOLD = 0.35
DISMISS_RATE = 0.8
PROTECTED = {"R20", "S01", "S02"}
SEV_DOWN = {"high": "medium", "medium": "low", "low": "low", "info": "info"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fingerprint TEXT, rule_id TEXT, flag_title TEXT, severity TEXT, category TEXT,
  item_oz TEXT, item_text TEXT, item_unit TEXT, trade TEXT, context TEXT,
  project TEXT, client TEXT, public INTEGER, project_date TEXT, project_type TEXT,
  decision TEXT, reason TEXT, reviewer TEXT, decided_at TEXT,
  outcome TEXT, outcome_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_fp ON decisions(fingerprint);
CREATE INDEX IF NOT EXISTS ix_rule ON decisions(rule_id);
"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def fingerprint(f: Flag, boq: BoQ) -> str:
    """Same rule + same item content = same finding, across files and projects."""
    it = boq.by_oz().get(f.oz) if f.oz else None
    if it is not None:
        basis = f"{f.rule_id}|{_norm(it.short_text)}|{_norm(it.long_text)[:300]}|{_norm(it.unit)}|{_norm(f.title)}"
    else:
        basis = f"{f.rule_id}|{_norm(f.title)}|{_norm(f.message)[:200]}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


class FeedbackStore:
    def __init__(self, path: Path | str = DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)

    # ------------------------------------------------------------------ write
    def record(self, f: Flag, boq: BoQ, decision: str, reason: str = "", reviewer: str = "",
               meta: dict | None = None) -> int:
        assert decision in ("confirmed", "dismissed")
        meta = meta or {}
        it = boq.by_oz().get(f.oz) if f.oz else None
        cur = self.con.execute(
            """INSERT INTO decisions (fingerprint, rule_id, flag_title, severity, category, item_oz, item_text, item_unit,
               trade, context, project, client, public, project_date, project_type, decision, reason, reviewer, decided_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fingerprint(f, boq), f.rule_id, f.title, f.severity, f.category, f.oz,
             (f"{it.short_text}\n{it.long_text}" if it else f.message)[:2000], it.unit if it else "",
             (it.section if it else "") or "", boq.sections.get(".".join(f.oz.split(".")[:-1]), "") if f.oz else "",
             meta.get("project", boq.project or boq.name), meta.get("client", boq.client),
             int(bool(meta.get("public"))) if meta.get("public") is not None else None,
             meta.get("date", _dt.date.today().isoformat()), meta.get("project_type", ""),
             decision, reason, reviewer, _dt.datetime.now().isoformat(timespec="seconds")))
        self.con.commit()
        return cur.lastrowid

    def set_outcome(self, decision_id: int, outcome: str) -> None:
        assert outcome in ("dispute", "clarified", "no_issue")
        self.con.execute("UPDATE decisions SET outcome=?, outcome_at=? WHERE id=?",
                         (outcome, _dt.datetime.now().isoformat(timespec="seconds"), decision_id))
        self.con.commit()

    # ------------------------------------------------------------------ read
    def latest_by_fingerprint(self) -> dict[str, sqlite3.Row]:
        rows = self.con.execute("SELECT * FROM decisions ORDER BY id").fetchall()
        return {r["fingerprint"]: r for r in rows}          # later decisions overwrite earlier ones

    def rule_stats(self) -> dict[tuple, tuple[int, int]]:
        """(rule_id, 'trade'|'client', value) -> (n_decisions, n_dismissed)."""
        out: dict[tuple, list[int]] = {}
        for r in self.con.execute("SELECT rule_id, trade, client, decision FROM decisions"):
            for kind, val in (("trade", r["trade"]), ("client", r["client"])):
                if not val:
                    continue
                k = (r["rule_id"], kind, val)
                s = out.setdefault(k, [0, 0])
                s[0] += 1
                s[1] += r["decision"] == "dismissed"
        return {k: (v[0], v[1]) for k, v in out.items()}

    def outcome_stats(self) -> dict[str, tuple[int, int]]:
        """rule_id -> (findings with a recorded outcome, of which caused a dispute)."""
        out = {}
        for r in self.con.execute("SELECT rule_id, outcome FROM decisions WHERE outcome IS NOT NULL AND decision='confirmed'"):
            n, d = out.get(r["rule_id"], (0, 0))
            out[r["rule_id"]] = (n + 1, d + (r["outcome"] == "dispute"))
        return out

    def outcome_records(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT rule_id, item_oz, item_text, outcome, project FROM decisions "
                                "WHERE outcome IS NOT NULL AND decision='confirmed'").fetchall()

    def project_decisions(self, project: str) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM decisions WHERE project=? AND decision='confirmed' ORDER BY id DESC",
                                (project,)).fetchall()

    def summary(self) -> dict:
        r = self.con.execute("""SELECT COUNT(*) n, SUM(decision='confirmed') c, SUM(decision='dismissed') d,
                                SUM(outcome='dispute') disp FROM decisions""").fetchone()
        return {"decisions": r["n"] or 0, "confirmed": r["c"] or 0, "dismissed": r["d"] or 0, "disputes": r["disp"] or 0}

    def all(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM decisions ORDER BY id DESC").fetchall()


# ---------------------------------------------------------------------- learning
def apply_learning(flags: list[Flag], boq: BoQ, store: FeedbackStore | None) -> list[Flag]:
    """Pre-fill decisions from memory and calibrate severities. Mutates and returns flags."""
    if store is None:
        return flags
    memory = store.latest_by_fingerprint()
    stats = store.rule_stats()
    outcomes = store.outcome_stats()
    items = boq.by_oz()
    content_w = _content_weights(flags, boq, store)
    for f in flags:
        # outcome data: what became of past findings on *similar work* (short + long text) sets the € weight;
        # without similar items, fall back to the finding type (check ID)
        if f.exposure_eur and id(f) in content_w:
            factor, n_s, d_s, example = content_w[id(f)]
            f.exposure_eur *= factor
            f.learned = {"de": f"€-Gewicht ×{factor:.2f}: {d_s} von {n_s} ähnlichen früheren Positionen endeten mit Warnung "
                               f"(z. B. „{example}“).",
                         "en": f"€ weight ×{factor:.2f}: {d_s} of {n_s} similar past items ended as a warning (e.g. '{example}')."}
        else:
            n_o, d_o = outcomes.get(f.rule_id, (0, 0))
            if n_o >= MIN_OUTCOMES and f.exposure_eur:
                factor = max(0.25, min(2.0, 2 * d_o / n_o))
                f.exposure_eur *= factor
                f.learned = {"de": f"€-Gewicht ×{factor:.2f}: {d_o} von {n_o} früheren Befunden dieser Art endeten mit Warnung (Streit/Nachtrag).",
                             "en": f"€ weight ×{factor:.2f}: {d_o} of {n_o} past findings of this type ended as a warning (dispute/claim)."}
        r = memory.get(fingerprint(f, boq))
        if r is not None:
            f.decision = {"status": r["decision"], "by": r["reviewer"] or "–", "at": (r["decided_at"] or "")[:10],
                          "reason": r["reason"] or "", "source": "memory"}
            continue
        if f.rule_id in PROTECTED or f.severity in ("low", "info"):
            continue
        it = items.get(f.oz) if f.oz else None
        for kind, val in (("trade", it.section if it else ""), ("client", boq.client)):
            n, d = stats.get((f.rule_id, kind, val), (0, 0)) if val else (0, 0)
            if n >= MIN_DECISIONS and d / n >= DISMISS_RATE:
                old = f.severity
                f.severity = SEV_DOWN[f.severity]
                f.learned = {"de": f"Schwere {old} → {f.severity}: {d} von {n} gleichartigen Befunden "
                                   f"({'Gewerk' if kind == 'trade' else 'AG'} „{val}“) wurden verworfen.",
                             "en": f"Severity {old} → {f.severity}: {d} of {n} similar findings "
                                   f"({kind} '{val}') were dismissed."}
                break
    return flags


def _content_weights(flags: list[Flag], boq: BoQ, store: FeedbackStore) -> dict:
    """id(flag) -> (factor, n_similar, n_warning, example short text) from past outcomes on similar item texts."""
    recs = store.outcome_records()
    items = boq.by_oz()
    targets = [f for f in flags if f.oz and f.oz in items and f.exposure_eur]
    if not recs or not targets:
        return {}
    from .embeddings import top_k
    corpus = [r["item_text"] or "" for r in recs]
    queries = [f"{items[f.oz].short_text}\n{items[f.oz].long_text}" for f in targets]
    out = {}
    for f, hits in zip(targets, top_k(queries, corpus, k=8)):
        sim = [(recs[i], s) for i, s in hits if s >= SIM_THRESHOLD]
        same_type = [(r, s) for r, s in sim if r["rule_id"] == f.rule_id]
        pool = same_type if len(same_type) >= MIN_SIMILAR else sim
        if len(pool) < MIN_SIMILAR:
            continue
        n = len(pool)
        d = sum(r["outcome"] == "dispute" for r, _ in pool)
        example = (pool[0][0]["item_text"] or "").split("\n", 1)[0][:60]
        out[id(f)] = (max(0.25, min(2.0, 2 * d / n)), n, d, example)
    return out


def is_dismissed(f: Flag) -> bool:
    return (f.decision or {}).get("status") == "dismissed"


def is_confirmed(f: Flag) -> bool:
    return (f.decision or {}).get("status") == "confirmed"
