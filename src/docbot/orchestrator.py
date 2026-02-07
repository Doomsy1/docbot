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
    _work_fn=None,
) -> ScopeResult:
    """Run a single scope exploration under concurrency + timeout control.

    When *_work_fn* is provided (an async callable accepting a ScopePlan and
    returning a ScopeResult), it replaces the real explore_scope + LLM call.
    This lets ``--mock-viz`` reuse the semaphore/timeout/tracker logic.
    """
    if tracker and node_id:
        tracker.set_state(node_id, AgentState.waiting, "awaiting semaphore")
    async with sem:
        if tracker and node_id:
            tracker.set_state(node_id, AgentState.running)
        try:
            if _work_fn is not None:
                result = await asyncio.wait_for(_work_fn(plan), timeout=timeout)
            else:
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


async def _run_scan(
    repo_path: Path,
    tracker: NoOpTracker,
    mock: bool = False,
) -> tuple:
    """Stage 1: Scan repository for source files."""
    console.print(f"[bold]Scanning[/bold] {repo_path} ...")
    tracker.set_state("scanner", AgentState.running)
    if mock:
        from . import mock_viz
        await asyncio.sleep(1.5)
        scan = mock_viz.mock_scan(repo_path)
    else:
        scan = await asyncio.to_thread(scan_repo, repo_path)
    tracker.set_state("scanner", AgentState.done, f"{len(scan.source_files)} files")

    # Show per-language file counts.
    if scan.languages:
        from collections import Counter
        lang_counts = Counter(sf.language for sf in scan.source_files)
        breakdown = ", ".join(f"{count} {lang}" for lang, count in sorted(lang_counts.items()))
        console.print(f"  Found {len(scan.source_files)} source file(s) ({breakdown}), "
                       f"{len(scan.packages)} package(s), {len(scan.entrypoints)} entrypoint(s).")
        console.print(f"  Languages: {', '.join(scan.languages)}")
    else:
        console.print(f"  Found {len(scan.source_files)} source file(s), "
                       f"{len(scan.packages)} package(s), {len(scan.entrypoints)} entrypoint(s).")

    return scan


async def _run_plan(
    scan,
    max_scopes: int,
    llm_client: LLMClient | None,
    tracker: NoOpTracker,
    mock: bool = False,
    meta: RunMeta | None = None,
) -> list[ScopePlan]:
    """Stage 2: Build and optionally refine scope plan."""
    using_llm = llm_client is not None
    console.print("[bold]Planning[/bold] scopes ...")
    tracker.set_state("planner", AgentState.running)
    if mock:
        from . import mock_viz
        await asyncio.sleep(2.0)
        plans = mock_viz.mock_plans()
    else:
        plans = await asyncio.to_thread(build_plan, scan, max_scopes)
        if using_llm:
            console.print("  Refining plan with LLM ...")
            plans = await refine_plan_with_llm(plans, scan, max_scopes, llm_client)
        if meta:
            meta.scope_count = len(plans)
    tracker.set_state("planner", AgentState.done, f"{len(plans)} scopes")
    console.print(f"  Created {len(plans)} scope(s).")
    return plans


async def _run_explore(
    plans: list[ScopePlan],
    repo_path: Path,
    concurrency: int,
    timeout: float,
    llm_client: LLMClient | None,
    tracker: NoOpTracker,
    mock: bool = False,
) -> list[ScopeResult]:
    """Stage 3: Explore scopes in parallel."""
    using_llm = llm_client is not None
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
            from . import mock_viz
            nid = f"explorer.{plan.scope_id}"
            result = await _explore_one(
                plan, repo_path, sem, timeout, llm_client,
                tracker=tracker, node_id=nid,
                _work_fn=mock_viz.mock_explore_work if mock else None,
            )
            progress.advance(task)
            return result

        scope_results: list[ScopeResult] = list(
            await asyncio.gather(*[_run_and_track(p) for p in plans])
        )

    tracker.set_state("explorer_hub", AgentState.done)
    return scope_results


async def _run_reduce(
    scope_results: list[ScopeResult],
    repo_path: str,
    llm_client: LLMClient | None,
    tracker: NoOpTracker,
    mock: bool = False,
) -> DocsIndex:
    """Stage 4: Reduce scope results into unified docs index."""
    using_llm = llm_client is not None
    console.print("[bold]Reducing[/bold] scope results ...")
    tracker.set_state("reducer", AgentState.running)
    if using_llm:
        tracker.add_node("reducer.analysis", "Analysis", "reducer")
        tracker.add_node("reducer.mermaid", "Mermaid graph", "reducer")
        tracker.set_state("reducer.analysis", AgentState.running)
        tracker.set_state("reducer.mermaid", AgentState.running)
        if mock:
            from . import mock_viz
            await asyncio.sleep(2.5)
            docs_index = mock_viz.mock_docs_index(scope_results, repo_path)
        else:
            console.print("  Generating cross-scope analysis and architecture graph with LLM ...")
            docs_index = await reduce_with_llm(scope_results, repo_path, llm_client)
        tracker.set_state("reducer.analysis", AgentState.done)
        tracker.set_state("reducer.mermaid", AgentState.done)
    else:
        docs_index = await asyncio.to_thread(reduce, scope_results, repo_path)
    tracker.set_state("reducer", AgentState.done)
    return docs_index


