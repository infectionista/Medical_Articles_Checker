#!/usr/bin/env python3
"""
Automatic Checklist Applier for Research Articles
Supports CONSORT, PRISMA, STROBE, and Genomics checklists
"""

import json
import re
import os
from typing import Dict, List, Tuple
from pathlib import Path
import argparse


class ChecklistApplier:
    """Main class for applying research checklists to articles"""

    def __init__(self, checklist_dir: str = "checklists"):
        """
        Initialize the checklist applier

        Args:
            checklist_dir: Directory containing checklist JSON files
        """
        self.checklist_dir = Path(checklist_dir)
        self.checklists = {}
        self.load_checklists()

    def load_checklists(self):
        """Load all available checklists from JSON files"""
        if not self.checklist_dir.exists():
            raise FileNotFoundError(f"Checklist directory not found: {self.checklist_dir}")

        for checklist_file in self.checklist_dir.glob("*.json"):
            with open(checklist_file, 'r') as f:
                checklist_data = json.load(f)
                checklist_name = checklist_data['name']
                self.checklists[checklist_name] = checklist_data
                print(f"✓ Loaded {checklist_name} checklist ({len(checklist_data['items'])} items)")

    def list_available_checklists(self) -> List[str]:
        """Return list of available checklist names"""
        return list(self.checklists.keys())

    def parse_article(self, article_path: str) -> str:
        """
        Parse article from various formats

        Args:
            article_path: Path to article file (txt, pdf, etc.)

        Returns:
            Article text content
        """
        article_path = Path(article_path)

        if not article_path.exists():
            raise FileNotFoundError(f"Article file not found: {article_path}")

        # For text files
        if article_path.suffix.lower() in ['.txt', '.md']:
            with open(article_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        # For PDF files - try to extract text
        elif article_path.suffix.lower() == '.pdf':
            return self._parse_pdf(article_path)

        else:
            raise ValueError(f"Unsupported file format: {article_path.suffix}")

    def _parse_pdf(self, pdf_path: Path) -> str:
        """
        Parse PDF file to extract text

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text
        """
        try:
            import PyPDF2
            text = ""
            with open(pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except ImportError:
            print("⚠ PyPDF2 not installed. Install with: pip install PyPDF2")
            print("  Attempting alternative PDF parsing...")

            # Fallback: try pdfplumber
            try:
                import pdfplumber
                text = ""
                with pdfplumber.open(pdf_path) as pdf:
                    for page in pdf.pages:
                        text += page.extract_text() + "\n"
                return text
            except ImportError:
                raise ImportError(
                    "PDF parsing requires PyPDF2 or pdfplumber.\n"
                    "Install with: pip install PyPDF2 or pip install pdfplumber"
                )

    def apply_checklist(self, article_text: str, checklist_name: str,
                       case_sensitive: bool = False) -> Dict:
        """
        Apply a specific checklist to an article

        Args:
            article_text: Full text of the article
            checklist_name: Name of checklist to apply (e.g., 'CONSORT', 'PRISMA')
            case_sensitive: Whether keyword matching should be case-sensitive

        Returns:
            Dictionary with checklist results
        """
        if checklist_name not in self.checklists:
            raise ValueError(
                f"Checklist '{checklist_name}' not found. "
                f"Available: {', '.join(self.list_available_checklists())}"
            )

        checklist = self.checklists[checklist_name]
        results = {
            'checklist_name': checklist['name'],
            'checklist_full_name': checklist['full_name'],
            'description': checklist['description'],
            'total_items': len(checklist['items']),
            'items_found': 0,
            'items_not_found': 0,
            'compliance_percentage': 0.0,
            'items': []
        }

        # Prepare article text for searching
        search_text = article_text if case_sensitive else article_text.lower()

        # Check each checklist item
        for item in checklist['items']:
            item_result = self._check_item(item, search_text, case_sensitive)
            results['items'].append(item_result)

            if item_result['found']:
                results['items_found'] += 1
            else:
                results['items_not_found'] += 1

        # Calculate compliance percentage
        results['compliance_percentage'] = round(
            (results['items_found'] / results['total_items']) * 100, 2
        )

        return results

    def _check_item(self, item: Dict, article_text: str,
                   case_sensitive: bool) -> Dict:
        """
        Check if a single checklist item is addressed in the article

        Args:
            item: Checklist item dictionary
            article_text: Article text (possibly lowercased)
            case_sensitive: Whether matching is case-sensitive

        Returns:
            Dictionary with item check results
        """
        keywords = item.get('keywords', [])
        found_keywords = []

        # Check each keyword
        for keyword in keywords:
            search_keyword = keyword if case_sensitive else keyword.lower()

            # Use word boundary matching for better accuracy
            pattern = r'\b' + re.escape(search_keyword) + r'\b'

            if re.search(pattern, article_text, re.IGNORECASE if not case_sensitive else 0):
                found_keywords.append(keyword)

        # Item is considered "found" if at least one keyword is present
        found = len(found_keywords) > 0

        return {
            'section': item['section'],
            'item': item['item'],
            'description': item['description'],
            'keywords': keywords,
            'found_keywords': found_keywords,
            'found': found,
            'keyword_match_rate': round(len(found_keywords) / len(keywords) * 100, 1) if keywords else 0
        }

    def generate_report(self, results: Dict, output_format: str = 'text') -> str:
        """
        Generate a formatted report from checklist results

        Args:
            results: Results dictionary from apply_checklist()
            output_format: Format for report ('text', 'markdown', 'json')

        Returns:
            Formatted report string
        """
        if output_format == 'json':
            return json.dumps(results, indent=2)

        elif output_format == 'markdown':
            return self._generate_markdown_report(results)

        else:  # text format
            return self._generate_text_report(results)

    def _generate_text_report(self, results: Dict) -> str:
        """Generate plain text report"""
        report = []
        report.append("=" * 80)
        report.append(f"{results['checklist_full_name']} ({results['checklist_name']})")
        report.append("=" * 80)
        report.append(f"Description: {results['description']}")
        report.append("")
        report.append(f"COMPLIANCE SUMMARY:")
        report.append(f"  Total items: {results['total_items']}")
        report.append(f"  Items found: {results['items_found']} ✓")
        report.append(f"  Items not found: {results['items_not_found']} ✗")
        report.append(f"  Compliance: {results['compliance_percentage']}%")
        report.append("")
        report.append("-" * 80)
        report.append("DETAILED RESULTS:")
        report.append("-" * 80)

        current_section = None
        for item in results['items']:
            if item['section'] != current_section:
                current_section = item['section']
                report.append(f"\n[{current_section}]")

            status = "✓ FOUND" if item['found'] else "✗ NOT FOUND"
            report.append(f"\n  Item {item['item']}: {status}")
            report.append(f"    Description: {item['description']}")

            if item['found']:
                report.append(f"    Matched keywords: {', '.join(item['found_keywords'])}")
                report.append(f"    Match rate: {item['keyword_match_rate']}%")
            else:
                report.append(f"    Expected keywords: {', '.join(item['keywords'][:5])}")
                if len(item['keywords']) > 5:
                    report.append(f"      ... and {len(item['keywords']) - 5} more")

        report.append("\n" + "=" * 80)
        return "\n".join(report)

    def _generate_markdown_report(self, results: Dict) -> str:
        """Generate markdown report"""
        report = []
        report.append(f"# {results['checklist_full_name']} ({results['checklist_name']})")
        report.append(f"\n**Description:** {results['description']}\n")

        report.append("## Compliance Summary\n")
        report.append(f"- **Total items:** {results['total_items']}")
        report.append(f"- **Items found:** {results['items_found']} ✓")
        report.append(f"- **Items not found:** {results['items_not_found']} ✗")
        report.append(f"- **Compliance:** {results['compliance_percentage']}%\n")

        # Progress bar
        filled = int(results['compliance_percentage'] / 5)
        bar = "█" * filled + "░" * (20 - filled)
        report.append(f"```\n{bar} {results['compliance_percentage']}%\n```\n")

        report.append("## Detailed Results\n")

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

        return "\n".join(report)

    def save_report(self, results: Dict, output_path: str, output_format: str = 'markdown'):
        """
        Save report to file

        Args:
            results: Results dictionary
            output_path: Path where to save report
            output_format: Format ('text', 'markdown', 'json')
        """
        report = self.generate_report(results, output_format)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"✓ Report saved to: {output_path}")


def main():
    """Command-line interface for the checklist applier"""
    parser = argparse.ArgumentParser(
        description='Apply research checklists to articles automatically',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Apply CONSORT checklist to an article
  python checklist_applier.py article.txt -c CONSORT

  # Apply PRISMA checklist and save markdown report
  python checklist_applier.py review.pdf -c PRISMA -o report.md -f markdown

  # List available checklists
  python checklist_applier.py --list

  # Apply genomics checklist to HIV study
  python checklist_applier.py hiv_study.txt -c GENOMICS -o genomics_report.md
        """
    )

    parser.add_argument('article', nargs='?', help='Path to article file (txt, pdf)')
    parser.add_argument('-c', '--checklist', help='Checklist to apply (CONSORT, PRISMA, STROBE, GENOMICS)')
    parser.add_argument('-o', '--output', help='Output file for report')
    parser.add_argument('-f', '--format', choices=['text', 'markdown', 'json'],
                       default='markdown', help='Output format (default: markdown)')
    parser.add_argument('--list', action='store_true', help='List available checklists')
    parser.add_argument('--case-sensitive', action='store_true',
                       help='Use case-sensitive keyword matching')

    args = parser.parse_args()

    # Initialize applier
    applier = ChecklistApplier()

    # List checklists if requested
    if args.list:
        print("\nAvailable checklists:")
        for name in applier.list_available_checklists():
            checklist = applier.checklists[name]
            print(f"  • {name}: {checklist['full_name']}")
            print(f"    {checklist['description']} ({len(checklist['items'])} items)")
        return

    # Validate arguments
    if not args.article:
        parser.error("Article file is required (use --list to see available checklists)")

    if not args.checklist:
        parser.error("Checklist name is required (-c/--checklist)")

    # Process article
    print(f"\n📄 Parsing article: {args.article}")
    article_text = applier.parse_article(args.article)
    print(f"✓ Article loaded ({len(article_text)} characters)")

    # Apply checklist
    print(f"\n📋 Applying {args.checklist} checklist...")
    results = applier.apply_checklist(
        article_text,
        args.checklist.upper(),
        case_sensitive=args.case_sensitive
    )

    # Generate and display report
    if args.output:
        applier.save_report(results, args.output, args.format)
    else:
        print("\n" + applier.generate_report(results, args.format))

    # Summary
    print(f"\n{'='*60}")
    print(f"Compliance: {results['compliance_percentage']}% "
          f"({results['items_found']}/{results['total_items']} items)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
