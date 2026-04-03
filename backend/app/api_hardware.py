from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.models.user import User
from app.services.hardware_generator import (
    HardwareGenerationError,
    generate_hardware_content,
    hardware_to_docx_bytes,
)

router = APIRouter(tags=["hardware"])
logger = logging.getLogger(__name__)

UI_DIR = Path(__file__).resolve().parent / "ui"

MAX_REF_LEN = 64
HARDWARE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW_SECONDS = 10 * 60
_rate_limit: Dict[int, List[float]] = {}


class HardwareRequest(BaseModel):
    hardware_reference: str


def require_roles(roles: List[str]):
    def _dependency(user: User = Depends(get_current_user)) -> User:
        actual_role = str(user.role).split(".")[-1]
        if actual_role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        return user

    return _dependency


def _validate_hardware_reference(hardware_reference: str) -> str:
    value = (hardware_reference or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="hardware_reference requis")
    if len(value) > MAX_REF_LEN:
        raise HTTPException(status_code=400, detail="hardware_reference trop long")
    if not HARDWARE_REF_RE.match(value):
        raise HTTPException(status_code=400, detail="hardware_reference invalide")
    return value


def _enforce_rate_limit(user_id: int) -> None:
    now = time.time()
    recent = [t for t in _rate_limit.get(user_id, []) if now - t < RATE_LIMIT_WINDOW_SECONDS]
    if len(recent) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail="Trop de générations. Merci de réessayer plus tard.",
        )
    recent.append(now)
    _rate_limit[user_id] = recent


@router.get("/hardware", response_class=HTMLResponse)
def hardware_page(_: User = Depends(get_current_user)):
    page = UI_DIR / "hardware.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Page hardware introuvable")
    return FileResponse(page)


@router.post("/api/hardware/debug")
def hardware_debug(
    payload: HardwareRequest,
    user: User = Depends(require_roles(["USER", "ADMIN"])),
):
    hardware_ref = _validate_hardware_reference(payload.hardware_reference)
    _enforce_rate_limit(user.id)
    try:
        result = generate_hardware_content(hardware_ref)
    except HardwareGenerationError as exc:
        logger.warning("hardware_debug_failed: %s", exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return result


@router.post("/api/hardware/docx")
def hardware_docx(
    payload: HardwareRequest,
    user: User = Depends(require_roles(["USER", "ADMIN"])),
):
    hardware_ref = _validate_hardware_reference(payload.hardware_reference)
    _enforce_rate_limit(user.id)
    try:
        result = generate_hardware_content(hardware_ref)
    except HardwareGenerationError as exc:
        logger.warning("hardware_docx_failed: %s", exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    docx_bytes = hardware_to_docx_bytes(hardware_ref, result["output_json"])
    filename = f"hardware_{hardware_ref}.docx"
    return StreamingResponse(
        iter([docx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\""},
    )
