"""A directory of `.dmxr` shows (docs/ARCHITECTURE.md Phase C/G's "show
library"). Deliberately minimal here -- lists and resolves names within
one directory; upload/delete/rich metadata is Phase G, layered on top of
this, not duplicating it.

Path-traversal defense is the one thing worth taking seriously even at
this small scope: `resolve()` is the boundary a future network API (Phase
D) will call with a client-supplied string, so "../../etc/passwd" or an
absolute path elsewhere on disk must be rejected here, once, rather than
trusted to every future caller to check.
"""
from __future__ import annotations

import os


class ShowNotFoundError(ValueError):
    """The requested name doesn't resolve to a file inside the library
    directory -- either it doesn't exist, or (this is the security-relevant
    case) it resolves outside the directory entirely."""


class ShowLibrary:
    def __init__(self, directory: str) -> None:
        self._directory = os.path.realpath(directory)

    @property
    def directory(self) -> str:
        return self._directory

    def list_shows(self) -> list[str]:
        """Sorted `.dmxr` filenames (not full paths) directly inside the
        library directory. Empty list if the directory doesn't exist yet
        (not an error -- a fresh install's shows/ dir is legitimately
        empty, docs/RASPBERRY_PI_INSTALL.md)."""
        if not os.path.isdir(self._directory):
            return []
        return sorted(f for f in os.listdir(self._directory) if f.endswith(".dmxr"))

    def resolve(self, name: str, *, must_exist: bool = True) -> str:
        """A bare filename (looked up inside the library) or an absolute
        path that already points inside it -> the real, absolute path.
        Raises ShowNotFoundError for anything that resolves outside the
        library directory, or (if must_exist) doesn't exist."""
        candidate = name if os.path.isabs(name) else os.path.join(self._directory, name)
        resolved = os.path.realpath(candidate)
        try:
            inside = os.path.commonpath([resolved, self._directory]) == self._directory
        except ValueError:
            inside = False  # different drives on Windows, os.path.commonpath raises
        if not inside:
            raise ShowNotFoundError(f"{name!r} is outside the show library directory")
        if must_exist and not os.path.isfile(resolved):
            raise ShowNotFoundError(f"{name!r} does not exist in the show library")
        return resolved
