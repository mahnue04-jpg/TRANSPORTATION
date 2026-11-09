"""Owner-scoped private master download HTTP headers without networking."""
import hashlib
import io
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.core.nova.creative_studio import router as studio_router


def _request(query=b""):
    return Request({
        "type": "http", "method": "GET", "path": "/file",
        "query_string": query, "headers": [],
    })


def test_private_download_response_advertises_exact_verified_size(monkeypatch):
    data = b"synthetic-private-master"
    sha = hashlib.sha256(data).hexdigest()
    opened = []

    class FakeService:
        def open_private_remote_asset(self, owner, project, asset, *, part):
            opened.append((owner, project, asset, part))
            return (io.BytesIO(data), "video/mp4", "master.mp4", len(data), sha)

    monkeypatch.setattr(studio_router, "get_service", lambda db: FakeService())
    response = studio_router.download_asset_file(
        "project", "master-1", _request(), "media",
        SimpleNamespace(user_id="owner", email=""), object(),
    )
    assert isinstance(response, StreamingResponse)
    assert response.headers["content-length"] == str(len(data))
    assert response.headers["content-type"] == "video/mp4"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in response.headers["content-disposition"]
    assert opened == [("owner", "project", "master-1", "media")]


def test_download_rejects_bearer_token_in_query_before_storage(monkeypatch):
    monkeypatch.setattr(
        studio_router, "get_service",
        lambda db: pytest.fail("Token in query must be rejected first")
    )
    with pytest.raises(HTTPException) as error:
        studio_router.download_asset_file(
            "project", "master-1", _request(b"token=secret"), "media",
            SimpleNamespace(user_id="owner", email=""), object(),
        )
    assert error.value.status_code == 400
