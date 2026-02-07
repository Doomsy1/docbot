"""Orchestrator -- async coordination of the full docbot pipeline."""

from __future__ import annotations

import asyncio
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .explorer import enrich_scope_with_llm, explore_scope
from .extractors import setup_extractors
from .llm import LLMClient
from .models import DocsIndex, RunMeta, ScopePlan, ScopeResult
from .planner import build_plan, refine_plan_with_llm
from .reducer import reduce, reduce_with_llm
from .renderer import render, render_with_llm
from .scanner import scan_repo
from .tracker import AgentState, NoOpTracker

console = Console()


def _make_run_id() -> str:
    import secrets
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = secrets.token_hex(3)
    return f"{ts}_{suffix}"


async def _explore_one(
    plan: ScopePlan,
    repo_root: Path,
    sem: asyncio.Semaphore,
    timeout: float,
    llm_client: LLMClient | None = None,
    tracker: NoOpTracker | None = None,
    node_id: str = "",
) -> ScopeResult:
    """Run a single scope exploration under concurrency + timeout control."""
    if tracker and node_id:
        tracker.set_state(node_id, AgentState.waiting, "awaiting semaphore")
    async with sem:
        if tracker and node_id:
            tracker.set_state(node_id, AgentState.running)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(explore_scope, plan, repo_root),
                timeout=timeout,
            )
            if llm_client and result.error is None:
                result = await enrich_scope_with_llm(result, repo_root, llm_client)
            if tracker and node_id:
                tracker.set_state(node_id, AgentState.done)
            return result
        except asyncio.TimeoutError:
            if tracker and node_id:
                tracker.set_state(node_id, AgentState.error, f"timeout {timeout}s")
            return ScopeResult(
                scope_id=plan.scope_id,
                title=plan.title,
                paths=plan.paths,
                error=f"Timed out after {timeout}s",
            )
        except Exception:
            if tracker and node_id:
                tracker.set_state(node_id, AgentState.error)
            return ScopeResult(
                scope_id=plan.scope_id,
                title=plan.title,
                paths=plan.paths,
                error=traceback.format_exc(limit=4),
            )


