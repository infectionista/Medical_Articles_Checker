#!/usr/bin/env python3
"""
Enhanced Checklist Checker with Context-Aware Matching

Key improvements over the original checklist_applier.py:
1. Section-aware matching: keywords are checked in expected article sections,
   not just anywhere in the text.
2. Weighted scoring: each checklist item has a weight; keyword match depth
   (how many keywords matched) contributes to the score.
3. Confidence levels: instead of binary found/not found, returns a confidence
   score per item (0.0 – 1.0).
4. Phrase matching: supports multi-word phrases and regex patterns, not just
   single-word boundary matching.
5. Negative evidence: detects explicit statements of absence (e.g.,
   "no blinding was performed") and adjusts scoring.
"""

import json
import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# Auto-load .env file if present (keeps API key out of code)
_env_path = Path(__file__).resolve().parent / '.env'
if _env_path.exists():
    # Read with utf-8-sig to auto-strip BOM if present
    for line in _env_path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, _, value = line.partition('=')
            key = key.strip()
            value = value.strip().strip('"').strip("'")  # Remove quotes
            # Sanitize: keep only printable ASCII (0x20-0x7E)
            # This strips invisible Unicode (zero-width spaces, BOM, etc.)
            # that break Python http.client's latin-1 header encoding
            value = ''.join(c for c in value if 32 <= ord(c) <= 126)
            # Always override: .env file takes priority over system env
            # (setdefault would silently ignore .env if a stale/wrong
            # value was already exported in the shell)
            os.environ[key] = value

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

from section_parser import SectionParser, ArticleSection, get_expected_sections

logger = logging.getLogger(__name__)


def normalize_pdf_text(text: str) -> str:
    """Normalize text extracted from PDF: fix ligatures, collapse whitespace."""
    # Fix common PDF ligatures
    ligatures = {
        '\ufb01': 'fi', '\ufb02': 'fl', '\ufb00': 'ff',
        '\ufb03': 'ffi', '\ufb04': 'ffl',
        '\u0131': 'i',  # dotless i
    }
    for lig, replacement in ligatures.items():
        text = text.replace(lig, replacement)
    # Collapse multiple spaces into one
    text = re.sub(r'  +', ' ', text)
    # Fix hyphenated line breaks (e.g., "ran-\ndomized" -> "randomized")
    text = re.sub(r'(\w)-\s*\n\s*(\w)', r'\1\2', text)
    return text


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ItemScore:
    """Result of evaluating a single checklist item."""
    item_id: str
    section: str
    description: str
    confidence: float             # 0.0 – 1.0
    verdict: str                  # "present", "partial", "absent", "explicitly_absent"
    matched_keywords: List[str]
    matched_in_sections: List[str]
    total_keywords: int
    keyword_match_ratio: float    # fraction of keywords matched
    section_match: bool           # were keywords found in the expected section?
    weight: float                 # item weight for aggregate scoring
    evidence_snippets: List[str]  # short text excerpts showing matches


@dataclass
class CheckResult:
    """Result of evaluating an entire checklist."""
    checklist_name: str
    checklist_full_name: str
    description: str
    total_items: int
    weighted_score: float         # 0–100 weighted compliance
    simple_score: float           # 0–100 binary (present vs absent)
    items: List[ItemScore]
    section_coverage: Dict[str, float]  # per-section compliance

    @property
    def present_count(self) -> int:
        return sum(1 for i in self.items if i.verdict == 'present')

    @property
    def partial_count(self) -> int:
        return sum(1 for i in self.items if i.verdict == 'partial')

    @property
    def absent_count(self) -> int:
        return sum(1 for i in self.items if i.verdict in ('absent', 'explicitly_absent'))

    @property
    def grade(self) -> str:
        """Letter grade based on weighted score."""
        s = self.weighted_score
        if s >= 80:
            return 'A'
        elif s >= 65:
            return 'B'
        elif s >= 50:
            return 'C'
        elif s >= 35:
            return 'D'
        else:
            return 'F'

    @property
    def grade_label(self) -> str:
        """Human-readable quality label."""
        labels = {
            'A': 'Excellent reporting quality',
            'B': 'Good reporting quality',
            'C': 'Acceptable, but significant gaps',
            'D': 'Poor reporting quality',
            'F': 'Very poor — major items missing',
        }
        return labels[self.grade]

    def summary(self, study_type: str = '', detected_checklist: str = '') -> dict:
        """Generate a standardized summary for the article quality assessment."""
        # Strongest items
        strong = [i for i in self.items if i.verdict == 'present']
        strong.sort(key=lambda x: -x.confidence)

        # Critical missing items (high weight, absent)
        critical_missing = [
            i for i in self.items
            if i.verdict in ('absent', 'explicitly_absent') and i.weight >= 1.1
        ]

        # Partially met items
        partial = [i for i in self.items if i.verdict == 'partial']

        return {
            'checklist': self.checklist_name,
            'study_type': study_type,
            'total_items': self.total_items,
            'weighted_score': round(self.weighted_score, 1),
            'grade': self.grade,
            'grade_label': self.grade_label,
            'present': self.present_count,
            'partial': self.partial_count,
            'absent': self.absent_count,
            'section_coverage': {k: round(v, 1) for k, v in self.section_coverage.items()},
            'strong_items': [
                {'id': i.item_id, 'desc': i.description, 'confidence': round(i.confidence, 2)}
                for i in strong[:5]
            ],
            'critical_missing': [
                {'id': i.item_id, 'desc': i.description, 'weight': i.weight, 'section': i.section}
                for i in critical_missing
            ],
            'partial_items': [
                {'id': i.item_id, 'desc': i.description, 'confidence': round(i.confidence, 2)}
                for i in partial
            ],
        }


# ---------------------------------------------------------------------------
# Negative evidence patterns
# ---------------------------------------------------------------------------

NEGATIVE_PATTERNS = [
    r'(?i)\bno\s+{kw}\b',
    r'(?i)\bnot\s+(?:\w+\s+){{0,2}}{kw}',
    r'(?i)\bwithout\s+{kw}',
    r'(?i)\b{kw}\s+was\s+not\s+(?:done|performed|used|applied|reported|conducted|obtained|provided)',
    r'(?i)\b{kw}\s+(?:were|was)\s+not\s+(?:available|possible|required|sought|described|mentioned)',
    r'(?i)\black(?:ed|ing)?\s+(?:of\s+)?(?:any\s+)?{kw}',
    r'(?i)\babsence\s+of\s+{kw}',
    r'(?i)\bno\s+(?:formal|explicit|documented|clear)\s+{kw}',
    r'(?i)\b{kw}\s+(?:is|are|was|were)\s+not\s+(?:clearly\s+)?(?:stated|specified|reported|described|addressed)',
    r'(?i)\bfailed\s+to\s+(?:report|describe|mention|specify|provide|document)\s+{kw}',
    r'(?i)\bdid\s+not\s+(?:report|describe|mention|specify|provide|address|include)\s+{kw}',
    r'(?i)\bomit(?:ted|s)?\s+{kw}',
]

