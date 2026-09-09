"""Nova Workspace persistence. Isolated from Health, Delivery, and Freight."""
from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.service import NovaCoreService
from app.core.nova.workspace.models import (
    NovaWorkspaceActivity,
    NovaWorkspaceConversation,
    NovaWorkspaceFile,
    NovaWorkspaceMessage,
    NovaWorkspaceProject,
    NovaWorkspaceSearch,
)
from app.core.nova.workspace.schemas import (
    NovaWorkspaceBrainOut,
    NovaWorkspaceBrainRequest,
    NovaWorkspaceConversationCreate,
    NovaWorkspaceConversationOut,
    NovaWorkspaceConversationUpdate,
    NovaWorkspaceFileCreate,
    NovaWorkspaceFileOut,
    NovaWorkspaceMessageOut,
    NovaWorkspaceProjectCreate,
    NovaWorkspaceProjectOut,
    NovaWorkspaceProjectUpdate,
    NovaWorkspaceSearchHit,
    NovaWorkspaceSearchOut,
    NovaWorkspaceSearchSavedOut,
    NovaWorkspaceActivityOut,
    NovaWorkspaceDashboardOut,
)
from app.database import get_chat_history
from app.helpers import now, uuid4


class NovaWorkspaceError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _new_id(prefix: str) -> str:
    return prefix + uuid4().replace("-", "")[:12].upper()


def _can_see_org_wide(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}


def _owner_filter(query, model, user: UserContext):
    if _can_see_org_wide(user):
        return query
    return query.filter(model.owner_user_id == user.user_id)


def project_out(row: NovaWorkspaceProject) -> NovaWorkspaceProjectOut:
    return NovaWorkspaceProjectOut(
        workspace_id=row.workspace_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        title=row.title,
        description=row.description,
        status=row.status,
        archived=row.archived,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_opened_at=row.last_opened_at,
    )


def file_out(row: NovaWorkspaceFile) -> NovaWorkspaceFileOut:
    return NovaWorkspaceFileOut(
        file_id=row.file_id,
        workspace_id=row.workspace_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        filename=row.filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
        last_accessed_at=row.last_accessed_at,
    )


def message_out(row: NovaWorkspaceMessage) -> NovaWorkspaceMessageOut:
    return NovaWorkspaceMessageOut(
        message_id=row.message_id,
        conversation_id=row.conversation_id,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
    )


def conversation_out(
    row: NovaWorkspaceConversation,
    messages: list[NovaWorkspaceMessage] | None = None,
    preview: str | None = None,
) -> NovaWorkspaceConversationOut:
    items = [message_out(item) for item in (messages or [])]
    return NovaWorkspaceConversationOut(
        conversation_id=row.conversation_id,
        workspace_id=row.workspace_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        title=row.title,
        source=row.source,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_opened_at=row.last_opened_at,
        preview=preview,
        messages=items,
    )


