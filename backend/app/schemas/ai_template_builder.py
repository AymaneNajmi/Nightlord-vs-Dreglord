from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class StyleGuide(BaseModel):
    numbering_pattern: str
    title_case: str
    indentation: List[int]
    detected_examples: List[str] = []

    class Config:
        extra = "forbid"


class TemplateOutlineItem(BaseModel):
    id: Optional[str] = None
    level: int = Field(ge=1, le=4)
    number: str
    title: str
    style_name: str
    content: str
    markers: List[str] = []
    descriptive_text: Optional[str] = None

    class Config:
        extra = "forbid"


class PlaceholderSpec(BaseModel):
    sec_id: str
    description: str
    recommended_question_types: List[str] = []
    intent: Optional[str] = None
    example: Optional[str] = None
    validation_rules: Optional[List[str]] = None
    placeholder: Optional[str] = None

    class Config:
        extra = "forbid"


class ExcelTableSpec(BaseModel):
    name: str
    reason: str
    columns_suggested: List[str] = []

    class Config:
        extra = "forbid"


class InsertItemSpec(BaseModel):
    name: str
    type: str = Field(pattern="^(image|diagram)$")
    description: str

    class Config:
        extra = "forbid"


class FormQuestionSpec(BaseModel):
    key: Optional[str] = None
    label: str
    type: Literal["single_choice", "multi_choice"]
    choices: List[str] = Field(min_length=2, max_length=10)
    required: bool = False
    help_text: Optional[str] = None

    class Config:
        extra = "forbid"


class FormSectionSpec(BaseModel):
    sec_id: str
    purpose: Optional[str] = None
    questions: List[FormQuestionSpec]

    class Config:
        extra = "forbid"


class FormSpec(BaseModel):
    sections: List[FormSectionSpec]

    class Config:
        extra = "forbid"


class SectionQuestionsOutput(BaseModel):
    sec_id: str
    section_title: str
    purpose: Optional[str] = None
    questions: List[FormQuestionSpec]

    class Config:
        extra = "forbid"


class AITemplateOutput(BaseModel):
    style_guide: StyleGuide
    template_outline: List[TemplateOutlineItem]
    placeholders: List[PlaceholderSpec]
    excel_tables: List[ExcelTableSpec]
    insert_items: List[InsertItemSpec]
    form: FormSpec

    class Config:
        extra = "forbid"


class AITemplateJobCreate(BaseModel):
    techno_name: str
    template_type: Optional[str] = None
    doc_type: str = "INGENIERIE"
    cover_template_id: Optional[int] = None
    client_names_to_remove: Optional[str] = None
    llm_provider: str = "openai"
