#!/usr/bin/env python3
"""
Detailed Checker - Automatic Study Type Detection and Checklist Application

This script automatically:
1. Analyzes an article to detect the study type
2. Finds the appropriate appraisal checklist from the reference table
3. Downloads the checklist if needed
4. Applies the appropriate evaluation
"""

import json
import re
import os
from pathlib import Path
import argparse
from typing import Dict, List, Tuple, Optional
from checklist_applier import ChecklistApplier


# Checklist mapping from checklist_table.pdf
STUDY_TYPE_CHECKLISTS = {
    "randomized_controlled_trial": {
        "name_ru": "Рандомизированное контролируемое испытание (РКИ)",
        "name_en": "Randomized Controlled Trial (RCT)",
        "checklist": "RoB 2 (Risk of Bias 2)",
        "url": "https://www.riskofbias.info/welcome/rob-2-0-tool/current-version-of-rob-2",
        "description": "Risk of bias assessment tool for RCTs",
        "local_checklist": "CONSORT"  # Our implemented equivalent
    },
    "non_randomized_intervention": {
        "name_ru": "Нерандомизированное интервенционное исследование",
        "name_en": "Non-randomized Interventional Study",
        "checklist": "ROBINS-I",
        "url": "https://www.riskofbias.info/welcome/robins-i-v2",
        "description": "Risk of bias in non-randomized studies",
        "local_checklist": "STROBE"
    },
    "cohort_study": {
        "name_ru": "Когортное исследование",
        "name_en": "Cohort Study",
        "checklist": "ROBINS-I",
        "url": "https://www.riskofbias.info/welcome/robins-i-v2",
        "description": "Assessment for cohort studies",
        "local_checklist": "STROBE"
    },
    "case_control": {
        "name_ru": "Исследование типа случай-контроль",
        "name_en": "Case-Control Study",
        "checklist": "JBI Case-Control",
        "url": "https://jbi.global/critical-appraisal-tools",
        "description": "JBI checklist for case-control studies",
        "local_checklist": "STROBE"
    },
    "analytical_cross_sectional": {
        "name_ru": "Аналитическое поперечное исследование",
        "name_en": "Analytical Cross-Sectional Study",
        "checklist": "JBI Analytical Cross-Sectional",
        "url": "https://jbi.global/critical-appraisal-tools",
        "description": "JBI checklist for analytical cross-sectional studies",
        "local_checklist": "STROBE"
    },
    "descriptive_cross_sectional": {
        "name_ru": "Описательное поперечное исследование",
        "name_en": "Descriptive Cross-Sectional Study",
        "checklist": "JBI Cross-Sectional",
        "url": "https://jbi.global/critical-appraisal-tools",
        "description": "JBI checklist for descriptive cross-sectional studies",
        "local_checklist": "STROBE"
    },
    "case_series": {
        "name_ru": "Серия клинических случаев",
        "name_en": "Case Series",
        "checklist": "JBI Case Series",
        "url": "https://jbi.global/critical-appraisal-tools",
        "description": "JBI checklist for case series",
        "local_checklist": "STROBE"
    },
    "case_report": {
        "name_ru": "Один клинический случай",
        "name_en": "Case Report",
        "checklist": "JBI Case Report",
        "url": "https://jbi.global/critical-appraisal-tools",
        "description": "JBI checklist for single case reports",
        "local_checklist": "STROBE"
    },
    "diagnostic_accuracy": {
        "name_ru": "Исследование точности диагностики",
        "name_en": "Diagnostic Accuracy Study",
        "checklist": "QUADAS-2",
        "url": "https://www.bristol.ac.uk/media-library/sites/quadas/migrated/documents/quadas2.pdf",
        "description": "Standard tool for diagnostic accuracy studies",
        "local_checklist": "STROBE"
    },
    "prognostic_factors": {
        "name_ru": "Исследование прогностических факторов",
        "name_en": "Prognostic Factor Study",
        "checklist": "QUIPS",
        "url": "https://methods.cochrane.org/sites/methods.cochrane.org.prognosis/files/uploads/QUIPS%20tool.pdf",
        "description": "Quality assessment tool for prognostic studies",
        "local_checklist": "STROBE"
    },
    "prognostic_model": {
        "name_ru": "Разработка/валидация прогностической модели",
        "name_en": "Prognostic Model Development/Validation",
        "checklist": "PROBAST",
        "url": "https://www.probast.org/wp-content/uploads/2020/02/PROBAST_20190515.pdf",
        "description": "Risk of bias tool for prognostic models",
        "local_checklist": "STROBE"
    },
    "systematic_review_interventions": {
        "name_ru": "Систематический обзор вмешательств",
        "name_en": "Systematic Review of Interventions",
        "checklist": "AMSTAR 2",
        "url": "https://amstar.ca",
        "description": "Quality assessment for systematic reviews",
        "local_checklist": "PRISMA"
    },
    "systematic_review_prognostic": {
        "name_ru": "Систематический обзор прогностических исследований/моделей",
        "name_en": "Systematic Review of Prognostic Studies/Models",
        "checklist": "AMSTAR 2 + ROBIS",
        "url": "https://www.bristol.ac.uk/population-health-sciences/projects/robis/robis-tool/",
        "description": "For reviews of prognostic studies and models",
        "local_checklist": "PRISMA"
    },
    "clinical_guidelines": {
        "name_ru": "Клинические рекомендации",
        "name_en": "Clinical Guidelines",
        "checklist": "AGREE II",
        "url": "https://www.agreetrust.org/wp-content/uploads/2017/12/AGREE-II-Users-Manual-and-23-item-Instrument-2009-Update-2017.pdf",
        "description": "Tool for assessing clinical guidelines quality",
        "local_checklist": None
    },
    "economic_evaluation": {
        "name_ru": "Экономическая оценка здравоохранения",
        "name_en": "Health Economic Evaluation",
        "checklist": "CHEERS 2022",
        "url": "https://www.equator-network.org/wp-content/uploads/2013/04/CHEERS-2022-checklist-1.pdf",
        "description": "Checklist for economic evaluation reports",
        "local_checklist": None
    },
    "qualitative": {
        "name_ru": "Качественное исследование",
        "name_en": "Qualitative Research",
        "checklist": "JBI Qualitative",
        "url": "https://jbi.global/critical-appraisal-tools",
        "description": "JBI checklist for qualitative research",
        "local_checklist": None
    },
    "mixed_methods": {
        "name_ru": "Смешанное исследование",
        "name_en": "Mixed Methods Research",
        "checklist": "MMAT 2018",
        "url": "https://mixedmethodsappraisaltoolpublic.pbworks.com/w/file/fetch/127916259/MMAT_2018_criteria-manual_2018-08-01_ENG.pdf",
        "description": "Mixed methods appraisal tool",
        "local_checklist": None
    },
    "genomic_study": {
        "name_ru": "Геномное исследование",
        "name_en": "Genomic/Sequence Analysis Study",
        "checklist": "Custom Genomics",
        "url": None,
        "description": "Custom genomics reporting checklist",
        "local_checklist": "GENOMICS"
    }
}