async def _run_render(
    docs_index: DocsIndex,
    scope_results: list[ScopeResult],
    output_dir: Path,
    llm_client: LLMClient | None,
    tracker: NoOpTracker,
    mock: bool = False,
) -> list[Path]:
    """Stage 5: Render documentation files."""
    using_llm = llm_client is not None
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

        if mock:
            await asyncio.sleep(2.0)
            written = []
        else:
            console.print("  Writing all docs with LLM ...")
            written = await render_with_llm(docs_index, output_dir, llm_client)

        for sr in scope_results:
            tracker.set_state(f"renderer.{sr.scope_id}", AgentState.done)
        tracker.set_state("renderer.readme", AgentState.done)
        tracker.set_state("renderer.arch", AgentState.done)
    else:
        written = await asyncio.to_thread(render, docs_index, output_dir)
    tracker.set_state("renderer", AgentState.done)

    for w in written:
        console.print(f"  wrote {w.relative_to(output_dir)}")
    
    return written


async def run_async(
    repo_path: Path,
    output_base: Path | None = None,
    max_scopes: int = 20,
    concurrency: int = 4,
    timeout: float = 120.0,
    llm_client: LLMClient | None = None,
    tracker: NoOpTracker | None = None,
    mock: bool = False,
) -> Path:
    """Full pipeline: scan -> plan -> explore -> reduce -> render.

    When llm_client is provided, LLM is used at EVERY step:
    - Planner: refines scope titles, notes, groupings
    - Explorer: generates per-scope summaries
    - Reducer: writes cross-scope analysis + Mermaid architecture graph
    - Renderer: writes per-scope docs, README, and architecture overview

    When *mock* is True the pipeline replays a simulated run with
    ``asyncio.sleep()`` delays -- no file I/O, no LLM calls.  All tracker
    state transitions are driven by the same code paths used for real runs.
    """
    if mock:
        from . import mock_viz
        import tempfile
        await asyncio.sleep(3.0)  # let the browser load D3 from CDN
        using_llm = True  # so we exercise the full tracker tree
        timeout = mock_viz.MOCK_TIMEOUT
        run_dir = Path(tempfile.mkdtemp(prefix="docbot_mock_"))
        console.print("[dim]Mock mode -- simulated pipeline, no LLM calls.[/dim]")
    else:
        repo_path = repo_path.resolve()
        if output_base is None:
            output_base = Path.cwd() / "runs"
        run_id = _make_run_id()
        run_dir = output_base / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        using_llm = llm_client is not None
        if using_llm:
            console.print(f"[bold]LLM:[/bold] {llm_client.model} via OpenRouter (used at every step)")
        else:
            console.print("[dim]No LLM configured; using template-only mode.[/dim]")
        # Register extractors (Python AST, tree-sitter, LLM fallback).
        setup_extractors(llm_client=llm_client)

    if tracker is None:
        tracker = NoOpTracker()

    if not mock:
        meta = RunMeta(
            run_id=run_id,
            repo_path=str(repo_path),
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    # -- Build tracker tree skeleton --
    tracker.add_node("orchestrator", "Orchestrator")
    tracker.add_node("scanner", "Scanner", "orchestrator")
    tracker.add_node("planner", "Planner", "orchestrator")
    tracker.add_node("explorer_hub", "Explorer Hub", "orchestrator")
    tracker.add_node("reducer", "Reducer", "orchestrator")
    tracker.add_node("renderer", "Renderer", "orchestrator")

    tracker.set_state("orchestrator", AgentState.running)

    # 1. Scan
    scan = await _run_scan(repo_path, tracker, mock)

    if not scan.source_files:
        console.print("[yellow]No source files found. Nothing to do.[/yellow]")
        tracker.set_state("orchestrator", AgentState.done)
        return run_dir

    # 2. Plan (+ LLM refinement)
    plans = await _run_plan(scan, max_scopes, llm_client, tracker, mock, meta if not mock else None)

    if not mock:
        plan_path = run_dir / "plan.json"
        plan_path.write_text(
            json.dumps([p.model_dump() for p in plans], indent=2),
            encoding="utf-8",
        )

    # 3. Explore in parallel (+ LLM summaries)
    scope_results = await _run_explore(plans, repo_path, concurrency, timeout, llm_client, tracker, mock)

    if not mock:
        scopes_dir = run_dir / "scopes"
        scopes_dir.mkdir(exist_ok=True)
        for sr in scope_results:
            (scopes_dir / f"{sr.scope_id}.json").write_text(
                sr.model_dump_json(indent=2), encoding="utf-8",
            )

    succeeded = sum(1 for r in scope_results if r.error is None)
    failed = len(scope_results) - succeeded
    if not mock:
        meta.succeeded = succeeded
        meta.failed = failed

    if failed:
        console.print(f"  [yellow]{failed} scope(s) failed.[/yellow]")
    console.print(f"  [green]{succeeded}/{len(scope_results)} scope(s) succeeded.[/green]")

    # 4. Reduce (+ LLM cross-scope analysis + Mermaid)
    docs_index = await _run_reduce(scope_results, str(repo_path), llm_client, tracker, mock)

    if not mock:
        index_path = run_dir / "docs_index.json"
        index_path.write_text(docs_index.model_dump_json(indent=2), encoding="utf-8")

    # 5. Render (+ LLM for all narrative docs)
    written = await _run_render(docs_index, scope_results, run_dir, llm_client, tracker, mock)

    if not mock:
        meta.finished_at = datetime.now(timezone.utc).isoformat()
        (run_dir / "run_meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    tracker.set_state("orchestrator", AgentState.done)
    console.print(f"\n[bold green]Done![/bold green] Output in: {run_dir}")
    return run_dir
