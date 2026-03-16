#!/usr/bin/env python3
"""
Section Parser for Scientific Articles

Splits article text into IMRaD sections (Introduction, Methods, Results,
and Discussion) plus other standard sections. This enables context-aware
checklist matching — verifying that keywords appear in the expected section,
not just anywhere in the text.
"""

import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ArticleSection:
    """Represents a parsed section of a scientific article."""
    name: str               # Normalized section name (e.g., "methods")
    original_heading: str   # Original heading text from the article
    text: str               # Full text content of the section
    start_pos: int          # Character offset in original text
    end_pos: int            # Character offset end
    subsections: List['ArticleSection'] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


# Canonical section names → regex patterns that match headings
SECTION_PATTERNS: Dict[str, List[str]] = {
    "title": [
        # Title is usually the first non-empty line; handled separately
    ],
    "abstract": [
        r'(?i)^\s*(?:abstract|summary|synopsis)',
        r'(?i)^\s*(?:structured\s+)?abstract',
    ],
    "introduction": [
        r'(?i)^\s*(?:\d+\.?\s*)?introduction',
        r'(?i)^\s*(?:\d+\.?\s*)?background',
        r'(?i)^\s*(?:\d+\.?\s*)?background\s+and\s+(?:rationale|objectives?)',
    ],
    "methods": [
        r'(?i)^\s*(?:\d+\.?\s*)?methods?\b',
        r'(?i)^\s*(?:\d+\.?\s*)?materials?\s+and\s+methods?',
        r'(?i)^\s*(?:\d+\.?\s*)?patients?\s+and\s+methods?',
        r'(?i)^\s*(?:\d+\.?\s*)?subjects?\s+and\s+methods?',
        r'(?i)^\s*(?:\d+\.?\s*)?experimental\s+(?:procedures?|methods?|design)',
        r'(?i)^\s*(?:\d+\.?\s*)?study\s+design',
        r'(?i)^\s*(?:\d+\.?\s*)?methodology',
    ],
    "results": [
        r'(?i)^\s*(?:\d+\.?\s*)?results?\b',
        r'(?i)^\s*(?:\d+\.?\s*)?findings?\b',
        r'(?i)^\s*(?:\d+\.?\s*)?results?\s+and\s+discussion',
    ],
    "discussion": [
        r'(?i)^\s*(?:\d+\.?\s*)?discussion\b',
        r'(?i)^\s*(?:\d+\.?\s*)?interpretation\b',
    ],
    "conclusion": [
        r'(?i)^\s*(?:\d+\.?\s*)?conclusions?\b',
        r'(?i)^\s*(?:\d+\.?\s*)?concluding\s+remarks?',
        r'(?i)^\s*(?:\d+\.?\s*)?summary\s+and\s+conclusions?',
    ],
    "references": [
        r'(?i)^\s*(?:\d+\.?\s*)?references?\b',
        r'(?i)^\s*(?:\d+\.?\s*)?bibliography\b',
        r'(?i)^\s*(?:\d+\.?\s*)?literature\s+cited',
    ],
    "acknowledgements": [
        r'(?i)^\s*(?:\d+\.?\s*)?acknowledgements?\b',
        r'(?i)^\s*(?:\d+\.?\s*)?funding\b',
        r'(?i)^\s*(?:\d+\.?\s*)?conflict\s+of\s+interest',
        r'(?i)^\s*(?:\d+\.?\s*)?competing\s+interests?',
        r'(?i)^\s*(?:\d+\.?\s*)?declarations?\b',
    ],
    "supplementary": [
        r'(?i)^\s*(?:\d+\.?\s*)?supplementary',
        r'(?i)^\s*(?:\d+\.?\s*)?supporting\s+information',
        r'(?i)^\s*(?:\d+\.?\s*)?appendix',
    ],
}

