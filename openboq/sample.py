"""A realistic, *clean* synthetic Rohbau BoQ (Neubau Mehrfamilienhaus) for demos and evaluation.

Prices are plausible demo values, not market data.
"""
from __future__ import annotations

from .model import BoQ, Item

SECTIONS = {
    "01": "Baustelleneinrichtung",
    "02": "Erdarbeiten",
    "03": "Beton- und Stahlbetonarbeiten",
    "04": "Mauerarbeiten",
    "05": "Abdichtungs- und Dämmarbeiten",
    "06": "Gerüstarbeiten",
}

# (oz, short, long, qty, unit, up, flags)
ROWS = [
    ("01.0010", "Baustelleneinrichtung einrichten, vorhalten, räumen",
     "Baustelleneinrichtung für sämtliche Rohbauarbeiten einrichten, für die gesamte Bauzeit vorhalten und nach Abschluss räumen. "
     "Einschließlich Unterkunfts- und Sanitärcontainer, Lagerflächen und Baustellenbeschilderung gemäß Baustelleneinrichtungsplan Anlage 3.",
     1, "psch", 28500.00, {}),
    ("01.0020", "Bauzaun mobil, Höhe 2,00 m",
     "Mobilen Bauzaun aus Stahlrohrrahmen mit Gittereinsatz, Höhe 2,00 m, auf Betonfüßen aufstellen, für die Bauzeit vorhalten und abbauen. "
     "Einschließlich zwei Toranlagen Breite 4,00 m.",
     180, "m", 9.50, {}),
    ("01.0030", "Baustrom- und Bauwasseranschluss",
     "Baustromverteiler und Bauwasseranschluss einschließlich Zähler herstellen, vorhalten und zurückbauen. "
     "Anschlusspunkte gemäß Baustelleneinrichtungsplan Anlage 3.",
     1, "psch", 3200.00, {}),
    ("01.0040", "Turmdrehkran vorhalten, Ausladung 40 m",
     "Obendreher-Turmdrehkran, Ausladung 40 m, Tragfähigkeit an der Spitze mind. 1,5 t, einschließlich Kranführer und Fundament, "
     "vorhalten je Woche.",
     26, "Wo", 1850.00, {}),

    ("02.0010", "Oberboden abtragen, d = 30 cm, seitlich lagern",
     "Oberboden Homogenbereich O1 gemäß Geotechnischem Bericht vom 14.03.2026 in einer Dicke von 30 cm abtragen und auf der Baustelle "
     "in Mieten bis 2,0 m Höhe seitlich lagern. Förderweg bis 50 m.",
     650, "m2", 3.80, {}),
    ("02.0020", "Baugrube ausheben, Tiefe bis 3,0 m",
     "Baugrube für das Untergeschoss ausheben, Homogenbereich B1 gemäß Geotechnischem Bericht vom 14.03.2026, Aushubtiefe bis 3,00 m "
     "unter Geländeoberkante, Böschungsneigung 60°. Boden seitlich zur Wiederverwendung lagern.",
     1450, "m3", 14.50, {}),
    ("02.0030", "Aushubmaterial laden, abfahren und entsorgen",
     "Nicht wiederverwendbaren Boden Homogenbereich B1 laden, abfahren und einer zugelassenen Verwertungsanlage zuführen, "
     "Einstufung Z 1.1 gemäß Deklarationsanalyse. Wiegescheine sind vorzulegen.",
     1100, "m3", 28.00, {}),
    ("02.0040", "Arbeitsraum verfüllen und verdichten",
     "Arbeitsraum mit seitlich gelagertem Boden Homogenbereich B1 lagenweise verfüllen, Schütthöhe max. 30 cm, "
     "verdichten auf Dpr ≥ 97 %.",
     320, "m3", 22.00, {}),
    ("02.0050", "Frostschutzschicht unter Bodenplatte, d = 20 cm",
     "Frostschutzschicht aus Kies-Sand-Gemisch 0/32 unter der Bodenplatte einbauen, d = 20 cm, verdichten auf Ev2 ≥ 100 MN/m².",
     520, "m2", 11.80, {}),
    ("02.0060", "Offene Wasserhaltung vorhalten und betreiben",
     "Offene Wasserhaltung mit Pumpensumpf und Tauchpumpe, Förderleistung bis 10 m³/h, einschließlich Ableitung in den Vorfluter, "
     "vorhalten und betreiben je Kalendertag.",
     20, "d", 145.00, {"provisional": True}),

    ("03.0010", "Sauberkeitsschicht C8/10, d = 5 cm",
     "Sauberkeitsschicht aus unbewehrtem Beton C8/10, X0, d = 5 cm, unter Bodenplatte und Fundamenten herstellen.",
     520, "m2", 9.20, {}),
    ("03.0020", "Streifenfundamente Stahlbeton C25/30",
     "Streifenfundamente aus Stahlbeton C25/30, XC2, Ortbeton, Größtkorn 16 mm, Konsistenz F3, einbauen und verdichten. "
     "Bewehrung und Schalung werden gesondert vergütet.",
     85, "m3", 195.00, {}),
    ("03.0030", "Schalung Streifenfundamente",
     "Schalung für Streifenfundamente, Höhe bis 1,00 m, herstellen, vorhalten und beseitigen.",
     210, "m2", 38.00, {}),
    ("03.0040", "Bodenplatte Stahlbeton C30/37, d = 25 cm",
     "Bodenplatte aus Stahlbeton C30/37, XC4, XF1, wasserundurchlässig nach WU-Richtlinie, Beanspruchungsklasse 1, d = 25 cm, "
     "Ortbeton einbauen, verdichten und abziehen.",
     130, "m3", 185.00, {}),
    ("03.0050", "Randschalung Bodenplatte, h = 25 cm",
     "Randschalung für die Bodenplatte, Höhe 25 cm, herstellen, vorhalten und beseitigen.",
     95, "m", 24.00, {}),
    ("03.0060", "Stahlbetonwände UG C30/37, d = 24 cm",
     "Wände im Untergeschoss (erdberührt) aus Stahlbeton C30/37, XC4, XF1, wasserundurchlässig nach WU-Richtlinie, d = 24 cm, "
     "Ortbeton einbauen und verdichten.",
     96, "m3", 265.00, {}),
    ("03.0070", "Schalung Wände, glatt",
     "Wandschalung, beidseitig, glatt, Sichtbetonklasse SB1, für Wanddicke 24 cm, Höhe bis 3,00 m, herstellen, vorhalten und beseitigen.",
     800, "m2", 42.00, {}),
    ("03.0080", "Stahlbetondecke C25/30, d = 20 cm",
     "Geschossdecken aus Stahlbeton C25/30, XC1, d = 20 cm, Ortbeton einbauen, verdichten, Oberfläche abziehen.",
     210, "m3", 235.00, {}),
    ("03.0090", "Schalung Decken, d = 20 cm",
     "Deckenschalung für Stahlbetondecken d = 20 cm, Unterseite glatt, Stützhöhe bis 3,00 m, herstellen, vorhalten und beseitigen.",
     1050, "m2", 36.00, {}),
    ("03.0100", "Betonstahl B500B liefern und verlegen",
     "Betonstahl B500B, Stabstahl, alle Durchmesser, liefern, schneiden, biegen und verlegen gemäß Bewehrungsplänen.",
     48, "t", 1650.00, {}),
    ("03.0110", "Betonstahlmatten B500A liefern und verlegen",
     "Betonstahlmatten B500A, Lagermatten, liefern, zuschneiden und verlegen gemäß Bewehrungsplänen.",
     22, "t", 1580.00, {}),
    ("03.0120", "Stahlbetonstützen C30/37, 30 x 30 cm",
     "Stützen aus Stahlbeton C30/37, XC1, Querschnitt 30 x 30 cm, Höhe bis 3,00 m, Ortbeton einbauen und verdichten.",
     6.5, "m3", 420.00, {}),
    ("03.0130", "Schalung Stützen 30 x 30 cm",
     "Stützenschalung für Querschnitt 30 x 30 cm, Höhe bis 3,00 m, Kanten gefast, herstellen, vorhalten und beseitigen.",
     86, "m2", 55.00, {}),
    ("03.0140", "Fertigteil-Treppenlauf",
     "Treppenlauf als Stahlbetonfertigteil C30/37, gerade, 16 Steigungen 17,5/28 cm, Breite 1,20 m, liefern und versetzen, "
     "einschließlich Trittschalldämmlager.",
     4, "St", 2900.00, {}),

    ("04.0010", "Mauerwerk Außenwand KS, d = 17,5 cm",
     "Außenwandmauerwerk aus Kalksandstein KS 20-2,0, d = 17,5 cm, in Dünnbettmörtel, Höhe bis 3,00 m, nach DIN EN 1996.",
     1250, "m2", 62.00, {}),
    ("04.0020", "Mauerwerk Innenwand tragend KS, d = 17,5 cm",
     "Tragende Innenwände aus Kalksandstein KS 20-2,0, d = 17,5 cm, in Dünnbettmörtel, Höhe bis 3,00 m.",
     980, "m2", 58.00, {}),
    ("04.0030", "Mauerwerk Innenwand nichttragend, Porenbeton, d = 11,5 cm",
     "Nichttragende Innenwände aus Porenbeton-Plansteinen PP2-0,40, d = 11,5 cm, in Dünnbettmörtel, Höhe bis 3,00 m, "
     "einschließlich Anschluss an Decke mit Gleitanker.",
     640, "m2", 44.00, {}),
    ("04.0040", "Flachstürze KS, l = 1,26 m",
     "Flachstürze aus Kalksandstein für Wanddicke 17,5 cm, Länge 1,26 m, liefern und einbauen einschließlich Übermauerung.",
     85, "St", 65.00, {}),

    ("05.0010", "Abdichtung erdberührter Kellerwände, PMBC",
     "Abdichtung erdberührter Kellerwände mit polymermodifizierter Bitumendickbeschichtung (PMBC), Wassereinwirkungsklasse W1.2-E "
     "nach DIN 18533, Trockenschichtdicke mind. 3 mm, einschließlich Hohlkehle.",
     380, "m2", 34.00, {}),
    ("05.0020", "Perimeterdämmung XPS, d = 120 mm",
     "Perimeterdämmung aus XPS-Platten, d = 120 mm, WLS 035, vollflächig verklebt, einschließlich Schutz gegen Verfüllung.",
     380, "m2", 39.00, {}),
    ("05.0030", "Querschnittsabdichtung Mauersperrbahn",
     "Querschnittsabdichtung unter Mauerwerk mit Mauersperrbahn R 500, Breite bis 24 cm, lose verlegt mit 20 cm Überlappung.",
     420, "m", 6.80, {}),
    ("05.0040", "Dränleitung DN 100 mit Kiesummantelung",
     "Dränleitung DN 100 aus PVC-U, gewellt, gelocht, mit Kiesummantelung 8/16 und Filtervlies nach DIN 4095 verlegen.",
     95, "m", 32.00, {}),

    ("06.0010", "Fassadengerüst, Lastklasse 3, Standzeit 8 Wochen",
     "Fassadengerüst als Arbeits- und Schutzgerüst, Lastklasse 3, Breitenklasse W09, einschließlich Seitenschutz, "
     "aufstellen, Grundstandzeit 8 Wochen vorhalten und abbauen.",
     1450, "m2", 9.80, {}),
    ("06.0020", "Gebrauchsüberlassung Gerüst über Grundstandzeit",
     "Gebrauchsüberlassung des Fassadengerüsts über die Grundstandzeit hinaus, je m² und Woche.",
     2900, "m2Wo", 0.45, {"provisional": True}),
]


def make_sample_boq() -> BoQ:
    boq = BoQ(project="Neubau Mehrfamilienhaus Am Lindenpark, 12 WE", name="LV Rohbauarbeiten", phase="84",
              sections=dict(SECTIONS))
    for oz, short, long, qty, unit, up, fl in ROWS:
        sec = oz.split(".")[0]
        boq.items.append(Item(
            oz=oz, short_text=short, long_text=long, qty=float(qty), unit=unit, up=float(up),
            it=round(float(qty) * float(up), 2), section=f"{sec} {SECTIONS[sec]}", section_oz=sec,
            provisional=fl.get("provisional", False), lump_sum=(unit == "psch"),
        ))
    return boq
