"""Generate the static AMICOR public website. Output is plain HTML."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
# Official public origin. Cloudflare Pages host amicor-public.pages.dev remains the underlying project host only.
ORIGIN = "https://getamicor.com"

NAV = [
    ("/", "Home"),
    ("/health/", "Health"),
    ("/deliver/", "Deliver"),
    ("/technologies/", "Technologies"),
    ("/lifesaver/", "Lifesaver"),
    ("/home-hub/", "Home Hub"),
    ("/about/", "About"),
    ("/contact/", "Contact"),
]


def asset_prefix(depth: int) -> str:
    return "../" * depth if depth else ""


def page(
    *,
    path: str,
    title: str,
    description: str,
    current: str,
    depth: int,
    body: str,
    theme: str = "corporate",
) -> str:
    prefix = asset_prefix(depth)
    nav = []
    for href, label in NAV:
        current_attr = ' aria-current="page"' if href == current else ""
        nav.append(f'<a href="{href}"{current_attr}>{label}</a>')
    nav_html = "\n          ".join(nav)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <meta name="description" content="{description}">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{ORIGIN}{path}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="AMICOR">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:url" content="{ORIGIN}{path}">
  <meta property="og:image" content="{ORIGIN}/assets/logo.svg">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{description}">
  <link rel="icon" href="{prefix}assets/logo.svg">
  <link rel="apple-touch-icon" href="{prefix}assets/logo.svg">
  <link rel="stylesheet" href="{prefix}assets/css/site.css">
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "AMICOR HEALTH ISF LLC",
    "alternateName": "AMICOR",
    "url": "{ORIGIN}/",
    "description": "Minnesota technology company building an integrated ecosystem across health, transportation, delivery, AI operations, and future intelligent hardware.",
    "email": "info@getamicor.com",
    "address": {{
      "@type": "PostalAddress",
      "addressRegion": "MN",
      "addressCountry": "US"
    }}
  }}
  </script>
</head>
<body class="theme-{theme}">
  <a class="skip" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="wrap header-row">
      <a class="brand" href="/">
        <img src="{prefix}assets/logo.svg" alt="AMICOR" width="36" height="36">
        <span>AMICOR</span>
      </a>
      <button class="menu-btn" type="button" data-menu-button aria-expanded="false" aria-controls="site-nav">Menu</button>
      <nav id="site-nav" class="nav" data-nav>
          {nav_html}
          <a class="nav-cta" href="/early-access/">Request Early Access</a>
      </nav>
    </div>
  </header>
  <main id="main">
    {body}
  </main>
  <footer class="site-footer">
    <div class="wrap footer-grid">
      <div>
        <strong>AMICOR</strong>
        <p>AMICOR HEALTH ISF LLC is a Minnesota technology company. Product availability varies. Unlaunched offerings are labeled Coming Soon, In Development, or Early Access.</p>
        <p><a href="mailto:info@getamicor.com">info@getamicor.com</a></p>
        <p>&copy; <span data-year></span> AMICOR HEALTH ISF LLC</p>
      </div>
      <div>
        <strong>Products</strong>
        <a href="/health/">AMICOR Health</a>
        <a href="/deliver/">AMICOR Deliver</a>
        <a href="/technologies/autonomous-operations-agent/">Operations Agent</a>
        <a href="/lifesaver/">Lifesaver AI Care Cloud</a>
        <a href="/home-hub/">Home Hub</a>
      </div>
      <div>
        <strong>Company</strong>
        <a href="/about/">About</a>
        <a href="/early-access/">Early Access</a>
        <a href="/contact/">Contact</a>
        <a href="/privacy/">Privacy Policy</a>
        <a href="/terms/">Terms of Service</a>
        <a href="/software-terms/">Software Terms</a>
        <a href="/accessibility/">Accessibility</a>
      </div>
    </div>
  </footer>
  <script src="{prefix}assets/js/site-config.js"></script>
  <script src="{prefix}assets/js/site.js"></script>
</body>
</html>
"""


PAGES: list[dict[str, object]] = []


def add(path: str, filename: str, title: str, description: str, current: str, depth: int, body: str, theme: str = "corporate") -> None:
    PAGES.append(
        {
            "filename": filename,
            "html": page(
                path=path,
                title=title,
                description=description,
                current=current,
                depth=depth,
                body=body,
                theme=theme,
            ),
        }
    )


