"""Canonical public catalog. One id, one card, one primary route.

Business services are not products. Nova Creative Studio is the only public
name for the creative product (route /nova-create/). Nova Snap is the
communications product and is not Synapse Meeting.
"""

from __future__ import annotations

from html import escape
from urllib.parse import quote

COMMUNICATIONS_WORKSPACE = "https://amicor-health-isf-py.onrender.com/nova/communications"

# Older inquiry strings still accepted by the lead store. They are not catalog cards.
LEGACY_LEAD_NAMES = (
    "Autonomous Operations Agent",
    "AMICOR Nova Work & Revenue",
    "AMICOR Nova Today",
    "AMICOR Nova Create",
    "AMICOR Deliver",
)

OTHER_INQUIRIES = ("Partnership", "Other")


def _item(**kwargs):
    return kwargs


SERVICES = [
    _item(
        id="research-reports",
        name="Research & reports",
        summary="Public-source research, cited findings, document preparation, and concise reports you can review.",
        href="/business-services/",
        art="card-research.jpg",
        alt="Conceptual illustration of a researcher reviewing source books and a folder. Not a client deliverable.",
    ),
    _item(
        id="data-admin",
        name="Data & administrative support",
        summary="Spreadsheet cleanup, task registers, document organization, and customer-support drafts.",
        href="/business-services/",
        art="card-data.jpg",
        alt="Conceptual illustration of a desk where documents are organized beside a spreadsheet. Not live customer data.",
    ),
    _item(
        id="crm-workflow",
        name="CRM & workflow assessment",
        summary="Map your current process, identify gaps, and build a prioritized improvement plan.",
        href="/business-services/",
        art="card-crm.jpg",
        alt="Conceptual illustration of a team mapping a workflow with cards and string. Not a live CRM.",
    ),
]

