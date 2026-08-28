"""Pure rendering tests for dmxreplay.control.webui -- no aiohttp/live
server needed, matching how player_viewmodel.py's tests stay independent
of Tkinter (same "test the logic separately from the transport/toolkit"
pattern used throughout this project)."""
from __future__ import annotations

from dmxreplay.control.webui import (
    _with_token,
    render_config_page,
    render_logs_page,
    render_message_page,
)


def test_with_token_appends_query_param():
    assert _with_token("/config", "abc123") == "/config?token=abc123"


def test_with_token_none_is_a_no_op():
    assert _with_token("/config", None) == "/config"


def test_render_config_page_shows_status_and_current_values():
    html = render_config_page(
        device_name="Stage",
        dmxreplay_version="0.1.0-dev",
        status={"loaded": True, "show_name": "MyShow.dmxr", "playing": True},
        config={"loop": True, "speed": 1.5, "fps": 44.0, "output_protocol": "Art-Net",
                "interface_ip": "127.0.0.1", "destination_ip": "192.168.1.1", "port": 6454, "priority": 100},
        network={"loop": True, "speed": 1.5, "fps": 44.0, "output_protocol": "Art-Net",
                 "interface_ip": "127.0.0.1", "destination_ip": "192.168.1.1", "port": 6454, "priority": 100},
    )
    assert "Stage" in html
    assert "MyShow.dmxr" in html
    assert "Playing" in html
    assert 'checked' in html  # loop checkbox
    assert '192.168.1.1' in html
    assert 'selected' in html  # Art-Net option selected


def test_render_config_page_escapes_untrusted_values():
    """show_name (and other values) ultimately trace back to a filename
    the user chose -- must never be interpolated unescaped into HTML."""
    html = render_config_page(
        device_name="Stage", dmxreplay_version="0.1.0-dev",
        status={"loaded": True, "show_name": "<script>alert(1)</script>", "playing": False},
        config={}, network={},
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_render_config_page_threads_token_into_form_actions():
    html = render_config_page(
        device_name="Stage", dmxreplay_version="0.1.0-dev",
        status={}, config={}, network={}, token="secret-token",
    )
    assert 'action="/config?token=secret-token"' in html
    assert 'action="/config/restart?token=secret-token"' in html
    assert 'href="/config/logs?token=secret-token"' in html


def test_render_config_page_does_not_double_escape_the_token():
    # A token containing '&' must be escaped exactly once -- a
    # double-escape bug this project's own first draft had (_with_token
    # calling html.escape() internally, then the caller escaping its
    # result again) would turn '&' into '&amp;amp;' instead of '&amp;'.
    html = render_config_page(
        device_name="Stage", dmxreplay_version="0.1.0-dev",
        status={}, config={}, network={}, token="a&b",
    )
    assert "token=a&amp;b" in html
    assert "&amp;amp;" not in html


def test_render_config_page_without_token_omits_query_param():
    html = render_config_page(
        device_name="Stage", dmxreplay_version="0.1.0-dev",
        status={}, config={}, network={},
    )
    assert 'action="/config"' in html
    assert "token=" not in html


def test_render_message_page_escapes_message():
    html = render_message_page(title="Error", message="<b>boom</b>")
    assert "<b>boom</b>" not in html
    assert "&lt;b&gt;boom&lt;/b&gt;" in html


def test_render_logs_page_shows_lines():
    html = render_logs_page(device_name="Stage", lines=["line one", "line two"])
    assert "line one" in html
    assert "line two" in html


def test_render_logs_page_empty():
    html = render_logs_page(device_name="Stage", lines=[])
    assert "no log entries yet" in html
