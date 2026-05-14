"""SpecForge Typer CLI — command-line interface for all SpecForge operations."""

import asyncio
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import click
import httpx
import typer
from typer.core import TyperGroup
from rich.console import Console
from rich.table import Table
from rich import print as rprint

# Suppress noisy third-party loggers at module load time
for _logger_name in ("httpx", "httpcore", "charset_normalizer", "certifi"):
    _l = logging.getLogger(_logger_name)
    _l.setLevel(logging.WARNING)
    _l.propagate = False

# CLI invocations: root logger at WARNING so only WARNING+ prints to terminal.
# This prevents httpx/httpcore INFO lines from leaking between rich output.
logging.getLogger().setLevel(logging.WARNING)

app = typer.Typer(
    name="specforge",
    help="SpecForge CLI — Offline-first reasoning orchestration framework",
    add_completion=False,
)

console = Console()


# ─── Helpers ────────────────────────────────────────────────────────────────────────


def _load_json_file(path: Path) -> dict:
    """Load and parse a JSON file, exit on error."""
    if not path.is_file():
        typer.secho(f"File not found: {path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        typer.secho(f"Invalid JSON in {path}: {exc.msg}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def _run_async(coro):
    """Run an async coroutine from a sync context."""
    try:
        asyncio.get_running_loop()
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


def _load_template(template_ref: str) -> "CognitiveTemplate":
    from src.models.cognitive_template import CognitiveTemplate

    template_path = Path(template_ref)
    if template_path.is_file():
        return CognitiveTemplate.load_from_file(template_path)

    from src.compiler.template_registry import TemplateRegistry
    from src.core.exceptions import TemplateNotFoundError

    registry = TemplateRegistry(templates_dir=Path("templates"))
    try:
        return _run_async(registry.load(template_ref))
    except TemplateNotFoundError:
        typer.secho(f"Template not found: {template_ref}", fg=typer.colors.RED, err=True)
        raise typer.Exit(1)


def _get_redis() -> "RedisClient":
    from src.cache.redis_client import RedisClient
    from src.core.config import get_config

    cfg = get_config()
    redis = RedisClient(redis_url=str(cfg.redis_url))
    return redis


# ─── Template group ─────────────────────────────────────────────────────────────


template_app = typer.Typer(help="Manage cognitive templates")
app.add_typer(template_app, name="template")


@template_app.command("list")
def template_list():
    """List all cognitive templates."""
    from src.compiler.template_registry import TemplateRegistry

    registry = TemplateRegistry(templates_dir=Path("templates"))
    templates = _run_async(registry.list_templates())

    table = Table(title="Cognitive Templates")
    table.add_column("ID", style="dim")
    table.add_column("Name")
    table.add_column("Version", style="cyan")
    table.add_column("Tags")

    for t in templates:
        table.add_row(
            t["template_id"][:8] + "…",
            t["name"],
            t["version"],
            ", ".join(t.get("tags", [])) or "—",
        )

    console.print(table)


@template_app.command("show")
def template_show(template_id: str):
    """Show full template JSON."""
    template = _load_template(template_id)
    console.print_json(template.model_dump_json(indent=2))


@template_app.command("validate")
def template_validate(file: Path):
    """Validate a .ct.json template file without executing."""
    from src.models.cognitive_template import CognitiveTemplate
    from src.core.exceptions import TemplateValidationError

    data = _load_json_file(file)
    try:
        template = CognitiveTemplate.model_validate(data)
    except Exception as exc:
        typer.secho(f"VALIDATION FAILED: {exc}", fg=typer.colors.RED)
        raise typer.Exit(1)

    builder = DAGBuilder()
    errors = builder.validate_structure(template.nodes)
    if errors:
        typer.secho("VALIDATION FAILED:", fg=typer.colors.RED)
        for err in errors:
            typer.secho(f"  • {err}", fg=typer.colors.RED)
        raise typer.Exit(1)

    typer.secho("VALID", fg=typer.colors.GREEN)


@template_app.command("waves")
def template_waves(template_id: str):
    """Print execution waves for a template."""
    template = _load_template(template_id)
    waves = template.get_execution_order()

    for i, wave in enumerate(waves):
        rprint(f"[cyan]Wave {i}:[/cyan] {', '.join(wave)}")


# ─── Run group ──────────────────────────────────────────────────────────────────


class _RunGroup(TyperGroup):
    """Backward-compatible run group.

    Rewrites legacy syntax `specforge run <template_id> ...` to
    `specforge run start <template_id> ...`.
    """

    def resolve_command(self, ctx: click.Context, args: list[str]):
        if args and args[0] not in self.commands and not args[0].startswith("-"):
            args.insert(0, "start")
        return super().resolve_command(ctx, args)


run_app = typer.Typer(help="Execute templates and manage runs", cls=_RunGroup)
app.add_typer(run_app, name="run")


@run_app.command("status")
def run_status(run_id: str):
    """Check execution status."""
    redis = _get_redis()

    async def _check() -> None:
        await redis.connect()
        raw = await redis.get(f"specforge:run:{run_id}")
        if not raw:
            typer.secho("Run not found", fg=typer.colors.RED)
            raise typer.Exit(1)
        data = json.loads(raw)
        console.print_json(json.dumps(data, indent=2, default=str))
        await redis.close()

    _run_async(_check())


@run_app.command("state")
def run_state(run_id: str):
    """Print current state.md content."""
    redis = _get_redis()

    async def _show() -> None:
        await redis.connect()
        raw = await redis.get(f"specforge:run:{run_id}")
        if not raw:
            typer.secho("Run not found", fg=typer.colors.RED)
            raise typer.Exit(1)
        data = json.loads(raw)
        state_path = data.get("state_file_path")
        if not state_path or not Path(state_path).is_file():
            typer.secho("state.md not found", fg=typer.colors.RED)
            raise typer.Exit(1)
        content = Path(state_path).read_text()
        console.print(content)
        await redis.close()

    _run_async(_show())


@run_app.command("cancel")
def run_cancel(run_id: str):
    """Cancel a running execution."""
    redis = _get_redis()

    async def _cancel() -> None:
        await redis.connect()
        raw = await redis.get(f"specforge:run:{run_id}")
        if not raw:
            typer.secho("Run not found", fg=typer.colors.RED)
            raise typer.Exit(1)
        data = json.loads(raw)
        data["status"] = "cancelled"
        await redis.set(f"specforge:run:{run_id}", json.dumps(data), ex=86400)
        typer.secho(f"Run {run_id} marked as cancelled", fg=typer.colors.YELLOW)
        await redis.close()

    _run_async(_cancel())


@run_app.command("list")
def run_list():
    """List recent executions."""
    redis = _get_redis()

    async def _list() -> None:
        await redis.connect()
        run_ids = await redis.smembers("specforge:executions:index")
        recent = sorted(run_ids, reverse=True)[:50]

        table = Table(title="Recent Executions")
        table.add_column("Run ID", style="dim")
        table.add_column("Template")
        table.add_column("Status")
        table.add_column("Started")

        for rid in recent:
            raw = await redis.get(f"specforge:run:{rid}")
            if raw:
                d = json.loads(raw)
                status_color = (
                    typer.colors.GREEN
                    if d["status"] == "completed"
                    else typer.colors.RED
                    if d["status"] == "failed"
                    else typer.colors.YELLOW
                )
                table.add_row(
                    rid[:8] + "…",
                    d.get("template_name", "—")[:30],
                    f"[{status_color}]{d['status']}[/{status_color}]",
                    d.get("started_at", "—")[:19],
                )

        console.print(table)
        await redis.close()

    _run_async(_list())


@run_app.command("start")
def run_start(
    template_id: str,
    input_file: Path = typer.Option(None, "--input-file", "-i"),
    output_dir: Path = typer.Option(Path("./output"), "--output-dir", "-o"),
    sync: bool = typer.Option(False, "--sync", "-s"),
):
    """Start a template execution."""
    from src.tasks.execution_tasks import run_template_execution

    input_data = {}
    if input_file:
        input_data = _load_json_file(input_file)

    run_id = str(uuid.uuid4())

    if sync:
        _run_sync_execution(run_id, template_id, input_data, output_dir)
    else:
        run_template_execution.delay(
            run_id=run_id,
            template_id=template_id,
            input_data=input_data,
            output_dir=str(output_dir),
        )
        console.print("[dim]Execution submitted.[/dim]")
        console.print(f"[dim]Run ID   : {run_id}[/dim]")
        console.print(f"[dim]Monitor  : specforge run status {run_id}[/dim]")
        console.print(f"[dim]State    : specforge run state {run_id}[/dim]")


def _run_sync_execution(run_id: str, template_id: str, input_data: dict, output_dir: Path) -> None:
    """Execute a template synchronously, polling the API every 2 seconds.

    Prints node results as they complete, then prints a final summary.
    Exits with code 1 if the execution fails.
    """
    from src.core.config import get_config

    cfg = get_config()
    base_url = str(cfg.api_base_url).rstrip("/")

    # ── Submit execution ──────────────────────────────────────────────────────────
    console.print("[dim]Starting execution...[/dim]")
    console.print(f"[dim]Template : {template_id}[/dim]")
    console.print(f"[dim]Output   : {output_dir}[/dim]")
    console.print(f"{'─' * 50}")

    async def _submit() -> str:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url}/api/v1/executions",
                json={
                    "template_id": template_id,
                    "input_data": input_data,
                    "output_dir": str(output_dir),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            run_id_value = data.get("run_id") or data.get("runId")
            if not run_id_value:
                raise KeyError("run_id")
            return run_id_value

    try:
        submitted_run_id = _run_async(_submit())
    except Exception as exc:
        console.print(f"[red]Failed to submit execution: {exc}[/red]")
        raise typer.Exit(1)

    output_path = output_dir / submitted_run_id
    console.print(f"[dim]Run ID   : {submitted_run_id}[/dim]")

    # ── Poll loop ───────────────────────────────────────────────────────────────
    from rich.live import Live
    from rich.text import Text

    displayed_nodes: set[str] = set()
    total_nodes = 0
    completed_nodes = 0
    POLL_INTERVAL = 2.0
    MAX_RETRIES = 3
    SEP = f"{'─' * 50}"

    def _status_icon(status: str) -> str:
        # Handle both snake_case (engine internals) and camelCase (API responses)
        s = status.lower()
        if s == "failed":
            return "[red]✕[/red]"
        if s == "pending":
            return "[dim]○[/dim]"
        if s == "running":
            return "[cyan]⟳[/cyan]"
        if s in ("passed_tier1", "passedTier1"):
            return "[green]✓[/green]"
        if s in ("passed_tier2", "passedTier2"):
            return "[yellow]⚠[/yellow]"
        if s in ("passed_tier3", "passedTier3"):
            return "[blue]◈[/blue]"
        return "[dim]○[/dim]"

    def _tier_label(tier: str, node_type: str | None = None) -> str:
        label = {"fast": "FAST", "repair": "REPAIR", "deep": "DEEP"}.get(
            tier.lower(), tier.upper()
        )
        if node_type:
            upper = node_type.upper()
            if upper == "SYMBOLIC":
                label += " [SYMBOLIC]"
            elif upper == "ADVERSARIAL":
                label += " [TRIAD]"
            elif upper == "LOOKAHEAD":
                label += " [LOOKAHEAD]"
        return label

    def _format_time(exec_time: float, node_type: str | None = None) -> str:
        """Format execution time for display.

        Non-SYMBOLIC nodes with < 1ms display as '—' (indicates missing/bad data).
        >= 1000ms displayed as seconds.
        """
        is_symbolic = node_type and node_type.upper() == "SYMBOLIC"
        if exec_time < 1.0 and not is_symbolic:
            return "—"
        if exec_time >= 1000.0:
            return f"{exec_time / 1000.0:.1f}s"
        return f"{exec_time:.0f}ms"

    def _print_node(node_id: str, node_data: dict) -> None:
        status = node_data.get("status", "pending")
        # API uses camelCase: tierUsed, executionTimeMs, attemptCount, nodeType
        # Also support snake_case from engine-internal dicts
        tier = node_data.get("tierUsed") or node_data.get("tier_used", "fast")
        exec_time = node_data.get("executionTimeMs") or node_data.get("execution_time_ms", 0.0)
        attempts = node_data.get("attemptCount") or node_data.get("attempt_count", 1)
        node_type = node_data.get("nodeType") or node_data.get("node_type")

        # 0 = pre-execution failure (e.g. missing variable resolution)
        attempts_str = "—" if attempts <= 0 else str(attempts)

        icon = _status_icon(status)
        tier_lbl = _tier_label(tier, node_type)
        time_str = _format_time(exec_time, node_type)
        suffix = ""
        if node_type:
            upper = node_type.upper()
            if upper == "SYMBOLIC":
                suffix = "  [SYMBOLIC]"
            elif upper == "ADVERSARIAL":
                suffix = "  [TRIAD]"
            elif upper == "LOOKAHEAD":
                suffix = "  [LOOKAHEAD]"

        console.print(f"{icon}  {node_id:<24} {tier_lbl:<12} {time_str:<8} attempt {attempts_str}{suffix}")

    def _is_done(node_data: dict) -> bool:
        s = (node_data.get("status") or "pending").lower()
        return s not in ("pending", "running")

    async def _poll_once() -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url}/api/v1/executions/{submitted_run_id}")
            resp.raise_for_status()
            return resp.json()

    async def _poll_loop() -> None:
        nonlocal displayed_nodes, total_nodes, completed_nodes

        retry_count = 0

        while True:
            try:
                data = _run_async(_poll_once())
                retry_count = 0
            except Exception as exc:
                retry_count += 1
                if retry_count > MAX_RETRIES:
                    console.print(f"[red]API unreachable after {MAX_RETRIES} retries. Aborting.[/red]")
                    raise typer.Exit(1)
                console.print(f"[yellow]API error (retry {retry_count}/{MAX_RETRIES}): {exc}[/yellow]")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            # API top-level keys are camelCase; per-node keys are snake_case
            status = data.get("status", "running")
            node_results = data.get("nodeResults") or data.get("node_results", {})
            total_nodes = data.get("totalNodes", data.get("total_nodes", len(node_results)))
            completed_nodes = sum(1 for v in node_results.values() if _is_done(v))

            # Print newly-completed nodes (each node printed only once)
            for node_id, node_data in node_results.items():
                if node_id not in displayed_nodes and _is_done(node_data):
                    displayed_nodes.add(node_id)
                    _print_node(node_id, node_data)

            if status in {"pending", "running"}:
                wave_desc = f"{completed_nodes}/{total_nodes} nodes complete"
                console.print(f"  [dim]{wave_desc}...[/dim]", end="\r")
                await asyncio.sleep(POLL_INTERVAL)
                # Overwrite the line with spaces before next output
                console.print(" " * 60, end="\r")
                continue

            # COMPLETED or FAILED
            console.print("\n" + SEP)
            duration = data.get("totalExecutionTimeMs") or data.get("total_execution_time_ms")
            duration_str = f"{duration / 1000:.1f}s" if duration else "—"
            state_path = data.get("stateFilePath") or data.get("state_file_path") or ""
            error_msg = data.get("errorMessage") or data.get("error_message")

            console.print(f"[dim]Status    : {status.upper()}[/dim]")
            console.print(f"[dim]Duration  : {duration_str}[/dim]")
            console.print(f"[dim]Nodes     : {completed_nodes}/{total_nodes}[/dim]")
            if state_path:
                console.print(f"[dim]Output    : {output_path / 'final_output.json'}[/dim]")
                console.print(f"[dim]State     : {state_path}[/dim]")
            console.print(SEP)

            if error_msg and status == "failed":
                console.print(f"[red]Error: {error_msg}[/red]")
                raise typer.Exit(1)

            return

    _run_async(_poll_loop())


