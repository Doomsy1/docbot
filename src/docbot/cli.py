"""CLI entry point for docbot."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from .llm import DEFAULT_MODEL

app = typer.Typer(
    name="docbot",
    help="Generate thorough documentation for a repository.",
    add_completion=False,
)
console = Console()


def _load_dotenv(start_dir: Path) -> None:
    """Load a .env file from *start_dir* (or parents) into os.environ.

    Only sets vars that are not already present in the environment.
    Handles KEY=VALUE lines, ignores comments and blank lines.
    """
    search = start_dir.resolve()
    for d in [search, *search.parents]:
        candidate = d / ".env"
        if candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            except OSError:
                pass
            return  # stop after the first .env found


@app.command()
def run(
    repo: Path = typer.Argument(..., help="Path to the target repository."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Base directory for run output (default: ./runs)."),
    max_scopes: int = typer.Option(20, "--max-scopes", help="Maximum number of documentation scopes."),
    concurrency: int = typer.Option(4, "--concurrency", "-j", help="Maximum parallel explorer workers."),
    timeout: float = typer.Option(120.0, "--timeout", "-t", help="Per-scope timeout in seconds."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="OpenRouter model ID."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM enrichment; AST/tree-sitter extraction still runs."),
    visualize: bool = typer.Option(False, "--visualize", "--viz", help="Open a live D3.js pipeline visualization in the browser."),
    mock_viz: bool = typer.Option(False, "--mock-viz", help="Run a mock pipeline simulation with the visualization (no LLM, no repo needed)."),
) -> None:
    """Scan, explore, and generate documentation for REPO."""

    from .orchestrator import run_async
    from .tracker import NoOpTracker, PipelineTracker

    # --mock-viz: reuses the real pipeline with sleep stubs instead of work.
    if mock_viz:
        from .viz_server import start_viz_server

        tracker = PipelineTracker()
        _server, url = start_viz_server(tracker)
        console.print(f"[bold cyan]Mock visualization:[/bold cyan] {url}")
        asyncio.run(run_async(
            repo_path=repo,
            concurrency=concurrency,
            tracker=tracker,
            mock=True,
        ))
        console.print("[dim]Simulation complete. Press Enter to exit.[/dim]")
        input()
        return

    repo = Path(repo).resolve()
    if not repo.is_dir():
        console.print(f"[red]Error:[/red] {repo} is not a directory.")
        raise typer.Exit(code=1)

    # Try loading .env from cwd (or parents) before checking for the key.
    _load_dotenv(Path.cwd())

    from .llm import LLMClient

    # Build LLM client if key is available and not disabled.
    llm_client = None
    if not no_llm:
        api_key = os.environ.get("OPENROUTER_KEY", "").strip()
        if api_key:
            llm_client = LLMClient(api_key=api_key, model=model)
        else:
            console.print("[yellow]OPENROUTER_KEY not set. Running in template-only mode.[/yellow]")
            console.print("[dim]Set OPENROUTER_KEY or pass --no-llm to suppress this warning.[/dim]")

    # Set up visualization tracker.
    tracker: PipelineTracker | NoOpTracker
    if visualize:
        from .viz_server import start_viz_server

        tracker = PipelineTracker()
        _server, url = start_viz_server(tracker)
        console.print(f"[bold cyan]Visualization:[/bold cyan] {url}")
    else:
        tracker = NoOpTracker()

    asyncio.run(run_async(
        repo_path=repo,
        output_base=output,
        max_scopes=max_scopes,
        concurrency=concurrency,
        timeout=timeout,
        llm_client=llm_client,
        tracker=tracker,
    ))

    if visualize:
        console.print("[dim]Visualization server still running. Press Enter to exit.[/dim]")
        input()


@app.command()
def serve(
    path: Path = typer.Argument(..., help="Path to a run directory or a repository to analyze then serve."),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8000, "--port", "-p", help="Port number."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="OpenRouter model ID (for chat & tours)."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser."),
) -> None:
    """Launch the interactive webapp to explore a completed run.

    PATH can be a docbot run directory (containing docs_index.json) or a
    repository — in which case docbot runs analysis first, then serves.
    """
    path = Path(path).resolve()
    if not path.is_dir():
        console.print(f"[red]Error:[/red] {path} is not a directory.")
        raise typer.Exit(code=1)

    _load_dotenv(Path.cwd())

    # Determine if this is a run directory or a repo to analyze.
    run_dir = _resolve_run_dir(path)

    if run_dir is None:
        # Looks like a repo — run analysis first.
        console.print(f"[bold]No docs_index.json found — running analysis on[/bold] {path}")
        from .orchestrator import run_async

        from .llm import LLMClient

        llm_client = None
        api_key = os.environ.get("OPENROUTER_KEY", "").strip()
        if api_key:
            llm_client = LLMClient(api_key=api_key, model=model)
        else:
            console.print("[yellow]OPENROUTER_KEY not set. Running in template-only mode.[/yellow]")

        run_dir = asyncio.run(run_async(repo_path=path, llm_client=llm_client))
        console.print()

    # Build LLM client for chat/tours.
    from .llm import LLMClient

    llm_client = None
    api_key = os.environ.get("OPENROUTER_KEY", "").strip()
    if api_key:
        llm_client = LLMClient(api_key=api_key, model=model)

    from .server import start_server

    url = f"http://{host}:{port}"
    console.print(f"[bold cyan]Serving[/bold cyan] {run_dir}")
    console.print(f"  {url}")

    if not no_browser:
        import webbrowser
        # Open after a short delay to let the server start.
        import threading
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    start_server(run_dir, host=host, port=port, llm_client=llm_client)


def _resolve_run_dir(path: Path) -> Path | None:
    """Check if *path* is or contains a docbot run directory. Returns None if not."""
    if (path / "docs_index.json").exists():
        return path

    # Check for timestamped run subdirectories.
    candidates = sorted(
        [d for d in path.iterdir() if d.is_dir() and (d / "docs_index.json").exists()]
    )
    if candidates:
        latest = candidates[-1]
        console.print(f"[yellow]Using latest run:[/yellow] {latest.name}")
        return latest

    return None


if __name__ == "__main__":
    app()
