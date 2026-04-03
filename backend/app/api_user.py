import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.techno import Techno
from app.models.template_doc import TemplateDoc
from app.models.forms import FormTemplate

from app.services.worksheet_store import save_worksheet, get_worksheet_path
from app.services.excel_docx_injector import inject_excel_tables
from app.services.docx_section_filter import remove_sections_by_titles

router = APIRouter(prefix="/api/user", tags=["user"])

OUT_DIR = Path("uploads/generated")
OUT_DIR.mkdir(parents=True, exist_ok=True)


class GeneratePayload(BaseModel):
    techno_id: int
    doc_id: int
    form_id: int
    worksheet_id: Optional[str] = None

    removed_titles: List[str] = []
    answers: Dict[str, Any] = {}  # future: used by docx_render/openai


@router.get("/technos")
def list_technos(db: Session = Depends(get_db)):
    technos = db.query(Techno).order_by(Techno.id.desc()).all()
    return [{"id": t.id, "name": t.name, "doc_type": getattr(t, "doc_type", None)} for t in technos]


@router.get("/docs/by-techno/{techno_id}")
def docs_by_techno(techno_id: int, db: Session = Depends(get_db)):
    # adapt if your relation differs
    docs = db.query(TemplateDoc).filter(TemplateDoc.techno_id == techno_id).order_by(TemplateDoc.id.desc()).all()
    return [
        {"id": d.id, "filename": getattr(d, "filename", f"doc-{d.id}.docx")}
        for d in docs
    ]


@router.get("/forms/by-techno/{techno_id}")
def forms_by_techno(techno_id: int, db: Session = Depends(get_db)):
    forms = (
        db.query(FormTemplate)
        .filter(FormTemplate.techno_id == techno_id)
        .order_by(FormTemplate.name.asc(), FormTemplate.version.desc())
        .all()
    )
    return [
        {
            "id": f.id,
            "name": f.name,
            "version": f.version,
            "is_active": f.is_active,
            "doc_id": f.doc_id,
        }
        for f in forms
    ]


# backend/app/api_user.py
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter(prefix="/api/user", tags=["user"])

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "static" / "uploads" / "worksheets"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {".xlsx", ".xlsm", ".xltx", ".xltm"}

# backend/app/api_user.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
from uuid import uuid4

router = APIRouter(prefix="/api/user", tags=["user"])

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

@router.post("/worksheet/upload")
async def upload_worksheet(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".xltx", ".xltm")):
        raise HTTPException(status_code=400, detail="Fichier Excel invalide.")

    ws_id = uuid4().hex
    target = UPLOAD_DIR / f"{ws_id}_{file.filename}"

    content = await file.read()
    target.write_bytes(content)

    return {"worksheet_id": ws_id, "filename": file.filename}



def _resolve_docx_path(doc: TemplateDoc) -> str:
    """
    ✅ ADAPTE ICI selon ton modèle TemplateDoc:
    - soit doc.path
    - soit doc.file_path
    - soit doc.doc_path
    """
    for attr in ["path", "file_path", "doc_path"]:
        p = getattr(doc, attr, None)
        if p:
            return p
    raise HTTPException(status_code=500, detail="TemplateDoc path non trouvé (path/file_path/doc_path).")


@router.post("/generate")
def generate(payload: GeneratePayload, db: Session = Depends(get_db)):
    # 1) get template doc
    doc = db.query(TemplateDoc).filter(TemplateDoc.id == payload.doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc introuvable")

    template_path = _resolve_docx_path(doc)
    if not os.path.exists(template_path):
        raise HTTPException(status_code=404, detail=f"Fichier DOCX introuvable: {template_path}")

    # 2) copy to temp working file
    job_id = str(uuid.uuid4())
    tmp1 = OUT_DIR / f"{job_id}_step1.docx"
    tmp2 = OUT_DIR / f"{job_id}_step2.docx"
    tmp3 = OUT_DIR / f"{job_id}_final.docx"

    shutil.copyfile(template_path, tmp1)

    # 3) remove sections
    remove_sections_by_titles(str(tmp1), str(tmp2), payload.removed_titles)

    # 4) inject excel tables if worksheet uploaded
    if payload.worksheet_id:
        excel_path = get_worksheet_path(payload.worksheet_id)
        inject_excel_tables(str(tmp2), str(tmp3), excel_path)
        final_path = tmp3
    else:
        final_path = tmp2

    # 5) (future) render answers using your docx_render/openai_writer
    # TODO: plug here when ready

    return FileResponse(
        path=str(final_path),
        filename=f"generated_{job_id}.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )




