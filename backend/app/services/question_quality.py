from __future__ import annotations

from typing import List

from app.schemas.ai_template_builder import FormQuestionSpec


def is_editorial_section(title: str) -> bool:
    lowered = (title or "").lower()
    return any(
        keyword in lowered
        for keyword in ["objectif", "contexte", "périmètre", "perimetre", "introduction", "glossaire"]
    )


def has_generic_labels(questions: List[FormQuestionSpec]) -> bool:
    forbidden = [
        "détails",
        "details",
        "informations",
        "description",
        "veuillez préciser",
        "preciser",
        "détails pour",
        "details pour",
    ]
    for question in questions:
        label = (question.label or "").lower()
        if any(term in label for term in forbidden):
            return True
    return False


def details_label_ratio(questions: List[FormQuestionSpec]) -> float:
    if not questions:
        return 0.0
    details_count = 0
    for question in questions:
        label = (question.label or "").lower()
        if "détails pour" in label or "details pour" in label:
            details_count += 1
    return details_count / len(questions)


def min_questions_required(is_editorial: bool) -> int:
    return 0


def enforce_question_quality(
    questions: List[FormQuestionSpec],
    is_editorial: bool,
    context_pack: str,
) -> None:
    if len(questions) > 8:
        del questions[8:]
    if details_label_ratio(questions) > 0.30:
        raise RuntimeError("Too many 'Détails pour' labels")
    if has_generic_labels(questions):
        raise RuntimeError("Generic labels detected")

    allowed_types = {"single_choice", "multi_choice"}
    for question in questions:
        if question.type not in allowed_types:
            raise RuntimeError(f"Unsupported question type: {question.type}")
        choices = question.choices or []
        if not (2 <= len(choices) <= 10):
            raise RuntimeError("choices must contain between 2 and 10 values")
