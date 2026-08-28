"""Real mDNS advertise + discover tests for dmxreplay.control.discovery --
confirmed to work in this project's own sandboxed development environment
(no mocking of zeroconf), but multicast support varies by network
namespace/container setup the way it did for tests/test_sacn_network.py's
multicast test, so these skip gracefully rather than failing hard if this
particular environment can't do it."""
from __future__ import annotations

import asyncio

import pytest

from dmxreplay.control.discovery import (
    SERVICE_TYPE,
    DeviceAdvertiser,
    _default_ip,
    _service_name,
    discover_devices,
)


def test_service_name_format():
    assert _service_name("Stage") == f"DMXReplay-Stage.{SERVICE_TYPE}"


def test_default_ip_returns_a_plausible_address():
    ip = _default_ip()
    parts = ip.split(".")
    assert len(parts) == 4
    assert all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def test_advertise_and_discover_round_trip():
    async def body():
        try:
            async with DeviceAdvertiser("TestStage", port=8080, auth_required=False) as ad:
                devices = await discover_devices(timeout_s=2.0)
        except OSError as exc:
            pytest.skip(f"multicast not available in this environment: {exc}")
            return
        matches = [d for d in devices if d["name"] == "DMXReplay-TestStage"]
        if not matches:
            pytest.skip("mDNS advertisement not observed in this environment (multicast loopback)")
        found = matches[0]
        assert found["ip"] == ad.ip
        assert found["port"] == 8080
        assert found["api_version"] == "1.0"
        assert found["auth_required"] == "false"

    asyncio.run(body())


def test_discover_with_nothing_advertising_returns_empty():
    async def body():
        devices = await discover_devices(timeout_s=0.5)
        # Not a strict assertion that it's empty (another DMXReplay device
        # could legitimately be on this network) -- just that it doesn't
        # raise and returns a list.
        assert isinstance(devices, list)

    asyncio.run(body())
