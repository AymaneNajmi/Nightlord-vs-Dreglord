import re
from difflib import SequenceMatcher
from typing import Iterable, List, Tuple

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

SNIPPET_CHUNKS = 3
SNIPPET_SEPARATOR = "\n--- EXTRACT ---\n"


def _strip_number_prefix(title: str) -> Tuple[str, str]:
    if not title:
        return "", ""
    cleaned = title.strip()
    match = re.match(
        r"^(?P<number>(?:[IVXLCDM]+|[A-Z]|\d+)(?:\.(?:[IVXLCDM]+|[A-Z]|\d+))*)\s+(?P<title>.+)$",
        cleaned,
    )
    if match:
        return match.group("number"), match.group("title").strip()
    return "", cleaned


def _compress_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    chunk_size = max(1, limit // SNIPPET_CHUNKS)
    parts = []
    parts.append(text[:chunk_size])
    if SNIPPET_CHUNKS >= 3:
        mid_start = max(0, len(text) // 2 - chunk_size // 2)
        parts.append(text[mid_start : mid_start + chunk_size])
    parts.append(text[-chunk_size:])
    return SNIPPET_SEPARATOR.join(parts)


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    deduped: List[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_title(value: str) -> str:
    value = value or ""
    _, stripped = _strip_number_prefix(value)
    cleaned = stripped or value
    cleaned = re.sub(r"[^a-zA-Z0-9À-ÿ]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _table_to_text(table: Table) -> str:
    rows: List[str] = []
    for row in table.rows:
        cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _iter_block_items(document: Document) -> Iterable[Paragraph | Table]:
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, document)
        elif child.tag.endswith("}tbl"):
            yield Table(child, document)


def _heading_level_from_style(style_name: str) -> int | None:
    if not style_name:
        return None
    name = style_name.strip()
    if not name:
        return None
    # Matches: "Heading 1", "Heading1", "Titre 1", "Titre1"
    match = re.search(r"(Heading|Titre)\s*(\d+)", name, re.IGNORECASE)
    if match:
        return int(match.group(2))
    lowered = name.lower()
    if lowered in {"title", "titre"}:
        return 1
    if lowered.startswith("heading") or lowered.startswith("titre"):
        digits = "".join(ch for ch in name if ch.isdigit())
        if digits:
            return int(digits)
        return 2
    return None


def _looks_like_heading_paragraph(paragraph: Paragraph) -> bool:
    text = (paragraph.text or "").strip()
    if len(text) < 4 or len(text) > 140:
        return False

    starts_num = text[0].isdigit()
    ends_colon = text.endswith(":")
    alpha_count = sum(c.isalpha() for c in text)
    upper_ratio = sum(c.isupper() for c in text) / max(1, alpha_count)
    mostly_upper = upper_ratio > 0.6 if alpha_count else False

    runs = list(paragraph.runs)
    if runs:
        bold_runs = sum(1 for r in runs if r.bold)
        bold_ratio = bold_runs / len(runs)
    else:
        bold_ratio = 0

    sizes = [r.font.size.pt for r in runs if r.font.size]
    avg_size = sum(sizes) / len(sizes) if sizes else 0

    return (starts_num or ends_colon or mostly_upper) and (bold_ratio >= 0.5 or avg_size >= 12)


def extract_sections_from_docx_by_headings(docx_path: str) -> List[dict]:
    doc = Document(docx_path)
    blocks: List[dict] = []
    char_offset = 0
    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            text = (block.text or "").strip()
            style_name = getattr(getattr(block, "style", None), "name", "") or ""
            level = _heading_level_from_style(style_name)
            is_heading = bool(level)
            if not is_heading and _looks_like_heading_paragraph(block):
                level = 3
                is_heading = True
            blocks.append(
                {
                    "type": "paragraph",
                    "text": text,
                    "is_heading": is_heading,
                    "level": level,
                    "start_offset": char_offset,
                    "end_offset": char_offset + len(text),
                }
            )
            char_offset += len(text) + 1
        else:
            table_text = _table_to_text(block)
            blocks.append(
                {
                    "type": "table",
                    "text": table_text,
                    "is_heading": False,
                    "level": None,
                    "start_offset": char_offset,
                    "end_offset": char_offset + len(table_text),
                }
            )
            char_offset += len(table_text) + 1

    heading_indices = [
        (idx, block["level"])
        for idx, block in enumerate(blocks)
        if block["type"] == "paragraph" and block["is_heading"] and block["text"]
    ]

    sections: List[dict] = []
    for pos, (idx, level) in enumerate(heading_indices):
        heading_text = blocks[idx]["text"]
        end = len(blocks)
        for next_idx, next_level in heading_indices[pos + 1 :]:
            if next_level is not None and next_level <= level:
                end = next_idx
                break
        content_parts: List[str] = []
        tables_near: List[str] = []
        for block in blocks[idx + 1 : end]:
            if block["type"] == "paragraph" and block["text"]:
                content_parts.append(block["text"])
            elif block["type"] == "table" and block["text"]:
                tables_near.append(block["text"])

        section_text = "\n".join(content_parts).strip()
        section_start = blocks[idx].get("start_offset", 0)
        section_end = blocks[end - 1].get("end_offset", section_start) if end > idx else blocks[idx].get("end_offset", section_start)
        sections.append(
            {
                "title": heading_text,
                "level": level,
                "text": section_text,
                "content": section_text,
                "tables": tables_near,
                "tables_near": tables_near,
                "start_offset": section_start,
                "end_offset": section_end,
            }
        )
    return sections


def build_section_context(
    title: str,
    sec_id: str,
    full_text: str,
    doc_tables: List[str],
    max_chars: int = 6000,
    docx_sections: List[dict] | None = None,
    doc_type: str | None = None,
    techno: str | None = None,
    allow_empty_context: bool = False,
) -> str:
    raw_title = title or ""
    _, stripped_title = _strip_number_prefix(raw_title)
    normalized_title = (stripped_title or raw_title).strip()
    title_lower = normalized_title.lower()
    full_text = full_text or ""
    keywords = [
        "vlan",
        "adressage",
        "routing",
        "routage",
        "ha",
        "firewall",
        "fmc",
        "ise",
        "prime",
        "supervision",
        "migration",
        "dc",
        "core",
        "campus",
        "datacenter",
        "sécurité",
        "securite",
        "switch",
        "routeur",
        "router",
        "vrf",
        "vpn",
        "dmz",
    ]
    title_tokens = re.findall(r"[a-zA-Z0-9À-ÿ]+", title_lower)
    expansion_keywords = [kw for kw in keywords if kw in title_lower]
    expansion_keywords.extend([tok for tok in title_tokens if len(tok) > 3])
    expansion_keywords = _dedupe_preserve_order(expansion_keywords)

    if docx_sections:
        normalized_input = _normalize_title(normalized_title)
        best_match = None
        best_score = 0.0
        for section in docx_sections:
            section_title = section.get("title") or ""
            normalized_section = _normalize_title(section_title)
            if not normalized_section:
                continue
            if normalized_input == normalized_section or normalized_input in normalized_section:
                best_match = section
                best_score = 1.0
                break
            score = SequenceMatcher(None, normalized_input, normalized_section).ratio()
            if score > best_score:
                best_score = score
                best_match = section
        if best_match and best_score >= 0.72:
            parts: List[str] = [f"SECTION {sec_id}: {normalized_title}".strip()]
            content = (best_match.get("text") or best_match.get("content") or "").strip()
            if content:
                parts.append("CONTENU SOUS LE HEADING:")
                parts.append(content)
            tables_near = best_match.get("tables") or best_match.get("tables_near") or []
            non_empty_tables = [t for t in tables_near if t]
            if non_empty_tables:
                parts.append("TABLEAUX PERTINENTS:")
                parts.extend(non_empty_tables)
            context_pack = "\n\n".join(parts).strip()
            # Si le match heading est vide, on continue vers les heuristiques globales.
            # Cela évite les contextes pauvres qui produisent des questions génériques.
            if content or non_empty_tables or len(context_pack) >= 200:
                if len(context_pack) > max_chars:
                    context_pack = context_pack[:max_chars].rstrip()
                return context_pack

    if allow_empty_context and docx_sections and not full_text.strip():
        return ""

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", full_text) if p.strip()]
    selected: List[str] = []
    for para in paragraphs:
        lower_para = para.lower()
        if title_lower and title_lower in lower_para:
            selected.append(para)
            continue
        if expansion_keywords and any(kw in lower_para for kw in expansion_keywords):
            selected.append(para)

    occurrences: List[int] = []
    if title_lower:
        occurrences = [match.start() for match in re.finditer(re.escape(title_lower), full_text.lower())]
    for occ in occurrences[:3]:
        start = max(0, occ - 1200)
        end = min(len(full_text), occ + 2400)
        selected.append(full_text[start:end].strip())

    table_candidates: List[str] = []
    for table in doc_tables:
        lower_table = table.lower()
        if title_lower and title_lower in lower_table:
            table_candidates.append(table)
            continue
        if expansion_keywords and any(kw in lower_table for kw in expansion_keywords):
            table_candidates.append(table)
            continue
        if any(k in title_lower for k in ["périmètre", "perimetre", "scope"]) and any(
            k in lower_table
            for k in ["bom", "vlan", "equip", "équip", "firewall", "switch", "router", "ise", "fmc", "prime"]
        ):
            table_candidates.append(table)

    selected = _dedupe_preserve_order(selected)
    table_candidates = _dedupe_preserve_order(table_candidates)

    parts: List[str] = [f"SECTION {sec_id}: {normalized_title}".strip()]
    if selected:
        parts.append("PARAGRAPHES PERTINENTS:")
        parts.extend(selected)
    if table_candidates:
        parts.append("TABLEAUX PERTINENTS:")
        parts.extend(table_candidates)

    context_pack = "\n\n".join(parts).strip()
    if len(context_pack) < 1500:
        if occurrences:
            occ = occurrences[0]
            start = max(0, occ - 4000)
            end = min(len(full_text), occ + 4000)
            fallback_chunk = full_text[start:end].strip()
        else:
            fallback_chunk = full_text[:8000].strip()
        if fallback_chunk and fallback_chunk not in context_pack:
            context_pack = "\n\n".join([context_pack, "CONTEXTE ÉTENDU:", fallback_chunk]).strip()
        if len(context_pack) < 1500:
            expanded = _compress_text(full_text, min(max_chars, 12000))
            if expanded and expanded not in context_pack:
                context_pack = "\n\n".join([context_pack, "CONTEXTE ÉTENDU (EXTRAITS):", expanded]).strip()

    if not context_pack.strip() and allow_empty_context:
        return ""

    if not context_pack.strip():
        context_pack = f"SECTION {sec_id}: {normalized_title}".strip()

    if len(context_pack) < 120 and not allow_empty_context:
        minimal_parts = [f"SECTION {sec_id}: {normalized_title}".strip()]
        if doc_type:
            minimal_parts.append(f"DOC_TYPE: {doc_type}")
        if techno:
            minimal_parts.append(f"TECHNO: {techno}")
        if full_text.strip():
            minimal_parts.append("CONTEXTE MINIMAL:")
            minimal_parts.append(_compress_text(full_text.strip(), min(max_chars, 1000)))
        context_pack = "\n\n".join(part for part in minimal_parts if part).strip()

    if len(context_pack) > max_chars:
        context_pack = context_pack[:max_chars].rstrip()
    return context_pack
