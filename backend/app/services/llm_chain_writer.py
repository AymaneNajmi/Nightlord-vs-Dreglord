import json
import logging
import asyncio
from typing import Dict, Any, List

from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

logger = logging.getLogger(__name__)

# Reusing the existing normalizer to remain Word-safe
def _normalize_word_text(s: str) -> str:
    import re
    if not isinstance(s, str):
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = s.replace("\t", " ")
    s = re.sub(r"[ ]{2,}", " ", s)
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()

# ==============================================================================
# INITIALISATION DES MODELES (LANGCHAIN)
# ==============================================================================
# "gpt-4o-mini" instead of "gpt-5-mini" as requested
llm_openai_planning = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
llm_openai_router = ChatOpenAI(model="gpt-4o-mini", temperature=0.0)
llm_openai_validator = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

llm_claude_writer = ChatAnthropic(model="claude-4-6-sonnet", temperature=0.7)
llm_claude_fallback = ChatAnthropic(model="claude-4-6-sonnet", temperature=0.4)

# ==============================================================================
# SCHEMAS DE SORTIE STRUCTUREE
# ==============================================================================
class TechnicalPlan(BaseModel):
    """Plan structuré attendu par OpenAI."""
    key_points: List[str] = Field(description="Liste des points techniques clés à aborder.")
    architecture_components: List[str] = Field(description="Composants d'architecture détectés.")
    suggested_structure: str = Field(description="Structure suggérée pour la rédaction finale.")

class FinalValidationResult(BaseModel):
    """Résultat de la vérification finale OpenAI."""
    is_valid: bool = Field(description="True si la rédaction finale respecte le format et ne contient pas de défaillances techniques.")
    corrected_text: str = Field(description="Texte potentiellement corrigé ou recopié.")

class RouteDecision(BaseModel):
    """Décision du routeur."""
    route: str = Field(description="La route choisie : 'hybrid', 'claude_only', ou 'openai_only'.")

class FinalText(BaseModel):
    """Pour les cas où l'on a besoin de contraindre OpenAI à sortir le texte final sous forme JSON."""
    final_text: str = Field(description="Le texte final formaté pour le document LLD.")

# ==============================================================================
# SYSTEM PROMPTS AVEC COMPOSANTS (Identité, Objectif, Contraintes, Résultats)
# ==============================================================================

openai_planning_prompt = ChatPromptTemplate.from_messages([
    ("system", """## Identité
Tu es un Architecte IT Système et Réseau très pragmatique, capable d'extraire la substantifique moelle d'informations techniques confuses.

## Objectif
Analyser les données brutes (Formulaire, Réponses de l'Ingénieur, Contexte) et concevoir un plan technique structuré précis pour la rédaction finale d'une section LLD.

## Contraintes
1. Tu ne rédiges pas le texte final. Tu extrais uniquement les données techniques factuelles et tu dictes la trame.
2. Tu dois formater ton retour en JSON strict (conforme au schéma).
3. Ne néglige aucune donnée technique essentielle présente dans le contexte.

## Résultats Attendus
Un objet JSON contenant "key_points", "architecture_components" et "suggested_structure".
"""),
    ("user", """## Contexte (Données Brutes)
{payload_data}

## Section Cible
Section : {section_key}

Sors-moi l'extraction technique et le plan :""")
])

claude_writing_prompt = ChatPromptTemplate.from_messages([
    ("system", """## Identité
Tu es un Technical Writer Senior, réputé pour ton style formel, précis, et élégant en français. Tu simplifies la lecture des documents d'ingénierie (LLD/HLD).

## Objectif
À partir des données techniques extraites et du plan suggéré, tu dois rédiger le texte final qui sera inséré dans le dossier d'ingénierie (Word).

## Contraintes
1. Ne JAMAIS utiliser de termes markéting ou exagérés (ex: "Incroyable", "Superbe"). Reste purement professionnel et factuel.
2. Respecte fidèlement les éléments techniques du plan fourni. Aucune hallucination de composants non listés.
3. Structure ton texte en 2 à 4 paragraphes fluides, avec d'éventuelles puces si nécessaire, mais en format texte propre. Pas de balises markdown encombrantes (comme #, ##, **, etc) qui pourraient casser l'insertion Word.
4. Rédige en Français.

## Résultats Attendus
Le texte rédactionnel final, prêt à être poussé dans un DOCX.
"""),
    ("user", """## Plan Technique Fourni
{technical_plan}

## Section Cible
Section : {section_key}

## Données de Contexte supplémentaires (si besoin de précisions)
{payload_data}

Rédige le texte final :""")
])

openai_validation_prompt = ChatPromptTemplate.from_messages([
    ("system", """## Identité
Tu es un Auditeur Qualité technique et syntaxique. Ton rôle est de sécuriser le contenu avant son export en document final.

## Objectif
Vérifier que le brouillon (Draft) rédigé est complet, sans jargon inadapté, purement factuel, et bien formaté en texte simple.

## Contraintes
1. Si le texte contient des marqueurs illisibles, du markdown abusif, ou du contenu générique vide, corrige-le.
2. S'il est valide, renvoie is_valid à true et repasse le même texte.
3. Rendre une structure JSON stricte.

## Résultats Attendus
Un objet JSON avec "is_valid" et "corrected_text".
"""),
    ("user", """## Brouillon à auditer
{draft_text}

## Section Cible
Section : {section_key}

Réalise l'audit et renvoie le JSON :""")
])

