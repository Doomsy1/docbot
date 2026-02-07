"""Git hook management for docbot.

Installs/uninstalls a post-commit hook that runs ``docbot update``
whenever new commits are made in a repository with an initialised
``.docbot/`` directory.
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


def install_hook(repo_root: Path) -> bool:
    """Install a post-commit hook that runs ``docbot update``.

    If a ``post-commit`` hook already exists the docbot section is appended
    (unless it is already present).  Returns ``True`` on success.
    """
    hooks_dir = repo_root / ".git" / "hooks"
    if not hooks_dir.is_dir():
        return False

    hook_path = hooks_dir / "post-commit"

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


def uninstall_hook(repo_root: Path) -> bool:
    """Remove the docbot section from the post-commit hook.

    If the hook file is empty (or shebang-only) after removal, deletes it.
    Returns ``True`` on success, ``False`` if there is nothing to remove.
    """
    hook_path = repo_root / ".git" / "hooks" / "post-commit"
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
