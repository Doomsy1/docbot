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
from .llm import LLMClient
from .models import DocsIndex, RunMeta, ScopePlan, ScopeResult
from .planner import build_plan, refine_plan_with_llm
from .reducer import reduce, reduce_with_llm
from .renderer import render, render_with_llm
from .scanner import scan_repo

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
) -> ScopeResult:
    """Run a single scope exploration under concurrency + timeout control."""
    async with sem:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(explore_scope, plan, repo_root),
                timeout=timeout,
            )
            if llm_client and result.error is None:
                result = await enrich_scope_with_llm(result, repo_root, llm_client)
            return result
        except asyncio.TimeoutError:
            return ScopeResult(
                scope_id=plan.scope_id,
                title=plan.title,
                paths=plan.paths,
                error=f"Timed out after {timeout}s",
            )
        except Exception:
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

    # 1. Scan
    console.print(f"[bold]Scanning[/bold] {repo_path} ...")
    scan = await asyncio.to_thread(scan_repo, repo_path)
    console.print(f"  Found {len(scan.py_files)} Python file(s), {len(scan.packages)} package(s), {len(scan.entrypoints)} entrypoint(s).")

    if not scan.py_files:
        console.print("[yellow]No Python files found. Nothing to do.[/yellow]")
        return run_dir

    # 2. Plan (+ LLM refinement)
    console.print("[bold]Planning[/bold] scopes ...")
    plans = await asyncio.to_thread(build_plan, scan, max_scopes)
    if using_llm:
        console.print("  Refining plan with LLM ...")
        plans = await refine_plan_with_llm(plans, scan, max_scopes, llm_client)
    meta.scope_count = len(plans)
    console.print(f"  Created {len(plans)} scope(s).")

    plan_path = run_dir / "plan.json"
    plan_path.write_text(
        json.dumps([p.model_dump() for p in plans], indent=2),
        encoding="utf-8",
    )

    # 3. Explore in parallel (+ LLM summaries)
    sem = asyncio.Semaphore(concurrency)

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
            result = await _explore_one(plan, repo_path, sem, timeout, llm_client)
            progress.advance(task)
            return result

        scope_results: list[ScopeResult] = list(
            await asyncio.gather(*[_run_and_track(p) for p in plans])
        )

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
    if using_llm:
        console.print("  Generating cross-scope analysis and architecture graph with LLM ...")
        docs_index = await reduce_with_llm(scope_results, str(repo_path), llm_client)
    else:
        docs_index = await asyncio.to_thread(reduce, scope_results, str(repo_path))

    index_path = run_dir / "docs_index.json"
    index_path.write_text(docs_index.model_dump_json(indent=2), encoding="utf-8")

    # 5. Render (+ LLM for all narrative docs)
    console.print("[bold]Rendering[/bold] documentation ...")
    if using_llm:
        console.print("  Writing all docs with LLM ...")
        written = await render_with_llm(docs_index, run_dir, llm_client)
    else:
        written = await asyncio.to_thread(render, docs_index, run_dir)
    for w in written:
        console.print(f"  wrote {w.relative_to(run_dir)}")

    meta.finished_at = datetime.now(timezone.utc).isoformat()
    (run_dir / "run_meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

    console.print(f"\n[bold green]Done![/bold green] Output in: {run_dir}")
    return run_dir
