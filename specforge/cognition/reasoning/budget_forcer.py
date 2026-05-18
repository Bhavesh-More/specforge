import asyncio
import httpx
import json
from dataclasses import dataclass
from typing import Optional
from .reasoning_config import BudgetForcerConfig


@dataclass
class BudgetForcerResult:
    reasoning_trace: str
    final_answer: str
    reasoning_token_count: int
    early_exit_attempts: int
    total_tokens: int


class BudgetForcer:
    THINK_OPEN = "<think>"
    THINK_CLOSE = "</think>"

    def __init__(self, config: BudgetForcerConfig, ollama_base_url: str = "http://localhost:11434"):
        self.config = config
        self.base_url = ollama_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=180.0)

    def build_system_prompt(self, original_system: Optional[str] = None) -> str:
        forced = (
            "You must think through problems carefully before answering.\n"
            "Begin ALL reasoning with <think> and do NOT write </think> until you have\n"
            "fully examined the problem from multiple angles, considered edge cases,\n"
            "and verified your reasoning. Only AFTER </think> provide your final concise answer.\n"
        )
        if original_system:
            forced = forced + "\n" + original_system
        return forced

    async def generate(
        self,
        model: str,
        task: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> BudgetForcerResult:
        if not task:
            raise ValueError("task cannot be empty")
        forced_system = self.build_system_prompt(system_prompt)
        prompt = f"{forced_system}\n\nTask: {task}\n\n{self.THINK_OPEN}"

        url = f"{self.base_url}/api/generate"
        options = {"num_predict": self.config.max_reasoning_tokens + 400, "temperature": temperature}
        body = {"model": model, "prompt": prompt, "stream": True, "options": options}

        in_think_block = True
        reasoning_text = ""
        answer_text = ""
        reasoning_tokens = 0
        early_exit_attempts = 0
        keep_going_index = 0

        partial_close_buf = ""

        try:
            async with self._client.stream("POST", url, json=body) as resp:
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except Exception:
                        if line.startswith("data:"):
                            try:
                                chunk = json.loads(line.split("data:", 1)[1].strip())
                            except Exception:
                                continue
                        else:
                            continue
                    token = chunk.get("response")
                    if token is None:
                        continue
                    # simple approach: look for the exact closing token
                    if in_think_block and self.THINK_CLOSE in token:
                        # split
                        parts = token.split(self.THINK_CLOSE, 1)
                        before = parts[0]
                        after = parts[1]
                        # count tokens conservatively
                        reasoning_text += before
                        reasoning_tokens += before.count(" ") + 1
                        if reasoning_tokens < self.config.min_reasoning_tokens:
                            # suppress close
                            phrase = self.config.keep_going_phrases[keep_going_index % len(self.config.keep_going_phrases)]
                            reasoning_text += phrase
                            keep_going_index += 1
                            early_exit_attempts += 1
                            # continue streaming
                            continue
                        else:
                            in_think_block = False
                            answer_text += after
                            # continue
                    else:
                        if in_think_block:
                            reasoning_text += token
                            reasoning_tokens += token.count(" ") + 1
                            if reasoning_tokens >= self.config.max_reasoning_tokens:
                                # force close
                                in_think_block = False
                                # synthetic close
                                # do not append closing token to reasoning_text
                        else:
                            answer_text += token
                    if chunk.get("done"):
                        break
        except httpx.RequestError as e:
            raise RuntimeError(f"Ollama request failed: {e}")

        total = reasoning_tokens + (answer_text.count(" ") + 1 if answer_text else 0)
        return BudgetForcerResult(
            reasoning_trace=reasoning_text,
            final_answer=answer_text,
            reasoning_token_count=reasoning_tokens,
            early_exit_attempts=early_exit_attempts,
            total_tokens=total,
        )

    async def close(self):
        await self._client.aclose()
