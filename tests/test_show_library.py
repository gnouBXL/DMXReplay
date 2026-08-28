"""Real filesystem tests for dmxreplay.service.ShowLibrary, including the
path-traversal defense it exists to provide."""
from __future__ import annotations

import os

import pytest

from dmxreplay.service import ShowLibrary, ShowNotFoundError


def test_list_shows_returns_only_dmxr_files_sorted(tmp_path):
    (tmp_path / "b.dmxr").write_bytes(b"")
    (tmp_path / "a.dmxr").write_bytes(b"")
    (tmp_path / "readme.txt").write_bytes(b"")
    library = ShowLibrary(str(tmp_path))
    assert library.list_shows() == ["a.dmxr", "b.dmxr"]


def test_list_shows_on_missing_directory_returns_empty_not_an_error(tmp_path):
    library = ShowLibrary(str(tmp_path / "does_not_exist"))
    assert library.list_shows() == []


def test_resolve_bare_filename_inside_library(tmp_path):
    (tmp_path / "show.dmxr").write_bytes(b"")
    library = ShowLibrary(str(tmp_path))
    resolved = library.resolve("show.dmxr")
    assert resolved == os.path.realpath(str(tmp_path / "show.dmxr"))


def test_resolve_missing_file_raises(tmp_path):
    library = ShowLibrary(str(tmp_path))
    with pytest.raises(ShowNotFoundError):
        library.resolve("nope.dmxr")


def test_resolve_must_exist_false_allows_a_new_filename(tmp_path):
    library = ShowLibrary(str(tmp_path))
    resolved = library.resolve("new_recording.dmxr", must_exist=False)
    assert resolved == os.path.realpath(str(tmp_path / "new_recording.dmxr"))


def test_resolve_rejects_path_traversal_outside_the_library(tmp_path):
    outside = tmp_path.parent / "secret.dmxr"
    outside.write_bytes(b"")
    library_dir = tmp_path / "shows"
    library_dir.mkdir()
    library = ShowLibrary(str(library_dir))

    with pytest.raises(ShowNotFoundError):
        library.resolve("../secret.dmxr")


def test_resolve_rejects_absolute_path_outside_the_library(tmp_path):
    outside = tmp_path / "outside.dmxr"
    outside.write_bytes(b"")
    library_dir = tmp_path / "shows"
    library_dir.mkdir()
    library = ShowLibrary(str(library_dir))

    with pytest.raises(ShowNotFoundError):
        library.resolve(str(outside))


def test_resolve_rejects_symlink_escaping_the_library(tmp_path):
    """A symlink *inside* the library directory that points outside it must
    not be trusted just because its name looked local -- os.path.realpath()
    resolves the symlink before the containment check runs."""
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "secret.dmxr").write_bytes(b"")
    library_dir = tmp_path / "shows"
    library_dir.mkdir()
    (library_dir / "link.dmxr").symlink_to(outside_dir / "secret.dmxr")

    library = ShowLibrary(str(library_dir))
    with pytest.raises(ShowNotFoundError):
        library.resolve("link.dmxr")


def test_delete_removes_the_file(tmp_path):
    (tmp_path / "show.dmxr").write_bytes(b"data")
    library = ShowLibrary(str(tmp_path))
    library.delete("show.dmxr")
    assert not (tmp_path / "show.dmxr").exists()


def test_delete_missing_show_raises(tmp_path):
    library = ShowLibrary(str(tmp_path))
    with pytest.raises(ShowNotFoundError):
        library.delete("nope.dmxr")


def test_delete_rejects_path_traversal_outside_the_library(tmp_path):
    outside = tmp_path.parent / "secret.dmxr"
    outside.write_bytes(b"data")
    library_dir = tmp_path / "shows"
    library_dir.mkdir()
    library = ShowLibrary(str(library_dir))

    with pytest.raises(ShowNotFoundError):
        library.delete("../secret.dmxr")
    assert outside.exists()  # never touched


def test_save_writes_the_file_and_returns_its_resolved_path(tmp_path):
    library = ShowLibrary(str(tmp_path))
    resolved = library.save("uploaded.dmxr", b"hello dmxr")
    assert resolved == os.path.realpath(str(tmp_path / "uploaded.dmxr"))
    assert (tmp_path / "uploaded.dmxr").read_bytes() == b"hello dmxr"
    assert not (tmp_path / "uploaded.dmxr.part").exists()  # no leftover temp file


def test_save_creates_the_library_directory_if_missing(tmp_path):
    library_dir = tmp_path / "shows"
    library = ShowLibrary(str(library_dir))
    library.save("uploaded.dmxr", b"data")
    assert (library_dir / "uploaded.dmxr").read_bytes() == b"data"


def test_save_rejects_names_containing_path_separators(tmp_path):
    library = ShowLibrary(str(tmp_path))
    with pytest.raises(ValueError, match="path separators"):
        library.save("../escape.dmxr", b"data")
    with pytest.raises(ValueError, match="path separators"):
        library.save("sub/dir.dmxr", b"data")


def test_save_rejects_names_not_ending_in_dmxr(tmp_path):
    library = ShowLibrary(str(tmp_path))
    with pytest.raises(ValueError, match=r"\.dmxr"):
        library.save("not_a_show.txt", b"data")


def test_save_overwrites_an_existing_show_of_the_same_name(tmp_path):
    library = ShowLibrary(str(tmp_path))
    library.save("show.dmxr", b"first")
    library.save("show.dmxr", b"second")
    assert (tmp_path / "show.dmxr").read_bytes() == b"second"