PRODUCTS = [
    _item(
        id="nova-operations-agent",
        name="Nova Operations Agent",
        status="Supervised release",
        table_status="SUPERVISED RELEASE",
        summary="Digital operations, research and task support with human review.",
        claim="Public demo, account trial, and scoped digital work requests.",
        href="/nova-operations/",
        art="card-operations.jpg",
        alt="Conceptual illustration of a digital operations workspace with people reviewing a workflow. Not a live screenshot.",
        lead="Nova Operations Agent",
        group="software",
    ),
    _item(
        id="work-revenue",
        name="Work & Revenue",
        status="Early access",
        table_status="EARLY ACCESS / IN DEVELOPMENT",
        summary="Explore opportunities and organized work pipelines; no unverified application claims.",
        claim="Find, manage, and track work. Received revenue is owner-confirmed only. No live external submit or payment collection from this site.",
        href="/work-revenue/",
        art="card-work-revenue.jpg",
        alt="Conceptual illustration of an opportunity pipeline on a studio display. Not live payment data.",
        lead="Work & Revenue",
        group="software",
    ),
    _item(
        id="nova-creative-studio",
        name="Nova Creative Studio",
        status="Supervised release",
        table_status="SUPERVISED RELEASE",
        summary="Scripts, storyboards and configured media tools.",
        claim="Signed-in creative planning and enabled media tools. Rendering and exports remain under improvement.",
        href="/nova-create/",
        art="card-nova-create.jpg",
        alt="Conceptual illustration of an image and video editing studio with storyboard frames.",
        lead="Nova Creative Studio",
        group="software",
    ),
    _item(
        id="nova-casting",
        name="Nova Casting & Auditions",
        status="Sandbox preview",
        table_status="SANDBOX PREVIEW",
        summary="Casting workflows and human-reviewed auditions; public submissions disabled.",
        claim="Authenticated preview for casting campaigns and human-reviewed auditions. Public audition intake is disabled.",
        href="/early-access/?product=" + quote("Nova Casting & Auditions"),
        art="card-casting.jpg",
        alt="Conceptual illustration of an audition camera and a reviewer at a monitor. Public submissions are off.",
        lead="Nova Casting & Auditions",
        group="software",
    ),
    _item(
        id="ask-nova",
        name="Ask Nova",
        status="Account access",
        table_status="ACCOUNT ACCESS",
        summary="Research, ideas and assisted drafts.",
        claim="Sign-in required. Tools and access depend on plan.",
        href="/ask-nova/",
        art="card-ask-nova.jpg",
        alt="Conceptual illustration of a person asking a question at a laptop. Sign-in required. Not a live transcript.",
        lead="Ask Nova",
        group="software",
    ),
    _item(
        id="nova-snap",
        name="Nova Snap",
        status="Coming Soon",
        table_status="COMING SOON / IN DEVELOPMENT",
        summary="Signed-in messages, drafts, and local calendar notes. Live calling is not available.",
        claim="Communications workspace for saved messages and drafts. Phone and video calling are not enabled. Not Synapse Meeting.",
        href="/nova-snap/",
        art="card-nova-snap.jpg",
        alt="Conceptual illustration of a person on a desk phone with handwritten message notes. Calling is not live. Not a video meeting and not a camera.",
        lead="Nova Snap",
        group="software",
    ),
    _item(
        id="nova-today",
        name="Nova Today",
        status="Early access",
        table_status="EARLY ACCESS / IN DEVELOPMENT",
        summary="Signed-in operations command center.",
        claim="Operator command center for signed-in workspaces.",
        href="/nova-today/",
        art="card-nova-today.jpg",
        alt="Conceptual illustration of a morning command desk. Not live operator data.",
        lead="Nova Today",
        group="software",
    ),
    _item(
        id="lifesaver",
        name="Lifesaver AI Care Cloud",
        status="In development",
        table_status="IN DEVELOPMENT",
        summary="Connected-care concept, not an emergency service or medical device.",
        claim="Health-technology initiative. Not a medical device or emergency service.",
        href="/lifesaver/",
        art="card-lifesaver.jpg",
        alt="Conceptual illustration of a home check-in with a small sensor. Not a medical device or emergency service.",
        lead="Lifesaver AI Care Cloud",
        group="care",
    ),
    _item(
        id="home-hub",
        name="Home Hub",
        status="Future hardware",
        table_status="FUTURE HARDWARE / IN DEVELOPMENT",
        summary="Concept tabletop smart hub; not for sale.",
        claim="Planned rotating tabletop hub. Not for sale.",
        href="/home-hub/",
        art="card-home-hub.jpg",
        alt="Conceptual illustration of a rotating tabletop smart display. Future hardware, not for sale.",
        lead="Home Hub",
        group="hardware",
    ),
    _item(
        id="farm-app",
        name="AMICOR Farm App",
        status="Coming Soon",
        table_status="COMING SOON / CONCEPT",
        summary="Planned mobile workspace for planting, field tasks, harvest logs and farm records.",
        claim="Farm recordkeeping concept. Not a released application or agricultural advisory service.",
        href="/farm-app/",
        art="card-farm-app.svg",
        alt="Conceptual illustration of farmland, crop rows and recordkeeping. Not a live application screenshot.",
        lead="AMICOR Farm App",
        group="software",
    ),
    _item(
        id="amicor-health",
        name="AMICOR Health",
        status="In development",
        table_status="IN DEVELOPMENT",
        summary="Private-pay transportation technology. No public rides and no licensed-market claim.",
        claim="Transportation technology. No current licensed-market claim.",
        href="/health/",
        art="card-health.jpg",
        alt="Conceptual illustration of a caregiver and vehicle at a curb. Not a booked ride.",
        lead="AMICOR Health",
        group="care",
    ),
    _item(
        id="amicor-delivery",
        name="AMICOR Delivery",
        status="In development",
        table_status="COMING SOON / IN DEVELOPMENT",
        summary="Planned delivery technology; no public orders.",
        claim="Planned delivery technology only.",
        href="/deliver/",
        art="card-delivery.jpg",
        alt="Conceptual illustration of a dispatch desk and a courier with a parcel. Not accepting public orders.",
        lead="AMICOR Delivery",
        group="care",
    ),
]


def by_id(product_id: str) -> dict:
    for product in PRODUCTS:
        if product["id"] == product_id:
            return product
    raise KeyError(product_id)


def lead_names() -> list[str]:
    names = ["Business Services"]
    names.extend(product["lead"] for product in PRODUCTS)
    names.extend(OTHER_INQUIRIES)
    return names


def accepted_lead_names() -> list[str]:
    return lead_names() + list(LEGACY_LEAD_NAMES)


def _esc(value: str) -> str:
    return escape(value, quote=True)


