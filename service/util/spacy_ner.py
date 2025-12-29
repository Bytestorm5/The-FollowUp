from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote, urljoin, urlparse

import requests
import spacy


# -----------------------------
# Wikipedia resolver
# -----------------------------

WIKI_SEARCH_URL = "https://en.wikipedia.org/w/index.php?search={q}&title=Special:Search&wprov=acrw1_-1"
WIKI_BASE = "https://en.wikipedia.org"


@lru_cache(maxsize=4096)
def wikipedia_redirect_target(entity_text: str, *, timeout_s: float = 5.0) -> Optional[str]:
    """
    Return canonical Wikipedia page URL if the search request redirects to /wiki/...
    Otherwise return None.
    """
    q = quote(entity_text.strip())    
    url = WIKI_SEARCH_URL.format(q=q)
    
    
    # We want to detect the redirect itself.
    r = requests.get(
        url,
        allow_redirects=False,
        timeout=timeout_s,
        headers={
            # Helps avoid occasional weirdness with very minimal UAs.
            "User-Agent": "spacy-ner-wiki-linker/1.0"
        },
    )

    if not (300 <= r.status_code < 400):
        
        return None

    loc = r.headers.get("Location")
    if not loc:
        
        return None

    target = urljoin(WIKI_BASE, loc)
    parsed = urlparse(target)

    # # Must be a direct article path: /wiki/...
    # if not parsed.path.startswith("/wiki/"):
    #     
    #     
    #     
    #     return None

    # # Exclude Special pages (e.g., /wiki/Special:Search)
    # if parsed.path.startswith("/wiki/Special:"):
    #     
    #     
    #     
    #     return None
    
    return target


# -----------------------------
# Markdown safety: protect regions we should NOT edit
# -----------------------------

FENCE_RE = re.compile(r"(?m)^(?P<fence>`{3,}|~{3,})[^\n]*\n")  # opening fence on its own line


@dataclass
class Segment:
    text: str
    protected: bool  # if True, don't run NER / replacement here


LINK_RE = re.compile(r"\[[^\]]*\]\([^)]+\)")  # basic markdown link [text](url)
INLINE_CODE_RE = re.compile(r"`[^`]*`")       # basic inline code `...`


def split_fenced_code_blocks(md: str) -> List[Segment]:
    """
    Split markdown into segments, marking fenced code blocks as protected.
    Handles ```...``` and ~~~...~~~ fences (not nested).
    """
    out: List[Segment] = []
    i = 0
    while i < len(md):
        m = FENCE_RE.search(md, i)
        if not m:
            out.append(Segment(md[i:], protected=False))
            break

        # text before fence
        if m.start() > i:
            out.append(Segment(md[i:m.start()], protected=False))

        fence = m.group("fence")
        # Find closing fence: same fence chars at line start
        close_re = re.compile(rf"(?m)^{re.escape(fence)}[^\n]*\n?")
        close_m = close_re.search(md, m.end())
        if not close_m:
            # Unclosed fence: treat rest as protected
            out.append(Segment(md[m.start():], protected=True))
            break

        block_end = close_m.end()
        out.append(Segment(md[m.start():block_end], protected=True))
        i = block_end

    return out


def split_inline_code_and_links(seg: Segment) -> List[Segment]:
    """
    Further split an unprotected segment by inline code and existing markdown links,
    marking those as protected.
    """
    if seg.protected:
        return [seg]

    text = seg.text
    spans: List[Tuple[int, int]] = []

    for m in LINK_RE.finditer(text):
        spans.append((m.start(), m.end()))
    for m in INLINE_CODE_RE.finditer(text):
        spans.append((m.start(), m.end()))

    if not spans:
        return [seg]

    # Merge overlapping spans
    spans.sort()
    merged: List[Tuple[int, int]] = []
    for s, e in spans:
        if not merged or s > merged[-1][1]:
            merged.append((s, e))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))

    out: List[Segment] = []
    cur = 0
    for s, e in merged:
        if s > cur:
            out.append(Segment(text[cur:s], protected=False))
        out.append(Segment(text[s:e], protected=True))
        cur = e
    if cur < len(text):
        out.append(Segment(text[cur:], protected=False))
    return out


def split_markdown(md: str) -> List[Segment]:
    segs = split_fenced_code_blocks(md)
    out: List[Segment] = []
    for s in segs:
        out.extend(split_inline_code_and_links(s))
    return out


# -----------------------------
# Entity replacement
# -----------------------------

