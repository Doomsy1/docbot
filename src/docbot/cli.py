"""CLI entry point for docbot -- git-integrated documentation tool."""

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
    help="Git-integrated documentation generator for any codebase.",
    add_completion=False,
)

hook_app = typer.Typer(help="Manage git hooks for automatic doc updates.")
app.add_typer(hook_app, name="hook")

console = Console()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


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


def _require_docbot(path: Path | None = None) -> tuple[Path, Path]:
    """Locate .docbot/ or exit with an error.

    Returns ``(project_root, docbot_dir)`` where *docbot_dir* is the
    ``.docbot/`` directory and *project_root* is its parent.
    """
    from .project import find_docbot_root

    start = Path(path).resolve() if path else Path.cwd()
    project_root = find_docbot_root(start)
    if project_root is None:
        console.print(
            "[red]Error:[/red] No .docbot/ directory found. "
            "Run [bold]docbot init[/bold] first."
        )
        raise typer.Exit(code=1)
    return project_root, project_root / ".docbot"


def _build_llm_client(
    model: str = DEFAULT_MODEL,
    no_llm: bool = False,
    *,
    quiet: bool = False,
):
    """Build an LLM client (or None) from environment + flags."""
    from .llm import LLMClient

    if no_llm:
        return None
    api_key = os.environ.get("OPENROUTER_KEY", "").strip()
    if api_key:
        return LLMClient(api_key=api_key, model=model)
    if not quiet:
        console.print(
            "[yellow]OPENROUTER_KEY not set. Running in template-only mode.[/yellow]"
        )
        console.print(
            "[dim]Set OPENROUTER_KEY or pass --no-llm to suppress this warning.[/dim]"
        )
    return None


def _resolve_run_dir(path: Path) -> Path | None:
    """Check if *path* is or contains a docbot run directory.

    Also checks for a .docbot/ directory.  Returns None if not found.
    """
    # Direct docs_index.json in the path.
    if (path / "docs_index.json").exists():
        return path

    # .docbot/ directory.
    if (path / ".docbot" / "docs_index.json").exists():
        return path / ".docbot"

    # Timestamped run subdirectories (legacy runs/ layout).
    candidates = sorted(
        [d for d in path.iterdir() if d.is_dir() and (d / "docs_index.json").exists()]
    )
    if candidates:
        latest = candidates[-1]
        console.print(f"[yellow]Using latest run:[/yellow] {latest.name}")
        return latest

    return None


