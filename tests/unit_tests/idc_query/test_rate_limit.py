import pytest

from idc_query_core.rate_limit import SlidingWindowRateLimiter


@pytest.mark.asyncio
async def test_sliding_window_reports_retry_and_recovers_after_expiry():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(
        limit=2,
        window_seconds=10,
        clock=lambda: now[0],
    )

    assert (await limiter.acquire('user-1')).allowed is True
    assert (await limiter.acquire('user-1')).allowed is True

    denied = await limiter.acquire('user-1')
    assert denied.allowed is False
    assert denied.retry_after_seconds == 10

    now[0] += 6
    assert (await limiter.acquire('user-1')).retry_after_seconds == 4

    now[0] += 4
    assert (await limiter.acquire('user-1')).allowed is True


@pytest.mark.asyncio
async def test_rate_limit_is_isolated_by_key():
    limiter = SlidingWindowRateLimiter(limit=1, window_seconds=60)

    assert (await limiter.acquire('group-1:user-1')).allowed is True
    assert (await limiter.acquire('group-1:user-1')).allowed is False
    assert (await limiter.acquire('group-1:user-2')).allowed is True