add(
    "/",
    "index.html",
    "AMICOR — Intelligent Technology for Health, Transportation, Delivery and Operations",
    "AMICOR is a Minnesota technology company building one ecosystem across health, transportation, delivery, AI operations, and future intelligent hardware.",
    "/",
    0,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">AMICOR HEALTH ISF LLC</p>
        <h1>AMICOR</h1>
        <p class="lede">Intelligent Technology for Health, Transportation, Delivery and Operations.</p>
        <div class="hero-actions">
          <a class="btn btn-primary" href="#ecosystem">Explore AMICOR</a>
          <a class="btn btn-ghost" href="/early-access/">Request Early Access</a>
        </div>
      </div>
    </section>
    <section class="section" id="ecosystem">
      <div class="wrap">
        <h2>One AMICOR ecosystem</h2>
        <p class="lede">AMICOR connects software, operations, and future hardware under one parent brand. Products ship on different timelines. Status labels on this site are the public source of truth.</p>
        <article class="panel featured" style="margin:28px 0 24px">
          <span class="chip chip-early">Featured early access</span>
          <h3>Autonomous Operations Agent</h3>
          <p>The first AMICOR Technologies product: AI that watches an operation, recommends the next action, keeps humans in control, verifies results, and maintains an audit trail.</p>
          <div class="cta-row">
            <a class="btn btn-primary" href="/technologies/autonomous-operations-agent/">View software</a>
            <a class="btn btn-ghost" href="/early-access/?product=Autonomous%20Operations%20Agent">Request Early Access</a>
          </div>
        </article>
        <div class="grid grid-2">
          <article class="card"><span class="chip chip-dev">In Development</span><h3>AMICOR Health</h3><p>AI-enabled private-pay transportation technology and operations software. Commercial launch and local licensing are not implied.</p><a class="card-link" href="/health/">Learn more</a></article>
          <article class="card"><span class="chip chip-soon">Coming Soon</span><h3>AMICOR Deliver</h3><p>Planned local delivery technology and operations. Not commercially available.</p><a class="card-link" href="/deliver/">Learn more</a></article>
          <article class="card"><span class="chip chip-dev">In Development</span><h3>Lifesaver AI Care Cloud</h3><p>An AMICOR health-technology initiative for a connected, home-centered ecosystem. Not a medical device or emergency service.</p><a class="card-link" href="/lifesaver/">Learn more</a></article>
          <article class="card"><span class="chip chip-future">Future Hardware</span><h3>AMICOR Home Hub</h3><p>Planned physical gateway for local edge intelligence, device connectivity, and privacy controls.</p><a class="card-link" href="/home-hub/">Learn more</a></article>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Product status</h2>
        <p>This matrix is the source of truth for public claims on this website.</p>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Product</th><th>Public status</th><th>What this site claims</th></tr></thead>
            <tbody>
              <tr><td>AMICOR corporate website</td><td>LIVE</td><td>This public information site.</td></tr>
              <tr><td>Autonomous Operations Agent</td><td>EARLY ACCESS / IN DEVELOPMENT</td><td>Supervised operations software. Not autonomous production execution.</td></tr>
              <tr><td>AMICOR Health</td><td>IN DEVELOPMENT</td><td>Transportation technology. No current licensed-market claim.</td></tr>
              <tr><td>AMICOR Deliver</td><td>COMING SOON / IN DEVELOPMENT</td><td>Planned delivery technology only.</td></tr>
              <tr><td>Lifesaver AI Care Cloud</td><td>IN DEVELOPMENT</td><td>Health-technology initiative. No clinical or emergency claims.</td></tr>
              <tr><td>Home Hub</td><td>FUTURE HARDWARE / IN DEVELOPMENT</td><td>Planned device. Not for sale.</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
    """,
)

add(
    "/health/",
    "health/index.html",
    "AMICOR Health — Private-Pay Transportation Technology",
    "AMICOR Health is AI-enabled private-pay transportation technology covering rider experience, dispatch intelligence, driver operations, and operational safety. In development.",
    "/health/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">AMICOR Health</p>
        <h1>Transportation technology with operational intelligence.</h1>
        <p class="lede">AMICOR Health is the company's AI-enabled private-pay transportation technology and operations platform. It is designed around rider experience, dispatch intelligence, driver operations, and operational safety.</p>
        <p class="notice">Status: In Development. This page does not claim that AMICOR currently holds a local operating license, including in Minneapolis, or that rides are generally available to the public. Public commercial transportation launch is not implied.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Who this page is for</h2>
        <p class="lede">AMICOR Health is an ecosystem product inside one company. Different readers need different facts. The status label above applies to all of them.</p>
        <div class="grid grid-2" style="margin-top:24px">
          <article class="card"><h3>Customers</h3><p>Private-pay trip technology is in development. This website is not a consumer booking app and does not sell ride accounts.</p></article>
          <article class="card"><h3>Partners</h3><p>AMICOR Health is the transportation software and operations layer of the AMICOR ecosystem. Partnership conversations start from Early Access, not from a live market claim.</p></article>
          <article class="card"><h3>Insurers</h3><p>Use this page for product-scope review only. No coverage, risk-transfer, or licensed-market statements are made here.</p></article>
          <article class="card"><h3>Advisors</h3><p>Health is in development. Treat Coming Soon / In Development labels as limits on what is commercially available today.</p></article>
          <article class="card"><h3>Future drivers</h3><p>Driver tools are part of the intended platform. This site is not an application portal and does not invite public driving work in a licensed market.</p></article>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>What the platform is designed to cover</h2>
        <div class="grid grid-2">
        <article class="card"><h3>Rider experience</h3><p>Clear trip requests, status visibility, and a supervised handoff from request to completion.</p></article>
        <article class="card"><h3>Dispatch intelligence</h3><p>Recommendations and operational context for dispatchers. Human approval remains part of the intended operating model.</p></article>
        <article class="card"><h3>Driver operations</h3><p>Assignment, acceptance, and lifecycle tools intended to keep drivers and dispatchers working from the same source of truth.</p></article>
        <article class="card"><h3>Operational safety</h3><p>Status checks, exception visibility, and audit-minded records. These are product-design goals, not certified performance results.</p></article>
        </div>
      </div>
    </section>
    """,
    "health",
)

