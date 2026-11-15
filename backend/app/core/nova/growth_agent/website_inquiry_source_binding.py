"""Trusted organization-to-website-source binding selection (offline only).

Cloudflare KV lead values supplied by the public website have no trusted
organization identity. An authenticated organization must be explicitly bound
to a dedicated namespace by operator-controlled configuration; never infer
the tenant from customer-submitted company, email, product, or message.
This module neither connects to Cloudflare nor contains actual credentials.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass


_ORG = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
_BINDING = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


class WebsiteInquiryBindingDenied(Exception):
    pass


@dataclass(frozen=True)
class InquirySourceBinding:
    organization_id: str
    namespace_binding: str


def select_inquiry_source_binding(
    organization_id: str,
    bindings: Mapping[str, str],
) -> InquirySourceBinding:
    """Select only a trusted exact match, rejecting shared/ambiguous sources.

    Do not pass request query parameters or user-supplied JSON as `bindings`.
    """
    if not isinstance(organization_id, str) or not _ORG.fullmatch(organization_id):
        raise WebsiteInquiryBindingDenied("website_inquiry_binding_unavailable")
    if not isinstance(bindings, Mapping):
        raise WebsiteInquiryBindingDenied("website_inquiry_binding_unavailable")
    binding = bindings.get(organization_id)
    if not isinstance(binding, str) or not _BINDING.fullmatch(binding):
        raise WebsiteInquiryBindingDenied("website_inquiry_binding_unavailable")
    # Never permit two tenants to share a non-tenant-tagged website KV namespace.
    if sum(1 for v in bindings.values() if v == binding) != 1:
        raise WebsiteInquiryBindingDenied("website_inquiry_binding_unavailable")
    return InquirySourceBinding(organization_id=organization_id, namespace_binding=binding)
