from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import re
import uuid
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.techno import Techno
from app.models.template_doc import TemplateDoc
from app.models.forms import FormTemplate, FormSection, FormQuestion, FormOption
from app.models.form_module_answer import FormModuleAnswer
from app.models.submissions import FormSubmission, SubmissionAnswer
from app.models.submission_section_text import SubmissionSectionText
from app.schemas.forms import FormSubmitPayload
from app.services.hardware_generator import generate_hardware_content, hardware_to_docx_bytes

from app.services.docx_headings import extract_sections_from_docx, extract_headings
from app.services.payload_builder import build_generation_payload
from app.services.openai_writer import generate_sections_json
from app.services.llm_provider import get_provider

from app.services.docx_render import render_docx_from_sections
from app.services.docx_pipeline import apply_doc_pipeline
from app.services.worksheets import get_worksheet_path

from app.services.docx_ops import (
    docx_has_inserer,
    docx_inserer_heading_titles,
    docx_inserer_placeholders,
    docx_content_blocks,
    docx_general_placeholders,
)
from app.core.auth import require_admin, require_authenticated
from app.models.user import User
from app.services.access_control import is_admin, user_can_access_techno


router = APIRouter(prefix="/api/forms", tags=["forms"])

OTHER_OPTION_LABELS = {"autres", "other"}
ALLOWED_QTYPES = {"text", "single_choice", "multi_choice", "module_hardware_cisco"}
MODULE_HARDWARE_CISCO_QTYPE = "module_hardware_cisco"


def _is_other_option_label(value: str) -> bool:
    return str(value or "").strip().lower() in OTHER_OPTION_LABELS

# folder for generated docs (final)
GENERATED_DIR = Path(__file__).resolve().parent / "generated_docs"
GENERATED_DIR.mkdir(exist_ok=True)

# folder for previews
PREVIEW_DIR = Path("storage/previews")
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

MODULE_OUTPUT_DIR = Path("storage/module_outputs")
MODULE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

GENERAL_ASSETS_DIR = Path("storage/general_assets")
GENERAL_ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _validate_question_type(raw_qtype: str | None) -> str:
    qtype = (raw_qtype or "single_choice").strip().lower()
    if qtype not in ALLOWED_QTYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported qtype: {qtype}")
    return qtype


def _validate_hardware_reference(hardware_reference: str) -> str:
    value = (hardware_reference or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="hardware_reference requis")
    if len(value) > 120:
        raise HTTPException(status_code=400, detail="hardware_reference trop long")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value):
        raise HTTPException(status_code=400, detail="hardware_reference invalide")
    return value


def _get_module_hardware_question(db: Session, form_id: int, question_id: int) -> FormQuestion:
    q = (
        db.query(FormQuestion)
        .join(FormSection, FormSection.id == FormQuestion.section_id)
        .filter(
            FormQuestion.id == question_id,
            FormSection.form_id == form_id,
            FormQuestion.qtype == MODULE_HARDWARE_CISCO_QTYPE,
        )
        .first()
    )
    if not q:
        raise HTTPException(status_code=404, detail="Module question not found")
    return q


def _resolve_logo_asset_path(logo_upload_id: Optional[str]) -> Optional[str]:
    if not logo_upload_id:
        return None
    for p in GENERAL_ASSETS_DIR.glob(f"logo_{logo_upload_id}.*"):
        if p.exists():
            return str(p)
    return None




def _module_sections_text(db: Session, form_id: int) -> Dict[str, str]:
    rows = (
        db.query(FormSection.sec_key, FormQuestion.label, FormModuleAnswer.output_summary_text)
        .join(FormQuestion, FormQuestion.section_id == FormSection.id)
        .join(
            FormModuleAnswer,
            (FormModuleAnswer.form_id == FormSection.form_id)
            & (FormModuleAnswer.question_id == FormQuestion.id),
        )
        .filter(
            FormSection.form_id == form_id,
            FormQuestion.qtype == MODULE_HARDWARE_CISCO_QTYPE,
            FormModuleAnswer.output_summary_text.isnot(None),
        )
        .all()
    )

    by_section: Dict[str, list[str]] = {}
    for sec_key, label, output_summary_text in rows:
        if not sec_key:
            continue
        block_title = str(label or "Hardware Cisco").strip() or "Hardware Cisco"
        body = str(output_summary_text or "").strip()
        if not body:
            continue
        chunk = f"{block_title}\n{body}".strip()
        by_section.setdefault(sec_key, []).append(chunk)

    return {k: "\n\n".join(v).strip() for k, v in by_section.items() if v}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# =========================================================
