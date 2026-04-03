from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

class SectionEditorialUpdate(BaseModel):
    section_intent: Optional[str] = None
    section_example: Optional[str] = None


class SubmitAnswerItem(BaseModel):
    question_id: int
    selected: List[str] = Field(default_factory=list)
    other_text: Optional[str] = None


class FormSubmitPayload(BaseModel):
    created_by: Optional[str] = None
    insert_html: Optional[str] = None
    answers: Dict[str, Any] = Field(default_factory=dict)
    answers_detailed: List[SubmitAnswerItem] = Field(default_factory=list)
