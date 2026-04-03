from __future__ import annotations

from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.worksheets import Worksheet

router = APIRouter(prefix="/api/worksheets", tags=["worksheets"])

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads" / "worksheets"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/upload")
def upload_worksheet(
    file: UploadFile = File(...),
    techno_id: int | None = Form(None),  # optionnel
    db: Session = Depends(get_db),
):
    if not file.filename:
        raise HTTPException(400, "Filename is required")

    lower = file.filename.lower()
    if not (lower.endswith(".xlsx") or lower.endswith(".xls")):
        raise HTTPException(400, "Only .xlsx/.xls allowed")

    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    out_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
    out_path = UPLOAD_DIR / out_name

    with out_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    row = Worksheet(
        techno_id=techno_id,
        filename=safe_name,
        stored_path=str(out_path),
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    return {"ok": True, "worksheet_id": row.id, "filename": row.filename}


@router.get("/{worksheet_id}")
def get_worksheet(worksheet_id: int, db: Session = Depends(get_db)):
    row = db.query(Worksheet).filter(Worksheet.id == worksheet_id).first()
    if not row:
        raise HTTPException(404, "Worksheet not found")

    return {
        "id": row.id,
        "techno_id": row.techno_id,
        "filename": row.filename,
        "stored_path": row.stored_path,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.get("/{worksheet_id}/download")
def download_worksheet(worksheet_id: int, db: Session = Depends(get_db)):
    row = db.query(Worksheet).filter(Worksheet.id == worksheet_id).first()
    if not row:
        raise HTTPException(404, "Worksheet not found")

    path = Path(row.stored_path)
    if not path.exists():
        raise HTTPException(404, "File missing on disk")

    return FileResponse(
        path=str(path),
        filename=row.filename,
        media_type=row.mime_type or "application/octet-stream",
    )
