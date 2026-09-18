"""Fail-closed refusals for Nova V3 Phase 1."""


class V3Error(Exception):
    def __init__(self, code: str, reason: str, *, http_status: int = 409):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.http_status = http_status