def _ensure_webapp_built() -> None:
    """Build the webapp if the dist folder doesn't exist."""
    import subprocess
    import sys
    import shutil

    here = Path(__file__).parent.resolve()
    potential_dists = [
        here / "web_dist",  # Bundled package
        here.parents[1] / "webapp" / "dist",  # Editable/source checkout
    ]

    # Check if dist already exists
    for p in potential_dists:
        if p.exists() and (p / "index.html").exists():
            return  # Already built

    # Find webapp source directory
    webapp_dir = here.parents[1] / "webapp"
    if not (webapp_dir / "package.json").exists():
        console.print(
            "[yellow]Warning: webapp source not found. Skipping auto-build.[/yellow]"
        )
        return

    # Check for node_modules
    node_modules = webapp_dir / "node_modules"
    if not node_modules.exists():
        console.print("[bold]Installing webapp dependencies...[/bold]")
        npm_exe: str | None = None
        # On Windows, npm is typically a .cmd shim (npm.cmd). Some environments
        # (or sanitized PATH/PATHEXT) can fail to resolve it when invoked from
        # subprocess with shell=False, so we explicitly probe common names.
        for candidate in (
            "npm.cmd",
            "npm.exe",
            "npm.bat",
            "npm",
        ):
            npm_exe = shutil.which(candidate)
            if npm_exe:
                break

        if npm_exe is None and os.name == "nt":
            program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            fallback = program_files / "nodejs" / "npm.cmd"
            if fallback.exists():
                npm_exe = str(fallback)

        if npm_exe is None:
            console.print(
                "[red]Error: npm not found. Please install Node.js and npm.[/red]"
            )
            sys.exit(1)

        try:
            subprocess.run(
                [npm_exe, "install"],
                cwd=str(webapp_dir),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            console.print(f"[red]Error: npm install failed:[/red] {e.stderr}")
            sys.exit(1)

    # Build the webapp
    console.print("[bold]Building webapp...[/bold]")
    npm_exe = shutil.which("npm.cmd") or shutil.which("npm.exe") or shutil.which("npm")
    if npm_exe is None and os.name == "nt":
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        fallback = program_files / "nodejs" / "npm.cmd"
        if fallback.exists():
            npm_exe = str(fallback)

    if npm_exe is None:
        console.print("[red]Error: npm not found. Please install Node.js and npm.[/red]")
        sys.exit(1)

    try:
        subprocess.run(
            [npm_exe, "run", "build"],
            cwd=str(webapp_dir),
            check=True,
            capture_output=True,
            text=True,
        )
        console.print("[green]Webapp built successfully![/green]")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Error: npm run build failed:[/red] {e.stderr}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    path: Optional[Path] = typer.Argument(
        None, help="Repository path (default: current directory)."
    ),
) -> None:
    """Initialise a .docbot/ directory in a git repository."""
    from .project import init_project

    target = Path(path).resolve() if path else Path.cwd()

    try:
        docbot_dir = init_project(target)
    except FileExistsError:
        console.print(f"[yellow]Already initialised:[/yellow] {target / '.docbot'}")
        raise typer.Exit(code=0)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]Initialised[/green] {docbot_dir}")
    console.print("  Run [bold]docbot generate[/bold] to create documentation.")


@app.command()
def generate(
    path: Optional[Path] = typer.Argument(
        None, help="Repository path (default: current directory)."
    ),
    max_scopes: Optional[int] = typer.Option(
        None, "--max-scopes", help="Maximum documentation scopes."
    ),
    concurrency: Optional[int] = typer.Option(
        None, "--concurrency", "-j", help="Parallel explorer workers."
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", "-t", help="Per-scope timeout in seconds."
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="OpenRouter model ID."
    ),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM enrichment."),
    visualize: bool = typer.Option(
        False, "--visualize", "--viz", help="Open live pipeline visualization."
    ),
    mock_viz: bool = typer.Option(
        False, "--mock-viz", help="Run mock pipeline simulation."
    ),
) -> None:
    """Run the full documentation pipeline, output to .docbot/."""
    from .models import DocbotConfig
    from .orchestrator import generate_async, run_async
    from .project import load_config
    from .tracker import NoOpTracker, PipelineTracker

    project_root, docbot_dir = _require_docbot(path)
    _load_dotenv(project_root)
    cfg = load_config(docbot_dir)

    # CLI flags override config values (only when explicitly provided).
    effective_cfg = DocbotConfig(
        model=model or cfg.model,
        concurrency=concurrency if concurrency is not None else cfg.concurrency,
        timeout=timeout if timeout is not None else cfg.timeout,
        max_scopes=max_scopes if max_scopes is not None else cfg.max_scopes,
        no_llm=no_llm or cfg.no_llm,
    )

    # --mock-viz: simulated pipeline for visualization development.
    if mock_viz:
        from .viz_server import start_viz_server

        tracker = PipelineTracker()
        _server, url = start_viz_server(tracker)
        console.print(f"[bold cyan]Mock visualization:[/bold cyan] {url}")
        asyncio.run(
            run_async(
                repo_path=project_root,
                concurrency=effective_cfg.concurrency,
                tracker=tracker,
                mock=True,
            )
        )
        console.print("[dim]Simulation complete. Press Enter to exit.[/dim]")
        input()
        return

    llm_client = _build_llm_client(effective_cfg.model, effective_cfg.no_llm)

    # Set up visualization tracker.
    tracker: PipelineTracker | NoOpTracker
    if visualize:
        from .viz_server import start_viz_server

        tracker = PipelineTracker()
        _server, url = start_viz_server(tracker)
        console.print(f"[bold cyan]Visualization:[/bold cyan] {url}")
    else:
        tracker = NoOpTracker()

    if llm_client is not None:
        console.print(f"[bold]LLM:[/bold] {effective_cfg.model} via OpenRouter")

    # Run the git-aware pipeline, outputting to .docbot/.
    asyncio.run(
        generate_async(
            docbot_root=docbot_dir,
            config=effective_cfg,
            llm_client=llm_client,
            tracker=tracker,
        )
    )

    if visualize:
        console.print(
            "[dim]Visualization server still running. Press Enter to exit.[/dim]"
        )
        input()