add(
    "/deliver/",
    "deliver/index.html",
    "AMICOR Deliver — Local Delivery Technology",
    "AMICOR Deliver is planned local delivery technology and operations. Coming soon and in development. Not commercially available.",
    "/deliver/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">AMICOR Deliver</p>
        <h1>Local delivery technology, when it is ready.</h1>
        <p class="lede">AMICOR Deliver is a planned product for local delivery technology and operations. It is part of the same AMICOR ecosystem, not a separate company or a live marketplace.</p>
        <p class="notice">Status: Coming Soon / In Development. AMICOR Deliver is not commercially launched and is not accepting public delivery orders.</p>
        <div class="hero-actions"><a class="btn btn-primary" href="/early-access/?product=AMICOR%20Deliver">Join the interest list</a></div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>What is planned</h2>
        <p class="lede">The intended platform covers request intake, courier assignment, route status, and operational oversight. These are design goals for a future product, not available services.</p>
        <div class="grid grid-2" style="margin-top:24px">
          <article class="card"><h3>Local delivery operations</h3><p>Software for coordinating pickup, handoff, and completion when the product is ready.</p></article>
          <article class="card"><h3>Courier workflow</h3><p>Planned assignment and status tools for couriers working inside the AMICOR ecosystem.</p></article>
          <article class="card"><h3>Shared operations intelligence</h3><p>Deliver is designed to sit beside AMICOR Health and the Autonomous Operations Agent, not as an isolated brand.</p></article>
          <article class="card"><h3>Not available today</h3><p>No consumer ordering, no merchant onboarding, and no courier hiring are offered on this website.</p></article>
        </div>
      </div>
    </section>
    """,
    "deliver",
)

add(
    "/technologies/",
    "technologies/index.html",
    "AMICOR Technologies — Software Product Catalog",
    "AMICOR Technologies is the software catalog for AMICOR products, starting with the Autonomous Operations Agent.",
    "/technologies/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">AMICOR Technologies</p>
        <h1>Software for operators who keep humans in control.</h1>
        <p class="lede">AMICOR Technologies is the software catalog inside the AMICOR ecosystem. The first featured product is the Autonomous Operations Agent.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <article class="panel">
          <span class="chip chip-early">Early Access / In Development</span>
          <h2>AMICOR Autonomous Operations Agent</h2>
          <p>AI that watches your operation, recommends the next action, keeps humans in control, verifies results, and maintains an audit trail.</p>
          <a class="btn btn-primary" href="/technologies/autonomous-operations-agent/">View product</a>
        </article>
      </div>
    </section>
    """,
    "tech",
)

