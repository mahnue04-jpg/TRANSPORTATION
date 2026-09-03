"""Applicant work-setup: in-app ICA e-sign, electronic W-9 status, Stripe Connect.

Never stores SSN/TIN or bank routing/account numbers. Does not submit applications
or create a new Driver 001 record.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.approval_engine.sensitive_providers import reject_raw_sensitive_payload
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication, PlatformDriverOnboardingDocument
from app.modules.platform_ops.onboarding.stripe_connect import (
    PAYOUT_DISPLAY,
    PAYOUT_STATUS_COMPLETE,
    PAYOUT_STATUS_NEEDS_ATTENTION,
    PAYOUT_STATUS_NOT_CONFIGURED,
    PAYOUT_STATUS_NOT_STARTED,
    PAYOUT_STATUS_PENDING,
    get_stripe_connect_client,
    is_stripe_connect_configured,
    map_account_to_payout_status,
)
from app.modules.platform_ops.storage import get_document_storage

logger = logging.getLogger("amicor.platform_ops.work_setup")

ICA_VERSION = "AMICOR-ICA-2026.1"
ICA_TITLE = "Independent Contractor Agreement"

W9_COMPLETE_STATUSES = frozenset({"completed", "externally_verified"})
W9_ATTENTION_STATUSES = frozenset({"requested", "pending"})
AGREEMENT_SIGNED_STATUSES = frozenset({"accepted", "signed", "provided"})
W9_TAX_CLASSIFICATIONS = frozenset(
    {
        "individual",
        "sole_proprietor",
        "single_member_llc",
        "llc",
        "c_corporation",
        "s_corporation",
        "partnership",
    }
)

ICA_TEXT = """AMICOR Independent Contractor Agreement
Version AMICOR-ICA-2026.1

This Independent Contractor Agreement ("Agreement") is between Amicor ("Company")
and the individual identified on this application ("Contractor").

1. Independent contractor. Contractor is an independent contractor, not an employee,
   partner, or agent of Company. Contractor controls how services are performed,
   subject to Company service standards, safety rules, and applicable law.

2. Services. Contractor may accept transportation assignments offered through
   Amicor. Accepting an assignment is optional. Contractor provides a qualified
   driver and an eligible vehicle.

3. Compensation. Company pays Contractor for completed, eligible trips according
   to the then-current rate schedule. Payouts are made only after Contractor
   completes required tax and payout account setup. Company does not collect
   bank account or routing numbers on this application.

4. Taxes. Contractor is solely responsible for all taxes arising from compensation
   under this Agreement. Contractor will complete required tax information through
   Amicor's secure electronic workflow. Company does not store Social Security
   numbers or Taxpayer Identification Numbers in this application.

5. Compliance. Contractor will maintain a valid driver's license, required
   insurance, vehicle registration, and any other qualification documents Company
   requests. Contractor authorizes Company to run applicable qualification checks.

6. Confidentiality and records. Contractor will protect rider and patient
   information and follow Company privacy instructions.

7. Term. This Agreement starts when Contractor signs it electronically and
   continues until either party ends it. Company may suspend or end access if
   qualification, safety, or compliance requirements are not met.

8. Electronic signature. Typing a legal name below, with the date and time
   recorded by Amicor, is Contractor's electronic signature and has the same
   effect as a handwritten signature.

