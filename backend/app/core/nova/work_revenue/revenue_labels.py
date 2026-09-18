"""AMICOR vs client revenue labeling. Internal tracking only. No Stripe, send, or payout."""
from __future__ import annotations

from typing import Any

AUTHORITATIVE_SOURCE = "nova_work_revenue_entries"
PARTY_AMICOR = "AMICOR"
PARTY_CLIENT_CONTEXT = "CLIENT_CONTEXT"


def _money(value: Any) -> float:
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def labeled_amount(
    *,
    amount: Any,
    party: str,
    role: str,
    authoritative: bool,
    label: str,
) -> dict[str, Any]:
    return {
        "amount": _money(amount),
        "party": party,
        "role": role,
        "authoritative": bool(authoritative),
        "label": label,
        "processor_confirmed": False,
        "included_in_amicor_totals": bool(authoritative and party == PARTY_AMICOR),
    }


def expected_amicor_revenue(*, estimated: Any, quoted: Any, contracted: Any) -> float:
    contracted_amount = _money(contracted)
    quoted_amount = _money(quoted)
    estimated_amount = _money(estimated)
    if contracted_amount:
        return contracted_amount
    if quoted_amount:
        return quoted_amount
    return estimated_amount


def labeling_rules() -> dict[str, Any]:
    return {
        "authoritative_source": AUTHORITATIVE_SOURCE,
        "amicor_ledger_party": PARTY_AMICOR,
        "client_context_party": PARTY_CLIENT_CONTEXT,
        "opportunity_fields_are_authoritative": False,
        "invoice_support_is_authoritative": False,
        "double_count_opportunity_into_amicor": False,
        "double_count_invoice_support_into_amicor": False,
        "owner_confirmation_required_for_received": True,
        "processor_confirmed_payment": False,
        "stripe_confirmed_payment": False,
        "labels": {
            "amicor_expected_revenue": "AMICOR expected revenue from the internal ledger",
            "amicor_owner_confirmed_received": "AMICOR owner-confirmed received. Not processor-confirmed.",
            "client_billed_amount": "Client billed amount from invoice-support drafts. Not a sent invoice.",
            "contract_opportunity_amount": "Client/opportunity contract amount. Context only.",
            "contextual_non_authoritative": "Contextual / non-authoritative. Not added into AMICOR totals.",
        },
        "disclaimer": (
            "AMICOR ledger != client billed draft. Opportunity amounts are context only. "
            "Invoice-support is not a sent invoice. OWNER CONFIRMED RECEIVED != PROCESSOR CONFIRMED PAYMENT. "
            "Nova does not collect payment."
        ),
    }


