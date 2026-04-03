from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api_forms import add_question, generate_doc, run_hardware_module_debug, run_hardware_module_save, submit_form
from app.core.db import Base, SessionLocal, engine
from app.models.forms import FormQuestion, FormSection, FormTemplate
from app.models.form_module_answer import FormModuleAnswer
from app.models.submission_section_text import SubmissionSectionText
from app.models.techno import DocType, Techno
from app.models.template_doc import TemplateDoc
from app.schemas.forms import FormSubmitPayload
from app.services.payload_builder import build_generation_payload


@pytest.fixture(autouse=True)
def clean_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


def seed_form(db):
    doc = TemplateDoc(filename="t.docx", stored_path="/tmp/t.docx", type=DocType.TEMPLATE)
    db.add(doc)
    db.flush()

    techno = Techno(name="Campus")
    db.add(techno)
    db.flush()

    form = FormTemplate(techno_id=techno.id, doc_id=doc.id, name="F1", version=1, is_active=True)
    db.add(form)
    db.flush()

    section = FormSection(
        form_id=form.id,
        sec_key="SEC_1",
        heading_level=1,
        heading_title="Section 1",
        order_index=0,
    )
    db.add(section)
    db.commit()
    return form, section


def test_admin_can_add_hardware_module_question_to_section():
    db = SessionLocal()
    _, section = seed_form(db)

    resp = add_question(
        section_id=section.id,
        payload={"qtype": "module_hardware_cisco", "is_required": True},
        db=db,
    )

    q = db.query(FormQuestion).filter(FormQuestion.id == resp["question_id"]).first()
    assert q is not None
    assert q.qtype == "module_hardware_cisco"
    assert q.label == "Hardware Cisco"
    assert q.is_required is True


def test_user_form_contains_hardware_module_widget_markup():
    html = Path("app/ui/user_form.html").read_text(encoding="utf-8")
    assert "module_hardware_cisco" in html
    assert "module-hardware-save" in html
    assert "module-hardware-debug" in html
    assert "module-hardware-docx" in html



def test_save_endpoint_persists_hardware_module_answer(monkeypatch):
    db = SessionLocal()
    form, section = seed_form(db)
    q_resp = add_question(
        section_id=section.id,
        payload={"qtype": "module_hardware_cisco", "is_required": True},
        db=db,
    )
    question_id = q_resp["question_id"]

    monkeypatch.setattr(
        "app.api_forms.generate_hardware_content",
        lambda _ref: {
            "output_json": {"description_generale": "ok"},
            "formatted_summary_text": "Référence: C9200L-24T-4X-E",
            "formatted_summary_html": "<p>Référence: C9200L-24T-4X-E</p>",
            "bom_table": {"columns": ["module_id", "description"], "rows": []},
        },
    )

    result = run_hardware_module_save(
        form_id=form.id,
        question_id=question_id,
        payload={"hardware_reference": "C9200L-24T-4X-E"},
        db=db,
    )

    assert result["ok"] is True
    assert result["message"] == "Résultat enregistré"

    saved = db.query(FormModuleAnswer).filter_by(form_id=form.id, question_id=question_id).first()
    assert saved is not None
    assert saved.reference == "C9200L-24T-4X-E"

    out = submit_form(form_id=form.id, payload=FormSubmitPayload(answers={}), db=db)
    assert out["status"] == "ok"

def test_required_module_blocks_submit_until_saved(monkeypatch):
    db = SessionLocal()
    form, section = seed_form(db)
    q_resp = add_question(
        section_id=section.id,
        payload={"qtype": "module_hardware_cisco", "is_required": True},
        db=db,
    )
    question_id = q_resp["question_id"]

    with pytest.raises(HTTPException) as exc:
        submit_form(form_id=form.id, payload=FormSubmitPayload(answers={}), db=db)
    assert exc.value.status_code == 400

    monkeypatch.setattr(
        "app.api_forms.generate_hardware_content",
        lambda _ref: {
            "output_json": {"description_generale": "ok"},
            "formatted_summary_text": "Référence: C9200L-24T-4X-E",
            "formatted_summary_html": "<p>Référence: C9200L-24T-4X-E</p>",
            "bom_table": {"columns": ["module_id", "description"], "rows": []},
        },
    )
    monkeypatch.setattr("app.api_forms.hardware_to_docx_bytes", lambda _ref, _data: b"docx")

    run_hardware_module_debug(
        form_id=form.id,
        question_id=question_id,
        payload={"hardware_reference": "C9200L-24T-4X-E"},
        db=db,
    )

    saved = db.query(FormModuleAnswer).filter_by(form_id=form.id, question_id=question_id).first()
    assert saved is not None
    assert saved.reference == "C9200L-24T-4X-E"

    out = submit_form(form_id=form.id, payload=FormSubmitPayload(answers={}), db=db)
    assert out["status"] == "ok"

    payload = build_generation_payload(db=db, form_id=form.id, submission_id=out["submission_id"])
    assert payload["context"]["hardware_modules"]
    first_module = payload["context"]["hardware_modules"][0]
    assert first_module["reference"] == "C9200L-24T-4X-E"
    section_question = payload["sections"][0]["questions"][0]
    assert section_question["qtype"] == "module_hardware_cisco"
    assert section_question["answer"]["reference"] == "C9200L-24T-4X-E"