add(
    "/technologies/autonomous-operations-agent/",
    "technologies/autonomous-operations-agent/index.html",
    "AMICOR Autonomous Operations Agent — Early Access Software",
    "The AMICOR Autonomous Operations Agent observes operations, recommends actions, requires human approval, verifies results, and keeps an audit trail. Early access. Preliminary pricing.",
    "/technologies/",
    2,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">AMICOR Technologies</p>
        <h1>Autonomous Operations Agent</h1>
        <p class="lede">AI that watches your operation, recommends the next action, keeps humans in control, verifies results, and maintains an audit trail.</p>
        <p class="notice">Status: Early Access / In Development. The agent is designed to supervise existing systems. It is not offered as unattended production execution.</p>
        <div class="hero-actions">
          <a class="btn btn-primary" href="/early-access/?product=Autonomous%20Operations%20Agent&amp;intent=demo">Request Demo</a>
          <a class="btn btn-ghost" href="/early-access/?product=Autonomous%20Operations%20Agent">Request Early Access</a>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>What it does</h2>
        <p class="lede">The product loop is observe, recommend, human approval, verify, and audit. After a person approves, existing operational systems perform the action. The agent does not run unattended production execution.</p>
        <div class="steps">
          <div class="step"><b>1</b><div><h3>OBSERVE</h3><p>Read live operational state from the systems you already run.</p></div></div>
          <div class="step"><b>2</b><div><h3>RECOMMEND</h3><p>Propose the next action using existing operational intelligence. Recommendation is not execution.</p></div></div>
          <div class="step"><b>3</b><div><h3>HUMAN APPROVAL</h3><p>Stop for a human decision. Approval stays with operators, dispatchers, or administrators. Approved work then continues through your current systems.</p></div></div>
          <div class="step"><b>4</b><div><h3>VERIFY</h3><p>Compare expected and actual state. Inconsistencies are reported, not silently repaired.</p></div></div>
          <div class="step"><b>5</b><div><h3>AUDIT</h3><p>Keep a correlated trail of what was observed, recommended, approved, and verified.</p></div></div>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Who it is for</h2>
        <div class="grid grid-2">
          <article class="card"><h3>Transportation</h3><p>Operators who need a supervised recommendation layer on live trip and assignment work.</p></article>
          <article class="card"><h3>NEMT</h3><p>Non-emergency medical transportation teams that keep humans in the approval path.</p></article>
          <article class="card"><h3>Courier / delivery</h3><p>Local delivery and courier operations that want observation and audit without unattended execution.</p></article>
          <article class="card"><h3>Fleet operations</h3><p>Fleet coordinators who need recommended next actions and a verifiable record.</p></article>
          <article class="card"><h3>Field-service operations</h3><p>Field teams that need the same observe-recommend-approve-verify loop across jobs and exceptions.</p></article>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Capabilities</h2>
        <div class="grid grid-3">
          <article class="card"><h3>Live operational observation</h3><p>Assemble ride, assignment, driver, and financial signals without replacing the source of truth.</p></article>
          <article class="card"><h3>Intelligent recommendations</h3><p>Wrap existing ranking and recommendation engines rather than inventing a parallel dispatcher.</p></article>
          <article class="card"><h3>Human approval controls</h3><p>The agent stops at approval. Autonomous production execution is not enabled in this program.</p></article>
          <article class="card"><h3>Exception detection</h3><p>Surface stale offers, conflicting state, and missing handoffs for human review.</p></article>
          <article class="card"><h3>Post-action verification</h3><p>After your system acts, confirm whether the result matches the expected state.</p></article>
          <article class="card"><h3>Operational audit trail</h3><p>One correlation identity can follow observation, recommendation, approval wait, verification, and exceptions.</p></article>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Preliminary pricing</h2>
        <p class="notice">Preliminary pricing / subject to change before commercial launch. These figures are planning prices, not an offer to sell. There is no payment checkout on this website.</p>
        <div class="price-grid" style="margin-top:20px">
          <article class="card price"><span class="chip chip-early">Early Access</span><h3>Early Access</h3><strong>Contact AMICOR</strong><p>Supervised evaluation. Request Early Access or a demo.</p></article>
          <article class="card price"><span class="chip chip-dev">Planned</span><h3>Starter</h3><strong>planned $149/month</strong><p>Preliminary pricing. Subject to change.</p></article>
          <article class="card price"><span class="chip chip-dev">Planned</span><h3>Growth</h3><strong>planned $399/month</strong><p>Preliminary pricing. Subject to change.</p></article>
          <article class="card price"><span class="chip chip-soon">Enterprise</span><h3>Business / Enterprise</h3><strong>Contact Sales</strong><p>Scoped after a conversation. No checkout.</p></article>
        </div>
        <div class="cta-row" style="margin-top:24px">
          <a class="btn btn-primary" href="/early-access/?product=Autonomous%20Operations%20Agent&amp;intent=demo">Request Demo</a>
          <a class="btn btn-ghost" href="/early-access/?product=Autonomous%20Operations%20Agent">Request Early Access</a>
        </div>
      </div>
    </section>
    """,
    "tech",
)

add(
    "/lifesaver/",
    "lifesaver/index.html",
    "Lifesaver AI Care Cloud — AMICOR Health Technology Initiative",
    "Lifesaver AI Care Cloud is an AMICOR health-technology initiative for a connected, home-centered ecosystem. In development. Not a medical or emergency service.",
    "/lifesaver/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">AMICOR health technology</p>
        <h1>Lifesaver AI Care Cloud</h1>
        <p class="lede">Lifesaver is an AMICOR initiative for a connected health-technology ecosystem: future Home Hub integration, a connected-device framework, and home-centered software services.</p>
        <p class="notice">Status: In Development. This is not a diagnostic product, emergency-response service, or clinically validated medical device. No regulatory approval or clinical-performance claims are made here.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>A connected health-technology direction</h2>
        <p class="lede">Lifesaver is software and architecture work inside the AMICOR ecosystem. It is not a substitute for clinical care, 911, or licensed medical devices.</p>
        <div class="grid grid-2" style="margin-top:24px">
          <article class="card"><h3>Connected health ecosystem</h3><p>A planned software environment that coordinates home, account, and operations services under the AMICOR brand.</p></article>
          <article class="card"><h3>Future Home Hub</h3><p>Designed to work with the planned AMICOR Home Hub as a local physical gateway, when that hardware exists.</p></article>
          <article class="card"><h3>Connected-device framework</h3><p>A future framework for linking compatible devices through privacy-minded account services. No device catalog is offered for sale here.</p></article>
          <article class="card"><h3>Privacy-centered architecture</h3><p>The intended design keeps household controls at the edge where possible and treats cloud services as complementary, not as a claim of certified privacy compliance.</p></article>
        </div>
      </div>
    </section>
    """,
    "lifesaver",
)