def card_action(product: dict) -> tuple[str, str]:
    """Public card CTA. Available is not used until a product is independently verified as generally usable."""
    status = product["status"].lower()
    table = product["table_status"].lower()
    unfinished = any(token in status for token in ("in development", "future hardware", "coming soon")) or "coming soon" in table
    if unfinished:
        return ("Join waitlist", "/early-access/?product=" + quote(product["lead"]))
    if any(token in status for token in ("early access", "preview", "sandbox")):
        label = "Preview" if "preview" in status or "sandbox" in status else "Early access"
        return (label, product["href"])
    return ("Open product", product["href"])


def visual_grid(prefix: str, *, eager: bool = False, grid_id: str = "product-catalog") -> str:
    cards = []
    for index, product in enumerate(PRODUCTS):
        loading = "eager" if eager and index == 0 else "lazy"
        label, href = card_action(product)
        cards.append(
            '<article class="product-visual-card" data-listing="product" data-product-id="'
            + _esc(product["id"])
            + '"><div class="product-visual-art"><img loading="'
            + loading
            + '" decoding="async" width="1280" height="720" src="'
            + prefix
            + "assets/img/"
            + product["art"]
            + '" alt="'
            + _esc(product["alt"])
            + '"></div><div class="product-visual-body"><p class="product-visual-status">'
            + _esc(product["status"])
            + "</p><h3>"
            + _esc(product["name"])
            + "</h3><p>"
            + _esc(product["summary"])
            + '</p><a class="card-link" href="'
            + _esc(href)
            + '">'
            + _esc(label)
            + "</a></div></article>"
        )
    return (
        '<div class="product-visual-grid" id="'
        + _esc(grid_id)
        + '">'
        + "".join(cards)
        + "</div><p class=\"art-note\">Conceptual illustrations. Not screenshots of live accounts, payments, calls, or devices. Business services are listed separately and are not catalog cards.</p>"
    )


def service_cards(prefix: str = "") -> str:
    cards = []
    for service in SERVICES:
        cards.append(
            '<article class="card" data-listing="service" data-service-id="'
            + _esc(service["id"])
            + '"><div class="card-visual"><img loading="lazy" decoding="async" width="1280" height="720" src="'
            + prefix
            + "assets/img/"
            + service["art"]
            + '" alt="'
            + _esc(service["alt"])
            + '"></div><h3>'
            + _esc(service["name"])
            + "</h3><p>"
            + _esc(service["summary"])
            + '</p><a class="card-link" href="'
            + _esc(service["href"])
            + '">Learn more</a></article>'
        )
    return '<div class="grid grid-3">' + "".join(cards) + "</div>"


def cross_links(*, group: str | None = None, label: str = "Product pages") -> str:
    chosen = [product for product in PRODUCTS if group is None or product["group"] == group]
    links = "".join(
        '<a href="' + _esc(product["href"]) + '">' + _esc(product["name"]) + "</a>" for product in chosen
    )
    return '<nav class="product-crosslinks" aria-label="' + _esc(label) + '">' + links + "</nav>"


def footer_links() -> str:
    items = ['<a href="/business-services/">Business Services</a>']
    for product in PRODUCTS:
        items.append('<a href="' + _esc(product["href"]) + '">' + _esc(product["name"]) + "</a>")
    return "\n          ".join(items)


def status_table() -> str:
    rows = [
        "<tr><td>AMICOR corporate website</td><td>LIVE</td><td>This public information site.</td></tr>",
    ]
    for product in PRODUCTS:
        rows.append(
            "<tr data-status-id=\""
            + _esc(product["id"])
            + "\"><td>"
            + _esc(product["name"])
            + "</td><td>"
            + _esc(product["table_status"])
            + "</td><td>"
            + _esc(product["claim"])
            + "</td></tr>"
        )
    return (
        '<div class="table-wrap"><table><thead><tr><th>Product</th><th>Public status</th><th>What this site claims</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table></div>"
    )


def inquiry_options() -> str:
    service = '<optgroup label="Business services"><option>Business Services</option></optgroup>'
    products = "".join("<option>" + _esc(product["lead"]) + "</option>" for product in PRODUCTS)
    other = "".join("<option>" + _esc(name) + "</option>" for name in OTHER_INQUIRIES)
    return (
        service
        + '<optgroup label="Products">'
        + products
        + "</optgroup>"
        + '<optgroup label="Other inquiries">'
        + other
        + "</optgroup>"
    )
