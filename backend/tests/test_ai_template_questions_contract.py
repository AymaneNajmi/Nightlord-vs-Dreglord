import json
import os
import sys
import types

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT_DIR)

if "pydantic_settings" not in sys.modules:
    mock_module = types.ModuleType("pydantic_settings")

    class BaseSettings:  # pragma: no cover
        def __init__(self, **kwargs):
            annotations = getattr(self.__class__, "__annotations__", {})
            for key in annotations:
                if key in kwargs:
                    setattr(self, key, kwargs[key])
                elif key in os.environ:
                    setattr(self, key, os.environ[key])
                elif hasattr(self.__class__, key):
                    setattr(self, key, getattr(self.__class__, key))
                else:
                    setattr(self, key, None)


    class SettingsConfigDict(dict):
        pass

    mock_module.BaseSettings = BaseSettings
    mock_module.SettingsConfigDict = SettingsConfigDict
    sys.modules["pydantic_settings"] = mock_module

if "openpyxl" not in sys.modules:
    openpyxl_module = types.ModuleType("openpyxl")
    openpyxl_module.load_workbook = lambda *args, **kwargs: None
    sys.modules["openpyxl"] = openpyxl_module

from app.schemas.ai_template_builder import StyleGuide
from app.services.ai_template_builder import generate_questions_for_section


STYLE_GUIDE = StyleGuide(
    numbering_pattern="decimal",
    title_case="sentence",
    indentation=[0, 1, 2, 3],
    detected_examples=["1 Objectif"],
)


def test_empty_context_returns_no_questions() -> None:
    output = generate_questions_for_section(
        sec_id="SEC_1_1",
        title="Objectif",
        context_pack="",
        style_guide=STYLE_GUIDE,
        doc_type="LLD",
        techno="LAN",
    )
    assert output.questions == []


def test_short_context_returns_no_questions() -> None:
    output = generate_questions_for_section(
        sec_id="SEC_1_2",
        title="Contexte",
        context_pack="Contexte trop court.",
        style_guide=STYLE_GUIDE,
        doc_type="LLD",
        techno="LAN",
    )
    assert output.questions == []


def test_rich_context_returns_only_choice_questions(monkeypatch: pytest.MonkeyPatch) -> None:
    rich_context = "Architecture cible segmentation sécurité routage redondance supervision " * 6

    payload = {
        "sec_id": "SEC_2_1",
        "section_title": "Architecture cible",
        "purpose": "But: capturer les choix fermés du contexte.",
        "questions": [
            {
                "key": f"q_{idx}",
                "label": f"Question {idx}",
                "type": "single_choice" if idx % 2 == 0 else "multi_choice",
                "choices": ["A", "B", "C"],
                "required": True,
            }
            for idx in range(1, 10)
        ],
    }

    monkeypatch.setattr(
        "app.services.ai_template_builder.call_llm_json",
        lambda **kwargs: json.dumps(payload, ensure_ascii=False),
    )

    output = generate_questions_for_section(
        sec_id="SEC_2_1",
        title="Architecture cible",
        context_pack=rich_context,
        style_guide=STYLE_GUIDE,
        doc_type="LLD",
        techno="LAN",
    )

    assert 2 <= len(output.questions) <= 5
    assert all(question.type in {"single_choice", "multi_choice"} for question in output.questions)
    assert all(2 <= len(question.choices) <= 10 for question in output.questions)


def test_openai_failure_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    rich_context = "Architecture cible avec exigences de sécurité et dépendances " * 6
    monkeypatch.setattr(
        "app.services.ai_template_builder.call_llm_json",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("OpenAI down")),
    )

    output = generate_questions_for_section(
        sec_id="SEC_3_1",
        title="Sécurité",
        context_pack=rich_context,
        style_guide=STYLE_GUIDE,
        doc_type="LLD",
        techno="LAN",
    )

    assert len(output.questions) >= 2


def test_placeholder_only_context_skips_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"count": 0}

    def _boom(**kwargs):
        called["count"] += 1
        raise AssertionError("LLM should not be called for placeholder-only context")

    monkeypatch.setattr("app.services.ai_template_builder.call_llm_json", _boom)

    output = generate_questions_for_section(
        sec_id="SEC_9_1",
        title="Architecture",
        context_pack="[[SEC_9_1]]\n[[insérer schéma]]\n[[Excel: VLAN]]",
        style_guide=STYLE_GUIDE,
        doc_type="LLD",
        techno="LAN",
    )

    assert output.questions == []
    assert called["count"] == 0
