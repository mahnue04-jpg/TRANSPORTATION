"""Offline tenant mapping tests; no Cloudflare client or credentials."""
import pytest

from app.core.nova.growth_agent.website_inquiry_source_binding import (
    WebsiteInquiryBindingDenied,
    select_inquiry_source_binding,
)


def test_exact_operator_configured_tenant_binding():
    entry = select_inquiry_source_binding(
        "amicor-owner", {"amicor-owner": "AMICOR_LEADS", "other": "OTHER_LEADS"}
    )
    assert entry.organization_id == "amicor-owner"
    assert entry.namespace_binding == "AMICOR_LEADS"


@pytest.mark.parametrize("organization_id,bindings", [
    ("other", {"amicor-owner": "AMICOR_LEADS"}),
    ("", {"": "AMICOR_LEADS"}),
    ("global", {"amicor-owner": "AMICOR_LEADS"}),
    ("../amicor-owner", {"../amicor-owner": "AMICOR_LEADS"}),
    ("amicor-owner", {"amicor-owner": "https://untrusted.example.invalid"}),
    ("amicor-owner", {"amicor-owner": "amicor_leads"}),
    ("amicor-owner", {"amicor-owner": "AMICOR_LEADS", "other": "AMICOR_LEADS"}),
    ("amicor-owner", None),
])
def test_unknown_ambiguous_or_untrusted_binding_denied(organization_id, bindings):
    with pytest.raises(WebsiteInquiryBindingDenied) as exc:
        select_inquiry_source_binding(organization_id, bindings)
    assert str(exc.value) == "website_inquiry_binding_unavailable"


def test_customer_supplied_company_cannot_select_namespace():
    bindings = {"amicor-owner": "AMICOR_LEADS"}
    with pytest.raises(WebsiteInquiryBindingDenied):
        select_inquiry_source_binding("Fictional Company", bindings)
