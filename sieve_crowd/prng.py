"""SplitMix64: tiny, portable PRNG (same specification as in the rest of the Sieve series)."""
from __future__ import annotations

_MASK = (1 << 64) - 1


class SplitMix64:
    def __init__(self, seed: int) -> None:
        self._s = seed & _MASK

    def next_u64(self) -> int:
        self._s = (self._s + 0x9E3779B97F4A7C15) & _MASK
        z = self._s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        if n <= 0:
            raise ValueError("n must be positive")
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            x = self.next_u64()
            if x < limit:
                return x % n

    def shuffle(self, items: list) -> None:
        """Fisher-Yates, in place."""
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]