add(
    "/home-hub/",
    "home-hub/index.html",
    "AMICOR Home Hub — Planned Physical Gateway",
    "The AMICOR Home Hub is a planned physical gateway for local edge intelligence, device connectivity, and privacy controls. Future hardware. In development.",
    "/home-hub/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Future hardware</p>
        <h1>AMICOR Home Hub</h1>
        <p class="lede">The Home Hub is the planned physical / edge gateway into the AMICOR ecosystem. It is intended to keep more device control at the edge of the home. It does not contain every AMICOR backend system locally.</p>
        <p class="notice">Status: Future Hardware / In Development. The Home Hub is not available for purchase and is not a certified medical or emergency device.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Two layers, one ecosystem</h2>
        <div class="grid grid-2">
          <article class="panel">
            <h3>HOME HUB</h3>
            <p>Physical / edge gateway. Local device connectivity, household privacy controls, and edge intelligence that stay with the home.</p>
          </article>
          <article class="panel">
            <h3>AMICOR CLOUD</h3>
            <p>The main intelligence and business platform: AI, operations, coordination, account services, and company systems that complement the hub.</p>
          </article>
        </div>
        <p class="lede" style="margin-top:24px">The Home Hub connects into the broader AMICOR ecosystem. Transportation, delivery, operations software, and account services remain cloud-side or operations-side systems. The hub is a gateway, not a complete AMICOR data center in the home.</p>
      </div>
    </section>
    """,
    "hub",
)

add(
    "/about/",
    "about/index.html",
    "About AMICOR — Minnesota Technology Company",
    "AMICOR HEALTH ISF LLC is a Minnesota technology company building an integrated ecosystem across health, transportation, delivery, AI operations, and future intelligent hardware.",
    "/about/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">About</p>
        <h1>A Minnesota technology company.</h1>
        <p class="lede">AMICOR HEALTH ISF LLC is a Minnesota-based company. The public brand is AMICOR. We build an integrated technology ecosystem across software, operations, and future hardware.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Company facts we can state</h2>
        <div class="grid grid-2">
        <article class="card"><h3>Legal name</h3><p>AMICOR HEALTH ISF LLC. Public communications use AMICOR as the parent identity.</p></article>
        <article class="card"><h3>Location</h3><p>Minnesota, United States. This site does not publish a street address or invent office locations.</p></article>
        <article class="card"><h3>Integrated ecosystem</h3><p>Health, Deliver, Technologies, Lifesaver, and Home Hub are products and initiatives of one company, not separate public brands.</p></article>
        <article class="card"><h3>Software + operations + future hardware</h3><p>AMICOR combines operations software, future operating products, and planned physical gateways. Team size, customers, revenue, partnerships, certifications, and funding are not claimed here.</p></article>
        </div>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <p>We publish product status in plain language. Partners, insurers, grant reviewers, and advisors should treat Coming Soon, In Development, and Early Access labels as limits on what is commercially available today.</p>
      </div>
    </section>
    """,
)

