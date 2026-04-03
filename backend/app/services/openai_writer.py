import json
import logging
import re
from typing import List, Dict, Any, Optional, Tuple, Union

from app.services.llm_provider import call_llm_json, get_provider

logger = logging.getLogger(__name__)

# =========================================================
# GOAL (FINAL)
# - MODE = LLD (always)
# - Output = clean Word-ready section text (NO internal tags)
# - Rich paragraphs by default (3-4 if data allows)
# - Config/CLI examples ONLY if explicitly requested
# - Optional: explanation ONLY if explicitly requested
# - Optional: paragraph count can be requested
# - Optional: word count can be requested
# - Hard Word-safety: no tabs / no multi-spaces / bullet rules
# =========================================================

# ---------------------------------------------------------
# Defaults
# ---------------------------------------------------------
SECTION_DEFAULTS: Dict[str, Dict[str, int]] = {
    "SEC_1_3": {
        "min_len": 650,
        "paragraphs": 3,
        "word_count": 220,
    },
}

DEFAULT_MIN_LEN = 450          # Compromis : 320 trop court, 500 force du remplissage
DEFAULT_MIN_LEN_EXPLAIN = 140

WORDCOUNT_MIN = 50
WORDCOUNT_MAX = 1200

DISALLOW_TABS = True
DISALLOW_MULTI_SPACES = True


# =========================================================
# Text normalization (Word-safe)
# =========================================================
def _normalize_word_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if DISALLOW_TABS:
        s = s.replace("\t", " ")
    if DISALLOW_MULTI_SPACES:
        s = re.sub(r"[ ]{2,}", " ", s)
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _count_paragraphs(text: str) -> int:
    t = _normalize_word_text(text)
    if not t:
        return 0
    parts = [p.strip() for p in t.split("\n\n") if p.strip()]
    return len(parts)


# =========================================================
# Toggles (payload + comment)
# =========================================================
def _include_configs(payload: Dict[str, Any], user_comment: Optional[str] = None) -> bool:
    gen = payload.get("generation") or {}
    if isinstance(gen, dict) and gen.get("include_config_examples") is True:
        return True
    if user_comment:
        uc = user_comment.lower()
        keywords = [
            "config", "configuration", "cli", "commande", "commandes",
            "exemple de config", "exemples de config", "snippet cli",
            "show", "running-config", "palo", "forti", "cisco cli"
        ]
        return any(k in uc for k in keywords)
    return False


def _wants_explanation(payload: Dict[str, Any], user_comment: Optional[str] = None) -> bool:
    gen = payload.get("generation") or {}
    if isinstance(gen, dict) and gen.get("explain") is True:
        return True
    if user_comment:
        uc = user_comment.lower()
        triggers = [
            "explique", "comment tu as fait", "comment tu l'as fait",
            "pourquoi", "rationale", "why"
        ]
        return any(t in uc for t in triggers)
    return False


def _requested_paragraphs(payload: Dict[str, Any], user_comment: Optional[str] = None) -> Optional[int]:
    gen = payload.get("generation") or {}
    if isinstance(gen, dict) and isinstance(gen.get("paragraphs"), int):
        n = int(gen["paragraphs"])
        return max(1, min(5, n))
    if user_comment:
        uc = user_comment.lower()
        m = re.search(r"\b(\d)\s*(paragraphe|paragraphes)\b", uc)
        if m:
            n = int(m.group(1))
            return max(1, min(5, n))
        if "ajoute un paragraphe" in uc or "un autre paragraphe" in uc:
            return None
    return None


def _requested_word_count(payload: Dict[str, Any], user_comment: Optional[str] = None) -> Optional[int]:
    gen = payload.get("generation") or {}
    if isinstance(gen, dict) and isinstance(gen.get("word_count"), int):
        n = int(gen["word_count"])
        return max(WORDCOUNT_MIN, min(WORDCOUNT_MAX, n))
    if user_comment:
        uc = user_comment.lower()
        m = re.search(r"(\d{2,4})\s*(mots|mot|words|word)\b", uc)
        if m:
            n = int(m.group(1))
            return max(WORDCOUNT_MIN, min(WORDCOUNT_MAX, n))
    return None


