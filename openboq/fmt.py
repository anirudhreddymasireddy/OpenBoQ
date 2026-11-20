"""German number formatting: 1.234,56"""


def de(v, nd: int = 2) -> str:
    s = f"{float(v):,.{nd}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def dep(v, nd: int = 1, sign: bool = True) -> str:
    s = f"{float(v) * 100:{'+' if sign else ''}.{nd}f}"
    return s.replace(".", ",") + " %"