# Methods subsections (important for detailed checklist matching)
METHODS_SUBSECTION_PATTERNS: Dict[str, List[str]] = {
    "study_design": [
        r'(?i)study\s+design',
        r'(?i)trial\s+design',
        r'(?i)experimental\s+design',
    ],
    "participants": [
        r'(?i)participants?',
        r'(?i)patients?\s+(?:selection|population|enrollment)',
        r'(?i)(?:inclusion|exclusion)\s+criteria',
        r'(?i)eligibility',
        r'(?i)subjects?',
    ],
    "randomization": [
        r'(?i)randomi[sz]ation',
        r'(?i)random\s+allocation',
        r'(?i)sequence\s+generation',
    ],
    "blinding": [
        r'(?i)blinding',
        r'(?i)masking',
        r'(?i)double[- ]blind',
    ],
    "interventions": [
        r'(?i)interventions?',
        r'(?i)treatment\s+(?:protocol|regimen)',
        r'(?i)drug\s+(?:administration|dosage)',
    ],
    "outcomes": [
        r'(?i)outcomes?\s+measures?',
        r'(?i)(?:primary|secondary)\s+(?:outcomes?|endpoints?)',
        r'(?i)endpoints?',
    ],
    "sample_size": [
        r'(?i)sample\s+size',
        r'(?i)power\s+(?:analysis|calculation)',
    ],
    "statistical_analysis": [
        r'(?i)statistic(?:al)?\s+(?:analysis|methods?)',
        r'(?i)data\s+analysis',
        r'(?i)analys[ei]s',
    ],
}