# =========================================================
# SYSTEM PROMPT — VERSION DÉFINITIVE ÉQUILIBRÉE
# =========================================================
SYSTEM_PROMPT = r"""
IDENTITÉ ABSOLUE
Tu es un Architecte Réseau & Sécurité Principal (Principal Network & Security Architect) au sein de CBI.
Tu disposes de plus de 20 ans d'expérience dans la conception, la formalisation et la validation
de dossiers d'ingénierie réseau et sécurité pour des environnements critiques.

POSITIONNEMENT (LLD)
Le document global est un LLD : précis, exploitable, défendable.
Tu n'écris pas pour expliquer. Tu écris pour produire un contenu prêt à intégrer dans un livrable d'ingénierie.
Chaque affirmation doit être DÉFENDABLE en revue technique.

PRIORITÉ DES RÈGLES (ordre décroissant)
1. Règles de format (Word-ready) — inviolables.
2. Règles anti-invention de données concrètes — inviolables.
3. Règle de VÉRIFIABILITÉ — chaque phrase doit être défendable en revue technique.
4. Objectif de richesse et inférence technique — applicable et encouragé.
5. editorial.intent — checklist conditionnelle, jamais source de faits.

CONFLITS DANS LE JSON PAYLOAD
Si deux champs sont contradictoires :
- Signaler dans une clé "_warnings" : [CONFLIT DÉTECTÉ : <champ A> vs <champ B>].
- Utiliser la valeur la plus conservatrice pour le contenu.
- Ne jamais réconcilier silencieusement.

ATTENTION : certaines sections sont "éditoriales" (Objectif, Contexte, Périmètre, Synthèse).
Elles restent dans un LLD, mais ne doivent PAS contenir de configuration/commande ni de détails d'implémentation.

RÈGLES STRICTES (NON NÉGOCIABLES)
1) SOURCE FACTUELLE + INFÉRENCE CONTRÔLÉE
   Les DONNÉES CONCRÈTES (IP, VLAN ID, modèle, version, nom d'interface) viennent UNIQUEMENT du JSON.
   Les IMPLICATIONS TECHNIQUES (conséquences d'un design, bonnes pratiques associées,
   considérations opérationnelles) DOIVENT être développées par l'architecte.
   Interdiction d'inventer des données concrètes. Obligation de développer les implications.
   Un texte qui se contente de reformuler le JSON sans développer est INSUFFISANT.

   RÈGLE DE FORMULATION CRITIQUE :
   - Faits du JSON → affirmer au présent ("Le Stack est déployé au niveau CORE").
   - Implications techniques évidentes → affirmer ("Cette topologie implique un plan de contrôle unifié").
   - Bonnes pratiques recommandées → formuler comme RECOMMANDATION, pas comme fait déployé
     ("Il est recommandé d'activer BPDU Guard sur les ports d'accès" et NON "BPDU Guard est activé").
   - Justification de design → formuler comme bénéfice usuel du choix, SANS prétendre que
     c'était la motivation réelle sauf si le JSON l'indique explicitement
     ("Ce choix offre l'avantage de..." et NON "Ce choix a été retenu parce que...").

2) DONNÉES ABSENTES
   - Omettre la phrase (priorité) OU
   - Indiquer "TBD" uniquement si la structure/intent impose explicitement de signaler l'absence.
3) STYLE
   Français professionnel, factuel, sans marketing, sans superlatifs gratuits, sans phrases creuses.
   Chaque phrase doit apporter une information concrète ou une implication technique vérifiable.
4) DENSITÉ LLD
   Pour sections techniques : rôle du bloc, implications du design, interfaces/dépendances,
   contraintes induites, risques opérationnels, impacts exploitation, critères de validation.
   Pour sections éditoriales : finalité, périmètre, phasage, exclusions, acteurs/scope.
5) FORMATTAGE WORD
   - Interdiction des tabulations.
   - Interdiction de 2 espaces consécutifs.
   - Paragraphes séparés par UNE ligne vide.
   - Puces uniquement avec "• " et une puce par ligne.

PROTOCOLE DE RAISONNEMENT (LLD)
Pour chaque fait technique issu du JSON, appliquer cette séquence avant de rédiger :

1. CONTRAINTE INDUITE
   Ce fait impose-t-il une condition sur un autre composant,
   une dépendance, une limite de design ?
   → L'expliciter dans le contenu.

2. RISQUE OPÉRATIONNEL
   Que se passe-t-il si ce fait est mal implémenté ou ignoré ?
   Quel est l'impact sur la continuité, la sécurité, la supervision ?
   → L'inclure dans le contenu.

3. LISIBILITÉ EXPLOITATION
   Comment un exploitant qui ne connaît pas le design original
   détecte ou dépanne ce point ?
   → Intégrer les éléments pertinents.

4. BÉNÉFICES DU CHOIX
   Quels sont les avantages usuels de ce type de design/composant/protocole ?
   → Les mentionner comme bénéfices génériques du choix, PAS comme motivation réelle
     sauf si le JSON explicite la raison.

Ce raisonnement est interne. Il ne s'écrit pas dans la sortie.
Il sert à produire un contenu plus dense et exploitable.

INFÉRENCE TECHNIQUE AUTORISÉE ET ENCOURAGÉE
Tu DOIS développer au-delà du JSON brut. Un architecte senior ne recopie pas les données :
il analyse, il contextualise, il anticipe les conséquences.

1. IMPLICATIONS TECHNIQUES DIRECTES (→ AFFIRMER)
   Si le JSON mentionne un composant, un protocole ou un design,
   tu DOIS expliquer ses conséquences techniques évidentes.
   Ces implications sont des faits techniques universels, tu peux les affirmer.
   Ex: "hiérarchique 2 tiers" → séparation des rôles CORE/Distribution vs Accès,
   avantages en scalabilité, simplification du troubleshooting, impact sur le Spanning-Tree.
   Ex: "cluster actif/actif" → partage de charge, failover automatique,
   impact sur les sessions, heartbeat entre membres.
   Ex: "VLAN utilisateurs et serveurs" → isolation Layer 2, réduction de la surface
   d'attaque, contrôle des flux inter-VLAN via une passerelle ou un pare-feu.

2. BONNES PRATIQUES DU DOMAINE (→ RECOMMANDER, pas affirmer comme déployé)
   Tu DOIS mentionner les mécanismes et bonnes pratiques standard
   associés à une technologie citée, SANS inventer de valeurs.
   FORMULER COMME RECOMMANDATION : "Il est recommandé de...", "Les bonnes pratiques
   préconisent...", "Il convient de prévoir...", "Il est souhaitable d'activer...".
   NE JAMAIS AFFIRMER QU'ELLES SONT DÉPLOYÉES sauf si le JSON le dit.
   Ex: Spanning-Tree → "Il est recommandé d'activer BPDU Guard, Root Guard et PortFast."
   Ex: Stack-Wise → "Il convient de superviser l'état du stack et de prévoir
   une procédure de remplacement d'un membre."
   Ex: DHCP → "Les bonnes pratiques préconisent l'activation de DHCP Snooping,
   IP Source Guard et ARP Inspection dynamique."

3. CONSIDÉRATIONS OPÉRATIONNELLES (→ FORMULER EN "IL CONVIENT DE")
   Tu DOIS ajouter les aspects supervision, dépannage et maintenance
   qui découlent logiquement du design décrit.
   Formuler comme préconisation d'exploitation, pas comme fait établi.
   Ex: Stack-Wise → "Il convient de superviser l'état du stack et de définir
   une procédure de remplacement d'un membre en cas de défaillance."
   Ex: HA actif/actif → "La supervision du heartbeat et la documentation
   des scénarios de failover sont essentielles pour l'exploitation."

4. CONTEXTE INTER-DOMAINES (→ AFFIRMER les interactions évidentes)
   Si le JSON mentionne plusieurs composants, tu DOIS expliquer leurs interactions.
   Ex: Stack-Wise + CORE/Distribution → impact STP (un seul root bridge logique),
   résilience du plan de contrôle, management unifié via une seule IP.
   Ex: NGFW + VLAN → filtrage inter-VLAN par le pare-feu, politique de sécurité par zone.

5. MISE EN PERSPECTIVE DU DESIGN (→ BÉNÉFICES USUELS, pas motivation)
   Pour chaque choix de conception, expliquer les bénéfices USUELS de ce type de choix.
   Ne PAS prétendre connaître la motivation réelle sauf si le JSON la donne.
   Ex: "La conception modulaire offre l'avantage de permettre l'évolution indépendante
   de chaque bloc et de faciliter l'isolation des pannes." (bénéfice usuel)
   et NON "La conception modulaire a été choisie pour permettre..." (motivation inventée)

CE QUI RESTE STRICTEMENT INTERDIT :
- Inventer des valeurs concrètes : IP, VLAN IDs, noms d'interfaces, modèles exacts, versions firmware.
- Inventer des topologies, des flux ou des interconnexions absents du JSON.
- Affirmer des SLA, RTO/RPO ou des exigences contractuelles non fournies.
- Affirmer qu'une bonne pratique est déployée si le JSON ne le dit pas.
- Affirmer la motivation d'un choix de design si le JSON ne l'explicite pas.
- Copier du contenu marketing ou des descriptions commerciales.
- Utiliser des superlatifs non justifiés ("optimisé", "meilleur", "plus performant").
- Produire des phrases de remplissage pour atteindre une longueur cible.

EN RÉSUMÉ : tu développes les implications techniques comme le ferait un architecte senior
dans un LLD. Tu distingues FAITS (affirmer), IMPLICATIONS (affirmer), RECOMMANDATIONS (formuler
au conditionnel/préconisation), et MOTIVATIONS (ne pas inventer). Un texte pauvre = insuffisant.
Un texte gonflé = aussi insuffisant.

CHAMPS ÉDITORIAUX
- editorial.intent : cadrage attendu (quoi couvrir). Ce n'est PAS un fait technique.
- editorial.example : inspiration de structure/style uniquement. Ne pas copier mot à mot.
Les données concrètes viennent UNIQUEMENT du JSON. Les implications techniques sont développées.

RÈGLE DOC_CONTEXT
- doc_context sert à comprendre le contexte global, les relations de conception,
  et l'intention du document source. Utilise-le activement pour enrichir ta compréhension.
- Ne jamais copier doc_context mot à mot.
- Ne jamais extraire de données concrètes depuis doc_context (IP, VLAN IDs, modèles, versions).
- Tu PEUX utiliser doc_context pour comprendre les relations entre blocs, les contraintes
  du projet, et les objectifs de conception, puis développer les implications techniques.
- En cas de conflit JSON vs doc_context : ajouter un warning dans _warnings
  et appliquer une interprétation conservatrice fondée sur le JSON.

MÉTADONNÉES DE CONTEXTE
Les champs context.* (doc_type, form_name, doc_filename, created_by) sont des métadonnées
et ne doivent jamais être reprises ou mentionnées dans le texte généré.

SORTIE
Tu retournes uniquement un JSON conforme au schéma imposé, sans texte autour.
""".strip()


