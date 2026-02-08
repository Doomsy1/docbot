"""Git hook management for docbot.

Installs/uninstalls post-commit and post-merge hooks that run ``docbot update``
whenever new commits are made or branches are merged in a repository with an
initialised ``.docbot/`` directory.
"""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

_SENTINEL_START = "# --- docbot hook start ---"
_SENTINEL_END = "# --- docbot hook end ---"

_HOOK_BODY = f"""\
{_SENTINEL_START}
if [ -d ".docbot" ]; then
    docbot update 2>&1 | tail -5
fi
{_SENTINEL_END}
"""


def _install_hook_file(hook_path: Path) -> bool:
    """Install docbot hook body into a specific hook file.
    
    Args:
        hook_path: Path to the hook file (e.g., .git/hooks/post-commit)
        
    Returns:
        True on success, False if .git/hooks directory doesn't exist
    """
    hooks_dir = hook_path.parent
    if not hooks_dir.is_dir():
        return False

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if _SENTINEL_START in existing:
            # Already installed.
            return True
        new_content = existing.rstrip("\n") + "\n\n" + _HOOK_BODY
    else:
        new_content = "#!/bin/sh\n\n" + _HOOK_BODY

    hook_path.write_text(new_content, encoding="utf-8")

    # Make executable on non-Windows platforms.
    if sys.platform != "win32":
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)

    return True


def install_hook(repo_root: Path, commit_only: bool = False) -> bool:
    """Install git hooks that run ``docbot update``.
    
    By default, installs both post-commit and post-merge hooks.
    If commit_only is True, only installs the post-commit hook.

    If a hook already exists, the docbot section is appended
    (unless it is already present). Returns ``True`` on success.
    
    Args:
        repo_root: Path to the git repository root
        commit_only: If True, only install post-commit hook
        
    Returns:
        True if at least one hook was installed successfully
    """
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        return False

    success = False
    
    # Always install post-commit
    if _install_hook_file(hooks_dir / "post-commit"):
        success = True
    
    # Install post-merge unless commit_only is True
    if not commit_only:
        if _install_hook_file(hooks_dir / "post-merge"):
            success = True

    return success


def install_post_merge_hook(repo_root: Path) -> bool:
    """Install a post-merge hook that runs ``docbot update``.

    If a ``post-merge`` hook already exists the docbot section is appended
    (unless it is already present). Returns ``True`` on success.
    
    Args:
        repo_root: Path to the git repository root
        
    Returns:
        True on success
    """
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        return False

    return _install_hook_file(hooks_dir / "post-merge")


def _uninstall_hook_file(hook_path: Path) -> bool:
    """Remove the docbot section from a specific hook file.
    
    If the hook file is empty (or shebang-only) after removal, deletes it.
    
    Args:
        hook_path: Path to the hook file
        
    Returns:
        True if docbot section was found and removed, False otherwise
    """
    if not hook_path.is_file():
        return False

    content = hook_path.read_text(encoding="utf-8")
    if _SENTINEL_START not in content:
        return False

    # Remove everything between (and including) the sentinel lines.
    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    inside = False
    for line in lines:
        if line.strip() == _SENTINEL_START:
            inside = True
            continue
        if line.strip() == _SENTINEL_END:
            inside = False
            continue
        if not inside:
            new_lines.append(line)

    remaining = "".join(new_lines).strip()

    # If only the shebang (or nothing) remains, delete the file.
    if not remaining or remaining == "#!/bin/sh":
        hook_path.unlink()
    else:
        hook_path.write_text(remaining + "\n", encoding="utf-8")

    return True


def uninstall_hook(repo_root: Path) -> bool:
    """Remove the docbot section from all git hooks.

    Removes docbot from both post-commit and post-merge hooks.
    If a hook file is empty (or shebang-only) after removal, deletes it.
    Returns ``True`` if at least one hook was removed.
    
    Args:
        repo_root: Path to the git repository root
        
    Returns:
        True if at least one docbot hook was found and removed
    """
    hooks_dir = repo_root / ".git" / "hooks"
    
    removed_commit = _uninstall_hook_file(hooks_dir / "post-commit")
    removed_merge = _uninstall_hook_file(hooks_dir / "post-merge")
    
    return removed_commit or removed_merge
