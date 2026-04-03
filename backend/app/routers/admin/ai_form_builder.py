from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth import require_admin
from app.core.db import SessionLocal
from app.models.ai_template_job import AITemplateJob
from app.models.forms import FormSection
from app.services.ai_form_builder_rich import run_generate_rich_job

router = APIRouter(
    prefix="/api/admin/ai-form-builder",
    tags=["admin-ai-form-builder"],
    dependencies=[Depends(require_admin)],
)

logger = logging.getLogger(__name__)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/jobs/{job_id}/generate-rich")
def generate_rich(job_id: int, db: Session = Depends(get_db)):
    job = db.query(AITemplateJob).filter(AITemplateJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        return run_generate_rich_job(db, job)
    except Exception as exc:  # noqa: BLE001
        # UX: do not return 400 for generation-quality failures.
        # The job is already marked FAILED by the service with error details.
        db.refresh(job)
        logger.exception("ai_form_builder_rich generation failed for job_id=%s", job_id)
        return {
            "status": "FAILED",
            "job_id": job.id,
            "form_template_id": job.form_template_id,
            "error_message": job.error_message or str(exc),
        }


@router.get("/jobs/{job_id}")
def get_job_rich(job_id: int, db: Session = Depends(get_db)):
    job = db.query(AITemplateJob).filter(AITemplateJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    sections_payload = []
    if job.form_template_id:
        rows = (
            db.query(FormSection)
            .filter(FormSection.form_id == job.form_template_id)
            .order_by(FormSection.order_index.asc())
            .all()
        )
        for sec in rows:
            sections_payload.append(
                {
                    "id": sec.id,
                    "section_key": sec.sec_key,
                    "title": sec.heading_title,
                    "level": "H2" if sec.heading_level == 2 else "H3",
                    "intent": sec.section_intent,
                    "example": sec.section_example,
                    "status": sec.status,
                    "error_message": sec.error_message,
                    "questions": [
                        {
                            "id": q.id,
                            "order": q.order_index,
                            "label": q.label,
                            "qtype": q.qtype,
                            "is_required": q.is_required,
                            "options": [
                                {"id": o.id, "order": o.order_index, "value": o.value or o.label}
                                for o in sorted(q.options, key=lambda item: item.order_index)
                            ],
                        }
                        for q in sorted(sec.questions, key=lambda item: item.order_index)
                    ],
                }
            )

    return {
        "job_id": job.id,
        "status": job.status,
        "error_message": job.error_message,
        "form_template_id": job.form_template_id,
        "sections": sections_payload,
    }