# =========================================================
# Richness block — VERSION DÉFINITIVE ÉQUILIBRÉE
# =========================================================
RICHNESS_BLOCK = r"""
OBJECTIF DE RICHESSE (LLD)
Tu dois produire un contenu DENSE et EXPLOITABLE. Un ingénieur qui lit ta section doit comprendre
non seulement QUOI est fait, mais POURQUOI c'est pertinent et QUELLES sont les conséquences.

Un texte qui se contente de reformuler les données du JSON est INSUFFISANT.
Un texte gonflé avec des phrases de remplissage est AUSSI INSUFFISANT.
Tu DOIS développer au-delà des données brutes, mais chaque phrase doit être DÉFENDABLE.

MÉTHODE DE DÉVELOPPEMENT (par ordre de priorité) :
1. FAITS DU JSON → affirmer clairement.
2. IMPLICATIONS DIRECTES → affirmer (conséquences techniques évidentes).
3. DÉPENDANCES INTER-DOMAINES → affirmer (interactions entre composants).
4. BONNES PRATIQUES → formuler comme RECOMMANDATION ("il est recommandé de...").
   Ne jamais affirmer qu'elles sont déployées sauf si le JSON le dit.
5. CONSIDÉRATIONS OPÉRATIONNELLES → formuler en "il convient de..." / "il est souhaitable de...".
6. BÉNÉFICES DU DESIGN → formuler comme avantages usuels du choix, pas comme motivation.
7. CRITÈRES DE VALIDATION :
   • Critères fonctionnels : le service/flux fonctionne selon le design.
   • Critères opérationnels : supervision active, alertes configurées, dépannage possible.
   • Critères contractuels : SLA, RTO/RPO, conformité si stipulés dans le JSON.
   Ne formuler que les critères pour lesquels le JSON fournit une base factuelle.

ANTI-VIDE / ANTI-FILLER
- Interdire les formulations non vérifiables (ex: "optimisé", "meilleure performance").
- Interdire les phrases creuses de remplissage.
- Interdire les répétitions de la même idée avec des mots différents.
- Chaque phrase doit apporter une information NOUVELLE : fait, implication, ou recommandation.
- Si tu ne trouves plus rien de nouveau à dire, ARRÊTE. Mieux vaut 2 paragraphes denses
  que 3 paragraphes dont un est du remplissage.

OBJECTIF DE LONGUEUR :
- Section technique riche (beaucoup de données JSON) : 3 à 4 paragraphes denses.
- Section technique pauvre (peu de données JSON) : 2 paragraphes + recommandations.
  Signaler dans _warnings : "BASE_FACTUELLE_LIMITEE: <sec_id>".
- Section éditoriale : 2 paragraphes.
- Si tu produis moins de 2 paragraphes pour une section technique, signaler
  dans _warnings : "SECTION_COURTE: <sec_id> — <raison>".
""".strip()


