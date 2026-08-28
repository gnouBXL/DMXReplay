"""Real tests for dmxreplay.demo.demo_show_path() -- the bundled demo show
the Player GUI's "File > Open Demo Show" opens with zero setup."""
from __future__ import annotations

import os

from dmxreplay.container import DMXReplayReader
from dmxreplay.demo import DEMO_UNIVERSE_COUNT, demo_show_path


def test_demo_show_path_generates_a_real_readable_dmxr_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    path = demo_show_path()
    assert os.path.isfile(path)
    with DMXReplayReader(path) as reader:
        manifest = reader.manifest
        frames = list(reader.read_frames())
    assert manifest.height == DEMO_UNIVERSE_COUNT
    assert manifest.show_name == "DMXReplay Demo Show"
    assert reader.has_audio is True
    assert len(frames) > 0
    assert len(frames[0].universes) == DEMO_UNIVERSE_COUNT


def test_demo_show_path_is_cached_not_regenerated(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    path1 = demo_show_path()
    mtime1 = os.path.getmtime(path1)
    path2 = demo_show_path()
    mtime2 = os.path.getmtime(path2)
    assert path1 == path2
    assert mtime1 == mtime2  # second call did not rewrite the file
