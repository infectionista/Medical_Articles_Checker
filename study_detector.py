#!/usr/bin/env python3
"""
Enhanced Study Type Detector

Improvements over the original (detailed_check.py StudyTypeDetector):

1. Negative context awareness: "non-randomized" no longer triggers RCT detection
2. Complete coverage: detection patterns for ALL 18 study types in the mapping table
3. Phrase-level matching: compound phrases scored higher than single words
4. Disqualifying patterns: explicit statements like "open-label" reduce RCT score
5. Confidence calibration: returns top-3 candidates with scores
"""

import re
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class DetectionResult:
    """Result of study type detection."""
    study_type: str              # Best match key (e.g., "non_randomized_intervention")
    confidence: float            # 0–100
    matched_keywords: List[str]  # Patterns that matched
    all_scores: Dict[str, float] # All study types with their scores
    warnings: List[str]          # Potential issues (e.g., "conflicting signals")


# Checklist mapping (same as detailed_check.py but kept here for reference)
STUDY_TYPE_CHECKLISTS = {
    "randomized_controlled_trial": {
        "name_ru": "Рандомизированное контролируемое испытание (РКИ)",
        "name_en": "Randomized Controlled Trial (RCT)",
        "checklist": "RoB 2",
        "local_checklist": "CONSORT"
    },
    "non_randomized_intervention": {
        "name_ru": "Нерандомизированное интервенционное исследование",
        "name_en": "Non-randomized Interventional Study",
        "checklist": "ROBINS-I",
        "local_checklist": "STROBE"
    },
    "cohort_study": {
        "name_ru": "Когортное исследование",
        "name_en": "Cohort Study",
        "checklist": "ROBINS-I",
        "local_checklist": "STROBE"
    },
    "case_control": {
        "name_ru": "Исследование случай-контроль",
        "name_en": "Case-Control Study",
        "checklist": "JBI Case-Control",
        "local_checklist": "STROBE"
    },
    "analytical_cross_sectional": {
        "name_ru": "Аналитическое поперечное исследование",
        "name_en": "Analytical Cross-Sectional Study",
        "checklist": "JBI Analytical Cross-Sectional",
        "local_checklist": "STROBE"
    },
    "descriptive_cross_sectional": {
        "name_ru": "Описательное поперечное исследование",
        "name_en": "Descriptive Cross-Sectional Study",
        "checklist": "JBI Cross-Sectional",
        "local_checklist": "STROBE"
    },
    "case_series": {
        "name_ru": "Серия клинических случаев",
        "name_en": "Case Series",
        "checklist": "JBI Case Series",
        "local_checklist": "STROBE"
    },
    "case_report": {
        "name_ru": "Один клинический случай",
        "name_en": "Case Report",
        "checklist": "JBI Case Report",
        "local_checklist": "STROBE"
    },
    "diagnostic_accuracy": {
        "name_ru": "Исследование точности диагностики",
        "name_en": "Diagnostic Accuracy Study",
        "checklist": "QUADAS-2",
        "local_checklist": "STROBE"
    },
    "systematic_review_interventions": {
        "name_ru": "Систематический обзор вмешательств",
        "name_en": "Systematic Review of Interventions",
        "checklist": "AMSTAR 2",
        "local_checklist": "PRISMA"
    },
    "systematic_review_prognostic": {
        "name_ru": "Систематический обзор прогностических исследований",
        "name_en": "Systematic Review of Prognostic Studies",
        "checklist": "AMSTAR 2 + ROBIS",
        "local_checklist": "PRISMA"
    },
    "genomic_study": {
        "name_ru": "Геномное исследование",
        "name_en": "Genomic/Sequence Analysis Study",
        "checklist": "Custom Genomics",
        "local_checklist": "GENOMICS"
    },
    "qualitative": {
        "name_ru": "Качественное исследование",
        "name_en": "Qualitative Research",
        "checklist": "JBI Qualitative",
        "local_checklist": None
    },
    "mixed_methods": {
        "name_ru": "Смешанное исследование",
        "name_en": "Mixed Methods Research",
        "checklist": "MMAT 2018",
        "local_checklist": None
    },
    "clinical_guidelines": {
        "name_ru": "Клинические рекомендации",
        "name_en": "Clinical Guidelines",
        "checklist": "AGREE II",
        "local_checklist": None
    },
    "economic_evaluation": {
        "name_ru": "Экономическая оценка здравоохранения",
        "name_en": "Health Economic Evaluation",
        "checklist": "CHEERS 2022",
        "local_checklist": None
    },
    "prognostic_factors": {
        "name_ru": "Исследование прогностических факторов",
        "name_en": "Prognostic Factor Study",
        "checklist": "QUIPS",
        "local_checklist": "STROBE"
    },
    "prognostic_model": {
        "name_ru": "Прогностическая модель",
        "name_en": "Prognostic Model Development/Validation",
        "checklist": "PROBAST",
        "local_checklist": "STROBE"
    },
}