# ✅ LIST FORMS BY TECHNO (Admin list)
# =========================================================
@router.get("/by-techno/{techno_id}")
def list_forms_by_techno(
    techno_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_authenticated),
):
    if not user_can_access_techno(db, current_user, techno_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    forms = (
        db.query(FormTemplate)
        .filter(FormTemplate.techno_id == techno_id)
        .order_by(FormTemplate.name.asc(), FormTemplate.version.desc())
        .all()
    )
    if not is_admin(current_user):
        forms = [form for form in forms if form.is_active]

    return [
        {
            "id": f.id,
            "name": f.name,
            "version": f.version,
            "is_active": f.is_active,
            "doc_id": f.doc_id,
            "doc_filename": f.doc.filename if getattr(f, "doc", None) else None,
            "created_by": f.created_by,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "parent_id": f.parent_id,
        }
        for f in forms
    ]


# =========================================================
# ✅ CREATE FORM (versioned)
# =========================================================
@router.post("/", summary="Create a form from a template doc (versioned)")
def create_form(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    techno_id = payload.get("techno_id")
    doc_id = payload.get("doc_id")
    name = (payload.get("name") or "Formulaire").strip()

    if not techno_id or not doc_id:
        raise HTTPException(400, detail="techno_id and doc_id required")

    techno = db.query(Techno).filter(Techno.id == techno_id).first()
    if not techno:
        raise HTTPException(404, detail="Techno not found")

    doc = (
        db.query(TemplateDoc)
        .filter(TemplateDoc.id == doc_id, TemplateDoc.techno_id == techno_id)
        .first()
    )
    if not doc:
        raise HTTPException(404, detail="Doc not found for this techno")

    # if a form with same name exists -> auto new version by cloning
    last = (
        db.query(FormTemplate)
        .filter(FormTemplate.techno_id == techno_id, FormTemplate.name == name)
        .order_by(FormTemplate.version.desc())
        .first()
    )

    if last:
        next_version = last.version + 1
        db.query(FormTemplate).filter(
            FormTemplate.techno_id == techno_id, FormTemplate.name == name
        ).update({FormTemplate.is_active: False})

        form = FormTemplate(
            techno_id=techno_id,
            doc_id=doc_id,
            name=name,
            version=next_version,
            is_active=True,
            parent_id=last.parent_id or last.id,
            created_by=str(current_user.id),
        )
        db.add(form)
        db.commit()
        db.refresh(form)

        _clone_form_content(db, src_form_id=last.id, dst_form_id=form.id)
        db.commit()
        return {"ok": True, "form_id": form.id, "sections_created": "cloned", "version": form.version}

    # else create V1
    form = FormTemplate(
        techno_id=techno_id,
        doc_id=doc_id,
        name=name,
        version=1,
        is_active=True,
        created_by=str(current_user.id),
    )
    db.add(form)
    db.commit()
    db.refresh(form)

    form.parent_id = form.id
    db.commit()

    # extract sections from docx
    if not doc.stored_path or not Path(doc.stored_path).exists():
        raise HTTPException(400, detail=f"Template file not found: {doc.stored_path}")

    sections = extract_sections_from_docx(doc.stored_path)
    if not sections:
        return {
            "ok": True,
            "form_id": form.id,
            "sections_created": 0,
            "warning": "No sections found (check Heading styles + [[SEC_x]] tags)",
            "version": form.version,
        }

    for s in sections:
        db.add(
            FormSection(
                form_id=form.id,
                sec_key=s["sec_key"],
                heading_level=s["level"],
                heading_title=s["title"],
                order_index=s["order_index"],
            )
        )
    db.commit()

    return {"ok": True, "form_id": form.id, "sections_created": len(sections), "version": form.version}


def _clone_form_content(db: Session, src_form_id: int, dst_form_id: int):
    src_sections = (
        db.query(FormSection)
        .filter(FormSection.form_id == src_form_id)
        .order_by(FormSection.order_index.asc())
        .all()
    )

    for s in src_sections:
        ns = FormSection(
            form_id=dst_form_id,
            sec_key=s.sec_key,
            heading_level=s.heading_level,
            heading_title=s.heading_title,
            order_index=s.order_index,
            section_intent=getattr(s, "section_intent", None),
            section_example=getattr(s, "section_example", None),
        )
        db.add(ns)
        db.flush()

        qs = (
            db.query(FormQuestion)
            .filter(FormQuestion.section_id == s.id)
            .order_by(FormQuestion.order_index.asc())
            .all()
        )

        for q in qs:
            nq = FormQuestion(
                section_id=ns.id,
                label=q.label,
                qtype=q.qtype,
                is_required=q.is_required,
                help_text=q.help_text,
                order_index=q.order_index,
            )
            db.add(nq)
            db.flush()

            opts = (
                db.query(FormOption)
                .filter(FormOption.question_id == q.id)
                .order_by(FormOption.order_index.asc())
                .all()
            )

            for o in opts:
                db.add(
                    FormOption(
                        question_id=nq.id,
                        label=o.label,
                        value=o.value,
                        order_index=o.order_index,
                    )
                )


# =========================================================
# ✅ CLONE FORM -> NEW VERSION
# =========================================================
@router.post("/{form_id}/clone")
def clone_form(
    form_id: int,
    payload: dict = Body(default={}),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    src = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not src:
        raise HTTPException(404, detail="Form not found")

    last = (
        db.query(FormTemplate)
        .filter(FormTemplate.techno_id == src.techno_id, FormTemplate.name == src.name)
        .order_by(FormTemplate.version.desc())
        .first()
    )
    next_version = (last.version + 1) if last else 1

    db.query(FormTemplate).filter(
        FormTemplate.techno_id == src.techno_id, FormTemplate.name == src.name
    ).update({FormTemplate.is_active: False})

    new_form = FormTemplate(
        techno_id=src.techno_id,
        doc_id=src.doc_id,
        name=src.name,
        version=next_version,
        is_active=True,
        parent_id=src.parent_id or src.id,
        created_by=str(current_user.id),
    )
    db.add(new_form)
    db.commit()
    db.refresh(new_form)

    _clone_form_content(db, src_form_id=src.id, dst_form_id=new_form.id)
    db.commit()

    return {"ok": True, "new_form_id": new_form.id, "version": new_form.version}


# =========================================================
# ✅ DELETE FORM (Admin only)
# =========================================================
@router.delete("/{form_id}", dependencies=[Depends(require_admin)])
def delete_form(form_id: int, db: Session = Depends(get_db)):
    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(404, detail="Form not found")
    if form.is_active:
        raise HTTPException(status_code=409, detail="Active form cannot be deleted")

    submission_ids = [
        row[0]
        for row in db.query(FormSubmission.id).filter(FormSubmission.form_id == form_id).all()
    ]
    if submission_ids:
        db.query(SubmissionSectionText).filter(
            SubmissionSectionText.form_id == form_id
        ).delete(synchronize_session=False)

        submissions = (
            db.query(FormSubmission)
            .filter(FormSubmission.id.in_(submission_ids))
            .all()
        )
        for submission in submissions:
            db.delete(submission)

    db.delete(form)
    db.commit()
    return {"ok": True, "form_id": form_id}


# =========================================================
# GET FORM BASIC
# =========================================================
@router.get("/{form_id}")
def get_form(form_id: int, db: Session = Depends(get_db)):
    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(404, detail="Form not found")

    sections = (
        db.query(FormSection)
        .filter(FormSection.form_id == form_id)
        .order_by(FormSection.order_index.asc())
        .all()
    )

    out_sections = []
    for s in sections:
        qs = (
            db.query(FormQuestion)
            .filter(FormQuestion.section_id == s.id)
            .order_by(FormQuestion.order_index.asc())
            .all()
        )

        out_qs = []
        for q in qs:
            opts = (
                db.query(FormOption)
                .filter(FormOption.question_id == q.id)
                .order_by(FormOption.order_index.asc())
                .all()
            )
            out_qs.append(
                {
                    "id": q.id,
                    "label": q.label,
                    "qtype": q.qtype,
                    "is_required": q.is_required,
                    "help_text": q.help_text,
                    "question_key": getattr(q, "question_key", None),
                    "show_if": getattr(q, "show_if_json", None),
                    "order_index": q.order_index,
                    "options": [{"id": o.id, "label": o.label, "value": o.value} for o in opts],
                }
            )

        out_sections.append(
            {
                "id": s.id,
                "sec_key": s.sec_key,
                "heading_level": s.heading_level,
                "heading_title": s.heading_title,
                "section_intent": getattr(s, "section_intent", None),
                "section_example": getattr(s, "section_example", None),
                "purpose_text": getattr(s, "purpose_text", None),
                "status": getattr(s, "status", "OK"),
                "error_message": getattr(s, "error_message", None),
                "questions": out_qs,
            }
        )

    return {
        "id": form.id,
        "techno_id": form.techno_id,
        "doc_id": form.doc_id,
        "name": form.name,
        "version": form.version,
        "is_active": form.is_active,
        "created_by": form.created_by,
        "created_at": form.created_at.isoformat() if form.created_at else None,
        "sections": out_sections,
    }


# =========================================================
# ✅ LIST SECTIONS (Admin Builder)  (fix 404)
# =========================================================
@router.get("/{form_id}/sections")
def list_sections(form_id: int, include_headings: bool = False, db: Session = Depends(get_db)):
    sections = (
        db.query(FormSection)
        .filter(FormSection.form_id == form_id)
        .order_by(FormSection.order_index.asc())
        .all()
    )

    heading_items = []
    heading_order = {}
    if include_headings:
        form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
        if form:
            tdoc = db.query(TemplateDoc).filter(TemplateDoc.id == form.doc_id).first()
            if tdoc and tdoc.stored_path and Path(tdoc.stored_path).exists():
                heading_items = extract_headings(str(tdoc.stored_path))
                heading_order = {(item.text, item.level): idx for idx, item in enumerate(heading_items)}

    seen = set()
    out = []
    for s in sections:
        out.append(
            {
                "id": s.id,
                "sec_key": s.sec_key,
                "level": s.heading_level,
                "title": s.heading_title,
                "order_index": heading_order.get((s.heading_title, s.heading_level), s.order_index),
                "section_intent": getattr(s, "section_intent", None),
                "section_example": getattr(s, "section_example", None),
                "asterisk_only": False,
                "status": getattr(s, "status", "OK"),
                "error_message": getattr(s, "error_message", None),
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
                    for q in sorted(s.questions, key=lambda item: item.order_index)
                ],
            }
        )
    for item in out:
        seen.add((item.get("title"), item.get("level")))

    if include_headings:
        for idx, item in enumerate(heading_items):
            key = (item.text, item.level)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "id": None,
                    "sec_key": None,
                    "level": item.level,
                    "title": item.text,
                    "order_index": idx,
                    "section_intent": None,
                    "section_example": None,
                    "asterisk_only": False,
                    "status": None,
                    "error_message": None,
                    "questions": [],
                }
            )

    out.sort(key=lambda row: (row.get("order_index", 0), row.get("level", 0), row.get("title") or ""))
    return out