def _record_activity(
    db: Session,
    *,
    organization_id: str,
    owner_user_id: str,
    kind: str,
    title: str,
    workspace_id: str | None = None,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> None:
    db.add(
        NovaWorkspaceActivity(
            activity_id=_new_id("NWA-"),
            organization_id=organization_id,
            owner_user_id=owner_user_id,
            workspace_id=workspace_id,
            kind=kind,
            title=title[:240],
            ref_type=ref_type,
            ref_id=ref_id,
        )
    )


def get_project(
    db: Session,
    workspace_id: str,
    *,
    organization_id: str,
    user: UserContext,
    touch: bool = False,
) -> NovaWorkspaceProject:
    query = db.query(NovaWorkspaceProject).filter(
        NovaWorkspaceProject.workspace_id == workspace_id,
        NovaWorkspaceProject.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaWorkspaceProject, user)
    row = query.first()
    if row is None:
        raise NovaWorkspaceError("Workspace project not found", status_code=404)
    if touch:
        row.last_opened_at = now()
        row.updated_at = row.updated_at
        db.commit()
        db.refresh(row)
    return row


def create_project(
    db: Session,
    payload: NovaWorkspaceProjectCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceProject:
    row = None
    for _ in range(5):
        row = NovaWorkspaceProject(
            workspace_id=_new_id("NW-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            title=payload.title.strip(),
            description=(payload.description or "").strip() or None,
            status="active",
            archived=False,
            last_opened_at=now(),
        )
        db.add(row)
        try:
            db.flush()
            _record_activity(
                db,
                organization_id=organization_id,
                owner_user_id=user.user_id,
                kind="project_created",
                title=f"Created project {row.title}",
                workspace_id=row.workspace_id,
                ref_type="project",
                ref_id=row.workspace_id,
            )
            db.commit()
            db.refresh(row)
            return row
        except IntegrityError:
            db.rollback()
            row = None
    raise NovaWorkspaceError("Could not allocate a workspace ID", status_code=409)


def list_projects(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    include_archived: bool = False,
) -> list[NovaWorkspaceProject]:
    query = db.query(NovaWorkspaceProject).filter(NovaWorkspaceProject.organization_id == organization_id)
    query = _owner_filter(query, NovaWorkspaceProject, user)
    if not include_archived:
        query = query.filter(NovaWorkspaceProject.archived.is_(False))
    return query.order_by(NovaWorkspaceProject.updated_at.desc()).all()


def update_project(
    db: Session,
    workspace_id: str,
    payload: NovaWorkspaceProjectUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceProject:
    row = get_project(db, workspace_id, organization_id=organization_id, user=user)
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.description is not None:
        row.description = payload.description.strip() or None
    if payload.status is not None:
        row.status = payload.status
    row.updated_at = now()
    _record_activity(
        db,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        kind="project_updated",
        title=f"Updated project {row.title}",
        workspace_id=row.workspace_id,
        ref_type="project",
        ref_id=row.workspace_id,
    )
    db.commit()
    db.refresh(row)
    return row


def archive_project(
    db: Session,
    workspace_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceProject:
    row = get_project(db, workspace_id, organization_id=organization_id, user=user)
    row.archived = True
    row.status = "archived"
    row.updated_at = now()
    _record_activity(
        db,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        kind="project_archived",
        title=f"Archived project {row.title}",
        workspace_id=row.workspace_id,
        ref_type="project",
        ref_id=row.workspace_id,
    )
    db.commit()
    db.refresh(row)
    return row


def add_file(
    db: Session,
    payload: NovaWorkspaceFileCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceFile:
    workspace_id = payload.workspace_id
    if workspace_id:
        get_project(db, workspace_id, organization_id=organization_id, user=user)
    excerpt = (payload.excerpt or "").strip()[:4000] or None
    row = NovaWorkspaceFile(
        file_id=_new_id("NWF-"),
        workspace_id=workspace_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        upload_id=payload.upload_id,
        filename=payload.filename.strip(),
        content_type=payload.content_type,
        size_bytes=payload.size_bytes,
        excerpt=excerpt,
        last_accessed_at=now(),
    )
    db.add(row)
    _record_activity(
        db,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        kind="file_added",
        title=f"Added file {row.filename}",
        workspace_id=workspace_id,
        ref_type="file",
        ref_id=row.file_id,
    )
    db.commit()
    db.refresh(row)
    return row


def list_files(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    workspace_id: str | None = None,
) -> list[NovaWorkspaceFile]:
    query = db.query(NovaWorkspaceFile).filter(NovaWorkspaceFile.organization_id == organization_id)
    query = _owner_filter(query, NovaWorkspaceFile, user)
    if workspace_id:
        query = query.filter(NovaWorkspaceFile.workspace_id == workspace_id)
    return query.order_by(NovaWorkspaceFile.created_at.desc()).all()


def create_conversation(
    db: Session,
    payload: NovaWorkspaceConversationCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceConversation:
    workspace_id = payload.workspace_id
    if workspace_id:
        get_project(db, workspace_id, organization_id=organization_id, user=user)
    title = (payload.title or "").strip() or "Mrs. Nova Brain conversation"
    row = NovaWorkspaceConversation(
        conversation_id=_new_id("NWC-"),
        workspace_id=workspace_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        title=title[:180],
        source=payload.source,
        last_opened_at=now(),
    )
    db.add(row)
    _record_activity(
        db,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        kind="conversation_created",
        title=f"Started conversation {row.title}",
        workspace_id=workspace_id,
        ref_type="conversation",
        ref_id=row.conversation_id,
    )
    db.commit()
    db.refresh(row)
    return row


def get_conversation(
    db: Session,
    conversation_id: str,
    *,
    organization_id: str,
    user: UserContext,
    touch: bool = False,
) -> tuple[NovaWorkspaceConversation, list[NovaWorkspaceMessage]]:
    query = db.query(NovaWorkspaceConversation).filter(
        NovaWorkspaceConversation.conversation_id == conversation_id,
        NovaWorkspaceConversation.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaWorkspaceConversation, user)
    row = query.first()
    if row is None:
        raise NovaWorkspaceError("Conversation not found", status_code=404)
    if touch:
        row.last_opened_at = now()
        db.commit()
        db.refresh(row)
    messages = (
        db.query(NovaWorkspaceMessage)
        .filter(
            NovaWorkspaceMessage.conversation_id == conversation_id,
            NovaWorkspaceMessage.organization_id == organization_id,
        )
        .order_by(NovaWorkspaceMessage.created_at.asc())
        .all()
    )
    return row, messages


def list_conversations(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    workspace_id: str | None = None,
) -> list[tuple[NovaWorkspaceConversation, str | None]]:
    query = db.query(NovaWorkspaceConversation).filter(
        NovaWorkspaceConversation.organization_id == organization_id
    )
    query = _owner_filter(query, NovaWorkspaceConversation, user)
    if workspace_id:
        query = query.filter(NovaWorkspaceConversation.workspace_id == workspace_id)
    rows = query.order_by(NovaWorkspaceConversation.updated_at.desc()).all()
    out: list[tuple[NovaWorkspaceConversation, str | None]] = []
    for row in rows:
        last = (
            db.query(NovaWorkspaceMessage)
            .filter(NovaWorkspaceMessage.conversation_id == row.conversation_id)
            .order_by(NovaWorkspaceMessage.created_at.desc())
            .first()
        )
        out.append((row, (last.content[:180] if last else None)))
    return out


def update_conversation(
    db: Session,
    conversation_id: str,
    payload: NovaWorkspaceConversationUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceConversation:
    row, _messages = get_conversation(
        db, conversation_id, organization_id=organization_id, user=user
    )
    if payload.title is not None:
        row.title = payload.title.strip()
    if payload.workspace_id is not None:
        if payload.workspace_id:
            get_project(db, payload.workspace_id, organization_id=organization_id, user=user)
        row.workspace_id = payload.workspace_id or None
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row


def append_message(
    db: Session,
    conversation_id: str,
    *,
    organization_id: str,
    user: UserContext,
    role: str,
    content: str,
) -> NovaWorkspaceMessage:
    row, _messages = get_conversation(
        db, conversation_id, organization_id=organization_id, user=user
    )
    message = NovaWorkspaceMessage(
        message_id=_new_id("NWM-"),
        conversation_id=row.conversation_id,
        organization_id=organization_id,
        role=role,
        content=content,
    )
    db.add(message)
    row.updated_at = now()
    db.commit()
    db.refresh(message)
    return message


def search_workspace(
    db: Session,
    query_text: str,
    *,
    organization_id: str,
    user: UserContext,
    persist: bool = True,
) -> NovaWorkspaceSearchOut:
    needle = query_text.strip()
    if len(needle) < 2:
        raise NovaWorkspaceError("Search query must be at least 2 characters", status_code=422)
    hits: list[NovaWorkspaceSearchHit] = []

    projects = _owner_filter(
        db.query(NovaWorkspaceProject).filter(NovaWorkspaceProject.organization_id == organization_id),
        NovaWorkspaceProject,
        user,
    ).all()
    for row in projects:
        blob = f"{row.title} {row.description or ''}".lower()
        if needle.lower() in blob:
            hits.append(
                NovaWorkspaceSearchHit(
                    kind="project",
                    id=row.workspace_id,
                    title=row.title,
                    snippet=(row.description or row.title)[:180],
                    workspace_id=row.workspace_id,
                )
            )

    files = _owner_filter(
        db.query(NovaWorkspaceFile).filter(NovaWorkspaceFile.organization_id == organization_id),
        NovaWorkspaceFile,
        user,
    ).all()
    for row in files:
        blob = f"{row.filename} {row.excerpt or ''}".lower()
        if needle.lower() in blob:
            hits.append(
                NovaWorkspaceSearchHit(
                    kind="file",
                    id=row.file_id,
                    title=row.filename,
                    snippet=(row.excerpt or row.filename)[:180],
                    workspace_id=row.workspace_id,
                )
            )

    conversations = _owner_filter(
        db.query(NovaWorkspaceConversation).filter(
            NovaWorkspaceConversation.organization_id == organization_id
        ),
        NovaWorkspaceConversation,
        user,
    ).all()
    for row in conversations:
        messages = (
            db.query(NovaWorkspaceMessage)
            .filter(NovaWorkspaceMessage.conversation_id == row.conversation_id)
            .all()
        )
        text = " ".join([row.title] + [item.content for item in messages]).lower()
        if needle.lower() in text:
            hits.append(
                NovaWorkspaceSearchHit(
                    kind="conversation",
                    id=row.conversation_id,
                    title=row.title,
                    snippet=row.title,
                    workspace_id=row.workspace_id,
                )
            )

    if persist:
        db.add(
            NovaWorkspaceSearch(
                search_id=_new_id("NWS-"),
                organization_id=organization_id,
                owner_user_id=user.user_id,
                query=needle[:400],
                result_count=len(hits),
            )
        )
        _record_activity(
            db,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            kind="search",
            title=f"Searched workspace for {needle[:80]}",
            ref_type="search",
        )
        db.commit()

    return NovaWorkspaceSearchOut(query=needle, result_count=len(hits), hits=hits[:40])


def dashboard(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceDashboardOut:
    projects = list_projects(db, organization_id=organization_id, user=user)[:12]
    files = list_files(db, organization_id=organization_id, user=user)[:12]
    conversations = [
        conversation_out(row, preview=preview)
        for row, preview in list_conversations(db, organization_id=organization_id, user=user)[:12]
    ]
    searches = (
        _owner_filter(
            db.query(NovaWorkspaceSearch).filter(NovaWorkspaceSearch.organization_id == organization_id),
            NovaWorkspaceSearch,
            user,
        )
        .order_by(NovaWorkspaceSearch.created_at.desc())
        .limit(8)
        .all()
    )
    activities = (
        _owner_filter(
            db.query(NovaWorkspaceActivity).filter(NovaWorkspaceActivity.organization_id == organization_id),
            NovaWorkspaceActivity,
            user,
        )
        .order_by(NovaWorkspaceActivity.created_at.desc())
        .limit(16)
        .all()
    )
    history: list[dict] = []
    try:
        history = get_chat_history(user.user_id, limit=8)
    except Exception:
        history = []
    return NovaWorkspaceDashboardOut(
        recent_work=[
            NovaWorkspaceActivityOut(
                activity_id=item.activity_id,
                kind=item.kind,
                title=item.title,
                workspace_id=item.workspace_id,
                ref_type=item.ref_type,
                ref_id=item.ref_id,
                created_at=item.created_at,
            )
            for item in activities
        ],
        recent_conversations=conversations,
        recent_files=[file_out(item) for item in files],
        active_projects=[project_out(item) for item in projects],
        saved_searches=[
            NovaWorkspaceSearchSavedOut(
                search_id=item.search_id,
                query=item.query,
                result_count=item.result_count,
                created_at=item.created_at,
            )
            for item in searches
        ],
        assistant_history=history,
    )


def _project_context(db: Session, workspace_id: str, *, organization_id: str, user: UserContext) -> str:
    row = get_project(db, workspace_id, organization_id=organization_id, user=user, touch=True)
    files = list_files(db, organization_id=organization_id, user=user, workspace_id=workspace_id)[:8]
    convos = list_conversations(db, organization_id=organization_id, user=user, workspace_id=workspace_id)[:6]
    activities = (
        db.query(NovaWorkspaceActivity)
        .filter(
            NovaWorkspaceActivity.organization_id == organization_id,
            NovaWorkspaceActivity.workspace_id == workspace_id,
        )
        .order_by(NovaWorkspaceActivity.created_at.desc())
        .limit(8)
        .all()
    )
    file_line = ", ".join(item.filename for item in files) or "none"
    convo_line = ", ".join(item[0].title for item in convos) or "none"
    change_line = "; ".join(item.title for item in activities) or "none"
    return (
        f"Nova Workspace project {row.title} ({row.workspace_id}). "
        f"Description: {row.description or 'none'}. "
        f"Files: {file_line}. Conversations: {convo_line}. Recent changes: {change_line}."
    )


def ask_workspace(
    db: Session,
    payload: NovaWorkspaceBrainRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkspaceBrainOut:
    action = payload.action
    conversation_id = payload.conversation_id
    workspace_id = payload.workspace_id
    question = (payload.question or "").strip()

    if action == "find_file":
        query = question or "file"
        search = search_workspace(db, query, organization_id=organization_id, user=user)
        return NovaWorkspaceBrainOut(
            action=action,
            answer=f"Mrs. Nova Brain searched Nova Workspace files and work for “{search.query}”.",
            search=search,
            generated_at=NovaCoreService._now(),
        )
    if action == "search_prior":
        query = question or "recent work"
        search = search_workspace(db, query, organization_id=organization_id, user=user)
        return NovaWorkspaceBrainOut(
            action=action,
            answer=f"Mrs. Nova Brain searched prior Nova Workspace work for “{search.query}”.",
            search=search,
            generated_at=NovaCoreService._now(),
        )

    context_prefix = ""
    if workspace_id:
        context_prefix = _project_context(
            db, workspace_id, organization_id=organization_id, user=user
        ) + "\n\n"

    if action == "summarize":
        source = context_prefix or question or "Summarize this Nova Workspace."
        summary = NovaCoreService.summarize(
            db,
            organization_id=organization_id,
            summary_type="build_progress",
            mode="founder_advisor",
            source_text=source[:10000],
        )
        answer = summary.summary
        next_actions = summary.highlights
    elif action == "next_action":
        step = NovaCoreService.next_step(
            db,
            organization_id=organization_id,
            mode="founder_advisor",
            goal=question or (context_prefix[:400] if context_prefix else "Continue Nova Workspace work"),
        )
        answer = step.next_recommended_step
        next_actions = step.checklist
    elif action == "explain_changed":
        asked = NovaCoreService.ask(
            db,
            organization_id=organization_id,
            mode="founder_advisor",
            question=(context_prefix + (question or "Explain what changed recently in this Nova Workspace.")).strip(),
        )
        answer = asked.answer
        next_actions = asked.next_actions
    else:
        if action == "continue" and conversation_id:
            _convo, messages = get_conversation(
                db, conversation_id, organization_id=organization_id, user=user, touch=True
            )
            prior = "\n".join(f"{item.role}: {item.content}" for item in messages[-8:])
            context_prefix += f"Prior Nova Workspace thread:\n{prior}\n\n"
        if len(question) < 3 and action != "continue":
            raise NovaWorkspaceError("Ask Mrs. Nova Brain at least 3 characters", status_code=422)
        prompt = (context_prefix + (question or "Continue the previous Nova Workspace thread.")).strip()
        asked = NovaCoreService.ask(
            db,
            organization_id=organization_id,
            mode="founder_advisor",
            question=prompt[:4000],
        )
        answer = asked.answer
        next_actions = asked.next_actions

    if conversation_id:
        convo, _msgs = get_conversation(
            db, conversation_id, organization_id=organization_id, user=user
        )
    else:
        convo = create_conversation(
            db,
            NovaWorkspaceConversationCreate(
                title=(question or action)[:180],
                workspace_id=workspace_id,
            ),
            organization_id=organization_id,
            user=user,
        )
        conversation_id = convo.conversation_id
    if question:
        append_message(
            db,
            conversation_id,
            organization_id=organization_id,
            user=user,
            role="user",
            content=question,
        )
    append_message(
        db,
        conversation_id,
        organization_id=organization_id,
        user=user,
        role="assistant",
        content=answer,
    )
    return NovaWorkspaceBrainOut(
        action=action,
        answer=answer,
        next_actions=next_actions or [],
        conversation_id=conversation_id,
        generated_at=NovaCoreService._now(),
    )
