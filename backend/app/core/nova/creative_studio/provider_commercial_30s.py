"""Guarded 30-second provider commercial.

The paid path is FalKlingVideoProvider motion plus FalKlingLipSyncProvider
narration sync. Planning, reservation, resume checks, and downloads do not
call fal. Local montage stays a separate offline demo and is not this path.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from typing import Any

from app.core.nova.creative_studio.models import new_id
from app.core.nova.creative_studio.studio_checkout import RENDER_COST_CEILING_USD

SHOT_COUNT = 6
SHOT_SECONDS = 5
PRONUNCIATION = "AM ih core"
PRICE_SOURCE = "owner_verified_provider_price"
_BRAND = re.compile(r"\bAMICOR\b")
_PHONETIC = re.compile(r"AH-mih-kor|AM\s+ih\s+core", re.IGNORECASE)
_PRICE_KEYS = {
    "source",
    "currency",
    "motion_usd_per_5s_shot",
    "lipsync_usd_per_clip",
    "shot_count",
    "balance_usd",
    "balance_status",
}
_OPEN_STATUSES = {"reserved", "submitting", "processing", "ambiguous"}


def credential_booleans() -> dict[str, bool]:
    """Presence and activation only. Never return a key or its prefix."""
    video_on = str(os.getenv("NOVA_CREATIVE_VIDEO_LIVE_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    kling_on = str(os.getenv("NOVA_CREATIVE_KLING_LIVE_ENABLED") or "").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "fal_key_present": bool(str(os.getenv("FAL_KEY") or "").strip()),
        "video_live_enabled": video_on,
        "kling_live_enabled": kling_on,
        "kling_activation_ready": video_on and kling_on,
    }


def _now(service) -> str:
    from app.core.nova.creative_studio.service import _now as stamp

    return stamp()


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _cents(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        return None
    scaled = number * 100
    nearest = round(scaled)
    if abs(scaled - nearest) > 1e-6:
        return None
    cents = int(nearest)
    return cents if cents > 0 else None


def _money(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def _load(project) -> dict[str, Any] | None:
    raw = (project.metadata or {}).get("provider_commercial_30s_reservation")
    return dict(raw) if isinstance(raw, dict) else None


def _save_reservation(service, project, reservation: dict[str, Any]) -> None:
    meta = dict(project.metadata or {})
    meta["provider_commercial_30s_reservation"] = reservation
    project.metadata = meta
    project.updated_at = _now(service)
    service.store.save_project(project)


def _atomic_claim_reservation(service, owner_id: str, project_id: str, *, expected_status: str) -> bool:
    """Claim a reserved job once, across DB-backed concurrent requests.

    A failed or unavailable conditional update refuses any billable work. Recovery
    from an interrupted claim is deliberately manual until provider reconciliation.
    """
    store = service.store
    claim = getattr(store, "compare_and_swap_project_metadata", None)
    if not callable(claim):
        return False
    project = service._project_or_404(owner_id, project_id)
    before = json.loads(json.dumps(project.metadata or {}))
    reservation = before.get("provider_commercial_30s_reservation")
    if not isinstance(reservation, dict) or reservation.get("status") != expected_status:
        return False
    if reservation.get("owner_submit_authorized") or reservation.get("submission_claimed"):
        return False
    after = json.loads(json.dumps(before))
    next_reservation = after["provider_commercial_30s_reservation"]
    next_reservation["submission_claimed"] = True
    next_reservation["status"] = "submitting"
    next_reservation["charge_status"] = "no_provider_post"
    return bool(claim(project_id, owner_id, before, after))


def _provider_status() -> dict[str, Any]:
    from app.core.nova.creative_studio.kling import FalKlingLipSyncProvider, FalKlingVideoProvider

    motion = FalKlingVideoProvider().status()
    lipsync = FalKlingLipSyncProvider().status()
    return {
        "motion_provider": motion.provider_id,
        "motion_status": motion.status,
        "motion_configured": bool(motion.configured),
        "lipsync_provider": lipsync.provider_id,
        "lipsync_status": lipsync.status,
        "lipsync_configured": bool(lipsync.configured),
        "providers_available": motion.status == "AVAILABLE" and lipsync.status == "AVAILABLE",
    }


def _ambiguous_posts(reservation: dict[str, Any] | None) -> bool:
    if not reservation:
        return False
    for shot in reservation.get("shots") or []:
        if shot.get("post_attempted") is True and not str(shot.get("motion_task_id") or "").strip():
            return True
        if shot.get("lipsync_post_attempted") is True and not str(shot.get("lipsync_task_id") or "").strip():
            return True
    return False


def _selection(service, owner_id: str, project_id: str) -> dict[str, Any]:
    project = service._project_or_404(owner_id, project_id)
    blockers: list[str] = []
    if int(project.duration_target or 0) != 30:
        blockers.append("duration_not_30")
    image = service._resolve_genova_presenter_image(owner_id, project_id)
    approved_image_id = str((project.metadata or {}).get("approved_genova_image_asset_id") or "")
    image_asset = next(
        (
            asset
            for asset in service.store.list_assets(project_id, owner_id)
            if asset.id == approved_image_id and asset.kind == "image"
        ),
        None,
    )
    if image is None or image_asset is None:
        blockers.append("missing_presenter_image")
    narration = service.genova_narration_readiness(owner_id, project_id)
    narration_asset = None
    if narration.get("approved") and narration.get("approved_asset_id"):
        narration_asset = next(
            (
                asset
                for asset in service.store.list_assets(project_id, owner_id)
                if asset.id == narration["approved_asset_id"] and asset.kind == "audio"
            ),
            None,
        )
    if narration_asset is None:
        blockers.append("missing_narration_audio")
    script = _text(narration_asset.content) if narration_asset is not None else ""
    if script and not _BRAND.search(script):
        blockers.append("missing_brand_pronunciation")
    if script and _PHONETIC.search(script):
        blockers.append("phonetic_script_not_exact")
    contract = str((narration_asset.metadata or {}).get("pronunciation_contract") or "") if narration_asset else ""
    if narration_asset is not None and contract != PRONUNCIATION:
        blockers.append("pronunciation_unconfirmed")
    scenes = service.store.list_scenes(project_id, owner_id)
    lines = [_text(scene.voiceover_text) for scene in scenes]
    if len(scenes) != SHOT_COUNT or any(not line for line in lines) or _text(" ".join(lines)) != script:
        blockers.append("ambiguous_shot_plan")
    shot_ids = list((narration_asset.metadata or {}).get("shot_audio_asset_ids") or []) if narration_asset else []
    shot_assets = []
    if narration_asset is not None:
        if not isinstance(shot_ids, list) or len(shot_ids) != SHOT_COUNT or len({str(item) for item in shot_ids}) != SHOT_COUNT:
            blockers.append("ambiguous_narration_slices")
        else:
            assets = {asset.id: asset for asset in service.store.list_assets(project_id, owner_id)}
            for asset_id in shot_ids:
                asset = assets.get(str(asset_id))
                path = None
                if asset is not None and asset.kind == "audio" and asset.url:
                    from app.core.nova.creative_studio.providers import _resolve_creative_media_url

                    path = _resolve_creative_media_url(asset.url)
                if asset is None or path is None or not path.is_file():
                    blockers.append("ambiguous_narration_slices")
                    shot_assets = []
                    break
                shot_assets.append(asset)
    approval = (project.metadata or {}).get("approved_genova_narration") or {}
    return {
        "project": project,
        "blockers": blockers,
        "image_asset": image_asset,
        "image_path": image,
        "narration_asset": narration_asset,
        "script": script,
        "script_sha256": hashlib.sha256(script.encode()).hexdigest() if script else "",
        "file_sha256": str(approval.get("file_sha256") or ""),
        "pronunciation": PRONUNCIATION if contract == PRONUNCIATION else None,
        "lines": lines,
        "shot_assets": shot_assets,
        "scenes": scenes,
    }


def _price(price_card: dict[str, Any] | None) -> dict[str, Any]:
    empty = {
        "blockers": ["unverified_per_shot_price"],
        "verified": False,
        "motion_cents": None,
        "lipsync_cents": None,
        "total_cents": None,
        "balance_cents": None,
        "balance_status": "cannot_verify",
    }
    if not isinstance(price_card, dict):
        return empty
    blockers: list[str] = []
    extra = set(price_card) - _PRICE_KEYS
    missing = _PRICE_KEYS - set(price_card)
    if extra:
        blockers.append("ambiguous_price")
    elif missing:
        blockers.append("unverified_per_shot_price")
    source = price_card.get("source")
    if source != PRICE_SOURCE and "ambiguous_price" not in blockers and "unverified_per_shot_price" not in blockers:
        blockers.append("unverified_per_shot_price")
    if price_card.get("currency") != "USD" or type(price_card.get("shot_count")) is not int or price_card.get("shot_count") != SHOT_COUNT:
        if "unverified_per_shot_price" not in blockers:
            blockers.append("ambiguous_price")
    motion_cents = _cents(price_card.get("motion_usd_per_5s_shot"))
    lipsync_cents = _cents(price_card.get("lipsync_usd_per_clip"))
    balance_cents = _cents(price_card.get("balance_usd"))
    if motion_cents is None or lipsync_cents is None:
        if "unverified_per_shot_price" not in blockers:
            blockers.append("ambiguous_price")
    total_cents = None
    if motion_cents is not None and lipsync_cents is not None and price_card.get("shot_count") == SHOT_COUNT:
        total_cents = SHOT_COUNT * (motion_cents + lipsync_cents)
        if total_cents > int(round(RENDER_COST_CEILING_USD * 100)):
            blockers.append("above_internal_ceiling")
    balance_status = price_card.get("balance_status")
    if balance_status != "owner_reported":
        blockers.append("balance_unverified" if balance_status in {None, "", "cannot_verify"} else "ambiguous_price")
    elif balance_cents is None:
        blockers.append("ambiguous_price")
    elif total_cents is not None and balance_cents < total_cents:
        blockers.append("insufficient_reported_balance")
    blockers = list(dict.fromkeys(blockers))
    return {
        "blockers": blockers,
        "verified": not blockers and total_cents is not None,
        "motion_cents": motion_cents,
        "lipsync_cents": lipsync_cents,
        "total_cents": total_cents,
        "balance_cents": balance_cents,
        "balance_status": balance_status if isinstance(balance_status, str) else "cannot_verify",
    }


def _key(owner_id: str, project_id: str, selected: dict[str, Any], priced: dict[str, Any]) -> str:
    payload = {
        "owner_id": owner_id,
        "project_id": project_id,
        "image_asset_id": getattr(selected.get("image_asset"), "id", None),
        "narration_asset_id": getattr(selected.get("narration_asset"), "id", None),
        "file_sha256": selected.get("file_sha256"),
        "script_sha256": selected.get("script_sha256"),
        "pronunciation": selected.get("pronunciation"),
        "lines": selected.get("lines"),
        "shot_audio_asset_ids": [asset.id for asset in selected.get("shot_assets") or []],
        "motion_cents": priced.get("motion_cents"),
        "lipsync_cents": priced.get("lipsync_cents"),
        "total_cents": priced.get("total_cents"),
        "balance_cents": priced.get("balance_cents"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _view(selected: dict[str, Any], priced: dict[str, Any], reservation: dict[str, Any] | None, blockers: list[str]) -> dict[str, Any]:
    credentials = credential_booleans()
    providers = _provider_status()
    posts = int((reservation or {}).get("provider_posts") or 0)
    authorized = bool(
        reservation
        and reservation.get("status") in {"reserved", "processing"}
        and reservation.get("owner_submit_authorized") is True
        and providers["providers_available"]
        and credentials["fal_key_present"]
        and credentials["kling_activation_ready"]
        and not blockers
        and not _ambiguous_posts(reservation)
    )
    total_cents = priced.get("total_cents")
    return {
        "mode": "NON_BILLABLE_PLAN",
        "project_id": selected["project"].id,
        "provider_motion": "fal_kling_video",
        "provider_lipsync": "fal_kling_lipsync",
        "output_class": "provider_backed_30s" if authorized else "not_authorized",
        "offline_demo_fallback": "separate_route",
        "uses_local_montage": False,
        "paid_provider_charges": None if posts or _ambiguous_posts(reservation) else False,
        "charge_status": "potential_charge_unverified" if posts or _ambiguous_posts(reservation) else "no_provider_post",
        "provider_posts": posts,
        "credentials": credentials,
        "activation": {
            "video_live_enabled": credentials["video_live_enabled"],
            "kling_live_enabled": credentials["kling_live_enabled"],
            "both_required": True,
        },
        "providers": providers,
        "approved_image_asset_id": getattr(selected.get("image_asset"), "id", None),
        "approved_narration_asset_id": getattr(selected.get("narration_asset"), "id", None),
        "script_sha256": selected.get("script_sha256"),
        "pronunciation": PRONUNCIATION,
        "pronunciation_confirmed": selected.get("pronunciation") == PRONUNCIATION,
        "exact_script": selected.get("script") or "",
        "shot_count": SHOT_COUNT,
        "shot_seconds": SHOT_SECONDS,
        "price": {
            "verified": bool(priced.get("verified")),
            "source": PRICE_SOURCE if priced.get("verified") else None,
            "per_shot_motion_usd": _money(priced["motion_cents"]) if priced.get("motion_cents") else None,
            "per_shot_lipsync_usd": _money(priced["lipsync_cents"]) if priced.get("lipsync_cents") else None,
            "total_usd": _money(total_cents) if total_cents else None,
            "ceiling_usd": f"{RENDER_COST_CEILING_USD:.2f}",
            "within_ceiling": bool(total_cents is not None and total_cents <= int(round(RENDER_COST_CEILING_USD * 100))),
            "balance_status": priced.get("balance_status"),
            "balance_usd": _money(priced["balance_cents"]) if priced.get("balance_cents") else None,
        },
        "blockers": blockers,
        "can_reserve": not blockers,
        "submission_authorized": authorized,
        "reservation": _public_reservation(reservation),
    }


def _public_reservation(reservation: dict[str, Any] | None) -> dict[str, Any] | None:
    if not reservation:
        return None
    hidden = {"price_card"}
    return {key: value for key, value in reservation.items() if key not in hidden}


def plan_provider_commercial_30s(service, owner_id: str, project_id: str, price_card: dict[str, Any] | None = None) -> dict[str, Any]:
    selected = _selection(service, owner_id, project_id)
    reservation = _load(selected["project"])
    card = price_card if price_card is not None else (reservation or {}).get("price_card")
    priced = _price(card if isinstance(card, dict) else None)
    blockers = list(dict.fromkeys([*selected["blockers"], *priced["blockers"]]))
    if reservation and reservation.get("status") in _OPEN_STATUSES:
        current = _key(owner_id, project_id, selected, priced) if priced.get("verified") and not selected["blockers"] else None
        if current and reservation.get("idempotency_key") != current:
            blockers.append("ambiguous_open_reservation")
    return _view(selected, priced, reservation, blockers)


def reserve_provider_commercial_30s(service, owner_id: str, project_id: str, price_card: dict[str, Any] | None) -> dict[str, Any]:
    """Create one durable hold. Does not post to a provider."""
    selected = _selection(service, owner_id, project_id)
    project = selected["project"]
    existing = _load(project)
    priced = _price(price_card)
    blockers = list(dict.fromkeys([*selected["blockers"], *priced["blockers"]]))
    if blockers:
        if existing and existing.get("status") in _OPEN_STATUSES and "ambiguous_open_reservation" not in blockers:
            current_key = existing.get("idempotency_key")
            fresh = _key(owner_id, project_id, selected, priced) if priced.get("verified") and not selected["blockers"] else None
            if fresh and fresh != current_key:
                blockers.append("ambiguous_open_reservation")
        view = _view(selected, priced, existing, blockers)
        view["reserved"] = False
        view["provider_posts"] = int((existing or {}).get("provider_posts") or 0)
        return view
    key = _key(owner_id, project_id, selected, priced)
    if existing and existing.get("status") in _OPEN_STATUSES and existing.get("idempotency_key") != key:
        view = _view(selected, priced, existing, ["ambiguous_open_reservation"])
        view["reserved"] = False
        return view
    if existing and existing.get("idempotency_key") == key:
        view = _view(selected, priced, existing, [])
        view["reserved"] = True
        view["idempotent_replay"] = True
        return view
    reservation = {
        "reservation_id": new_id("cres"),
        "idempotency_key": key,
        "status": "reserved",
        "amount_usd": _money(priced["total_cents"]),
        "amount_cents": priced["total_cents"],
        "ceiling_usd": f"{RENDER_COST_CEILING_USD:.2f}",
        "provider_posts": 0,
        "motion_posts": 0,
        "lipsync_posts": 0,
        "paid_provider_charges": False,
        "owner_submit_authorized": False,
        "created_at": _now(service),
        "image_asset_id": selected["image_asset"].id,
        "narration_asset_id": selected["narration_asset"].id,
        "script_sha256": selected["script_sha256"],
        "pronunciation": PRONUNCIATION,
        "price_card": {key: price_card[key] for key in _PRICE_KEYS},
        "shots": [
            {
                "index": index,
                "voiceover_text": line,
                "audio_asset_id": audio.id,
                "audio_url": audio.url,
                "motion_task_id": None,
                "lipsync_task_id": None,
                "post_attempted": False,
                "lipsync_post_attempted": False,
                "saved_url": None,
                "lipsync_url": None,
            }
            for index, (line, audio) in enumerate(zip(selected["lines"], selected["shot_assets"]), start=1)
        ],
    }
    _save_reservation(service, project, reservation)
    _write_download(service, owner_id, project_id, reservation)
    view = _view(selected, priced, _load(service._project_or_404(owner_id, project_id)), [])
    view["reserved"] = True
    view["idempotent_replay"] = False
    return view


def _write_download(service, owner_id: str, project_id: str, reservation: dict[str, Any]) -> None:
    from app.core.nova.creative_studio.providers import _creative_media_root_and_prefix

    root, prefix = _creative_media_root_and_prefix()
    root.mkdir(parents=True, exist_ok=True)
    filename = f"nova-30s-reservation-{reservation['reservation_id']}.json"
    body = json.dumps(_public_reservation(reservation), sort_keys=True, indent=2)
    (root / filename).write_text(body, encoding="utf-8")
    if reservation.get("download_asset_id"):
        return
    asset = service._save_text_asset(
        owner_id=owner_id,
        project_id=project_id,
        kind="cost_reservation",
        title="30s provider cost reservation",
        content=reservation["amount_usd"],
        status="RESERVED",
        metadata={
            "reservation_id": reservation["reservation_id"],
            "paid_provider_charges": False,
            "provider_posts": 0,
            "output_class": "cost_reservation",
        },
        url=f"{prefix}/{filename}",
    )
    project = service._project_or_404(owner_id, project_id)
    current = _load(project) or reservation
    current["download_asset_id"] = asset.id
    _save_reservation(service, project, current)
    (root / filename).write_text(json.dumps(_public_reservation(current), sort_keys=True, indent=2), encoding="utf-8")


def validate_provider_commercial_30s_resume(service, owner_id: str, project_id: str) -> dict[str, Any]:
    """Check saved tokens and the downloadable hold. Does not contact fal."""
    from app.core.nova.creative_studio.kling import FalKlingLipSyncProvider, FalKlingVideoProvider
    from app.core.nova.creative_studio.providers import _resolve_creative_media_url

    project = service._project_or_404(owner_id, project_id)
    reservation = _load(project)
    if not reservation:
        return {
            "resume_valid": False,
            "problems": ["no_reservation"],
            "provider_posts": 0,
            "paid_provider_charges": False,
            "download_ready": False,
        }
    posts = int(reservation.get("provider_posts") or 0)
    problems: list[str] = []
    motion = FalKlingVideoProvider()
    lipsync = FalKlingLipSyncProvider()
    for shot in reservation.get("shots") or []:
        motion_token = str(shot.get("motion_task_id") or "").strip()
        lipsync_token = str(shot.get("lipsync_task_id") or "").strip()
        if motion_token:
            try:
                motion._decode_task(motion_token) if hasattr(motion, "_decode_task") else _decode_motion(motion, motion_token)
            except Exception:
                problems.append(f"invalid_motion_task_{shot.get('index')}")
        if lipsync_token:
            try:
                lipsync._decode_lipsync_task(lipsync_token)
            except Exception:
                problems.append(f"invalid_lipsync_task_{shot.get('index')}")
        for field, label in (("saved_url", "motion"), ("lipsync_url", "lipsync")):
            raw = str(shot.get(field) or "").strip()
            if not raw:
                continue
            path = _resolve_creative_media_url(raw)
            if path is None or not path.is_file() or path.stat().st_size <= 0:
                problems.append(f"missing_saved_{label}_{shot.get('index')}")
    download_ready = False
    asset_id = reservation.get("download_asset_id")
    if asset_id:
        try:
            path, _media, _name = service.open_asset_file(owner_id, project_id, asset_id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            download_ready = payload.get("reservation_id") == reservation.get("reservation_id")
            if json.dumps(payload).find("FAL_KEY") >= 0:
                problems.append("download_exposed_secret_name")
                download_ready = False
        except Exception:
            problems.append("reservation_download_unavailable")
    else:
        problems.append("reservation_download_unavailable")
    return {
        "resume_valid": not problems,
        "problems": problems,
        "reservation_id": reservation.get("reservation_id"),
        "provider_posts": posts,
        "paid_provider_charges": None if posts or _ambiguous_posts(reservation) else False,
        "charge_status": "potential_charge_unverified" if posts or _ambiguous_posts(reservation) else "no_provider_post",
        "download_ready": download_ready,
        "saved": True,
    }


def _decode_motion(provider, token: str) -> dict[str, Any]:
    import base64

    from app.core.nova.creative_studio.kling import TOKEN_PREFIX

    if not str(token).startswith(TOKEN_PREFIX) or len(token) > 4000:
        raise ValueError("bad motion token")
    task = json.loads(base64.urlsafe_b64decode(token[len(TOKEN_PREFIX):]))
    provider._validate_task(task)
    return task


def _image_url(selected: dict[str, Any]) -> str:
    asset = selected.get("image_asset")
    return str(getattr(asset, "url", "") or "")


def submit_provider_commercial_30s(
    service,
    owner_id: str,
    project_id: str,
    *,
    authorize_provider_submit: bool = False,
    price_card: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Post motion and lip-sync only after a matching reserved hold and an explicit authorization.

    A saved task is resumed. A post that was started without a saved task id fails closed
    instead of posting again.
    """
    from app.core.nova.creative_studio.kling import FalKlingLipSyncProvider, FalKlingVideoProvider

    project = service._project_or_404(owner_id, project_id)
    existing = _load(project)
    card = price_card if price_card is not None else (existing or {}).get("price_card")
    selected = _selection(service, owner_id, project_id)
    priced = _price(card if isinstance(card, dict) else None)
    blockers = list(dict.fromkeys([*selected["blockers"], *priced["blockers"]]))
    if authorize_provider_submit is not True:
        view = _view(selected, priced, existing, blockers or ["authorization_required"])
        if "authorization_required" not in view["blockers"]:
            view["blockers"] = [*view["blockers"], "authorization_required"]
        view["submission_authorized"] = False
        view["paid_provider_charges"] = False
        return view
    if not existing or existing.get("status") not in _OPEN_STATUSES:
        view = _view(selected, priced, existing, [*blockers, "reservation_required"])
        view["submission_authorized"] = False
        return view
    if blockers or not priced.get("verified"):
        view = _view(selected, priced, existing, blockers or ["unverified_per_shot_price"])
        view["submission_authorized"] = False
        return view
    key = _key(owner_id, project_id, selected, priced)
    if existing.get("idempotency_key") != key:
        view = _view(selected, priced, existing, ["ambiguous_open_reservation"])
        view["submission_authorized"] = False
        return view
    if _ambiguous_posts(existing):
        existing["status"] = "ambiguous"
        _save_reservation(service, project, existing)
        view = _view(selected, priced, existing, ["ambiguous_provider_post"])
        view["submission_authorized"] = False
        return view
    credentials = credential_booleans()
    providers = _provider_status()
    if not credentials["fal_key_present"] or not providers["motion_configured"]:
        view = _view(selected, priced, existing, ["credential_missing"])
        view["submission_authorized"] = False
        return view
    if not providers["providers_available"] or not credentials["kling_activation_ready"]:
        view = _view(selected, priced, existing, ["live_flag_off"])
        view["submission_authorized"] = False
        return view

    # A single DB-backed request may claim the reservation. Fail closed for
    # in-memory stores or a concurrently claimed job; never post on uncertainty.
    if not _atomic_claim_reservation(service, owner_id, project_id, expected_status="reserved"):
        view = _view(selected, priced, existing, ["submission_claim_unavailable"])
        view["submission_authorized"] = False
        return view
    project = service._project_or_404(owner_id, project_id)
    existing = _load(project)
    if not existing or not existing.get("submission_claimed"):
        view = _view(selected, priced, existing, ["submission_claim_unavailable"])
        view["submission_authorized"] = False
        return view
    existing["owner_submit_authorized"] = True
    existing["status"] = "processing"
    existing["paid_provider_charges"] = False
    _save_reservation(service, project, existing)
    image_url = _image_url(selected)
    narration_url = str(selected["narration_asset"].url or "")
    motion_provider = FalKlingVideoProvider()
    lipsync_provider = FalKlingLipSyncProvider()

    def persist() -> None:
        _save_reservation(service, service._project_or_404(owner_id, project_id), existing)

    for shot in existing["shots"]:
        if shot.get("saved_url"):
            continue
        if shot.get("post_attempted") is True and not str(shot.get("motion_task_id") or "").strip():
            existing["status"] = "ambiguous"
            persist()
            view = _view(selected, priced, existing, ["ambiguous_provider_post"])
            view["submission_authorized"] = False
            return view
        resume = str(shot.get("motion_task_id") or "").strip()
        if not resume:
            shot["post_attempted"] = True
            existing["paid_provider_charges"] = None
            existing["charge_status"] = "potential_charge_unverified"
            persist()
            result = motion_provider.generate(
                brief={
                    "project_id": project_id,
                    "shot_index": shot["index"],
                    "prompt_text": shot["voiceover_text"],
                    "objective": shot["voiceover_text"],
                    "prompt_image_url": image_url,
                    "duration_seconds": SHOT_SECONDS,
                    "persist_task_before_poll": True,
                    "generation_mode": "image_to_motion",
                }
            )
            existing["provider_posts"] = int(existing.get("provider_posts") or 0) + 1
            existing["motion_posts"] = int(existing.get("motion_posts") or 0) + 1
            shot["motion_task_id"] = str(result.get("task_id") or "").strip() or None
            if result.get("asset_generated") and result.get("url"):
                shot["saved_url"] = str(result["url"])
            persist()
            if not shot.get("motion_task_id"):
                existing["status"] = "ambiguous"
                persist()
                view = _view(selected, priced, existing, ["ambiguous_provider_post"])
                view["submission_authorized"] = False
                return view
            if not shot.get("saved_url"):
                continue
        else:
            result = motion_provider.generate(
                brief={
                    "project_id": project_id,
                    "shot_index": shot["index"],
                    "prompt_image_url": image_url,
                    "resume_task_id": resume,
                    "persist_task_before_poll": True,
                }
            )
            if result.get("task_id"):
                shot["motion_task_id"] = str(result["task_id"])
            if result.get("asset_generated") and result.get("url"):
                shot["saved_url"] = str(result["url"])
            persist()

    if any(not shot.get("saved_url") for shot in existing["shots"]):
        view = _view(selected, priced, existing, [])
        view["status"] = "PROCESSING"
        view["message"] = "Motion tasks are saved. Resume them before lip-sync. No duplicate post was made."
        view["paid_provider_charges"] = None
        view["charge_status"] = "potential_charge_unverified"
        view["render_mode"] = "fal_kling_motion_then_lipsync"
        view["offline_demo_fallback"] = False
        return view

    for shot in existing["shots"]:
        if shot.get("lipsync_url"):
            continue
        if shot.get("lipsync_post_attempted") is True and not str(shot.get("lipsync_task_id") or "").strip():
            existing["status"] = "ambiguous"
            persist()
            view = _view(selected, priced, existing, ["ambiguous_provider_post"])
            view["submission_authorized"] = False
            return view
        resume = str(shot.get("lipsync_task_id") or "").strip()
        audio_url = str(shot.get("audio_url") or narration_url)
        if not resume:
            shot["lipsync_post_attempted"] = True
            existing["paid_provider_charges"] = None
            existing["charge_status"] = "potential_charge_unverified"
            persist()
            result = lipsync_provider.generate_lipsync(
                video_url=shot["saved_url"],
                audio_url=audio_url,
            )
            existing["provider_posts"] = int(existing.get("provider_posts") or 0) + 1
            existing["lipsync_posts"] = int(existing.get("lipsync_posts") or 0) + 1
            shot["lipsync_task_id"] = str(result.get("task_id") or "").strip() or None
            if result.get("asset_generated") and result.get("url"):
                shot["lipsync_url"] = str(result["url"])
            persist()
            if not shot.get("lipsync_task_id"):
                existing["status"] = "ambiguous"
                persist()
                view = _view(selected, priced, existing, ["ambiguous_provider_post"])
                view["submission_authorized"] = False
                return view
        else:
            result = lipsync_provider.generate_lipsync(
                video_url=shot["saved_url"],
                audio_url=audio_url,
                resume_task_id=resume,
            )
            if result.get("task_id"):
                shot["lipsync_task_id"] = str(result["task_id"])
            if result.get("asset_generated") and result.get("url"):
                shot["lipsync_url"] = str(result["url"])
            persist()

    # Six video URLs are scene-generation evidence, not a finished commercial.
    # Final mux/concatenation, ffprobe duration, captions, and durable MP4 download
    # must be verified separately before claiming the 30-second deliverable.
    scenes_ready = all(shot.get("lipsync_url") for shot in existing["shots"])
    if scenes_ready:
        existing["status"] = "scenes_ready"
        existing["paid_provider_charges"] = None
        existing["charge_status"] = "potential_charge_unverified"
        persist()
    view = _view(selected, priced, existing, [])
    view["status"] = "SCENES_READY" if scenes_ready else "PROCESSING"
    view["render_mode"] = "fal_kling_motion_then_lipsync"
    view["output_class"] = "provider_scenes_pending_final_assembly"
    view["offline_demo_fallback"] = False
    view["uses_local_montage"] = False
    view["true_ai_motion_synthesis"] = scenes_ready
    view["provider_lip_sync"] = scenes_ready
    view["final_mp4_verified"] = False
    view["final_mp4_url"] = None
    view["paid_provider_charges"] = None
    view["charge_status"] = "potential_charge_unverified"
    view["pipeline"] = "provider_commercial_30s"
    view["message"] = (
        "Six synchronized scenes reported ready. Final 30-second MP4 assembly, captions, and downloadable artifact still require verification."
        if scenes_ready
        else "Lip-sync tasks are saved. Resume them instead of posting again."
    )
    return view


