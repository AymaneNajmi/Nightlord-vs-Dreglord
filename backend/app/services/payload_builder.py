import json
from sqlalchemy.orm import Session
from app.models.forms import FormTemplate, FormSection, FormQuestion, FormOption
from app.models.submissions import FormSubmission, SubmissionAnswer
from app.models.template_doc import TemplateDoc
from app.models.form_module_answer import FormModuleAnswer
from app.models.techno import Techno

def _parse_json_safe(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return raw


def build_generation_payload(db: Session, form_id: int, submission_id: int) -> dict:
    form = db.query(FormTemplate).filter(FormTemplate.id == form_id).first()
    if not form:
        raise ValueError("Form not found")

    sub = db.query(FormSubmission).filter(
        FormSubmission.id == submission_id,
        FormSubmission.form_id == form_id
    ).first()
    if not sub:
        raise ValueError("Submission not found")

    techno = db.query(Techno).filter(Techno.id == form.techno_id).first()
    doc = db.query(TemplateDoc).filter(TemplateDoc.id == form.doc_id).first()

    ans = db.query(SubmissionAnswer).filter(SubmissionAnswer.submission_id == sub.id).all()
    ans_map = {a.question_id: a for a in ans}

    module_rows = db.query(FormModuleAnswer).filter(FormModuleAnswer.form_id == form.id).all()
    module_map = {m.question_id: m for m in module_rows}

    sections = db.query(FormSection).filter(FormSection.form_id == form.id).order_by(FormSection.order_index.asc()).all()

    out_sections = []
    for s in sections:
        questions = db.query(FormQuestion).filter(FormQuestion.section_id == s.id).order_by(FormQuestion.order_index.asc()).all()

        out_q = []
        for q in questions:
            row = ans_map.get(q.id)
            raw = ((row.value_text if row else "") or "").strip()
            other_text = ((row.other_text if row else None) or "").strip() or None

            if ";" in raw:
                answer = [x.strip() for x in raw.split(";") if x.strip()]
            else:
                answer = raw if raw else None

            if other_text:
                if isinstance(answer, list):
                    answer = [*answer, f"Autres: {other_text}"]
                elif answer:
                    answer = f"{answer} | Autres: {other_text}"
                else:
                    answer = f"Autres: {other_text}"

            if q.qtype == "module_hardware_cisco":
                module_row = module_map.get(q.id)
                module_payload = None
                if module_row:
                    module_payload = {
                        "reference": module_row.reference,
                        "generated_at": module_row.generated_at.isoformat() if module_row.generated_at else None,
                        "output_docx_path": module_row.output_docx_path,
                        "output_json": _parse_json_safe(module_row.output_json),
                        "formatted_summary_text": module_row.output_summary_text,
                        "formatted_summary_html": module_row.output_summary_html,
                        "bom_table": _parse_json_safe(module_row.output_bom_json),
                    }
                answer = module_payload
                other_text = None

            out_q.append({
                "id": q.id,
                "label": q.label,
                "qtype": q.qtype,
                "help_text": q.help_text,
                "answer": answer,
                "other_text": other_text,
            })

        out_sections.append({
            "section_id": s.id,
            "sec_key": s.sec_key,
            "title": s.heading_title,
            "level": s.heading_level,

            # ✅ NEW (admin-defined)
            "section_intent": getattr(s, "section_intent", None),
            "section_example": getattr(s, "section_example", None),

            "questions": out_q
        })

    payload = {
        "context": {
            "doc_type": str(getattr(techno, "doc_type", None)) if techno else None,
            "form_name": form.name,
            "doc_filename": doc.filename if doc else None,
            "created_by": sub.created_by,
            "hardware_modules": [
                {
                    "question_id": m.question_id,
                    "reference": m.reference,
                    "generated_at": m.generated_at.isoformat() if m.generated_at else None,
                    "output_json": _parse_json_safe(m.output_json),
                    "formatted_summary_text": m.output_summary_text,
                    "formatted_summary_html": m.output_summary_html,
                    "bom_table": _parse_json_safe(m.output_bom_json),
                }
                for m in module_rows
                if m.output_json
            ],
        },
        "sections": out_sections
    }
    return payload
