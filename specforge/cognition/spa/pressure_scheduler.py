from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .entropy_monitor import EntropyReading


class PressureZone(str, Enum):
    STABLE = "stable"
    WARNING = "warning"
    ANNEAL = "anneal"


@dataclass
class PressureEvent:
    token_index: int
    zone: PressureZone
    suffix_injected: str
    entropy_at_trigger: float
    injection_number: int


@dataclass
class SPAConfig:
    warn_threshold: float = 0.30
    inject_threshold: float = 0.50
    min_tokens_between_injections: int = 60
    pressure_schedule: str = "standard"


PRESSURE_SCHEDULES: dict[str, list[str]] = {
    "standard": [
        "\n\nBe precise. State only what is certain.",
        "\n\nStick strictly to the original task. Avoid elaboration.",
        "\n\nOutput only structured, verifiable facts.",
        "\n\nConstrain your response. Avoid all speculation.",
        "\n\nReturn to the core question. Be concise and exact.",
    ],
    "strict": [
        "\n\nSTOP. Re-read the original task. Answer ONLY what was asked.",
        "\n\nOutput must be factual and directly task-relevant. Nothing else.",
        "\n\nHalt generation. Summarise what you have established so far, then stop.",
    ],
    "gentle": [
        "\n\nRemember to stay focused on the main question.",
        "\n\nGently refocus: what exactly was asked?",
        "\n\nStay on topic and be concise.",
    ],
}


class PressureScheduler:
    """
    Stateful policy engine. Call .process(reading) on every token.
    Returns a PressureEvent if injection should fire, None otherwise.
    """

    def __init__(self, config: SPAConfig):
        self.config = config
        self._injection_count = 0
        self._last_injection_token = -999
        sched = PRESSURE_SCHEDULES.get(config.pressure_schedule)
        if sched is None:
            sched = PRESSURE_SCHEDULES["standard"]
        self._suffixes = sched

    def process(self, reading: EntropyReading) -> Optional[PressureEvent]:
        entropy = reading.smoothed_entropy
        # Rule 1: stable
        if entropy < self.config.warn_threshold:
            return None
        # Rule 2: warning (no action)
        if entropy < self.config.inject_threshold:
            return None
        # Rule 3: spacing
        if (reading.token_index - self._last_injection_token) < self.config.min_tokens_between_injections:
            return None
        # Otherwise inject
        idx = min(self._injection_count, max(0, len(self._suffixes) - 1))
        suffix = self._suffixes[idx]
        self._injection_count += 1
        self._last_injection_token = reading.token_index
        event = PressureEvent(
            token_index=reading.token_index,
            zone=PressureZone.ANNEAL,
            suffix_injected=suffix,
            entropy_at_trigger=entropy,
            injection_number=self._injection_count,
        )
        return event

    def get_zone(self, entropy: float) -> PressureZone:
        if entropy < self.config.warn_threshold:
            return PressureZone.STABLE
        if entropy < self.config.inject_threshold:
            return PressureZone.WARNING
        return PressureZone.ANNEAL

    def injection_count(self) -> int:
        return int(self._injection_count)

    def reset(self):
        self._injection_count = 0
        self._last_injection_token = -999