# =========================================================
# ✅ FULL FORM FOR USER UI
# =========================================================
@router.get("/{form_id}/full")
def get_form_full(form_id: int, db: Session = Depends(get_db)):
    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    sections = (
        db.query(FormSection)
        .filter(FormSection.form_id == form_id)
        .order_by(FormSection.order_index.asc())
        .all()
    )

    out_sections = []
    for s in sections:
        questions = (
            db.query(FormQuestion)
            .filter(FormQuestion.section_id == s.id)
            .order_by(FormQuestion.order_index.asc())
            .all()
        )

        out_q = []
        for q in questions:
            out_q.append(
                {
                    "id": q.id,
                    "label": q.label,
                    "qtype": q.qtype,
                    "is_required": q.is_required,
                    "help_text": q.help_text,
                    "question_key": getattr(q, "question_key", None),
                    "show_if": getattr(q, "show_if_json", None),
                    "order_index": q.order_index,
                    "options": [{"id": o.id, "label": o.label} for o in (q.options or [])],
                }
            )

        out_sections.append(
            {
                "id": s.id,
                "title": s.heading_title,
                "sec_key": s.sec_key,
                "level": s.heading_level,
                "section_intent": getattr(s, "section_intent", None),
                "section_example": getattr(s, "section_example", None),
                "purpose_text": getattr(s, "purpose_text", None),
                "questions": out_q,
            }
        )

    # ✅ detection [[INSERER]] dans le doc template
    has_rich_insert = False
    insert_heading_titles: set[str] = set()
    insert_heading_labels: dict[str, str] = {}
    insert_orphan_labels: list[str] = []
    content_blocks: list[dict[str, str | int | None]] = []
    general_placeholders: dict[str, object] = {"text_placeholders": [], "has_logo": False}
    tdoc = db.query(TemplateDoc).filter(TemplateDoc.id == form.doc_id).first()
    if tdoc and tdoc.stored_path and Path(tdoc.stored_path).exists():
        has_rich_insert = docx_has_inserer(tdoc.stored_path)
        if has_rich_insert:
            insert_heading_labels, insert_orphan_labels = docx_inserer_placeholders(tdoc.stored_path)
            insert_heading_titles = set(insert_heading_labels.keys())
        content_blocks = docx_content_blocks(tdoc.stored_path)
        general_placeholders = docx_general_placeholders(tdoc.stored_path)

    def _normalize_title(s: str) -> str:
        return re.sub(r"\s+", " ", (s or "").strip()).lower()

    for s in out_sections:
        insert_key = _normalize_title(s.get("title") or "")
        s["has_insert_placeholder"] = insert_key in insert_heading_titles
        s["insert_key"] = insert_key
        s["insert_label"] = insert_heading_labels.get(insert_key)

    return {
        "id": form.id,
        "name": f"{form.name} - V{form.version}",
        "techno_name": (form.techno.name if getattr(form, "techno", None) else None),
        "doc_filename": (form.doc.filename if getattr(form, "doc", None) else None),
        "sections": out_sections,
        "has_rich_insert": has_rich_insert,
        "insert_orphan_labels": insert_orphan_labels,
        "content_blocks": content_blocks,
        "general_placeholders": general_placeholders,
    }


