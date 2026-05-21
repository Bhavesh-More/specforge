"""Ollama inference layer — execute atomic LLM nodes."""

import httpx
import json
from datetime import datetime, timezone
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

        start_ms = time.perf_counter()

        system_prompt, user_message, rule_files = await self._surgeon.build_final_prompt(
            node=node,
            global_state=global_state,
            input_data=input_data,
        )

        # The final assembly node is a deterministic merge of prior structured
        # outputs. Running it through Ollama adds a large, brittle prompt with no
        # real reasoning benefit, so synthesize it locally instead.
        if node.node_id == "finalize":
            final_output = self._assemble_finalize_playbook(global_state, input_data)
            raw_output = json.dumps(final_output, separators=(",", ":"), ensure_ascii=False)
            elapsed_ms = (time.perf_counter() - start_ms) * 1000

            _log.info(
                "node_executed",
                node_id=node.node_id,
                attempt_number=attempt_number,
                execution_time_ms=round(elapsed_ms, 2),
                mode="deterministic_assembly",
            )

            return raw_output, rule_files

        memory_context = global_state.get("__quality_memory_context__")
        if isinstance(memory_context, str) and memory_context.strip():
            user_message = (
                f"{user_message}\n\n"
                f"{memory_context}\n\n"
                "Apply the relevant memory as guidance, but keep the current task "
                "and output schema authoritative."
            )
        fmb_config = global_state.get("__fmb_adapted_config__")
        if isinstance(fmb_config, dict):
            prefixes = fmb_config.get("prompt_prefix_additions") or []
            if prefixes:
                prefix_text = "\n".join(str(prefix) for prefix in prefixes)
                user_message = f"{prefix_text}\n\n{user_message}"

        # Inject error feedback on retry attempts
        if attempt_number > 1 and previous_error:
            user_message = (
                f"{user_message}\n\n⚠️ PREVIOUS ATTEMPT FAILED\n"
                f"Error: {previous_error}\n"
                f"Correct your output accordingly."
            )

        # ─── DEEP REASONING PIPELINE (Person 1: SPA Layer) ──────────────────
        # Detect deep reasoning nodes either by explicit node_type == 'deep_reason'
        # (case-insensitive) or by the legacy node_id suffix ("_deep_reason").
        node_type_val = getattr(node, 'node_type', '') or ''
        if hasattr(node_type_val, 'value'):
            node_type_str = str(getattr(node_type_val, 'value', '') or '')
        else:
            node_type_str = str(node_type_val)
        force_deep_reason = (
            isinstance(fmb_config, dict) and bool(fmb_config.get("force_deep_reason"))
        )
        is_deep_reason = (
            (node_type_str.lower() == 'deep_reason')
            or node.node_id.endswith("_deep_reason")
            or force_deep_reason
        )

        if is_deep_reason:
            try:
                _log.info("deep_reason_node_detected", node_id=node.node_id, node_type=node_type_val)

                # Build ReasoningPipelineConfig and propagate focus_prompt tuning
                rpc = ReasoningPipelineConfig(
                    model=self._client.model,
                    ollama_base_url=self._client.base_url,
                )

                # If focus_prompt tuning exists, map sensible fields into the
                # budget and socratic configs to respect template intent.
                focus = getattr(node, 'focus_prompt', None)
                if focus:
                    try:
                        max_toks = int(getattr(focus, 'max_tokens', None) or getattr(focus, 'max_tokens', None) or 0)
                    except Exception:
                        max_toks = 0
                    temp = None
                    try:
                        temp = float(getattr(focus, 'temperature', None))
                    except Exception:
                        temp = None

                    if max_toks and rpc.budget_config:
                        # set max_reasoning_tokens to focus max_tokens but keep min reasonable
                        rpc.budget_config.max_reasoning_tokens = max(rpc.budget_config.min_reasoning_tokens, max_toks)
                    if temp is not None and rpc.socratic_config:
                        # propagate temperature to synthesis step
                        rpc.socratic_config.synthesis_temperature = temp

                pipeline = ReasoningPipeline(rpc)
                result = await pipeline.execute(user_message, system_prompt=system_prompt)
                await pipeline.close()

                # If the pipeline produced a final answer, return it directly.
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
                if isinstance(fmb_config, dict):
                    spa_cfg_dict = dict(spa_cfg_dict)
                    inject_override = fmb_config.get("spa_inject_threshold_override")
                    warn_override = fmb_config.get("spa_warn_threshold_override")
                    if inject_override is not None:
                        spa_cfg_dict["inject_threshold"] = float(inject_override)
                    if warn_override is not None:
                        spa_cfg_dict["warn_threshold"] = float(warn_override)
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
                scs_config = SCSConfig(ollama_base_url=self._client.base_url)
                if isinstance(fmb_config, dict):
                    n_override = fmb_config.get("n_drafts_override")
                    threshold_override = fmb_config.get("scs_confidence_threshold")
                    if n_override is not None:
                        scs_config.n_drafts = int(n_override)
                        scs_config.NODE_TYPE_N_OVERRIDES[
                            getattr(node.node_type, "value", str(node.node_type))
                        ] = int(n_override)
                    if threshold_override is not None:
                        scs_config.confidence_threshold = float(threshold_override)
                scs_executor = SCSExecutor(scs_config)
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

    def _assemble_finalize_playbook(
        self,
        global_state: dict[str, Any],
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the final data exfiltration playbook from structured node outputs."""

        gather_context = global_state.get("gather_context") or {}
        triage = global_state.get("triage") or {}
        analyze = global_state.get("analyze") or {}
        draft_response_actions = global_state.get("draft_response_actions") or {}
        draft_dlp = global_state.get("draft_dlp_gap_and_compliance") or {}
        validate = global_state.get("validate") or {}

        incident_id = (
            gather_context.get("incident_id")
            or input_data.get("incident_id")
            or "unknown"
        )

        def _as_list(value: Any) -> list[Any]:
            return value if isinstance(value, list) else []

        def _as_dict(value: Any) -> dict[str, Any]:
            return value if isinstance(value, dict) else {}

        iocs = _as_list(analyze.get("iocs"))
        confirmed_iocs = [
            {"type": item.get("type", "other"), "value": item.get("value", "")}
            for item in iocs
            if isinstance(item, dict)
            and item.get("confidence", "confirmed") == "confirmed"
            and isinstance(item.get("value"), str)
            and item.get("value")
        ]

        if not confirmed_iocs:
            confirmed_iocs = [
                {"type": item.get("type", "other"), "value": item.get("value", "")}
                for item in iocs
                if isinstance(item, dict)
                and isinstance(item.get("value"), str)
                and item.get("value")
            ]

        compliance_trace = _as_dict(draft_dlp.get("compliance_trace"))
        gdpr_assessment = compliance_trace.get("gdpr_assessment")
        if not isinstance(gdpr_assessment, dict):
            gdpr_assessment = {
                "gdpr_art33_required": bool(triage.get("gdpr_notification_likely")),
                "gdpr_art34_required": bool(triage.get("gdpr_notification_likely")),
            }

        playbook_status = "final" if validate.get("passed", False) else "draft_with_caveats"
        validation_issues = _as_list(validate.get("issues"))

        executive_summary = triage.get("triage_summary")
        if not isinstance(executive_summary, str) or not executive_summary.strip():
            summary_parts = [
                f"Incident {incident_id} involved suspected data exfiltration.",
                f"Triage indicates {triage.get('exfiltration_vector', 'unknown')} with {triage.get('actor_type', 'unknown')}.",
                f"Immediate response actions were drafted and the playbook was validated{' with caveats' if validation_issues else ''}.",
            ]
            executive_summary = " ".join(summary_parts)

        return {
            "playbook_id": incident_id,
            "playbook_status": playbook_status,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "executive_summary": executive_summary,
            "incident_overview": {
                "incident_id": incident_id,
                "incident_title": gather_context.get("incident_title", "unknown"),
                "severity": gather_context.get("severity", triage.get("revised_severity", "unknown")),
                "reported_at": gather_context.get("reported_at", "unknown"),
                "actor_type": triage.get("actor_type", "unknown"),
                "exfiltration_vector": triage.get("exfiltration_vector", "unknown"),
                "triage_confidence": triage.get("triage_confidence", "unknown"),
            },
            "exfiltration_scope": {
                "confirmed_data_lost": _as_list(analyze.get("data_loss_assessment", {}).get("confirmed_exfiltrated")),
                "suspected_data_lost": _as_list(analyze.get("data_loss_assessment", {}).get("suspected_exfiltrated")),
                "total_volume_confirmed": analyze.get("data_loss_assessment", {}).get("total_volume_confirmed", triage.get("estimated_volume_lost", "unknown")),
                "total_volume_suspected": analyze.get("data_loss_assessment", {}).get("total_volume_suspected", "unknown"),
            },
            "timeline": _as_list(analyze.get("timeline")),
            "indicators_of_compromise": _as_list(analyze.get("iocs")),
            "ioc_blocklist_export": confirmed_iocs,
            "root_cause_analysis": {
                "primary_cause": _as_dict(analyze.get("root_cause")).get("primary_cause", "unknown"),
                "control_failure": _as_dict(analyze.get("root_cause")).get("control_failure", "unknown"),
                "initial_access_vector": _as_dict(analyze.get("root_cause")).get("initial_access_vector", "unknown"),
                "contributing_factors": _as_list(_as_dict(analyze.get("root_cause")).get("contributing_factors")),
                "confidence": _as_dict(analyze.get("root_cause")).get("confidence", "unknown"),
            },
            "exfiltration_path": analyze.get("exfiltration_path_summary", "unknown"),
            "containment": _as_list(draft_response_actions.get("containment_actions")),
            "eradication": _as_list(draft_response_actions.get("eradication_actions")),
            "recovery": _as_list(draft_response_actions.get("recovery_actions")),
            "verification": _as_list(draft_response_actions.get("verification_steps")),
            "mitre_attack_mapping": _as_list(analyze.get("mitre_technique_chain")),
            "dlp_gap_analysis": _as_list(draft_dlp.get("dlp_gaps")),
            "lessons_learned": _as_list(draft_dlp.get("lessons_learned")),
            "next_actions": _as_list(draft_dlp.get("next_actions")),
            "compliance_traceability": {
                "nist_80061_phases": _as_list(compliance_trace.get("nist_80061_phases")),
                "soc2_criteria": _as_list(compliance_trace.get("soc2_criteria")),
                "gdpr_assessment": gdpr_assessment,
            },
            "caveats": [
                f"{issue.get('severity', 'info')}: {issue.get('description', 'validation issue')}"
                for issue in validation_issues
                if isinstance(issue, dict)
            ],
        }


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