class EnhancedStudyTypeDetector:
    """
    Detects study type from article text with negative context awareness.
    """

    def __init__(self):
        # ---------------------------------------------------------------
        # Detection patterns
        # Each type has:
        #   positive_patterns:  regex patterns that ADD score
        #   negative_patterns:  regex patterns that SUBTRACT score
        #   base_weight:        score per matched positive pattern
        #   disqualifiers:      patterns that set score to 0
        # ---------------------------------------------------------------
        self.patterns = {

            "randomized_controlled_trial": {
                "positive": [
                    (r'\brandomized controlled trial\b', 8),    # Explicit RCT label
                    (r'\brandomised controlled trial\b', 8),
                    (r'\b(?:double|triple|single)[- ]blind\b', 6),
                    (r'\bplacebo[- ]controlled\b', 6),
                    (r'\ballocation concealment\b', 5),
                    (r'\bintention[- ]to[- ]treat\b', 5),
                    (r'\bCONSORT\b', 5),
                    (r'\bparallel[- ]group\b', 4),
                    (r'\bcrossover trial\b', 4),
                    (r'\brandomly assigned\b', 4),
                    (r'\brandomized to\b', 4),
                    (r'\brandomised to\b', 4),
                    (r'\bblock randomi[sz]ation\b', 4),
                    (r'\bRCT\b', 3),
                ],
                "negative": [
                    # These SUBTRACT from RCT score
                    (r'\bnon[- ]?randomi[sz]ed\b', -10),  # Explicit non-randomized
                    (r'\bopen[- ]label\b', -4),             # Reduces RCT likelihood
                    (r'\bno\s+randomi[sz]ation\b', -8),
                    (r'\bwithout\s+randomi[sz]ation\b', -8),
                    (r'\bquasi[- ]experiment\b', -10),
                    (r'\buncontrolled\b', -5),
                    (r'\bno\s+control\s+group\b', -6),
                    (r'\bobservational\b', -3),
                ],
            },

            "non_randomized_intervention": {
                "positive": [
                    (r'\bnon[- ]?randomi[sz]ed\b', 8),
                    (r'\bquasi[- ]experiment(?:al)?\b', 7),
                    (r'\bopen[- ]label\b.*\btrial\b', 6),
                    (r'\bintervention(?:al)?\s+study\b', 5),
                    (r'\bpilot\s+study\b', 4),
                    (r'\bsingle[- ]arm\b', 5),
                    (r'\bbefore[- ]and[- ]after\b', 5),
                    (r'\bcontrolled\s+(?:before|clinical)\b', 4),
                    (r'\btreatment\s+group\b.*\bcontrol\s+group\b', 3),
                    (r'\bcompar(?:ed|ing)\s+(?:treatment|intervention)\b', 3),
                    (r'\bROBINS[- ]I\b', 5),
                ],
                "negative": [
                    (r'\brandomized controlled trial\b', -6),
                    (r'\bdouble[- ]blind\b', -5),
                    (r'\bplacebo[- ]controlled\b', -5),
                ],
            },

            "cohort_study": {
                "positive": [
                    (r'\bcohort\s+study\b', 8),
                    (r'\bprospective\s+cohort\b', 8),
                    (r'\bretrospective\s+cohort\b', 8),
                    (r'\blongitudinal\s+study\b', 6),
                    (r'\bfollow[- ]up\s+(?:study|period|of)\b', 4),
                    (r'\bincidence\s+(?:rate|of)\b', 4),
                    (r'\bperson[- ]years?\b', 5),
                    (r'\bhazard\s+ratio\b', 3),
                    (r'\bexposed\s+(?:and|vs|versus)\s+unexposed\b', 5),
                    (r'\bcohort\b', 3),  # Single word — lower weight
                ],
                "negative": [
                    (r'\brandomized controlled trial\b', -5),
                    (r'\bsystematic review\b', -5),
                    (r'\bmeta[- ]analysis\b', -5),
                ],
            },

            "case_control": {
                "positive": [
                    (r'\bcase[- ]control\s+study\b', 8),
                    (r'\bcases\s+and\s+controls\b', 7),
                    (r'\bodds\s+ratio\b', 4),
                    (r'\bmatched\s+controls?\b', 5),
                    (r'\bcase[- ]control\b', 5),
                    (r'\bnested\s+case[- ]control\b', 6),
                ],
                "negative": [
                    (r'\bcohort study\b', -3),
                    (r'\brandomized\b', -3),
                ],
            },

            "case_series": {
                "positive": [
                    (r'\bcase\s+series\b', 8),
                    (r'\bconsecutive\s+(?:patients|cases)\b', 5),
                    (r'\bseries\s+of\s+\d+\s+(?:patients|cases)\b', 6),
                    (r'\bno\s+control\s+group\b', 3),
                    (r'\buncontrolled\s+case\b', 5),
                ],
                "negative": [
                    (r'\brandomized\b', -4),
                    (r'\bcase[- ]control\b', -4),
                ],
            },

            "case_report": {
                "positive": [
                    (r'\bcase\s+report\b', 8),
                    (r'\bsingle\s+(?:case|patient)\b', 5),
                    (r'\bunique\s+case\b', 5),
                    (r'\brare\s+case\b', 5),
                    (r'\bwe\s+report\s+(?:a|the)\s+case\b', 6),
                    (r'\bwe\s+present\s+(?:a|the)\s+case\b', 6),
                ],
                "negative": [
                    (r'\bcase\s+series\b', -5),
                    (r'\bcohort\b', -3),
                ],
            },

            "analytical_cross_sectional": {
                "positive": [
                    (r'\bcross[- ]sectional\s+(?:study|analysis|survey)\b', 7),
                    (r'\bprevalence\s+(?:study|survey|of)\b', 5),
                    (r'\bassociation\s+between\b', 3),
                    (r'\bcross[- ]sectional\b', 4),
                ],
                "negative": [
                    (r'\blongitudinal\b', -4),
                    (r'\bfollow[- ]up\b', -3),
                    (r'\bcohort\b', -3),
                ],
            },

            "descriptive_cross_sectional": {
                "positive": [
                    (r'\bdescriptive\s+(?:study|analysis|cross[- ]sectional)\b', 6),
                    (r'\bsurvey\b.*\bprevalence\b', 5),
                    (r'\bpoint\s+prevalence\b', 5),
                    (r'\bsingle\s+time\s+point\b', 5),
                ],
                "negative": [
                    (r'\bassociation\b', -2),
                    (r'\brisk\s+factor\b', -2),
                ],
            },

            "diagnostic_accuracy": {
                "positive": [
                    (r'\bdiagnostic\s+accuracy\b', 8),
                    (r'\bsensitivity\s+and\s+specificity\b', 7),
                    (r'\bROC\s+curve\b', 6),
                    (r'\bAUC\b', 4),
                    (r'\bpositive\s+predictive\s+value\b', 5),
                    (r'\bnegative\s+predictive\s+value\b', 5),
                    (r'\bQUADAS\b', 6),
                    (r'\breference\s+standard\b', 4),
                    (r'\bgold\s+standard\b', 3),
                    (r'\bindex\s+test\b', 4),
                ],
                "negative": [],
            },

            "systematic_review_interventions": {
                "positive": [
                    (r'\bsystematic\s+review\b', 8),
                    (r'\bmeta[- ]analysis\b', 7),
                    (r'\bPRISMA\b', 6),
                    (r'\bsearch\s+strategy\b', 5),
                    (r'\bincluded\s+studies\b', 4),
                    (r'\bforest\s+plot\b', 5),
                    (r'\bpooled\s+(?:estimate|analysis|effect)\b', 5),
                    (r'\bheterogeneity\b', 3),
                    (r'\bI[²2]\s+(?:statistic|=)\b', 4),
                    (r'\bstudy\s+selection\b', 3),
                    (r'\bquality\s+assessment\b', 3),
                    (r'\brisk\s+of\s+bias\b', 3),
                ],
                "negative": [],
            },

            "systematic_review_prognostic": {
                "positive": [
                    (r'\bsystematic\s+review\b.*\bprognostic\b', 8),
                    (r'\bprognostic\b.*\bsystematic\s+review\b', 8),
                    (r'\bmeta[- ]analysis\b.*\bprognostic\b', 7),
                    (r'\bROBIS\b', 5),
                ],
                "negative": [],
            },

            "genomic_study": {
                "positive": [
                    (r'\bwhole[- ]genome\s+sequencing\b', 8),
                    (r'\bnext[- ]generation\s+sequencing\b', 7),
                    (r'\bNGS\b', 5),
                    (r'\bphylogenetic\s+analysis\b', 6),
                    (r'\bbioinformatics\b', 4),
                    (r'\bGenBank\b', 5),
                    (r'\bgenomic\s+(?:analysis|data|study)\b', 5),
                    (r'\bsequence\s+analysis\b', 4),
                    (r'\bGWAS\b', 6),
                    (r'\bgenome[- ]wide\b', 5),
                    (r'\bvariant\s+calling\b', 5),
                    (r'\bmutational\s+analysis\b', 4),
                ],
                "negative": [],
            },

            "qualitative": {
                "positive": [
                    (r'\bqualitative\s+(?:study|research|analysis)\b', 8),
                    (r'\bsemi[- ]structured\s+interviews?\b', 6),
                    (r'\bfocus\s+groups?\b', 5),
                    (r'\bthematic\s+analysis\b', 6),
                    (r'\bgrounded\s+theory\b', 6),
                    (r'\bphenomenolog(?:y|ical)\b', 5),
                    (r'\bethnograph(?:y|ic)\b', 5),
                    (r'\bnarrative\s+analysis\b', 5),
                    (r'\bcontent\s+analysis\b', 4),
                ],
                "negative": [],
            },

            "mixed_methods": {
                "positive": [
                    (r'\bmixed[- ]methods?\b', 8),
                    (r'\bquantitative\s+and\s+qualitative\b', 6),
                    (r'\bqualitative\s+and\s+quantitative\b', 6),
                    (r'\bMMR\b', 4),
                    (r'\bconvergent\s+design\b', 5),
                    (r'\bsequential\s+explanatory\b', 5),
                ],
                "negative": [],
            },

            "prognostic_factors": {
                "positive": [
                    (r'\bprognostic\s+factor\b', 8),
                    (r'\bprognostic\s+(?:value|significance|marker)\b', 6),
                    (r'\bpredictors?\s+of\s+(?:outcome|survival|mortality)\b', 5),
                    (r'\bQUIPS\b', 6),
                    (r'\bCox\s+regression\b.*\bprognostic\b', 5),
                ],
                "negative": [],
            },

            "prognostic_model": {
                "positive": [
                    (r'\bprognostic\s+model\b', 8),
                    (r'\bprediction\s+model\b', 7),
                    (r'\brisk\s+score\b', 4),
                    (r'\bnomogram\b', 5),
                    (r'\bPROBAST\b', 6),
                    (r'\bTRIPOD\b', 6),
                    (r'\bcalibration\s+(?:plot|curve)\b', 5),
                    (r'\bdiscrimination\b.*\bAUC\b', 4),
                    (r'\bvalidation\s+cohort\b', 4),
                ],
                "negative": [],
            },

            "clinical_guidelines": {
                "positive": [
                    (r'\bclinical\s+(?:practice\s+)?guideline\b', 8),
                    (r'\brecommendation\s+(?:grade|strength|level)\b', 6),
                    (r'\bAGREE\s+II\b', 6),
                    (r'\bGRADE\s+(?:approach|framework|quality)\b', 5),
                    (r'\bconsensus\s+statement\b', 4),
                    (r'\bDelphi\b', 3),
                    (r'\bevidence[- ]based\s+guideline\b', 6),
                ],
                "negative": [],
            },

            "economic_evaluation": {
                "positive": [
                    (r'\bcost[- ]effectiveness\b', 7),
                    (r'\bcost[- ]benefit\b', 6),
                    (r'\bcost[- ]utility\b', 6),
                    (r'\bQALY\b', 6),
                    (r'\bICER\b', 6),
                    (r'\bwillingness\s+to\s+pay\b', 5),
                    (r'\beconomic\s+evaluation\b', 7),
                    (r'\bCHEERS\b', 5),
                    (r'\bMarkov\s+model\b', 4),
                ],
                "negative": [],
            },
        }

    def detect(self, article_text: str) -> DetectionResult:
        """
        Detect the most likely study type from article text.

        Returns DetectionResult with best match, confidence, and full scores.
        """
        text_lower = article_text.lower()
        scores: Dict[str, float] = {}
        all_matched: Dict[str, List[str]] = {}
        warnings: List[str] = []

        for study_type, config in self.patterns.items():
            score = 0.0
            matched = []

            # Positive patterns
            for pattern, weight in config["positive"]:
                if re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL):
                    score += weight
                    matched.append(f"+{weight}: {pattern}")

            # Negative patterns (subtract from score)
            for pattern, weight in config.get("negative", []):
                if re.search(pattern, text_lower, re.IGNORECASE | re.DOTALL):
                    score += weight  # weight is already negative
                    matched.append(f"{weight}: {pattern}")

            if score > 0:
                scores[study_type] = score
                all_matched[study_type] = matched

        if not scores:
            return DetectionResult(
                study_type="unknown",
                confidence=0.0,
                matched_keywords=[],
                all_scores={},
                warnings=["No study type patterns matched."],
            )

        # Sort by score
        sorted_types = sorted(scores.items(), key=lambda x: -x[1])
        best_type, best_score = sorted_types[0]

        # Confidence: based on gap between #1 and #2
        if len(sorted_types) >= 2:
            second_score = sorted_types[1][1]
            gap = best_score - second_score
            # Higher gap = higher confidence
            confidence = min(100, (best_score / (best_score + second_score)) * 100)

            # Warn if close race
            if gap < 5:
                warnings.append(
                    f"Close match: {sorted_types[0][0]} ({sorted_types[0][1]:.0f}) "
                    f"vs {sorted_types[1][0]} ({sorted_types[1][1]:.0f})"
                )
        else:
            confidence = min(100, best_score * 5)

        return DetectionResult(
            study_type=best_type,
            confidence=round(confidence, 1),
            matched_keywords=all_matched.get(best_type, []),
            all_scores=scores,
            warnings=warnings,
        )

    def get_checklist_for_type(self, study_type: str) -> Optional[str]:
        """Get the local checklist name for a study type."""
        info = STUDY_TYPE_CHECKLISTS.get(study_type, {})
        return info.get("local_checklist")

    def get_type_info(self, study_type: str) -> Dict:
        """Get full info dict for a study type."""
        return STUDY_TYPE_CHECKLISTS.get(study_type, {})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python study_detector.py <article.txt|article.pdf>")
        sys.exit(1)

    path = sys.argv[1]

    if path.endswith('.pdf'):
        import PyPDF2
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = "\n".join(page.extract_text() for page in reader.pages)
    else:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()

    detector = EnhancedStudyTypeDetector()
    result = detector.detect(text)

    info = detector.get_type_info(result.study_type)

    print(f"\nDetected study type: {info.get('name_en', result.study_type)}")
    print(f"Confidence: {result.confidence:.0f}%")
    print(f"Recommended checklist: {info.get('checklist', 'N/A')}")
    print(f"Local checklist: {info.get('local_checklist', 'N/A')}")

    if result.warnings:
        print(f"\nWarnings:")
        for w in result.warnings:
            print(f"  ⚠ {w}")

    print(f"\nAll scores:")
    for st, score in sorted(result.all_scores.items(), key=lambda x: -x[1]):
        st_info = detector.get_type_info(st)
        print(f"  {st:40s} {score:6.1f}  -> {st_info.get('local_checklist', 'N/A')}")

    print(f"\nMatched patterns for {result.study_type}:")
    for p in result.matched_keywords:
        print(f"  {p}")
