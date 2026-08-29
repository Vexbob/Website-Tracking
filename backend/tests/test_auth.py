"""Tests fuer Auth-Utilities (v1.33.0).

Bewusst ohne echte DB / FastAPI-Client: wir testen nur die reinen
Helper-Funktionen (Password-CT-Check, Cache-Invalidation, Token-Roundtrip).
"""
import os
import sys
import time

# Test-ENV bevor auth.py importiert wird (validiert SECRET_KEY-Pflicht)
os.environ.setdefault("SECRET_KEY", "test-only-not-used")
os.environ.setdefault("DATABASE_URL", "postgres://test:test@localhost/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import (  # noqa: E402
    verify_password_ct, pwd_context, create_token, TOKEN_EXPIRE_HOURS,
    _invalidate_user_cache, _user_cache,
)


def test_verify_password_ct_correct():
    h = pwd_context.hash("hunter22-longer")
    assert verify_password_ct("hunter22-longer", h) is True


def test_verify_password_ct_wrong():
    h = pwd_context.hash("hunter22-longer")
    assert verify_password_ct("nope", h) is False


def test_verify_password_ct_no_hash_is_false():
    # User existiert nicht / noch nicht aktiviert -> auch bei "gutem" Passwort False.
    assert verify_password_ct("egal", None) is False
    assert verify_password_ct("egal", "") is False


def test_verify_password_ct_is_constant_time_ish():
    """Grober Sanity-Check: der Verify gegen None (User existiert nicht) muss
    ebenfalls einen Bcrypt-Cycle durchlaufen, d.h. mindestens ~30% der Zeit
    eines echten Verify brauchen. Vor v1.33.0 war der None-Fall ~1000x schneller
    weil bcrypt gar nicht aufgerufen wurde (Timing-Attack).
    """
    h = pwd_context.hash("some-long-password-42")

    t0 = time.perf_counter()
    for _ in range(3):
        verify_password_ct("wrong-pw", h)
    real_dt = time.perf_counter() - t0

    t0 = time.perf_counter()
    for _ in range(3):
        verify_password_ct("wrong-pw", None)
    fake_dt = time.perf_counter() - t0

    # Bei korrektem CT-Check: fake_dt sollte in derselben Groessenordnung liegen.
    # Wir sind bewusst grosszuegig (>= 30% der echten Zeit), um flaky CI zu vermeiden.
    assert fake_dt >= real_dt * 0.3, (
        f"Timing-Attack-Regression: fake={fake_dt:.3f}s echt={real_dt:.3f}s"
    )


def test_create_token_roundtrip():
    from jose import jwt
    from auth import SECRET_KEY, ALGORITHM
    tok = create_token("alice")
    payload = jwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["sub"] == "alice"
    assert "exp" in payload


def test_token_expire_hours_default_env():
    # Default = 24, es sei denn ENV setzt was anderes.
    assert TOKEN_EXPIRE_HOURS >= 1


def test_invalidate_user_cache_single_and_all():
    _user_cache["alice"] = (time.monotonic(), {"id": 1})
    _user_cache["bob"] = (time.monotonic(), {"id": 2})
    _invalidate_user_cache("alice")
    assert "alice" not in _user_cache
    assert "bob" in _user_cache
    _invalidate_user_cache()
    assert _user_cache == {}
