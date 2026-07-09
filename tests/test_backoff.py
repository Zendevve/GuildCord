"""
Tests for the generic BackoffPolicy used by reconnect loops.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from guildcord.common.backoff import BackoffPolicy


def test_delay_grows_geometrically_without_jitter():
    policy = BackoffPolicy(base_delay=2.0, max_delay=100.0, multiplier=2.0, jitter=0.0)
    delays = [policy.next_delay() for _ in range(5)]
    assert delays == [2.0, 4.0, 8.0, 16.0, 32.0]


def test_delay_caps_at_max_delay():
    policy = BackoffPolicy(base_delay=10.0, max_delay=25.0, multiplier=2.0, jitter=0.0)
    delays = [policy.next_delay() for _ in range(6)]
    # 10, 20, capped at 25 from here on
    assert delays[-1] == 25.0
    assert all(d <= 25.0 for d in delays)


def test_reset_restarts_the_curve():
    policy = BackoffPolicy(base_delay=3.0, max_delay=100.0, multiplier=2.0, jitter=0.0)
    policy.next_delay()
    policy.next_delay()
    assert policy.attempt == 2
    policy.reset()
    assert policy.attempt == 0
    assert policy.next_delay() == 3.0  # back to base


def test_jitter_stays_within_bounds():
    policy = BackoffPolicy(base_delay=10.0, max_delay=10.0, multiplier=1.0, jitter=0.5)
    for _ in range(200):
        delay = policy.next_delay()
        # raw_delay is always 10.0 here (multiplier=1, capped at max=base);
        # +/-50% jitter should keep it within [5.0, 15.0]
        assert 5.0 <= delay <= 15.0


def test_rejects_invalid_construction():
    with pytest.raises(ValueError):
        BackoffPolicy(base_delay=0)
    with pytest.raises(ValueError):
        BackoffPolicy(base_delay=10, max_delay=5)


if __name__ == "__main__":
    test_delay_grows_geometrically_without_jitter()
    test_delay_caps_at_max_delay()
    test_reset_restarts_the_curve()
    test_jitter_stays_within_bounds()
    test_rejects_invalid_construction()
    print("All backoff tests passed.")
