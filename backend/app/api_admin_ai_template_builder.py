from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import SessionLocal
from app.models.ai_template_job import AITemplateJob, AITemplateJobStatus
from app.models.techno import DocType
from app.models.template_doc import TemplateDoc
from app.models.user import User
from app.services.ai_template_builder import MAX_FILE_SIZE, store_uploads, run_ai_template_job
from app.services.llm_provider import get_provider

router = APIRouter(
    prefix="/api/admin/ai-template-builder",
    tags=["admin-ai-template-builder"],
    dependencies=[Depends(require_admin)],
)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _read_upload(file: UploadFile) -> bytes:
    data = file.file.read()
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"Fichier trop volumineux (> {MAX_FILE_SIZE} bytes)")
    return data


@router.post("/jobs")
def create_job(
    techno_name: str = Form(...),
    template_type: Optional[str] = Form(None),
    doc_type: DocType = Form(DocType.INGENIERIE),
    cover_template_id: Optional[int] = Form(None),
    client_names_to_remove: Optional[str] = Form(None),
    llm_provider: str = Form("openai"),
    docs: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
):
    if not docs:
        raise HTTPException(status_code=400, detail="Documents requis")
    clean_name = (techno_name or "").strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Nom techno requis")
    if cover_template_id:
        cover_exists = db.query(TemplateDoc).filter(TemplateDoc.id == cover_template_id).first()
        if not cover_exists:
            raise HTTPException(status_code=404, detail="Page de garde introuvable")

    provider = get_provider(llm_provider)

    job = AITemplateJob(
        techno_name=clean_name,
        template_type=(template_type or "").strip() or None,
        doc_type=doc_type,
        cover_template_id=cover_template_id,
        llm_provider=provider.value,
        status=AITemplateJobStatus.PENDING,
        progress=0,
        created_by=current_admin.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    uploads: List[tuple[str, bytes]] = []
    for f in docs:
        if not (f.filename.lower().endswith(".docx") or f.filename.lower().endswith(".pdf")):
            raise HTTPException(status_code=400, detail="Formats acceptés: .docx, .pdf")
        uploads.append((f.filename, _read_upload(f)))

    source_files = store_uploads(job.id, uploads)
    job.source_files = source_files
    if client_names_to_remove:
        job.logs = "Noms à expurger reçus."
        job.redaction_report = {"names": [n for n in client_names_to_remove.splitlines() if n.strip()]}
    db.commit()

    return {"ok": True, "job_id": job.id}


@router.post("/jobs/{job_id}/run")
def run_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    job = db.query(AITemplateJob).filter(AITemplateJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == AITemplateJobStatus.RUNNING:
        return {"ok": True, "status": job.status}
    names = []
    if job.redaction_report and isinstance(job.redaction_report, dict):
        names = job.redaction_report.get("names") or []
    background_tasks.add_task(_run_job_task, job_id, names)
    return {"ok": True, "status": "RUNNING"}


def _run_job_task(job_id: int, names: List[str]) -> None:
    db = SessionLocal()
    try:
        run_ai_template_job(db, job_id=job_id, client_names=names)
    finally:
        db.close()


@router.get("/jobs/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(AITemplateJob).filter(AITemplateJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "techno_name": job.techno_name,
        "template_type": job.template_type,
        "doc_type": job.doc_type,
        "cover_template_id": job.cover_template_id,
        "llm_provider": job.llm_provider,
        "status": job.status,
        "progress": job.progress,
        "logs": job.logs,
        "error_message": job.error_message,
        "redaction_report": job.redaction_report,
        "source_files": job.source_files,
        "output_payload": job.output_payload,
        "template_doc_id": job.template_doc_id,
        "form_template_id": job.form_template_id,
        "techno_id": job.techno_id,
        "created_by": job.created_by,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db)):
    jobs = db.query(AITemplateJob).order_by(AITemplateJob.id.desc()).all()
    return [
        {
            "id": job.id,
            "techno_name": job.techno_name,
            "template_type": job.template_type,
            "doc_type": job.doc_type,
            "status": job.status,
            "llm_provider": job.llm_provider,
            "progress": job.progress,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "template_doc_id": job.template_doc_id,
            "form_template_id": job.form_template_id,
            "techno_id": job.techno_id,
        }
        for job in jobs
    ]


@router.get("/cover-templates")
def list_cover_templates(db: Session = Depends(get_db)):
    docs = (
        db.query(TemplateDoc)
        .filter(TemplateDoc.filename.ilike("%.docx"))
        .order_by(TemplateDoc.id.desc())
        .all()
    )
    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "techno_id": doc.techno_id,
        }
        for doc in docs
    ]