# ─── Knowledge group ─────────────────────────────────────────────────────────────


knowledge_app = typer.Typer(help="Manage rule files and the knowledge graph")
app.add_typer(knowledge_app, name="knowledge")


@knowledge_app.command("list")
def knowledge_list():
    """List all rule files."""
    from src.knowledge.graph_manager import KnowledgeGraphManager

    kg = KnowledgeGraphManager(rules_dir=Path("rules"))

    async def _list() -> None:
        await kg.initialize()
        all_files = kg._indexer.get_all_files()

        table = Table(title="Rule Files")
        table.add_column("File")

        for f in sorted(all_files):
            table.add_row(f)

        console.print(table)

    _run_async(_list())


@knowledge_app.command("show")
def knowledge_show(file_name: str):
    """Print rule file content."""
    path = Path("rules") / (file_name if file_name.endswith(".md") else f"{file_name}.md")
    if not path.is_file():
        typer.secho(f"Rule file not found: {file_name}", fg=typer.colors.RED)
        raise typer.Exit(1)
    console.print(path.read_text(encoding="utf-8"))


@knowledge_app.command("create")
def knowledge_create(
    name: str,
    from_file: Path = typer.Option(None, "--from-file", "-f"),
):
    """Create a new rule file."""
    from src.knowledge.graph_manager import KnowledgeGraphManager

    kg = KnowledgeGraphManager(rules_dir=Path("rules"))

    if from_file:
        content = from_file.read_text(encoding="utf-8")
    else:
        content = typer.prompt("Rule content (Markdown)", type=str, default="")

    path = _run_async(kg.create_rule_file(name, content))
    typer.secho(f"Created: {path}", fg=typer.colors.GREEN)


