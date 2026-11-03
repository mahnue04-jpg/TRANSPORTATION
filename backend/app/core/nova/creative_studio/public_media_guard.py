"""Deny direct static access to owner-imported Studio originals.

A protected asset must be served only by the owner-scoped API endpoint.
This is a defensive guard for existing imported-video files; a follow-up
migration should also move private media outside the static web root.
"""
from pathlib import PurePosixPath

from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles


class GuardedCreativeStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: dict):
        # Starlette normalizes the requested relative path before file lookup.
        # All imported originals use the server-generated imported_video_ prefix.
        # Deny them through EVERY static alias, including /static and /assets.
        normalized = path.replace("\\", "/")
        if PurePosixPath(normalized).name.startswith("imported_video_"):
            return Response(status_code=404, headers={"Cache-Control": "no-store"})
        return await super().get_response(path, scope)