add(
    "/early-access/",
    "early-access/index.html",
    "AMICOR Early Access and Partners",
    "Request AMICOR early access or partnership conversations. Validated form. Successful submit means AMICOR received the business inquiry.",
    "/early-access/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Partners / Early Access</p>
        <h1>Tell us what you want to explore.</h1>
        <p class="lede">This form is for customers, partners, insurers, reviewers, and advisors. A success message appears only after AMICOR’s lead store accepts the request. Do not submit medical records or other sensitive health information.</p>
        <p class="form-error" data-form-error role="alert"></p>
        <p class="form-success" data-form-success tabindex="-1" aria-live="polite">Thank you. Your request was sent to AMICOR.</p>
        <form class="panel" data-early-access-form novalidate>
          <div class="hp" aria-hidden="true">
            <label>Company website <input name="company_website" tabindex="-1" autocomplete="off" aria-hidden="true"></label>
          </div>
          <label>Name <input name="name" autocomplete="name" required></label>
          <label>Company <input name="company" autocomplete="organization" required></label>
          <label>Email <input name="email" type="email" autocomplete="email" required></label>
          <label>Phone <span class="optional">(optional)</span> <input name="phone" type="tel" autocomplete="tel"></label>
          <label>Industry <input name="industry" required></label>
          <label>Company size
            <select name="companySize" required>
              <option value="">Select</option>
              <option>1-10</option>
              <option>11-50</option>
              <option>51-200</option>
              <option>201-1000</option>
              <option>1000+</option>
            </select>
          </label>
          <label>Interested product
            <select name="product" id="product" required>
              <option value="">Select</option>
              <option>Autonomous Operations Agent</option>
              <option>AMICOR Health</option>
              <option>AMICOR Deliver</option>
              <option>Lifesaver AI Care Cloud</option>
              <option>Home Hub</option>
              <option>Partnership</option>
              <option>Other</option>
            </select>
          </label>
          <label>Message <textarea name="message" rows="5" required></textarea></label>
          <label class="consent">
            <input name="consent" type="checkbox" value="yes" required>
            <span>I understand this is not a purchase, I have read the <a href="/privacy/">Privacy Policy</a> draft, I will not submit medical records or other sensitive health information, and I consent to AMICOR storing this business inquiry.</span>
          </label>
          <button class="btn btn-primary" type="submit">Submit request</button>
        </form>
      </div>
    </section>
    """,
)

add(
    "/contact/",
    "contact/index.html",
    "Contact AMICOR",
    "Contact AMICOR HEALTH ISF LLC through the public website. Minnesota technology company. Use the early-access form for product and partnership inquiries.",
    "/contact/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Contact</p>
        <h1>Start with the public channel.</h1>
        <p class="lede">AMICOR HEALTH ISF LLC is a Minnesota company. For product, partnership, and review inquiries, use the Early Access form first. You can also write to <a href="mailto:info@getamicor.com">info@getamicor.com</a>. This page does not publish a street address or a personal inbox.</p>
        <p class="notice">A success message on the Early Access form means AMICOR stored the inquiry. That form works even if mailbox forwarding is not finished yet.</p>
        <p class="contact-channels">General contact: <a href="mailto:info@getamicor.com">info@getamicor.com</a></p>
        <div class="hero-actions">
          <a class="btn btn-primary" href="/early-access/">Open Early Access form</a>
          <a class="btn btn-ghost" href="/about/">About AMICOR</a>
        </div>
      </div>
    </section>
    """,
)