@knowledge_app.command("graph-stats")
def knowledge_graph_stats():
    """Print knowledge graph statistics."""
    from src.knowledge.graph_manager import KnowledgeGraphManager

    kg = KnowledgeGraphManager(rules_dir=Path("rules"))

    async def _stats() -> None:
        await kg.initialize()
        stats = await kg.get_graph_stats()

        table = Table(title="Knowledge Graph Stats")
        table.add_column("Metric")
        table.add_column("Value")
        table.add_row("Total Files", str(stats["total_files"]))
        table.add_row("Total Links", str(stats["total_links"]))
        table.add_row("Isolated Files", str(len(stats["isolated_files"])))

        console.print(table)

        if stats["most_linked"]:
            rprint("\n[cyan]Most Linked Files:[/cyan]")
            for fname, count in stats["most_linked"][:10]:
                rprint(f"  {fname}: {count} links")

    _run_async(_stats())


@knowledge_app.command("rebuild")
def knowledge_rebuild():
    """Rebuild the knowledge graph index."""
    from src.knowledge.graph_manager import KnowledgeGraphManager

    kg = KnowledgeGraphManager(rules_dir=Path("rules"))
    _run_async(kg.initialize())
    typer.secho("Knowledge graph index rebuilt", fg=typer.colors.GREEN)