class StudyTypeDetector:
    """Detects study type from article text"""

    def __init__(self):
        # Keywords for detecting different study types
        self.detection_patterns = {
            "randomized_controlled_trial": {
                "keywords": [
                    r'\brandom(?:i[sz]ed|i[sz]ation)\b',
                    r'\bRCT\b',
                    r'\btrial\b',
                    r'\bcontrolled trial\b',
                    r'\bparallel.group\b',
                    r'\bintention.to.treat\b',
                    r'\ballocation concealment\b'
                ],
                "weight": 5
            },
            "systematic_review_interventions": {
                "keywords": [
                    r'\bsystematic review\b',
                    r'\bmeta.analysis\b',
                    r'\bPRISMA\b',
                    r'\bsearch strategy\b',
                    r'\bincluded studies\b',
                    r'\bforest plot\b',
                    r'\bpooled estimate\b'
                ],
                "weight": 5
            },
            "cohort_study": {
                "keywords": [
                    r'\bcohort\b',
                    r'\bprospective\b',
                    r'\bretrospecti(?:ve|vely)\b',
                    r'\bfollow.up\b',
                    r'\bincidence\b',
                    r'\blongitudinal\b'
                ],
                "weight": 4
            },
            "case_control": {
                "keywords": [
                    r'\bcase.control\b',
                    r'\bcases and controls\b',
                    r'\bodds ratio\b',
                    r'\bmatched\b',
                    r'\bretrospective\b'
                ],
                "weight": 4
            },
            "case_series": {
                "keywords": [
                    r'\bcase series\b',
                    r'\bconsecutive (?:patients|cases)\b',
                    r'\bseries of \d+',
                    r'\b\d+ (?:patients|cases|children)\b',
                    r'\bno control\b'
                ],
                "weight": 3
            },
            "case_report": {
                "keywords": [
                    r'\bcase report\b',
                    r'\bsingle (?:case|patient)\b',
                    r'\bunique case\b',
                    r'\brare case\b'
                ],
                "weight": 3
            },
            "cross_sectional": {
                "keywords": [
                    r'\bcross.sectional\b',
                    r'\bprevalence\b',
                    r'\bsurvey\b',
                    r'\bsingle time point\b'
                ],
                "weight": 3
            },
            "diagnostic_accuracy": {
                "keywords": [
                    r'\bdiagnostic accuracy\b',
                    r'\bsensitivity and specificity\b',
                    r'\bROC curve\b',
                    r'\bAUC\b',
                    r'\bpositive predictive value\b',
                    r'\bnegative predictive value\b'
                ],
                "weight": 5
            },
            "genomic_study": {
                "keywords": [
                    r'\bsequenc(?:ing|e analysis)\b',
                    r'\bgenome\b',
                    r'\bgenomic\b',
                    r'\bphylogenetic\b',
                    r'\bbioinformatics\b',
                    r'\bNext.Generation Sequencing\b',
                    r'\bNGS\b',
                    r'\bGenBank\b'
                ],
                "weight": 4
            },
            "qualitative": {
                "keywords": [
                    r'\bqualitative\b',
                    r'\binterviews\b',
                    r'\bfocus groups\b',
                    r'\bthematic analysis\b',
                    r'\bgrounded theory\b',
                    r'\bphenomenology\b'
                ],
                "weight": 5
            }
        }

    def detect_study_type(self, article_text: str) -> Tuple[str, float, List[str]]:
        """
        Detect the most likely study type from article text

        Args:
            article_text: Full text of the article

        Returns:
            Tuple of (study_type, confidence_score, matched_keywords)
        """
        text_lower = article_text.lower()
        scores = {}
        matched_keywords = {}

        for study_type, pattern_info in self.detection_patterns.items():
            score = 0
            matches = []

            for pattern in pattern_info['keywords']:
                if re.search(pattern, text_lower, re.IGNORECASE):
                    score += pattern_info['weight']
                    matches.append(pattern)

            if score > 0:
                scores[study_type] = score
                matched_keywords[study_type] = matches

        if not scores:
            return "unknown", 0.0, []

        # Get the study type with highest score
        best_match = max(scores.items(), key=lambda x: x[1])
        study_type = best_match[0]
        score = best_match[1]

        # Calculate confidence (normalized)
        max_possible = len(self.detection_patterns[study_type]['keywords']) * \
                      self.detection_patterns[study_type]['weight']
        confidence = min(100, (score / max_possible) * 100)

        return study_type, confidence, matched_keywords.get(study_type, [])