def labeled_revenue_view(
    *,
    amicor_estimated: Any,
    amicor_quoted: Any,
    amicor_contracted: Any,
    amicor_received: Any,
    client_billed: Any,
    opportunity_estimated: Any,
    opportunity_quoted: Any,
    opportunity_contracted: Any,
    opportunity_received: Any,
    mismatch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rules = labeling_rules()
    estimated = _money(amicor_estimated)
    quoted = _money(amicor_quoted)
    contracted = _money(amicor_contracted)
    received = _money(amicor_received)
    billed = _money(client_billed)
    opp_estimated = _money(opportunity_estimated)
    opp_quoted = _money(opportunity_quoted)
    opp_contracted = _money(opportunity_contracted)
    opp_received = _money(opportunity_received)
    expected = expected_amicor_revenue(estimated=estimated, quoted=quoted, contracted=contracted)
    flags = dict(mismatch or {})
    flags["client_billed_vs_amicor_contracted"] = abs(billed - contracted) > 0.009 if billed and contracted else False
    flags["opportunity_received_vs_amicor_received"] = abs(opp_received - received) > 0.009 if opp_received else False
    flags["has_mismatch"] = bool(
        flags.get("has_mismatch")
        or flags["client_billed_vs_amicor_contracted"]
        or flags["opportunity_received_vs_amicor_received"]
    )
    return {
        "authoritative_source": AUTHORITATIVE_SOURCE,
        "double_counted": False,
        "amicor": {
            "party": PARTY_AMICOR,
            "authoritative_source": AUTHORITATIVE_SOURCE,
            "estimated": labeled_amount(
                amount=estimated,
                party=PARTY_AMICOR,
                role="amicor_estimated",
                authoritative=True,
                label=rules["labels"]["amicor_expected_revenue"],
            ),
            "quoted": labeled_amount(
                amount=quoted,
                party=PARTY_AMICOR,
                role="amicor_quoted",
                authoritative=True,
                label=rules["labels"]["amicor_expected_revenue"],
            ),
            "contracted": labeled_amount(
                amount=contracted,
                party=PARTY_AMICOR,
                role="amicor_expected_revenue",
                authoritative=True,
                label=rules["labels"]["amicor_expected_revenue"],
            ),
            "expected_revenue": labeled_amount(
                amount=expected,
                party=PARTY_AMICOR,
                role="amicor_expected_revenue",
                authoritative=True,
                label=rules["labels"]["amicor_expected_revenue"],
            ),
            "owner_confirmed_received": labeled_amount(
                amount=received,
                party=PARTY_AMICOR,
                role="amicor_owner_confirmed_received",
                authoritative=True,
                label=rules["labels"]["amicor_owner_confirmed_received"],
            ),
        },
        "client_context": {
            "party": PARTY_CLIENT_CONTEXT,
            "authoritative_source": None,
            "billed_amount": labeled_amount(
                amount=billed,
                party=PARTY_CLIENT_CONTEXT,
                role="client_billed_amount",
                authoritative=False,
                label=rules["labels"]["client_billed_amount"],
            ),
            "contract_opportunity_amount": labeled_amount(
                amount=opp_contracted,
                party=PARTY_CLIENT_CONTEXT,
                role="contract_opportunity_amount",
                authoritative=False,
                label=rules["labels"]["contract_opportunity_amount"],
            ),
            "estimated_opportunity_amount": labeled_amount(
                amount=opp_estimated,
                party=PARTY_CLIENT_CONTEXT,
                role="contextual_non_authoritative",
                authoritative=False,
                label=rules["labels"]["contextual_non_authoritative"],
            ),
            "quoted_opportunity_amount": labeled_amount(
                amount=opp_quoted,
                party=PARTY_CLIENT_CONTEXT,
                role="contextual_non_authoritative",
                authoritative=False,
                label=rules["labels"]["contextual_non_authoritative"],
            ),
            "opportunity_received_amount": labeled_amount(
                amount=opp_received,
                party=PARTY_CLIENT_CONTEXT,
                role="contextual_non_authoritative",
                authoritative=False,
                label=rules["labels"]["contextual_non_authoritative"],
            ),
        },
        "mismatch": flags,
        "rules": rules,
    }


def dashboard_revenue_summary(view: dict[str, Any]) -> dict[str, Any]:
    amicor = view.get("amicor") or {}
    client = view.get("client_context") or {}
    rules = view.get("labeling") if isinstance(view.get("labeling"), dict) else None
    if not rules or not rules.get("labels"):
        rules = labeling_rules()
    return {
        "estimated_pipeline": (amicor.get("estimated") or {}).get("amount") or 0,
        "quoted_pipeline": (amicor.get("quoted") or {}).get("amount") or 0,
        "contracted_value": (amicor.get("contracted") or {}).get("amount") or 0,
        "owner_confirmed_received": (amicor.get("owner_confirmed_received") or {}).get("amount") or 0,
        "amicor_expected_revenue": (amicor.get("expected_revenue") or {}).get("amount") or 0,
        "client_billed_amount": (client.get("billed_amount") or {}).get("amount") or 0,
        "contract_opportunity_amount": (client.get("contract_opportunity_amount") or {}).get("amount") or 0,
        "authoritative_source": AUTHORITATIVE_SOURCE,
        "double_counted": False,
        "amicor": amicor,
        "client_context": client,
        "mismatch": view.get("mismatch") or {},
        "labels": rules.get("labels") or {},
        "disclaimer": rules.get("disclaimer"),
    }
