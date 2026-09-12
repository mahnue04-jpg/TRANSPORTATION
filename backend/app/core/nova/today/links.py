"""Nova V2 Phase 3 source links. Only existing V1 pages; never invent record URLs."""
from __future__ import annotations

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.today.models import NovaV2CommandAction
from sqlalchemy.orm import Session


def _can_see_org_wide(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}

MODULE_PAGES = {
    "communications": "/nova/communications",
    "government": "/nova/government",
    "business": "/nova/business",
    "workspace": "/nova/workspace",
}
PRODUCT_PAGES = {
    "health": "/workspace",
    "delivery": "/app",
    "freight": "/nova/freight",
}


def is_synthetic_ref(source_ref_id: str | None) -> bool:
    return str(source_ref_id or "").startswith("rec-")


def bare_source_ref(source_ref_id: str) -> str:
    ref = str(source_ref_id or "")
    if ref.endswith(":renewal"):
        return ref[: -len(":renewal")]
    return ref


def module_page(source_module: str, source_ref_id: str | None = None) -> str | None:
    if source_module == "link":
        return PRODUCT_PAGES.get(str(source_ref_id or ""))
    return MODULE_PAGES.get(source_module)


def source_record_visible(
    db: Session,
    *,
    source_module: str,
    source_ref_id: str,
    organization_id: str,
    user: UserContext,
) -> bool:
    """True only when the existing V1 record is visible to this tenant/user."""
    if is_synthetic_ref(source_ref_id):
        return False
    if source_module == "link":
        return source_ref_id in PRODUCT_PAGES
    ref = bare_source_ref(source_ref_id)
    try:
        if source_module == "communications":
            return _communications_visible(db, ref, organization_id=organization_id, user=user)
        if source_module == "government":
            from app.core.nova.government.service import get_item, list_programs

            try:
                get_item(db, ref, organization_id=organization_id, user=user)
                return True
            except Exception:
                return any(
                    row.program_id == ref
                    for row in list_programs(db, organization_id=organization_id, user=user)
                )
        if source_module == "business":
            return _business_visible(db, ref, organization_id=organization_id, user=user)
        if source_module == "workspace":
            return _workspace_visible(db, ref, organization_id=organization_id, user=user)
    except Exception:
        return False
    return False


def source_href(
    db: Session,
    *,
    source_module: str,
    source_ref_id: str,
    organization_id: str,
    user: UserContext,
) -> str | None:
    """Return an existing V1 page only when the source record is visible. No invented query URLs."""
    page = module_page(source_module, source_ref_id)
    if page is None:
        return None
    if not source_record_visible(
        db,
        source_module=source_module,
        source_ref_id=source_ref_id,
        organization_id=organization_id,
        user=user,
    ):
        return None
    return page


def source_details(
    db: Session,
    *,
    source_module: str,
    source_ref_id: str,
    organization_id: str,
    user: UserContext,
) -> dict[str, str] | None:
    if not source_record_visible(
        db,
        source_module=source_module,
        source_ref_id=source_ref_id,
        organization_id=organization_id,
        user=user,
    ):
        return None
    ref = bare_source_ref(source_ref_id)
    try:
        if source_module == "communications":
            return _communications_details(db, ref, organization_id=organization_id, user=user)
        if source_module == "government":
            from app.core.nova.government.service import get_item, list_programs, work_out

            try:
                row = get_item(db, ref, organization_id=organization_id, user=user)
                item = work_out(row)
                return {
                    "kind": "government_item",
                    "title": item.title,
                    "status": item.status,
                    "agency": item.agency or "",
                }
            except Exception:
                program = next(
                    (
                        row
                        for row in list_programs(db, organization_id=organization_id, user=user)
                        if row.program_id == ref
                    ),
                    None,
                )
                if program is None:
                    return None
                return {
                    "kind": "government_program",
                    "title": program.program_name,
                    "agency": program.agency or "",
                }
        if source_module == "business":
            return _business_details(db, ref, organization_id=organization_id, user=user)
        if source_module == "workspace":
            return _workspace_details(db, ref, organization_id=organization_id, user=user)
        if source_module == "link":
            return {"kind": "product_link", "title": source_ref_id, "page": module_page("link", source_ref_id) or ""}
    except Exception:
        return None
    return None


