#!/usr/bin/env python3
"""Render Issue #351 thirty-second walking talking commercial."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.nova.creative_studio.generation import assemble_short_video  # noqa: E402
from app.core.nova.creative_studio.walking_presenter import (  # noqa: E402
    render_walking_commercial_30s,
    validate_presenter_mp4,
)


def main() -> int:
    out_dir = Path("/opt/cursor/artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / "nova-351-walking-commercial-30s.mp4"
    board = assemble_short_video(
        topic="AMICOR Nova business services commercial",
        audience="small business owners",
        platform="TikTok",
        duration_target=30,
        style="modern professional",
        tone="clear and confident",
        cta="Visit getamicor.com to explore AMICOR Nova.",
        brand_name="AMICOR",
    )
    result = render_walking_commercial_30s(
        output_mp4=mp4,
        scenes=board["scenes"],
        license_status="GREEN",
    )
    probe = validate_presenter_mp4(mp4, min_seconds=28.0, max_seconds=32.0)
    summary = {
        "mp4": str(mp4),
        "size_bytes": mp4.stat().st_size,
        "result": {
            "duration_seconds": result.get("duration_seconds"),
            "lip_sync": result.get("lip_sync"),
            "lip_sync_method": result.get("lip_sync_method"),
            "license_status": result.get("license_status"),
            "mobile_download_ready": result.get("mobile_download_ready"),
            "paid_provider_charges": result.get("paid_provider_charges"),
            "validation": probe,
        },
    }
    (out_dir / "nova-351-walking-commercial-30s.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if probe.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