def test_generate_document_prefers_module_text_over_saved_section_text(monkeypatch):
    db = SessionLocal()
    form, section = seed_form(db)
    q_resp = add_question(
        section_id=section.id,
        payload={"qtype": "module_hardware_cisco", "is_required": True},
        db=db,
    )
    question_id = q_resp["question_id"]

    monkeypatch.setattr(
        "app.api_forms.generate_hardware_content",
        lambda _ref: {
            "output_json": {"description_generale": "Switch coeur réseau"},
            "formatted_summary_text": "Référence: C9200L-24P-4X\nSwitch coeur réseau",
            "formatted_summary_html": "<p>Référence: C9200L-24P-4X</p>",
            "bom_table": {"columns": ["module_id", "description"], "rows": []},
        },
    )

    run_hardware_module_debug(
        form_id=form.id,
        question_id=question_id,
        payload={"hardware_reference": "C9200L-24P-4X"},
        db=db,
    )

    submit = submit_form(form_id=form.id, payload=FormSubmitPayload(answers={}), db=db)

    db.add(
        SubmissionSectionText(
            submission_id=submit["submission_id"],
            form_id=form.id,
            sec_key=section.sec_key,
            final_text="TBD",
        )
    )
    db.commit()

    captured = {}

    def fake_apply_doc_pipeline(**kwargs):
        captured.update(kwargs)

    def fail_ai_generation(_payload, _missing):
        raise AssertionError("AI generation should not run when module text is available")

    monkeypatch.setattr("app.api_forms.apply_doc_pipeline", fake_apply_doc_pipeline)
    monkeypatch.setattr("app.api_forms.generate_sections_json", fail_ai_generation)

    out = generate_doc(
        form_id=form.id,
        payload={"submission_id": submit["submission_id"]},
        db=db,
    )

    assert out["ok"] is True
    sec_text = captured["sections_text"]["SEC_1"]
    assert "Référence: C9200L-24P-4X" in sec_text
    assert sec_text != "TBD"


def test_generate_document_uses_hardware_module_text(monkeypatch):
    db = SessionLocal()
    form, section = seed_form(db)
    q_resp = add_question(
        section_id=section.id,
        payload={"qtype": "module_hardware_cisco", "is_required": True},
        db=db,
    )
    question_id = q_resp["question_id"]

    monkeypatch.setattr(
        "app.api_forms.generate_hardware_content",
        lambda _ref: {
            "output_json": {
                "description_generale": "Switch coeur réseau",
                "fonctionnalites": ["StackWise-160", "PoE+"],
                "datasheet_url": "https://cisco.example/ds",
            },
            "formatted_summary_text": "Référence: C9200L-24P-4X\nSwitch coeur réseau\nFonctionnalités:\n- StackWise-160",
            "formatted_summary_html": "<p>Référence: C9200L-24P-4X</p>",
            "bom_table": {"columns": ["module_id", "description"], "rows": []},
        },
    )

    run_hardware_module_debug(
        form_id=form.id,
        question_id=question_id,
        payload={"hardware_reference": "C9200L-24P-4X"},
        db=db,
    )

    submit = submit_form(form_id=form.id, payload=FormSubmitPayload(answers={}), db=db)

    captured = {}

    def fake_apply_doc_pipeline(**kwargs):
        captured.update(kwargs)

    def fail_ai_generation(_payload, _missing):
        raise AssertionError("AI generation should not run when module text is available")

    monkeypatch.setattr("app.api_forms.apply_doc_pipeline", fake_apply_doc_pipeline)
    monkeypatch.setattr("app.api_forms.generate_sections_json", fail_ai_generation)

    out = generate_doc(
        form_id=form.id,
        payload={"submission_id": submit["submission_id"]},
        db=db,
    )

    assert out["ok"] is True
    assert out["generated_now"] == 0
    sec_text = captured["sections_text"]["SEC_1"]
    assert "C9200L-24P-4X" in sec_text
    assert "Switch coeur réseau" in sec_text
    assert "StackWise-160" in sec_text


def test_module_injection_uses_same_summary_as_hardware_endpoint(monkeypatch):
    from types import SimpleNamespace

    from app.api_hardware import HardwareRequest, hardware_debug

    db = SessionLocal()
    form, section = seed_form(db)
    q_resp = add_question(
        section_id=section.id,
        payload={"qtype": "module_hardware_cisco", "is_required": True},
        db=db,
    )
    question_id = q_resp["question_id"]

    monkeypatch.setattr(
        "app.services.hardware_generator.generate_hardware_json",
        lambda _ref: SimpleNamespace(
            model_dump=lambda: {
                "description_generale": "Switch coeur réseau",
                "fonctionnalites": ["StackWise-160"],
                "performance_scalability": [{"metric": "Capacité", "value": "160 Gbps"}],
                "aspect_fonctionnel": "Commutation d'accès",
                "datasheet_url": "https://cisco.example/ds",
                "uplink_modules": [{"module_id": "C9200-NM-4X", "description": "4x10G"}],
            }
        ),
    )

    hardware_result = hardware_debug(
        payload=HardwareRequest(hardware_reference="C9200L-24P-4X"),
        user=SimpleNamespace(id=10, role="USER"),
    )

    module_result = run_hardware_module_debug(
        form_id=form.id,
        question_id=question_id,
        payload={"hardware_reference": "C9200L-24P-4X"},
        db=db,
    )

    assert module_result["formatted_summary_text"] == hardware_result["formatted_summary_text"]
    assert module_result["bom_table"] == hardware_result["bom_table"]

    submit = submit_form(form_id=form.id, payload=FormSubmitPayload(answers={}), db=db)
    payload = build_generation_payload(db=db, form_id=form.id, submission_id=submit["submission_id"])
    section_question = payload["sections"][0]["questions"][0]
    assert section_question["answer"]["formatted_summary_text"] == hardware_result["formatted_summary_text"]