add(
    "/privacy/",
    "privacy/index.html",
    "Privacy Policy — AMICOR",
    "Business-draft privacy notice for the AMICOR public website. Not attorney-approved. AMICOR HEALTH ISF LLC, Minnesota.",
    "/privacy/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Business draft</p>
        <h1>Privacy Policy</h1>
        <p class="lede">This is a business draft for AMICOR HEALTH ISF LLC, a Minnesota company. It is not attorney-approved and is not a complete privacy program, HIPAA statement, or certification.</p>
        <p class="notice">Legal review is still required before this page is treated as governing terms. Do not submit medical records, diagnoses, insurance identifiers, or other sensitive health information through this website.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap grid grid-2">
        <article class="card"><h2>Who we are</h2><p>The public brand is AMICOR. The legal operator of this site is AMICOR HEALTH ISF LLC, Minnesota, United States. This page does not publish a street address.</p></article>
        <article class="card"><h2>What this site collects</h2><p>The Early Access form may collect name, company, email, optional phone, industry, company size, product interest, a message, a consent flag, and a timestamp. That is business-contact information, not clinical data.</p></article>
        <article class="card"><h2>How it is stored today</h2><p>When the Early Access form succeeds, the inquiry is stored in an AMICOR-owned Cloudflare lead store. An optional inbox webhook may be added later and must not replace that store. Browser storage is used only if live delivery fails.</p></article>
        <article class="card"><h2>What we do not claim</h2><p>This draft does not claim HIPAA compliance, medical-device compliance, sale of personal information, or that a live customer database already exists.</p></article>
      </div>
    </section>
    <section class="section">
      <div class="wrap">
        <h2>Cookies and analytics</h2>
        <p>This static site does not add a third-party analytics or advertising pixel. The browser may store a menu state or form fallback locally.</p>
        <h2>Questions</h2>
        <p>Use the <a href="/early-access/">Early Access form</a>, the <a href="/contact/">Contact</a> page, or <a href="mailto:info@getamicor.com">info@getamicor.com</a>. A form success message means AMICOR stored the business inquiry.</p>
      </div>
    </section>
    """,
)

add(
    "/terms/",
    "terms/index.html",
    "Terms of Service — AMICOR",
    "Business-draft website terms for AMICOR HEALTH ISF LLC. Not attorney-approved. No SLA, refund, or launch warranty.",
    "/terms/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Business draft</p>
        <h1>Terms of Service</h1>
        <p class="lede">These draft website terms describe use of the public AMICOR site operated by AMICOR HEALTH ISF LLC, Minnesota. They are not attorney-approved and are not a customer contract for transportation, delivery, software, or hardware.</p>
        <p class="notice">Legal review is still required. This page does not create warranties, refund rights, uptime promises, SLAs, insurance coverage, or licensed-market rights.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap grid grid-2">
        <article class="card"><h2>Informational site</h2><p>This website describes products and initiatives at different stages. Status labels — Early Access, In Development, Coming Soon, and Future Hardware — limit what is available today.</p></article>
        <article class="card"><h2>No commercial launch claim</h2><p>Using this site is not a booking, a delivery order, a software purchase, or a hardware sale. Preliminary prices are planning figures, not an offer to sell.</p></article>
        <article class="card"><h2>Acceptable use</h2><p>Do not misuse the form, attempt to inject content, or submit sensitive health information. We may ignore or discard abusive submissions.</p></article>
        <article class="card"><h2>As-is information</h2><p>Site content is provided as-is for public information. AMICOR does not warrant completeness, uninterrupted access, or fitness for a particular purpose on this page.</p></article>
      </div>
    </section>
    """,
)

