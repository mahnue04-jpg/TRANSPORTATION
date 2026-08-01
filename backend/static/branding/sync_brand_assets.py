"""Render Brand Identity v1 raster icons from the canonical SVG palette."""
from __future__ import annotations

import shutil
import struct
import zlib
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None
    ImageDraw = None

ROOT = Path(__file__).resolve().parent
REPO_BRAND = ROOT.parents[2] / "assets" / "branding"


def _write_png(path: Path, width: int, height: int, rgba=(11, 107, 203, 255)) -> None:
    if Image is not None:
        img = Image.new("RGBA", (width, height), (2, 10, 22, 255))
        draw = ImageDraw.Draw(img)
        margin = max(4, width // 16)
        draw.rounded_rectangle(
            (margin, margin, width - margin, height - margin),
            radius=max(8, width // 8),
            fill=(11, 107, 203, 255),
        )
        inner = margin + max(3, width // 20)
        draw.rounded_rectangle(
            (inner, inner, width - inner, height - inner),
            radius=max(6, width // 10),
            fill=(25, 199, 255, 180),
        )
        cx, cy = width // 2, int(height * 0.62)
        tri = [(width * 0.34, height * 0.72), (width * 0.5, height * 0.42), (width * 0.66, height * 0.72)]
        draw.polygon(tri, fill=(255, 255, 255, 255))
        bar_h = max(2, height // 18)
        draw.rectangle((cx - width // 10, cy - bar_h, cx + width // 10, cy + bar_h), fill=(11, 107, 203, 255))
        path_y = int(height * 0.36)
        draw.arc(
            (width * 0.22, path_y, width * 0.78, height * 0.58),
            start=200,
            end=-20,
            fill=(255, 255, 255, 220),
            width=max(2, width // 24),
        )
        img.save(path, format="PNG")
        return

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    raw = b"".join(
        b"\x00" + bytes([rgba[0], rgba[1], rgba[2], rgba[3]] * width) for _ in range(height)
    )
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def _write_ico(path: Path) -> None:
    src = ROOT / "amicor-logo-v1.png"
    if Image is not None and src.exists():
        img = Image.open(src).convert("RGBA").resize((32, 32), Image.Resampling.LANCZOS)
        img.save(path, format="ICO", sizes=[(32, 32)])
        return
    w = h = 16
    img_bytes = b"\x00" * (w * h * 4) + b"\x00" * (w * h // 8)
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(img_bytes), 22)
    path.write_bytes(header + entry + img_bytes)


def main() -> None:
    REPO_BRAND.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "amicor-logo-v1.svg", REPO_BRAND / "amicor-logo-v1.svg")
    _write_png(ROOT / "amicor-logo-v1.png", 512, 512)
    _write_png(ROOT / "apple-touch-icon.png", 180, 180)
    _write_png(ROOT / "android-chrome-192.png", 192, 192)
    _write_png(ROOT / "android-chrome-512.png", 512, 512)
    _write_ico(ROOT / "favicon.ico")
    for name in (
        "amicor-logo-v1.png",
        "apple-touch-icon.png",
        "android-chrome-192.png",
        "android-chrome-512.png",
        "favicon.ico",
    ):
        shutil.copy2(ROOT / name, REPO_BRAND / name)
    print(f"Brand assets synced: {ROOT}")


if __name__ == "__main__":
    main()
