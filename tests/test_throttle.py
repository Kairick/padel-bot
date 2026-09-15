from padel_bot.bot.throttle import RateLimiter


def test_allows_up_to_limit_then_blocks():
    limiter = RateLimiter(max_events=3, per_seconds=60)
    assert [limiter.allow(1, now=t) for t in (0, 1, 2, 3)] == [True, True, True, False]


def test_window_slides():
    limiter = RateLimiter(max_events=2, per_seconds=60)
    assert limiter.allow(1, now=0)
    assert limiter.allow(1, now=30)
    assert not limiter.allow(1, now=59)
    assert limiter.allow(1, now=60)  # the first event left the window
    assert not limiter.allow(1, now=61)


def test_users_are_independent():
    limiter = RateLimiter(max_events=1, per_seconds=60)
    assert limiter.allow(1, now=0)
    assert not limiter.allow(1, now=1)
    assert limiter.allow(2, now=1)


def test_blocked_attempts_do_not_extend_the_window():
    limiter = RateLimiter(max_events=1, per_seconds=10)
    assert limiter.allow(1, now=0)
    for t in range(1, 10):
        assert not limiter.allow(1, now=t)
    assert limiter.allow(1, now=10)
