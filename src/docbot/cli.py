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
    help="Generate thorough documentation for a Python repository.",
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
    repo: Path = typer.Argument(..., help="Path to the target Python repository."),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Base directory for run output (default: ./runs)."),
    max_scopes: int = typer.Option(20, "--max-scopes", help="Maximum number of documentation scopes."),
    concurrency: int = typer.Option(4, "--concurrency", "-j", help="Maximum parallel explorer workers."),
    timeout: float = typer.Option(120.0, "--timeout", "-t", help="Per-scope timeout in seconds."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="OpenRouter model ID."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM calls; use template-only mode."),
) -> None:
    """Scan, explore, and generate documentation for REPO."""
    repo = Path(repo).resolve()
    if not repo.is_dir():
        console.print(f"[red]Error:[/red] {repo} is not a directory.")
        raise typer.Exit(code=1)

    # Try loading .env from cwd (or parents) before checking for the key.
    _load_dotenv(Path.cwd())

    from .llm import LLMClient
    from .orchestrator import run_async

    # Build LLM client if key is available and not disabled.
    llm_client = None
    if not no_llm:
        api_key = os.environ.get("OPENROUTER_KEY", "").strip()
        if api_key:
            llm_client = LLMClient(api_key=api_key, model=model)
        else:
            console.print("[yellow]OPENROUTER_KEY not set. Running in template-only mode.[/yellow]")
            console.print("[dim]Set OPENROUTER_KEY or pass --no-llm to suppress this warning.[/dim]")

    asyncio.run(run_async(
        repo_path=repo,
        output_base=output,
        max_scopes=max_scopes,
        concurrency=concurrency,
        timeout=timeout,
        llm_client=llm_client,
    ))


if __name__ == "__main__":
    app()