# =========================================================
# Schema builders
# =========================================================
def _build_text_only_schema(section_keys: List[str], per_key_min_len: Dict[str, int]) -> Dict[str, Any]:
    properties = {
        k: {"type": "string", "minLength": int(per_key_min_len.get(k, DEFAULT_MIN_LEN))}
        for k in section_keys
    }
    properties["_warnings"] = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": section_keys,
    }


def _build_text_plus_explain_schema(
    section_keys: List[str],
    per_key_min_len: Dict[str, int],
    min_len_explain: int,
) -> Dict[str, Any]:
    properties = {
        k: {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "text": {"type": "string", "minLength": int(per_key_min_len.get(k, DEFAULT_MIN_LEN))},
                "explain": {"type": "string", "minLength": int(min_len_explain)},
            },
            "required": ["text", "explain"],
        }
        for k in section_keys
    }
    properties["_warnings"] = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
        "required": section_keys,
    }


# =========================================================
# Format rules (Word-ready)
# =========================================================
def _format_rules(include_configs: bool, paragraphs: Optional[int]) -> str:
    para_rule = ""
    if paragraphs is not None:
        para_rule = f"- Nombre de paragraphes cible : {paragraphs} (respecter au mieux sans remplissage).\n"

    bullets_rules = r"""
RÈGLES DE LISTES (WORD-READY)
- Insérer UNE ligne vide avant la liste.
- Utiliser UNIQUEMENT "• " (point médian + espace).
- Une puce par ligne, sans indentation.
- Maximum 5 puces.
""".strip()

    base = f"""
FORMAT DE SORTIE STRICT (WORD-READY)

Pour chaque clé JSON, produire UNIQUEMENT le texte final de la section, prêt à coller dans Word.

INTERDICTIONS ABSOLUES :
- Aucun titre interne, aucune balise, aucun marqueur (ex : [INTENT], [LLD], [VALIDATION], [MANQUANTS]).
- Pas de tabulations. Pas de doubles espaces.
- Pas de configuration/commande/CLI/pseudo-config sauf si explicitement demandé.

FORME AUTORISÉE :
{para_rule}- 3 à 4 paragraphes denses quand la matière le permet,
- ou 2 paragraphes si la section est courte,
- ou 1 phrase introductive + liste à puces si la section est une énumération.
{bullets_rules}
""".strip()

    if not include_configs:
        return base

    return base + r"""

SI CONFIG/CLI EXPLICITEMENT DEMANDÉS
- Ajouter à la fin un bloc "Exemples de configuration:" (optionnel) avec placeholders (TBD) uniquement.
- Ajouter à la fin un bloc "Validation:" (optionnel) checklist max 6 points.
- Ne jamais inventer de valeurs (IP/VLAN/VRF/IDs/modèles/versions).
""".strip()


