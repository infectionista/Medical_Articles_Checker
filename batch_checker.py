#!/usr/bin/env python3
"""
Batch Checklist Applier - Apply checklists to multiple articles at once
"""

import argparse
import os
from pathlib import Path
import json
from checklist_applier import ChecklistApplier


def process_directory(input_dir: str, checklist_name: str, output_dir: str,
                     output_format: str = 'markdown', file_pattern: str = '*.txt'):
    """
    Process all articles in a directory

    Args:
        input_dir: Directory containing article files
        checklist_name: Checklist to apply
        output_dir: Directory for output reports
        output_format: Format for reports
        file_pattern: Glob pattern for article files
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)

    # Create output directory if it doesn't exist
    output_path.mkdir(parents=True, exist_ok=True)

    # Initialize applier
    applier = ChecklistApplier()

    # Find all matching files
    article_files = list(input_path.glob(file_pattern))

    if not article_files:
        print(f"⚠ No files found matching pattern '{file_pattern}' in {input_dir}")
        return

    print(f"\n{'='*70}")
    print(f"Batch Processing: {len(article_files)} articles")
    print(f"Checklist: {checklist_name}")
    print(f"Output format: {output_format}")
    print(f"{'='*70}\n")

    results_summary = []

    for i, article_file in enumerate(article_files, 1):
        print(f"[{i}/{len(article_files)}] Processing: {article_file.name}")

        try:
            # Parse article
            article_text = applier.parse_article(str(article_file))

            # Apply checklist
            results = applier.apply_checklist(article_text, checklist_name)

            # Generate output filename
            output_filename = article_file.stem + f"_{checklist_name.lower()}_report"

            if output_format == 'markdown':
                output_filename += '.md'
            elif output_format == 'json':
                output_filename += '.json'
            else:
                output_filename += '.txt'

            output_file = output_path / output_filename

            # Save report
            applier.save_report(results, str(output_file), output_format)

            # Track summary
            results_summary.append({
                'article': article_file.name,
                'checklist': checklist_name,
                'compliance': results['compliance_percentage'],
                'items_found': results['items_found'],
                'total_items': results['total_items'],
                'report_file': output_filename
            })

            print(f"  ✓ Compliance: {results['compliance_percentage']}% "
                  f"({results['items_found']}/{results['total_items']} items)")
            print(f"  ✓ Report saved: {output_file}")

        except Exception as e:
            print(f"  ✗ Error processing {article_file.name}: {e}")
            results_summary.append({
                'article': article_file.name,
                'error': str(e)
            })

        print()

    # Save summary report
    summary_file = output_path / f"batch_summary_{checklist_name.lower()}.json"
    with open(summary_file, 'w') as f:
        json.dump({
            'checklist': checklist_name,
            'total_articles': len(article_files),
            'results': results_summary
        }, f, indent=2)

    print(f"\n{'='*70}")
    print(f"Batch processing complete!")
    print(f"Summary saved to: {summary_file}")
    print(f"{'='*70}\n")

    # Print summary statistics
    successful = [r for r in results_summary if 'compliance' in r]
    if successful:
        avg_compliance = sum(r['compliance'] for r in successful) / len(successful)
        print(f"Average compliance: {avg_compliance:.2f}%")
        print(f"Successful: {len(successful)}/{len(article_files)}")


def main():
    """Command-line interface for batch processing"""
    parser = argparse.ArgumentParser(
        description='Apply checklists to multiple research articles',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all .txt files in articles/ directory with CONSORT checklist
  python batch_checker.py articles/ -c CONSORT -o reports/

  # Process PDF files with PRISMA checklist
  python batch_checker.py reviews/ -c PRISMA -o reports/ -p "*.pdf"

  # Generate JSON reports
  python batch_checker.py data/ -c STROBE -o output/ -f json
        """
    )

    parser.add_argument('input_dir', help='Directory containing article files')
    parser.add_argument('-c', '--checklist', required=True,
                       help='Checklist to apply (CONSORT, PRISMA, STROBE, GENOMICS)')
    parser.add_argument('-o', '--output-dir', required=True,
                       help='Directory for output reports')
    parser.add_argument('-f', '--format', choices=['text', 'markdown', 'json'],
                       default='markdown', help='Output format (default: markdown)')
    parser.add_argument('-p', '--pattern', default='*.txt',
                       help='File pattern to match (default: *.txt)')

    args = parser.parse_args()

    process_directory(
        args.input_dir,
        args.checklist.upper(),
        args.output_dir,
        args.format,
        args.pattern
    )


if __name__ == "__main__":
    main()