class DetailedChecker:
    """Advanced checker with automatic study type detection"""

    def __init__(self, checklist_dir: str = "checklists"):
        self.detector = StudyTypeDetector()
        self.applier = ChecklistApplier(checklist_dir)
        self.study_type_map = STUDY_TYPE_CHECKLISTS

    def analyze_article(self, article_path: str, output_dir: str = "reports",
                       auto_detect: bool = True, force_type: Optional[str] = None) -> Dict:
        """
        Analyze article with automatic study type detection

        Args:
            article_path: Path to article file
            output_dir: Directory for output reports
            auto_detect: Whether to auto-detect study type
            force_type: Force a specific study type (overrides auto-detection)

        Returns:
            Analysis results dictionary
        """
        print(f"\n{'='*80}")
        print("DETAILED ARTICLE CHECKER")
        print(f"{'='*80}\n")

        # Parse article
        print(f"📄 Parsing article: {article_path}")
        article_text = self.applier.parse_article(article_path)
        print(f"✓ Article loaded ({len(article_text)} characters)\n")

        # Detect study type
        if force_type:
            study_type = force_type
            confidence = 100.0
            matched_keywords = []
            print(f"🔧 Forced study type: {study_type}")
        elif auto_detect:
            print("🔍 Detecting study type...")
            study_type, confidence, matched_keywords = self.detector.detect_study_type(article_text)
            print(f"✓ Detected: {study_type} (confidence: {confidence:.1f}%)")
            print(f"  Matched patterns: {len(matched_keywords)}")
        else:
            study_type = "unknown"
            confidence = 0.0
            matched_keywords = []

        # Get checklist information
        checklist_info = self.study_type_map.get(study_type, {})

        if not checklist_info:
            print(f"\n⚠ Unknown study type. Using default checklist (STROBE).")
            local_checklist = "STROBE"
        else:
            local_checklist = checklist_info.get("local_checklist", "STROBE")
            print(f"\n📋 Study Type: {checklist_info.get('name_en', study_type)}")
            print(f"   Recommended checklist: {checklist_info.get('checklist', 'N/A')}")
            print(f"   URL: {checklist_info.get('url', 'N/A')}")
            print(f"   Using local equivalent: {local_checklist}")

        # Apply checklist
        if local_checklist and local_checklist in self.applier.list_available_checklists():
            print(f"\n📊 Applying {local_checklist} checklist...")
            results = self.applier.apply_checklist(article_text, local_checklist)

            # Add study type information to results
            results['detected_study_type'] = study_type
            results['detection_confidence'] = confidence
            results['matched_keywords'] = matched_keywords
            results['recommended_checklist'] = checklist_info.get('checklist', 'N/A')
            results['checklist_url'] = checklist_info.get('url', 'N/A')

            # Create output directory
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)

            # Generate filename
            article_name = Path(article_path).stem
            report_file = output_path / f"{article_name}_detailed_report.md"
            json_file = output_path / f"{article_name}_detailed_results.json"

            # Save markdown report
            report = self._generate_detailed_report(results, checklist_info)
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"\n✓ Report saved: {report_file}")

            # Save JSON results
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, indent=2)
            print(f"✓ JSON saved: {json_file}")

            print(f"\n{'='*80}")
            print(f"Compliance: {results['compliance_percentage']}% "
                  f"({results['items_found']}/{results['total_items']} items)")
            print(f"{'='*80}\n")

            return results
        else:
            print(f"\n❌ Local checklist '{local_checklist}' not available.")
            print(f"   Recommended: Download from {checklist_info.get('url', 'N/A')}")
            return {
                'detected_study_type': study_type,
                'detection_confidence': confidence,
                'recommended_checklist': checklist_info.get('checklist', 'N/A'),
                'checklist_url': checklist_info.get('url', 'N/A'),
                'error': 'Local checklist not available'
            }

    def _generate_detailed_report(self, results: Dict, checklist_info: Dict) -> str:
        """Generate detailed markdown report with study type information"""
        report = []

        report.append(f"# Detailed Article Analysis Report\n")
        report.append(f"**Analysis Date:** {Path.cwd()}\n")

        # Study Type Detection Section
        report.append("## Study Type Detection\n")
        report.append(f"- **Detected Type:** {checklist_info.get('name_en', results['detected_study_type'])}")
        report.append(f"- **Confidence:** {results.get('detection_confidence', 0):.1f}%")
        report.append(f"- **Matched Patterns:** {len(results.get('matched_keywords', []))}\n")

        # Recommended Checklist Section
        report.append("## Recommended Appraisal Checklist\n")
        report.append(f"- **Checklist:** {results.get('recommended_checklist', 'N/A')}")
        report.append(f"- **URL:** {results.get('checklist_url', 'N/A')}")
        report.append(f"- **Description:** {checklist_info.get('description', 'N/A')}")
        report.append(f"- **Local Equivalent Used:** {results['checklist_name']}\n")

        # Compliance Summary
        report.append("## Compliance Summary\n")
        report.append(f"- **Total items:** {results['total_items']}")
        report.append(f"- **Items found:** {results['items_found']} ✓")
        report.append(f"- **Items not found:** {results['items_not_found']} ✗")
        report.append(f"- **Compliance:** {results['compliance_percentage']}%\n")

        # Progress bar
        filled = int(results['compliance_percentage'] / 5)
        bar = "█" * filled + "░" * (20 - filled)
        report.append(f"```\n{bar} {results['compliance_percentage']}%\n```\n")

        # Detailed Results
        report.append("## Detailed Checklist Results\n")

        current_section = None
        for item in results['items']:
            if item['section'] != current_section:
                current_section = item['section']
                report.append(f"\n### {current_section}\n")

            status = "✅" if item['found'] else "❌"
            report.append(f"{status} **Item {item['item']}:** {item['description']}")

            if item['found']:
                report.append(f"   - Matched keywords: `{', '.join(item['found_keywords'])}`")
                report.append(f"   - Match rate: {item['keyword_match_rate']}%")
            else:
                keywords_preview = ', '.join(item['keywords'][:3])
                report.append(f"   - Expected keywords: `{keywords_preview}`...")
            report.append("")

        # Recommendations
        report.append("\n## Recommendations\n")
        report.append("For complete appraisal of this study type, consider using:")
        report.append(f"- **{results.get('recommended_checklist', 'N/A')}**")
        report.append(f"- Download from: {results.get('checklist_url', 'N/A')}\n")

        if results['items_not_found'] > 0:
            report.append("### Missing Items to Address:\n")
            missing_count = 0
            for item in results['items']:
                if not item['found'] and missing_count < 5:
                    report.append(f"{missing_count + 1}. {item['description']}")
                    missing_count += 1
            if results['items_not_found'] > 5:
                report.append(f"   ... and {results['items_not_found'] - 5} more items\n")

        return "\n".join(report)


