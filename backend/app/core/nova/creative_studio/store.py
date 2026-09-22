"""Creative Studio store: owner-scoped persistence.

Default runtime path uses the shared SQLAlchemy engine/session.
An in-memory store remains available for isolated unit tests.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.nova.creative_studio.db_models import (
    NovaCreativeAsset,
    NovaCreativeBrand,
    NovaCreativeBrief,
    NovaCreativeJob,
    NovaCreativeProject,
    NovaCreativeScene,
)
from app.core.nova.creative_studio.models import (
    BrandProfile,
    ContentBrief,
    CreativeAsset,
    CreativeProject,
    CreativeScene,
    GenerationJob,
)
from app.core.nova.creative_studio.schema_ensure import ensure_nova_creative_schema
from app.db.session import SessionLocal


def _dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=True)


def _dumps_list(value: Any) -> str:
    return json.dumps(list(value or []), ensure_ascii=True)


def _loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


class CreativeStudioStore:
    """In-process Creative Studio store with owner isolation (tests / fallback)."""

    def __init__(self) -> None:
        self.projects: dict[str, CreativeProject] = {}
        self.assets: dict[str, CreativeAsset] = {}
        self.scenes: dict[str, CreativeScene] = {}
        self.brands: dict[str, BrandProfile] = {}
        self.briefs: dict[str, ContentBrief] = {}
        self.jobs: dict[str, GenerationJob] = {}

    def reset(self) -> None:
        self.projects.clear()
        self.assets.clear()
        self.scenes.clear()
        self.brands.clear()
        self.briefs.clear()
        self.jobs.clear()

    def save_project(self, row: CreativeProject) -> CreativeProject:
        self.projects[row.id] = row
        return row

    def get_project(self, project_id: str, owner_id: str) -> CreativeProject | None:
        row = self.projects.get(project_id)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    def list_projects(self, owner_id: str) -> list[CreativeProject]:
        return sorted(
            [p for p in self.projects.values() if p.owner_id == owner_id],
            key=lambda p: p.updated_at,
            reverse=True,
        )

    def save_asset(self, row: CreativeAsset) -> CreativeAsset:
        self.assets[row.id] = row
        return row

    def list_assets(self, project_id: str, owner_id: str) -> list[CreativeAsset]:
        return sorted(
            [
                a
                for a in self.assets.values()
                if a.project_id == project_id and a.owner_id == owner_id
            ],
            key=lambda a: a.created_at,
        )

    def save_scene(self, row: CreativeScene) -> CreativeScene:
        self.scenes[row.id] = row
        return row

    def list_scenes(self, project_id: str, owner_id: str) -> list[CreativeScene]:
        rows = [
            s
            for s in self.scenes.values()
            if s.project_id == project_id and s.owner_id == owner_id
        ]
        return sorted(rows, key=lambda s: s.index)

    def delete_scenes(self, project_id: str, owner_id: str) -> None:
        for scene_id in [
            s.id for s in self.scenes.values() if s.project_id == project_id and s.owner_id == owner_id
        ]:
            self.scenes.pop(scene_id, None)

    def save_brand(self, row: BrandProfile) -> BrandProfile:
        self.brands[row.id] = row
        return row

    def get_brand(self, brand_id: str, owner_id: str) -> BrandProfile | None:
        row = self.brands.get(brand_id)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    def list_brands(self, owner_id: str) -> list[BrandProfile]:
        return sorted(
            [b for b in self.brands.values() if b.owner_id == owner_id],
            key=lambda b: b.updated_at,
            reverse=True,
        )

    def save_brief(self, row: ContentBrief) -> ContentBrief:
        self.briefs[row.id] = row
        return row

    def get_brief(self, brief_id: str, owner_id: str) -> ContentBrief | None:
        row = self.briefs.get(brief_id)
        if row is None or row.owner_id != owner_id:
            return None
        return row

    def save_job(self, row: GenerationJob) -> GenerationJob:
        self.jobs[row.id] = row
        return row

    def list_jobs(self, project_id: str, owner_id: str) -> list[GenerationJob]:
        return sorted(
            [
                j
                for j in self.jobs.values()
                if j.project_id == project_id and j.owner_id == owner_id
            ],
            key=lambda j: j.created_at,
            reverse=True,
        )

    def snapshot(self, owner_id: str) -> dict[str, Any]:
        return {
            "projects": [p.as_dict() for p in self.list_projects(owner_id)],
            "brands": [b.as_dict() for b in self.list_brands(owner_id)],
        }


class DbCreativeStudioStore:
    """Owner-scoped Creative Studio persistence on the shared application DB."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def save_project(self, row: CreativeProject) -> CreativeProject:
        orm = self.db.get(NovaCreativeProject, row.id)
        if orm is None:
            orm = NovaCreativeProject(id=row.id, owner_id=row.owner_id)
            self.db.add(orm)
        elif orm.owner_id != row.owner_id:
            raise PermissionError("owner isolation violation on project write")
        orm.title = row.title
        orm.project_type = row.project_type
        orm.platform = row.platform
        orm.objective = row.objective or ""
        orm.audience = row.audience or ""
        orm.tone = row.tone or ""
        orm.duration_target = row.duration_target
        orm.status = row.status
        orm.brand_profile_id = row.brand_profile_id
        orm.brief_id = row.brief_id
        orm.metadata_json = _dumps(row.metadata or {})
        orm.created_at = row.created_at
        orm.updated_at = row.updated_at
        self.db.commit()
        self.db.refresh(orm)
        return self._project_from_orm(orm)

    def get_project(self, project_id: str, owner_id: str) -> CreativeProject | None:
        orm = (
            self.db.query(NovaCreativeProject)
            .filter(NovaCreativeProject.id == project_id, NovaCreativeProject.owner_id == owner_id)
            .one_or_none()
        )
        return self._project_from_orm(orm) if orm else None

    def list_projects(self, owner_id: str) -> list[CreativeProject]:
        rows = (
            self.db.query(NovaCreativeProject)
            .filter(NovaCreativeProject.owner_id == owner_id)
            .order_by(NovaCreativeProject.updated_at.desc())
            .all()
        )
        return [self._project_from_orm(row) for row in rows]

    def save_asset(self, row: CreativeAsset) -> CreativeAsset:
        orm = self.db.get(NovaCreativeAsset, row.id)
        if orm is None:
            orm = NovaCreativeAsset(id=row.id, owner_id=row.owner_id, project_id=row.project_id)
            self.db.add(orm)
        elif orm.owner_id != row.owner_id:
            raise PermissionError("owner isolation violation on asset write")
        orm.project_id = row.project_id
        orm.kind = row.kind
        orm.title = row.title
        orm.content = row.content or ""
        orm.status = row.status
        orm.mime_type = row.mime_type or "text/plain"
        orm.url = row.url
        orm.metadata_json = _dumps(row.metadata or {})
        orm.created_at = row.created_at
        self.db.commit()
        self.db.refresh(orm)
        return self._asset_from_orm(orm)

    def list_assets(self, project_id: str, owner_id: str) -> list[CreativeAsset]:
        rows = (
            self.db.query(NovaCreativeAsset)
            .filter(NovaCreativeAsset.project_id == project_id, NovaCreativeAsset.owner_id == owner_id)
            .order_by(NovaCreativeAsset.created_at.asc())
            .all()
        )
        return [self._asset_from_orm(row) for row in rows]

    def save_scene(self, row: CreativeScene) -> CreativeScene:
        orm = self.db.get(NovaCreativeScene, row.id)
        if orm is None:
            orm = NovaCreativeScene(id=row.id, owner_id=row.owner_id, project_id=row.project_id)
            self.db.add(orm)
        elif orm.owner_id != row.owner_id:
            raise PermissionError("owner isolation violation on scene write")
        orm.project_id = row.project_id
        orm.scene_index = int(row.index)
        orm.heading = row.heading
        orm.description = row.description or ""
        orm.visual_prompt = row.visual_prompt or ""
        orm.voiceover_text = row.voiceover_text or ""
        orm.subtitle_text = row.subtitle_text or ""
        orm.duration_seconds = float(row.duration_seconds)
        orm.transition_note = row.transition_note or ""
        orm.music_mood_note = row.music_mood_note or ""
        orm.status = row.status
        orm.created_at = row.created_at
        self.db.commit()
        self.db.refresh(orm)
        return self._scene_from_orm(orm)

    def list_scenes(self, project_id: str, owner_id: str) -> list[CreativeScene]:
        rows = (
            self.db.query(NovaCreativeScene)
            .filter(NovaCreativeScene.project_id == project_id, NovaCreativeScene.owner_id == owner_id)
            .order_by(NovaCreativeScene.scene_index.asc())
            .all()
        )
        return [self._scene_from_orm(row) for row in rows]

    def delete_scenes(self, project_id: str, owner_id: str) -> None:
        (
            self.db.query(NovaCreativeScene)
            .filter(NovaCreativeScene.project_id == project_id, NovaCreativeScene.owner_id == owner_id)
            .delete(synchronize_session=False)
        )
        self.db.commit()

    def save_brand(self, row: BrandProfile) -> BrandProfile:
        orm = self.db.get(NovaCreativeBrand, row.id)
        if orm is None:
            orm = NovaCreativeBrand(id=row.id, owner_id=row.owner_id)
            self.db.add(orm)
        elif orm.owner_id != row.owner_id:
            raise PermissionError("owner isolation violation on brand write")
        orm.business_name = row.business_name
        orm.logo_reference = row.logo_reference or ""
        orm.tagline = row.tagline or ""
        orm.tone = row.tone or ""
        orm.target_audience = row.target_audience or ""
        orm.preferred_cta = row.preferred_cta or ""
        orm.brand_description = row.brand_description or ""
        orm.prohibited_claims_json = _dumps_list(row.prohibited_claims)
        orm.preferred_platforms_json = _dumps_list(row.preferred_platforms)
        orm.created_at = row.created_at
        orm.updated_at = row.updated_at
        self.db.commit()
        self.db.refresh(orm)
        return self._brand_from_orm(orm)

    def get_brand(self, brand_id: str, owner_id: str) -> BrandProfile | None:
        orm = (
            self.db.query(NovaCreativeBrand)
            .filter(NovaCreativeBrand.id == brand_id, NovaCreativeBrand.owner_id == owner_id)
            .one_or_none()
        )
        return self._brand_from_orm(orm) if orm else None

    def list_brands(self, owner_id: str) -> list[BrandProfile]:
        rows = (
            self.db.query(NovaCreativeBrand)
            .filter(NovaCreativeBrand.owner_id == owner_id)
            .order_by(NovaCreativeBrand.updated_at.desc())
            .all()
        )
        return [self._brand_from_orm(row) for row in rows]

    def save_brief(self, row: ContentBrief) -> ContentBrief:
        orm = self.db.get(NovaCreativeBrief, row.id)
        if orm is None:
            orm = NovaCreativeBrief(id=row.id, owner_id=row.owner_id)
            self.db.add(orm)
        elif orm.owner_id != row.owner_id:
            raise PermissionError("owner isolation violation on brief write")
        orm.project_id = row.project_id
        orm.topic = row.topic
        orm.audience = row.audience or ""
        orm.objective = row.objective or ""
        orm.tone = row.tone or ""
        orm.cta = row.cta or ""
        orm.style = row.style or ""
        orm.key_points_json = _dumps_list(row.key_points)
        orm.duration_target = row.duration_target
        orm.platform = row.platform or "generic"
        orm.created_at = row.created_at
        self.db.commit()
        self.db.refresh(orm)
        return self._brief_from_orm(orm)

    def get_brief(self, brief_id: str, owner_id: str) -> ContentBrief | None:
        orm = (
            self.db.query(NovaCreativeBrief)
            .filter(NovaCreativeBrief.id == brief_id, NovaCreativeBrief.owner_id == owner_id)
            .one_or_none()
        )
        return self._brief_from_orm(orm) if orm else None

    def save_job(self, row: GenerationJob) -> GenerationJob:
        orm = self.db.get(NovaCreativeJob, row.id)
        if orm is None:
            orm = NovaCreativeJob(id=row.id, owner_id=row.owner_id, project_id=row.project_id)
            self.db.add(orm)
        elif orm.owner_id != row.owner_id:
            raise PermissionError("owner isolation violation on job write")
        orm.project_id = row.project_id
        orm.kind = row.kind
        orm.status = row.status
        orm.message = row.message or ""
        orm.result_asset_ids_json = _dumps_list(row.result_asset_ids)
        orm.provider = row.provider
        orm.created_at = row.created_at
        orm.updated_at = row.updated_at
        self.db.commit()
        self.db.refresh(orm)
        return self._job_from_orm(orm)

    def list_jobs(self, project_id: str, owner_id: str) -> list[GenerationJob]:
        rows = (
            self.db.query(NovaCreativeJob)
            .filter(NovaCreativeJob.project_id == project_id, NovaCreativeJob.owner_id == owner_id)
            .order_by(NovaCreativeJob.created_at.desc())
            .all()
        )
        return [self._job_from_orm(row) for row in rows]

    def snapshot(self, owner_id: str) -> dict[str, Any]:
        return {
            "projects": [p.as_dict() for p in self.list_projects(owner_id)],
            "brands": [b.as_dict() for b in self.list_brands(owner_id)],
        }

    @staticmethod
    def _project_from_orm(orm: NovaCreativeProject) -> CreativeProject:
        return CreativeProject(
            id=orm.id,
            owner_id=orm.owner_id,
            title=orm.title,
            project_type=orm.project_type,
            platform=orm.platform,
            objective=orm.objective or "",
            audience=orm.audience or "",
            tone=orm.tone or "",
            duration_target=orm.duration_target,
            status=orm.status,
            brand_profile_id=orm.brand_profile_id,
            brief_id=orm.brief_id,
            metadata=_loads(orm.metadata_json, {}),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _asset_from_orm(orm: NovaCreativeAsset) -> CreativeAsset:
        return CreativeAsset(
            id=orm.id,
            project_id=orm.project_id,
            owner_id=orm.owner_id,
            kind=orm.kind,
            title=orm.title,
            content=orm.content or "",
            status=orm.status,
            mime_type=orm.mime_type or "text/plain",
            url=orm.url,
            metadata=_loads(orm.metadata_json, {}),
            created_at=orm.created_at,
        )

    @staticmethod
    def _scene_from_orm(orm: NovaCreativeScene) -> CreativeScene:
        return CreativeScene(
            id=orm.id,
            project_id=orm.project_id,
            owner_id=orm.owner_id,
            index=int(orm.scene_index),
            heading=orm.heading,
            description=orm.description or "",
            visual_prompt=orm.visual_prompt or "",
            voiceover_text=orm.voiceover_text or "",
            subtitle_text=orm.subtitle_text or "",
            duration_seconds=float(orm.duration_seconds or 0),
            transition_note=orm.transition_note or "",
            music_mood_note=orm.music_mood_note or "",
            status=orm.status,
            created_at=orm.created_at,
        )

    @staticmethod
    def _brand_from_orm(orm: NovaCreativeBrand) -> BrandProfile:
        return BrandProfile(
            id=orm.id,
            owner_id=orm.owner_id,
            business_name=orm.business_name,
            logo_reference=orm.logo_reference or "",
            tagline=orm.tagline or "",
            tone=orm.tone or "",
            target_audience=orm.target_audience or "",
            preferred_cta=orm.preferred_cta or "",
            brand_description=orm.brand_description or "",
            prohibited_claims=list(_loads(orm.prohibited_claims_json, [])),
            preferred_platforms=list(_loads(orm.preferred_platforms_json, [])),
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )

    @staticmethod
    def _brief_from_orm(orm: NovaCreativeBrief) -> ContentBrief:
        return ContentBrief(
            id=orm.id,
            owner_id=orm.owner_id,
            project_id=orm.project_id,
            topic=orm.topic,
            audience=orm.audience or "",
            objective=orm.objective or "",
            tone=orm.tone or "",
            cta=orm.cta or "",
            style=orm.style or "",
            key_points=list(_loads(orm.key_points_json, [])),
            duration_target=orm.duration_target,
            platform=orm.platform or "generic",
            created_at=orm.created_at,
        )

    @staticmethod
    def _job_from_orm(orm: NovaCreativeJob) -> GenerationJob:
        return GenerationJob(
            id=orm.id,
            project_id=orm.project_id,
            owner_id=orm.owner_id,
            kind=orm.kind,
            status=orm.status,
            message=orm.message or "",
            result_asset_ids=list(_loads(orm.result_asset_ids_json, [])),
            provider=orm.provider,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
        )


_STORE: CreativeStudioStore | None = None
_SCHEMA_READY = False


def _ensure_schema_once() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    ensure_nova_creative_schema()
    _SCHEMA_READY = True


def get_store(db: Session | None = None) -> CreativeStudioStore | DbCreativeStudioStore:
    """Runtime default: DB-backed store. Without a session, open a short-lived session store.

    Prefer passing an explicit FastAPI Session via get_service(db=...).
    """
    if db is not None:
        _ensure_schema_once()
        return DbCreativeStudioStore(db)
    global _STORE
    if _STORE is None:
        _STORE = CreativeStudioStore()
    return _STORE


def get_db_store(db: Session | None = None) -> DbCreativeStudioStore:
    _ensure_schema_once()
    if db is not None:
        return DbCreativeStudioStore(db)
    return DbCreativeStudioStore(SessionLocal())


def reset_store_for_tests() -> None:
    """Reset in-memory singleton and recreate Creative Studio tables for DB tests."""
    global _STORE, _SCHEMA_READY
    _STORE = CreativeStudioStore()
    _SCHEMA_READY = False
    # Drop/recreate only Creative Studio tables for isolation in the shared test DB.
    from app.db.session import engine

    for table in (
        NovaCreativeJob.__table__,
        NovaCreativeScene.__table__,
        NovaCreativeAsset.__table__,
        NovaCreativeProject.__table__,
        NovaCreativeBrief.__table__,
        NovaCreativeBrand.__table__,
    ):
        table.drop(bind=engine, checkfirst=True)
    ensure_nova_creative_schema(engine)
    _SCHEMA_READY = True
