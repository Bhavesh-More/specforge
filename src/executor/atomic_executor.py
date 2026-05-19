"""Ollama inference layer — execute atomic LLM nodes."""

import httpx
from typing import Any

from src.core.exceptions import NodeExecutionError, OllamaConnectionError
from src.core.logging import get_logger
from src.executor.context_surgeon import ContextSurgeon
from src.models.cognitive_template import DAGNode
from specforge.sampling import SCSConfig, SCSExecutor
from specforge.cognition import (
    ReasoningPipeline, ReasoningPipelineConfig, 
    SPAExecutor, SPAConfig
)

_log = get_logger(__name__)

# ─── OllamaClient ──────────────────────────────────────────────────────────────


class OllamaClient:
    """Thin async HTTP client for the Ollama REST API.

    Attributes:
        base_url: Base URL of the Ollama instance (e.g. 'http://localhost:11434').
        model: Model name to use for generation.
        temperature: Sampling temperature (default 0.3).
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        temperature: float = 0.3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._client: httpx.AsyncClient = httpx.AsyncClient(timeout=120.0)

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 512,
        json_mode: bool = True,
    ) -> str:
        """Call Ollama ``/api/generate`` and return the text response.

        Args:
            system_prompt: The system-level specialist identity prompt.
            user_message: The user prompt with interpolated variables.
            max_tokens: Hard cap on generated tokens.
            json_mode: If True, request JSON-formatted output.

        Returns:
            The raw ``response`` string from Ollama.

        Raises:
            OllamaConnectionError: If the request fails or times out.
        """
        payload: dict[str, object] = {
            "model": self.model,
            "system": system_prompt,
            "prompt": user_message,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        try:
            response = await self._client.post(
                f"{self.base_url}/api/generate",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")

        except httpx.TimeoutException as exc:
            _log.error("ollama_timeout", url=f"{self.base_url}/api/generate")
            raise OllamaConnectionError(
                base_url=self.base_url,
                original_exc=exc,
                context={"operation": "generate", "model": self.model},
            )

        except httpx.HTTPStatusError as exc:
            _log.error(
                "ollama_http_error",
                status=exc.response.status_code,
                url=f"{self.base_url}/api/generate",
            )
            raise OllamaConnectionError(
                base_url=self.base_url,
                original_exc=exc,
                context={
                    "operation": "generate",
                    "model": self.model,
                    "status": exc.response.status_code,
                },
            )

        except httpx.RequestError as exc:
            _log.error("ollama_request_error", url=f"{self.base_url}/api/generate")
            raise OllamaConnectionError(
                base_url=self.base_url,
                original_exc=exc,
                context={"operation": "generate", "model": self.model},
            )

    async def health_check(self) -> bool:
        """Ping the Ollama ``/api/tags`` endpoint.

        Returns:
            True if the endpoint returns 200, False otherwise.
        """
        try:
            response = await self._client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except (httpx.RequestError, httpx.TimeoutException):
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()


# ─── AtomicExecutor ────────────────────────────────────────────────────────────


class AtomicExecutor:
    """Execute a single atomic DAG node via Ollama with retry and error injection.

    Attributes:
        ollama_client: The OllamaClient instance to use for generation.
        context_surgeon: The ContextSurgeon instance for building prompts.
    """

    def __init__(
        self,
        ollama_client: OllamaClient,
        context_surgeon: ContextSurgeon,
    ) -> None:
        self._client = ollama_client
        self._surgeon = context_surgeon

    async def execute_node(
        self,
        node: DAGNode,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
        attempt_number: int = 1,
        previous_error: str | None = None,
    ) -> tuple[str, list[str]]:
        """Execute a single atomic node and return its raw output.

        Builds the prompt via ContextSurgeon, optionally appends a retry error
        hint if this is not the first attempt, then calls Ollama.

        Args:
            node: The DAGNode to execute.
            global_state: Accumulated outputs from previously executed nodes.
            input_data: Top-level input payload for this run.
            attempt_number: Which attempt this is (1 = first, 2+ = retry).
            previous_error: Error message from the previous failed attempt.

        Returns:
            Tuple of (raw_output_string, rule_files_used).

        Raises:
            NodeExecutionError: If the Ollama call fails.
        """
        import time

        system_prompt, user_message, rule_files = await self._surgeon.build_final_prompt(
            node=node,
            global_state=global_state,
            input_data=input_data,
        )

        # Inject error feedback on retry attempts
        if attempt_number > 1 and previous_error:
            user_message = (
                f"{user_message}\n\n⚠️ PREVIOUS ATTEMPT FAILED\n"
                f"Error: {previous_error}\n"
                f"Correct your output accordingly."
            )

        start_ms = time.perf_counter()

        # ─── DEEP REASONING PIPELINE (Person 1: SPA Layer) ──────────────────
        # Check for deep reasoning by node_id suffix (e.g., "severity_classification_deep_reason")
        # Nodes with this suffix use SPA + Budget Forcing + Socratic method
        if node.node_id.endswith("_deep_reason"):
            try:
                _log.info("deep_reason_node_detected", node_id=node.node_id)
                pipeline = ReasoningPipeline(ReasoningPipelineConfig(
                    model=self._client.model,
                    ollama_base_url=self._client.base_url,
                ))
                result = await pipeline.execute(user_message, system_prompt=system_prompt)
                await pipeline.close()
                
                # Check if final_answer is empty; if so, fall through to SPA/Ollama
                if result.final_answer and result.final_answer.strip():
                    elapsed_ms = (time.perf_counter() - start_ms) * 1000
                    _log.info(
                        "deep_reason_completed",
                        node_id=node.node_id,
                        pipeline_used=result.pipeline_used,
                        execution_time_ms=round(elapsed_ms, 2),
                    )
                    return result.final_answer, rule_files
                else:
                    _log.warning(
                        "deep_reason_empty_output",
                        node_id=node.node_id,
                        reasoning_trace_len=len(result.reasoning_trace or ""),
                    )
                    # Fall through to SPA/Ollama
            except Exception as exc:
                _log.warning(
                    "deep_reason_fallback",
                    node_id=node.node_id,
                    error=str(exc),
                )
                # Fall through to normal execution

        # ─── SEMANTIC PRESSURE ANNEALING (Person 1: SPA Layer) ──────────────
        # Check for pressure_annealing config in bento_config (Pydantic model)
        bento_config = getattr(node, 'bento_config', None)
        if bento_config and hasattr(bento_config, 'pressure_annealing') and bento_config.pressure_annealing:
            try:
                _log.info("pressure_annealing_enabled", node_id=node.node_id)
                spa_cfg_dict = bento_config.pressure_annealing
                spa_cfg = SPAConfig(**spa_cfg_dict)
                spa_executor = SPAExecutor(self._client.base_url)
                result = await spa_executor.generate(
                    model=self._client.model,
                    prompt=user_message,
                    spa_config=spa_cfg,
                    system_prompt=system_prompt,
                    max_tokens=node.focus_prompt.max_tokens if hasattr(node, 'focus_prompt') else 500,
                    temperature=node.focus_prompt.temperature if hasattr(node, 'focus_prompt') else self._client.temperature,
                )
                await spa_executor.close()
                elapsed_ms = (time.perf_counter() - start_ms) * 1000
                _log.info(
                    "spa_completed",
                    node_id=node.node_id,
                    injections=result.injection_count,
                    execution_time_ms=round(elapsed_ms, 2),
                )
                return result.text, rule_files
            except Exception as exc:
                _log.warning(
                    "spa_fallback",
                    node_id=node.node_id,
                    error=str(exc),
                )
                # Fall through to normal execution

        scs_executor: SCSExecutor | None = None
        scs_result = None

        # SCS is only safe for free-form text generation. Structured JSON nodes
        # must continue through the existing validated Ollama path so we don't
        # bypass schema enforcement or introduce invalid control characters.
        should_use_scs = not bool(node.focus_prompt.output_schema)

        if should_use_scs:
            try:
                scs_executor = SCSExecutor(
                    SCSConfig(ollama_base_url=self._client.base_url)
                )
                scs_result = await scs_executor.generate(
                    model=self._client.model,
                    prompt=f"{system_prompt}\n\n{user_message}",
                    node_type=getattr(node.node_type, "value", str(node.node_type)),
                    max_tokens=node.focus_prompt.max_tokens,
                    temperature=node.focus_prompt.temperature,
                )
            except Exception as exc:
                _log.warning(
                    "scs_fallback",
                    node_id=node.node_id,
                    error=str(exc),
                )
            finally:
                if scs_executor is not None:
                    await scs_executor.close()

        if scs_result is not None and not scs_result.should_escalate:
            raw_output = scs_result.text
            elapsed_ms = (time.perf_counter() - start_ms) * 1000

            _log.info(
                "node_executed",
                node_id=node.node_id,
                attempt_number=attempt_number,
                execution_time_ms=round(elapsed_ms, 2),
            )

            return raw_output, rule_files

        try:
            raw_output = await self._client.generate(
                system_prompt=system_prompt,
                user_message=user_message,
                max_tokens=node.focus_prompt.max_tokens,
                json_mode=True,
            )
        except OllamaConnectionError:
            raise
        except Exception as exc:
            _log.error("node_execution_error", node_id=node.node_id, error=str(exc))
            raise NodeExecutionError(
                node_id=node.node_id,
                attempt_count=attempt_number,
                last_output="",
                context={"error": str(exc)},
            ) from exc

        elapsed_ms = (time.perf_counter() - start_ms) * 1000

        _log.info(
            "node_executed",
            node_id=node.node_id,
            attempt_number=attempt_number,
            execution_time_ms=round(elapsed_ms, 2),
        )

        return raw_output, rule_files


# ─── Factory ───────────────────────────────────────────────────────────────────


def create_ollama_client(
    base_url: str,
    model: str,
    temperature: float = 0.3,
) -> OllamaClient:
    """Create an OllamaClient from base URL and model name.

    Args:
        base_url: Ollama server base URL (e.g. 'http://localhost:11434').
        model: Model name to use for generation.
        temperature: Sampling temperature.

    Returns:
        A configured OllamaClient bound to the given base URL and model.
    """
    return OllamaClient(
        base_url=base_url,
        model=model,
        temperature=temperature,
    )
