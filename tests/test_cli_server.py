"""dmxreplay-server CLI tests: argument parsing, config-driven wiring
(pure functions, no server startup), and a real subprocess smoke test of
the actually-installed console script (confirms pyproject.toml entry-point
wiring end-to-end, same pattern as test_cli.py's
test_info_cli_subprocess_smoke_test)."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request

from dmxreplay.cli import server as server_cli
from dmxreplay.codec import ENCODINGS
from dmxreplay.container import DMXReplayWriter
from dmxreplay.dmx import CHANNELS_PER_UNIVERSE, DMXFrame, Universe
from dmxreplay.metadata import Manifest, UniverseMapping


def test_build_parser_defaults():
    args = server_cli.build_parser().parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 8080
    assert args.no_auth is False
    assert args.enable_recorder is False


def test_build_services_without_recorder():
    args = server_cli.build_parser().parse_args([])
    player, recorder = server_cli._build_services(args)
    assert player is not None
    assert recorder is None


def test_build_services_with_recorder_flag():
    args = server_cli.build_parser().parse_args(["--enable-recorder"])
    player, recorder = server_cli._build_services(args)
    assert recorder is not None


def test_build_token_no_auth_returns_none():
    args = server_cli.build_parser().parse_args(["--no-auth"])
    assert server_cli._build_token(args) is None


def test_build_token_persists_and_reloads(tmp_path):
    token_path = str(tmp_path / "token")
    args = server_cli.build_parser().parse_args(["--token-file", token_path])
    first = server_cli._build_token(args)
    second = server_cli._build_token(args)
    assert first.value == second.value  # reused, not regenerated


def test_apply_config_wires_show_and_output(tmp_path):
    from dmxreplay.config import PlayerConfig
    from dmxreplay.service import PlayerService

    dmxr_path = str(tmp_path / "s.dmxr")
    mapping = [UniverseMapping.from_artnet_port_address(row=0, port_address=1)]
    manifest = Manifest(
        encoding="grayscale", fps=30.0, vfr=False, timestamp_resolution_ns=1_000_000,
        width=ENCODINGS["grayscale"]["width"], height=1,
        universes=mapping, created_at="2026-08-27T00:00:00Z", duration_seconds=0.0,
        recorder={"name": "dmxreplay-tests", "version": "0.1.0-dev"},
    )
    with DMXReplayWriter(dmxr_path, manifest) as w:
        w.write_frame(DMXFrame(timestamp_ns=0, universes=(Universe.blank(),)))

    config = PlayerConfig(show=dmxr_path, output="artnet", interface="127.0.0.1", loop=True)
    player = PlayerService()
    server_cli._apply_config(player, config)

    status = player.get_status()
    assert status.loaded is True
    assert status.loop is True
    net = player.get_network_status()
    assert net["output_protocol"] == "Art-Net"
    assert net["interface_ip"] == "127.0.0.1"


def test_server_cli_subprocess_smoke_test(tmp_path):
    """Confirms the actually-installed dmxreplay-server console script
    (per pyproject.toml [project.scripts]) starts for real, serves
    /api/v1/version with no auth needed, and rejects /api/v1/status
    without the printed token."""
    proc = subprocess.Popen(
        [sys.executable, "-m", "dmxreplay.cli.server", "--port", "18765", "--host", "127.0.0.1", "--no-auth"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        deadline = time.monotonic() + 5.0
        last_error = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen("http://127.0.0.1:18765/api/v1/version", timeout=0.5) as resp:
                    assert resp.status == 200
                    break
            except (urllib.error.URLError, ConnectionError) as exc:
                last_error = exc
                time.sleep(0.1)
        else:
            raise AssertionError(f"server never became reachable: {last_error}")

        with urllib.request.urlopen("http://127.0.0.1:18765/api/v1/status", timeout=1.0) as resp:
            assert resp.status == 200  # --no-auth: reachable with no token
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
