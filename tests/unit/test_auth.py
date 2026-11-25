"""Portfolio sign-in helpers: credential checks, signed session tokens, throttling and redirects."""

from app import auth


def make(user="suresh", password="pw", secret=None, max_age=3600):
    return auth.Authenticator(user, password, secret, max_age)


def test_checks_credentials():
    a = make()
    assert a.check_credentials("suresh", "pw")
    assert a.check_credentials(" Suresh ", "pw")  # username isn't case sensitive
    assert not a.check_credentials("suresh", "PW")  # password is
    assert not a.check_credentials("someone", "pw")
    assert not a.check_credentials("", "")


def test_without_password_nobody_can_sign_in():
    a = make(password=None)
    assert not a.configured
    assert not a.check_credentials("suresh", "")
    assert not a.valid_token(make().make_token())


def test_token_round_trip_and_expiry():
    a = make(max_age=60)
    token = a.make_token(now=1000)
    assert a.valid_token(token, now=1030)
    assert not a.valid_token(token, now=1061)


def test_tampered_or_foreign_tokens_are_rejected():
    a = make()
    token = a.make_token()
    user, expires, sig = token.split("|")
    assert not a.valid_token(f"{user}|{int(expires) + 99999}|{sig}")
    assert not a.valid_token(f"admin|{expires}|{sig}")
    assert not a.valid_token("garbage")
    assert not a.valid_token("")
    assert not a.valid_token(None)
    # A token signed with other credentials (e.g. before a password change) no longer works.
    assert not a.valid_token(make(password="old").make_token())
    assert not a.valid_token(make(secret="other").make_token())


def test_explicit_secret_survives_password_change():
    token = make(password="old", secret="s").make_token()
    assert make(password="new", secret="s").valid_token(token)


def test_throttle_blocks_after_limit_and_expires():
    t = auth.LoginThrottle(limit=3, window_seconds=60)
    for i in range(3):
        assert not t.blocked("ip", now=100 + i)
        t.fail("ip", now=100 + i)
    assert t.blocked("ip", now=105)
    assert not t.blocked("other", now=105)
    assert not t.blocked("ip", now=200)  # the window has passed
    t.fail("ip2", now=1)
    t.reset("ip2")
    assert not t.blocked("ip2", now=2)


def test_safe_next_only_allows_local_paths():
    assert auth.safe_next("/portfolio") == "/portfolio"
    assert auth.safe_next("/portfolio?x=1") == "/portfolio?x=1"
    for bad in (None, "", "https://evil.example", "//evil.example", "/\\evil.example", "portfolio"):
        assert auth.safe_next(bad) == "/portfolio"


def test_protected_paths():
    for path in ("/portfolio", "/portfolio/", "/api/performance", "/api/research/AAPL", "/api/ticker/AAPL/news"):
        assert auth.is_protected(path), path
    for path in ("/", "/news/health", "/ticker/AAPL", "/api/ticker/AAPL", "/api/quotes", "/api/news", "/login", "/healthz"):
        assert not auth.is_protected(path), path