def result_type_for(row: NovaV2CommandAction) -> str:
    status = str(row.status or "")
    recommended = str(row.recommended_action or "")
    if status == "dismissed":
        return "dismissed"
    if status == "snoozed":
        return "snoozed"
    if status in {"approved", "done"} and recommended == "create_draft":
        return "draft_created"
    if status in {"approved", "done"} and recommended == "create_task":
        return "task_created"
    if status in {"approved", "done"} and recommended == "acknowledge":
        return "acknowledged"
    if status in {"approved", "done"} and recommended == "open_link":
        return "link_opened"
    if status in {"approved", "done"} and recommended == "recheck_source":
        return "source_rechecked"
    if status == "approved":
        return "approved"
    if status == "done":
        return "approved"
    return status or "proposed"


def prior_status_for(row: NovaV2CommandAction) -> str:
    if str(row.status or "") == "proposed":
        return "proposed"
    return "proposed"


def _communications_visible(db: Session, ref: str, *, organization_id: str, user: UserContext) -> bool:
    from app.core.nova.communications.service import get_message, list_drafts, list_events

    try:
        get_message(db, ref, organization_id=organization_id, user=user, mark_read=False)
        return True
    except Exception:
        pass
    if any(row.id == ref for row in list_drafts(db, user=user)):
        return True
    return any(row.id == ref for row in list_events(db, user=user))


def _communications_details(db: Session, ref: str, *, organization_id: str, user: UserContext) -> dict[str, str]:
    from app.core.nova.communications.service import get_message, list_drafts, list_events, message_out

    try:
        row = get_message(db, ref, organization_id=organization_id, user=user, mark_read=False)
        out = message_out(row)
        return {
            "kind": "message",
            "sender": out.sender,
            "subject": out.subject,
            "source": out.source,
            "received_at": out.created_at.isoformat() if out.created_at else "",
            "unread": "unread" if not out.read else "read",
            "important": "important" if out.important else "normal",
        }
    except Exception:
        pass
    for draft in list_drafts(db, user=user):
        if draft.id == ref:
            return {"kind": "draft", "subject": draft.subject, "status": draft.status}
    for event in list_events(db, user=user):
        if event.id == ref:
            return {"kind": "event", "title": event.title}
    return {"kind": "communications"}


def _business_visible(db: Session, ref: str, *, organization_id: str, user: UserContext) -> bool:
    from app.core.nova.business.service import get_customer, get_opportunity, get_task

    for loader in (get_task, get_customer, get_opportunity):
        try:
            loader(db, ref, organization_id=organization_id, user=user)
            return True
        except Exception:
            continue
    return False


def _business_details(db: Session, ref: str, *, organization_id: str, user: UserContext) -> dict[str, str]:
    from app.core.nova.business.service import (
        customer_out,
        get_customer,
        get_opportunity,
        get_task,
        opportunity_out,
        task_out,
    )

    try:
        return {"kind": "task", "title": task_out(get_task(db, ref, organization_id=organization_id, user=user)).title}
    except Exception:
        pass
    try:
        customer = customer_out(get_customer(db, ref, organization_id=organization_id, user=user))
        return {"kind": "customer", "title": customer.name}
    except Exception:
        pass
    opportunity = opportunity_out(get_opportunity(db, ref, organization_id=organization_id, user=user))
    return {"kind": "opportunity", "title": opportunity.title}


def _workspace_visible(db: Session, ref: str, *, organization_id: str, user: UserContext) -> bool:
    from app.core.nova.workspace.models import NovaWorkspaceActivity
    from app.core.nova.workspace.service import get_project

    try:
        get_project(db, ref, organization_id=organization_id, user=user, touch=False)
        return True
    except Exception:
        pass
    query = db.query(NovaWorkspaceActivity).filter(
        NovaWorkspaceActivity.activity_id == ref,
        NovaWorkspaceActivity.organization_id == organization_id,
    )
    if not _can_see_org_wide(user):
        query = query.filter(NovaWorkspaceActivity.owner_user_id == user.user_id)
    return query.first() is not None


def _workspace_details(db: Session, ref: str, *, organization_id: str, user: UserContext) -> dict[str, str]:
    from app.core.nova.workspace.models import NovaWorkspaceActivity
    from app.core.nova.workspace.service import get_project, project_out

    try:
        project = project_out(get_project(db, ref, organization_id=organization_id, user=user, touch=False))
        return {"kind": "project", "title": project.title, "status": project.status}
    except Exception:
        pass
    query = db.query(NovaWorkspaceActivity).filter(
        NovaWorkspaceActivity.activity_id == ref,
        NovaWorkspaceActivity.organization_id == organization_id,
    )
    if not _can_see_org_wide(user):
        query = query.filter(NovaWorkspaceActivity.owner_user_id == user.user_id)
    row = query.first()
    if row is None:
        return {"kind": "workspace"}
    return {"kind": "activity", "title": row.title, "status": row.kind}