By signing, Contractor confirms they have read this Agreement and agree to it.
"""


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _documents_for(application: PlatformDriverOnboardingApplication) -> list[PlatformDriverOnboardingDocument]:
    return list(getattr(application, "documents", None) or [])


def _latest_category(
    documents: list[PlatformDriverOnboardingDocument],
    category: str,
) -> PlatformDriverOnboardingDocument | None:
    matches = [doc for doc in documents if str(doc.category) == category]
    if not matches:
        return None
    return sorted(matches, key=lambda doc: str(doc.created_at or ""), reverse=True)[0]


def _doc_present(documents: list[PlatformDriverOnboardingDocument], category: str) -> bool:
    for doc in documents:
        if str(doc.category) != category:
            continue
        if str(getattr(doc, "review_status", "") or "").lower() in {"rejected", "missing"}:
            continue
        return True
    return False


def agreement_is_signed(
    application: PlatformDriverOnboardingApplication,
    documents: list[PlatformDriverOnboardingDocument] | None = None,
) -> bool:
    docs = documents if documents is not None else _documents_for(application)
    status = str(getattr(application, "agreement_status", None) or "").lower()
    if status in AGREEMENT_SIGNED_STATUSES:
        return True
    return _doc_present(docs, "independent_contractor_agreement")


def tax_information_is_complete(
    application: PlatformDriverOnboardingApplication,
    documents: list[PlatformDriverOnboardingDocument] | None = None,
) -> bool:
    workflow = str(getattr(application, "w9_workflow_status", None) or "").lower()
    if workflow in W9_COMPLETE_STATUSES:
        return True
    docs = documents if documents is not None else _documents_for(application)
    latest = _latest_category(docs, "w9_status")
    if latest is None:
        return False
    review = str(latest.review_status or "").lower()
    value = str(latest.status_only_value or "").lower()
    return review == "accepted" or value in {"provided", "verified", "signed", "accepted", "complete"}


def payout_is_complete(application: PlatformDriverOnboardingApplication) -> bool:
    if bool(getattr(application, "stripe_payouts_enabled", False)):
        return True
    status = str(getattr(application, "stripe_onboarding_status", None) or "").lower()
    return status == PAYOUT_STATUS_COMPLETE


def work_setup_is_complete(
    application: PlatformDriverOnboardingApplication,
    documents: list[PlatformDriverOnboardingDocument] | None = None,
) -> bool:
    docs = documents if documents is not None else _documents_for(application)
    return (
        agreement_is_signed(application, docs)
        and tax_information_is_complete(application, docs)
        and payout_is_complete(application)
    )


def _ica_status(application: PlatformDriverOnboardingApplication, documents: list[PlatformDriverOnboardingDocument]) -> dict[str, Any]:
    signed = agreement_is_signed(application, documents)
    signed_at = getattr(application, "agreement_accepted_at", None)
    version = getattr(application, "agreement_version", None)
    return {
        "key": "independent_contractor_agreement",
        "label": "Independent contractor agreement",
        "status_key": "signed" if signed else "not_signed",
        "status": "Signed / On file" if signed else "Not signed",
        "complete": signed,
        "action_label": None if signed else "Review and sign",
        "message": "Signed agreement is on file." if signed else "Review the agreement and sign electronically.",
        "agreement_version": version or ICA_VERSION,
        "signed_at": _iso(signed_at),
    }


def _tax_status(application: PlatformDriverOnboardingApplication, documents: list[PlatformDriverOnboardingDocument]) -> dict[str, Any]:
    complete = tax_information_is_complete(application, documents)
    workflow = str(getattr(application, "w9_workflow_status", None) or "").lower()
    if complete:
        status_key = "complete"
        status = "Complete"
        message = "Tax information is on file. Social Security and TIN values are not shown here."
    elif workflow in W9_ATTENTION_STATUSES:
        status_key = "needs_attention"
        status = "Needs attention"
        message = "Finish the electronic tax workflow. Do not enter a Social Security number on this page."
    else:
        status_key = "incomplete"
        status = "Incomplete"
        message = "Complete tax information electronically. Do not upload a W-9 file or enter a Social Security number here."
    return {
        "key": "w9",
        "label": "Tax information",
        "status_key": status_key,
        "status": status,
        "complete": complete,
        "action_label": None if complete else "Complete tax information",
        "message": message,
        "tax_classification": getattr(application, "w9_tax_classification", None) if complete else None,
        "stores_ssn_tin": False,
    }


def _payout_status(application: PlatformDriverOnboardingApplication) -> dict[str, Any]:
    configured = is_stripe_connect_configured()
    stored = str(getattr(application, "stripe_onboarding_status", None) or "").lower()
    has_account = bool(getattr(application, "stripe_account_id", None))
    if payout_is_complete(application):
        status_key = PAYOUT_STATUS_COMPLETE
    elif stored in {PAYOUT_STATUS_NEEDS_ATTENTION, PAYOUT_STATUS_NOT_CONFIGURED}:
        status_key = stored
    elif has_account or stored == PAYOUT_STATUS_PENDING:
        status_key = PAYOUT_STATUS_PENDING
    elif not configured:
        status_key = PAYOUT_STATUS_NOT_CONFIGURED
    elif stored:
        status_key = stored
    else:
        status_key = PAYOUT_STATUS_NOT_STARTED
    if status_key == PAYOUT_STATUS_NOT_CONFIGURED:
        message = "Payout setup is not configured yet. An owner still needs to add Stripe Connect keys."
        action_label = "Set Up Payout Account"
    elif status_key == PAYOUT_STATUS_COMPLETE:
        message = "Payout account is connected. Bank details stay in Stripe and are not shown here."
        action_label = None
    elif status_key == PAYOUT_STATUS_PENDING:
        message = "Finish payout verification in Stripe, then return here."
        action_label = "Continue payout setup"
    elif status_key == PAYOUT_STATUS_NEEDS_ATTENTION:
        message = "Payout setup needs attention. Continue in Stripe. Bank details are never entered on this page."
        action_label = "Set Up Payout Account"
    else:
        message = "Set up your payout account with Stripe. Amicor never asks for routing or account numbers here."
        action_label = "Set Up Payout Account"
    return {
        "key": "payout",
        "label": "Payout account",
        "status_key": status_key,
        "status": PAYOUT_DISPLAY.get(status_key, "Needs attention"),
        "complete": status_key == PAYOUT_STATUS_COMPLETE,
        "action_label": action_label,
        "message": message,
        "configured": configured or has_account,
    }


def serialize_work_setup(
    application: PlatformDriverOnboardingApplication,
    documents: list[PlatformDriverOnboardingDocument] | None = None,
) -> dict[str, Any]:
    docs = documents if documents is not None else _documents_for(application)
    agreement = _ica_status(application, docs)
    tax = _tax_status(application, docs)
    payout = _payout_status(application)
    return {
        "application_id": application.id,
        "agreement": agreement,
        "tax": tax,
        "payout": payout,
        "all_complete": bool(agreement["complete"] and tax["complete"] and payout["complete"]),
    }


def agreement_packet() -> dict[str, Any]:
    return {
        "agreement_version": ICA_VERSION,
        "title": ICA_TITLE,
        "text": ICA_TEXT,
    }


def _record_work_setup_audit(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    event_type: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    from app.modules.platform_ops.onboarding.service import _record_audit

    safe_meta = dict(metadata or {})
    for forbidden in ("ssn", "tin", "ein", "routing_number", "account_number", "bank_account_number"):
        safe_meta.pop(forbidden, None)
    _record_audit(
        db,
        application=application,
        event_type=event_type,
        metadata=safe_meta,
    )


def _store_signed_agreement_document(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    typed_signature: str,
    signed_at: datetime,
) -> PlatformDriverOnboardingDocument:
    existing = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(
            PlatformDriverOnboardingDocument.application_id == application.id,
            PlatformDriverOnboardingDocument.category == "independent_contractor_agreement",
        )
        .order_by(PlatformDriverOnboardingDocument.created_at.desc())
        .first()
    )
    if existing:
        return existing
    evidence = {
        "application_id": application.id,
        "organization_id": application.organization_id,
        "agreement_version": ICA_VERSION,
        "title": ICA_TITLE,
        "status": "signed",
        "typed_signature": typed_signature,
        "signed_at": signed_at.isoformat(),
        "agreement_text": ICA_TEXT,
    }
    payload = json.dumps(evidence, indent=2).encode("utf-8")
    storage = get_document_storage()
    backend, storage_ref, byte_size = storage.store(
        organization_id=application.organization_id,
        application_id=application.id,
        category="independent_contractor_agreement",
        filename=f"signed-ica-{ICA_VERSION}.json",
        content_type="application/json",
        stream=BytesIO(payload),
    )
    document = PlatformDriverOnboardingDocument(
        id=uuid4(),
        application_id=application.id,
        organization_id=application.organization_id,
        category="independent_contractor_agreement",
        storage_backend=backend,
        storage_ref=storage_ref,
        original_filename=f"signed-ica-{ICA_VERSION}.json",
        content_type="application/json",
        byte_size=byte_size,
        review_status="accepted",
        created_at=now(),
        updated_at=now(),
    )
    db.add(document)
    db.flush()
    return document


def sign_independent_contractor_agreement(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    typed_signature: str,
    accepted: bool,
    agreement_version: str | None = None,
) -> dict[str, Any]:
    if application.status != "draft":
        raise ValueError("Only draft applications can sign the contractor agreement.")
    if not accepted:
        raise ValueError("Please accept the independent contractor agreement.")
    signature = str(typed_signature or "").strip()
    if len(signature) < 2:
        raise ValueError("Please type your full legal name to sign the independent contractor agreement.")
    if agreement_version and str(agreement_version).strip() not in {ICA_VERSION, ""}:
        raise ValueError("The agreement version on this page is out of date. Reload and sign again.")

    documents = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(PlatformDriverOnboardingDocument.application_id == application.id)
        .all()
    )
    already_signed = bool(
        getattr(application, "agreement_status", None)
        and str(application.agreement_status).lower() in AGREEMENT_SIGNED_STATUSES
        and getattr(application, "agreement_accepted_at", None)
    )
    if already_signed:
        return serialize_work_setup(application, documents)

    signed_at = now()
    document = _store_signed_agreement_document(
        db,
        application=application,
        typed_signature=signature,
        signed_at=signed_at,
    )
    application.agreement_version = ICA_VERSION
    application.agreement_status = "signed"
    application.agreement_accepted_at = signed_at
    application.agreement_evidence_document_id = document.id
    application.updated_at = signed_at
    _record_work_setup_audit(
        db,
        application=application,
        event_type="contractor_agreement_signed",
        metadata={
            "agreement_version": ICA_VERSION,
            "document_id": document.id,
            "signature_recorded": True,
        },
    )
    db.commit()
    db.refresh(application)
    documents = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(PlatformDriverOnboardingDocument.application_id == application.id)
        .all()
    )
    return serialize_work_setup(application, documents)


def _upsert_w9_status_document(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
) -> None:
    from app.modules.platform_ops.onboarding.service import upsert_status_only_document

    existing = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(
            PlatformDriverOnboardingDocument.application_id == application.id,
            PlatformDriverOnboardingDocument.category == "w9_status",
        )
        .order_by(PlatformDriverOnboardingDocument.created_at.desc())
        .first()
    )
    if existing and str(existing.review_status or "").lower() == "accepted":
        return
    upsert_status_only_document(
        db,
        application=application,
        category="w9_status",
        status_only_value="provided",
    )


def complete_electronic_w9(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if application.status != "draft":
        raise ValueError("Only draft applications can update tax information.")
    reject_raw_sensitive_payload(payload)
    documents = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(PlatformDriverOnboardingDocument.application_id == application.id)
        .all()
    )
    if tax_information_is_complete(application, documents):
        return serialize_work_setup(application, documents)
    classification = str(payload.get("tax_classification") or "").strip().lower()
    legal_name = str(payload.get("legal_name") or "").strip()
    if classification not in W9_TAX_CLASSIFICATIONS:
        raise ValueError("Please choose a valid tax classification.")
    if len(legal_name) < 2:
        raise ValueError("Please enter the legal name as it should appear on tax forms.")
    if not payload.get("certify_accurate"):
        raise ValueError("Please certify that the tax information is accurate.")
    if not payload.get("certify_us_person"):
        raise ValueError("Please certify that you are a U.S. person for tax purposes.")

    application.w9_tax_classification = classification
    application.w9_workflow_status = "completed"
    application.w9_workflow_updated_at = now()
    application.w9_external_provider = "amicor_electronic_w9"
    application.updated_at = now()
    _upsert_w9_status_document(db, application=application)
    _record_work_setup_audit(
        db,
        application=application,
        event_type="w9_workflow_completed",
        metadata={
            "status": "completed",
            "tax_classification": classification,
            "stores_ssn_tin": False,
            "already_complete": False,
        },
    )
    db.commit()
    db.refresh(application)
    documents = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(PlatformDriverOnboardingDocument.application_id == application.id)
        .all()
    )
    return serialize_work_setup(application, documents)


def _safe_redirect_url(url: str | None) -> str | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Invalid return URL.")
    if parsed.username or parsed.password:
        raise ValueError("Invalid return URL.")
    return raw


def start_payout_onboarding(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    return_url: str | None,
    refresh_url: str | None,
) -> dict[str, Any]:
    if application.status != "draft":
        raise ValueError("Only draft applications can start payout setup.")
    safe_return = _safe_redirect_url(return_url)
    safe_refresh = _safe_redirect_url(refresh_url) or safe_return
    client = get_stripe_connect_client()
    if client is None:
        if not getattr(application, "stripe_onboarding_status", None):
            application.stripe_onboarding_status = PAYOUT_STATUS_NOT_CONFIGURED
            application.stripe_connect_updated_at = now()
            application.updated_at = now()
            db.commit()
            db.refresh(application)
        status = serialize_work_setup(application)
        status["payout"]["onboarding_url"] = None
        status["payout"]["configured"] = False
        status["payout"]["status_key"] = PAYOUT_STATUS_NOT_CONFIGURED
        status["payout"]["status"] = PAYOUT_DISPLAY[PAYOUT_STATUS_NOT_CONFIGURED]
        status["payout"]["message"] = (
            "Payout setup is not configured yet. An owner still needs to add Stripe Connect keys."
        )
        return status

    account_id = str(getattr(application, "stripe_account_id", None) or "").strip()
    created_new = False
    if not account_id:
        display = " ".join(
            part
            for part in (
                application.legal_first_name or "",
                application.legal_last_name or "",
            )
            if part
        ).strip() or "Amicor driver"
        created = client.create_recipient_account(
            display_name=display,
            email=application.email,
            metadata={
                "application_id": application.id,
                "organization_id": application.organization_id,
            },
        )
        account_id = str(created.get("id") or "").strip()
        if not account_id:
            raise ValueError("Stripe did not return a connected account.")
        application.stripe_account_id = account_id
        application.stripe_onboarding_status = PAYOUT_STATUS_PENDING
        application.stripe_payouts_enabled = False
        application.stripe_details_submitted = False
        created_new = True

    if not safe_return:
        raise ValueError("A return URL is required to start payout setup.")
    link = client.create_account_onboarding_link(
        account_id=account_id,
        refresh_url=safe_refresh or safe_return,
        return_url=safe_return,
    )
    onboarding_url = str(link.get("url") or "").strip() or None
    application.stripe_connect_updated_at = now()
    if not application.stripe_onboarding_status:
        application.stripe_onboarding_status = PAYOUT_STATUS_PENDING
    application.updated_at = now()
    _record_work_setup_audit(
        db,
        application=application,
        event_type="stripe_connect_onboarding_started",
        metadata={
            "created_new_account": created_new,
            "has_onboarding_url": bool(onboarding_url),
        },
    )
    db.commit()
    db.refresh(application)
    status = serialize_work_setup(application)
    status["payout"]["onboarding_url"] = onboarding_url
    return status


def refresh_payout_status(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
) -> dict[str, Any]:
    account_id = str(getattr(application, "stripe_account_id", None) or "").strip()
    client = get_stripe_connect_client()
    if not account_id:
        return serialize_work_setup(application)
    if client is None:
        return serialize_work_setup(application)
    account = client.retrieve_account(account_id)
    mapped = map_account_to_payout_status(account)
    application.stripe_onboarding_status = mapped["stripe_onboarding_status"]
    application.stripe_payouts_enabled = bool(mapped["stripe_payouts_enabled"])
    application.stripe_details_submitted = bool(mapped["stripe_details_submitted"])
    application.stripe_connect_updated_at = now()
    application.updated_at = now()
    _record_work_setup_audit(
        db,
        application=application,
        event_type="stripe_connect_status_refreshed",
        metadata={
            "stripe_onboarding_status": application.stripe_onboarding_status,
            "stripe_payouts_enabled": application.stripe_payouts_enabled,
        },
    )
    db.commit()
    db.refresh(application)
    return serialize_work_setup(application)