@app.command()
def update(
    path: Optional[Path] = typer.Argument(
        None, help="Repository path (default: current directory)."
    ),
    concurrency: Optional[int] = typer.Option(
        None, "--concurrency", "-j", help="Parallel explorer workers."
    ),
    timeout: Optional[float] = typer.Option(
        None, "--timeout", "-t", help="Per-scope timeout in seconds."
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="OpenRouter model ID."
    ),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM enrichment."),
) -> None:
    """Incrementally update docs for files changed since the last documented commit."""
    from .models import DocbotConfig
    from .orchestrator import update_async
    from .project import load_config
    from .tracker import NoOpTracker

    project_root, docbot_dir = _require_docbot(path)
    _load_dotenv(project_root)
    cfg = load_config(docbot_dir)
    effective_cfg = DocbotConfig(
        model=model or cfg.model,
        concurrency=concurrency if concurrency is not None else cfg.concurrency,
        timeout=timeout if timeout is not None else cfg.timeout,
        max_scopes=cfg.max_scopes,
        no_llm=no_llm or cfg.no_llm,
    )

    llm_client = _build_llm_client(effective_cfg.model, effective_cfg.no_llm)

    asyncio.run(
        update_async(
            docbot_root=docbot_dir,
            config=effective_cfg,
            llm_client=llm_client,
            tracker=NoOpTracker(),
        )
    )


@app.command()
def status(
    path: Optional[Path] = typer.Argument(
        None, help="Repository path (default: current directory)."
    ),
) -> None:
    """Show the current documentation state."""
    from .git_utils import get_changed_files, get_current_commit
    from .project import load_config, load_state

    project_root, docbot_dir = _require_docbot(path)
    state = load_state(docbot_dir)
    cfg = load_config(docbot_dir)

    if not state.last_commit:
        console.print("[yellow]No documentation generated yet.[/yellow]")
        console.print("  Run [bold]docbot generate[/bold] to get started.")
        return

    console.print(f"[bold]Last documented commit:[/bold] {state.last_commit[:12]}")
    if state.last_run_at:
        console.print(f"[bold]Last run:[/bold]              {state.last_run_at}")
    console.print(f"[bold]Scopes:[/bold]                {len(state.scope_file_map)}")
    console.print(f"[bold]Model:[/bold]                 {cfg.model}")

    # Check what has changed since.
    current = get_current_commit(project_root)
    if current and current != state.last_commit:
        changed = get_changed_files(project_root, state.last_commit)
        if changed:
            # Map to affected scopes.
            affected: set[str] = set()
            for f in changed:
                for scope_id, paths in state.scope_file_map.items():
                    if f in paths:
                        affected.add(scope_id)

            console.print()
            console.print(
                f"[yellow]{len(changed)} file(s) changed since last run:[/yellow]"
            )
            for f in changed[:15]:
                console.print(f"  {f}")
            if len(changed) > 15:
                console.print(f"  ... and {len(changed) - 15} more")
            console.print(
                f"\n  {len(affected)}/{len(state.scope_file_map)} scope(s) would need updating."
            )
            console.print("  Run [bold]docbot update[/bold] to refresh.")
        else:
            console.print("\n[green]Documentation is up to date.[/green]")
    elif current == state.last_commit:
        console.print("\n[green]Documentation is up to date.[/green]")


