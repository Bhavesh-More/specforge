import math
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EntropyReading:
    token: str               # the token text
    raw_entropy: float       # H = -sum(p * log(p)) for this token
    smoothed_entropy: float  # EWMA smoothed value
    token_index: int         # position in the generation


class EntropyMonitor:
    """
    Maintains a rolling EWMA of token-level entropy from Ollama logprobs.

    Ollama returns logprobs as a list of dicts: [{"token": str, "logprob": float}, ...]
    for the top-K tokens at each generation step. We compute entropy over this distribution.
    """

    def __init__(self, window_size: int = 20, ewma_alpha: float = 0.3):
        """
        Args:
            window_size: number of recent tokens to keep in the rolling window
            ewma_alpha: smoothing factor for exponential weighted moving average.
                        Higher = more reactive, lower = more stable.
        """
        self.window_size = window_size
        self.ewma_alpha = ewma_alpha
        self._window = deque(maxlen=window_size)
        self._smoothed = 0.0
        self._token_count = 0

    def feed(self, token: str, logprobs: list[dict]) -> EntropyReading:
        """
        Accept one token's logprob distribution, compute entropy, update EWMA.
        """
        # Convert logprobs to probabilities
        probs = []
        for e in (logprobs or []):
            lp = e.get("logprob")
            try:
                p = math.exp(lp) if lp is not None else 0.0
            except OverflowError:
                p = 0.0
            probs.append(p)

        # Normalize
        total = sum(probs)
        if total <= 0:
            H = 0.0
        else:
            probs = [p / total for p in probs]
            H = 0.0
            for p in probs:
                if p <= 0.0:
                    continue
                H -= p * math.log(p + 1e-12)

        # Update EWMA and window
        self._token_count += 1
        self._smoothed = self.ewma_alpha * H + (1.0 - self.ewma_alpha) * self._smoothed
        self._window.append(H)

        return EntropyReading(token=token, raw_entropy=H, smoothed_entropy=self._smoothed, token_index=self._token_count)

    def current_smoothed(self) -> float:
        """Return the current EWMA-smoothed entropy value."""
        return float(self._smoothed)

    def reset(self):
        """Reset all state. Called between node executions."""
        self._window.clear()
        self._smoothed = 0.0
        self._token_count = 0