async def run_async(
    repo_path: Path,
    output_base: Path | None = None,
    max_scopes: int = 20,
    concurrency: int = 4,
    timeout: float = 120.0,
    llm_client: LLMClient | None = None,
    tracker: NoOpTracker | None = None,
) -> Path:
    """Full pipeline: scan -> plan -> explore -> reduce -> render.

    When llm_client is provided, LLM is used at EVERY step:
    - Planner: refines scope titles, notes, groupings
    - Explorer: generates per-scope summaries
    - Reducer: writes cross-scope analysis + Mermaid architecture graph
    - Renderer: writes per-scope docs, README, and architecture overview
    """
    repo_path = repo_path.resolve()
    if output_base is None:
        output_base = Path.cwd() / "runs"

    if tracker is None:
        tracker = NoOpTracker()

    run_id = _make_run_id()
    run_dir = output_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = RunMeta(
        run_id=run_id,
        repo_path=str(repo_path),
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    using_llm = llm_client is not None
    if using_llm:
        console.print(f"[bold]LLM:[/bold] {llm_client.model} via OpenRouter (used at every step)")
    else:
        console.print("[dim]No LLM configured; using template-only mode.[/dim]")

    # Register extractors (Python AST, tree-sitter, LLM fallback).
    setup_extractors(llm_client=llm_client)

    # -- Build tracker tree skeleton --
    tracker.add_node("orchestrator", "Orchestrator")
    tracker.add_node("scanner", "Scanner", "orchestrator")
    tracker.add_node("planner", "Planner", "orchestrator")
    tracker.add_node("explorer_hub", "Explorer Hub", "orchestrator")
    tracker.add_node("reducer", "Reducer", "orchestrator")
    tracker.add_node("renderer", "Renderer", "orchestrator")

    tracker.set_state("orchestrator", AgentState.running)

    # 1. Scan
    console.print(f"[bold]Scanning[/bold] {repo_path} ...")
    tracker.set_state("scanner", AgentState.running)
    scan = await asyncio.to_thread(scan_repo, repo_path)
    tracker.set_state("scanner", AgentState.done, f"{len(scan.py_files)} files")
    console.print(f"  Found {len(scan.py_files)} Python file(s), {len(scan.packages)} package(s), {len(scan.entrypoints)} entrypoint(s).")

    if not scan.py_files:
        console.print("[yellow]No Python files found. Nothing to do.[/yellow]")
        tracker.set_state("orchestrator", AgentState.done)
        return run_dir

    # 2. Plan (+ LLM refinement)
    console.print("[bold]Planning[/bold] scopes ...")
    tracker.set_state("planner", AgentState.running)
    plans = await asyncio.to_thread(build_plan, scan, max_scopes)
    if using_llm:
        console.print("  Refining plan with LLM ...")
        plans = await refine_plan_with_llm(plans, scan, max_scopes, llm_client)
    meta.scope_count = len(plans)
    tracker.set_state("planner", AgentState.done, f"{len(plans)} scopes")
    console.print(f"  Created {len(plans)} scope(s).")

    plan_path = run_dir / "plan.json"
    plan_path.write_text(
        json.dumps([p.model_dump() for p in plans], indent=2),
        encoding="utf-8",
    )

    # 3. Explore in parallel (+ LLM summaries)
    sem = asyncio.Semaphore(concurrency)
    tracker.set_state("explorer_hub", AgentState.running)

    # Add a child node per scope
    for p in plans:
        nid = f"explorer.{p.scope_id}"
        tracker.add_node(nid, p.title, "explorer_hub")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        label = "Exploring scopes" + (" (+ LLM summaries)" if using_llm else "")
        task = progress.add_task(label, total=len(plans))

        async def _run_and_track(plan: ScopePlan) -> ScopeResult:
            nid = f"explorer.{plan.scope_id}"
            result = await _explore_one(
                plan, repo_path, sem, timeout, llm_client,
                tracker=tracker, node_id=nid,
            )
            progress.advance(task)
            return result

        scope_results: list[ScopeResult] = list(
            await asyncio.gather(*[_run_and_track(p) for p in plans])
        )

    tracker.set_state("explorer_hub", AgentState.done)

    scopes_dir = run_dir / "scopes"
    scopes_dir.mkdir(exist_ok=True)
    for sr in scope_results:
        (scopes_dir / f"{sr.scope_id}.json").write_text(
            sr.model_dump_json(indent=2), encoding="utf-8",
        )

    succeeded = sum(1 for r in scope_results if r.error is None)
    failed = len(scope_results) - succeeded
    meta.succeeded = succeeded
    meta.failed = failed

    if failed:
        console.print(f"  [yellow]{failed} scope(s) failed.[/yellow]")
    console.print(f"  [green]{succeeded}/{len(scope_results)} scope(s) succeeded.[/green]")

    # 4. Reduce (+ LLM cross-scope analysis + Mermaid)
    console.print("[bold]Reducing[/bold] scope results ...")
    tracker.set_state("reducer", AgentState.running)
    if using_llm:
        tracker.add_node("reducer.analysis", "Analysis", "reducer")
        tracker.add_node("reducer.mermaid", "Mermaid graph", "reducer")
        tracker.set_state("reducer.analysis", AgentState.running)
        tracker.set_state("reducer.mermaid", AgentState.running)
        console.print("  Generating cross-scope analysis and architecture graph with LLM ...")
        docs_index = await reduce_with_llm(scope_results, str(repo_path), llm_client)
        tracker.set_state("reducer.analysis", AgentState.done)
        tracker.set_state("reducer.mermaid", AgentState.done)
    else:
        docs_index = await asyncio.to_thread(reduce, scope_results, str(repo_path))
    tracker.set_state("reducer", AgentState.done)

    index_path = run_dir / "docs_index.json"
    index_path.write_text(docs_index.model_dump_json(indent=2), encoding="utf-8")

    # 5. Render (+ LLM for all narrative docs)
    console.print("[bold]Rendering[/bold] documentation ...")
    tracker.set_state("renderer", AgentState.running)
    if using_llm:
        # Add child nodes for each scope doc, readme, and architecture
        for sr in scope_results:
            tracker.add_node(f"renderer.{sr.scope_id}", sr.title, "renderer")
        tracker.add_node("renderer.readme", "README", "renderer")
        tracker.add_node("renderer.arch", "Architecture", "renderer")

        # Set all running
        for sr in scope_results:
            tracker.set_state(f"renderer.{sr.scope_id}", AgentState.running)
        tracker.set_state("renderer.readme", AgentState.running)
        tracker.set_state("renderer.arch", AgentState.running)

        console.print("  Writing all docs with LLM ...")
        written = await render_with_llm(docs_index, run_dir, llm_client)

        for sr in scope_results:
            tracker.set_state(f"renderer.{sr.scope_id}", AgentState.done)
        tracker.set_state("renderer.readme", AgentState.done)
        tracker.set_state("renderer.arch", AgentState.done)
    else:
        written = await asyncio.to_thread(render, docs_index, run_dir)
    tracker.set_state("renderer", AgentState.done)

    for w in written:
        console.print(f"  wrote {w.relative_to(run_dir)}")

    meta.finished_at = datetime.now(timezone.utc).isoformat()
    (run_dir / "run_meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    tracker.set_state("orchestrator", AgentState.done)
    console.print(f"\n[bold green]Done![/bold green] Output in: {run_dir}")
    return run_dir
