from __future__ import annotations
from pathlib import Path
import uuid

WORKSHEETS_DIR = Path("storage/worksheets")
WORKSHEETS_DIR.mkdir(parents=True, exist_ok=True)


def save_worksheet_bytes(content: bytes, original_name: str) -> str:
    worksheet_id = str(uuid.uuid4())
    ext = Path(original_name).suffix.lower() or ".xlsx"
    out = WORKSHEETS_DIR / f"{worksheet_id}{ext}"
    out.write_bytes(content)
    return worksheet_id


def get_worksheet_path(worksheet_id: str) -> Path:
    # try xlsx then xlsm
    for ext in (".xlsx", ".xlsm", ".xls"):
        p = WORKSHEETS_DIR / f"{worksheet_id}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"Worksheet not found for id={worksheet_id}")


from pathlib import Path
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.worksheets import Worksheet


def get_worksheet_path(worksheet_id: int) -> Path:
    db: Session = SessionLocal()
    try:
        row = db.query(Worksheet).filter(Worksheet.id == worksheet_id).first()
        if not row:
            raise ValueError("Worksheet not found")
        p = Path(row.stored_path)
        if not p.exists():
            raise ValueError(f"Worksheet file missing on disk: {p}")
        return p
    finally:
        db.close()
