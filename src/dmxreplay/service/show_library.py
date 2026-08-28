"""A directory of `.dmxr` shows (docs/ARCHITECTURE.md Phase C/G's "show
library"). Lists/resolves names within one directory (Phase C); `delete()`/
`save()` (Phase G) add delete and upload, layered on the same `resolve()`
containment check rather than duplicating it. Rich per-show metadata
(duration/encoding/universe count/...) is `PlayerService.get_show_info()`,
which opens the file itself -- not this class's job, since it only knows
about paths, not container internals.

Path-traversal defense is the one thing worth taking seriously even at
this small scope: `resolve()` is the boundary the network Control API
(Phase D) calls with a client-supplied string, so "../../etc/passwd" or an
absolute path elsewhere on disk must be rejected here, once, rather than
trusted to every future caller to check. `save()` adds its own equivalent
check up front (see its docstring) since it deliberately can't use
`resolve()`'s must-already-exist path alone.
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

    def delete(self, name: str) -> None:
        """Removes a show from the library (Phase G's "delete via the
        Control API"). `resolve()` (must_exist=True, the default) is what
        keeps this from ever deleting outside the library directory."""
        os.remove(self.resolve(name))

    def save(self, name: str, data: bytes) -> str:
        """Writes `data` as a new show named `name` (Phase G's "upload from
        client to Pi") and returns its resolved path. `name` must be a bare
        filename -- `os.path.basename(name) != name` catches every path-
        separator/`..` trick in one check, rejecting it before it ever
        reaches `resolve()`'s own (file-must-already-exist-inside-directory)
        containment check, which `must_exist=False` here deliberately
        bypasses since the whole point is that the file doesn't exist yet.

        Written via a temp file + `os.replace()` (atomic on POSIX) so a
        client that disconnects mid-upload leaves no half-written `.dmxr`
        file sitting in the library for `list_shows()`/`LOAD_SHOW` to trip
        over."""
        if not name or os.path.basename(name) != name:
            raise ValueError(f"{name!r} is not a valid show file name (no path separators allowed)")
        if not name.endswith(".dmxr"):
            raise ValueError(f"{name!r} must end with .dmxr")
        os.makedirs(self._directory, exist_ok=True)
        target = self.resolve(name, must_exist=False)
        tmp_path = target + ".part"
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, target)
        return target
