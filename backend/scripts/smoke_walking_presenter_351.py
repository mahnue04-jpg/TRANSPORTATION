#!/usr/bin/env python3
"""Render Issue #351 five-second walking presenter proof to artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.nova.creative_studio.walking_presenter import (  # noqa: E402
    DEFAULT_SCRIPT,
    render_walking_presenter,
    validate_presenter_mp4,
)


def main() -> int:
    out_dir = Path("/opt/cursor/artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / "nova-351-walking-presenter-5s.mp4"
    result = render_walking_presenter(output_mp4=mp4, script=DEFAULT_SCRIPT)
    probe = validate_presenter_mp4(mp4)
    summary = {
        "mp4": str(mp4),
        "size_bytes": mp4.stat().st_size,
        "result": {
            "duration_seconds": result.get("duration_seconds"),
            "lip_sync": result.get("lip_sync"),
            "full_body_walking": result.get("full_body_walking"),
            "paid_provider_charges": result.get("paid_provider_charges"),
            "license_status": result.get("license_status"),
            "validation": probe,
        },
    }
    summary_path = out_dir / "nova-351-walking-presenter-5s.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if probe.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
