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
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from section_parser import SectionParser, ArticleSection, get_expected_sections


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
    r'(?i)\b{kw}\s+was\s+not\s+(?:done|performed|used|applied|reported)',
    r'(?i)\b{kw}\s+(?:were|was)\s+not\s+(?:available|possible)',
    r'(?i)\black(?:ed|ing)?\s+(?:of\s+)?{kw}',
    r'(?i)\babsence\s+of\s+{kw}',
]


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

        # Evaluate each item
        item_scores: List[ItemScore] = []
        for item_def in checklist['items']:
            score = self._evaluate_item(item_def, sections)
            item_scores.append(score)

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

    # ----- reporting -----

    def generate_report(self, result: CheckResult, format: str = 'markdown',
                        audience: str = 'specialist', study_type: str = '') -> str:
        """
        Generate a report.

        Args:
            result: CheckResult from check()
            format: 'markdown', 'json', or 'text'
            audience: 'public' (patient/layperson), 'student', or 'specialist'
            study_type: detected study type string (for context)
        """
        if format == 'json':
            return self._to_json(result)
        elif format == 'markdown':
            return self._to_audience_markdown(result, audience, study_type)
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

    def _get_why_it_matters(self, description: str) -> str:
        """Get a plain-language explanation of why a missing item matters."""
        desc_lower = description.lower()
        for key, explanation in self.ITEM_WHY_IT_MATTERS.items():
            if key in desc_lower:
                return explanation
        return 'This information helps readers assess whether the study was conducted and reported properly.'

    def _to_audience_markdown(self, result: CheckResult, audience: str = 'specialist',
                              study_type: str = '') -> str:
        """Generate markdown report tailored to audience level."""
        if audience == 'public':
            return self._report_public(result, study_type)
        elif audience == 'student':
            return self._report_student(result, study_type)
        else:
            return self._report_specialist(result, study_type)

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
