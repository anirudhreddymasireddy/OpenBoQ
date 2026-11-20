from types import SimpleNamespace
from pathlib import Path

from openboq.evaluate import run
from openboq.gaeb_parser import parse_gaeb_xml, parse_number
from openboq.gaeb_writer import write_gaeb
from openboq.ifc_check import check_ifc
from openboq.pipeline import analyze
from openboq.rules import run_rules
from openboq.sample import make_sample_boq
from openboq.sample_ifc import make_sample_ifc


def test_number_parsing():
    assert parse_number("1.234,56") == 1234.56
    assert parse_number("1234.5") == 1234.5
    assert parse_number("1 234,5") == 1234.5


def test_gaeb_roundtrip(tmp_path: Path):
    b = make_sample_boq()
    p = write_gaeb(b, tmp_path / "lv.X84")
    r = parse_gaeb_xml(p)
    assert len(r.items) == len(b.items)
    assert abs(r.total - b.total) < 0.01
    assert r.items[0].oz == "01.0010"
    assert any(i.provisional for i in r.items)


def test_clean_lv_has_no_real_findings():
    flags = run_rules(make_sample_boq())
    assert not [f for f in flags if f.severity in ("high", "medium")]


def test_planted_errors_found():
    r = run(n_runs=20)
    assert r["recall"] >= 0.95
    assert r["precision"] >= 0.95


def test_ifc_crosscheck(tmp_path: Path):
    ifc = make_sample_ifc(tmp_path / "m.ifc")
    flags, table = check_ifc(make_sample_boq(), ifc)
    titles = " ".join(f.title for f in flags)
    assert "Unterzüge" in titles                 # element in model, missing in LV
    assert "Decken – Beton" in titles            # +13 % deviation
    assert not any("Bodenplatte" in f.title for f in flags)


class _FakeClient:
    """Mimics anthropic.Anthropic().messages.create with a tool_use answer."""
    def __init__(self):
        self.messages = self

    def create(self, **kw):
        block = SimpleNamespace(type="tool_use", input={"findings": [{
            "oz": "03.0080", "category": "besondere_leistung", "severity": "medium",
            "title": "Deckenrandabschalung fehlt", "message": "Randabschalung ist Besondere Leistung.",
            "reference": "VOB/C DIN 18331", "suggestion": "Position ergänzen", "risk_share": 0.05, "confidence": 0.8}]})
        text = SimpleNamespace(type="text", text="Zusammenfassung.")
        return SimpleNamespace(content=[block, text])


def test_llm_layer_with_fake_client():
    res = analyze(make_sample_boq(), use_llm=True, llm_client=_FakeClient())
    ai = [f for f in res.flags if f.source == "llm"]
    assert ai and ai[0].oz == "03.0080" and ai[0].exposure_eur > 0


class _RecordingClient:
    """Fake client: one finding per batch on its first item; records every request."""
    def __init__(self):
        import threading
        self.messages = self
        self.calls = []
        self.lock = threading.Lock()

    def create(self, **kw):
        with self.lock:
            self.calls.append(kw)
        user = kw["messages"][0]["content"]
        oz = user.split("OZ ", 1)[1].split(" ", 1)[0]
        block = SimpleNamespace(type="tool_use", input={"findings": [{
            "oz": oz, "category": "unklar", "severity": "low", "title": "t", "message": "m",
            "risk_share": 0.0, "confidence": 0.5}]})
        return SimpleNamespace(content=[block])


def test_llm_parallel_batches_cache_and_examples():
    from openboq.llm_checks import llm_item_checks
    boq = make_sample_boq()
    fake = _RecordingClient()
    flags = llm_item_checks(boq, client=fake, batch=5, workers=4)
    assert len(fake.calls) == 7                                   # 34 items / 5 per batch
    assert [f.oz for f in flags] == [boq.items[i].oz for i in range(0, 34, 5)]   # LV order kept
    sys_blocks = fake.calls[0]["system"]
    assert sys_blocks[-1]["cache_control"] == {"type": "ephemeral"}
    assert all(c["system"] is sys_blocks for c in fake.calls)    # identical cached prefix
    assert any("Beispiele für typische Mängel" in c["messages"][0]["content"] for c in fake.calls)


def test_embedding_retrieval_fallback():
    from openboq.embeddings import top_k
    corpus = ["Baugrube ausheben, Bodenklasse 3–5", "Fassadengerüst stellen", "Dämmung Bodenplatte ca. 10 cm"]
    hits = top_k(["Gerüst für die Fassade, Lastklasse 3"], corpus, k=1)
    assert hits[0][0][0] == 1
