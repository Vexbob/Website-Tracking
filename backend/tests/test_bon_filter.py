"""Tests fuer den Bonfilter und die Summenzeile darueber (v2.11.8).

Die Bonliste zeigt einen Ausschnitt -- hoechstens 200 Zeilen. Die Zeile
darueber ("348 Bons gefiltert, 1.204,30 EUR") meint dagegen das Ganze. Beide
Angaben stehen untereinander auf derselben Seite, also muessen sie dieselbe
Menge meinen; sonst widerspricht die Seite sich selbst.

Bis v2.11.8 tat sie genau das: die Summe wurde im Browser ueber die geladenen
Zeilen gerechnet. Unterhalb von 200 Bons stimmte sie, darueber war sie zu
klein -- und anzusehen war ihr das nicht. Seitdem bauen Liste und Summe ihren
Filter aus derselben Funktion. Diese Tests halten das fest.
"""
import inspect
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")

from routers import expenses_router as er


VOLL = dict(user_id=7, date_from="2026-01-01", date_to="2026-03-31",
            store_id=3, category_id=9, expense_type="lebensmittel",
            q="milch")


# ============================================ Liste und Summe meinen dasselbe

def test_liste_und_summe_kennen_dieselben_filter():
    """Ein neuer Filter an der Liste muss auch die Summe erreichen.

    Waere er nur an der Liste, zeigte die Seite wieder eine Zahl, die eine
    andere Menge meint als die Zeilen darunter -- der Fehler, wegen dem es
    diese Datei gibt.
    """
    egal = {"db", "user", "limit"}
    liste = set(inspect.signature(er.list_expenses).parameters) - egal
    summe = set(inspect.signature(er.stats_filtered).parameters) - egal
    assert liste == summe, f"nur an einer Stelle: {liste ^ summe}"


def test_beide_bauen_ihren_filter_aus_derselben_funktion():
    for fn in (er.list_expenses, er.stats_filtered):
        quelle = inspect.getsource(fn)
        assert "_bon_filter(" in quelle, f"{fn.__name__} baut seinen Filter selbst"


def test_die_summe_kennt_keine_obergrenze():
    """`limit` gehoert zur Liste, nicht zur Auskunft ueber die Menge.

    Geprueft wird die SQL-Form `LIMIT $n` -- das Wort allein steht auch in
    Kommentaren, die gerade erklaeren, warum es hier nichts zu suchen hat.
    """
    assert "limit" not in inspect.signature(er.stats_filtered).parameters
    quelle = re.sub(r'""".*?"""', "", inspect.getsource(er.stats_filtered),
                    flags=re.S)
    assert not re.search(r"\bLIMIT\s+\$", quelle, re.I)


# ====================================================== Das SQL bleibt heil

def test_jede_bedingung_hat_ihren_platzhalter():
    """Platzhalter und Parameterliste muessen zusammenpassen.

    asyncpg zaehlt $1, $2, ... gegen die uebergebenen Werte. Ein Filter, der
    seinen Wert nicht anhaengt, sprengt die Abfrage erst zur Laufzeit.
    """
    conds, params = er._bon_filter(**VOLL)
    stellen = {int(n) for n in re.findall(r"\$(\d+)", " ".join(conds))}
    assert stellen == set(range(1, len(params) + 1)), (stellen, len(params))


def test_ohne_filter_bleibt_nur_der_eigene_bestand():
    conds, params = er._bon_filter(user_id=7, date_from=None, date_to=None,
                                   store_id=None, category_id=None,
                                   expense_type=None, q=None)
    assert conds == ["e.user_id=$1"]
    assert params == [7]


def test_der_nutzer_steht_immer_an_erster_stelle():
    """Ohne diese Bedingung saehe man fremde Bons -- in beiden Abfragen."""
    conds, params = er._bon_filter(**VOLL)
    assert conds[0] == "e.user_id=$1"
    assert params[0] == 7


def test_eine_einzelne_ziffer_gilt_nicht_als_suche():
    """Unter zwei Zeichen wird nicht gesucht -- Liste und Summe gleichermassen,
    sonst zaehlte die eine mehr als die andere zeigt."""
    conds, _ = er._bon_filter(user_id=7, date_from=None, date_to=None,
                              store_id=None, category_id=None,
                              expense_type=None, q="m")
    assert len(conds) == 1


def test_die_suche_trifft_laden_notiz_und_artikel():
    conds, params = er._bon_filter(user_id=7, date_from=None, date_to=None,
                                   store_id=None, category_id=None,
                                   expense_type=None, q="  Milch ")
    such = conds[1]
    assert "s.name" in such and "e.note" in such and "ei.description" in such
    assert params[1] == "%milch%"   # getrimmt und kleingeschrieben


def test_die_summenabfrage_verbindet_die_laeden():
    """Die Suche schaut in `s.name` -- ohne den JOIN liefe die Zaehlabfrage
    auf einen Fehler, den man erst beim Suchen saehe."""
    quelle = er.stats_filtered.__doc__ and inspect.getsource(er.stats_filtered)
    assert "LEFT JOIN stores s" in quelle
