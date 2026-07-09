"""
Generic exponential-backoff-with-jitter helper for any retrying network
client. This is the standard "full jitter" backoff pattern (delay grows
geometrically up to a cap, randomized to avoid synchronized retry storms
across multiple clients) — not specific to WoW or Discord in any way.
"""

from __future__ import annotations

import random


class BackoffPolicy:
    """
    Usage:
        policy = BackoffPolicy()
        while True:
            try:
                do_the_thing()
                policy.reset()          # success — back to base delay next time
            except Exception:
                delay = policy.next_delay()
                await asyncio.sleep(delay)
    """

    def __init__(
        self,
        base_delay: float = 5.0,
        max_delay: float = 300.0,
        multiplier: float = 2.0,
        jitter: float = 0.2,
    ):
        if base_delay <= 0:
            raise ValueError("base_delay must be positive")
        if max_delay < base_delay:
            raise ValueError("max_delay must be >= base_delay")
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.multiplier = multiplier
        self.jitter = jitter
        self._attempt = 0

    def reset(self) -> None:
        """Call after a successful operation to restart the delay curve."""
        self._attempt = 0

    def next_delay(self) -> float:
        """
        Returns the delay (in seconds) to wait before the next attempt,
        and advances the internal attempt counter. Delay grows as
        base_delay * multiplier^attempt, capped at max_delay, with
        +/- jitter% random variation applied.
        """
        raw_delay = min(
            self.base_delay * (self.multiplier**self._attempt), self.max_delay
        )
        self._attempt += 1

        if self.jitter <= 0:
            return raw_delay

        jitter_amount = raw_delay * self.jitter
        return max(0.0, raw_delay + random.uniform(-jitter_amount, jitter_amount))

    @property
    def attempt(self) -> int:
        return self._attempt