class SectionParser:
    """
    Parses scientific articles into structured sections.

    Supports:
    - Heading-based splitting (most common)
    - Heuristic splitting for unstructured text (e.g., poor PDF extraction)
    - IMRaD structure detection
    - Methods subsection detection
    """

    def __init__(self):
        self.section_patterns = SECTION_PATTERNS
        self.methods_subsection_patterns = METHODS_SUBSECTION_PATTERNS

    def parse(self, text: str) -> Dict[str, ArticleSection]:
        """
        Parse article text into sections.

        Args:
            text: Full article text

        Returns:
            Dict mapping normalized section names to ArticleSection objects.
            Always includes a 'full_text' key with the entire text.
        """
        sections = {}

        # Always store the full text
        sections['full_text'] = ArticleSection(
            name='full_text',
            original_heading='(Full Text)',
            text=text,
            start_pos=0,
            end_pos=len(text),
        )

        # Find all section boundaries
        boundaries = self._find_section_boundaries(text)

        if len(boundaries) < 2:
            # Couldn't find clear sections — try heuristic approach
            boundaries = self._heuristic_section_detection(text)

        if len(boundaries) < 2:
            # Still nothing — return full_text with a guess at abstract
            abstract = self._extract_abstract_heuristic(text)
            if abstract:
                sections['abstract'] = abstract
            return sections

        # Build sections from boundaries
        for i, (section_name, heading, start_pos) in enumerate(boundaries):
            end_pos = boundaries[i + 1][2] if i + 1 < len(boundaries) else len(text)
            section_text = text[start_pos:end_pos]

            section = ArticleSection(
                name=section_name,
                original_heading=heading,
                text=section_text,
                start_pos=start_pos,
                end_pos=end_pos,
            )

            # Parse methods subsections if this is the methods section
            if section_name == 'methods':
                section.subsections = self._parse_methods_subsections(section_text, start_pos)

            sections[section_name] = section

        return sections

    def _find_section_boundaries(self, text: str) -> List[Tuple[str, str, int]]:
        """
        Find section boundaries by matching heading patterns.

        Returns list of (section_name, original_heading, char_position)
        sorted by position.
        """
        boundaries = []
        lines = text.split('\n')
        char_pos = 0

        for line in lines:
            stripped = line.strip()

            # Skip empty lines and very long lines (not headings)
            if not stripped or len(stripped) > 120:
                char_pos += len(line) + 1
                continue

            # Check if this line looks like a heading
            if self._is_likely_heading(stripped):
                for section_name, patterns in self.section_patterns.items():
                    for pattern in patterns:
                        if re.match(pattern, stripped):
                            boundaries.append((section_name, stripped, char_pos))
                            break
                    else:
                        continue
                    break

            char_pos += len(line) + 1

        # Sort by position (should already be, but ensure)
        boundaries.sort(key=lambda x: x[2])

        return boundaries

    def _is_likely_heading(self, line: str) -> bool:
        """Heuristic: is this line probably a section heading?"""
        # All caps or title case, short length
        if len(line) > 100:
            return False

        # Common heading patterns
        if re.match(r'^[A-Z][A-Z\s\d.:&-]{2,60}$', line):  # ALL CAPS
            return True
        if re.match(r'^\d+\.?\s+[A-Z]', line):  # Numbered: "1. Introduction"
            return True
        if line.endswith(':') and len(line) < 50:  # Ends with colon
            return True

        # Check against our known patterns
        for patterns in self.section_patterns.values():
            for pattern in patterns:
                if re.match(pattern, line):
                    return True

        return False

    def _heuristic_section_detection(self, text: str) -> List[Tuple[str, str, int]]:
        """
        Fallback: detect sections by searching for keywords in the text
        even when headings are not clearly formatted (e.g., PDF extraction).
        """
        boundaries = []
        text_lower = text.lower()

        # Look for paragraph-start patterns that suggest section changes
        # Common in PDFs where formatting is lost
        search_terms = [
            ('abstract', r'(?:^|\n)\s*abstract[:\s\.]'),
            ('introduction', r'(?:^|\n)\s*(?:\d\.?\s*)?introduction[:\s\.]'),
            ('methods', r'(?:^|\n)\s*(?:\d\.?\s*)?(?:materials?\s+and\s+)?methods?[:\s\.]'),
            ('results', r'(?:^|\n)\s*(?:\d\.?\s*)?results?[:\s\.]'),
            ('discussion', r'(?:^|\n)\s*(?:\d\.?\s*)?discussion[:\s\.]'),
            ('conclusion', r'(?:^|\n)\s*(?:\d\.?\s*)?conclusions?[:\s\.]'),
            ('references', r'(?:^|\n)\s*(?:\d\.?\s*)?references?[:\s\.]'),
        ]

        for section_name, pattern in search_terms:
            match = re.search(pattern, text_lower)
            if match:
                boundaries.append((section_name, section_name.title(), match.start()))

        boundaries.sort(key=lambda x: x[2])
        return boundaries

    def _extract_abstract_heuristic(self, text: str) -> Optional[ArticleSection]:
        """Try to find abstract even without clear headings."""
        # Look for "Abstract" keyword
        match = re.search(r'(?i)\babstract\b', text)
        if match:
            # Take up to 2000 chars after "Abstract"
            start = match.start()
            end = min(start + 2000, len(text))
            # Try to find next section or double newline as boundary
            next_section = re.search(r'\n\s*\n\s*(?:Introduction|Background|Keywords)', text[start+50:end])
            if next_section:
                end = start + 50 + next_section.start()

            return ArticleSection(
                name='abstract',
                original_heading='Abstract',
                text=text[start:end],
                start_pos=start,
                end_pos=end,
            )
        return None

    def _parse_methods_subsections(self, methods_text: str, base_offset: int) -> List[ArticleSection]:
        """Parse subsections within the Methods section."""
        subsections = []
        text_lower = methods_text.lower()

        for sub_name, patterns in self.methods_subsection_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, text_lower)
                if match:
                    # Extract a window of text around the match (up to 1500 chars)
                    start = max(0, match.start() - 50)
                    end = min(len(methods_text), match.end() + 1500)

                    subsections.append(ArticleSection(
                        name=sub_name,
                        original_heading=methods_text[match.start():match.end()],
                        text=methods_text[start:end],
                        start_pos=base_offset + start,
                        end_pos=base_offset + end,
                    ))
                    break  # One match per subsection type is enough

        return subsections

    def get_section_summary(self, sections: Dict[str, ArticleSection]) -> Dict:
        """
        Generate a summary of parsed sections for diagnostics.
        """
        summary = {
            'total_sections': len(sections) - 1,  # Exclude full_text
            'total_words': sections['full_text'].word_count,
            'sections': {},
            'imrad_complete': all(
                s in sections for s in ['introduction', 'methods', 'results', 'discussion']
            ),
            'has_abstract': 'abstract' in sections,
        }

        for name, section in sections.items():
            if name == 'full_text':
                continue
            summary['sections'][name] = {
                'heading': section.original_heading,
                'words': section.word_count,
                'start': section.start_pos,
                'subsections': [s.name for s in section.subsections] if section.subsections else [],
            }

        return summary


