from app.cache import TTLCache


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_returns_value_before_expiry_and_none_after():
    clock = FakeClock()
    cache = TTLCache(10, clock=clock)
    cache.set("k", "v")
    clock.now = 9.9
    assert cache.get("k") == "v"
    clock.now = 10.0
    assert cache.get("k") is None


def test_missing_key_and_clear():
    cache = TTLCache(10)
    assert cache.get("nope") is None
    cache.set("k", 1)
    cache.clear()
    assert cache.get("k") is None
