"""Price forecasts for the what-if tab: expected material price change by the time the work is built.

Data (all free, no API key):

* German producer price indices per material (Eurostat ``sts_inppd_m``, reported by Destatis), the German HICP for
  refuse collection (disposal fees) and the Eurostat labour cost index for construction (wages).
* World Bank Commodity Markets Outlook: annual forecasts for Brent crude and iron ore (next 2–3 years), plus the
  monthly "Pink Sheet" history of both.

Method, per cost driver (see ``DRIVER_SOURCES``):

* Oil- or ore-linked (diesel, bitumen, plastics, steel): the German index follows the World Bank commodity path with an
  elasticity β estimated from the history (12-month log changes, OLS, clipped to 0…1). Steel only follows iron ore
  partly, and the regression says how much.
* Everything else (cement/concrete, gravel, timber, disposal, wages): the log-linear trend of the last 36 months is
  extended.
* Range: ±1 standard deviation of the index's own 12-month changes over the last five years, scaled with √(horizon).

The expected change for a construction period is the average forecast index over its months against the latest
observed month – i.e. against the price level of today's bid.

Data is fetched at most once a day in a background thread and cached in ``data/price_cache/``. A snapshot ships in
``data/price_index_snapshot.json`` so the app works offline and opens instantly. Rebuild it with
``python -m openboq.forecast --snapshot``.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "data" / "price_index_snapshot.json"
CACHE = ROOT / "data" / "price_cache" / "price_index_cache.json"
MAX_AGE = 24 * 3600

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
WB_PAGE = "https://www.worldbank.org/en/research/commodity-markets"
WB_FORECAST_PAGE = "https://www.worldbank.org/en/research/commodity-markets/price-forecasts"
UA = {"User-Agent": "OpenBoQ price forecast (python urllib)"}

PPI = {"geo": "DE", "unit": "I21", "s_adj": "NSA", "indic_bt": "PRC_PRR_DOM"}
# driver -> (Eurostat dataset, filters, linked commodity or None, label de, label en)
DRIVER_SOURCES: dict[str, tuple[str, dict, str | None, str, str]] = {
    "steel": ("sts_inppd_m", {**PPI, "nace_r2": "C241"}, "iron_ore",
              "Erzeugerpreise Roheisen und Stahl (NACE 24.1)", "Producer prices iron and steel (NACE 24.1)"),
    "concrete": ("sts_inppd_m", {**PPI, "nace_r2": "C2363"}, None,
                 "Erzeugerpreise Transportbeton (NACE 23.63)", "Producer prices ready-mixed concrete (NACE 23.63)"),
    "bitumen": ("sts_inppd_m", {**PPI, "nace_r2": "C192"}, "brent",
                "Erzeugerpreise Mineralölerzeugnisse (NACE 19.2)", "Producer prices refined petroleum (NACE 19.2)"),
    "fuel": ("sts_inppd_m", {**PPI, "nace_r2": "C192"}, "brent",
             "Erzeugerpreise Mineralölerzeugnisse (NACE 19.2)", "Producer prices refined petroleum (NACE 19.2)"),
    "plastic": ("sts_inppd_m", {**PPI, "nace_r2": "C2221"}, "brent",
                "Erzeugerpreise Kunststoffplatten, -rohre (NACE 22.21)", "Producer prices plastic sheets, pipes (NACE 22.21)"),
    "aggregates": ("sts_inppd_m", {**PPI, "nace_r2": "B081"}, None,
                   "Erzeugerpreise Steine, Kies, Sand (NACE 08.1)", "Producer prices stone, gravel, sand (NACE 08.1)"),
    "timber": ("sts_inppd_m", {**PPI, "nace_r2": "C16"}, None,
               "Erzeugerpreise Holzwaren (NACE 16)", "Producer prices wood products (NACE 16)"),
    "disposal": ("prc_hicp_minr", {"geo": "DE", "unit": "I15", "coicop18": "CP0442"}, None,
                 "Verbraucherpreise Müllabfuhr (HVPI 04.4.2)", "Consumer prices refuse collection (HICP 04.4.2)"),
    "labour": ("lc_lci_r2_q", {"geo": "DE", "unit": "I20", "s_adj": "SCA", "nace_r2": "F", "lcstruct": "D11"}, None,
               "Arbeitskostenindex Baugewerbe, Löhne (NACE F)", "Labour cost index construction, wages (NACE F)"),
}
COMMODITIES = {"brent": ("Crude oil, Brent", "Rohöl Brent", "Brent crude oil"),
               "iron_ore": ("Iron ore", "Eisenerz", "Iron ore")}   # key: (row label in the World Bank files, de, en)

TREND_MONTHS = 36
VOL_MONTHS = 60


# ---------------------------------------------------------------- fetching

def _get(url: str, timeout: float) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _month_key(label: str) -> list[str]:
    """'2026-10' -> ['2026-10']; '2026-Q3' -> its three months; '2026M10' -> ['2026-10']."""
    m = re.fullmatch(r"(\d{4})-?M?(\d{2})", label)
    if m:
        return [f"{m.group(1)}-{m.group(2)}"]
    m = re.fullmatch(r"(\d{4})-Q([1-4])", label)
    if m:
        q = int(m.group(2))
        return [f"{m.group(1)}-{3 * q - 2 + k:02d}" for k in range(3)]
    return []


def parse_eurostat(js: dict) -> dict[str, float]:
    """JSON-stat 2.0 with one category in every dimension but time -> {YYYY-MM: value}."""
    if "value" not in js:
        raise ValueError(f"Eurostat: {js.get('error') or 'no values'}")
    tidx = js["dimension"]["time"]["category"]["index"]
    # flat index = time position × product of the sizes of the dimensions after time
    ids, sizes = js["id"], js["size"]
    stride = math.prod(sizes[ids.index("time") + 1:])
    out = {}
    for lab, pos in tidx.items():
        v = js["value"].get(str(pos * stride))
        if v is not None:
            for mk in _month_key(lab):
                out[mk] = float(v)
    return dict(sorted(out.items()))


def fetch_eurostat(dataset: str, filters: dict, since: str = "2014-01", timeout: float = 30) -> dict[str, float]:
    since_q = since if dataset != "lc_lci_r2_q" else f"{since[:4]}-Q1"
    q = "&".join(f"{k}={v}" for k, v in filters.items())
    return parse_eurostat(json.loads(_get(f"{EUROSTAT}{dataset}?{q}&sinceTimePeriod={since_q}&format=JSON&lang=EN",
                                          timeout)))


def _wb_links(page: str, timeout: float) -> list[str]:
    html = _get(page, timeout).decode("utf-8", "replace")
    return re.findall(r'https://thedocs\.worldbank\.org/[^"\s]+?\.xlsx', html)


def latest_forecast_url(timeout: float = 30) -> tuple[str, str]:
    """Most recent CMO forecast file on the World Bank page -> (url, 'October 2026')."""
    best = None
    for u in set(_wb_links(WB_FORECAST_PAGE, timeout) + _wb_links(WB_PAGE, timeout)):
        m = re.search(r"CMO-(April|October)-(\d{4})-Forecasts\.xlsx", u, re.I)
        if m:
            k = (int(m.group(2)), m.group(1).lower() == "october")
            if best is None or k > best[0]:
                best = (k, u, f"{m.group(1).capitalize()} {m.group(2)}")
    if not best:
        raise ValueError("World Bank: no forecast file found")
    return best[1], best[2]


def parse_wb_forecast(xlsx: bytes) -> dict[str, dict[str, float]]:
    """Table 1 of the CMO forecast workbook -> {commodity: {year: annual average price}} (actuals and forecasts)."""
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx), data_only=True, read_only=True).worksheets[0]
    cols: dict[int, str] = {}
    out: dict[str, dict[str, float]] = {}
    for row in ws.iter_rows(values_only=True):
        if not cols:
            years = [(i, str(c).strip().rstrip("f")) for i, c in enumerate(row)
                     if re.fullmatch(r"20\d\df?", str(c or "").strip())]
            if len(years) >= 3:
                for i, y in years:            # first block = price levels; later blocks repeat the years
                    if y not in cols.values():
                        cols[i] = y
            continue
        label = next((str(c).strip() for c in row if c is not None and str(c).strip()), "")
        for key, (wb_label, _, _) in COMMODITIES.items():
            if key not in out and label.startswith(wb_label):
                vals = {y: float(row[i]) for i, y in cols.items() if isinstance(row[i], (int, float))}
                if vals:
                    out[key] = vals
    if set(out) != set(COMMODITIES):
        raise ValueError(f"World Bank forecast: found only {sorted(out)}")
    return out


def parse_wb_monthly(xlsx: bytes, since: str = "2014-01") -> dict[str, dict[str, float]]:
    """'Monthly Prices' sheet of the Pink Sheet -> {commodity: {YYYY-MM: price}}."""
    import openpyxl
    ws = openpyxl.load_workbook(io.BytesIO(xlsx), data_only=True, read_only=True)["Monthly Prices"]
    idx: dict[str, int] = {}
    out: dict[str, dict[str, float]] = {k: {} for k in COMMODITIES}
    for row in ws.iter_rows(values_only=True):
        if not idx:
            for key, (wb_label, _, _) in COMMODITIES.items():
                for i, c in enumerate(row):
                    if str(c or "").startswith(wb_label) and key not in idx:
                        idx[key] = i
            if len(idx) < len(COMMODITIES):
                idx = {}
            continue
        mk = _month_key(str(row[0] or ""))
        if mk and mk[0] >= since:
            for key, i in idx.items():
                if isinstance(row[i], (int, float)):
                    out[key][mk[0]] = float(row[i])
    if not all(out.values()):
        raise ValueError("World Bank monthly: series missing")
    return out


def refresh(base: dict | None = None, timeout: float = 30) -> dict:
    """Fetch everything; a source that fails keeps its values from ``base`` (snapshot/cache)."""
    data = json.loads(json.dumps(base)) if base else {"history": {}, "commodities": {}, "wb_forecast": {}}
    data.setdefault("errors", {})
    data["errors"] = {}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fetched = {}
    for d, (ds, flt, _, _, _) in DRIVER_SOURCES.items():
        key = f"{ds}:{flt.get('nace_r2') or flt.get('coicop18')}"
        try:
            ser = fetched.get(key) or fetch_eurostat(ds, flt, timeout=timeout)
            fetched[key] = ser
            data["history"][d] = {"series": ser, "fetched": now}
        except Exception as e:                           # noqa: BLE001 – keep the old values, report the error
            data["errors"][d] = str(e)[:200]
    try:
        url = next(u for u in _wb_links(WB_PAGE, timeout) if u.endswith("CMO-Historical-Data-Monthly.xlsx"))
        for k, ser in parse_wb_monthly(_get(url, 120)).items():
            data["commodities"][k] = {"series": ser, "fetched": now, "url": url}
    except Exception as e:                               # noqa: BLE001
        data["errors"]["wb_monthly"] = str(e)[:200]
    try:
        url, release = latest_forecast_url(timeout)
        data["wb_forecast"] = {"release": release, "url": url, "fetched": now,
                               "annual": parse_wb_forecast(_get(url, 60))}
    except Exception as e:                               # noqa: BLE001
        data["errors"]["wb_forecast"] = str(e)[:200]
    data["built"] = now
    return data


# ---------------------------------------------------------------- loading + daily cache

_lock = threading.Lock()
_refreshing = False


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:                                    # noqa: BLE001
        return None


def _background_refresh(base: dict):
    global _refreshing
    try:
        data = refresh(base, timeout=20)
        if data.get("history"):
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(CACHE)
    except Exception:                                    # noqa: BLE001 – offline: keep what we have
        pass
    finally:
        try:   # remember the attempt so an offline machine does not retry on every rerun
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            (CACHE.parent / "last_attempt").write_text(str(time.time()))
        except OSError:
            pass
        with _lock:
            _refreshing = False


def load(auto_refresh: bool = True) -> tuple[dict, str]:
    """Data for the forecast and where it came from ('cache' or 'snapshot'). Never blocks on the network: when the
    cache is older than a day a background thread fetches fresh data for the next rerun."""
    global _refreshing
    cache, snap = _read(CACHE), _read(SNAPSHOT)
    data, origin = (cache, "cache") if cache else (snap or {}, "snapshot")
    if auto_refresh and os.environ.get("OPENBOQ_OFFLINE") != "1":
        age = time.time() - CACHE.stat().st_mtime if cache else math.inf
        try:
            attempt_age = time.time() - float((CACHE.parent / "last_attempt").read_text())
        except (OSError, ValueError):
            attempt_age = math.inf
        if age > MAX_AGE and attempt_age > 3600:
            with _lock:
                if not _refreshing:
                    _refreshing = True
                    threading.Thread(target=_background_refresh, args=(data,), daemon=True).start()
    return data, origin


# ---------------------------------------------------------------- model

def _add(mk: str, n: int) -> str:
    y, m = map(int, mk.split("-"))
    t = y * 12 + m - 1 + n
    return f"{t // 12}-{t % 12 + 1:02d}"


def _diff(a: str, b: str) -> int:
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (ya - yb) * 12 + ma - mb


def _ols(x: list[float], y: list[float]) -> tuple[float, float]:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    b = sum((a - mx) * (c - my) for a, c in zip(x, y)) / sxx if sxx else 0.0
    return my - b * mx, b


def _std(v: list[float]) -> float:
    if len(v) < 2:
        return 0.0
    m = sum(v) / len(v)
    return math.sqrt(sum((a - m) ** 2 for a in v) / (len(v) - 1))


def _yoy(ser: dict[str, float]) -> dict[str, float]:
    return {k: math.log(v / ser[_add(k, -12)]) for k, v in ser.items() if _add(k, -12) in ser and v > 0 and ser[_add(k, -12)] > 0}


def commodity_path(monthly: dict[str, float], annual: dict[str, float], until: str) -> dict[str, float]:
    """Monthly commodity price path from the latest observed month to ``until``: log-linear between the latest
    observation and the World Bank annual averages placed in July of each year; flat after the last forecast year."""
    last = max(monthly)
    anchors = [(last, monthly[last])] + sorted((f"{y}-07", v) for y, v in annual.items() if f"{y}-07" > last and v > 0)
    out = {}
    m = _add(last, 1)
    while m <= until:
        nxt = next((a for a in anchors if a[0] >= m), None)
        if nxt is None:
            out[m] = anchors[-1][1]
        else:
            prv = [a for a in anchors if a[0] < m][-1]
            w = _diff(m, prv[0]) / _diff(nxt[0], prv[0])
            out[m] = math.exp((1 - w) * math.log(prv[1]) + w * math.log(nxt[1]))
        m = _add(m, 1)
    return out


@dataclass
class DriverForecast:
    driver: str
    last: str                     # latest observed month
    history: dict                 # YYYY-MM -> index (latest = 100)
    path: dict                    # YYYY-MM -> forecast index (latest = 100)
    low: dict
    high: dict
    method: str                   # 'commodity' | 'trend'
    commodity: str | None
    beta: float | None            # elasticity to the commodity
    trend: float                  # annual drift (log) used in the forecast
    sigma: float                  # std of 12-month log changes (last 5 years)

    def change(self, start: str, months: int) -> tuple[float, float, float]:
        """Average change over the construction months vs. the latest observation: (expected, low, high)."""
        ms = [_add(start, k) for k in range(max(1, months))]
        def avg(d):
            vals = [d.get(m, self.history.get(m, 100.0)) for m in ms]
            return sum(vals) / len(vals) / 100 - 1
        return avg(self.path), avg(self.low), avg(self.high)


def forecast_driver(data: dict, driver: str, until: str) -> DriverForecast | None:
    h = (data.get("history") or {}).get(driver, {}).get("series")
    if not h or len(h) < 30:
        return None
    h = dict(sorted(h.items()))
    last = max(h)
    base = h[last]
    yoy = _yoy(h)
    recent = [v for k, v in yoy.items() if _diff(last, k) < VOL_MONTHS]
    sigma = _std(recent)
    link = DRIVER_SOURCES[driver][2]
    com = (data.get("commodities") or {}).get(link or "", {}).get("series")
    ann = ((data.get("wb_forecast") or {}).get("annual") or {}).get(link or "")
    path: dict[str, float] = {}
    beta = None
    method = "trend"
    # trend: log-linear slope over the last 36 months
    tail = [(k, v) for k, v in h.items() if _diff(last, k) < TREND_MONTHS and v > 0]
    _, slope = _ols([_diff(k, last) for k, _ in tail], [math.log(v) for _, v in tail])
    trend = slope * 12
    if link and com and ann:
        cy = _yoy(com)
        common = [k for k in yoy if k in cy]
        if len(common) >= 36:
            alpha, b = _ols([cy[k] for k in common], [yoy[k] for k in common])
            beta = min(1.0, max(0.0, b))
            # domestic drift beyond the commodity: mean of y - βx (kept small and transparent)
            trend = sum(yoy[k] - beta * cy[k] for k in common) / len(common)
            cp = commodity_path(com, ann, until)
            c0 = com[max(com)]
            # align: commodity path starts after its own latest month; months before use the latest price
            m = _add(last, 1)
            while m <= until:
                c = cp.get(m, c0 if m <= max(com) else cp.get(max(cp)) if cp else c0)
                h_ = _diff(m, last)
                path[m] = 100 * math.exp(beta * math.log(c / c0) + trend * h_ / 12)
                m = _add(m, 1)
            method = "commodity"
    if not path:
        m = _add(last, 1)
        while m <= until:
            path[m] = 100 * math.exp(trend * _diff(m, last) / 12)
            m = _add(m, 1)
    low = {m: v * math.exp(-sigma * math.sqrt(_diff(m, last) / 12)) for m, v in path.items()}
    high = {m: v * math.exp(sigma * math.sqrt(_diff(m, last) / 12)) for m, v in path.items()}
    return DriverForecast(driver=driver, last=last, history={k: 100 * v / base for k, v in h.items()}, path=path,
                          low=low, high=high, method=method, commodity=link if method == "commodity" else None,
                          beta=beta, trend=trend, sigma=sigma)


def forecast_all(data: dict, start: date, months: int) -> dict[str, DriverForecast]:
    until = _add(f"{start.year}-{start.month:02d}", max(1, months) + 1)
    out = {}
    for d in DRIVER_SOURCES:
        f = forecast_driver(data, d, until)
        if f:
            out[d] = f
    return out


def expected_changes(fc: dict[str, DriverForecast], start: date, months: int) -> dict[str, tuple[float, float, float]]:
    s = f"{start.year}-{start.month:02d}"
    return {d: f.change(max(s, _add(f.last, 1)), months) for d, f in fc.items()}


def data_status(data: dict) -> dict:
    """Latest month per source and the World Bank release, for the caption."""
    hist = data.get("history") or {}
    lasts = sorted({max(v["series"]) for v in hist.values() if v.get("series")})
    return {"eurostat_last": lasts[-1] if lasts else None, "eurostat_first": lasts[0] if lasts else None,
            "wb_release": (data.get("wb_forecast") or {}).get("release"), "built": data.get("built"),
            "errors": data.get("errors") or {}}


if __name__ == "__main__":
    import sys
    if "--snapshot" in sys.argv:
        d = refresh(_read(SNAPSHOT))
        if d["errors"]:
            print("errors:", d["errors"])
        SNAPSHOT.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
        print(f"wrote {SNAPSHOT} ({SNAPSHOT.stat().st_size // 1024} KB)")
    fc = forecast_all(load(auto_refresh=False)[0], date.today().replace(day=1), 12)
    for k, f in fc.items():
        e, lo, hi = f.change(_add(f.last, 1), 12)
        print(f"{k:11s} {f.method:9s} beta={f.beta if f.beta is None else round(f.beta, 2)!s:5s} last={f.last} "
              f"next 12 m: {100 * e:+.1f} % ({100 * lo:+.1f} .. {100 * hi:+.1f})")