# Convenience alias
SECTION_ALIASES = {
    # Map checklist section expectations to parser section names
    'Title and Abstract': ['abstract', 'title'],
    'Title': ['title', 'abstract'],
    'Abstract': ['abstract'],
    'Introduction': ['introduction'],
    'Other': ['acknowledgements', 'full_text'],
    'Methods': ['methods'],
    'Methods - Trial design': ['methods'],
    'Methods - Participants': ['methods'],
    'Methods - Interventions': ['methods'],
    'Methods - Outcomes': ['methods'],
    'Methods - Sample size': ['methods'],
    'Methods - Randomization': ['methods'],
    'Methods - Allocation concealment': ['methods'],
    'Methods - Blinding': ['methods'],
    'Methods - Implementation': ['methods'],
    'Methods - Statistical methods': ['methods'],
    'Results': ['results'],
    'Results - Participant flow': ['results'],
    'Results - Recruitment': ['results'],
    'Results - Baseline data': ['results'],
    'Results - Numbers analysed': ['results'],
    'Results - Outcomes and estimation': ['results'],
    'Results - Ancillary analyses': ['results'],
    'Results - Harms': ['results'],
    'Discussion': ['discussion'],
    'Discussion - Limitations': ['discussion'],
    'Discussion - Generalisability': ['discussion'],
    'Discussion - Interpretation': ['discussion'],
    'Other information - Registration': ['acknowledgements', 'methods', 'full_text'],
    'Other information - Protocol': ['acknowledgements', 'methods', 'full_text'],
    'Other information - Funding': ['acknowledgements', 'full_text'],
    # STROBE sections
    'Setting': ['methods'],
    'Variables': ['methods'],
    'Data sources': ['methods'],
    'Bias': ['methods', 'discussion'],
    'Study size': ['methods'],
    'Quantitative variables': ['methods'],
    'Statistical methods': ['methods'],
    'Descriptive data': ['results'],
    'Outcome data': ['results'],
    'Main results': ['results'],
    'Other analyses': ['results'],
    'Key results': ['discussion'],
    'Limitations': ['discussion'],
    'Interpretation': ['discussion'],
    'Generalisability': ['discussion'],
    # PRISMA sections
    'Eligibility criteria': ['methods'],
    'Information sources': ['methods'],
    'Search strategy': ['methods'],
    'Selection process': ['methods'],
    'Data collection': ['methods'],
    'Risk of bias': ['methods', 'results'],
    'Synthesis methods': ['methods'],
    'Study selection': ['results'],
    'Study characteristics': ['results'],
    'Synthesis of results': ['results'],
}


def get_expected_sections(checklist_section_name: str) -> List[str]:
    """
    Given a checklist section name (e.g., 'Methods - Blinding'),
    return the article sections where this should be found.

    Falls back to full_text if no mapping exists.
    """
    return SECTION_ALIASES.get(checklist_section_name, ['full_text'])


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python section_parser.py <article.txt>")
        sys.exit(1)

    with open(sys.argv[1], 'r', encoding='utf-8', errors='ignore') as f:
        text = f.read()

    parser = SectionParser()
    sections = parser.parse(text)
    summary = parser.get_section_summary(sections)

    print(f"\nArticle Section Analysis")
    print(f"{'=' * 60}")
    print(f"Total words: {summary['total_words']}")
    print(f"Sections found: {summary['total_sections']}")
    print(f"IMRaD complete: {'Yes' if summary['imrad_complete'] else 'No'}")
    print(f"Has abstract: {'Yes' if summary['has_abstract'] else 'No'}")
    print()

    for name, info in summary['sections'].items():
        subs = f" (subsections: {', '.join(info['subsections'])})" if info['subsections'] else ""
        print(f"  [{name}] {info['heading']} — {info['words']} words{subs}")
