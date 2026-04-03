import os
import re
import sys
import types

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

from app.schemas.ai_template_builder import TemplateOutlineItem
from app.services.ai_template_builder import _merge_section_purpose, normalize_template_placeholders

PLACEHOLDER_ONLY_RE = re.compile(r"^(\[\[[^\]]+\]\])(\n\[\[[^\]]+\]\])*$")


def test_template_content_contains_only_placeholders() -> None:
    outline = [
        TemplateOutlineItem(
            id="SEC_1_1",
            level=2,
            number="1.1",
            title="Présentation générale",
            style_name="Heading 2",
            content="Présentation générale de l'environnement client",
            markers=[],
        ),
        TemplateOutlineItem(
            id="SEC_2_1",
            level=2,
            number="2.1",
            title="Plan d'adressage",
            style_name="Heading 2",
            content="Texte libre\n[[Excel: Plan IP]]",
            markers=[],
        ),
    ]

    normalized_outline, _ = normalize_template_placeholders(outline)

    assert all(PLACEHOLDER_ONLY_RE.match(item.content or "") for item in normalized_outline)


def test_descriptive_text_is_moved_to_purpose() -> None:
    outline = [
        TemplateOutlineItem(
            id="SEC_3_1",
            level=2,
            number="3.1",
            title="Architecture cible",
            style_name="Heading 2",
            content="Présentation générale de l'architecture cible\n[[SEC_3_1]]",
            markers=[],
        )
    ]

    normalized_outline, _ = normalize_template_placeholders(outline)
    descriptive = normalized_outline[0].descriptive_text

    merged_purpose = _merge_section_purpose("But: collecter les choix techniques.", descriptive)

    assert descriptive == "Présentation générale de l'architecture cible"
    assert "Présentation générale" in (merged_purpose or "")
    assert "collecter les choix techniques" in (merged_purpose or "")
