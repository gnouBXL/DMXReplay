"""mDNS/Zeroconf advertisement and discovery of DMXReplay devices on the
local network (cross-platform extension Phase E, extension brief §19).
Discovery is never required for the Control API itself -- connecting
directly by IP always works (docs/MOBILE_API.md) -- this is purely a
convenience layer on top, using the standard/most widely deployed
cross-platform mDNS library rather than hand-rolling the protocol (unlike
Art-Net/sACN, docs/ARTNET.md/docs/SACN.md, which DMXReplay implements from
the wire spec because no adequate existing library covered them -- mDNS
has one, so this doesn't reinvent it).
"""
from __future__ import annotations

import asyncio
import socket

from zeroconf import Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

SERVICE_TYPE = "_dmxreplay._tcp.local."
RESOLVE_TIMEOUT_MS = 3000


def _default_ip() -> str:
    """Best-effort local IP for the advertised service address: opens a UDP
    socket "connected" to a public IP (no packet is actually sent --
    connect() on SOCK_DGRAM just makes the OS pick a route/local address)
    purely to ask which local interface it would use for outbound
    traffic. A well-known trick for "what's my LAN IP" without pulling in
    another dependency just for this."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def _service_name(device_name: str) -> str:
    return f"DMXReplay-{device_name}.{SERVICE_TYPE}"


class DeviceAdvertiser:
    """Advertises this DMXReplay device via mDNS for as long as it's
    running. Async context manager:

        async with DeviceAdvertiser("Stage", port=8080) as ad:
            ...  # advertised for the duration of this block
    """

    def __init__(
        self, device_name: str, port: int, *,
        api_version: str = "1.0", auth_required: bool = True, ip: str | None = None,
    ) -> None:
        self.device_name = device_name
        self.port = port
        self.ip = ip or _default_ip()
        self.api_version = api_version
        self.auth_required = auth_required
        self._aiozc: AsyncZeroconf | None = None
        self._info: AsyncServiceInfo | None = None

    async def start(self) -> None:
        self._aiozc = AsyncZeroconf()
        self._info = AsyncServiceInfo(
            SERVICE_TYPE,
            _service_name(self.device_name),
            port=self.port,
            addresses=[socket.inet_aton(self.ip)],
            properties={
                "api_version": self.api_version,
                "auth_required": "true" if self.auth_required else "false",
            },
        )
        await self._aiozc.async_register_service(self._info)

    async def stop(self) -> None:
        if self._aiozc is not None and self._info is not None:
            await self._aiozc.async_unregister_service(self._info)
            await self._aiozc.async_close()
        self._aiozc = None
        self._info = None

    async def __aenter__(self) -> "DeviceAdvertiser":
        await self.start()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.stop()


class _CollectingListener:
    def __init__(self, zeroconf: Zeroconf, found: dict[str, dict]) -> None:
        self._zeroconf = zeroconf
        self._found = found

    def add_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        asyncio.ensure_future(self._resolve(service_type, name))

    def update_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        asyncio.ensure_future(self._resolve(service_type, name))

    def remove_service(self, zc: Zeroconf, service_type: str, name: str) -> None:
        self._found.pop(name, None)

    async def _resolve(self, service_type: str, name: str) -> None:
        info = AsyncServiceInfo(service_type, name)
        if not await info.async_request(self._zeroconf, RESOLVE_TIMEOUT_MS):
            return
        addresses = info.parsed_scoped_addresses()
        properties = {
            k.decode("utf-8", "replace"): v.decode("utf-8", "replace")
            for k, v in info.properties.items() if v is not None
        }
        self._found[name] = {
            "name": name[: -len("." + SERVICE_TYPE)] if name.endswith("." + SERVICE_TYPE) else name,
            "ip": addresses[0] if addresses else None,
            "port": info.port,
            **properties,
        }


async def discover_devices(timeout_s: float = 3.0) -> list[dict]:
    """Browses the LAN for DMXReplay devices for `timeout_s` seconds.
    Returns a list of {"name", "ip", "port", "api_version",
    "auth_required"} dicts, one per device found. This is a reference
    implementation for a desktop tool or test; the mobile app (Phase F)
    will use its own platform's native mDNS APIs (NSNetServiceBrowser/
    Bonjour on iOS, NsdManager on Android) rather than embed Python."""
    aiozc = AsyncZeroconf()
    found: dict[str, dict] = {}
    listener = _CollectingListener(aiozc.zeroconf, found)
    browser = AsyncServiceBrowser(aiozc.zeroconf, SERVICE_TYPE, listener)
    try:
        await asyncio.sleep(timeout_s)
    finally:
        await browser.async_cancel()
        await aiozc.async_close()
    return list(found.values())
