"""Request-time feature flag for the synthetic media slice."""
from __future__ import annotations

import os

FLAG_NAME = "NOVA_INTELLIGENCE_MEDIA"


def media_enabled() -> bool:
    """True only when the environment value is exactly ``1``.

    Unset, empty, ``true``, ``yes``, and surrounding whitespace stay off.
    """
    return os.environ.get(FLAG_NAME) == "1"