# ─── Heal group ───────────────────────────────────────────────────────────────


heal_app = typer.Typer(help="View and manage self-healing events")
app.add_typer(heal_app, name="heal")


@heal_app.command("events")
def heal_events():
    """List recent healing events."""
    import asyncio
    import json
    from rich.table import Table

    async def _list_events() -> None:
        from src.api.routers.healing import _HEALING_INDEX_KEY, _healing_event_key
        from src.api.dependencies import get_redis

        redis = await get_redis()
        event_ids = await redis.smembers(_HEALING_INDEX_KEY)
        events = []

        for eid in event_ids:
            raw = await redis.get(_healing_event_key(eid))
            if raw:
                events.append(json.loads(raw))

        events = sorted(
            events,
            key=lambda e: e.get("triggered_at", ""),
            reverse=True,
        )[:20]

        table = Table(title="Recent Healing Events")
        table.add_column("Event ID", style="dim")
        table.add_column("Node ID")
        table.add_column("Trigger")
        table.add_column("Applied")

        for e in events:
            table.add_row(
                e["event_id"][:8] + "…",
                e["node_id"],
                e["trigger"],
                "✅" if e["applied"] else "❌",
            )

        console.print(table)

    _run_async(_list_events())


@heal_app.command("show")
def heal_show(event_id: str):
    """Show full healing event details."""
    import asyncio

    async def _show_event() -> None:
        from src.api.routers.healing import _load_event
        from src.api.dependencies import get_redis

        redis = await get_redis()
        event = await _load_event(event_id, redis)
        if not event:
            typer.secho("Healing event not found", fg=typer.colors.RED)
            raise typer.Exit(1)

        console.print_json(json.dumps(event, indent=2, default=str))

    _run_async(_show_event())


