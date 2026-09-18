"""Draft proposals and quotes from the approved catalog only."""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.growth.catalog import APPROVED_SERVICES
from app.core.nova.v3.growth.models import Lead


def prepare_quote(
    lead: Lead,
    *,
    service_id: str,
    kind: str = "standard",
    discount_pct: float = 0,
    custom_amount: float | None = None,
) -> dict[str, Any]:
    service = APPROVED_SERVICES.get(service_id)
    if service is None:
        raise V3Error("UNKNOWN_SERVICE", "service is not in the approved catalog", http_status=400)
    if kind not in {"standard", "trial", "recurring", "one_time", "custom"}:
        raise V3Error("INVALID_QUOTE_KIND", "unsupported quote kind", http_status=400)
    price = service.get("price")
    owner_action = False
    if price is None and custom_amount is None:
        owner_action = True
        amount = None
        body = (
            f"INTERNAL QUOTE DRAFT for {lead.organization_name}. Service: {service['name']}. "
            "Price is not in the approved catalog. OWNER_ACTION_REQUIRED. Nova did not invent a number."
        )
    elif custom_amount is not None and (price is None or abs(float(custom_amount) - float(price)) > 0.009):
        owner_action = True
        amount = round(float(custom_amount), 2)
        body = (
            f"INTERNAL CUSTOM QUOTE for {lead.organization_name}. Requested amount {amount} {service['currency']} "
            f"differs from catalog. Owner approval required before any send."
        )
    else:
        amount = round(float(price), 2)
        max_disc = float(service.get("max_discount_pct") or 0)
        if discount_pct > max_disc + 0.0001:
            raise V3Error("UNAUTHORIZED_DISCOUNT", "discount exceeds approved range", http_status=409)
        if kind == "trial" and int(service.get("trial_days") or 0) <= 0:
            raise V3Error("TRIAL_NOT_PUBLISHED", "trial is not in the approved catalog for this service", http_status=409)
        if kind == "one_time" and service.get("billing") not in {"one_time", "custom"}:
            kind = "standard"
        if kind == "recurring" and service.get("billing") != "recurring":
            kind = "standard"
        trial_line = (
            f" Published trial: {service['trial_days']} days."
            if kind == "trial" or int(service.get("trial_days") or 0) > 0
            else ""
        )
        disc_line = f" Discount {discount_pct}% within approved range." if discount_pct else ""
        body = (
            f"INTERNAL {kind.replace('_', ' ').upper()} PROPOSAL for {lead.organization_name}. "
            f"Service: {service['name']}. Catalog amount: {amount} {service['currency']} ({service['billing']})."
            f"{trial_line}{disc_line} Not a live proposal. No contract acceptance."
        )
    return {
        "service_id": service_id,
        "kind": kind,
        "amount": amount,
        "currency": service["currency"],
        "body": body,
        "owner_action_required": owner_action,
        "sent_externally": False,
        "product": service["product"],
        "billing": service["billing"],
    }
