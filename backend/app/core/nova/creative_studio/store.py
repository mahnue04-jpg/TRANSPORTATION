"""In-process Creative Studio store with owner isolation."""

from __future__ import annotations

from typing import Any

from app.core.nova.creative_studio.models import (
    BrandProfile,
    ContentBrief,
    CreativeAsset,
    CreativeProject,
    CreativeScene,
    GenerationJob,
)


class CreativeStudioStore:
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


_STORE: CreativeStudioStore | None = None


def get_store() -> CreativeStudioStore:
    global _STORE
    if _STORE is None:
        _STORE = CreativeStudioStore()
    return _STORE


def reset_store_for_tests() -> None:
    global _STORE
    _STORE = CreativeStudioStore()