# ---------------------------------------------------------------------------
# Critical methodological elements that retracted/fraudulent papers often omit.
# These are checked as "mandatory lacunae" — if absent, the system flags them
# with higher severity. Used by _check_critical_lacunae().
# ---------------------------------------------------------------------------
CRITICAL_LACUNAE = {
    'CONSORT': [
        ('ethics approval', [
            r'(?i)\b(?:ethics?\s+(?:committee|board|approval|review)|IRB\s+approv|'
            r'institutional\s+review\s+board|(?:local|regional)\s+ethics)',
        ]),
        ('trial registration', [
            r'(?i)\b(?:NCT\d{5,}|ISRCTN\d+|ACTRN\d+|clinicaltrials\.gov|'
            r'trial\s+regist(?:ration|ered|ry))',
        ]),
        ('informed consent', [
            r'(?i)\b(?:informed\s+consent|written\s+consent|consent\s+(?:was\s+)?obtained|'
            r'participants?\s+(?:provided|gave)\s+(?:written\s+)?consent)',
        ]),
    ],
    'STROBE': [
        ('ethics approval', [
            r'(?i)\b(?:ethics?\s+(?:committee|board|approval|review)|IRB\s+approv|'
            r'institutional\s+review\s+board)',
        ]),
        ('informed consent', [
            r'(?i)\b(?:informed\s+consent|written\s+consent|consent\s+(?:was\s+)?obtained)',
        ]),
    ],
    'JBI_CASE_SERIES': [
        ('ethics approval', [
            r'(?i)\b(?:ethics?\s+(?:committee|board|approval)|IRB\s+approv)',
        ]),
        ('informed consent', [
            r'(?i)\b(?:informed\s+consent|patient\s+consent|consent\s+(?:was\s+)?obtained)',
        ]),
    ],
    'STARD': [
        ('ethics approval', [
            r'(?i)\b(?:ethics?\s+(?:committee|board|approval|review)|IRB\s+approv|'
            r'institutional\s+review\s+board)',
        ]),
        ('informed consent', [
            r'(?i)\b(?:informed\s+consent|written\s+consent|consent\s+(?:was\s+)?obtained)',
        ]),
        ('study registration', [
            r'(?i)\b(?:registered|PROSPERO|ClinicalTrials\.gov|NCT\d{5,}|'
            r'study\s+regist(?:ration|ered|ry))',
        ]),
    ],
    'CARE': [
        ('informed consent', [
            r'(?i)\b(?:informed\s+consent|consent\s+(?:was\s+)?obtained|'
            r'consent\s+for\s+publication|patient\s+consent(?:ed)?|'
            r'written\s+consent)',
        ]),
        ('ethics approval', [
            r'(?i)\b(?:ethics?\s+(?:committee|board|approval)|IRB\s+approv)',
        ]),
    ],
    'TREND': [
        ('ethics approval', [
            r'(?i)\b(?:ethics?\s+(?:committee|board|approval|review)|IRB\s+approv|'
            r'institutional\s+review\s+board)',
        ]),
        ('informed consent', [
            r'(?i)\b(?:informed\s+consent|written\s+consent|consent\s+(?:was\s+)?obtained)',
        ]),
    ],
}


# ---------------------------------------------------------------------------
# Enhanced checker
# ---------------------------------------------------------------------------