DEFAULT_ENTITY_LABELS = {
    # "PERSON",
    # "ORG",
    "GPE",
    "LOC",
    "PRODUCT",
    "EVENT",
    "WORK_OF_ART",
    # "LAW",
    "NORP",
    "FAC",
}


def escape_md_link_text(s: str) -> str:
    # Minimal escaping for markdown link labels.
    return s.replace("\\", "\\\\").replace("]", r"\]")


def normalize_term(t: str) -> str:
    # Normalize to treat "Barack Obama" == "barack  obama"
    return re.sub(r"\s+", " ", t.strip()).casefold()


def insert_links_for_entities(
    text: str,
    *,
    nlp,
    resolve_url: Callable[[str], Optional[str]],
    seen_terms: set[str],                      # <-- NEW: global state passed in
    allowed_labels: Optional[set] = None,
) -> str:
    """
    Run spaCy NER on plain text and insert markdown links for entities.
    Only the FIRST occurrence of each term (across the whole document) is processed.
    """
    allowed = allowed_labels or DEFAULT_ENTITY_LABELS
    doc = nlp(text)

    # 1) Collect earliest occurrence per normalized term (within THIS segment)
    earliest_by_term: dict[str, Tuple[int, int, str]] = {}  # term_key -> (start, end, raw_text)
    for ent in doc.ents:
        if ent.label_ not in allowed:
            continue

        raw = ent.text.strip()
        if len(raw) < 2:
            continue

        key = normalize_term(raw)

        # If we've already seen this term anywhere earlier in the doc, skip entirely
        if key in seen_terms:
            continue

        # Keep the earliest span for this term in this segment
        prev = earliest_by_term.get(key)
        if prev is None or ent.start_char < prev[0]:
            earliest_by_term[key] = (ent.start_char, ent.end_char, raw)

    if not earliest_by_term:
        return text

    # 2) Replace from right-to-left (safe for offsets)
    spans = sorted(earliest_by_term.items(), key=lambda kv: kv[1][0], reverse=True)

    out = text
    for key, (start, end, raw) in spans:
        # Attempt only on first occurrence (and mark seen no matter what)
        seen_terms.add(key)

        # Avoid linking if it's already inside markdown link syntax (extra guard)
        if start > 0 and out[start - 1] == "[":
            continue

        url = resolve_url(raw)
        if not url:
            continue

        label = escape_md_link_text(out[start:end])
        out = out[:start] + f"[{label}]({url})" + out[end:]

    return out

NLP = spacy.load("en_core_web_sm")
def link_named_entities_in_markdown(
    md: str,
    *,
    nlp=NLP,
    resolve_url: Callable[[str], Optional[str]] = wikipedia_redirect_target,
    allowed_labels: Optional[set] = None,
) -> str:
    """
    Main entry point: keeps Markdown structure safe, links entities in non-protected text.
    Links only the first occurrence of each term across the entire markdown.
    """
    segs = split_markdown(md)
    out_parts: List[str] = []

    seen_terms: set[str] = set()  # <-- NEW: global "already processed" terms

    for seg in segs:
        if seg.protected:
            out_parts.append(seg.text)
        else:
            out_parts.append(
                insert_links_for_entities(
                    seg.text,
                    nlp=nlp,
                    resolve_url=resolve_url,
                    allowed_labels=allowed_labels,
                    seen_terms=seen_terms,   # <-- pass global tracker
                )
            )

    return "".join(out_parts)


def extract_entity_counts(
    md: str,
    *,
    nlp=NLP,
    allowed_labels: Optional[set] = None,
) -> dict[str, int]:
    """
    Return a mapping of entity text -> occurrence count using spaCy NER.

    The markdown is lightly cleaned to drop link syntax while keeping the text.
    Entity keys are taken from the first occurrence of each normalized term.
    Results are sorted by descending count for stability.
    """
    allowed = allowed_labels or (DEFAULT_ENTITY_LABELS | {"ORG"})
    text = md or ""
    # Strip markdown link syntax while retaining the visible text.
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`+", " ", text)

    doc = nlp(text)
    counts: dict[str, tuple[str, int]] = {}
    for ent in doc.ents:
        if ent.label_ not in allowed:
            continue
        raw = ent.text.strip()
        if len(raw) < 2:
            continue
        key = normalize_term(raw)
        if not key:
            continue
        display, prev_count = counts.get(key, (raw, 0))
        counts[key] = (display, prev_count + 1)

    # Collapse to display text -> count, sorted for determinism
    out: dict[str, int] = {display: c for display, c in counts.values()}
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0].casefold())))