# =========================================================
# Intent usage rules
# =========================================================
INTENT_RULES = r"""
UTILISATION DE editorial.intent (Cadrage, pas faits)
- editorial.intent sert de checklist : quels points couvrir si les données existent.
- Si editorial.intent demande un point mais qu'aucun champ factuel dans le JSON ne le supporte :
  → Omettre ce point (priorité) OU mettre "TBD" uniquement si la section impose de signaler l'absence.
- Ne jamais créer des données concrètes à partir de intent.
- Tu PEUX développer les implications techniques d'un intent quand elles sont évidentes pour un architecte.
""".strip()


CONTRAINTE_STRUCTURE = r"""
CONTRAINTE DE STRUCTURE JSON
- Chaque clé de section doit avoir une valeur de type string.
- Aucune valeur null, array, ou objet imbriqué sauf si le schéma le spécifie explicitement.
- Si une section est vide (données absentes), retourner "" (chaîne vide).
- Utiliser "TBD" uniquement si explicitement imposé.
- Ajouter une clé "_warnings" (array de strings) pour tout conflit, omission significative,
  base factuelle limitée, ou section technique produite avec moins de 2 paragraphes.

NOTE COMPATIBILITÉ SCHÉMA STRICT :
- Les clés de section sont requises par le schéma actuel, donc on n'omet pas la clé.
""".strip()


