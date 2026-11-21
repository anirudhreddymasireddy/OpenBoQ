"""Price forecast for the what-if tab: parsing, model and the bundled snapshot (no network)."""
import math
from datetime import date

from openboq import forecast as F


def _months(start: str, n: int):
    out, m = [], start
    for _ in range(n):
        out.append(m)
        m = F._add(m, 1)
    return out


def test_parse_eurostat_monthly_and_quarterly():
    js = {"id": ["freq", "geo", "time"], "size": [1, 1, 3], "value": {"0": 100, "2": 102.5},
          "dimension": {"time": {"category": {"index": {"2026-Q1": 0, "2026-Q2": 1, "2026-Q3": 2}}}}}
    s = F.parse_eurostat(js)
    assert s["2026-01"] == s["2026-03"] == 100 and s["2026-09"] == 102.5 and "2026-04" not in s
    assert F._month_key("2026M10") == ["2026-10"]


def test_commodity_path_hits_world_bank_anchors():
    monthly = {m: 120.0 for m in _months("2024-01", 34)}            # last: 2026-10
    p = F.commodity_path(monthly, {"2026": 91, "2027": 79, "2028": 70}, "2029-06")
    assert min(p) == "2026-11" and abs(p["2027-07"] - 79) < 1e-9 and abs(p["2028-07"] - 70) < 1e-9
    assert p["2029-06"] == 70 and 79 < p["2027-01"] < 120


def test_trend_and_commodity_linked_forecast():
    ms = _months("2016-01", 130)
    oil = {m: 60 * (1.5 if i % 24 < 12 else 1.0) for i, m in enumerate(ms)}
    data = {"history": {"fuel": {"series": {m: 100 * (oil[m] / 60) ** 0.5 for m in ms}},       # elasticity 0.5
                        "concrete": {"series": {m: 100 * math.exp(0.03 * i / 12) for i, m in enumerate(ms)}}},
            "commodities": {"brent": {"series": oil}},
            "wb_forecast": {"annual": {"brent": {str(int(ms[-1][:4]) + 1): 45}}}}
    fc = F.forecast_all(data, date(int(ms[-1][:4]) + 1, 7, 1), 1)
    assert fc["fuel"].method == "commodity" and abs(fc["fuel"].beta - 0.5) < 0.02
    assert fc["concrete"].method == "trend" and abs(fc["concrete"].trend - 0.03) < 1e-6
    ch = F.expected_changes(fc, date(int(ms[-1][:4]) + 1, 7, 1), 1)
    e, lo, hi = ch["concrete"]
    assert lo <= e <= hi and 0 < e < 0.06
    assert ch["fuel"][0] < 0          # oil falls -> diesel falls


def test_bundled_snapshot_covers_every_driver():
    from openboq.whatif import DRIVERS
    data = F._read(F.SNAPSHOT)
    assert data and data["wb_forecast"]["annual"]["brent"] and data["wb_forecast"]["annual"]["iron_ore"]
    fc = F.forecast_all(data, date.today(), 12)
    assert set(fc) == set(DRIVERS) == set(F.DRIVER_SOURCES)
    for e, lo, hi in F.expected_changes(fc, date.today(), 12).values():
        assert lo <= e <= hi and -0.6 < e < 0.6