@app.command()
def serve(
    path: Optional[Path] = typer.Argument(
        None, help="Path to .docbot/, run directory, or repository."
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address."),
    port: int = typer.Option(8000, "--port", "-p", help="Port number."),
    model: str = typer.Option(
        DEFAULT_MODEL, "--model", "-m", help="OpenRouter model ID (for chat)."
    ),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="Don't auto-open browser."
    ),
) -> None:
    """Launch the interactive webapp to explore documentation.

    Defaults to the .docbot/ directory in the current project.
    Also accepts a run directory or repository path.
    """
    _load_dotenv(Path.cwd())

    # Determine the run directory to serve from.
    run_dir: Path | None = None

    if path is not None:
        resolved = Path(path).resolve()
        if not resolved.is_dir():
            console.print(f"[red]Error:[/red] {resolved} is not a directory.")
            raise typer.Exit(code=1)
        run_dir = _resolve_run_dir(resolved)
    else:
        # Default: try to find .docbot/ in the current project.
        from .project import find_docbot_root

        project_root = find_docbot_root(Path.cwd())
        if project_root and (project_root / ".docbot" / "docs_index.json").exists():
            run_dir = project_root / ".docbot"

    if run_dir is None:
        if path is not None:
            # Path was given but no docs found -- run analysis first.
            resolved = Path(path).resolve()
            console.print(
                f"[bold]No docs found -- running analysis on[/bold] {resolved}"
            )
            from .orchestrator import run_async

            llm_client = _build_llm_client(model)
            run_dir = asyncio.run(run_async(repo_path=resolved, llm_client=llm_client))
            console.print()
        else:
            console.print(
                "[red]Error:[/red] No .docbot/ directory or docs_index.json found.\n"
                "  Run [bold]docbot init[/bold] and [bold]docbot generate[/bold] first,\n"
                "  or pass a path to a run directory."
            )
            raise typer.Exit(code=1)

    llm_client = _build_llm_client(model, quiet=True)

    # Ensure webapp is built before starting server
    _ensure_webapp_built()

    from .server import start_server

    url = f"http://{host}:{port}"
    console.print(f"[bold cyan]Serving[/bold cyan] {run_dir}")
    console.print(f"  {url}")

    if not no_browser:
        import threading
        import webbrowser

        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    start_server(run_dir, host=host, port=port, llm_client=llm_client)


@app.command()
def config(
    key: Optional[str] = typer.Argument(None, help="Config key to get or set."),
    value: Optional[str] = typer.Argument(None, help="New value (omit to read)."),
    path: Optional[Path] = typer.Option(None, "--path", help="Repository path."),
) -> None:
    """View or modify .docbot/config.toml settings."""
    from .project import load_config, save_config

    _project_root, docbot_dir = _require_docbot(path)

    cfg = load_config(docbot_dir)

    if key is None:
        # Print all config.
        console.print("[bold]docbot config:[/bold]")
        for field_name in cfg.model_fields:
            console.print(f"  {field_name} = {getattr(cfg, field_name)!r}")
        return

    if key not in cfg.model_fields:
        console.print(
            f"[red]Error:[/red] Unknown config key [bold]{key}[/bold].\n"
            f"  Valid keys: {', '.join(cfg.model_fields)}"
        )
        raise typer.Exit(code=1)

    if value is None:
        # Print single value.
        console.print(f"{key} = {getattr(cfg, key)!r}")
        return

    # Set value -- coerce to the correct type.
    field_info = cfg.model_fields[key]
    field_type = field_info.annotation
    try:
        if field_type is bool or field_type == (bool | None):
            coerced = value.lower() in ("true", "1", "yes")
        elif field_type is int or field_type == (int | None):
            coerced = int(value)
        elif field_type is float or field_type == (float | None):
            coerced = float(value)
        else:
            coerced = value
    except (ValueError, TypeError):
        console.print(f"[red]Error:[/red] Cannot convert {value!r} to {field_type}")
        raise typer.Exit(code=1)

    setattr(cfg, key, coerced)
    save_config(docbot_dir, cfg)
    console.print(f"[green]Updated:[/green] {key} = {coerced!r}")


