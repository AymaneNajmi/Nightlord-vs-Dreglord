from pathlib import Path
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.auth import require_admin, require_authenticated
from app.models.techno import Techno, DocType
from app.models.template_doc import TemplateDoc
from app.models.user import User
from app.services.access_control import user_can_access_techno, visible_technos_query

router = APIRouter(prefix="/api/technos", tags=["technos"])

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"     # backend/app/uploads
UPLOAD_DIR.mkdir(exist_ok=True)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("")
def list_technos(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated),
):
    technos = visible_technos_query(db, current_user).order_by(Techno.id.desc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "doc_type": t.doc_type,
            "created_by": t.created_by,
            "template_doc_id": t.template_doc_id,
            "form_template_id": t.form_template_id,
            "cover_template_id": t.cover_template_id,
            "documents": [
                {"id": d.id, "filename": d.filename, "created_at": d.created_at.isoformat()}
                for d in t.documents
            ],
        }
        for t in technos
    ]


@router.get("/{techno_id}")
def get_techno(
    techno_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated),
):
    if not user_can_access_techno(db, current_user, techno_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    techno = db.query(Techno).filter(Techno.id == techno_id).first()
    if not techno:
        raise HTTPException(status_code=404, detail="Techno not found")
    return {
        "id": techno.id,
        "name": techno.name,
        "description": techno.description,
        "doc_type": techno.doc_type,
        "created_by": techno.created_by,
        "template_doc_id": techno.template_doc_id,
        "form_template_id": techno.form_template_id,
        "cover_template_id": techno.cover_template_id,
        "template_doc_filename": techno.template_doc.filename if techno.template_doc else None,
        "form_template_name": techno.form_template.name if techno.form_template else None,
        "cover_template_filename": techno.cover_template.filename if techno.cover_template else None,
        "documents": [
            {"id": d.id, "filename": d.filename, "created_at": d.created_at.isoformat()}
            for d in techno.documents
        ],
    }


@router.post("")
def create_techno(
    name: str = Form(...),
    description: str | None = Form(None),
    doc_type: DocType = Form(DocType.INGENIERIE),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    # unique check
    exists = db.query(Techno).filter(Techno.name == name).first()
    if exists:
        raise HTTPException(status_code=409, detail="Techno already exists")

    techno = Techno(
        name=name,
        description=description,
        doc_type=doc_type,
        created_by=current_user.id,
    )
    db.add(techno)
    db.commit()
    db.refresh(techno)

    # optional upload
    if file:
        if not (file.filename.lower().endswith(".docx") or file.filename.lower().endswith(".doc")):
            raise HTTPException(status_code=400, detail="Only .doc/.docx allowed")

        techno_dir = UPLOAD_DIR / str(techno.id)
        techno_dir.mkdir(exist_ok=True)

        safe_name = file.filename.replace("/", "_").replace("\\", "_")
        stored_path = techno_dir / safe_name

        with stored_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        doc = TemplateDoc(
            techno_id=techno.id,
            filename=safe_name,
            stored_path=str(stored_path),
            mime_type=file.content_type or "application/octet-stream",
        )
        db.add(doc)
        db.commit()

    return {"ok": True, "id": techno.id}


@router.post("/{techno_id}/upload")
def upload_doc(
    techno_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    techno = db.query(Techno).filter(Techno.id == techno_id).first()
    if not techno:
        raise HTTPException(status_code=404, detail="Techno not found")
    if not user_can_access_techno(db, current_user, techno_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not (file.filename.lower().endswith(".docx") or file.filename.lower().endswith(".doc")):
        raise HTTPException(status_code=400, detail="Only .doc/.docx allowed")

    techno_dir = UPLOAD_DIR / str(techno.id)
    techno_dir.mkdir(exist_ok=True)

    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    stored_path = techno_dir / safe_name

    with stored_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    doc = TemplateDoc(
        techno_id=techno.id,
        filename=safe_name,
        stored_path=str(stored_path),
        mime_type=file.content_type or "application/octet-stream",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    return {"ok": True, "doc_id": doc.id}


@router.get("/docs/{doc_id}/download")
def download_doc(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated),
):
    doc = db.query(TemplateDoc).filter(TemplateDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Doc not found")
    if not user_can_access_techno(db, current_user, doc.techno_id):
        raise HTTPException(status_code=403, detail="Forbidden")

    path = Path(doc.stored_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing on disk")

    return FileResponse(
        path=str(path),
        filename=doc.filename,
        media_type=doc.mime_type,
    )


@router.patch("/{techno_id}")
def update_techno(
    techno_id: int,
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if not user_can_access_techno(db, current_user, techno_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    techno = db.query(Techno).filter(Techno.id == techno_id).first()
    if not techno:
        raise HTTPException(status_code=404, detail="Techno not found")

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Techno name required")
        exists = (
            db.query(Techno)
            .filter(Techno.name == name, Techno.id != techno_id)
            .first()
        )
        if exists:
            raise HTTPException(status_code=409, detail="Techno already exists")
        techno.name = name

    if "doc_type" in payload and payload.get("doc_type") is not None:
        try:
            techno.doc_type = DocType(payload.get("doc_type"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid doc_type") from exc

    db.commit()
    db.refresh(techno)
    return {"ok": True, "id": techno.id, "name": techno.name, "doc_type": techno.doc_type}


@router.delete("/{techno_id}")
def delete_techno(
    techno_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if not user_can_access_techno(db, current_user, techno_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    techno = db.query(Techno).filter(Techno.id == techno_id).first()
    if not techno:
        raise HTTPException(status_code=404, detail="Techno not found")

    techno_dir = UPLOAD_DIR / str(techno.id)
    if techno_dir.exists():
        shutil.rmtree(techno_dir, ignore_errors=True)

    db.delete(techno)
    db.commit()
    return {"ok": True, "id": techno_id}
