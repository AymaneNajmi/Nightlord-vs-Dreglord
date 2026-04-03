from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.template_doc import TemplateDoc
from app.services.docx_headings import extract_headings

router = APIRouter(prefix="/api/docs", tags=["docs"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/{doc_id}/headings")
def get_doc_headings(doc_id: int, db: Session = Depends(get_db)):
    doc = db.query(TemplateDoc).filter(TemplateDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc not found")

    path = Path(doc.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    if not path.name.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Headings extraction supports .docx only")

    headings = extract_headings(str(path))
    return {"doc_id": doc_id, "headings": headings}

# backend/app/api_docs.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.models import TemplateDoc  # adapte l'import à ton projet

router = APIRouter(prefix="/api", tags=["docs"])

@router.get("/docs/by-techno/{techno_id}")
def docs_by_techno(techno_id: int, db: Session = Depends(get_db)):
    docs = db.query(TemplateDoc).filter(TemplateDoc.techno_id == techno_id).all()
    return [{"id": d.id, "filename": d.filename, "techno_id": d.techno_id} for d in docs]