# ---------------------------------------------------------------------------
# Hook subcommands
# ---------------------------------------------------------------------------


@hook_app.command("install")
def hook_install(
    path: Optional[Path] = typer.Argument(
        None, help="Repository path (default: current directory)."
    ),
) -> None:
    """Install a post-commit git hook that runs 'docbot update'."""
    from .hooks import install_hook

    project_root, _docbot_dir = _require_docbot(path)

    if install_hook(project_root):
        console.print("[green]Post-commit hook installed.[/green]")
        console.print("  Docs will auto-update on each commit.")
    else:
        console.print("[red]Error:[/red] Could not install hook (is this a git repo?).")
        raise typer.Exit(code=1)


@hook_app.command("uninstall")
def hook_uninstall(
    path: Optional[Path] = typer.Argument(
        None, help="Repository path (default: current directory)."
    ),
) -> None:
    """Remove the docbot post-commit hook."""
    from .hooks import uninstall_hook

    project_root, _docbot_dir = _require_docbot(path)

    if uninstall_hook(project_root):
        console.print("[green]Post-commit hook removed.[/green]")
    else:
        console.print("[yellow]No docbot hook found to remove.[/yellow]")


# ---------------------------------------------------------------------------
# Legacy alias
# ---------------------------------------------------------------------------


@app.command(hidden=True)
def run(
    repo: Path = typer.Argument(..., help="Path to the target repository."),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Base directory for run output (default: ./runs)."
    ),
    max_scopes: int = typer.Option(
        20, "--max-scopes", help="Maximum number of documentation scopes."
    ),
    concurrency: int = typer.Option(
        4, "--concurrency", "-j", help="Maximum parallel explorer workers."
    ),
    timeout: float = typer.Option(
        120.0, "--timeout", "-t", help="Per-scope timeout in seconds."
    ),
    model: str = typer.Option(
        DEFAULT_MODEL, "--model", "-m", help="OpenRouter model ID."
    ),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM enrichment."),
    visualize: bool = typer.Option(
        False, "--visualize", "--viz", help="Open live pipeline visualization."
    ),
    mock_viz: bool = typer.Option(
        False, "--mock-viz", help="Run mock pipeline simulation."
    ),
) -> None:
    """[Legacy] Scan, explore, and generate documentation for REPO.

    This is the original standalone pipeline. Prefer 'docbot init' + 'docbot generate'.
    """
    from .orchestrator import run_async
    from .tracker import NoOpTracker, PipelineTracker

    if mock_viz:
        from .viz_server import start_viz_server

        tracker = PipelineTracker()
        _server, url = start_viz_server(tracker)
        console.print(f"[bold cyan]Mock visualization:[/bold cyan] {url}")
        asyncio.run(
            run_async(
                repo_path=repo,
                concurrency=concurrency,
                tracker=tracker,
                mock=True,
            )
        )
        console.print("[dim]Simulation complete. Press Enter to exit.[/dim]")
        input()
        return

    repo = Path(repo).resolve()
    if not repo.is_dir():
        console.print(f"[red]Error:[/red] {repo} is not a directory.")
        raise typer.Exit(code=1)

    _load_dotenv(Path.cwd())
    llm_client = _build_llm_client(model, no_llm)

    tracker: PipelineTracker | NoOpTracker
    if visualize:
        from .viz_server import start_viz_server

        tracker = PipelineTracker()
        _server, url = start_viz_server(tracker)
        console.print(f"[bold cyan]Visualization:[/bold cyan] {url}")
    else:
        tracker = NoOpTracker()

    asyncio.run(
        run_async(
            repo_path=repo,
            output_base=output,
            max_scopes=max_scopes,
            concurrency=concurrency,
            timeout=timeout,
            llm_client=llm_client,
            tracker=tracker,
        )
    )

    if visualize:
        console.print(
            "[dim]Visualization server still running. Press Enter to exit.[/dim]"
        )
        input()


if __name__ == "__main__":
    app()
