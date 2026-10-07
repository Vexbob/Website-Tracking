"""Der Rahmen: echte HTTP-Anfragen durch FastAPI, Starlette und
python-multipart (v2.40.0).

Die uebrigen Tests rufen Endpunkte meist direkt auf (``fn.__wrapped__``) und
gehen damit an genau den Teilen vorbei, die ein Framework-Update aendert:
Formular lesen, Datei annehmen, Rate-Limit. Bis v2.39.0 lagen dort die
bekannten Luecken (python-multipart 0.0.6, Starlette 0.35) -- und ein Update,
das sie schliesst, darf den Login nicht still zerbrechen. Diese Tests laufen
ohne Datenbank: der Lifespan startet ohne ``with`` nicht, und ``get_db`` wird
ersetzt.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest                                                  # noqa: E402
from fastapi.testclient import TestClient                       # noqa: E402

import main                                                    # noqa: E402
from auth import get_current_user, pwd_context                 # noqa: E402
from database import get_db                                    # noqa: E402
from deps import besucher_adresse                              # noqa: E402

HASH = pwd_context.hash("richtig-und-lang")


class _Verbindung:
    async def fetchrow(self, sql, *a):
        if "FROM users" in sql and a and a[0] == "etienne":
            return {"username": "etienne", "password_hash": HASH}
        return None


async def _db():
    yield _Verbindung()


@pytest.fixture
def client():
    main.limiter.reset()
    main.app.dependency_overrides[get_db] = _db
    main.app.dependency_overrides[get_current_user] = lambda: {"id": 1, "username": "etienne", "is_admin": False}
    try:
        yield TestClient(main.app, raise_server_exceptions=False)
    finally:
        main.app.dependency_overrides.clear()
        main.limiter.reset()


def test_der_login_liest_das_formular(client):
    gut = client.post("/token", data={"username": "etienne", "password": "richtig-und-lang"})
    assert gut.status_code == 200 and gut.json()["token_type"] == "bearer"
    falsch = client.post("/token", data={"username": "etienne", "password": "falsch"})
    assert falsch.status_code == 401


def test_ein_kaputtes_formular_ist_kein_serverfehler(client):
    """Ein Content-Type, an dem der alte Parser haengen blieb (CVE-2024-24762),
    endet heute mit einer Antwort -- und nicht mit einem 500er."""
    res = client.post("/token", content=b"username=a&password=b",
                      headers={"Content-Type": 'application/x-www-form-urlencoded; !="' + "\\" * 2000})
    assert res.status_code in (400, 401, 422)


def test_eine_datei_kommt_durch_den_ganzen_stapel(client):
    res = client.post("/api/depot/import", files={"file": ("auszug.pdf", b"kein pdf", "application/pdf")})
    assert res.status_code == 400 and "PDF" in res.json()["detail"]


def test_die_login_sperre_zaehlt_je_besucher(client):
    for _ in range(5):
        assert client.post("/token", data={"username": "x", "password": "y"},
                           headers={"X-Forwarded-For": "203.0.113.7"}).status_code == 401
    gesperrt = client.post("/token", data={"username": "x", "password": "y"},
                           headers={"X-Forwarded-For": "203.0.113.7"})
    assert gesperrt.status_code == 429
    # Ein anderer Besucher ist davon nicht betroffen.
    anderer = client.post("/token", data={"username": "etienne", "password": "richtig-und-lang"},
                          headers={"X-Forwarded-For": "198.51.100.4"})
    assert anderer.status_code == 200


class _Anfrage:
    def __init__(self, kopf=None, host="10.0.0.2"):
        self.headers = {"x-forwarded-for": kopf} if kopf else {}
        self.client = type("C", (), {"host": host})()
        self.scope = {"client": (host, 1234)}


def test_die_adresse_des_besuchers_setzt_der_proxy():
    # Den letzten Eintrag haengt der Proxy an; davor darf der Besucher alles behaupten.
    assert besucher_adresse(_Anfrage("1.1.1.1, 203.0.113.7")) == "203.0.113.7"
    assert besucher_adresse(_Anfrage("203.0.113.7")) == "203.0.113.7"
    assert besucher_adresse(_Anfrage()) == "10.0.0.2"