add(
    "/software-terms/",
    "software-terms/index.html",
    "Software Terms — AMICOR",
    "Business-draft software terms for AMICOR Technologies early access. Not attorney-approved. Human approval required. No autonomous production execution.",
    "/software-terms/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Business draft</p>
        <h1>Software Terms</h1>
        <p class="lede">This draft applies to public discussion of AMICOR Technologies software, including the Autonomous Operations Agent. It is not attorney-approved and is not an executed license.</p>
        <p class="notice">Legal review is still required. There is no payment checkout on this website, no refund promise, no uptime SLA, and no grant of production execution rights.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap grid grid-2">
        <article class="card"><h2>Early Access / In Development</h2><p>The Autonomous Operations Agent is offered for supervised evaluation conversations only. It is not sold as unattended production execution.</p></article>
        <article class="card"><h2>Human approval</h2><p>The intended loop is observe, recommend, human approval, verify, and audit. After a person approves, existing operational systems perform the action.</p></article>
        <article class="card"><h2>Preliminary pricing</h2><p>Listed prices are preliminary and subject to change before commercial launch. Contact AMICOR is not an invoice.</p></article>
        <article class="card"><h2>Not a medical device</h2><p>AMICOR software described here is not a diagnostic product, emergency service, or certified medical device. No regulatory-approval claim is made.</p></article>
      </div>
    </section>
    """,
)

add(
    "/accessibility/",
    "accessibility/index.html",
    "Accessibility — AMICOR",
    "AMICOR accessibility goals for the public website. Business draft, not a WCAG certification.",
    "/accessibility/",
    1,
    """
    <section class="hero">
      <div class="wrap">
        <p class="kicker">Business draft</p>
        <h1>Accessibility</h1>
        <p class="lede">AMICOR HEALTH ISF LLC aims to keep this public website usable with keyboard, screen readers, and common phone sizes. This page is a business draft, not a WCAG certification or legal accessibility audit.</p>
        <p class="notice">Legal and accessibility review is still required. We do not claim certified conformance.</p>
      </div>
    </section>
    <section class="section">
      <div class="wrap grid grid-2">
        <article class="card"><h2>Current goals</h2><p>Skip link, labeled form fields, visible focus, heading order, 44-pixel tap targets, and text alternatives for the logo.</p></article>
        <article class="card"><h2>Known limits</h2><p>Legal pages remain drafts. The status table may scroll horizontally on small screens. Mailbox forwarding for info@getamicor.com is an owner Cloudflare step and may not be active yet.</p></article>
        <article class="card"><h2>Reporting a barrier</h2><p>Describe the page and the barrier through the <a href="/early-access/">Early Access form</a> or <a href="mailto:info@getamicor.com">info@getamicor.com</a>.</p></article>
        <article class="card"><h2>What this is not</h2><p>This statement is not a guarantee, not an ADA legal opinion, and not a claim that every AMICOR product interface is covered.</p></article>
      </div>
    </section>
    """,
)


def main() -> None:
    for item in PAGES:
        target = ROOT / str(item["filename"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item["html"]), encoding="utf-8")

    routes = [
        "/",
        "/health/",
        "/deliver/",
        "/technologies/",
        "/technologies/autonomous-operations-agent/",
        "/lifesaver/",
        "/home-hub/",
        "/about/",
        "/early-access/",
        "/contact/",
        "/privacy/",
        "/terms/",
        "/software-terms/",
        "/accessibility/",
    ]
    sitemap = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for route in routes:
        sitemap.extend(["  <url>", f"    <loc>{ORIGIN}{route}</loc>", "  </url>"])
    sitemap.append("</urlset>")
    (ROOT / "sitemap.xml").write_text("\n".join(sitemap) + "\n", encoding="utf-8")
    (ROOT / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {ORIGIN}/sitemap.xml\n",
        encoding="utf-8",
    )
    (ROOT / "404.html").write_text(
        page(
            path="/404.html",
            title="Page not found — AMICOR",
            description="The requested AMICOR page was not found.",
            current="/",
            depth=0,
            body='<section class="hero"><div class="wrap"><h1>Page not found</h1><p class="lede">That address is not part of the AMICOR public site.</p><a class="btn btn-primary" href="/">Return home</a></div></section>',
        ),
        encoding="utf-8",
    )
    print(f"Wrote {len(PAGES)} pages")


if __name__ == "__main__":
    main()
