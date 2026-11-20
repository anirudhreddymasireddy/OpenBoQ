"""German number formatting: 1.234,56"""


def de(v, nd: int = 2) -> str:
    s = f"{float(v):,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def dep(v, nd: int = 1, sign: bool = True) -> str:
    s = f"{float(v) * 100:{'+' if sign else ''}.{nd}f}"
    return s.replace(".", ",") + " %"


def en(v, nd: int = 2) -> str:
    return f"{float(v):,.{nd}f}"


def num(v, nd: int = 2, lang: str = "de") -> str:
    return en(v, nd) if lang == "en" else de(v, nd)


def money(v, lang: str = "de") -> str:
    return f"€{en(v, 0)}" if lang == "en" else f"{de(v, 0)} €"