@heal_app.command("approve")
def heal_approve(event_id: str):
    """Approve and apply a healing event's patches."""
    import asyncio
    import json
    from src.api.routers.healing import _load_event, _store_event
    from src.api.dependencies import get_redis
    from src.healing.rule_patcher import RulePatcher
    from datetime import datetime, timezone
    from pathlib import Path

    async def _approve() -> None:
        redis = await get_redis()
        event = await _load_event(event_id, redis)
        if not event:
            typer.secho("Healing event not found", fg=typer.colors.RED)
            raise typer.Exit(1)

        if event["applied"]:
            typer.secho("Patches already applied", fg=typer.colors.YELLOW)
            raise typer.Exit(1)

        patcher = RulePatcher(rules_dir=Path("rules"))
        for patch_data in event.get("patches", []):
            await patcher.apply_patch(
                rule_file_name=patch_data["file_name"],
                new_content=patch_data["patched_content"],
                changes_summary=patch_data["changes_summary"],
                backup=True,
            )
        event["applied"] = True
        event["applied_at"] = datetime.now(timezone.utc).isoformat()
        event["approved_by"] = "cli"
        await _store_event(event_id, event, redis)
        typer.secho(f"Event {event_id} approved and patches applied", fg=typer.colors.GREEN)

    _run_async(_approve())