class EnhancedChecker:
    """
    Context-aware, weighted checklist evaluator.
    """

    def __init__(self, checklist_dir: str = "checklists"):
        self.checklist_dir = Path(checklist_dir)
        self.checklists: Dict[str, dict] = {}
        self.section_parser = SectionParser()
        self._load_checklists()

    # ----- loading -----

    def _load_checklists(self):
        if not self.checklist_dir.exists():
            raise FileNotFoundError(f"Checklist directory not found: {self.checklist_dir}")

        for path in self.checklist_dir.glob("*.json"):
            with open(path, 'r') as f:
                data = json.load(f)
            name = data['name']
            self.checklists[name] = data

    def list_checklists(self) -> List[str]:
        return list(self.checklists.keys())

    # ----- main API -----

    def check(
        self,
        article_text: str,
        checklist_name: str,
        *,
        sections: Optional[Dict[str, ArticleSection]] = None,
    ) -> CheckResult:
        """
        Evaluate an article against a checklist.

        Args:
            article_text: full text of the article
            checklist_name: which checklist to apply
            sections: pre-parsed sections (if None, will parse internally)

        Returns:
            CheckResult with per-item and aggregate scores.
        """
        if checklist_name not in self.checklists:
            raise ValueError(
                f"Unknown checklist '{checklist_name}'. "
                f"Available: {', '.join(self.list_checklists())}"
            )

        checklist = self.checklists[checklist_name]

        # Normalize PDF artifacts before parsing
        article_text = normalize_pdf_text(article_text)

        # Parse sections if not provided
        if sections is None:
            sections = self.section_parser.parse(article_text)

        # Evaluate each item (Phase 1 + 2 + 2.5: keywords + semantic)
        item_scores: List[ItemScore] = []
        for item_def in checklist['items']:
            score = self._evaluate_item(item_def, sections, article_text)
            item_scores.append(score)

        # --- Phase 3 (optional): LLM smart fallback ---
        # Only triggers when Phase 1+2 gave POOR results (>50% items absent).
        # This avoids expensive API calls for articles that already score well.
        absent_items = [
            (i, item_def) for i, (score, item_def)
            in enumerate(zip(item_scores, checklist['items']))
            if score.verdict == 'absent'
        ]
        absent_ratio = len(absent_items) / len(item_scores) if item_scores else 0

        if absent_items and absent_ratio > 0.50:
            api_key = os.environ.get('ANTHROPIC_API_KEY', '')
            if api_key:
                logger.info(
                    "Phase 3 LLM: %d/%d items absent (%.0f%%) — calling Haiku",
                    len(absent_items), len(item_scores), absent_ratio * 100,
                )
                items_to_check = [item_def for _, item_def in absent_items]
                llm_results = self._llm_evaluate_items(
                    items_to_check, article_text, checklist_name
                )
                for idx, item_def in absent_items:
                    item_id = item_def['item']
                    if item_id in llm_results:
                        is_present, evidence = llm_results[item_id]
                        if is_present:
                            old = item_scores[idx]
                            item_scores[idx] = ItemScore(
                                item_id=old.item_id,
                                section=old.section,
                                description=old.description,
                                confidence=0.55,
                                verdict='partial',
                                matched_keywords=old.matched_keywords,
                                matched_in_sections=old.matched_in_sections + ['LLM'],
                                total_keywords=old.total_keywords,
                                keyword_match_ratio=old.keyword_match_ratio,
                                section_match=old.section_match,
                                weight=old.weight,
                                evidence_snippets=(
                                    old.evidence_snippets + [f"[LLM] {evidence}"]
                                )[:4],
                            )

        # --- Critical lacunae detection (ethics, consent, registration) ---
        critical_lacunae = self._check_critical_lacunae(article_text, checklist_name)
        if critical_lacunae:
            logger.info(
                "Critical lacunae detected: %s",
                ', '.join(critical_lacunae),
            )

        # Aggregate scores
        total_weight = sum(s.weight for s in item_scores)
        weighted_score = 0.0
        if total_weight > 0:
            weighted_score = sum(s.confidence * s.weight for s in item_scores) / total_weight * 100

        simple_present = sum(1 for s in item_scores if s.verdict in ('present', 'partial'))
        simple_score = (simple_present / len(item_scores) * 100) if item_scores else 0

        # Per-section coverage
        section_groups: Dict[str, List[ItemScore]] = {}
        for s in item_scores:
            base_section = s.section.split(' - ')[0] if ' - ' in s.section else s.section
            section_groups.setdefault(base_section, []).append(s)

        section_coverage = {}
        for sec, items in section_groups.items():
            if items:
                section_coverage[sec] = sum(i.confidence for i in items) / len(items) * 100

        return CheckResult(
            checklist_name=checklist['name'],
            checklist_full_name=checklist['full_name'],
            description=checklist['description'],
            total_items=len(item_scores),
            weighted_score=round(weighted_score, 2),
            simple_score=round(simple_score, 2),
            items=item_scores,
            section_coverage=section_coverage,
        )

    # ----- per-item evaluation -----

    def _evaluate_item(
        self,
        item_def: dict,
        sections: Dict[str, ArticleSection],
        article_text: str = '',
    ) -> ItemScore:
        """Evaluate a single checklist item against parsed sections."""

        item_id = item_def['item']
        section_name = item_def['section']
        description = item_def['description']
        keywords = item_def.get('keywords', [])
        weight = item_def.get('weight', 1.0)

        # Determine which article sections to search in
        expected_sections = get_expected_sections(section_name)

        matched_keywords: List[str] = []
        matched_in_sections: List[str] = []
        evidence_snippets: List[str] = []
        section_match = False
        has_negative_evidence = False

        # --- Phase 1: Search in expected sections ---
        for sec_name in expected_sections:
            if sec_name not in sections:
                continue
            sec = sections[sec_name]
            sec_text = sec.text.lower()

            for kw in keywords:
                kw_lower = kw.lower()
                pattern = r'\b' + re.escape(kw_lower) + r'\b'

                match = re.search(pattern, sec_text)
                if match and kw not in matched_keywords:
                    matched_keywords.append(kw)
                    matched_in_sections.append(sec_name)
                    section_match = True

                    # Extract evidence snippet (±60 chars around match)
                    start = max(0, match.start() - 60)
                    end = min(len(sec_text), match.end() + 60)
                    snippet = '...' + sec_text[start:end].strip() + '...'
                    evidence_snippets.append(snippet)

            # Also check methods subsections
            if sec_name == 'methods' and sec.subsections:
                for sub in sec.subsections:
                    sub_text = sub.text.lower()
                    for kw in keywords:
                        kw_lower = kw.lower()
                        pattern = r'\b' + re.escape(kw_lower) + r'\b'
                        if re.search(pattern, sub_text) and kw not in matched_keywords:
                            matched_keywords.append(kw)
                            matched_in_sections.append(f"methods/{sub.name}")
                            section_match = True

        # --- Phase 2: Supplementary search in full text ---
        # Always search full text for additional keyword matches to boost
        # confidence, even if some keywords already matched in sections.
        if 'full_text' in sections:
            full_text = sections['full_text'].text.lower()
            for kw in keywords:
                if kw in matched_keywords:
                    continue  # Already found in a specific section
                kw_lower = kw.lower()
                pattern = r'\b' + re.escape(kw_lower) + r'\b'
                match = re.search(pattern, full_text)
                if match:
                    matched_keywords.append(kw)
                    matched_in_sections.append('full_text (supplement)')

                    start = max(0, match.start() - 60)
                    end = min(len(full_text), match.end() + 60)
                    snippet = '...' + full_text[start:end].strip() + '...'
                    evidence_snippets.append(snippet)

        # --- Phase 2.5: TF-IDF Semantic Matching (ambiguity resolution) ---
        # Activate when keyword matching found few/no matches — the item
        # *might* be present but described with different wording.
        semantic_boost = 0.0
        keyword_match_ratio_raw = len(matched_keywords) / len(keywords) if keywords else 0
        if HAS_SKLEARN and keyword_match_ratio_raw < 0.25 and article_text:
            sem_score, sem_snippet = self._semantic_match(description, article_text)
            if sem_score >= 0.12:
                # Scale boost: 0.12→small boost, 0.25+→strong boost
                semantic_boost = min(sem_score * 1.8, 0.35)
                if sem_snippet and sem_snippet not in evidence_snippets:
                    evidence_snippets.append(f"[semantic] {sem_snippet}")
                if not matched_in_sections:
                    matched_in_sections.append('full_text (semantic)')
                logger.debug(
                    "Semantic match for %s: score=%.3f, boost=%.3f",
                    item_id, sem_score, semantic_boost,
                )

        # --- Phase 3: Check for negative evidence ---
        if 'full_text' in sections:
            full_text = sections['full_text'].text
            has_negative_evidence = self._check_negative_evidence(keywords, full_text)

        # --- Compute confidence ---
        keyword_match_ratio = len(matched_keywords) / len(keywords) if keywords else 0

        confidence = self._compute_confidence(
            keyword_match_ratio=keyword_match_ratio,
            section_match=section_match,
            has_negative_evidence=has_negative_evidence,
            num_keywords_matched=len(matched_keywords),
            total_keywords=len(keywords),
        )

        # Apply semantic boost on top of keyword confidence
        if semantic_boost > 0:
            confidence = min(confidence + semantic_boost, 0.85)  # Cap at 0.85

        # --- Determine verdict ---
        if has_negative_evidence and keyword_match_ratio < 0.3:
            verdict = 'explicitly_absent'
        elif confidence >= 0.6:
            verdict = 'present'
        elif confidence >= 0.25:
            verdict = 'partial'
        else:
            verdict = 'absent'

        return ItemScore(
            item_id=item_id,
            section=section_name,
            description=description,
            confidence=round(confidence, 3),
            verdict=verdict,
            matched_keywords=matched_keywords,
            matched_in_sections=matched_in_sections,
            total_keywords=len(keywords),
            keyword_match_ratio=round(keyword_match_ratio, 3),
            section_match=section_match,
            weight=weight,
            evidence_snippets=evidence_snippets[:3],  # Limit to 3 snippets
        )

    def _compute_confidence(
        self,
        keyword_match_ratio: float,
        section_match: bool,
        has_negative_evidence: bool,
        num_keywords_matched: int,
        total_keywords: int,
    ) -> float:
        """
        Compute a confidence score (0.0 – 1.0) for an item being present.

        The key insight: our upgraded checklists use *specific compound phrases*
        (e.g., "primary outcome", "allocation concealment") — matching even one
        such phrase in the correct section is strong evidence. This is different
        from the old checker where "background" or "results" could match anywhere.

        Factors:
        - keyword_match_ratio: raw fraction of keywords found
        - section_match: keywords found in the expected article section
        - compound keyword bonus: multi-word keywords are inherently more specific
        - negative evidence penalty
        """
        if total_keywords == 0:
            return 0.0

        # Base: keyword ratio — but we set a floor for section-matched items
        base = keyword_match_ratio

        # Section bonus: finding keywords in the expected section is much
        # more meaningful than finding them in a random place
        if section_match:
            # For section-matched items, even 1 keyword is meaningful evidence
            # because our keywords are specific compound phrases
            base = max(base, 0.35)  # Floor: at least 0.35 if in right section
            base += 0.20
        elif num_keywords_matched > 0:
            # Found in full_text fallback only — lower confidence
            base *= 0.7

        # Multiple keyword confirmation bonus
        if num_keywords_matched >= 3:
            base = min(base + 0.15, 1.0)  # Strong evidence with 3+ matches
        elif num_keywords_matched >= 2:
            base = min(base + 0.08, 1.0)  # Moderate boost for 2 matches

        # Single generic keyword penalty — only if the keyword is short (1 word)
        # Compound phrases (2+ words) are specific enough on their own
        if num_keywords_matched == 1 and total_keywords >= 5:
            # Check if the matched keyword is a compound phrase
            # (compound phrases are strong even alone)
            pass  # No penalty for compound phrases, handled by section_match floor

        # Negative evidence penalty
        if has_negative_evidence:
            base -= 0.3

        return max(0.0, min(1.0, base))

    def _check_negative_evidence(self, keywords: List[str], text: str) -> bool:
        """Check if the article explicitly states absence of a checklist item."""
        for kw in keywords[:5]:  # Check first 5 keywords
            kw_escaped = re.escape(kw.lower())
            for neg_pattern_template in NEGATIVE_PATTERNS:
                try:
                    neg_pattern = neg_pattern_template.format(kw=kw_escaped)
                    if re.search(neg_pattern, text, re.IGNORECASE):
                        return True
                except (re.error, KeyError, IndexError):
                    continue
        return False

    def _check_critical_lacunae(
        self, article_text: str, checklist_name: str,
    ) -> List[str]:
        """
        Detect critical methodological omissions (lacunae).

        Retracted/fraudulent papers often omit ethics approval, trial
        registration, and informed consent — or replace them with vague
        wording. This method scans for the PRESENCE of these mandatory
        elements and returns a list of those that are MISSING.

        Returns:
            List of lacuna labels (e.g., ['ethics approval', 'informed consent'])
        """
        lacunae_defs = CRITICAL_LACUNAE.get(checklist_name, [])
        if not lacunae_defs:
            return []

        missing = []
        for label, patterns in lacunae_defs:
            found = False
            for pat in patterns:
                if re.search(pat, article_text):
                    found = True
                    break
            if not found:
                missing.append(label)

        return missing

    # ----- semantic matching -----

    def _semantic_match(
        self, item_description: str, article_text: str,
        top_n: int = 3, min_sentence_len: int = 20,
    ) -> Tuple[float, str]:
        """
        Use TF-IDF cosine similarity to find article sentences that
        semantically match a checklist item description.

        Returns:
            (best_similarity_score, best_matching_snippet)
            Score is 0.0–1.0; snippet is the best-matching sentence.
        """
        if not HAS_SKLEARN or not article_text or not item_description:
            return 0.0, ''

        # Pre-process: fix PDF line-break artifacts (e.g., "Framing-\nham" → "Framingham")
        cleaned_text = re.sub(r'-\s*\n\s*', '', article_text)
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text)

        # Use overlapping windows (2-3 sentences) for better context matching
        # First split into sentences
        raw_sentences = re.split(r'(?<=[.!?])\s+', cleaned_text)
        raw_sentences = [
            s.strip() for s in raw_sentences
            if len(s.strip()) >= min_sentence_len
            and not re.match(r'^\d+[\.\)]?\s', s.strip())  # skip numbered refs
        ]

        if not raw_sentences:
            return 0.0, ''

        # Create windows of 2 consecutive sentences for better context
        windows = []
        for i in range(len(raw_sentences)):
            windows.append(raw_sentences[i])
            if i + 1 < len(raw_sentences):
                windows.append(raw_sentences[i] + ' ' + raw_sentences[i + 1])

        # Limit to prevent memory issues
        if len(windows) > 800:
            windows = windows[:800]

        try:
            corpus = [item_description.lower()] + [w.lower() for w in windows]

            vectorizer = TfidfVectorizer(
                stop_words='english',
                max_features=8000,
                ngram_range=(1, 3),  # up to trigrams for better phrase matching
                min_df=1,
                sublinear_tf=True,
            )
            tfidf_matrix = vectorizer.fit_transform(corpus)

            similarities = cosine_similarity(
                tfidf_matrix[0:1], tfidf_matrix[1:]
            ).flatten()

            top_indices = similarities.argsort()[-top_n:][::-1]
            best_idx = top_indices[0]
            best_score = float(similarities[best_idx])

            # Use top-3 average for more robust scoring
            top3_scores = [float(similarities[i]) for i in top_indices]
            avg_top3 = sum(top3_scores) / len(top3_scores)

            # Combined score: best match weighted more, but top-3 avg helps
            combined_score = best_score * 0.7 + avg_top3 * 0.3

            if combined_score >= 0.08:  # Threshold tuned for PDF text
                best_window = windows[best_idx]
                if len(best_window) > 180:
                    best_window = best_window[:180] + '...'
                return combined_score, best_window

        except Exception as e:
            logger.debug("Semantic matching failed: %s", e)

        return 0.0, ''

    def _llm_evaluate_items(
        self,
        items_to_check: List[dict],
        article_text: str,
        checklist_name: str,
    ) -> Dict[str, Tuple[bool, str]]:
        """
        Use Claude API (Haiku) to evaluate ambiguous checklist items.

        This is Phase 3 (optional): called only when an API key is configured
        and items remain ambiguous after keyword + semantic matching.

        Uses raw HTTP (urllib) instead of the anthropic SDK to avoid
        encoding issues on macOS and other platforms.

        Args:
            items_to_check: list of item defs with 'item' and 'description'
            article_text: the full article text
            checklist_name: name of the checklist being applied

        Returns:
            Dict mapping item_id -> (present: bool, evidence: str)
        """
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            logger.debug("No ANTHROPIC_API_KEY set; skipping LLM phase")
            return {}

        # Build a focused prompt with just the ambiguous items
        items_text = '\n'.join(
            f"- [{it['item']}] {it['description']}"
            for it in items_to_check
        )

        # Clean article text: remove non-UTF8 and problematic characters
        article_text_clean = article_text.encode('utf-8', errors='ignore').decode('utf-8')
        article_text_clean = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', article_text_clean)

        # Truncate to fit context window (Haiku: ~200k tokens)
        max_chars = 80_000
        if len(article_text_clean) > max_chars:
            article_text_clean = article_text_clean[:max_chars] + '\n[...truncated...]'

        prompt = (
            "You are evaluating a medical research article against the "
            f"{checklist_name} reporting checklist.\n\n"
            "For each item below, determine if the article adequately reports "
            "that element. Be strict: only mark 'present' if the article "
            "explicitly and clearly addresses this item. If unclear or only "
            "tangentially mentioned, mark as false.\n\n"
            "Respond ONLY with valid JSON: a dict where each key is "
            "the item ID and the value is an object with 'present' (boolean) "
            "and 'evidence' (brief quote or explanation, max 100 chars).\n\n"
            f"Items to evaluate:\n{items_text}\n\n"
            f"Article text:\n{article_text_clean}"
        )

        try:
            logger.info("LLM Phase 3: evaluating %d items via raw HTTP...", len(items_to_check))

            import subprocess, sys, tempfile

            # Write prompt to a temp file (avoids encoding issues entirely)
            prompt_safe = prompt.encode('utf-8', errors='ignore').decode('utf-8')
            prompt_safe = re.sub(r'[^\x09\x0a\x0d\x20-\x7e\x80-\uffff]', ' ', prompt_safe)

            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.txt', encoding='utf-8', delete=False
            ) as tf:
                tf.write(prompt_safe)
                prompt_file = tf.name

            # Write a standalone Python script that uses urllib (no SDK needed)
            # This avoids all anthropic SDK encoding/proxy issues
            script_content = '''
import json, sys, os, ssl

# Read prompt from file
with open(sys.argv[1], "r", encoding="utf-8") as f:
    prompt_text = f.read()

# Read API key from env
api_key_raw = os.environ.get("ANTHROPIC_API_KEY", "")

# Diagnostic: show key state before/after sanitization
raw_len = len(api_key_raw)
non_ascii = [f"U+{ord(c):04X}" for c in api_key_raw if ord(c) > 127]

# Strip invisible/non-ASCII characters that break HTTP latin-1 headers
api_key = "".join(c for c in api_key_raw if 32 <= ord(c) <= 126)

print(f"  [LLM diag] key length: raw={raw_len}, clean={len(api_key)}, "
      f"non-ascii chars removed: {non_ascii[:5]}", file=sys.stderr)
print(f"  [LLM diag] key starts with: {api_key[:12]}..., ends with: ...{api_key[-6:]}",
      file=sys.stderr)

if not api_key or not api_key.startswith("sk-"):
    print(f"ERROR: API key invalid after sanitization (len={len(api_key)})", file=sys.stderr)
    sys.exit(1)

# Build the request payload
payload = json.dumps({
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 2048,
    "messages": [{"role": "user", "content": prompt_text}],
}).encode("utf-8")

from urllib.request import Request, urlopen
from urllib.error import HTTPError

req = Request(
    "https://api.anthropic.com/v1/messages",
    data=payload,
    headers={
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    },
    method="POST",
)

try:
    ctx = ssl.create_default_context()
    with urlopen(req, timeout=80, context=ctx) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        print(body["content"][0]["text"])
except HTTPError as e:
    # Read and print the error response body for debugging
    err_body = e.read().decode("utf-8", errors="replace")
    print(f"HTTP {e.code}: {err_body}", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
'''

            with tempfile.NamedTemporaryFile(
                mode='w', suffix='.py', encoding='utf-8', delete=False
            ) as sf:
                sf.write(script_content)
                script_file = sf.name

            # Build clean env: strip proxy vars that interfere with direct HTTPS
            clean_env = {
                k: v for k, v in os.environ.items()
                if 'proxy' not in k.lower()
            }
            clean_env['PYTHONUTF8'] = '1'
            clean_env['PYTHONIOENCODING'] = 'utf-8'

            result = subprocess.run(
                [sys.executable, '-X', 'utf8', script_file, prompt_file],
                capture_output=True, text=True, timeout=90,
                env=clean_env,
            )

            # Clean up temp files
            for tmp in (prompt_file, script_file):
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

            if result.returncode != 0:
                # Show full stderr for debugging (not truncated)
                err_msg = result.stderr.strip()
                logger.warning("LLM subprocess failed:\n%s", err_msg[-500:])
                print(f"  LLM error detail: {err_msg[-300:]}", flush=True)
                return {}

            response_text = result.stdout
            json_match = re.search(r'\{[\s\S]+\}', response_text)
            if json_match:
                results = json.loads(json_match.group())
                logger.info("LLM returned results for %d items", len(results))
                return {
                    item_id: (
                        val.get('present', False),
                        val.get('evidence', ''),
                    )
                    for item_id, val in results.items()
                }
            else:
                logger.warning("LLM returned no JSON: %s", response_text[:200])

        except subprocess.TimeoutExpired:
            logger.warning("LLM call timed out after 90s")
        except Exception as e:
            logger.warning("LLM evaluation failed: %s", e)

        return {}

    # ----- reporting -----

    def generate_report(self, result: CheckResult, format: str = 'markdown',
                        audience: str = 'specialist', study_type: str = '',
                        detection_result=None, article_text: str = '') -> str:
        """
        Generate a report.

        Args:
            result: CheckResult from check()
            format: 'markdown', 'json', or 'text'
            audience: 'public' (patient/layperson), 'student', or 'specialist'
            study_type: detected study type string (for context)
            detection_result: DetectionResult from study_detector (optional, for design analysis)
            article_text: original article text (optional, for propensity score detection)
        """
        if format == 'json':
            return self._to_json(result)
        elif format == 'markdown':
            return self._to_audience_markdown(result, audience, study_type,
                                              detection_result, article_text)
        else:
            return self._to_text(result)

    # ----- audience-level explanations -----

    # Maps section names to plain-language explanations
    SECTION_EXPLANATIONS_PUBLIC = {
        'Title and Abstract': 'Does the title and summary clearly say what kind of study this is?',
        'Introduction': 'Does the article explain why the study was done and what it was trying to find out?',
        'Methods': 'Does the article explain how the study was done — who participated, what was measured, and how?',
        'Results': 'Does the article clearly show what was found?',
        'Discussion': 'Does the article discuss what the results mean, what the limitations are, and whether the results apply to other people?',
        'Other': 'Does the article disclose funding sources and conflicts of interest?',
        'Other information': 'Does the article disclose funding sources and conflicts of interest?',
    }

    SECTION_EXPLANATIONS_STUDENT = {
        'Title and Abstract': 'The title should identify the study design. The abstract should be structured (Background, Methods, Results, Conclusions).',
        'Introduction': 'Should include scientific background/rationale and clearly stated objectives or hypotheses.',
        'Methods': 'Should describe study design, setting, participants, variables, data sources, bias control, sample size, and statistical methods.',
        'Results': 'Should report participant flow, descriptive data, outcome data, main results with effect estimates and confidence intervals.',
        'Discussion': 'Should summarize key results, discuss limitations and biases, provide cautious interpretation, and address generalizability.',
        'Other': 'Should declare funding, role of funders, competing interests, and data availability.',
        'Other information': 'Should declare funding, role of funders, competing interests, and data availability.',
    }

    # Maps item descriptions to plain-language "why it matters"
    ITEM_WHY_IT_MATTERS = {
        'bias': 'Without discussing potential biases, readers cannot judge how reliable the results are.',
        'sample size': 'Without a sample size calculation, the study may be too small to detect a real effect.',
        'statistical': 'Without proper statistical methods, the conclusions may be mathematically wrong.',
        'limitations': 'If authors do not discuss limitations, they may be overstating their conclusions.',
        'confound': 'Without controlling for confounders, the observed effect may be caused by something else entirely.',
        'generali': 'Without discussing generalizability, it is unclear whether the results apply to other populations.',
        'randomiz': 'Without randomization, treatment groups may differ in ways that bias the results.',
        'blinding': 'Without blinding, participants or researchers may unconsciously influence the results.',
        'flow diagram': 'Without a flow diagram, it is hard to see how many participants dropped out and why.',
        'funding': 'Funding sources can influence study design and interpretation — transparency is essential.',
        'missing data': 'If missing data are not addressed, the results may be biased by incomplete information.',
        'consent': 'Ethical approval and consent ensure participants were protected and the study was reviewed.',
    }

    # ---- Study design classification with mapping to same checklist ----
    STROBE_SUBTYPES = {
        'cohort_study', 'case_control', 'analytical_cross_sectional',
        'descriptive_cross_sectional', 'case_series', 'case_report',
        'non_randomized_intervention', 'diagnostic_accuracy',
        'prognostic_factors', 'prognostic_model',
    }

    DESIGN_EXPLANATIONS_STUDENT = {
        'cohort_study': (
            "A **cohort study** follows a group of people over time to see who develops "
            "an outcome. Researchers observe but do not assign treatments."
        ),
        'case_control': (
            "A **case-control study** starts with people who have the outcome (cases) "
            "and compares them with similar people without it (controls), looking backward "
            "for exposures."
        ),
        'case_series': (
            "A **case series** describes a group of patients with a particular condition, "
            "without a comparison group. It cannot prove causation."
        ),
        'non_randomized_intervention': (
            "A **non-randomized intervention study** assigns a treatment, but without random "
            "allocation. This introduces selection bias — patients in the treatment group "
            "may differ systematically from controls."
        ),
        'randomized_controlled_trial': (
            "A **randomized controlled trial (RCT)** is the gold standard for evaluating "
            "interventions. Random assignment minimizes bias by making groups comparable."
        ),
        'systematic_review_interventions': (
            "A **systematic review with meta-analysis** pools results from multiple studies "
            "using predefined methods, providing the strongest level of evidence."
        ),
        'genomic_study': (
            "A **genomic/phylogenetic study** analyzes genetic sequences to understand "
            "evolutionary relationships, transmission patterns, or molecular epidemiology."
        ),
    }

    DESIGN_EXPLANATIONS_SPECIALIST = {
        'cohort_study': "Cohort study — prospective or retrospective follow-up of exposed vs unexposed groups.",
        'case_control': "Case-control study — retrospective comparison of cases vs controls for prior exposures.",
        'case_series': "Case series — descriptive report of consecutive/selected cases, no control group.",
        'non_randomized_intervention': "Non-randomized intervention — treatment assigned without randomization (quasi-experimental).",
        'randomized_controlled_trial': "Randomized controlled trial — participants randomly allocated to intervention vs control.",
        'systematic_review_interventions': "Systematic review and meta-analysis of intervention studies.",
        'genomic_study': "Genomic/phylogenetic sequence analysis study.",
    }

    # Propensity score matching patterns
    PSM_PATTERNS = [
        r'propensity[- ]score\s+match',
        r'propensity[- ]score\s+analysis',
        r'propensity[- ]score\s+weight',
        r'inverse\s+probability\s+(?:of\s+treatment\s+)?weight',
        r'IPTW',
        r'propensity[- ]adjusted',
        r'PS[- ]match',
    ]

    # Age-matched/historical controls patterns
    MATCHED_CONTROL_PATTERNS = [
        r'(?:age|sex|gender)[- ]matched\s+control',
        r'historical\s+control',
        r'matched\s+(?:pair|cohort|sample)',
        r'frequency[- ]match',
    ]

    def _detect_control_methods(self, article_text: str) -> dict:
        """Detect propensity score matching and control matching methods in text."""
        if not article_text:
            return {}

        text_lower = article_text.lower()
        found = {}

        for pat in self.PSM_PATTERNS:
            m = re.search(pat, text_lower)
            if m:
                start = max(0, m.start() - 60)
                end = min(len(text_lower), m.end() + 60)
                found['propensity_score'] = text_lower[start:end].strip()
                break

        for pat in self.MATCHED_CONTROL_PATTERNS:
            m = re.search(pat, text_lower)
            if m:
                start = max(0, m.start() - 60)
                end = min(len(text_lower), m.end() + 60)
                found['matched_controls'] = text_lower[start:end].strip()
                break

        return found

    def _design_analysis_block(self, audience: str, study_type: str,
                               detection_result=None, article_text: str = '') -> str:
        """Generate a study design analysis block for student/specialist reports."""
        lines = []
        is_student = (audience == 'student')

        lines.append("## Study design analysis\n")

        # --- Primary classification ---
        if is_student:
            expl = self.DESIGN_EXPLANATIONS_STUDENT.get(study_type, '')
            if expl:
                lines.append(expl + "\n")
        else:
            expl = self.DESIGN_EXPLANATIONS_SPECIALIST.get(study_type, '')
            if expl:
                lines.append(f"**Primary classification:** {expl}\n")

        # --- Design ambiguity: if competing types are close ---
        if detection_result and hasattr(detection_result, 'all_scores') and detection_result.all_scores:
            sorted_scores = sorted(detection_result.all_scores.items(), key=lambda x: -x[1])
            if len(sorted_scores) >= 2:
                best_type, best_score = sorted_scores[0]
                second_type, second_score = sorted_scores[1]

                # Check if both map to same checklist (STROBE family)
                both_strobe = (best_type in self.STROBE_SUBTYPES
                               and second_type in self.STROBE_SUBTYPES)

                gap_ratio = second_score / best_score if best_score > 0 else 0

                if gap_ratio > 0.4:  # Close competition
                    if is_student:
                        lines.append("### Design classification note\n")
                        lines.append(
                            f"This study shows features of both "
                            f"**{best_type.replace('_', ' ')}** and "
                            f"**{second_type.replace('_', ' ')}**. "
                        )
                        if both_strobe:
                            lines.append(
                                "Both types are evaluated with the same STROBE checklist, "
                                "so the quality assessment is valid regardless of which "
                                "exact subtype applies.\n"
                            )
                        lines.append(
                            "Study design classification is not always clear-cut — "
                            "real articles often combine elements of different designs. "
                            "What matters most is understanding what type of evidence "
                            "the study provides and what biases may be present.\n"
                        )
                    else:
                        lines.append("### Design ambiguity\n")
                        lines.append(
                            f"Competing classifications: "
                            f"**{best_type.replace('_', ' ')}** (score {best_score:.0f}) vs "
                            f"**{second_type.replace('_', ' ')}** (score {second_score:.0f}). "
                        )
                        if both_strobe:
                            lines.append(
                                "Both map to STROBE checklist — assessment validity unaffected."
                            )
                        lines.append("")

        # --- Propensity score matching / control methods ---
        control_methods = self._detect_control_methods(article_text)

        if control_methods:
            if is_student:
                lines.append("### Control group methodology\n")
                if 'propensity_score' in control_methods:
                    lines.append(
                        "This study uses **propensity score matching (PSM)** — "
                        "a statistical technique that creates comparable groups "
                        "when randomization is not possible. PSM estimates each "
                        "participant's probability of receiving the treatment based on "
                        "their characteristics (age, sex, comorbidities, etc.), then "
                        "matches treated and untreated participants with similar "
                        "probabilities. This reduces selection bias but cannot fully "
                        "replace randomization because unmeasured confounders may "
                        "still differ between groups.\n"
                    )
                if 'matched_controls' in control_methods:
                    lines.append(
                        "The study compares results against **matched controls** "
                        "(e.g., age-matched, sex-matched). While matching improves "
                        "comparability, it is not equivalent to randomization. "
                        "Matched controls from a different population or time period "
                        "(historical controls) may introduce additional biases from "
                        "differences in care standards, diagnostic criteria, or "
                        "population characteristics.\n"
                    )
            else:  # specialist
                lines.append("### Control methodology detected\n")
                if 'propensity_score' in control_methods:
                    lines.append(
                        "**Propensity score methods detected.** "
                        "PSM/IPTW can reduce measured confounding in non-randomized studies "
                        "but cannot address unmeasured confounders. Verify: "
                        "balance diagnostics reported, caliper specified, "
                        "sensitivity analysis for unmeasured confounding (e.g., E-value).\n"
                    )
                if 'matched_controls' in control_methods:
                    lines.append(
                        "**Matched controls detected** (age/sex/frequency matching). "
                        "Verify matching variables are appropriate, report number unmatched, "
                        "and assess whether matching introduces collider bias.\n"
                    )
        elif article_text and study_type in ('non_randomized_intervention', 'cohort_study', 'case_control'):
            # No PSM found in an observational study — worth noting
            if is_student:
                lines.append("### Note on confounding\n")
                lines.append(
                    "This observational study does not appear to use propensity score "
                    "matching or other statistical methods to control for confounding. "
                    "Without such adjustments, differences between treatment groups "
                    "may be due to patient characteristics rather than the treatment itself.\n"
                )
            else:
                lines.append("### Confounding adjustment\n")
                lines.append(
                    "No propensity score methods or formal matching detected. "
                    "For non-randomized comparisons, consider whether adequate "
                    "confounding adjustment was performed (multivariable regression, "
                    "stratification, or instrumental variables).\n"
                )

        return "\n".join(lines) if len(lines) > 1 else ""

    def _get_why_it_matters(self, description: str) -> str:
        """Get a plain-language explanation of why a missing item matters."""
        desc_lower = description.lower()
        for key, explanation in self.ITEM_WHY_IT_MATTERS.items():
            if key in desc_lower:
                return explanation
        return 'This information helps readers assess whether the study was conducted and reported properly.'

    def _to_audience_markdown(self, result: CheckResult, audience: str = 'specialist',
                              study_type: str = '', detection_result=None,
                              article_text: str = '') -> str:
        """Generate markdown report tailored to audience level."""
        if audience == 'public':
            report = self._report_public(result, study_type)
        elif audience == 'student':
            report = self._report_student(result, study_type)
        else:
            report = self._report_specialist(result, study_type)

        # Add study design analysis for student and specialist audiences
        if audience in ('student', 'specialist') and (detection_result or article_text):
            design_block = self._design_analysis_block(
                audience, study_type, detection_result, article_text)
            if design_block:
                # Insert after the first heading block
                report = report + "\n\n" + design_block

        return report

    def _report_public(self, result: CheckResult, study_type: str = '') -> str:
        """Plain-language report for patients and non-specialists."""
        lines = []
        grade_emoji = {'A': '🟢', 'B': '🔵', 'C': '🟡', 'D': '🟠', 'F': '🔴'}.get(result.grade, '⚪')

        # --- Title and verdict ---
        lines.append(f"# Can you trust this study?")
        lines.append("")

        verdict_text = {
            'A': 'This study is **well-reported**. The authors described their methods, results, and limitations clearly. This does not guarantee the conclusions are correct, but the reporting meets high standards.',
            'B': 'This study is **mostly well-reported**, with some minor gaps. Overall, the key information is present.',
            'C': 'This study has **significant gaps** in how it was reported. Some important details are missing, which makes it harder to evaluate the results.',
            'D': 'This study is **poorly reported**. Many important details about methods, results, or limitations are missing. Be cautious about the conclusions.',
            'F': 'This study has **very poor reporting quality**. Most of the information needed to evaluate the study is missing. The conclusions should be treated with significant skepticism.',
        }

        lines.append(f"{grade_emoji} **Reporting quality: Grade {result.grade}** — {result.weighted_score:.0f}%\n")
        lines.append(verdict_text.get(result.grade, ''))
        lines.append("")

        # --- What was checked ---
        if study_type:
            lines.append(f"*Study type detected: {study_type.replace('_', ' ')}. "
                         f"Evaluated against the {result.checklist_name} checklist ({result.total_items} items).*\n")

        # --- Traffic light summary by section ---
        lines.append("## What does this study report well, and what is missing?\n")

        explanations = self.SECTION_EXPLANATIONS_PUBLIC
        for sec, cov in sorted(result.section_coverage.items()):
            if cov >= 60:
                icon = '🟢'
                status = 'Well covered'
            elif cov >= 30:
                icon = '🟡'
                status = 'Partially covered'
            else:
                icon = '🔴'
                status = 'Poorly covered or missing'

            question = explanations.get(sec, f'Is the {sec.lower()} section adequate?')
            lines.append(f"{icon} **{sec}** — {status} ({cov:.0f}%)")
            lines.append(f"   {question}\n")

        # --- Key concerns in plain language ---
        critical = [i for i in result.items if i.verdict in ('absent', 'explicitly_absent') and i.weight >= 1.1]
        if critical:
            lines.append("## Key concerns\n")
            lines.append("The following important information is **missing** from this article:\n")
            for item in critical:
                why = self._get_why_it_matters(item.description)
                lines.append(f"- **{item.description}**")
                lines.append(f"  *Why it matters:* {why}\n")

        # --- Bottom line ---
        lines.append("## Bottom line\n")
        if result.grade in ('A', 'B'):
            lines.append("The article provides enough methodological detail for readers to evaluate the study. "
                         "However, good reporting does not automatically mean the conclusions are correct — "
                         "it means you have enough information to judge for yourself.")
        elif result.grade == 'C':
            lines.append("The article is missing some important details. "
                         "Consider looking for other studies on the same topic before drawing conclusions.")
        else:
            lines.append("This article is missing substantial information about how the study was done. "
                         "It is difficult to evaluate whether the conclusions are trustworthy. "
                         "Look for better-reported studies or systematic reviews on this topic.")

        return "\n".join(lines)

    def _report_student(self, result: CheckResult, study_type: str = '') -> str:
        """Educational report for students learning to critically appraise articles."""
        lines = []
        grade_emoji = {'A': '🟢', 'B': '🔵', 'C': '🟡', 'D': '🟠', 'F': '🔴'}.get(result.grade, '⚪')

        lines.append(f"# Reporting Quality Assessment — Study Guide")
        lines.append(f"\n**Checklist used:** {result.checklist_name} ({result.checklist_full_name})")
        if study_type:
            lines.append(f"**Study type:** {study_type.replace('_', ' ')}")
        lines.append("")

        # --- Overall grade ---
        lines.append(f"## Overall: {grade_emoji} Grade {result.grade} — {result.grade_label}")
        lines.append(f"**Score: {result.weighted_score:.1f}%** — "
                      f"{result.present_count} fully reported, "
                      f"{result.partial_count} partially, "
                      f"{result.absent_count} missing out of {result.total_items} items.\n")

        # --- Section-by-section breakdown ---
        lines.append("## Section-by-section analysis\n")

        explanations = self.SECTION_EXPLANATIONS_STUDENT

        # Group items by base section
        section_groups: dict = {}
        for item in result.items:
            base = item.section.split(' - ')[0] if ' - ' in item.section else item.section
            section_groups.setdefault(base, []).append(item)

        for sec in sorted(section_groups.keys()):
            items = section_groups[sec]
            cov = result.section_coverage.get(sec, 0)

            if cov >= 60:
                sec_icon = '🟢'
            elif cov >= 30:
                sec_icon = '🟡'
            else:
                sec_icon = '🔴'

            lines.append(f"### {sec_icon} {sec} ({cov:.0f}%)\n")

            # Section explanation
            if sec in explanations:
                lines.append(f"*{explanations[sec]}*\n")

            # Items table
            lines.append("| Item | Status | Description | Confidence |")
            lines.append("|------|--------|-------------|------------|")
            for item in items:
                icon = {'present': '✅', 'partial': '🟡', 'absent': '❌',
                        'explicitly_absent': '🚫'}.get(item.verdict, '❓')
                lines.append(f"| {item.item_id} | {icon} {item.verdict} | "
                             f"{item.description[:70]} | {item.confidence:.0%} |")
            lines.append("")

            # Missing items with educational notes
            missing = [i for i in items if i.verdict in ('absent', 'explicitly_absent')]
            if missing:
                lines.append("**What to look for** when these items are missing:\n")
                for item in missing:
                    why = self._get_why_it_matters(item.description)
                    lines.append(f"- Item {item.item_id} — {item.description}")
                    lines.append(f"  → {why}")
                lines.append("")

        # --- Learning points ---
        lines.append("## Learning points\n")

        if result.grade in ('D', 'F'):
            lines.append("This article demonstrates **common reporting deficiencies**. "
                         "Pay attention to:\n")
            if any(i.verdict == 'absent' and 'bias' in i.description.lower() for i in result.items):
                lines.append("- **Bias discussion absent:** A well-designed study should always acknowledge potential biases "
                             "(selection bias, information bias, confounding).")
            if any(i.verdict == 'absent' and 'limitation' in i.description.lower() for i in result.items):
                lines.append("- **No limitations section:** This is a red flag. Every study has limitations; "
                             "not reporting them suggests lack of critical reflection.")
            if any(i.verdict == 'absent' and 'sample size' in i.description.lower() for i in result.items):
                lines.append("- **No sample size justification:** Without a power calculation, the study may be "
                             "underpowered — unable to detect a real effect even if one exists.")
        elif result.grade in ('A', 'B'):
            lines.append("This article demonstrates **good reporting practice**. "
                         "Notice how the authors provide enough detail for you to assess the study independently.")

        lines.append(f"\n*Evaluated against the {result.checklist_name} checklist. "
                     f"For the full checklist, see: {result.checklist_full_name}.*")

        return "\n".join(lines)

    def _report_specialist(self, result: CheckResult, study_type: str = '') -> str:
        """Full technical report for researchers and clinicians."""
        # This is the existing detailed markdown report
        return self._to_markdown(result, study_type)

    def _to_json(self, result: CheckResult) -> str:
        data = {
            'checklist_name': result.checklist_name,
            'checklist_full_name': result.checklist_full_name,
            'description': result.description,
            'total_items': result.total_items,
            'weighted_score': result.weighted_score,
            'simple_score': result.simple_score,
            'present_count': result.present_count,
            'absent_count': result.absent_count,
            'section_coverage': result.section_coverage,
            'items': [
                {
                    'item_id': i.item_id,
                    'section': i.section,
                    'description': i.description,
                    'confidence': i.confidence,
                    'verdict': i.verdict,
                    'matched_keywords': i.matched_keywords,
                    'matched_in_sections': i.matched_in_sections,
                    'total_keywords': i.total_keywords,
                    'keyword_match_ratio': i.keyword_match_ratio,
                    'section_match': i.section_match,
                    'weight': i.weight,
                    'evidence_snippets': i.evidence_snippets,
                }
                for i in result.items
            ],
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def _to_markdown(self, result: CheckResult, study_type: str = '') -> str:
        lines = []
        lines.append(f"# {result.checklist_full_name} — Reporting Quality Assessment")
        lines.append(f"\n**Checklist:** {result.checklist_name}")
        if study_type:
            lines.append(f"**Study type:** {study_type}")
        lines.append(f"**Description:** {result.description}\n")

        # Overall grade — the main output
        grade_emoji = {'A': '🟢', 'B': '🔵', 'C': '🟡', 'D': '🟠', 'F': '🔴'}.get(result.grade, '⚪')
        lines.append(f"## Overall Quality: {grade_emoji} Grade {result.grade} — {result.grade_label}\n")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| **Reporting quality score** | **{result.weighted_score:.1f}%** |")
        lines.append(f"| Items fully reported | {result.present_count} of {result.total_items} |")
        lines.append(f"| Items partially reported | {result.partial_count} |")
        lines.append(f"| Items missing | {result.absent_count} |")

        # Section coverage
        lines.append("\n## Section Coverage\n")
        lines.append("| Section | Coverage |")
        lines.append("|---------|----------|")
        for sec, cov in sorted(result.section_coverage.items()):
            bar_len = int(cov / 10)
            bar = '\u2588' * bar_len + '\u2591' * (10 - bar_len)
            lines.append(f"| {sec} | {bar} {cov:.0f}% |")

        # Detailed items
        lines.append("\n## Detailed Results\n")
        current_section = None
        for item in result.items:
            base_section = item.section.split(' - ')[0] if ' - ' in item.section else item.section
            if base_section != current_section:
                current_section = base_section
                lines.append(f"\n### {current_section}\n")

            icon = {
                'present': '\u2705',
                'partial': '\U0001f7e1',
                'absent': '\u274c',
                'explicitly_absent': '\U0001f6ab',
            }.get(item.verdict, '\u2753')

            conf_bar_len = int(item.confidence * 10)
            conf_bar = '\u2588' * conf_bar_len + '\u2591' * (10 - conf_bar_len)

            lines.append(f"{icon} **Item {item.item_id}** [{item.verdict}] "
                         f"confidence: {conf_bar} {item.confidence:.0%}")
            lines.append(f"   {item.description}")

            if item.matched_keywords:
                lines.append(f"   - Keywords matched: `{'`, `'.join(item.matched_keywords)}`"
                             f" ({item.keyword_match_ratio:.0%} of {item.total_keywords})")
                lines.append(f"   - Found in: {', '.join(set(item.matched_in_sections))}")
            if item.evidence_snippets:
                lines.append(f"   - Evidence: _{item.evidence_snippets[0]}_")
            if item.verdict == 'absent':
                expected_kw = ', '.join(item.matched_keywords or item.evidence_snippets[:3] or ['(no keywords matched)'])
                if not item.matched_keywords:
                    lines.append(f"   - Searched for: `{'`, `'.join(item.matched_keywords)}` (none found)")
            lines.append("")

        # Recommendations
        absent_items = [i for i in result.items if i.verdict in ('absent', 'explicitly_absent')]
        if absent_items:
            lines.append("\n## Missing Items — Recommendations\n")
            for i, item in enumerate(absent_items[:10], 1):
                lines.append(f"{i}. **{item.section} (Item {item.item_id}):** {item.description}")
            if len(absent_items) > 10:
                lines.append(f"\n...and {len(absent_items) - 10} more items.")

        return "\n".join(lines)

    def _to_text(self, result: CheckResult) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append(f"  {result.checklist_full_name} — Reporting Quality Assessment")
        lines.append("=" * 80)
        lines.append(f"  GRADE: {result.grade} — {result.grade_label}")
        lines.append(f"  Reporting quality score: {result.weighted_score:.1f}%")
        lines.append(f"  Fully reported:   {result.present_count}/{result.total_items}")
        lines.append(f"  Partially:        {result.partial_count}/{result.total_items}")
        lines.append(f"  Missing:          {result.absent_count}/{result.total_items}")
        lines.append("-" * 80)

        for item in result.items:
            status_map = {
                'present': '[FOUND   ]',
                'partial': '[PARTIAL ]',
                'absent': '[MISSING ]',
                'explicitly_absent': '[EXPLICIT]',
            }
            status = status_map.get(item.verdict, '[???     ]')
            lines.append(f"  {status} {item.item_id}: {item.description[:60]}"
                         f" (conf: {item.confidence:.0%})")

        lines.append("=" * 80)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        description='Enhanced Checklist Checker with context-aware matching',
    )
    parser.add_argument('article', help='Path to article file (txt/pdf)')
    parser.add_argument('-c', '--checklist', required=True,
                        help='Checklist name (CONSORT, PRISMA, STROBE, GENOMICS)')
    parser.add_argument('-o', '--output', help='Output file path')
    parser.add_argument('-f', '--format', choices=['text', 'markdown', 'json'],
                        default='markdown', help='Output format')
    parser.add_argument('--list', action='store_true', help='List checklists')

    args = parser.parse_args()

    checker = EnhancedChecker()

    if args.list:
        print("Available checklists:", ', '.join(checker.list_checklists()))
        exit(0)

    # Read article
    article_path = Path(args.article)
    if article_path.suffix.lower() == '.pdf':
        try:
            import PyPDF2
            text = ""
            with open(article_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
        except ImportError:
            print("Install PyPDF2: pip install PyPDF2")
            exit(1)
    else:
        with open(article_path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

    # Run check
    result = checker.check(text, args.checklist.upper())
    report = checker.generate_report(result, args.format)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"Report saved to {args.output}")
    else:
        print(report)

    print(f"\nWeighted score: {result.weighted_score:.1f}%")
    print(f"Simple score:   {result.simple_score:.1f}%")
