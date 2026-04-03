from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List

from openai import OpenAI

logger = logging.getLogger(__name__)

MODEL_NAME = "claude-sonnet-4-6"
MIN_QUESTIONS_PER_SECTION = 8
MAX_QUESTIONS_PER_SECTION = 15

SECTION_MARKER_RE = re.compile(r"\[\[(SEC_[A-Za-z0-9_]+)\]\]")


def extract_sections(raw_content: str) -> List[Dict[str, Any]]:
    """Extract sections and their real content from source text containing [[SEC_*]] placeholders."""
    content = raw_content or ""
    matches = list(SECTION_MARKER_RE.finditer(content))
    sections: List[Dict[str, Any]] = []

    if not matches:
        blocks = [b.strip() for b in re.split(r"\n\s*\n", content) if b.strip()]
        for idx, block in enumerate(blocks, start=1):
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            label = lines[0][:120] if lines else f"Section {idx}"
            sections.append(
                {
                    "section_id": f"SEC_{idx}",
                    "section_label": label,
                    "level": "H2",
                    "content": "\n".join(lines[1:]).strip() if len(lines) > 1 else block,
                }
            )
        return sections

    for idx, marker in enumerate(matches):
        section_id = marker.group(1)
        start = marker.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(content)
        block = content[start:end].strip()

        lines = [line.strip() for line in block.splitlines() if line.strip()]
        label = section_id
        level = "H2"
        section_text = block

        if lines:
            first_line = lines[0]
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", first_line)
            if heading_match:
                level = f"H{len(heading_match.group(1))}"
                label = heading_match.group(2).strip()
                section_text = "\n".join(lines[1:]).strip()
            else:
                title_match = re.match(r"^(?:Titre|Title)\s*:\s*(.+)$", first_line, flags=re.IGNORECASE)
                if title_match:
                    label = title_match.group(1).strip()
                    section_text = "\n".join(lines[1:]).strip()
                elif len(lines) > 1:
                    label = first_line[:120]
                    section_text = "\n".join(lines[1:]).strip()

        sections.append(
            {
                "section_id": section_id,
                "section_label": label,
                "level": level,
                "content": section_text,
            }
        )

    return sections


def _section_prompt(section: Dict[str, Any]) -> str:
    return (
        "Tu dois générer des questions riches et strictement spécifiques au contenu de CETTE section.\n"
        "N'utilise jamais le contenu d'une autre section. N'invente pas de valeurs génériques.\n"
        "Chaque question doit contenir : label, intent (2-3 phrases), example (pour IA uniquement), "
        "type, options, validation.\n"
        f"Nombre de questions: entre {MIN_QUESTIONS_PER_SECTION} et {MAX_QUESTIONS_PER_SECTION}.\n"
        "Types permis: single_choice, multiple_choice, boolean, text, table.\n"
        "Les options doivent être des valeurs techniques réelles et pertinentes du domaine réseau/sécurité.\n"
        "JSON attendu (strict):\n"
        "{{\n"
        "  \"section_id\": \"...\",\n"
        "  \"section_label\": \"...\",\n"
        "  \"level\": \"H2\",\n"
        "  \"questions\": [ ... ]\n"
        "}}\n\n"
        f"SECTION_ID: {section['section_id']}\n"
        f"SECTION_LABEL: {section['section_label']}\n"
        f"LEVEL: {section['level']}\n"
        "CONTENU REEL DE LA SECTION:\n"
        f"{section.get('content', '')}\n\n"
        "IMPORTANT:\n"
        "- id question format: q_<section_id>_<index>\n"
        "- order commence à 0 et s'incrémente\n"
        "- required=true pour toutes les questions\n"
        "- options=[] pour text/table si non applicable\n"
        "- validation cohérente avec le type\n"
        "- Réponds en JSON uniquement, sans markdown."
    )


def _check_section_prompt_no_crash() -> bool:
    section = {
        "section_id": "SEC_1_1",
        "section_label": "Sécurité périmétrique",
        "level": "H2",
        "content": (
            "Le NGFW active IPS, TLS inspection et segmentation des flux. "
            'Exemple validation: {"kind": "enum", "rules": ...}.' 
        ),
    }
    prompt = _section_prompt(section)
    return (
        isinstance(prompt, str)
        and "SEC_1_1" in prompt
        and '"questions": [ ... ]' in prompt
        and '{"kind": "enum", "rules": ...}' in prompt
    )


def _normalize_questions(section_payload: Dict[str, Any], section: Dict[str, Any]) -> Dict[str, Any]:
    questions = section_payload.get("questions") or []
    if len(questions) < MIN_QUESTIONS_PER_SECTION:
        base = questions[:]
        while len(base) < MIN_QUESTIONS_PER_SECTION:
            i = len(base)
            base.append(
                {
                    "id": f"q_{section['section_id']}_{i}",
                    "label": f"Préciser le paramètre technique #{i + 1} pour {section['section_label']}.",
                    "type": "text",
                    "required": True,
                    "order": i,
                    "intent": "Cette question capture un détail nécessaire à la conception cible. "
                    "Elle clarifie une contrainte opérationnelle utile pour générer un document final précis.",
                    "example": "Exemple interne IA: VLAN utilisateurs = 120.",
                    "options": [],
                    "validation": {"kind": "length", "rules": {"min": 3, "max": 400}},
                }
            )
        questions = base

    questions = questions[:MAX_QUESTIONS_PER_SECTION]
    for i, q in enumerate(questions):
        q["id"] = f"q_{section['section_id']}_{i}"
        q["order"] = i
        q["required"] = True
        q.setdefault("intent", "Question nécessaire pour qualifier le besoin technique de la section.")
        q.setdefault("example", "Valeur d'exemple interne IA.")
        q.setdefault("options", [])
        q.setdefault("validation", {"kind": "none", "rules": {}})

    return {
        "section_id": section["section_id"],
        "section_label": section["section_label"],
        "level": section["level"],
        "questions": questions,
    }


async def generate_questions_for_section(section: Dict[str, Any]) -> Dict[str, Any]:
    """Generate rich, section-specific questions for one section."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def _call_llm() -> Dict[str, Any]:
        response = client.responses.create(
            model=MODEL_NAME,
            input=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un expert réseau/sécurité. Génère des questions de formulaire ultra-spécifiques "
                        "au contenu fourni."
                    ),
                },
                {"role": "user", "content": _section_prompt(section)},
            ],
            temperature=0.2,
            max_output_tokens=5000,
        )

        payload = json.loads(response.output_text)
        return _normalize_questions(payload, section)

    try:
        return await asyncio.to_thread(_call_llm)
    except Exception as exc:  # pragma: no cover - fallback de résilience runtime
        logger.warning("LLM generation failed for section %s: %s", section.get("section_id"), exc)
        return _normalize_questions({"questions": []}, section)


async def generate_form(raw_content: str) -> List[Dict[str, Any]]:
    """Extract sections, then generate each section form in parallel via asyncio.gather."""
    sections = extract_sections(raw_content)
    tasks = [generate_questions_for_section(section) for section in sections]
    if not tasks:
        return []
    return await asyncio.gather(*tasks)
