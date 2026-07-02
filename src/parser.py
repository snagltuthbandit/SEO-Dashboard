"""Mention detection + scoring for AI citation tracking.

Approximate by design — this is a naive text-matching + keyword-proximity
heuristic, not an NLU classifier. Spot-check parser output against raw
responses before trusting the dashboard (see README "Known limitations").
"""
import re
from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

RECOMMENDATION_PHRASES = [
    "recommend",
    "consider",
    "top choice",
    "best option",
    "i'd suggest",
    "i would suggest",
    "top pick",
    "great choice",
    "worth considering",
    "strongly suggest",
]

RECOMMENDATION_PROXIMITY_CHARS = 50


def load_entities(competitors_path: Path = None) -> list:
    """Merge brand + competitors from config/competitors.yaml into one
    uniform list: [{name, aliases, domain, is_brand}, ...]."""
    path = competitors_path or (CONFIG_DIR / "competitors.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f)

    entities = []
    brand = cfg["brand"]
    entities.append(
        {
            "name": brand["name"],
            "aliases": brand.get("aliases", []),
            "domain": brand.get("domain", ""),
            "is_brand": True,
        }
    )
    for comp in cfg.get("competitors", []):
        entities.append(
            {
                "name": comp["name"],
                "aliases": comp.get("aliases", []),
                "domain": comp.get("domain", ""),
                "is_brand": False,
            }
        )
    return entities


def load_prompts(prompts_path: Path = None) -> list:
    path = prompts_path or (CONFIG_DIR / "prompts.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return cfg["prompts"]


def _search_terms(entity: dict) -> list:
    terms = [entity["name"]] + list(entity.get("aliases", []))
    if entity.get("domain"):
        terms.append(entity["domain"])
    return [t for t in terms if t]


def _find_all_spans(text: str, term: str) -> list:
    """Word-boundary, case-insensitive occurrences of `term` in `text`,
    as (start, end) spans."""
    pattern = r"\b" + re.escape(term) + r"\b"
    return [m.span() for m in re.finditer(pattern, text, flags=re.IGNORECASE)]


def _merge_spans(spans: list) -> list:
    """Merge overlapping spans so e.g. 'Alabama' and 'University of Alabama'
    matching the same text don't get double-counted as two mentions."""
    if not spans:
        return []
    spans = sorted(spans)
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _position_for_offset(offset: int, text_len: int) -> str:
    """Bucket a character offset into a position label.

    'first' = the mention lands in the opening ~10% of the response (i.e.
    the model named it essentially immediately). Otherwise fall back to
    thirds-of-response as specified in the build brief.
    """
    if text_len == 0:
        return "not_mentioned"
    if offset < text_len * 0.10:
        return "first"
    third = text_len / 3
    if offset < third:
        return "early"
    if offset < third * 2:
        return "mid"
    return "late"


def _is_recommended(text: str, mention_offsets: list) -> bool:
    if not mention_offsets:
        return False
    rec_offsets = []
    for phrase in RECOMMENDATION_PHRASES:
        rec_offsets.extend(start for start, _end in _find_all_spans(text, phrase))
    if not rec_offsets:
        return False
    for m_off in mention_offsets:
        for r_off in rec_offsets:
            if abs(m_off - r_off) <= RECOMMENDATION_PROXIMITY_CHARS:
                return True
    return False


def _citation_position(domain: str, citations: list) -> str:
    for idx, url in enumerate(citations):
        if domain and domain.lower() in url.lower():
            if idx == 0:
                return "first"
            ratio = idx / max(len(citations) - 1, 1)
            if ratio < 0.34:
                return "early"
            if ratio < 0.67:
                return "mid"
            return "late"
    return "not_mentioned"


def _attribute_spans(text: str, entities: list) -> dict:
    """Assign each matched text region to exactly one entity, longest match
    wins.

    Ambiguous aliases like "Alabama" match inside more specific names
    ("University of North Alabama", "University of Alabama in Huntsville").
    Without this, the brand's own name inflates a competitor's count. We
    collect every (entity, term) match, then greedily claim regions
    longest-first so the most specific name owns the text and no character
    range is counted twice.

    Returns {entity_index: [sorted (start, end) spans]}.
    """
    matches = []  # (start, end, entity_idx, term_len)
    for idx, entity in enumerate(entities):
        for term in _search_terms(entity):
            for start, end in _find_all_spans(text, term):
                matches.append((start, end, idx, len(term)))

    # Longest term first; on ties, earlier position. Then claim greedily,
    # skipping any match overlapping already-claimed text.
    matches.sort(key=lambda m: (-m[3], m[0]))
    claimed = []  # (start, end) already attributed
    by_entity = {i: [] for i in range(len(entities))}
    for start, end, idx, _len in matches:
        if any(start < c_end and end > c_start for c_start, c_end in claimed):
            continue
        claimed.append((start, end))
        by_entity[idx].append((start, end))

    for idx in by_entity:
        by_entity[idx].sort()
    return by_entity


def analyze(raw_response: str, entities: list, citations: list = None) -> list:
    """Return one mention record per entity:
    {entity_name, mentioned, position, is_recommended, mention_count}
    """
    text = raw_response or ""
    text_len = len(text)
    results = []

    attributed = _attribute_spans(text, entities)

    for idx, entity in enumerate(entities):
        merged_spans = attributed[idx]
        all_offsets = [start for start, _end in merged_spans]

        mention_count = len(merged_spans)
        mentioned = mention_count > 0
        position = (
            _position_for_offset(all_offsets[0], text_len)
            if mentioned
            else "not_mentioned"
        )
        is_recommended = _is_recommended(text, all_offsets)

        # Perplexity citations cross-check: a domain hit in the citations
        # array is a stronger signal than a text mention (the model
        # actually pulled from the site) — surface it even if the plain-
        # text search missed it.
        if citations and entity.get("domain"):
            cited = any(
                entity["domain"].lower() in url.lower() for url in citations
            )
            if cited and not mentioned:
                mentioned = True
                mention_count = max(mention_count, 1)
                position = _citation_position(entity["domain"], citations)

        results.append(
            {
                "entity_name": entity["name"],
                "mentioned": int(mentioned),
                "position": position,
                "is_recommended": int(is_recommended),
                "mention_count": mention_count,
            }
        )

    return results
