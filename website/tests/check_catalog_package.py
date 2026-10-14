"""Registry-derived catalog checks for the website package workflow.

Card count, names, ids, and image assets come from website/catalog.py.
"""
from __future__ import annotations

import hashlib
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalog import PRODUCTS, accepted_lead_names, lead_names  # noqa: E402


def _allowlist(source: str) -> list[str]:
    match = re.search(r"const PRODUCTS = new Set\(\[(.*?)\]\);", source, re.S)
    if not match:
        raise AssertionError("Lead allowlist is missing")
    return re.findall(r'"((?:\\.|[^"\\])*)"', match.group(1))


def _cards(site: str) -> list[tuple[str, str, str]]:
    articles = re.findall(
        r'<article class="product-visual-card"[^>]*data-product-id="([^"]+)"[^>]*>(.*?)</article>',
        site,
        re.S,
    )
    cards = []
    for product_id, body in articles:
        image = re.search(r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]+)"', body)
        if not image:
            raise AssertionError(f"Catalog card has no image: {product_id}")
        cards.append((product_id, image.group(1), html.unescape(image.group(2))))
    return cards


def main() -> None:
    site = (ROOT / "products" / "index.html").read_text(encoding="utf-8")
    plain = html.unescape(site)
    expected = len(PRODUCTS)
    for product in PRODUCTS:
        if product["name"] not in plain:
            raise AssertionError(f"Missing product: {product['name']}")
        if f'data-product-id="{product["id"]}"' not in site:
            raise AssertionError(f"Missing product id: {product['id']}")
    if "No public rides and no licensed-market claim." not in site:
        raise AssertionError("Health claim is missing")
    if "product-visual-grid" not in site:
        raise AssertionError("Visual catalog not generated")
    if not (ROOT / "assets" / "css" / "product-visuals.css").is_file():
        raise AssertionError("Product visual stylesheet is missing")

    for src in re.findall(r'<img[^>]*src="([^"]+)"', site):
        if src.startswith(("http:", "https:", "data:")):
            continue
        image = (ROOT / "products" / src).resolve()
        if not image.is_file():
            raise AssertionError(f"Missing image: {src}")

    cards = _cards(site)
    if len(cards) != expected:
        raise AssertionError(f"catalog cards: {len(cards)}; registry: {expected}")
    ids = [product_id for product_id, _src, _alt in cards]
    srcs = [src for _product_id, src, _alt in cards]
    alts = [alt for _product_id, _src, alt in cards]
    if ids != [product["id"] for product in PRODUCTS]:
        raise AssertionError(f"Catalog ids drifted from the registry: {ids}")
    if len(set(ids)) != expected or len(set(srcs)) != expected or len(set(alts)) != expected:
        raise AssertionError("Catalog ids, images, or alt text are not unique")
    hashes = set()
    for product, src, alt in zip(PRODUCTS, srcs, alts):
        path = (ROOT / "products" / src).resolve()
        if path.name != product["art"]:
            raise AssertionError(f"{product['id']} image is {path.name}, registry art is {product['art']}")
        if alt != product["alt"]:
            raise AssertionError(f"{product['id']} alt text drifted from the registry")
        hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    if len(hashes) != expected:
        raise AssertionError(f"Unique image hashes: {len(hashes)}; registry: {expected}")

    health = next(product for product in PRODUCTS if product["id"] == "amicor-health")
    if not any(src.endswith(health["art"]) and "caregiver and vehicle" in alt for _product_id, src, alt in cards):
        raise AssertionError("Health card image or alt text drifted")
    if 'type="file"' in site:
        raise AssertionError("Catalog must not accept file uploads")
    if "public submissions disabled" not in site.lower():
        raise AssertionError("Casting public-submission status is missing")
    casting = next(product for product in PRODUCTS if product["id"] == "nova-casting")
    snap = next(product for product in PRODUCTS if product["id"] == "nova-snap")
    if casting["href"] not in site:
        raise AssertionError("Casting catalog CTA is not the allowlisted product")
    if "Nova%20Casting%20and%20Auditions" in site:
        raise AssertionError("Casting CTA uses a name that is not on the allowlist")
    if snap["href"] not in site or snap["name"] not in plain:
        raise AssertionError("Nova Snap catalog card is missing")
    if snap["status"] != "Coming Soon":
        raise AssertionError("Nova Snap card status must stay Coming Soon")
    if "Join waitlist" not in site:
        raise AssertionError("Unfinished products are missing the waitlist CTA")
    if ">Available<" in site:
        raise AssertionError("Catalog marks a product Available without a separate usability check")

    home = (ROOT / "index.html").read_text(encoding="utf-8")
    home_cards = _cards(home)
    if len(home_cards) != expected:
        raise AssertionError(f"homepage cards: {len(home_cards)}; registry: {expected}")
    if [product_id for product_id, _src, _alt in home_cards] != [product["id"] for product in PRODUCTS]:
        raise AssertionError("Homepage card ids drifted from the registry")
    home_hashes = set()
    for product, src, alt in zip(PRODUCTS, [item[1] for item in home_cards], [item[2] for item in home_cards]):
        if not src.startswith("assets/img/"):
            raise AssertionError(f"Homepage image path drifted: {src}")
        path = (ROOT / src).resolve()
        if path.name != product["art"] or alt != product["alt"] or not path.is_file():
            raise AssertionError(f"Homepage art drifted for {product['id']}")
        home_hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    if len(home_hashes) != expected:
        raise AssertionError(f"Homepage unique image hashes: {len(home_hashes)}; registry: {expected}")
    if "\\n              <tr>" in site:
        raise AssertionError("Status table contains a literal escaped newline")

    leads = (ROOT / "functions" / "api" / "leads.js").read_text(encoding="utf-8")
    allowlist = _allowlist(leads)
    expected_allow = accepted_lead_names()
    if set(allowlist) != set(expected_allow):
        drifted = sorted(set(allowlist) ^ set(expected_allow))
        raise AssertionError(f"Lead allowlist drifted from the registry: {drifted}")
    if snap["lead"] not in allowlist or casting["lead"] not in allowlist:
        raise AssertionError("Nova Snap or Casting is missing from the lead allowlist")

    early = (ROOT / "early-access" / "index.html").read_text(encoding="utf-8")
    select = re.search(r'<select name="product"[^>]*>(.*?)</select>', early, re.S)
    if not select:
        raise AssertionError("Inquiry select is missing")
    options = [html.unescape(item) for item in re.findall(r"<option>([^<]+)</option>", select.group(1))]
    if options != lead_names():
        raise AssertionError(f"Inquiry options drifted from the registry: {options}")
    if snap["lead"] not in options:
        raise AssertionError("Nova Snap is missing from inquiry options")

    repo = ROOT.parent
    mise = (repo / "mise.toml").read_text(encoding="utf-8")
    if mise.count("python.github_attestations = false") != 1:
        raise AssertionError("mise attestation pin drifted")
    if (repo / "runtime.txt").read_text(encoding="utf-8").strip() != "3.11.9":
        raise AssertionError("runtime.txt drifted")
    print(
        f"Registry cards: {len(cards)}; unique images: {len(hashes)}; "
        f"allowlist: {len(allowlist)}; inquiry options: {len(options)}"
    )


if __name__ == "__main__":
    main()
