"""Git integration utilities."""

from .project import (
    init_project,
    find_docbot_root,
    load_config,
    save_config,
    load_state,
    save_state,
)
from .utils import (
    get_current_commit,
    get_changed_files,
    is_commit_reachable,
    get_repo_root,
)
from .hooks import install_hook, uninstall_hook
from .history import save_snapshot, load_snapshot, list_snapshots, prune_snapshots
from .diff import compute_diff

__all__ = [
    "init_project",
    "find_docbot_root",
    "load_config",
    "save_config",
    "load_state",
    "save_state",
    "get_current_commit",
    "get_changed_files",
    "is_commit_reachable",
    "get_repo_root",
    "install_hook",
    "uninstall_hook",
    "save_snapshot",
    "load_snapshot",
    "list_snapshots",
    "prune_snapshots",
    "compute_diff",
]
