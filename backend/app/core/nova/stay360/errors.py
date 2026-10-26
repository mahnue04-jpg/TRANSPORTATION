"""Stay360 application errors. Messages stay free of guest secrets."""

from __future__ import annotations


class Stay360Error(Exception):
    def __init__(self, status: int, code: str, message: str, payload: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.payload = payload

    def detail(self) -> dict:
        body: dict = {"code": self.code, "message": self.message}
        if self.payload is not None:
            body["result"] = self.payload
        return body


class Stay360ProviderBlocked(RuntimeError):
    """Raised if a caller tries to reach a live airline, hotel, or map provider."""


def reject_external_provider(name: str) -> None:
    """Stay360 arrival updates are in-process fixtures. This never opens a socket."""
    label = str(name or "provider").strip() or "provider"
    raise Stay360ProviderBlocked(
        f"Stay360 does not call external provider {label}. Use in-process fixtures."
    )
