import asyncio
import httpx
import json
import re
from dataclasses import dataclass, field
from .reasoning_config import SocraticConfig


@dataclass
class SubQuestion:
    index: int
    question: str
    answer: str = ""


@dataclass
class SocraticResult:
    sub_questions: list[SubQuestion]
    synthesis: str
    total_tokens_used: int
    phases_completed: int


class SocraticNode:
    def __init__(self, config: SocraticConfig, ollama_base_url: str = "http://localhost:11434"):
        self.config = config
        self.base_url = ollama_base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=120.0)

    async def execute(self, task: str, model: str) -> SocraticResult:
        questions = await self._generate_questions(task, model)
        sub_questions = [SubQuestion(index=i + 1, question=q) for i, q in enumerate(questions)]
        # Phase 2: answer concurrently
        async def _answer(sq: SubQuestion):
            ans = await self._answer_question(task, sq.question, model)
            sq.answer = ans
            return sq
        answered = await asyncio.gather(*[_answer(sq) for sq in sub_questions])
        synthesis = await self._synthesise(task, answered, model)
        total_tokens = 0
        return SocraticResult(sub_questions=answered, synthesis=synthesis, total_tokens_used=total_tokens, phases_completed=3)

    async def _generate_questions(self, task: str, model: str) -> list[str]:
        prompt = (
            f"Given this task: {task}\n\n"
            f"List exactly {self.config.num_questions} specific sub-questions that, if each is answered\n"
            "correctly, would together fully resolve the task.\n"
            "Be precise. Do not answer the questions yet.\n"
            "Format: one question per line, starting with a number and period.\n"
            "Sub-questions:"
        )
        text = await self._call_ollama(prompt, model, max_tokens=self.config.question_max_tokens, temperature=self.config.question_temperature)
        lines = text.splitlines()
        qs = []
        for line in lines:
            m = re.match(r"^\s*\d+[\.|\)]\s+(.+)$", line)
            if m:
                qs.append(m.group(1).strip())
        if len(qs) < self.config.num_questions:
            # fallback: split by lines and take first n non-empty
            fallback = [l.strip() for l in lines if l.strip()]
            qs = fallback[: self.config.num_questions]
            if len(qs) < self.config.num_questions:
                # pad generic questions
                while len(qs) < self.config.num_questions:
                    qs.append("Please clarify a missing sub-question.")
        return qs

    async def _answer_question(self, task: str, question: str, model: str) -> str:
        prompt = (
            f"Task context: {task}\n\nSub-question: {question}\n\n"
            "Answer this sub-question directly and concisely. State only what is certain:"
        )
        text = await self._call_ollama(prompt, model, max_tokens=self.config.answer_max_tokens, temperature=self.config.answer_temperature)
        return text.strip()

    async def _synthesise(self, task: str, sub_questions: list[SubQuestion], model: str) -> str:
        qa_lines = []
        for i, sq in enumerate(sub_questions, start=1):
            qa_lines.append(f"Q{i}: {sq.question}\nA{i}: {sq.answer}\n")
        qa_context = "\n".join(qa_lines)
        prompt = (
            f"Original task: {task}\n\nReasoning conducted:\n{qa_context}\n"
            "Based on this structured reasoning, provide the final definitive answer.\n"
            "Be concise and directly address the original task:"
        )
        text = await self._call_ollama(prompt, model, max_tokens=self.config.synthesis_max_tokens, temperature=self.config.synthesis_temperature)
        return text.strip()

    async def _call_ollama(self, prompt: str, model: str, max_tokens: int, temperature: float) -> str:
        url = f"{self.base_url}/api/generate"
        body = {"model": model, "prompt": prompt, "stream": False, "options": {"num_predict": max_tokens, "temperature": temperature}}
        try:
            resp = await self._client.post(url, json=body)
            data = resp.json()
            return data.get("response", "")
        except httpx.RequestError as e:
            raise RuntimeError(f"Ollama request failed: {e}")

    async def close(self):
        await self._client.aclose()