@heal_app.command("reject")
def heal_reject(event_id: str):
    """Reject a healing event."""
    import asyncio
    from src.api.routers.healing import _load_event, _store_event
    from src.api.dependencies import get_redis

    async def _reject() -> None:
        redis = await get_redis()
        event = await _load_event(event_id, redis)
        if not event:
            typer.secho("Healing event not found", fg=typer.colors.RED)
            raise typer.Exit(1)

        event["applied"] = False
        event["approved_by"] = "cli"
        await _store_event(event_id, event, redis)
        typer.secho(f"Event {event_id} rejected", fg=typer.colors.YELLOW)

    _run_async(_reject())


# ─── Doctor group ──────────────────────────────────────────────────────────────


doctor_app = typer.Typer(help="System health check")
app.add_typer(doctor_app, name="doctor")


@doctor_app.command("doctor")
def doctor():
    """Run system health checks: Ollama, Redis, DB, rules directory."""
    from src.core.config import get_config
    from src.executor.atomic_executor import create_ollama_client

    cfg = get_config()

    # Ollama
    async def check_ollama() -> tuple[str, bool]:
        client = create_ollama_client(cfg)
        healthy = await client.health_check()
        await client.close()
        return ("Ollama", healthy)

    # Redis
    async def check_redis() -> tuple[str, bool]:
        redis = _get_redis()
        await redis.connect()
        await redis.close()
        return ("Redis", True)

    # Rules dir
    def check_rules() -> tuple[str, bool]:
        rules = Path("rules")
        return ("Rules directory", rules.is_dir())

    # Templates dir
    def check_templates() -> tuple[str, bool]:
        templates = Path("templates")
        return ("Templates directory", templates.is_dir())

    all_checks = [
        _run_async(check_ollama()),
        _run_async(check_redis()),
        check_rules(),
        check_templates(),
    ]

    table = Table(title="SpecForge Health Check")
    table.add_column("Check", style="bold")
    table.add_column("Status")
    table.add_column("Detail")

    for name, passed in all_checks:
        table.add_row(
            name,
            "[green]✅ PASS[/green]" if passed else "[red]❌ FAIL[/red]",
            "healthy" if passed else "unreachable",
        )

    console.print(table)


from src.cache.redis_client import RedisClient
from src.compiler.dag_builder import DAGBuilder
from src.core.exceptions import TemplateNotFoundError
from src.models.cognitive_template import CognitiveTemplate


if __name__ == "__main__":
    app()
