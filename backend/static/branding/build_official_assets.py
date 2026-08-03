"""Build Amicor brand assets from the approved official logo source (no redesign).

Canonical source: amicor-official-source.png
Only crop/resize — does not redraw, recolor, or simplify the artwork.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
REPO_BRAND = ROOT.parents[2] / "assets" / "branding"
SOURCE_CANDIDATES = [
    ROOT / "amicor-official-source.png",
    Path.home() / "Downloads" / "ChatGPT Image Aug 2, 2026, 04_16_36 PM.png",
]
CACHE_TAG = "20260803.1"


def _load_source() -> Path:
    for path in SOURCE_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "Approved logo not found. Place it at backend/static/branding/amicor-official-source.png"
    )


def _alpha_bbox(arr: np.ndarray, alpha_min: int = 8) -> tuple[int, int, int, int]:
    ys, xs = np.where(arr[:, :, 3] >= alpha_min)
    if len(xs) == 0:
        raise ValueError("Approved source has no opaque pixels")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _emblem_split(arr: np.ndarray) -> int:
    """Cut after full A + roadway + green person; before AMICOR wordmark.

    Wordmark blues/tagline greens sit to the right — search only the left
    emblem region so the mark never includes AMICOR text.
    """
    rgb = arr[:, :, :3].astype(np.int16)
    alpha = arr[:, :, 3] >= 12
    blue = (
        alpha
        & (rgb[:, :, 2] > 95)
        & (rgb[:, :, 2] > rgb[:, :, 0] + 20)
        & (rgb[:, :, 2] >= rgb[:, :, 1] - 15)
    )
    green = (
        alpha
        & (rgb[:, :, 1] > 100)
        & (rgb[:, :, 1] > rgb[:, :, 0] + 20)
        & (rgb[:, :, 1] > rgb[:, :, 2] + 12)
    )
    # Upper/mid band: A body + person (excludes lower tagline row).
    u = slice(180, 560)
    col_b = blue[u, :].sum(0)
    col_g = green[u, :].sum(0)
    # Emblem is left of the AMICOR wordmark (~x 620–720 gap on 1536-wide source).
    search_lo, search_hi = 560, 720
    gap = None
    for x in range(search_lo, search_hi):
        if col_b[x] < 8 and col_g[x] < 8:
            gap = x
            break
    if gap is None:
        # Fallback: end of dense green figure cluster before mid-canvas.
        figure_cols = np.where(col_g[:720] > 8)[0]
        gap = int(figure_cols.max()) + 18 if len(figure_cols) else 660
    # Person figure greens end ~655; AMICOR wordmark starts after ~720.
    # Prefer a cut that keeps the full person/road/A without wordmark letters.
    return int(min(max(gap + 12, 655), 675))


def _pad_square(img: Image.Image, pad_ratio: float = 0.06) -> Image.Image:
    w, h = img.size
    side = max(w, h)
    pad = max(4, int(side * pad_ratio))
    canvas = Image.new("RGBA", (side + pad * 2, side + pad * 2), (0, 0, 0, 0))
    canvas.paste(img, ((canvas.width - w) // 2, (canvas.height - h) // 2), img)
    return canvas


def _fit(img: Image.Image, size: int) -> Image.Image:
    return _pad_square(img).resize((size, size), Image.Resampling.LANCZOS)


def _splash(full: Image.Image, width: int, height: int, path: Path) -> None:
    """Dark splash with official full logo centered (no redesign)."""
    canvas = Image.new("RGBA", (width, height), (2, 10, 22, 255))
    max_w = int(width * 0.78)
    max_h = int(height * 0.28)
    scale = min(max_w / full.width, max_h / full.height)
    logo = full.resize(
        (max(1, int(full.width * scale)), max(1, int(full.height * scale))),
        Image.Resampling.LANCZOS,
    )
    x = (width - logo.width) // 2
    y = (height - logo.height) // 2
    canvas.paste(logo, (x, y), logo)
    canvas.convert("RGB").save(path, format="PNG", optimize=True)


def build() -> dict:
    src_path = _load_source()
    canonical = ROOT / "amicor-official-source.png"
    if src_path.resolve() != canonical.resolve():
        shutil.copy2(src_path, canonical)

    source = Image.open(canonical).convert("RGBA")
    arr = np.array(source)
    bbox = _alpha_bbox(arr)
    # Small pad so soft glow around full lockup is preserved.
    pad = 8
    bx0 = max(0, bbox[0] - pad)
    by0 = max(0, bbox[1] - pad)
    bx1 = min(arr.shape[1], bbox[2] + pad)
    by1 = min(arr.shape[0], bbox[3] + pad)
    full = source.crop((bx0, by0, bx1, by1))

    full_path = ROOT / "amicor-logo-full.png"
    primary_path = ROOT / "amicor-logo-primary.png"
    full.save(full_path, format="PNG", optimize=True)
    shutil.copy2(full_path, primary_path)

    split = _emblem_split(arr)
    emblem_arr = arr.copy()
    emblem_arr[:, split:, 3] = 0
    ex0, ey0, ex1, ey1 = _alpha_bbox(emblem_arr)
    # Preserve full A / person / roadway — pad crop edges.
    ep = 10
    ex0, ey0 = max(0, ex0 - ep), max(0, ey0 - ep)
    ex1, ey1 = min(arr.shape[1], ex1 + ep), min(arr.shape[0], ey1 + ep)
    emblem = Image.fromarray(emblem_arr, "RGBA").crop((ex0, ey0, ex1, ey1))

    mark_hd = _fit(emblem, 1024)
    mark_path = ROOT / "amicor-mark.png"
    mark_hd.save(mark_path, format="PNG", optimize=True)
    mark_hd.save(ROOT / "amicor-logo.png", format="PNG", optimize=True)

    # Replace temporary v1 placeholders with official mark so stale refs cannot resurface.
    mark_hd.save(ROOT / "amicor-logo-v1.png", format="PNG", optimize=True)
    # Redirect SVG placeholder to official PNG via HTML-incompatible note: keep PNG only;
    # write a tiny SVG that embeds nothing drawn — instead ship PNG as sole v1 raster.
    # For any leftover type=image/svg+xml links, point consumers to PNG in HTML updates.

    apple = _fit(emblem, 180)
    android192 = _fit(emblem, 192)
    android512 = _fit(emblem, 512)
    apple.save(ROOT / "apple-touch-icon.png", format="PNG", optimize=True)
    android192.save(ROOT / "android-chrome-192.png", format="PNG", optimize=True)
    android512.save(ROOT / "android-chrome-512.png", format="PNG", optimize=True)

    ico_sizes = [16, 32, 48]
    icos = [_fit(emblem, s) for s in ico_sizes]
    icos[0].save(
        ROOT / "favicon.ico",
        format="ICO",
        sizes=[(s, s) for s in ico_sizes],
        append_images=icos[1:],
    )

    # Splash screens (full official wordmark lockup, centered)
    _splash(full, 1284, 2778, ROOT / "splash-1284x2778.png")
    _splash(full, 1170, 2532, ROOT / "splash-1170x2532.png")
    _splash(full, 1080, 1920, ROOT / "splash-1080x1920.png")
    _splash(full, 512, 512, ROOT / "splash-icon.png")

    REPO_BRAND.mkdir(parents=True, exist_ok=True)
    for name in (
        "amicor-official-source.png",
        "amicor-logo-full.png",
        "amicor-logo-primary.png",
        "amicor-mark.png",
        "amicor-logo.png",
        "amicor-logo-v1.png",
        "apple-touch-icon.png",
        "android-chrome-192.png",
        "android-chrome-512.png",
        "favicon.ico",
        "splash-1284x2778.png",
        "splash-1170x2532.png",
        "splash-1080x1920.png",
        "splash-icon.png",
    ):
        src = ROOT / name
        if src.is_file():
            shutil.copy2(src, REPO_BRAND / name)

    # Remove obsolete generated SVG placeholder (generic road icon).
    for obsolete in (ROOT / "amicor-logo-v1.svg", REPO_BRAND / "amicor-logo-v1.svg"):
        if obsolete.is_file():
            obsolete.unlink()

    info = {
        "cache_tag": CACHE_TAG,
        "source": str(canonical),
        "bbox": (bx0, by0, bx1, by1),
        "split": split,
        "full_size": full.size,
        "emblem_bbox": (ex0, ey0, ex1, ey1),
        "mark_size": mark_hd.size,
    }
    print("Official Amicor assets rebuilt from approved source (crop/resize only):")
    for k, v in info.items():
        print(f"  {k}: {v}")
    return info


if __name__ == "__main__":
    build()