def main():
    """Command-line interface"""
    parser = argparse.ArgumentParser(
        description='Detailed Article Checker with Automatic Study Type Detection',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect study type and apply appropriate checklist
  python detailed_check.py article.pdf

  # Force specific study type
  python detailed_check.py article.pdf --type case_series

  # Specify output directory
  python detailed_check.py article.pdf -o reports/my_study

  # List available study types
  python detailed_check.py --list-types
        """
    )

    parser.add_argument('article', nargs='?', help='Path to article file')
    parser.add_argument('-o', '--output', default='reports',
                       help='Output directory for reports (default: reports)')
    parser.add_argument('--type', help='Force specific study type')
    parser.add_argument('--no-auto-detect', action='store_true',
                       help='Disable automatic study type detection')
    parser.add_argument('--list-types', action='store_true',
                       help='List available study types')

    args = parser.parse_args()

    # List types if requested
    if args.list_types:
        print("\nAvailable Study Types:\n")
        for key, info in STUDY_TYPE_CHECKLISTS.items():
            print(f"  {key}")
            print(f"    EN: {info['name_en']}")
            print(f"    Checklist: {info['checklist']}")
            print(f"    Local: {info.get('local_checklist', 'N/A')}")
            print()
        return

    if not args.article:
        parser.error("Article file is required (use --list-types to see available study types)")

    # Run detailed check
    checker = DetailedChecker()
    checker.analyze_article(
        args.article,
        output_dir=args.output,
        auto_detect=not args.no_auto_detect,
        force_type=args.type
    )


if __name__ == "__main__":
    main()