def assemble_provider_commercial_30s_offline(service, owner_id: str, project_id: str) -> dict[str, Any]:
    """Owner-scoped, non-billable composition of six *locally saved* lip-sync clips.

    Never downloads remote provider URLs or submits generation jobs. Captioned
    release is deliberately separate and must pass QC before becoming customer-ready.
    """
    from pathlib import Path

    from app.core.nova.creative_studio.provider_commercial_assembly import (
        CommercialAssemblyError,
        assemble_saved_scenes,
    )
    from app.core.nova.creative_studio.providers import (
        _creative_media_root_and_prefix,
        _resolve_creative_media_url,
    )

    project = service._project_or_404(owner_id, project_id)
    reservation = _load(project)
    if not reservation or reservation.get("status") not in {"scenes_ready", "assembled_uncaptioned"}:
        return {"status": "BLOCKED", "reason": "scenes_not_ready", "provider_posts": 0}
    shots = reservation.get("shots") or []
    if len(shots) != SHOT_COUNT or [shot.get("index") for shot in shots] != list(range(1, SHOT_COUNT + 1)):
        return {"status": "BLOCKED", "reason": "invalid_scene_order"}
    existing_id = reservation.get("final_assembly_asset_id")
    if existing_id:
        try:
            path, _, _ = service.open_asset_file(owner_id, project_id, existing_id)
            # An existing video alone is insufficient: its draft-caption sidecar
            # must also survive restart before claiming a reusable preview.
            captions, _, _ = service.open_asset_file(owner_id, project_id, existing_id, part="captions")
            if path.is_file() and path.stat().st_size > 0 and captions.is_file() and captions.stat().st_size > 0:
                return {"status": "ASSEMBLED_UNCAPTIONED", "asset_id": existing_id,
                        "final_mp4_verified": True, "captions_verified": False,
                        "caption_draft_available": True, "idempotent_replay": True}
        except Exception:
            return {"status": "BLOCKED", "reason": "existing_output_missing_manual_review"}
    paths = []
    for shot in shots:
        url = str(shot.get("lipsync_url") or "")
        path = _resolve_creative_media_url(url) if url else None
        if path is None or not path.is_file():
            return {"status": "BLOCKED", "reason": "provider_scene_not_saved_locally",
                    "shot_index": shot.get("index"), "provider_posts": 0}
        paths.append(Path(path))
    root, prefix = _creative_media_root_and_prefix()
    root.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "", str(reservation.get("reservation_id") or ""))
    if not safe_name:
        return {"status": "BLOCKED", "reason": "invalid_reservation_id"}
    output = root / f"nova-provider-commercial-{safe_name}.mp4"
    try:
        assembled = assemble_saved_scenes(paths, output)
    except (CommercialAssemblyError, OSError, ValueError):
        return {"status": "BLOCKED", "reason": "offline_assembly_failed"}
    # open_asset_file(part="captions") serves an SRT beside the MP4.
    # Scene-slot captions are drafts, not verified speech-synchronized captions.
    from app.core.nova.creative_studio.provider_commercial_assembly import write_six_scene_caption_draft
    try:
        write_six_scene_caption_draft(
            [str(shot.get("voiceover_text") or "") for shot in shots],
            output.with_suffix(".srt"),
        )
    except (CommercialAssemblyError, OSError, ValueError):
        return {"status": "BLOCKED", "reason": "caption_draft_failed"}
    asset = service._save_text_asset(
        owner_id=owner_id, project_id=project_id, kind="video",
        title="Genova 30s commercial (uncaptioned QC preview)",
        content="Offline assembled preview; captions and final customer acceptance pending",
        status="QC_PENDING",
        url=f"{prefix}/{output.name}",
        metadata={"source": "provider_commercial_30s", "scene_count": SHOT_COUNT,
                  "duration_seconds": assembled["duration_seconds"],
                  "captions_verified": False, "caption_draft_available": True,
                  "customer_ready": False},
    )
    reservation["final_assembly_asset_id"] = asset.id
    reservation["status"] = "assembled_uncaptioned"
    _save_reservation(service, project, reservation)
    return {"status": "ASSEMBLED_UNCAPTIONED", "asset_id": asset.id,
            "final_mp4_verified": True, "captions_verified": False,
            "customer_ready": False, "provider_posts": 0}