@router.post("/assets/logo/upload")
async def upload_general_logo(file: UploadFile = File(...)):
    content_type = (file.content_type or "").lower()
    if content_type not in {"image/png", "image/jpeg", "image/jpg", "image/webp"}:
        raise HTTPException(status_code=400, detail="Logo must be an image (png/jpg/webp)")

    ext = Path(file.filename or "logo").suffix.lower() or ".png"
    logo_upload_id = uuid.uuid4().hex
    out_path = GENERAL_ASSETS_DIR / f"logo_{logo_upload_id}{ext}"
    out_path.write_bytes(await file.read())
    return {"logo_upload_id": logo_upload_id, "filename": file.filename}



# =========================================================
# ✅ ADD QUESTION
# =========================================================
@router.post("/sections/{section_id}/questions", dependencies=[Depends(require_admin)])
def add_question(section_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    s = db.query(FormSection).filter(FormSection.id == section_id).first()
    if not s:
        raise HTTPException(404, detail="Section not found")

    qtype = _validate_question_type(payload.get("qtype"))
    default_label = "Hardware Cisco" if qtype == MODULE_HARDWARE_CISCO_QTYPE else ""
    label = (payload.get("label") or default_label).strip()
    is_required = bool(payload.get("is_required", False))
    help_text = payload.get("help_text")

    if not label:
        raise HTTPException(400, detail="Question label required")

    order_index = payload.get("order_index")
    if order_index is None:
        last = (
            db.query(FormQuestion)
            .filter(FormQuestion.section_id == section_id)
            .order_by(FormQuestion.order_index.desc())
            .first()
        )
        order_index = (last.order_index + 1) if last else 0
    else:
        try:
            order_index = int(order_index)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, detail="order_index must be an integer") from exc
        if order_index < 0:
            raise HTTPException(400, detail="order_index must be >= 0")

    if qtype == MODULE_HARDWARE_CISCO_QTYPE:
        help_text = None

    q = FormQuestion(
        section_id=section_id,
        label=label,
        qtype=qtype,
        is_required=is_required,
        help_text=help_text,
        order_index=order_index,
    )
    db.add(q)
    db.commit()
    db.refresh(q)

    options = payload.get("options") or []
    if qtype in ("single_choice", "multi_choice") and options:
        for i, opt in enumerate(options):
            text = (opt.get("label") or "").strip()
            if not text:
                continue
            db.add(
                FormOption(
                    question_id=q.id,
                    label=text,
                    value=opt.get("value"),
                    order_index=i,
                )
            )
        db.commit()

    return {"ok": True, "question_id": q.id}


