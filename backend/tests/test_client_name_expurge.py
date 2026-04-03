import os
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

from app.models.techno import Techno
from app.models.template_doc import TemplateDoc
from app.schemas.ai_template_builder import AITemplateOutput
from app.services.ai_template_builder import create_form_from_output, deep_replace


class FakeQuery:
    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def update(self, *args, **kwargs):
        return 0

    def first(self):
        return None


class FakeDB:
    def __init__(self):
        self._id = 1
        self.inserted = []
        self.bulk_inserted = []

    def query(self, *args, **kwargs):
        return FakeQuery()

    def add(self, obj):
        self.inserted.append(obj)

    def add_all(self, objs):
        self.inserted.extend(objs)

    def flush(self):
        for obj in self.inserted:
            if hasattr(obj, "id") and getattr(obj, "id", None) is None:
                setattr(obj, "id", self._id)
                self._id += 1

    def bulk_save_objects(self, objs):
        self.bulk_inserted.extend(objs)


def test_client_name_replaced_in_output_and_db_insert() -> None:
    client_names = ["MAGHREBAIL"]
    raw_output = {
        "style_guide": {
            "numbering_pattern": "decimal",
            "title_case": "sentence",
            "indentation": [0, 1, 2],
            "detected_examples": ["MAGHREBAIL heading"],
        },
        "template_outline": [
            {
                "id": "SEC_1",
                "level": 2,
                "number": "1",
                "title": "Contexte MAGHREBAIL",
                "style_name": "Heading 2",
                "content": "Détail client MAGHREBAIL",
                "markers": [],
            }
        ],
        "placeholders": [],
        "excel_tables": [],
        "insert_items": [],
        "form": {
            "sections": [
                {
                    "sec_id": "SEC_1",
                    "purpose": "But MAGHREBAIL",
                    "questions": [
                        {
                            "key": "q_1",
                            "label": "Question MAGHREBAIL ?",
                            "type": "single_choice",
                            "choices": ["MAGHREBAIL A", "MAGHREBAIL B"],
                            "required": True,
                        }
                    ],
                }
            ]
        },
    }

    replaced_output = deep_replace(raw_output, client_names)
    serialized_output = str(replaced_output)
    assert "MAGHREBAIL" not in serialized_output

    output = AITemplateOutput.model_validate(replaced_output)
    db = FakeDB()
    techno = Techno(id=10, name="LAN")
    template_doc = TemplateDoc(id=20, techno_id=10, filename="f.docx", stored_path="/tmp/f.docx", mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    create_form_from_output(
        db=db,
        techno=techno,
        template_doc=template_doc,
        output=output,
        created_by="test",
        client_names=client_names,
    )

    inserted_payload = " ".join(str(obj) for obj in [*db.inserted, *db.bulk_inserted])
    assert "MAGHREBAIL" not in inserted_payload