openai_router_prompt = ChatPromptTemplate.from_messages([
    ("system", """## Identité
Tu es le Cerveau (Router) de l'orchestrateur de génération documentaire.

## Objectif
Catégoriser le besoin de la section selon la complexité et choisir le pipeline adéquat.

## Contraintes
- 'hybrid' : nécessite une grande qualité rédactionnelle ET de la technique (ex: présentation de l'architecture).
- 'openai_only' : pure extraction tabulaire ou technique factuelle simple.
- 'claude_only' : simple texte introductif ou éditorial, peu de contenu complexe.

## Résultats Attendus
Un objet JSON indiquant la `route`.
"""),
    ("user", """## Contexte Méta
Section: {section_key}
Données brutes: {payload_sample}

Quelle est la route ?""")
])

# ==============================================================================
# CHAÎNES LCEL (LangChain Expression Language)
# ==============================================================================

# 1. Extraction Technique
openai_planning_chain = openai_planning_prompt | llm_openai_planning.with_structured_output(TechnicalPlan)

# 2. Rédaction
claude_writing_chain = claude_writing_prompt | llm_claude_writer | StrOutputParser()

# 3. Validation
openai_validation_chain = openai_validation_prompt | llm_openai_validator.with_structured_output(FinalValidationResult)

# 4. Routeur
openai_router_chain = openai_router_prompt | llm_openai_router.with_structured_output(RouteDecision)


# ==============================================================================
# LOGIQUE D'ORCHESTRATION ASYNCHRONE 
# ==============================================================================

async def execute_hybrid_pipeline(payload: Dict[str, Any], section_key: str) -> str:
    """
    Le Pipeline Hybride a été inversé selon le plan : 
    OpenAI (Plan technique) -> Claude (Rédaction Narrative) -> OpenAI (Validation).
    """
    payload_str = json.dumps(payload.get("context", {}), ensure_ascii=False)
    
    # Étape 1 : Planification / Extraction (OpenAI)
    try:
        plan_obj = await openai_planning_chain.ainvoke({"payload_data": payload_str, "section_key": section_key})
        technical_plan = json.dumps({
            "key_points": plan_obj.key_points,
            "architecture_components": plan_obj.architecture_components,
            "suggested_structure": plan_obj.suggested_structure
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Failed Planning OpenAI for {section_key} : {e}")
        technical_plan = "Extrait de contexte brut: " + payload_str[:1500]

    # Étape 2 : Rédaction (Claude) avec fallback
    try:
        draft_text = await claude_writing_chain.ainvoke({
            "payload_data": payload_str[:2000], 
            "technical_plan": technical_plan, 
            "section_key": section_key
        })
    except Exception as e:
        logger.error(f"Failed Writing Claude for {section_key} : {e}")
        fallback = ChatPromptTemplate.from_messages([("user", "Fais un résumé professionnel de: {txt}")]) | llm_claude_fallback | StrOutputParser()
        draft_text = await fallback.ainvoke({"txt": technical_plan[:2000]})

    # Étape 3 : Validation Qualité (OpenAI)
    try:
        validation_obj = await openai_validation_chain.ainvoke({"draft_text": draft_text, "section_key": section_key})
        if not validation_obj.is_valid:
            logger.info(f"Self-correction triggered by OpenAI for {section_key}.")
            final_text = validation_obj.corrected_text
        else:
            final_text = draft_text
    except Exception as e:
        logger.warning(f"Validation flow skipped due to error: {e}")
        final_text = draft_text

    return _normalize_word_text(final_text)

async def execute_router(payload: Dict[str, Any], section_key: str) -> str:
    """Détermine dynamiquement la route (Router Agent)."""
    payload_str = str(payload.get("context", {}))[:500]
    
    try:
        decision = await openai_router_chain.ainvoke({"section_key": section_key, "payload_sample": payload_str})
        return decision.route
    except Exception:
        return "hybrid"

async def generate_section_chained(section_key: str, payload: Dict[str, Any]) -> str:
    route = await execute_router(payload, section_key)
    logger.info(f"Router Decision for {section_key}: {route}")
    
    if route == "hybrid":
        return await execute_hybrid_pipeline(payload, section_key)
    elif route == "claude_only":
        direct_prompt = ChatPromptTemplate.from_messages([
            ("system", "## Identité\nTu es un Assistant d'écriture neutre et professionnel.\n\n## Objectif\nRédiger une synthèse nette.\n\n## Contraintes\nPas de markdown complexe.\n\n## Résultats\nDu texte brut."),
            ("user", "Section: {section_key}\nData: {payload}")
        ])
        chain = direct_prompt | llm_claude_writer | StrOutputParser()
        res = await chain.ainvoke({"section_key": section_key, "payload": json.dumps(payload, ensure_ascii=False)[:2000]})
        return _normalize_word_text(res)
    else:
        # openai_only
        direct_prompt = ChatPromptTemplate.from_messages([
            ("system", "## Identité\nTu es un extracteur technique.\n\n## Objectif\nExtraire les infos brutes et factuelles.\n\n## Contraintes\nAucun style narratif.\n\n## Résultats\nJSON {final_text: ...}"),
            ("user", "Section: {section_key}\nData: {payload}")
        ])
        chain = direct_prompt | llm_openai_planning.with_structured_output(FinalText)
        res = await chain.ainvoke({"section_key": section_key, "payload": json.dumps(payload, ensure_ascii=False)[:2000]})
        return _normalize_word_text(res.final_text)

def generate_sections_chained_sync(payload: Dict[str, Any], section_keys: List[str]) -> Dict[str, str]:
    async def gather_all():
        tasks = [generate_section_chained(key, payload) for key in section_keys]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_output = {}
        for key, result in zip(section_keys, results):
            if isinstance(result, Exception):
                logger.error(f"Error gathering section {key}: {result}")
                final_output[key] = "TBD - Erreur de génération LCEL."
            else:
                final_output[key] = result
        return final_output

    return asyncio.run(gather_all())
