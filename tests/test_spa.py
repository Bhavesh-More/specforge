import pytest
import asyncio
import math
from specforge.cognition.spa.entropy_monitor import EntropyMonitor, EntropyReading
from specforge.cognition.spa.pressure_scheduler import PressureScheduler, SPAConfig, PressureZone


class TestEntropyMonitor:
    def test_entropy_of_uniform_distribution(self):
        """Uniform distribution over K tokens should give maximum entropy."""
        monitor = EntropyMonitor()
        # 4 equally likely tokens: entropy = log(4) ≈ 1.386
        logprobs = [{"token": f"t{i}", "logprob": math.log(0.25)} for i in range(4)]
        reading = monitor.feed("t0", logprobs)
        assert abs(reading.raw_entropy - math.log(4)) < 0.01

    def test_entropy_of_certain_distribution(self):
        """One token with probability ~1 should give entropy near 0."""
        monitor = EntropyMonitor()
        logprobs = [
            {"token": "the", "logprob": math.log(0.999)},
            {"token": "a", "logprob": math.log(0.001)},
        ]
        reading = monitor.feed("the", logprobs)
        assert reading.raw_entropy < 0.02

    def test_smoothed_entropy_lags_raw(self):
        """EWMA should smooth out sudden spikes."""
        monitor = EntropyMonitor(ewma_alpha=0.3)
        # Feed 10 low-entropy tokens, then one high-entropy
        low_lp = [{"token": f"t{i}", "logprob": math.log(0.001 if i > 0 else 0.99)} for i in range(10)]
        for _ in range(9):
            monitor.feed("t0", low_lp)
        high_lp = [{"token": f"t{i}", "logprob": math.log(0.1)} for i in range(10)]
        reading = monitor.feed("t1", high_lp)
        # Smoothed should be less than raw (lagging)
        assert reading.smoothed_entropy < reading.raw_entropy

    def test_reset_clears_state(self):
        monitor = EntropyMonitor()
        logprobs = [{"token": "t0", "logprob": -0.5}]
        monitor.feed("t0", logprobs)
        monitor.reset()
        assert monitor.current_smoothed() == 0.0


class TestPressureScheduler:
    def _make_reading(self, entropy: float, index: int = 100):
        from specforge.cognition.spa.entropy_monitor import EntropyReading
        return EntropyReading(token="test", raw_entropy=entropy,
                              smoothed_entropy=entropy, token_index=index)

    def test_no_injection_in_stable_zone(self):
        scheduler = PressureScheduler(SPAConfig(warn_threshold=0.30, inject_threshold=0.50))
        reading = self._make_reading(0.20)
        assert scheduler.process(reading) is None

    def test_no_injection_in_warning_zone(self):
        scheduler = PressureScheduler(SPAConfig(warn_threshold=0.30, inject_threshold=0.50))
        reading = self._make_reading(0.40)
        assert scheduler.process(reading) is None

    def test_injection_fires_above_threshold(self):
        scheduler = PressureScheduler(SPAConfig(
            warn_threshold=0.30, inject_threshold=0.50,
            min_tokens_between_injections=0
        ))
        reading = self._make_reading(0.55, index=100)
        event = scheduler.process(reading)
        assert event is not None
        assert event.injection_number == 1
        assert len(event.suffix_injected) > 0

    def test_injection_spacing_enforced(self):
        scheduler = PressureScheduler(SPAConfig(
            inject_threshold=0.50, min_tokens_between_injections=60
        ))
        r1 = self._make_reading(0.55, index=100)
        r2 = self._make_reading(0.55, index=120)  # only 20 tokens later
        scheduler.process(r1)
        result = scheduler.process(r2)
        assert result is None  # too soon

    def test_zone_classification(self):
        scheduler = PressureScheduler(SPAConfig(warn_threshold=0.30, inject_threshold=0.50))
        assert scheduler.get_zone(0.10) == PressureZone.STABLE
        assert scheduler.get_zone(0.40) == PressureZone.WARNING
        assert scheduler.get_zone(0.60) == PressureZone.ANNEAL