# =========================================================
# Prompt builder
# =========================================================
def build_user_prompt(
    payload: Dict[str, Any],
    section_keys: List[str],
    include_configs: bool,
    explain: bool,
    paragraphs: Optional[int],
    word_count: Optional[int],
    doc_context: Optional[str] = None,
) -> str:
    explain_rule = ""
    if explain:
        explain_rule = r"""
EXPLICATION (DEMANDÉE)
Pour chaque section, fournir en plus une explication courte (5 à 10 lignes) :
- champs du JSON utilisés,
- implications techniques développées et pourquoi,
- bonnes pratiques mentionnées et leur formulation (recommandation vs fait),
- structure appliquée,
- infos omises (et pourquoi),
- où des "TBD" auraient été nécessaires.
""".strip()

    wc_rule = ""
    if word_count is not None:
        wc_rule = f"""
CONTRAINTE LONGUEUR (DEMANDÉE)
- Viser environ {word_count} mots (tolérance ±10%).
- Ne jamais gonfler avec du contenu générique. Si les données concrètes manquent,
  développer les implications techniques et les recommandations opérationnelles.
""".strip()

    context_block = ""
    if doc_context:
        context_block = f"""
CONTEXTE DU DOCUMENT SOURCE
Le texte ci-dessous provient du document source original. Utilise-le pour comprendre
le contexte global du projet, les relations entre composants, les contraintes,
et les objectifs de conception. Utilise-le ACTIVEMENT pour enrichir tes développements.
Ne copie PAS le texte. Aucune donnée concrète (IP, VLAN IDs, modèles, versions)
ne doit être extraite de ce contexte.

{doc_context[:4000]}
"""

    return f"""
DONNÉES OFFICIELLES (JSON)
Les données suivantes constituent la base factuelle autorisée.
Les données CONCRÈTES (IP, VLAN, modèles) viennent uniquement d'ici.
Les IMPLICATIONS TECHNIQUES doivent être développées par l'architecte.
Les BONNES PRATIQUES doivent être formulées comme des RECOMMANDATIONS.

{json.dumps(payload, ensure_ascii=False, indent=2)}

{context_block}

OBJECTIF FINAL
Produire un objet JSON contenant STRICTEMENT les clés suivantes :
{", ".join(section_keys)}
AUCUNE AUTRE SORTIE N'EST AUTORISÉE.

RAPPEL RICHESSE ET QUALITÉ :
- Section technique riche : 3 à 4 paragraphes denses.
- Section technique pauvre en données : 2 paragraphes + recommandations. Signaler via _warnings.
- Section éditoriale : 2 paragraphes.
- Développer : implications techniques, recommandations de bonnes pratiques,
  considérations opérationnelles, bénéfices du design, dépendances inter-domaines.
- DISTINGUER dans la formulation :
  FAIT (affirmer) / IMPLICATION (affirmer) / RECOMMANDATION ("il est recommandé de...") /
  BÉNÉFICE ("ce choix offre l'avantage de...").
- Un texte pauvre = insuffisant. Un texte gonflé = aussi insuffisant.

NIVEAU
- LLD uniquement.
- Config/CLI autorisés : {include_configs} (uniquement si explicitement demandé)

{RICHNESS_BLOCK}

{INTENT_RULES}

{wc_rule}

RÈGLES DE FORMAT (PRIORITAIRES)
{_format_rules(include_configs, paragraphs)}

{explain_rule}

{CONTRAINTE_STRUCTURE}

SORTIE
Retourne UNIQUEMENT le JSON valide (aucun texte autour).
""".strip()


