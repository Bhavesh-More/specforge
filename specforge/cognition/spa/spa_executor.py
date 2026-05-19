import httpx
import json
import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional
from .entropy_monitor import EntropyMonitor, EntropyReading
from .pressure_scheduler import PressureScheduler, PressureEvent, SPAConfig


@dataclass
class SPAGenerationResult:
    text: str
    pressure_events: list[PressureEvent]
    entropy_readings: list[EntropyReading]
    total_tokens: int
    injection_count: int
    final_smoothed_entropy: float


class SPAExecutor:
    OLLAMA_GENERATE_URL = "{base}/api/generate"

    def __init__(self, ollama_base_url: str = "http://localhost:11434"):
        self.base_url = ollama_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    async def generate(
        self,
        model: str,
        prompt: str,
        spa_config: Optional[SPAConfig] = None,
        max_tokens: int = 500,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
    ) -> SPAGenerationResult:
        if spa_config is None:
            spa_config = SPAConfig()
        monitor = EntropyMonitor()
        scheduler = PressureScheduler(spa_config)

        current_text = ""
        pressure_events: list[PressureEvent] = []
        entropy_readings: list[EntropyReading] = []

        original_prompt = prompt

        # we will loop and re-prompt if injections occur
        while True:
            async for chunk in self._stream_ollama(model, original_prompt + current_text, max_tokens, temperature, system_prompt):
                token = chunk.get("response")
                if token is None:
                    continue
                logprobs = chunk.get("logprobs", []) or []
                reading = monitor.feed(token, logprobs)
                entropy_readings.append(reading)
                event = scheduler.process(reading)
                current_text += token
                if event is not None:
                    # inject suffix and re-prompt
                    current_text += event.suffix_injected
                    pressure_events.append(event)
                    monitor.reset()
                    # continue outer while with updated current_text
                    break
                if chunk.get("done"):
                    # final chunk
                    return SPAGenerationResult(
                        text=current_text,
                        pressure_events=pressure_events,
                        entropy_readings=entropy_readings,
                        total_tokens=len(entropy_readings),
                        injection_count=scheduler.injection_count(),
                        final_smoothed_entropy=monitor.current_smoothed(),
                    )
            else:
                # stream ended without 'done'—break
                return SPAGenerationResult(
                    text=current_text,
                    pressure_events=pressure_events,
                    entropy_readings=entropy_readings,
                    total_tokens=len(entropy_readings),
                    injection_count=scheduler.injection_count(),
                    final_smoothed_entropy=monitor.current_smoothed(),
                )

    async def _stream_ollama(
        self,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        system_prompt: Optional[str],
    ) -> AsyncIterator[dict]:
        url = self.OLLAMA_GENERATE_URL.format(base=self.base_url)
        body = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
                "logprobs": True,
            },
        }
        if system_prompt:
            body["system"] = system_prompt

        try:
            async with self._client.stream("POST", url, json=body) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        # try to be lenient: some streams prefix with data: 
                        if line.startswith("data:"):
                            try:
                                chunk = json.loads(line.split("data:", 1)[1].strip())
                            except Exception:
                                continue
                        else:
                            continue
                    yield chunk
        except httpx.RequestError as e:
            raise RuntimeError(f"Ollama stream request failed: {e}")

    async def close(self):
        await self._client.aclose()
