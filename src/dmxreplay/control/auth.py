"""Local-network security for the Control API (cross-platform extension
Phase D). Minimum per the extension brief: device pairing, authentication,
authorization, an API version, and secure configuration changes
(docs/API.md §10, docs/MOBILE_API.md).

Model: one shared bearer token per DMXReplay instance, generated on first
run and persisted to disk (owner-only permissions where the OS supports
it -- `os.chmod` is a no-op on Windows, documented below rather than
silently assumed to work). "Pairing" is: whoever does local setup
(physically at the Pi, over SSH, or via docs/RASPBERRY_PI_INSTALL.md's
install flow) reads the token once and enters it into the mobile app --
there is no over-the-network pairing handshake that could itself be
intercepted, deliberately, since the brief's own framing for this is
staying simple on a trusted local lighting network, not building a full
PKI for a LAN appliance.
"""
from __future__ import annotations

import os
import secrets


class ApiToken:
    def __init__(self, value: str) -> None:
        if not value:
            raise ValueError("token value must be non-empty")
        self._value = value

    @property
    def value(self) -> str:
        return self._value

    def matches(self, presented: str | None) -> bool:
        """Constant-time comparison -- a naive `==` here would leak how
        many leading characters matched via response-timing, the standard
        reason token/password comparisons use `secrets.compare_digest`."""
        if presented is None:
            return False
        return secrets.compare_digest(self._value, presented)

    @classmethod
    def generate(cls) -> "ApiToken":
        return cls(secrets.token_urlsafe(32))

    @classmethod
    def load_or_create(cls, path: str) -> "ApiToken":
        """Loads the token from `path` if it already exists (so restarting
        the service doesn't invalidate every already-paired client's saved
        token), else generates a new one and writes it there."""
        if os.path.isfile(path):
            with open(path, "r") as f:
                value = f.read().strip()
            if value:
                return cls(value)
        token = cls.generate()
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(token.value + "\n")
        return token