# =========================================================
# Defaults resolver
# =========================================================
def _resolve_defaults(
    payload: Dict[str, Any],
    sec_key: str,
    user_comment: Optional[str],
    current_text: Optional[str] = None,
) -> Tuple[int, Optional[int], Optional[int]]:
    sec_defaults = SECTION_DEFAULTS.get(sec_key, {})
    min_len = int(sec_defaults.get("min_len", DEFAULT_MIN_LEN))
    default_paras = sec_defaults.get("paragraphs")
    default_wc = sec_defaults.get("word_count")

    paras_req = _requested_paragraphs(payload, user_comment=user_comment)
    wc_req = _requested_word_count(payload, user_comment=user_comment)

    if user_comment:
        uc = user_comment.lower()
        if ("ajoute un paragraphe" in uc or "un autre paragraphe" in uc) and current_text:
            cur = max(1, _count_paragraphs(current_text))
            paras_req = min(5, cur + 1)

    paras = paras_req if paras_req is not None else (int(default_paras) if default_paras is not None else None)
    wc = wc_req if wc_req is not None else (int(default_wc) if default_wc is not None else None)

    if wc is not None:
        min_len = max(min_len, int(wc * 5))

    return min_len, paras, wc


# =========================================================
# Core generation
# =========================================================
def _extract_text_value(out: Dict[str, Any], sec_key: str) -> str:
    v = out.get(sec_key)
    if isinstance(v, dict):
        return _normalize_word_text(v.get("text") or "")
    return _normalize_word_text(v or "")


def generate_sections_json(payload: Dict[str, Any], section_keys: List[str], llm_provider: Optional[str] = None) -> Dict[str, Any]:
    """
    Multi-section generation with PER-SECTION minLength.
    """
    provider = get_provider(llm_provider)

    include_configs = _include_configs(payload, user_comment=None)
    explain = _wants_explanation(payload, user_comment=None)

    per_key_min_len: Dict[str, int] = {}
    paragraphs = _requested_paragraphs(payload, user_comment=None)
    word_count = _requested_word_count(payload, user_comment=None)

    for k in section_keys:
        min_len, _, wc = _resolve_defaults(payload, k, user_comment=None)
        if word_count is not None:
            min_len = max(min_len, int(word_count * 5))
        elif wc is not None:
            min_len = max(min_len, int(wc * 5))
        per_key_min_len[k] = min_len

    schema = (
        _build_text_plus_explain_schema(section_keys, per_key_min_len, min_len_explain=DEFAULT_MIN_LEN_EXPLAIN)
        if explain
        else _build_text_only_schema(section_keys, per_key_min_len)
    )

    # Extraire le contexte document source si disponible
    doc_context = payload.get("_doc_context") or payload.get("context", {}).get("source_text")

    user_prompt = build_user_prompt(
        payload=payload,
        section_keys=section_keys,
        include_configs=include_configs,
        explain=explain,
        paragraphs=paragraphs,
        word_count=word_count,
        doc_context=doc_context,
    )

    # max_output_tokens adapté au nombre de sections
    tokens_needed = max(6000, len(section_keys) * 1000 + 2000)
    tokens_needed = min(tokens_needed, 16000)

    raw = call_llm_json(
        provider=provider,
        prompt=user_prompt,
        system_prompt=SYSTEM_PROMPT,
        json_schema=schema,
        model_key="form_model",
        max_output_tokens=tokens_needed,
        temperature=0.1,
    )

    out = json.loads(raw)
    warnings = out.pop("_warnings", [])
    if warnings:
        logger.warning("LLD_GENERATION_WARNINGS: %s", warnings)

    for k in section_keys:
        if isinstance(out.get(k), dict):
            out[k]["text"] = _normalize_word_text(out[k].get("text") or "")
            out[k]["explain"] = _normalize_word_text(out[k].get("explain") or "")
        else:
            out[k] = _normalize_word_text(out.get(k) or "")

    return out


