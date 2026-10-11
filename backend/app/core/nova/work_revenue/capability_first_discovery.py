"""Capability-first nationwide discovery planning for Nova Work.

Discovery order:
  verified capability registry
  → allowed work families
  → targeted remote/vendor/contract queries
  → source discovery (caller)
  → duty classifier / qualification guards (caller)

This module never contacts employers, submits applications, or moves money.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.nova.v3.capability_catalog import CAPABILITIES as V3_CAPABILITIES
from app.core.nova.work_revenue.capability_classification import classify_opportunity_capability
from app.core.nova.work_revenue.capability_registry import list_capabilities, nova_supported_ids

# Preferred opportunity wording baked into generated queries.
_REMOTE_VENDOR_TERMS = (
    "remote",
    "contract",
    "contractor",
    "freelance",
    "independent contractor",
    "vendor",
)

# Owner-designated primary revenue lanes. These are searched first and receive
# a modest scoring boost when the discovered duties actually match Nova's
# verified digital capabilities. The order is intentional.
PRIMARY_REVENUE_FAMILIES: tuple[str, ...] = (
    "lead_generation_public_data",
    "content_media_processing",
    "b2b_workflow_automation",
    "api_micro_saas",
)

# Explicitly banned generic occupation searches.
_BANNED_QUERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdelivery driver\b", re.I),
    re.compile(r"\bwarehouse associate\b", re.I),
    re.compile(r"\bregistered nurse\b", re.I),
    re.compile(r"\bwarehouse jobs?\b", re.I),
    re.compile(r"\bdelivery driver jobs?\b", re.I),
    re.compile(r"\bregistered nurse jobs?\b", re.I),
    re.compile(r"\bjobs near me\b", re.I),
    re.compile(r"^\s*nurse\s*$", re.I),
    re.compile(r"^\s*truck driver\s*$", re.I),
)

_DOWNRANK_SIGNALS = re.compile(
    r"\b("
    r"w-2|w2|full-time employee|employee role|onsite|on-site|must report in person|"
    r"driver|physical labor|lifting|manual labor|shift work onsite|"
    r"licensed professional|rn required|cpa required|security clearance|"
    r"named[- ]person|talent network|"
    r"product designer|ux designer|ui designer|graphic designer|"
    r"software engineer|shopify developer|staff engineer|principal engineer|data scientist"
    r")\b",
    re.I,
)
_PREFERRED_SIGNALS = re.compile(
    r"\b("
    r"remote|contract|contractor|freelance|independent contractor|vendor|"
    r"consultant|project|b2b|fixed-price|hourly contract|remote services"
    r")\b",
    re.I,
)

# Remote digital / AI / administrative contractor searches. A query that is
# itself a physical trade search is not this intent.
_DIGITAL_SEARCH_INTENT = re.compile(
    r"\b("
    r"remote|worldwide|international|\bb2b\b|freelance|1099|contractor|independent contractor|project[- ]based|"
    r"virtual assistant|virtual assistance|administrative|admin support|"
    r"ai operations|ai workflow|automation support|workflow automation|"
    r"content operations|project coordination|crm|reporting|research|"
    r"data work|data entry|data cleanup|spreadsheet|bookkeeping"
    r")\b",
    re.I,
)
_DIGITAL_DOMAIN = re.compile(
    r"\b("
    r"ai operations|ai workflow|workflow automation|automation support|"
    r"administrative support|admin support|virtual assistant|virtual assistance|"
    r"project coordination|content operations|crm|customer relationship|"
    r"research|reporting|data entry|data cleanup|data work|spreadsheet|"
    r"bookkeeping support|bookkeeping|digital business operations"
    r")\b",
    re.I,
)
_CONTRACT_STYLE = re.compile(
    r"\b(remote|1099|freelance|freelancer|contractor|independent contractor|project[- ]based|contract)\b",
    re.I,
)
# Hard mismatches for a remote digital contractor search. Title text is included
# by the caller. This does not grant a positive capability match from a title.
_PHYSICAL_LICENSED_ONSITE_ROLE = re.compile(
    r"("
    r"\bwastewater\b|\bwater treatment operator\b|\butility operator\b|"
    r"\bclass\s*[abcd]\b.{0,48}\boperator\b|"
    r"\boperator\b.{0,48}\blicen[cs]e\b|\blicen[cs]ed operator\b|\boperator licen[cs]e\b|"
    r"\bcdl\b|\bcommercial driver(?:'s)? licen[cs]e\b|"
    r"\btruck driver\b|\bdelivery driver\b|\broute driver\b|\bbus driver\b|"
    r"\bforklift\b|"
    r"\bwarehouse\s+(?:associate|worker|clerk|laborer|technician)\b|"
    r"\bmanual labor\b|\bphysical labor\b|\bheavy lifting\b|"
    r"\bconstruction\s+(?:worker|laborer|labor|crew|site|trade)\b|\bjourneyman\b|"
    r"\broof(?:ing|er)?\b|\broof replacement\b|\bfacility maintenance\b|"
    r"\belectrician\b|\bplumber\b|\bpipefitter\b|\bwelder\b|\bcarpenter\b|"
    r"\bhvac\s+technician\b|\bmillwright\b|"
    r"\bnursing licen[cs]e\b|\bregistered nurse\b|\brn licen[cs]e\b|\blpn\b|\bcna\b|"
    r"\bmedical licen[cs]e\b|\bphysician\b|\bsurgeon\b|"
    r"\bbar admission\b|\blicensed attorney\b|\battorney licen[cs]e\b|\blaw licen[cs]e\b|"
    r"\bengineering licen[cs]e\b|\bpe licen[cs]e\b|\bprofessional engineer licen[cs]e\b|"
    r"\bsecurity clearance\b|"
    r"\bon-?site only\b|\bmust be on-?site\b|\bmandatory on-?site\b|"
    r"\bin-person only\b|\bphysical presence required\b|\bfully on-?site\b"
    r")",
    re.I,
)
_ONSITE_REMOTE_STATUS = frozenset({
    "on-site",
    "onsite",
    "on site",
    "in-person",
    "in person",
    "on-premise",
    "on premise",
})


def _listing_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(key) or "")
        for key in (
            "title",
            "opportunity_title",
            "description",
            "requirements",
            "skills",
            "skills_required",
            "credentials",
            "credentials_required",
            "remote_status",
            "place_of_performance",
            "geography",
            "job_type",
        )
    )


def _match_not_negated(pattern: re.Pattern[str], text: str) -> bool:
    for match in pattern.finditer(text or ""):
        prefix = text[max(0, match.start() - 20):match.start()]
        if re.search(r"\b(?:no|not|without|non-)\s*$", prefix, re.I):
            continue
        return True
    return False


def is_remote_digital_search_intent(query: str | None) -> bool:
    """True for remote digital, AI, or administrative contractor searches.

    An explicit physical-trade query is left alone so a direct wastewater or
    CDL search is not rewritten into a digital filter.
    """
    text = str(query or "").strip()
    if not text:
        return False
    if _match_not_negated(_PHYSICAL_LICENSED_ONSITE_ROLE, text) and not _DIGITAL_DOMAIN.search(text):
        return False
    if _DIGITAL_DOMAIN.search(text) or _DIGITAL_SEARCH_INTENT.search(text):
        return True
    return False


def is_physical_licensed_or_onsite_role(job: dict[str, Any]) -> bool:
    """Physical trades, operator/professional licenses, or mandatory on-site work."""
    remote = str(job.get("remote_status") or "").strip().lower().replace("_", " ")
    remote = remote.replace("-", " ")
    normalized = " ".join(remote.split())
    if normalized in _ONSITE_REMOTE_STATUS or normalized.replace(" ", "-") in _ONSITE_REMOTE_STATUS:
        return True
    if normalized in {"on site", "in person"}:
        return True
    return _match_not_negated(_PHYSICAL_LICENSED_ONSITE_ROLE, _listing_text(job))


def blocks_physical_role_for_digital_search(job: dict[str, Any], query: str | None) -> bool:
    """Drop physical/licensed/on-site roles from a remote digital contractor search."""
    if not is_physical_licensed_or_onsite_role(job):
        return False
    if is_remote_digital_search_intent(query):
        return True
    family_id = str(job.get("search_family") or "").strip()
    return bool(family_id and family_id in SEARCH_FAMILIES)


def digital_contractor_rank_signal(text: str) -> bool:
    """Remote/1099/freelance/contract digital work Nova should rank first."""
    return bool(_CONTRACT_STYLE.search(text or "") and _DIGITAL_DOMAIN.search(text or ""))


# Distinct work lanes in the owner's remote 1099 brief. A query that names
# two or more lanes is a union search: a listing may match any one lane.
_DIGITAL_QUERY_LANES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("ai", re.compile(r"\b(ai|artificial intelligence|automation|workflow automation|ai operations)\b", re.I)),
    ("admin", re.compile(r"\b(administrative support|admin support|virtual assistant|virtual assistance|data entry)\b", re.I)),
    ("research", re.compile(r"\bresearch\b", re.I)),
    ("reporting", re.compile(r"\breporting\b", re.I)),
    ("crm", re.compile(r"\bcrm\b", re.I)),
    ("content", re.compile(r"\bcontent operations\b", re.I)),
    ("coordination", re.compile(r"\bproject coordination\b", re.I)),
    ("digital_ops", re.compile(r"\bdigital business operations\b", re.I)),
)
_LISTING_LANE_TITLE = re.compile(
    r"\b("
    r"virtual assistant|virtual assistance|"
    r"administrative (?:assistant|support|coordinator|specialist)|"
    r"admin(?:istrative)? assistant|"
    r"operations assistant|"
    r"data entry|"
    r"research (?:assistant|contractor|support|specialist|analyst)|"
    r"business research|"
    r"reporting (?:assistant|specialist|coordinator|support)|"
    r"crm|"
    r"content operations|"
    r"project coordinat\w*|"
    r"automation|"
    r"ai operations|ai workflow|ai assistant|ai support|"
    r"artificial intelligence operations|"
    r"digital business operations|"
    r"business operations (?:assistant|support|coordinator)"
    r")\b",
    re.I,
)
# Management titles are not the contractor lanes in the remote 1099 brief.
_LEADERSHIP_TITLE = re.compile(
    r"\b("
    r"project manager|product manager|product lead|technical lead|"
    r"general manager|engineering manager|"
    r"director|head of|vice president|\bvp\b|\bchief\b"
    r")\b",
    re.I,
)
_NON_US_PLACE = re.compile(
    r"\b("
    r"south korea|seoul|north korea|india|chennai|germany|deutschland|france|"
    r"brazil|philippines|nigeria|singapore|japan|tokyo|china|beijing|dubai|"
    r"saudi arabia|riyadh|pakistan|bangladesh|vietnam|indonesia|poland|"
    r"ukraine|egypt|taiwan|united kingdom|\buk\b|london|toronto|australia|sydney"
    r")\b",
    re.I,
)
_US_OR_WORLD_PLACE = re.compile(
    r"\b(united states|u\.s\.a?\.?|\busa\b|worldwide|anywhere)\b",
    re.I,
)
_FOREIGN_LOCATION_REQUIREMENT = re.compile(
    r"\b(?:based|located|reside|residing|living|must be|candidates?|applicants?)\s+"
    r"(?:in|from|within)\s+$",
    re.I,
)


def digital_query_lanes(query: str | None) -> set[str]:
    """Work lanes named in a search, such as admin, research, or AI."""
    text = str(query or "")
    return {name for name, pattern in _DIGITAL_QUERY_LANES if pattern.search(text)}


def is_multi_lane_remote_digital_query(query: str | None) -> bool:
    """True when one remote digital search asks for two or more work lanes.

    A pure AI search stays on the AI duty gate. This brief is a union of
    AI, admin, research, CRM, and the other named lanes.
    """
    if not is_remote_digital_search_intent(query):
        return False
    return len(digital_query_lanes(query)) >= 2


# One explicit lane must match its own title family. A research description
# inside a copywriter or project-manager listing is not research work.
_SINGLE_LANE_TITLES: dict[str, re.Pattern[str]] = {
    "admin": re.compile(
        r"\b("
        r"virtual assistant|virtual assistance|"
        r"administrative (?:assistant|support|coordinator|specialist)|"
        r"admin(?:istrative)? assistant|"
        r"operations assistant|operations support|"
        r"office assistant|business operations support"
        r")\b",
        re.I,
    ),
    "research": re.compile(
        r"\b("
        r"research (?:assistant|contractor|support|specialist|analyst)|"
        r"business research|market research|internet research|competitor research"
        r")\b",
        re.I,
    ),
    "crm": re.compile(
        r"\b("
        r"crm|"
        r"customer (?:operations|data|support)|"
        r"data operations"
        r")\b",
        re.I,
    ),
}


def single_lane_title_match(job: dict[str, Any], query: str | None) -> bool | None:
    """Whether a one-lane search title belongs to that lane.

    None means the query is not a single admin, research, or CRM lane.
    """
    if not is_remote_digital_search_intent(query):
        return None
    lanes = digital_query_lanes(query)
    if len(lanes) != 1:
        return None
    pattern = _SINGLE_LANE_TITLES.get(next(iter(lanes)))
    if pattern is None:
        return None
    title = str(job.get("title") or job.get("opportunity_title") or "")
    if _LEADERSHIP_TITLE.search(title):
        return False
    return bool(pattern.search(title))


def matches_remote_digital_work_lane(job: dict[str, Any]) -> bool:
    """Title names a digital lane from the remote contractor brief.

    Bare "AI" is not a lane. AI trainer, product lead, and other management
    titles stay out even when the title also contains a lane word.
    """
    title = str(job.get("title") or job.get("opportunity_title") or "")
    if _LEADERSHIP_TITLE.search(title):
        return False
    return bool(_LISTING_LANE_TITLE.search(title))


def _role_is_remote(job: dict[str, Any]) -> bool:
    """True when the listing is remote work rather than a place the worker must occupy."""
    remote = str(job.get("remote_status") or "").strip().lower().replace("_", " ").replace("-", " ")
    if "remote" in remote or remote in {"worldwide", "anywhere", "global", "work from home", "wfh"}:
        return True
    return bool(re.search(
        r"\b(?:fully remote|remote|worldwide|work from anywhere|work from home)\b",
        _listing_text(job),
        re.I,
    ))


def non_us_location_required(job: dict[str, Any]) -> bool:
    """True when the worker must be outside the United States.

    A remote listing may name a client country. That is not a residency
    requirement. Explicit based, located, or reside language still is.
    Geography that also allows the United States or worldwide stays eligible.
    """
    blob = " ".join(
        str(job.get(key) or "")
        for key in ("title", "opportunity_title", "description", "requirements")
    )
    for match in _NON_US_PLACE.finditer(blob):
        prefix = blob[max(0, match.start() - 48):match.start()]
        if _FOREIGN_LOCATION_REQUIREMENT.search(prefix):
            return True
    geography = str(job.get("geography") or "")
    if _NON_US_PLACE.search(geography) and not _US_OR_WORLD_PLACE.search(geography):
        if _role_is_remote(job):
            return False
        return True
    return False


# Certifications and minimum-years claims Nova must not invent. Preferred or
# negated wording is ignored. Title text is included by the caller.
# Keep requirement verbs attached to the credential noun. Arbitrary proximity
# windows can consume a negation or attach an unrelated skill's requirement.
_CREDENTIAL = (
    r"(?:a |an )?(?:(?:professional|active|valid|current)\s+)*"
    r"(?:certifications?|certificates?|licen[cs]es?|"
    r"(?:pmp|capm|cpa|comptia|cissp|shrm(?:-cp|-scp)?|six sigma)"
    r"(?:\s+(?:certifications?|certificates?|licen[cs]es?|certified))?)"
)
_CREDENTIAL_LIST = rf"{_CREDENTIAL}(?:\s*(?:,\s*(?:(?:and|or)\s+)?|\s+(?:and|or)\s+){_CREDENTIAL})*"
_CERTIFICATION_OR_LICENSE_REQUIRED = re.compile(
    rf"(?:\b{_CREDENTIAL_LIST}\s*:?\s+(?:(?:is|are)\s+)?(?:not\s+)?(?:required|mandatory|a must)\b"
    rf"|\b{_CREDENTIAL_LIST}\s+must\s+be\s+(?:active|valid|current)\b"
    rf"|\b(?:must\s+(?:hold|have|possess|be)|required to\s+(?:hold|have|possess|be))\s+{_CREDENTIAL}\b"
    rf"|\b(?:required|mandatory)\s*:?\s+{_CREDENTIAL}\b"
    rf"|\brequires?\s+{_CREDENTIAL}\b"
    r"|\bmust be certified\b"
    r"|\bmust be licensed\b"
    r"|\blicensing\s+(?:is\s+)?(?:required|mandatory)\b)",
    re.I,
)
_EXPERIENCE_HISTORY_REQUIRED = re.compile(
    r"(?:"
    r"\b(?:at least|minimum(?: of)?|min\.?)\s+\d{1,2}\s*\+?\s+years?(?:'s)?(?: of)? (?:professional |relevant |related |industry )?(?:experience|exp)\b"
    r"|\b\d{1,2}\s*\+\s+years?(?:'s)?(?: of)? (?:professional |relevant |related |industry )?(?:experience|exp)\b"
    r"|\b\d{1,2}\s*(?:-|to)\s*\d{1,2}\s+years?(?:'s)?(?: of)? (?:professional |relevant |related )?(?:experience|exp)\b"
    r"|\byears of (?:professional |relevant |related )?experience required\b"
    r"|\b(?:must have|must possess|requires?)\s+(?:at least\s+)?\d{1,2}\s*\+?\s+years?(?:'s)?(?: of)? (?:professional |relevant |related |industry )?(?:experience|exp)\b"
    r"|\b\d{1,2}\s+years?(?:'s)?(?: of)? (?:professional |relevant |related |industry )?(?:experience|exp)\s+(?:(?:is|are)\s+)?(?:not\s+)?(?:required|mandatory)\b"
    r")",
    re.I,
)


def _required_claim(pattern: re.Pattern[str], text: str) -> bool:
    """True when a requirement is stated and not negated or marked preferred."""
    for match in pattern.finditer(text or ""):
        # Sentence/list boundaries prevent one qualification's optional wording
        # from excusing a separate mandatory qualification.
        prefix = re.split(r"[.;\n]", text[:match.start()])[-1]
        suffix = re.split(r"[.;\n]", text[match.end():])[0]
        if re.search(r"\bnot\s+(?:required|mandatory)\b", match.group(), re.I):
            continue
        if re.search(r"\b(?:no|not|without|non-|never)(?:\s+(?:a|an|any|the))?\s*$", prefix, re.I):
            continue
        if re.search(r"^\s*(?:is |are )?(?:not required|not mandatory)\b", suffix, re.I):
            continue
        # Explicit mandatory wording wins over a contradictory preference
        # label; bare years counts under that label remain non-blocking.
        if re.search(r"\b(?:must|required|mandatory|requires?)\b", match.group(), re.I) or re.search(
            r"^\s*(?:(?:is|are)\s+)?(?:required|mandatory)\b", suffix, re.I
        ):
            return True
        if re.search(r"^\s*(?:is |are )?(?:optional|preferred|a plus|nice to have)\b", suffix, re.I):
            continue
        if re.search(r"\b(?:preferred|optional|nice to have|a plus)\s*[:\-–—]?\s*$", prefix, re.I):
            continue
        return True
    return False


def certification_or_license_required(job: dict[str, Any]) -> bool:
    """Professional license or certification the verified profile does not hold."""
    return _required_claim(_CERTIFICATION_OR_LICENSE_REQUIRED, _listing_text(job))


def unverified_experience_required(job: dict[str, Any]) -> bool:
    """Minimum years of experience Nova would have to fabricate."""
    return _required_claim(_EXPERIENCE_HISTORY_REQUIRED, _listing_text(job))


def upfront_fee_required(job: dict[str, Any]) -> bool:
    """Payment to apply, membership, or other upfront access fee."""
    from app.core.nova.v3.live_qualification import FEE_YES, _detect_fee

    text = " ".join(
        (
            _listing_text(job),
            str(job.get("compensation_text") or ""),
        )
    ).lower()
    return _detect_fee(text) == FEE_YES


def remote_digital_performability_blockers(job: dict[str, Any], query: str | None) -> list[str]:
    """Reasons a remote digital search cannot treat this listing as performable.

    Physical/licensed/on-site roles stay on the existing gate. These extra
    reasons apply only when the owner asked for remote digital contractor work.
    """
    if not is_remote_digital_search_intent(query):
        return []
    reasons: list[str] = []
    if certification_or_license_required(job):
        reasons.append("certification_or_license_required")
    if unverified_experience_required(job):
        reasons.append("unverified_experience_required")
    if upfront_fee_required(job):
        reasons.append("upfront_fee_required")
    if non_us_location_required(job):
        reasons.append("non_us_location_required")
    from app.core.nova.work_revenue.international_match import international_blockers

    for code in international_blockers(job):
        if code not in reasons:
            reasons.append(code)
    if "non_us_location_required" in reasons and "residency_required" not in reasons:
        reasons.append("residency_required")
    return reasons
_STATE_RESTRICT = re.compile(
    r"\b("
    r"must (?:reside|live) in|residents? only|only (?:candidates|applicants) in|"
    r"(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
    r"florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|"
    r"maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|"
    r"nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|"
    r"north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|"
    r"south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|"
    r"wisconsin|wyoming) (?:residents?|only)"
    r")\b",
    re.I,
)

SEARCH_FAMILIES: dict[str, dict[str, Any]] = {
    "lead_generation_public_data": {
        "label": "Lead generation / permitted public-data research",
        "capability_ids": ("business_research", "data_spreadsheet", "ai_workflow_automation", "REPORTING", "RESEARCH"),
        "queries": (
            "fixed price lead list building public business directories freelance",
            "data scraping public directory contractor remote",
            "web data extraction public records freelance project",
            "B2B lead research list building contractor remote",
            "public business contact research spreadsheet freelance",
            "market data collection public sources fixed price project",
            "data extraction cleanup verification freelance contract",
            "real estate public records research spreadsheet contractor",
        ),
        "safety_notes": (
            "Use public or client-authorized sources only.",
            "Do not bypass authentication, CAPTCHAs, paywalls, or access controls.",
            "Avoid sensitive personal data and honor source terms and privacy requirements.",
        ),
    },
    "content_media_processing": {
        "label": "High-speed content / media processing",
        "capability_ids": ("content_documentation", "document_intelligence", "data_spreadsheet", "REPORTING"),
        "queries": (
            "podcast show notes transcription formatting fixed price freelance",
            "video transcript cleanup summary contractor remote",
            "content repurposing blog formatting freelance project",
            "timestamped show notes podcast contractor",
            "document cleanup reformatting batch freelance",
            "audio transcript summary fixed price project",
            "content operations turnaround contractor remote",
        ),
    },
    "b2b_workflow_automation": {
        "label": "Local B2B workflow automation",
        "capability_ids": ("ai_workflow_automation", "document_intelligence", "administrative_operations", "data_spreadsheet", "web_software"),
        "queries": (
            "small business workflow automation contractor",
            "email intake automation local business freelance",
            "document routing automation contractor remote",
            "CRM workflow automation small business project",
            "property management workflow automation contractor",
            "law firm intake automation freelance project",
            "trade contractor office automation project",
            "monthly operations automation retainer small business",
        ),
    },
    "api_micro_saas": {
        "label": "API / micro-SaaS implementation",
        "capability_ids": ("web_software", "ai_workflow_automation", "document_intelligence"),
        "queries": (
            "custom API endpoint freelance project remote",
            "document parser API contractor",
            "data parser microservice freelance",
            "webhook automation API integration fixed price",
            "RapidAPI custom API development freelance",
            "Make.com webhook integration contractor",
            "Zapier API integration freelance project",
            "text processing API microservice contractor",
        ),
        "verified_only": True,
    },
    "nova_anonymous_clients": {
        "label": "Nova Anonymous client acquisition",
        "capability_ids": (
            "administrative_operations",
            "business_research",
            "data_spreadsheet",
            "content_documentation",
            "customer_support_operations",
            "ai_workflow_automation",
            "document_intelligence",
            "proposal_rfp",
            "bookkeeping_support",
            "web_software",
        ),
        "queries": (
            "business operations support contractor remote",
            "AI workflow automation project contractor",
            "spreadsheet cleanup freelance project",
            "data cleaning contractor remote",
            "business research freelance project",
            "competitor research contractor remote",
            "document processing automation contract",
            "SOP writing contractor remote",
            "RFP proposal support contractor remote",
            "customer support workflow automation contractor",
            "CRM cleanup automation freelance project",
            "bookkeeping support contractor remote no CPA",
            "invoice tracking support contractor remote",
            "small web development contract project remote",
            "API integration freelance project remote",
        ),
    },

    "administrative_operations": {
        "label": "Administrative operations",
        "capability_ids": ("administrative_operations", "ADMINISTRATIVE_SUPPORT", "SCHEDULING_SUPPORT", "CRM_DATA_ORGANIZATION"),
        "queries": (
            "remote administrative support contractor",
            "virtual administrative assistant contractor",
            "operations support contractor remote",
            "document preparation contractor remote",
            "project administration remote contractor",
            "scheduling support independent contractor",
            "data entry contractor remote",
            "CRM cleanup freelance project",
            "workflow documentation contractor remote",
            "business operations support remote contractor",
        ),
    },
    "bookkeeping_support": {
        "label": "Bookkeeping / financial admin support",
        "capability_ids": ("bookkeeping_support",),
        "queries": (
            "bookkeeping support contractor remote no CPA",
            "bookkeeping cleanup remote contractor",
            "transaction categorization freelance project",
            "expense organization remote contractor",
            "invoice preparation administrative support contractor",
            "accounts receivable administrative support remote",
            "accounts payable administrative support remote",
            "reconciliation support remote contractor",
            "financial spreadsheet preparation freelance",
            "financial reporting support contractor remote",
        ),
        "block_terms": ("CPA required", "audit opinion", "tax signing", "licensed financial advice"),
    },
    "data_spreadsheet": {
        "label": "Data / spreadsheets / reporting",
        "capability_ids": ("data_spreadsheet", "REPORTING", "CRM_DATA_ORGANIZATION"),
        "queries": (
            "Excel contractor remote",
            "spreadsheet cleanup freelance project",
            "spreadsheet analysis remote contractor",
            "CSV cleanup freelance project",
            "data cleanup remote contractor",
            "data organization independent contractor",
            "data validation remote contractor",
            "reporting contractor remote",
            "dashboard report preparation freelance",
            "inventory data analysis remote contractor",
        ),
    },
    "research_analysis": {
        "label": "Research / analysis",
        "capability_ids": ("business_research", "RESEARCH"),
        "queries": (
            "internet research contractor remote",
            "business research freelance project",
            "market research assistant remote contractor",
            "competitor research freelance project",
            "supplier research remote contractor",
            "lead research freelance project",
            "information gathering remote contractor",
            "data research freelance project",
            "research report preparation remote contractor",
        ),
    },
    "document_writing": {
        "label": "Document / writing support",
        "capability_ids": ("content_documentation", "proposal_rfp", "document_intelligence", "DOCUMENT_PREPARATION", "PROPOSAL_DRAFTING"),
        "queries": (
            "business document preparation remote contractor",
            "report preparation freelance project",
            "proposal drafting remote contractor",
            "RFP support freelance project",
            "RFP proposal support contractor remote",
            "SOP creation remote contractor",
            "process documentation freelance project",
            "document formatting remote contractor",
            "presentation content freelance project",
            "business correspondence drafting remote",
            "content operations remote contractor",
        ),
    },
    "customer_support_operations": {
        "label": "Customer support / back office",
        "capability_ids": ("customer_support_operations", "CUSTOMER_FOLLOWUP_DRAFTING", "EMAIL_DRAFTING"),
        "queries": (
            "email support contractor remote",
            "chat support contractor remote",
            "customer support operations remote contractor",
            "ticket triage remote contractor",
            "FAQ support freelance project",
            "CRM organization remote contractor",
            "customer data cleanup freelance",
            "response drafting remote contractor",
        ),
        "owner_review_if": ("phone", "live phone", "named specialist", "AI policy unclear"),
    },
    "web_software": {
        "label": "Web / software / digital support",
        "capability_ids": ("web_software", "ai_workflow_automation"),
        "queries": (
            "website updates remote contractor",
            "HTML CSS fixes freelance project",
            "QA testing support remote contractor",
            "technical documentation freelance project",
            "website administration remote contractor",
            "data transformation freelance project",
            "workflow automation remote contractor",
            "API integration support freelance project",
            "software documentation remote contractor",
        ),
        "verified_only": True,
    },
    "logistics_digital": {
        "label": "Logistics / warehouse digital support",
        "capability_ids": ("data_spreadsheet", "business_research", "administrative_operations", "REPORTING"),
        "queries": (
            "remote inventory analyst contractor",
            "inventory reconciliation remote contractor",
            "warehouse reporting contractor remote",
            "logistics data support freelance project",
            "shipment tracking administration remote",
            "inventory data cleanup remote contractor",
            "logistics research freelance project",
            "warehouse documentation remote contractor",
            "route analysis remote contractor",
            "dispatch administrative support remote contractor",
        ),
        "never_generate": ("warehouse associate", "warehouse jobs"),
    },
    "transportation_digital": {
        "label": "Transportation / delivery digital support",
        "capability_ids": ("data_spreadsheet", "administrative_operations", "business_research", "REPORTING"),
        "queries": (
            "dispatch support contractor remote",
            "route planning support remote contractor",
            "transportation reporting freelance project",
            "shipment tracking remote contractor",
            "logistics administration remote contractor",
            "delivery data analysis remote contractor",
            "delivery documentation remote contractor",
            "fleet spreadsheet reporting remote contractor",
        ),
        "never_generate": ("delivery driver", "delivery driver jobs"),
    },
    "healthcare_non_clinical": {
        "label": "Healthcare non-clinical support",
        "capability_ids": ("administrative_operations", "data_spreadsheet", "content_documentation", "document_intelligence"),
        "queries": (
            "healthcare administrative support remote contractor",
            "healthcare data cleanup freelance project",
            "records organization remote contractor",
            "medical document formatting remote contractor",
            "non-clinical scheduling support remote",
            "healthcare reporting support remote contractor",
            "healthcare operations research freelance",
        ),
        "never_generate": ("registered nurse", "registered nurse jobs", "clinical practitioner"),
        "block_terms": ("diagnosis", "treatment", "patient care", "medication administration", "clinical judgment"),
    },
    "ai_automation": {
        "label": "AI / automation contract work",
        "capability_ids": ("ai_workflow_automation", "document_intelligence", "content_documentation"),
        "queries": (
            "AI operations contractor remote",
            "AI workflow automation contractor remote",
            "AI workflow support freelance project",
            "AI research support remote contractor",
            "automation contractor remote",
            "prompt document workflow support freelance",
            "AI content operations remote contractor",
            "AI data quality freelance project",
            "AI evaluation contractor remote vendor allowed",
        ),
        "respect_ai_policy": True,
    },
}


_FAMILY_REQUEST_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("lead_generation_public_data", re.compile(r"\b(lead generation|lead list|list building|data scraping|web scraping|data extraction|public records|public directory|market data)\b", re.I)),
    ("content_media_processing", re.compile(r"\b(transcription|show notes|podcast|content repurposing|transcript cleanup|timestamped|media formatting|blog formatting)\b", re.I)),
    ("b2b_workflow_automation", re.compile(r"\b(b2b automation|business automation|workflow automation|intake automation|document routing|crm automation|email automation)\b", re.I)),
    ("api_micro_saas", re.compile(r"\b(api endpoint|micro[- ]?saas|microservice|rapidapi|webhook|api integration|document parser|data parser)\b", re.I)),
    ("nova_anonymous_clients", re.compile(r"\b(nova anonymous|amicor anonymous|anonymous operations agent|anonymous operation agent|autonomous operations agent|autonomous operation agent)\b", re.I)),
    ("bookkeeping_support", re.compile(r"\b(bookkeep(?:ing)?|accounts? payable|accounts? receivable|reconciliation|invoice prep|expense categorization|financial spreadsheet)\b", re.I)),
    ("document_writing", re.compile(r"\b(writing|writer|document|proposal|rfp|sop|content writing|content writer|report writing|business correspondence)\b", re.I)),
    ("research_analysis", re.compile(r"\b(research|market research|competitor research|lead research|supplier research|analysis research)\b", re.I)),
    ("data_spreadsheet", re.compile(r"\b(spreadsheet|excel|csv|data cleanup|data entry|data analysis|reporting|inventory data)\b", re.I)),
    ("ai_automation", re.compile(r"\b(ai|artificial intelligence|automation|prompt|workflow automation|ai analysis|ai operations)\b", re.I)),
    ("customer_support_operations", re.compile(r"\b(customer support|chat support|email support|ticket|faq|customer service|back office)\b", re.I)),
    ("web_software", re.compile(r"\b(web|website|html|css|api|software|technical documentation|qa testing)\b", re.I)),
    ("administrative_operations", re.compile(r"\b(admin(?:istrative)?|virtual assistant|office support|operations support|scheduling|crm|clerical)\b", re.I)),
    ("logistics_digital", re.compile(r"\b(logistics|warehouse reporting|inventory reconciliation|shipment tracking|dispatch admin)\b", re.I)),
    ("transportation_digital", re.compile(r"\b(transportation|delivery data|fleet reporting|route planning|dispatch support)\b", re.I)),
    ("healthcare_non_clinical", re.compile(r"\b(healthcare admin|medical document|non-clinical|records organization|healthcare reporting)\b", re.I)),
)


def resolve_requested_families(query: str) -> list[str]:
    """Resolve every capability family explicitly requested by the owner."""
    text = re.sub(r"\s+", " ", str(query or "").strip())
    if not text:
        return []
    return [
        family_id
        for family_id, pattern in _FAMILY_REQUEST_PATTERNS
        if pattern.search(text)
    ]


def resolve_requested_family(query: str) -> str | None:
    """Backward-compatible single-family resolver."""
    families = resolve_requested_families(query)
    return families[0] if families else None


def targeted_queries_for_request(query: str, *, max_queries: int = 5) -> list[dict[str, Any]]:
    """Return capability-backed query variants for the owner's requested work.

    Compound owner requests are split across the explicitly named capability
    families instead of being mislabeled as only the first matching family.
    """
    normalized = re.sub(r"\s+", " ", str(query or "").strip())
    if not normalized:
        return []
    limit = max(1, int(max_queries))
    family_ids = resolve_requested_families(normalized)
    if not family_ids:
        return [{
            "query": normalized,
            "search_family": None,
            "search_family_label": "User-specified work",
            "capability_registry_matches": [],
            "why_searched": "Exact user-specified search; no capability family inferred.",
            "geography": "United States remote nationwide",
            "preferred_signals": list(_REMOTE_VENDOR_TERMS),
        }]

    supported = _supported_capability_keys()
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    # For a compound request, give each requested family at least one focused
    # query before adding variants. This prevents one broad family from
    # consuming the whole search budget.
    for family_id in family_ids:
        if len(rows) >= limit:
            break
        generated = generate_capability_first_queries(families=[family_id])
        candidate = generated[0] if generated else None
        if candidate is None:
            continue
        key = str(candidate["query"]).lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(candidate)

    # Fill any remaining budget round-robin from the requested families.
    offsets = {family_id: 1 for family_id in family_ids}
    while len(rows) < limit:
        added = False
        for family_id in family_ids:
            generated = generate_capability_first_queries(families=[family_id])
            index = offsets[family_id]
            offsets[family_id] = index + 1
            if index >= len(generated):
                continue
            item = generated[index]
            key = str(item["query"]).lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(item)
            added = True
            if len(rows) >= limit:
                break
        if not added:
            break

    # If only one family was requested, preserve the owner's exact wording as
    # the first query while retaining the family label.
    if len(family_ids) == 1:
        family_id = family_ids[0]
        exact = {
            "query": normalized,
            "search_family": family_id,
            "search_family_label": SEARCH_FAMILIES[family_id]["label"],
            "capability_registry_matches": [
                cid for cid in SEARCH_FAMILIES[family_id]["capability_ids"] if cid in supported
            ],
            "why_searched": f"Owner requested {SEARCH_FAMILIES[family_id]['label']}; Nova restricted discovery to this capability family.",
            "geography": "United States remote nationwide",
            "preferred_signals": list(_REMOTE_VENDOR_TERMS),
        }
        rows = [exact] + [row for row in rows if str(row["query"]).lower() != normalized.lower()]
        rows = rows[:limit]
    return rows


def _supported_capability_keys() -> set[str]:
    keys = set(nova_supported_ids())
    keys.update(V3_CAPABILITIES.keys())
    # availability filter from work_revenue registry
    for row in list_capabilities():
        if row.get("availability") in {"AVAILABLE", "AVAILABLE_WITH_OWNER_REVIEW"}:
            keys.add(str(row.get("capability_id")))
    return keys


def is_banned_query(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return True
    return any(pattern.search(text) for pattern in _BANNED_QUERY_PATTERNS)


def _family_supported(family: dict[str, Any], supported: set[str]) -> bool:
    ids = family.get("capability_ids") or ()
    if family.get("verified_only"):
        return any(item in supported for item in ids)
    return any(item in supported for item in ids) or True


def generate_capability_first_queries(
    *,
    families: list[str] | None = None,
    include_nationwide_remote: bool = True,
) -> list[dict[str, Any]]:
    """Build targeted discovery queries from verified capabilities and families."""
    supported = _supported_capability_keys()
    selected = families or [
        *PRIMARY_REVENUE_FAMILIES,
        *[family_id for family_id in SEARCH_FAMILIES.keys() if family_id not in PRIMARY_REVENUE_FAMILIES],
    ]
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for family_id in selected:
        family = SEARCH_FAMILIES.get(family_id)
        if not family:
            continue
        if not _family_supported(family, supported):
            continue
        matched_caps = [cid for cid in family["capability_ids"] if cid in supported]
        for query in family["queries"]:
            q = str(query).strip()
            if not q or is_banned_query(q):
                continue
            if not re.search(r"\b(remote|freelance|contractor)\b", q, re.I):
                q = f"{q} remote contractor"
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "query": q,
                    "search_family": family_id,
                    "search_family_label": family["label"],
                    "capability_registry_matches": matched_caps,
                    "why_searched": (
                        f"Capability-first nationwide remote/digital search for {family['label']} "
                        "using verified Nova capabilities."
                    ),
                    "geography": "United States remote nationwide" if include_nationwide_remote else "remote",
                    "preferred_signals": list(_REMOTE_VENDOR_TERMS),
                }
            )
    return rows


def capability_first_search_queries(*, families: list[str] | None = None) -> list[str]:
    return [row["query"] for row in generate_capability_first_queries(families=families)]


def search_family_catalog() -> list[dict[str, Any]]:
    supported = _supported_capability_keys()
    rows: list[dict[str, Any]] = []
    for family_id, family in SEARCH_FAMILIES.items():
        rows.append(
            {
                "family_id": family_id,
                "label": family["label"],
                "capability_ids": list(family["capability_ids"]),
                "supported": _family_supported(family, supported),
                "query_count": len(
                    [q for q in family["queries"] if not is_banned_query(q)]
                ),
                "sample_queries": [q for q in family["queries"] if not is_banned_query(q)][:3],
                "never_generate": list(family.get("never_generate") or ()),
            }
        )
    return rows


_FAMILY_TEXT_EVIDENCE: dict[str, re.Pattern[str]] = {
    "lead_generation_public_data": re.compile(
        r"\b(lead list|lead generation|list building|public directory|public records|"
        r"data scraping|web scraping|data extraction|contact research|market data collection)\b",
        re.I,
    ),
    "content_media_processing": re.compile(
        r"\b(transcription|transcript cleanup|show notes|podcast notes|timestamped notes|"
        r"content repurposing|blog formatting|media processing|document reformatting)\b",
        re.I,
    ),
    "b2b_workflow_automation": re.compile(
        r"\b(workflow automation|intake automation|document routing|crm automation|"
        r"email automation|business automation|operations automation|zapier|make\.com|n8n)\b",
        re.I,
    ),
    "api_micro_saas": re.compile(
        r"\b(api endpoint|api integration|microservice|micro[- ]?saas|rapidapi|"
        r"webhook|document parser|data parser|text processing api)\b",
        re.I,
    ),
    "administrative_operations": re.compile(
        r"\b(administrative support|administrative operations|virtual assistant|"
        r"document preparation|project administration|scheduling support|data entry|"
        r"crm (?:cleanup|organization)|workflow documentation|business operations support)\b",
        re.I,
    ),
    "bookkeeping_support": re.compile(
        r"\b(bookkeep(?:ing)?|accounts? payable|accounts? receivable|reconciliation|"
        r"invoice (?:tracking|preparation|processing)|expense (?:organization|categorization)|"
        r"financial spreadsheet|transaction categorization|ledger|quickbooks|xero)\b",
        re.I,
    ),
    "data_spreadsheet": re.compile(
        r"\b(spreadsheet|excel|google sheets|csv|data cleanup|data cleaning|"
        r"data validation|data organization|dashboard reporting|inventory data analysis)\b",
        re.I,
    ),
    "research_analysis": re.compile(
        r"\b(internet research|business research|market research|competitor research|"
        r"supplier research|lead research|information gathering|research report|data research)\b",
        re.I,
    ),
    "document_writing": re.compile(
        r"\b(business document|proposal drafting|rfp support|sop (?:creation|writing)|"
        r"process documentation|document formatting|business correspondence|"
        r"report preparation|content operations)\b",
        re.I,
    ),
    "customer_support_operations": re.compile(
        r"\b(email support|chat support|customer support operations|ticket triage|"
        r"faq support|response drafting|support knowledge base|crm organization)\b",
        re.I,
    ),
    "web_software": re.compile(
        r"\b(website updates?|html|css|qa testing|technical documentation|"
        r"website administration|api integration|software documentation|web development)\b",
        re.I,
    ),
    "logistics_digital": re.compile(
        r"\b(inventory reconciliation|warehouse reporting|logistics data support|"
        r"shipment tracking|inventory data cleanup|warehouse documentation|route analysis|"
        r"dispatch administrative support|inventory analyst)\b",
        re.I,
    ),
    "transportation_digital": re.compile(
        r"\b(dispatch support|route planning|transportation reporting|shipment tracking|"
        r"logistics administration|delivery data analysis|delivery documentation|"
        r"fleet spreadsheet reporting)\b",
        re.I,
    ),
    "healthcare_non_clinical": re.compile(
        r"\b(healthcare administrative support|healthcare data cleanup|records organization|"
        r"medical document formatting|non-clinical scheduling support|"
        r"healthcare reporting support|healthcare operations research)\b",
        re.I,
    ),
    "ai_automation": re.compile(
        r"\b(ai workflow automation|ai workflow support|workflow automation|"
        r"ai research support|automation contractor|prompt (?:document )?workflow|"
        r"ai content operations|ai data quality|api integration|zapier|make\.com|n8n|"
        r"prompt engineering|llm|ai agent|agent workflow)\b",
        re.I,
    ),
}


def _family_text_evidence(family_id: str | None, text: str) -> bool | None:
    pattern = _FAMILY_TEXT_EVIDENCE.get(str(family_id or "").strip())
    if pattern is None:
        return None
    return bool(pattern.search(str(text or "")))


_FAMILY_DUTY_MATCHES: dict[str, frozenset[str]] = {
    "lead_generation_public_data": frozenset({
        "research", "spreadsheet_analysis", "data_organization", "reporting",
    }),
    "content_media_processing": frozenset({
        "content_operations", "document_preparation", "reporting", "data_organization",
    }),
    "b2b_workflow_automation": frozenset({
        "ai_assisted_analysis", "workflow_documentation", "document_preparation",
        "data_organization", "web_software_support", "administrative_support",
    }),
    "api_micro_saas": frozenset({
        "web_software_support", "ai_assisted_analysis", "data_organization",
        "document_preparation",
    }),
    "administrative_operations": frozenset({
        "administrative_support", "data_organization", "document_preparation",
        "workflow_documentation", "reporting", "spreadsheet_analysis",
    }),
    "bookkeeping_support": frozenset({
        "bookkeeping_support", "spreadsheet_analysis", "reporting", "data_organization",
    }),
    "data_spreadsheet": frozenset({
        "spreadsheet_analysis", "reporting", "data_organization",
    }),
    "research_analysis": frozenset({
        "research", "reporting", "spreadsheet_analysis",
    }),
    "ai_automation": frozenset({
        "ai_assisted_analysis", "workflow_documentation", "document_preparation",
        "data_organization", "reporting", "research", "content_operations",
        "web_software_support",
    }),
}


def _planned_family_duty_match(family_id: str | None, duty_matches: list[str]) -> bool | None:
    """Whether discovered duties actually fit the capability family that found the row.

    None means the family does not yet have a strict mapping and keeps legacy scoring.
    """
    allowed = _FAMILY_DUTY_MATCHES.get(str(family_id or "").strip())
    if allowed is None:
        return None
    normalized_matches = {
        str(item or "").strip()
        for item in duty_matches
        if str(item or "").strip()
    }
    # No classified duty evidence is not the same as a confirmed family mismatch.
    # Preserve the caller's INSUFFICIENT_INFORMATION/owner-review path instead of
    # turning sparse provider records into a hard REJECT.
    if not normalized_matches:
        return None
    return bool(allowed.intersection(normalized_matches))


def score_discovery_candidate(job: dict[str, Any], *, query: str | None = None) -> dict[str, Any]:
    """Immediate post-discovery scoring before or with qualification."""
    text = " ".join(
        str(job.get(key) or "")
        for key in ("title", "description", "job_type", "geography", "compensation_text", "remote_status")
    )
    duty = classify_opportunity_capability(
        {
            "title": job.get("title") or job.get("opportunity_title"),
            "description": job.get("description"),
            "requirements": job.get("requirements"),
            "skills_required": job.get("skills_required"),
            "credentials_required": job.get("credentials_required"),
            "engagement_type": job.get("job_type") or job.get("engagement_type"),
            "remote_status": job.get("remote_status") or "remote",
            "physical_presence_required": job.get("physical_presence_required") or "unknown",
            "ai_policy": job.get("ai_policy"),
        }
    )
    score = 55
    preferred_hits = len(_PREFERRED_SIGNALS.findall(text))
    downrank_hits = len(_DOWNRANK_SIGNALS.findall(text))
    score += min(25, preferred_hits * 4)
    score -= min(40, downrank_hits * 12)

    remote_ok = "remote" in text.lower() or str(job.get("remote_status") or "").lower() == "remote"
    if remote_ok:
        score += 8
    else:
        score -= 20

    state_restricted = bool(_STATE_RESTRICT.search(text))
    if state_restricted:
        score -= 8

    classification = duty["capability_classification"]
    if classification == "CAN_PERFORM":
        score += 20
    elif classification == "NEEDS_OWNER_REVIEW":
        score += 5
    elif classification == "INSUFFICIENT_INFORMATION":
        score = min(score, 45)
    else:
        score = min(score, 35)

    score = max(0, min(100, score))
    if classification == "INSUFFICIENT_INFORMATION":
        band = "INSUFFICIENT_INFORMATION"
    elif score >= 80:
        band = "STRONG_FIT"
    elif score >= 60:
        band = "OWNER_REVIEW"
    else:
        band = "REJECT"

    family = match_query_to_family(query or "")
    planned_family_id = str(job.get("search_family") or "").strip() or None
    planned_family = SEARCH_FAMILIES.get(planned_family_id) if planned_family_id else None
    family_candidates = [
        str(item or "").strip()
        for item in list(job.get("search_family_candidates") or [])
        if str(item or "").strip()
    ]
    if planned_family_id and planned_family_id not in family_candidates:
        family_candidates.insert(0, planned_family_id)

    duty_matches = list(duty["capability_registry_matches"])
    candidate_matches = [
        _planned_family_duty_match(family_id, duty_matches)
        for family_id in family_candidates
    ]
    if any(match is True for match in candidate_matches):
        family_duty_match = True
    elif candidate_matches and all(match is False for match in candidate_matches):
        family_duty_match = False
    elif planned_family_id:
        family_duty_match = _planned_family_duty_match(planned_family_id, duty_matches)
    else:
        family_duty_match = None
    # Search-provider keyword hits are not enough. When structured duty
    # classification is sparse, require concrete text evidence for at least one
    # planned family. This is the generic anti-drift gate used across all major
    # capability families, rather than adding one-off filters for every bad title.
    if family_duty_match is None and family_candidates and not duty_matches:
        evidence_matches = [
            _family_text_evidence(family_id, text)
            for family_id in family_candidates
        ]
        known_evidence = [match for match in evidence_matches if match is not None]
        if any(match is True for match in known_evidence):
            family_duty_match = True
        elif known_evidence:
            family_duty_match = False

        obvious_human_evaluator = bool(
            re.search(
                r"\b(ai trainer|model evaluator|quality evaluator|human evaluator|rater|annotator|"
                r"rate model responses|evaluate model responses|image qa evaluator)\b",
                text,
                re.I,
            )
        )
        if obvious_human_evaluator:
            family_duty_match = False

    if family_duty_match is False:
        score = min(score, 35)
        band = "REJECT"
    elif planned_family_id in PRIMARY_REVENUE_FAMILIES and family_duty_match is True:
        # Owner-designated revenue priorities get a modest boost only after
        # concrete duty evidence confirms the fit.
        score = min(100, score + 10)
        if band != "INSUFFICIENT_INFORMATION":
            if score >= 80:
                band = "STRONG_FIT"
            elif score >= 60:
                band = "OWNER_REVIEW"
            else:
                band = "REJECT"

    # Title text may disqualify a hard physical/licensed/on-site role. It still
    # does not grant a positive capability match (title_used_for_decision stays false).
    physical_blocked = blocks_physical_role_for_digital_search(job, query)
    performability_blockers = remote_digital_performability_blockers(job, query)
    from app.core.nova.work_revenue.international_match import assess_international_match

    international = assess_international_match(job)
    lane_decision = single_lane_title_match(job, query)
    lane_mismatch = bool(
        (is_multi_lane_remote_digital_query(query) and not matches_remote_digital_work_lane(job))
        or lane_decision is False
    )
    digital_rank_boost = False
    if physical_blocked or performability_blockers or lane_mismatch:
        score = min(score, 15)
        band = "REJECT"
    elif (
        lane_decision is True
        and band == "REJECT"
        and family_duty_match is False
    ):
        # The title is the requested lane. A narrow family-text miss should not
        # hide an admin, research, or CRM role the owner asked for.
        band = "OWNER_REVIEW"
        score = max(score, 60)
    elif band not in {"INSUFFICIENT_INFORMATION", "REJECT"} and digital_contractor_rank_signal(text):
        digital_rank_boost = True
        score = min(100, score + 18)
        if score >= 80:
            band = "STRONG_FIT"
        elif score >= 60:
            band = "OWNER_REVIEW"
        else:
            band = "REJECT"
    return {
        "discovery_score": score,
        "discovery_band": band,
        "capability_match": bool(duty["capability_registry_matches"]),
        "planned_family_duty_match": family_duty_match,
        "search_family_candidates": family_candidates,
        "remote_eligibility": "YES" if remote_ok else "NO",
        "vendor_contract_compatibility": "YES" if preferred_hits else "UNKNOWN",
        "physical_presence_requirement": duty["required_physical_presence"],
        "license_requirement": duty["required_license_or_credential"] or "NONE",
        "AI_policy": job.get("ai_policy") or "unknown",
        "human_identity_requirement": "YES" if "named" in text.lower() or "talent network" in text.lower() else "NO",
        "fee_to_apply": "unknown",
        "compensation_signal": "YES" if job.get("compensation_text") else "UNKNOWN",
        "actual_duty_fit": classification,
        "capability_classification": classification,
        "capability_registry_matches": duty["capability_registry_matches"],
        "nova_can_do": duty["nova_can_do"],
        "nova_cannot_do": duty["nova_cannot_do"],
        "deliverables_nova_can_produce": duty["deliverables_nova_can_produce"],
        "owner_review_needed": duty["owner_review_needed"] or band == "OWNER_REVIEW",
        "state_restriction_detected": state_restricted,
        "physical_licensed_onsite_blocked": physical_blocked,
        "remote_digital_blockers": performability_blockers,
        "remote_digital_lane_mismatch": lane_mismatch,
        "certification_or_license_blocked": "certification_or_license_required" in performability_blockers,
        "unverified_experience_blocked": "unverified_experience_required" in performability_blockers,
        "upfront_fee_blocked": "upfront_fee_required" in performability_blockers,
        "native_fluency_blocked": "native_fluency_required" in performability_blockers,
        "residency_blocked": "residency_required" in performability_blockers,
        "citizenship_blocked": "citizenship_required" in performability_blockers,
        "permit_blocked": "permit_required" in performability_blockers,
        "untested_language_blocked": "untested_language_required" in performability_blockers,
        "language_support": international["language_support"],
        "tested_language_codes": international["tested_language_codes"],
        "native_fluency_claimed": False,
        "ai_translation_is_native_fluency": False,
        "digital_contractor_rank_boost": digital_rank_boost,
        "search_family": planned_family_id or (family or {}).get("family_id"),
        "search_family_label": str(job.get("search_family_label") or "").strip()
        or (planned_family or {}).get("label")
        or (family or {}).get("label"),
        "why_searched": str(job.get("why_searched") or "").strip()
        or (family or {}).get("why_searched")
        or "Capability-first remote/digital discovery against verified Nova capabilities.",
        "title_used_for_decision": False,
        "nationwide_remote_allowed": True,
    }


def match_query_to_family(query: str) -> dict[str, Any] | None:
    q = str(query or "").strip().lower()
    if not q:
        return None
    for family_id, family in SEARCH_FAMILIES.items():
        for candidate in family["queries"]:
            if candidate.lower() == q or candidate.lower() in q or q in candidate.lower():
                return {
                    "family_id": family_id,
                    "label": family["label"],
                    "why_searched": (
                        f"Capability-first nationwide remote/digital search for {family['label']}."
                    ),
                }
    # soft keyword match
    for family_id, family in SEARCH_FAMILIES.items():
        label_bits = family["label"].lower().split()
        if any(bit in q for bit in label_bits if len(bit) > 4):
            return {
                "family_id": family_id,
                "label": family["label"],
                "why_searched": (
                    f"Capability-first nationwide remote/digital search for {family['label']}."
                ),
            }
    return None


def assert_no_banned_generated_queries(queries: list[str] | None = None) -> None:
    for query in queries or capability_first_search_queries():
        if is_banned_query(query):
            raise AssertionError(f"Banned generic query generated: {query}")
