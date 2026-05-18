import asyncio
from dataclasses import dataclass
from typing import Optional
from .budget_forcer import BudgetForcer, BudgetForcerResult
from .socratic_node import SocraticNode, SocraticResult
from .reasoning_config import ReasoningPipelineConfig


@dataclass
class DeepReasonResult:
    final_answer: str
    reasoning_trace: Optional[str]
    socratic_result: Optional[SocraticResult]
    budget_result: Optional[BudgetForcerResult]
    pipeline_used: list[str]
    total_tokens: int


class ReasoningPipeline:
    def __init__(self, config: ReasoningPipelineConfig):
        self.config = config
        self._budget_forcer = BudgetForcer(config.budget_config, config.ollama_base_url) if config.use_budget_forcing else None
        self._socratic = SocraticNode(config.socratic_config, config.ollama_base_url) if config.use_socratic else None

    async def execute(self, task: str, system_prompt: Optional[str] = None) -> DeepReasonResult:
        pipeline_used = []
        socratic_result = None
        budget_result = None
        intermediate_task = task

        if self._socratic is not None:
            socratic_result = await self._socratic.execute(task, self.config.model)
            pipeline_used.append("socratic")
            # build a concise QA summary
            qa_lines = []
            for i, sq in enumerate(socratic_result.sub_questions, start=1):
                qa_lines.append(f"Q{i}: {sq.question}\nA{i}: {sq.answer}\n")
            socratic_qa_summary = "\n".join(qa_lines)
            intermediate_task = f"Task: {task}\n\nReasoning so far:\n{socratic_qa_summary}\n\nProvide the final answer:"

        if self._budget_forcer is not None:
            budget_result = await self._budget_forcer.generate(model=self.config.model, task=intermediate_task, system_prompt=system_prompt)
            pipeline_used.append("budget_forcing")
            final_answer = budget_result.final_answer
            reasoning_trace = budget_result.reasoning_trace
        else:
            budget_result = None
            final_answer = socratic_result.synthesis if socratic_result else intermediate_task
            reasoning_trace = None

        total_tokens = 0
        return DeepReasonResult(
            final_answer=final_answer,
            reasoning_trace=reasoning_trace,
            socratic_result=socratic_result,
            budget_result=budget_result,
            pipeline_used=pipeline_used,
            total_tokens=total_tokens,
        )

    async def close(self):
        if self._budget_forcer:
            await self._budget_forcer.close()
        if self._socratic:
            await self._socratic.close()