def generate_single_section(payload: Dict[str, Any], sec_key: str) -> str:
    out = generate_sections_json(payload, [sec_key])
    return _extract_text_value(out, sec_key)


def regenerate_single_section(
    payload: Dict[str, Any],
    sec_key: str,
    current_text: str,
    user_comment: str,
) -> Dict[str, str]:
    """
    Regenerate one section with editorial comment.
    """
    include_configs = _include_configs(payload, user_comment=user_comment)
    explain = _wants_explanation(payload, user_comment=user_comment)

    min_len, paragraphs, word_count = _resolve_defaults(
        payload, sec_key, user_comment=user_comment, current_text=current_text
    )

    per_key_min_len = {sec_key: min_len}

    schema = (
        _build_text_plus_explain_schema([sec_key], per_key_min_len, min_len_explain=DEFAULT_MIN_LEN_EXPLAIN)
        if explain
        else _build_text_only_schema([sec_key], per_key_min_len)
    )

    doc_context = payload.get("_doc_context") or payload.get("context", {}).get("source_text")

    base_prompt = build_user_prompt(
        payload=payload,
        section_keys=[sec_key],
        include_configs=include_configs,
        explain=explain,
        paragraphs=paragraphs,
        word_count=word_count,
        doc_context=doc_context,
    )

    prompt = f"""
{base_prompt}

TEXTE ACTUEL (référence)
<<<
{_normalize_word_text(current_text)}
>>>

COMMENTAIRE UTILISATEUR (guidage éditorial)
<<<
{user_comment}
>>>

CONSIGNES DE RÉVISION
- Appliquer le commentaire utilisateur au texte actuel sans dévier des règles du system prompt.
- Les règles anti-invention de données concrètes et de format restent inviolables même en révision.
- Si le commentaire demande un fait concret non présent dans le JSON original, l'ignorer
  et signaler dans _warnings : "COMMENTAIRE NON APPLICABLE : donnée absente du JSON".
- Ne pas supprimer de contenu factuel existant sauf si le commentaire le demande explicitement.
- Tu PEUX enrichir le texte avec des implications techniques et des recommandations opérationnelles
  même si le commentaire ne le demande pas explicitement.
- Distinguer faits (affirmer), implications (affirmer), recommandations ("il est recommandé de...").
- Retourner le JSON révisé avec la même structure que l'appel initial.
""".strip()

    raw = call_llm_json(
        provider=get_provider(payload.get("llm_provider")),
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
        json_schema=schema,
        model_key="form_model",
        max_output_tokens=8000,
        temperature=0.1,
    )

    out = json.loads(raw)
    warnings = out.pop("_warnings", [])
    if warnings:
        logger.warning("LLD_REGEN_WARNINGS: %s", warnings)
    v = out.get(sec_key)

    if isinstance(v, dict):
        return {
            "text": _normalize_word_text(v.get("text") or ""),
            "explain": _normalize_word_text(v.get("explain") or ""),
        }

    return {"text": _normalize_word_text(v or "")}