# =========================================================
# ✅ UPDATE QUESTION
# =========================================================
@router.patch("/questions/{question_id}", dependencies=[Depends(require_admin)])
def update_question(question_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    q = db.query(FormQuestion).filter(FormQuestion.id == question_id).first()
    if not q:
        raise HTTPException(404, detail="Question not found")

    if "label" in payload:
        label = (payload.get("label") or "").strip()
        if not label:
            raise HTTPException(400, detail="Question label required")
        q.label = label

    if "qtype" in payload:
        q.qtype = _validate_question_type(payload.get("qtype") or q.qtype)

    if "is_required" in payload:
        q.is_required = bool(payload.get("is_required"))

    if "help_text" in payload:
        q.help_text = (payload.get("help_text") or "").strip() or None

    if q.qtype == MODULE_HARDWARE_CISCO_QTYPE:
        q.help_text = None

    if "order_index" in payload:
        try:
            order_index = int(payload.get("order_index"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, detail="order_index must be an integer") from exc
        if order_index < 0:
            raise HTTPException(400, detail="order_index must be >= 0")
        q.order_index = order_index

    if "options" in payload or q.qtype == MODULE_HARDWARE_CISCO_QTYPE:
        db.query(FormOption).filter(FormOption.question_id == q.id).delete()
        options = payload.get("options") or []
        if q.qtype in ("single_choice", "multi_choice"):
            for i, opt in enumerate(options):
                text = (opt.get("label") or "").strip()
                if not text:
                    continue
                db.add(
                    FormOption(
                        question_id=q.id,
                        label=text,
                        value=opt.get("value"),
                        order_index=i,
                    )
                )

    db.commit()
    db.refresh(q)

    return {"ok": True, "question_id": q.id}


# =========================================================
# ✅ DELETE QUESTION
# =========================================================
@router.delete("/questions/{question_id}", dependencies=[Depends(require_admin)])
def delete_question(question_id: int, db: Session = Depends(get_db)):
    q = db.query(FormQuestion).filter(FormQuestion.id == question_id).first()
    if not q:
        raise HTTPException(404, detail="Question not found")

    db.delete(q)
    db.commit()
    return {"ok": True, "question_id": question_id}


# =========================================================
# ✅ UPDATE SECTION EDITORIAL
# =========================================================
@router.patch("/sections/{section_id}/editorial", dependencies=[Depends(require_admin)])
def update_section_editorial(section_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    s = db.query(FormSection).filter(FormSection.id == section_id).first()
    if not s:
        raise HTTPException(404, detail="Section not found")

    if "section_intent" in payload:
        s.section_intent = (payload.get("section_intent") or "").strip() or None

    if "section_example" in payload:
        s.section_example = (payload.get("section_example") or "").strip() or None

    db.commit()
    db.refresh(s)

    return {
        "ok": True,
        "section_id": s.id,
        "section_intent": getattr(s, "section_intent", None),
        "section_example": getattr(s, "section_example", None),
    }


# =========================================================
# ✅ MODULE HARDWARE CISCO ANSWERS
# =========================================================
@router.get("/{form_id}/module-questions/{question_id}/hardware")
def get_hardware_module_answer(form_id: int, question_id: int, db: Session = Depends(get_db)):
    _get_module_hardware_question(db, form_id, question_id)
    answer = (
        db.query(FormModuleAnswer)
        .filter(FormModuleAnswer.form_id == form_id, FormModuleAnswer.question_id == question_id)
        .first()
    )
    if not answer:
        return {"ok": True, "result": None}

    output_json = None
    if answer.output_json:
        try:
            output_json = json.loads(answer.output_json)
        except json.JSONDecodeError:
            output_json = answer.output_json

    bom_table = None
    if answer.output_bom_json:
        try:
            bom_table = json.loads(answer.output_bom_json)
        except json.JSONDecodeError:
            bom_table = answer.output_bom_json

    return {
        "ok": True,
        "result": {
            "reference": answer.reference,
            "output_json": output_json,
            "formatted_summary_text": answer.output_summary_text,
            "formatted_summary_html": answer.output_summary_html,
            "bom_table": bom_table,
            "output_docx_path": answer.output_docx_path,
            "generated_at": answer.generated_at.isoformat() if answer.generated_at else None,
        },
    }


@router.post("/{form_id}/module-questions/{question_id}/hardware/debug")
def run_hardware_module_debug(form_id: int, question_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    _get_module_hardware_question(db, form_id, question_id)
    hardware_ref = _validate_hardware_reference(payload.get("hardware_reference") or "")

    generated = generate_hardware_content(hardware_ref)

    answer = (
        db.query(FormModuleAnswer)
        .filter(FormModuleAnswer.form_id == form_id, FormModuleAnswer.question_id == question_id)
        .first()
    )
    if not answer:
        answer = FormModuleAnswer(form_id=form_id, question_id=question_id, reference=hardware_ref)
        db.add(answer)

    answer.reference = hardware_ref
    answer.output_json = json.dumps(generated["output_json"], ensure_ascii=False)
    answer.output_summary_text = generated["formatted_summary_text"]
    answer.output_summary_html = generated["formatted_summary_html"]
    answer.output_bom_json = json.dumps(generated["bom_table"], ensure_ascii=False)
    answer.generated_at = datetime.utcnow()

    db.commit()
    return {"ok": True, "reference": hardware_ref, **generated}


@router.post("/{form_id}/module-questions/{question_id}/hardware/save")
def run_hardware_module_save(form_id: int, question_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    _get_module_hardware_question(db, form_id, question_id)
    hardware_ref = _validate_hardware_reference(payload.get("hardware_reference") or "")

    generated = generate_hardware_content(hardware_ref)

    answer = (
        db.query(FormModuleAnswer)
        .filter(FormModuleAnswer.form_id == form_id, FormModuleAnswer.question_id == question_id)
        .first()
    )
    if not answer:
        answer = FormModuleAnswer(form_id=form_id, question_id=question_id, reference=hardware_ref)
        db.add(answer)

    answer.reference = hardware_ref
    answer.output_json = json.dumps(generated["output_json"], ensure_ascii=False)
    answer.output_summary_text = generated["formatted_summary_text"]
    answer.output_summary_html = generated["formatted_summary_html"]
    answer.output_bom_json = json.dumps(generated["bom_table"], ensure_ascii=False)
    answer.generated_at = datetime.utcnow()

    db.commit()
    return {"ok": True, "reference": hardware_ref, "message": "Résultat enregistré", **generated}


@router.post("/{form_id}/module-questions/{question_id}/hardware/docx")
def run_hardware_module_docx(form_id: int, question_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    _get_module_hardware_question(db, form_id, question_id)
    hardware_ref = _validate_hardware_reference(payload.get("hardware_reference") or "")

    generated = generate_hardware_content(hardware_ref)
    docx_bytes = hardware_to_docx_bytes(hardware_ref, generated["output_json"])

    safe_ref = re.sub(r"[^A-Za-z0-9._-]+", "_", hardware_ref)
    filename = f"hardware_form{form_id}_q{question_id}_{safe_ref}.docx"
    output_path = MODULE_OUTPUT_DIR / filename
    output_path.write_bytes(docx_bytes)

    answer = (
        db.query(FormModuleAnswer)
        .filter(FormModuleAnswer.form_id == form_id, FormModuleAnswer.question_id == question_id)
        .first()
    )
    if not answer:
        answer = FormModuleAnswer(form_id=form_id, question_id=question_id, reference=hardware_ref)
        db.add(answer)

    answer.reference = hardware_ref
    answer.output_json = json.dumps(generated["output_json"], ensure_ascii=False)
    answer.output_summary_text = generated["formatted_summary_text"]
    answer.output_summary_html = generated["formatted_summary_html"]
    answer.output_bom_json = json.dumps(generated["bom_table"], ensure_ascii=False)
    answer.output_docx_path = str(output_path)
    answer.generated_at = datetime.utcnow()

    db.commit()
    return {
        "ok": True,
        "reference": hardware_ref,
        **generated,
        "output_docx_path": str(output_path),
        "filename": filename,
    }


# =========================================================
# ✅ SUBMIT ANSWERS
# =========================================================
@router.post("/{form_id}/submit")
def submit_form(form_id: int, payload: FormSubmitPayload = Body(...), db: Session = Depends(get_db)):
    answers = payload.answers or {}
    created_by = payload.created_by
    insert_html = (payload.insert_html or "").strip() or None

    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    merged_answers: Dict[int, Dict[str, Any]] = {}

    for k, v in answers.items():
        if not str(k).startswith("q_"):
            continue
        try:
            qid = int(str(k).split("_", 1)[1])
        except Exception:
            continue

        if isinstance(v, list):
            selected = [str(x).strip() for x in v if str(x).strip()]
        else:
            val = str(v).strip()
            selected = [val] if val else []

        merged_answers[qid] = {
            "selected": selected,
            "other_text": None,
        }

    for item in payload.answers_detailed or []:
        selected = [str(x).strip() for x in (item.selected or []) if str(x).strip()]
        other_text = (item.other_text or "").strip() or None
        merged_answers[item.question_id] = {
            "selected": selected,
            "other_text": other_text,
        }

    question_ids = list(merged_answers.keys())
    questions = (
        db.query(FormQuestion)
        .filter(FormQuestion.id.in_(question_ids), FormQuestion.section_id.in_(
            db.query(FormSection.id).filter(FormSection.form_id == form_id)
        ))
        .all()
        if question_ids else []
    )
    question_map = {q.id: q for q in questions}

    required_module_questions = (
        db.query(FormQuestion)
        .join(FormSection, FormSection.id == FormQuestion.section_id)
        .filter(
            FormSection.form_id == form_id,
            FormQuestion.qtype == MODULE_HARDWARE_CISCO_QTYPE,
            FormQuestion.is_required.is_(True),
        )
        .all()
    )
    if required_module_questions:
        required_module_ids = [q.id for q in required_module_questions]
        saved_module_ids = {
            row.question_id
            for row in db.query(FormModuleAnswer).filter(
                FormModuleAnswer.form_id == form_id,
                FormModuleAnswer.question_id.in_(required_module_ids),
                FormModuleAnswer.output_summary_text.isnot(None),
            ).all()
        }
        missing = [q.label for q in required_module_questions if q.id not in saved_module_ids]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Module requis non exécuté: {', '.join(missing)}",
            )

    for qid, answer in merged_answers.items():
        q = question_map.get(qid)
        if not q:
            continue
        if q.qtype not in {"single_choice", "multi_choice"}:
            answer["other_text"] = None
            continue

        selected = answer.get("selected") or []
        other_selected = any(_is_other_option_label(label) for label in selected)
        if other_selected and not (answer.get("other_text") or "").strip():
            raise HTTPException(
                status_code=400,
                detail=f"other_text is required for question {qid} when Autres/Other is selected",
            )
        if not other_selected:
            answer["other_text"] = None

    sub = FormSubmission(form_id=form_id, created_by=created_by, insert_html=insert_html)
    db.add(sub)
    db.commit()
    db.refresh(sub)

    for qid, answer in merged_answers.items():
        q = question_map.get(qid)
        if not q:
            continue

        selected = answer.get("selected") or []
        value_text = ";".join(selected)
        if not value_text and not answer.get("other_text"):
            continue

        db.add(
            SubmissionAnswer(
                submission_id=sub.id,
                question_id=qid,
                value_text=value_text,
                other_text=answer.get("other_text"),
            )
        )

    db.commit()
    return {"status": "ok", "form_id": form_id, "submission_id": sub.id}


# =========================================================
# ✅ PREVIEW (AI JSON)  (your UI calls this)
# accepts submission_id + optional worksheet_id + removed_sec_keys (ignored here)
# =========================================================
@router.post("/{form_id}/preview")
def preview_ai(form_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    submission_id = payload.get("submission_id")
    if not submission_id:
        raise HTTPException(status_code=400, detail="submission_id required")

    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    sub = db.query(FormSubmission).filter(
        FormSubmission.id == int(submission_id),
        FormSubmission.form_id == form_id,
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    sections = (
        db.query(FormSection)
        .filter(FormSection.form_id == form_id)
        .order_by(FormSection.order_index.asc())
        .all()
    )
    section_keys = [s.sec_key for s in sections]
    if not section_keys:
        raise HTTPException(status_code=400, detail="No sections in this form")

    gen_payload = build_generation_payload(db, form_id=form_id, submission_id=int(submission_id))
    llm_provider = get_provider(payload.get("llm_provider"))
    sections_text = generate_sections_json(gen_payload, section_keys, llm_provider=llm_provider.value)

    return {"ok": True, "form_id": form_id, "submission_id": int(submission_id), "sections_text": sections_text}


# =========================================================
# ✅ SAVE PER-SECTION FINAL TEXT + COMMENT
# =========================================================
@router.put("/{form_id}/submission/{submission_id}/sections")
def save_submission_sections(form_id: int, submission_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    sub = db.query(FormSubmission).filter(
        FormSubmission.id == submission_id,
        FormSubmission.form_id == form_id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    items = payload.get("sections") or []
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="sections list required")

    valid_keys = {
        s.sec_key
        for s in db.query(FormSection).filter(FormSection.form_id == form_id).all()
    }

    saved = 0
    for it in items:
        sec_key = (it.get("sec_key") or "").strip()
        final_text = (it.get("final_text") or "").strip()
        comment = (it.get("comment") or "").strip() or None

        if not sec_key or sec_key not in valid_keys:
            continue
        if not final_text:
            continue

        row = db.query(SubmissionSectionText).filter(
            SubmissionSectionText.submission_id == submission_id,
            SubmissionSectionText.sec_key == sec_key,
        ).first()

        if row:
            row.final_text = final_text
            row.comment = comment
        else:
            db.add(
                SubmissionSectionText(
                    submission_id=submission_id,
                    form_id=form_id,
                    sec_key=sec_key,
                    final_text=final_text,
                    comment=comment,
                )
            )
        saved += 1

    db.commit()
    return {"ok": True, "saved": saved}


# =========================================================
# ✅ PREVIEW DOCX PIPELINE
# expects: sections_text + removed_sec_keys + worksheet_id
# =========================================================
@router.post("/{form_id}/preview-docx")
def preview_form_docx(form_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(404, detail="Form not found")

    tdoc = db.query(TemplateDoc).filter(TemplateDoc.id == form.doc_id).first()
    if not tdoc:
        raise HTTPException(404, detail="TemplateDoc not found")

    template_path = tdoc.stored_path
    if not template_path or not Path(template_path).exists():
        raise HTTPException(400, detail=f"Template file not found: {template_path}")

    sections_text: Dict[str, str] = payload.get("sections_text") or {}
    removed_sec_keys: List[str] = payload.get("removed_sec_keys") or []
    removed_titles: List[str] = payload.get("removed_titles") or []
    worksheet_id: Optional[int] = payload.get("worksheet_id")
    insert_html = (payload.get("insert_html") or "").strip() or None
    text_placeholder_values = payload.get("text_placeholder_values") or {}
    logo_upload_id = (payload.get("logo_upload_id") or "").strip() or None

    titles_to_remove: List[str] = []
    if removed_sec_keys:
        rows = db.query(FormSection.heading_title).filter(
            FormSection.form_id == form_id,
            FormSection.sec_key.in_(removed_sec_keys),
        ).all()
        titles_to_remove = [r[0] for r in rows if r and r[0]]
    if removed_titles:
        titles_to_remove.extend([t for t in removed_titles if t and t.strip()])
    if titles_to_remove:
        titles_to_remove = list(dict.fromkeys(t.strip() for t in titles_to_remove if t and t.strip()))

    worksheet_path = None
    if worksheet_id:
        worksheet_path = str(get_worksheet_path(worksheet_id))

    out_path = PREVIEW_DIR / f"preview_{form_id}_{uuid.uuid4().hex[:8]}.docx"

    apply_doc_pipeline(
        template_path=str(template_path),
        out_path=str(out_path),
        sections_text=sections_text,
        titles_to_remove=titles_to_remove,
        worksheet_path=worksheet_path,
        insert_html=insert_html,
        text_placeholder_values=text_placeholder_values,
        logo_path=_resolve_logo_asset_path(logo_upload_id),
    )

    return FileResponse(
        path=str(out_path),
        filename=out_path.name,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# =========================================================
# ✅ GENERATE FINAL DOCX (UPDATED: now uses pipeline too)
# payload: submission_id + worksheet_id + removed_sec_keys
# logic:
#  - use saved section texts when available
#  - generate missing via OpenAI
#  - apply pipeline (remove + replace + worksheet)
# =========================================================
@router.post("/{form_id}/generate")
def generate_doc(form_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    submission_id = payload.get("submission_id")
    if not submission_id:
        raise HTTPException(status_code=400, detail="submission_id required")

    removed_sec_keys = payload.get("removed_sec_keys") or []
    removed_titles: List[str] = payload.get("removed_titles") or []
    worksheet_id = payload.get("worksheet_id")
    text_placeholder_values = payload.get("text_placeholder_values") or {}
    logo_upload_id = (payload.get("logo_upload_id") or "").strip() or None
    llm_provider = get_provider(payload.get("llm_provider"))

    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise HTTPException(status_code=404, detail="Form not found")

    doc = db.query(TemplateDoc).filter(TemplateDoc.id == form.doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Template doc not found")

    sub = db.query(FormSubmission).filter(
        FormSubmission.id == int(submission_id),
        FormSubmission.form_id == form_id
    ).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")

    # ✅ NEW: payload insert_html override, else take from DB
    insert_html = (payload.get("insert_html") or "").strip() or None
    if not insert_html and getattr(sub, "insert_html", None):
        insert_html = (sub.insert_html or "").strip() or None

    sections = db.query(FormSection).filter(FormSection.form_id == form_id).order_by(FormSection.order_index.asc()).all()
    section_keys = [s.sec_key for s in sections]
    if not section_keys:
        raise HTTPException(status_code=400, detail="No sections in this form")

    saved_rows = db.query(SubmissionSectionText).filter(
        SubmissionSectionText.submission_id == int(submission_id),
        SubmissionSectionText.form_id == form_id
    ).all()
    saved_map = {r.sec_key: (r.final_text or "").strip() for r in saved_rows if (r.final_text or "").strip()}

    module_text_map = _module_sections_text(db=db, form_id=form_id)

    sections_text: Dict[str, str] = {}
    for k in section_keys:
        # Priorité explicite au contenu module (Hardware Cisco) quand il existe,
        # pour éviter qu'un ancien texte sauvegardé (ex: "TBD") masque le résultat module.
        module_value = (module_text_map.get(k) or "").strip()
        if module_value:
            sections_text[k] = module_value
            continue

        saved_value = (saved_map.get(k) or "").strip()
        if saved_value:
            sections_text[k] = saved_value
            continue

        sections_text[k] = ""

    missing_keys = [k for k in section_keys if not (sections_text.get(k) or "").strip()]

    if missing_keys:
        gen_payload = build_generation_payload(db, form_id=form_id, submission_id=int(submission_id))
        ai_out = generate_sections_json(gen_payload, missing_keys, llm_provider=llm_provider.value)
        for k in missing_keys:
            sections_text[k] = (ai_out.get(k) or "").strip() or "TBD"

    titles_to_remove = []
    if removed_sec_keys:
        rows = db.query(FormSection.heading_title).filter(
            FormSection.form_id == form_id,
            FormSection.sec_key.in_(removed_sec_keys)
        ).all()
        titles_to_remove = [r[0] for r in rows if r and r[0]]
    if removed_titles:
        titles_to_remove.extend([t for t in removed_titles if t and t.strip()])
    if titles_to_remove:
        titles_to_remove = list(dict.fromkeys(t.strip() for t in titles_to_remove if t and t.strip()))

    worksheet_path = None
    if worksheet_id:
        worksheet_path = str(get_worksheet_path(int(worksheet_id)))

    out_name = f"generated_{form_id}_{submission_id}_{uuid.uuid4().hex[:8]}.docx"
    out_path = GENERATED_DIR / out_name

    apply_doc_pipeline(
        template_path=str(doc.stored_path),
        out_path=str(out_path),
        sections_text=sections_text,
        titles_to_remove=titles_to_remove,
        worksheet_path=worksheet_path,
        insert_html=insert_html,  # ✅ NEW
        text_placeholder_values=text_placeholder_values,
        logo_path=_resolve_logo_asset_path(logo_upload_id),
    )

    return {
        "ok": True,
        "filename": out_name,
        "download_url": f"/api/forms/generated/{out_name}/download",
        "used_saved": len(section_keys) - len(missing_keys),
        "generated_now": len(missing_keys),
        "removed": len(titles_to_remove),
        "worksheet": bool(worksheet_path),
    }



    return {
        "ok": True,
        "filename": out_name,
        "download_url": f"/api/forms/generated/{out_name}/download",
        "used_saved": len(section_keys) - len(missing_keys),
        "generated_now": len(missing_keys),
    }


@router.get("/generated/{filename}/download")
def download_generated(filename: str):
    path = GENERATED_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Generated file not found")

    return FileResponse(
        path=str(path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
