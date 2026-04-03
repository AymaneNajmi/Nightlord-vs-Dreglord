import os
import uuid
from dataclasses import dataclass
from pathlib import Path

UPLOAD_DIR = Path("uploads/worksheets")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class StoredWorksheet:
    worksheet_id: str
    filename: str
    path: str


def save_worksheet(file_bytes: bytes, original_name: str) -> StoredWorksheet:
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        raise ValueError("Format Excel non supporté. Utilise .xlsx")

    worksheet_id = str(uuid.uuid4())
    safe_name = f"{worksheet_id}{ext}"
    path = UPLOAD_DIR / safe_name
    path.write_bytes(file_bytes)

    return StoredWorksheet(
        worksheet_id=worksheet_id,
        filename=original_name,
        path=str(path),
    )


def get_worksheet_path(worksheet_id: str) -> str:
    # accept any supported ext
    for ext in [".xlsx", ".xlsm", ".xltx", ".xltm"]:
        p = UPLOAD_DIR / f"{worksheet_id}{ext}"
        if p.exists():
            return str(p)
    raise FileNotFoundError("Worksheet introuvable")
