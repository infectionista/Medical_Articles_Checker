#!/usr/bin/env python3
"""
Evaluation Pipeline — compares system output against ground truth annotations.

Usage:
  # Evaluate all annotated articles:
  python evaluate.py

  # Evaluate a specific article (by annotation file):
  python evaluate.py eval_corpus/annotations/gautret_2020_hydroxychloroquine.json

  # Evaluate with verbose per-item breakdown:
  python evaluate.py -v

  # Export results to JSON:
  python evaluate.py -o eval_results.json

Workflow:
  1. Place article PDFs in eval_corpus/articles/
  2. Fill in an annotation JSON (copy _TEMPLATE.json)
  3. Run this script
  4. Review disagreements, fix bugs or update annotations
"""

import json
import sys
import os
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from enhanced_checker import EnhancedChecker
from study_detector import EnhancedStudyTypeDetector


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ItemComparison:
    """Comparison of system vs ground truth for a single checklist item."""
    item_id: str
    ground_truth: Optional[bool]  # True/False/None
    system_verdict: str           # present/partial/absent/explicitly_absent
    system_confidence: float
    match: bool                   # System agrees with ground truth?
    category: str                 # TP, TN, FP, FN, SKIPPED
    gt_notes: str                 # Annotator's notes
    system_keywords: List[str]    # Keywords the system matched


@dataclass
class ArticleEvaluation:
    """Full evaluation result for one article."""
    article_id: str
    article_title: str

    # Study type detection
    expected_type: str
    detected_type: str
    type_correct: bool
    expected_checklist: str
    detected_checklist: str
    checklist_correct: bool

    # Per-item results
    comparisons: List[ItemComparison]

    # Aggregate metrics
    total_items: int
    evaluated_items: int    # Excluding null ground truth
    tp: int                 # True positives
    tn: int                 # True negatives
    fp: int                 # False positives
    fn: int                 # False negatives

    @property
    def recall(self) -> float:
        """Sensitivity: TP / (TP + FN)"""
        denom = self.tp + self.fn
        return self.tp / denom if denom > 0 else 0.0

    @property
    def specificity(self) -> float:
        """Specificity: TN / (TN + FP)"""
        denom = self.tn + self.fp
        return self.tn / denom if denom > 0 else 0.0

    @property
    def precision(self) -> float:
        """Precision: TP / (TP + FP)"""
        denom = self.tp + self.fp
        return self.tp / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        """F1 score: harmonic mean of precision and recall"""
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def accuracy(self) -> float:
        """Overall accuracy: (TP + TN) / total evaluated"""
        return (self.tp + self.tn) / self.evaluated_items if self.evaluated_items > 0 else 0.0


# ---------------------------------------------------------------------------
# Evaluation logic
# ---------------------------------------------------------------------------

class Evaluator:
    """Runs the checker against articles and compares with ground truth."""

    def __init__(self, checklist_dir: str = "checklists"):
        self.checker = EnhancedChecker(checklist_dir=checklist_dir)
        self.detector = EnhancedStudyTypeDetector()

    def evaluate_article(
        self,
        annotation_path: str,
        article_text: Optional[str] = None,
    ) -> ArticleEvaluation:
        """
        Evaluate one article against its ground truth annotation.

        Args:
            annotation_path: Path to annotation JSON
            article_text: If provided, use this text. Otherwise, try to read
                          the PDF/TXT referenced in the annotation.
        """
        # Load annotation
        with open(annotation_path, 'r', encoding='utf-8') as f:
            annotation = json.load(f)

        article_info = annotation['article']
        article_id = article_info['id']
        article_title = article_info['title']

        # Load article text if not provided
        if article_text is None:
            article_file = article_info.get('file', '')
            # Try relative to eval_corpus dir, then to project root
            for base in [Path(annotation_path).parent.parent, Path('.')]:
                full_path = base / article_file
                if full_path.exists():
                    article_text = self._read_article(str(full_path))
                    break
            if article_text is None:
                print(f"  WARNING: Article file not found: {article_file}")
                print(f"  Running evaluation on annotation-only mode (no system check)")
                return self._annotation_only_eval(annotation)

        # --- Study type detection ---
        expected_type = annotation['study_type']['expected_type']
        expected_checklist = annotation['study_type']['expected_checklist']

        detection = self.detector.detect(article_text)
        detected_type = detection.study_type
        detected_checklist = self.detector.get_checklist_for_type(detected_type) or 'STROBE'

        type_correct = detected_type == expected_type
        checklist_correct = detected_checklist == expected_checklist

        # --- Checklist evaluation ---
        # Determine which checklist items to compare
        checklist_key = f"{expected_checklist.lower()}_items"
        if expected_checklist == 'CONSORT':
            checklist_key = 'consort_items'
        elif expected_checklist == 'STROBE':
            checklist_key = 'strobe_items'
        elif expected_checklist == 'PRISMA':
            checklist_key = 'prisma_items'

        gt_items = annotation.get(checklist_key, annotation.get('consort_items', {}))

        # Run the checker with the expected checklist
        checklist_name = expected_checklist
        if checklist_name not in self.checker.list_checklists():
            checklist_name = 'CONSORT'  # Fallback

        result = self.checker.check(article_text, checklist_name)

        # Compare per-item
        comparisons = []
        tp = tn = fp = fn = 0
        evaluated = 0

        for sys_item in result.items:
            item_id = sys_item.item_id
            gt = gt_items.get(item_id, {})

            gt_present = gt.get('present') if isinstance(gt, dict) else gt
            gt_notes = gt.get('notes', '') if isinstance(gt, dict) else ''

            # System verdict → binary
            sys_present = sys_item.verdict in ('present', 'partial')

            # Skip items with null ground truth
            if gt_present is None:
                category = 'SKIPPED'
                match = True  # Don't count
            elif gt_present and sys_present:
                category = 'TP'
                tp += 1
                evaluated += 1
                match = True
            elif not gt_present and not sys_present:
                category = 'TN'
                tn += 1
                evaluated += 1
                match = True
            elif not gt_present and sys_present:
                category = 'FP'
                fp += 1
                evaluated += 1
                match = False
            else:  # gt_present and not sys_present
                category = 'FN'
                fn += 1
                evaluated += 1
                match = False

            comparisons.append(ItemComparison(
                item_id=item_id,
                ground_truth=gt_present,
                system_verdict=sys_item.verdict,
                system_confidence=sys_item.confidence,
                match=match,
                category=category,
                gt_notes=gt_notes,
                system_keywords=sys_item.matched_keywords,
            ))

        return ArticleEvaluation(
            article_id=article_id,
            article_title=article_title,
            expected_type=expected_type,
            detected_type=detected_type,
            type_correct=type_correct,
            expected_checklist=expected_checklist,
            detected_checklist=detected_checklist,
            checklist_correct=checklist_correct,
            comparisons=comparisons,
            total_items=len(comparisons),
            evaluated_items=evaluated,
            tp=tp, tn=tn, fp=fp, fn=fn,
        )

    def _read_article(self, path: str) -> str:
        """Read article text from PDF or TXT."""
        if path.lower().endswith('.pdf'):
            try:
                import PyPDF2
                with open(path, 'rb') as f:
                    reader = PyPDF2.PdfReader(f)
                    return '\n'.join(page.extract_text() for page in reader.pages)
            except Exception as e:
                print(f"  Error reading PDF: {e}")
                return ""
        else:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

    def _annotation_only_eval(self, annotation: dict) -> ArticleEvaluation:
        """Create a stub evaluation when article file is not available."""
        info = annotation['article']
        st = annotation['study_type']
        return ArticleEvaluation(
            article_id=info['id'],
            article_title=info['title'],
            expected_type=st['expected_type'],
            detected_type='(no article)',
            type_correct=False,
            expected_checklist=st['expected_checklist'],
            detected_checklist='(no article)',
            checklist_correct=False,
            comparisons=[],
            total_items=0, evaluated_items=0,
            tp=0, tn=0, fp=0, fn=0,
        )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_article_report(eval_result: ArticleEvaluation, verbose: bool = False):
    """Print evaluation results for one article."""

    e = eval_result
    print(f"\n{'='*70}")
    print(f"  {e.article_title}")
    print(f"  [{e.article_id}]")
    print(f"{'='*70}")

    # Study type
    type_icon = '\u2705' if e.type_correct else '\u274c'
    cl_icon = '\u2705' if e.checklist_correct else '\u274c'
    print(f"\n  Study type:  {type_icon} expected={e.expected_type}, detected={e.detected_type}")
    print(f"  Checklist:   {cl_icon} expected={e.expected_checklist}, detected={e.detected_checklist}")

    if e.evaluated_items == 0:
        print(f"\n  No items evaluated (article file not found?)")
        return

    # Confusion matrix
    print(f"\n  Confusion matrix ({e.evaluated_items} items evaluated):")
    print(f"  ┌─────────────┬────────────────────────────────┐")
    print(f"  │             │ Ground truth Present │ Absent  │")
    print(f"  ├─────────────┼──────────────────────┼─────────┤")
    print(f"  │ Sys Present │ TP = {e.tp:3d}             │ FP = {e.fp:2d} │")
    print(f"  │ Sys Absent  │ FN = {e.fn:3d}             │ TN = {e.tn:2d} │")
    print(f"  └─────────────┴──────────────────────┴─────────┘")

    # Metrics
    print(f"\n  Recall (sensitivity): {e.recall:.1%}  — of {e.tp+e.fn} present items, found {e.tp}")
    print(f"  Specificity:          {e.specificity:.1%}  — of {e.tn+e.fp} absent items, correctly rejected {e.tn}")
    print(f"  Precision:            {e.precision:.1%}  — of {e.tp+e.fp} system 'present', {e.tp} truly present")
    print(f"  F1 score:             {e.f1:.1%}")
    print(f"  Accuracy:             {e.accuracy:.1%}")

    # Errors
    fps = [c for c in e.comparisons if c.category == 'FP']
    fns = [c for c in e.comparisons if c.category == 'FN']

    if fps:
        print(f"\n  FALSE POSITIVES (system found, but absent in ground truth):")
        for c in fps:
            print(f"    {c.item_id}: system={c.system_verdict} (conf={c.system_confidence:.0%})")
            print(f"      keywords: {c.system_keywords[:3]}")
            if c.gt_notes:
                print(f"      annotator: {c.gt_notes}")

    if fns:
        print(f"\n  FALSE NEGATIVES (system missed, but present in ground truth):")
        for c in fns:
            print(f"    {c.item_id}: system={c.system_verdict} (conf={c.system_confidence:.0%})")
            if c.gt_notes:
                print(f"      annotator: {c.gt_notes}")

    if verbose:
        print(f"\n  ALL ITEMS:")
        for c in e.comparisons:
            gt_str = {True: 'present', False: 'absent', None: 'N/A'}[c.ground_truth]
            icon = {
                'TP': '\u2705', 'TN': '\u2705',
                'FP': '\U0001f534', 'FN': '\U0001f534',
                'SKIPPED': '\u2796',
            }.get(c.category, '?')
            print(f"    {icon} {c.item_id:5s} gt={gt_str:8s} sys={c.system_verdict:18s} "
                  f"conf={c.system_confidence:.0%}  [{c.category}]")


def print_aggregate_report(evaluations: List[ArticleEvaluation]):
    """Print aggregate metrics across all articles."""
    print(f"\n{'='*70}")
    print(f"  AGGREGATE METRICS ({len(evaluations)} articles)")
    print(f"{'='*70}")

    total_tp = sum(e.tp for e in evaluations)
    total_tn = sum(e.tn for e in evaluations)
    total_fp = sum(e.fp for e in evaluations)
    total_fn = sum(e.fn for e in evaluations)
    total_eval = sum(e.evaluated_items for e in evaluations)
    type_correct = sum(1 for e in evaluations if e.type_correct)
    cl_correct = sum(1 for e in evaluations if e.checklist_correct)

    print(f"\n  Study type detection: {type_correct}/{len(evaluations)} correct")
    print(f"  Checklist selection:  {cl_correct}/{len(evaluations)} correct")

    if total_eval > 0:
        recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0
        spec = total_tn / (total_tn + total_fp) if (total_tn + total_fp) > 0 else 0
        prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0
        f1 = 2 * prec * recall / (prec + recall) if (prec + recall) > 0 else 0
        acc = (total_tp + total_tn) / total_eval

        print(f"\n  Pooled metrics ({total_eval} item-level comparisons):")
        print(f"    Recall:      {recall:.1%}  (TP={total_tp}, FN={total_fn})")
        print(f"    Specificity: {spec:.1%}  (TN={total_tn}, FP={total_fp})")
        print(f"    Precision:   {prec:.1%}")
        print(f"    F1:          {f1:.1%}")
        print(f"    Accuracy:    {acc:.1%}")

    # Per-article summary table
    print(f"\n  Per-article summary:")
    print(f"  {'Article':<40s} {'Recall':>8s} {'Spec':>8s} {'F1':>8s} {'Type':>6s}")
    print(f"  {'-'*40} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
    for e in evaluations:
        type_ok = '\u2705' if e.type_correct else '\u274c'
        print(f"  {e.article_id:<40s} {e.recall:>7.0%} {e.specificity:>7.0%} "
              f"{e.f1:>7.0%} {type_ok:>6s}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Evaluate Article Checker against ground truth annotations',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python evaluate.py                              # All annotations
  python evaluate.py eval_corpus/annotations/gautret*.json  # Specific file
  python evaluate.py -v                           # Verbose per-item
  python evaluate.py -o eval_results.json         # Export JSON
        """,
    )
    parser.add_argument('annotations', nargs='*',
                        help='Annotation JSON files (default: all in eval_corpus/annotations/)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show all items, not just errors')
    parser.add_argument('-o', '--output', help='Export results to JSON file')
    parser.add_argument('--checklist-dir', default='checklists',
                        help='Path to checklists directory')

    args = parser.parse_args()

    # Find annotation files
    if args.annotations:
        annotation_files = args.annotations
    else:
        corpus_dir = Path('eval_corpus/annotations')
        if not corpus_dir.exists():
            print(f"No eval_corpus/annotations/ directory found.")
            print(f"Create it and add annotation JSON files.")
            sys.exit(1)
        annotation_files = sorted(
            str(p) for p in corpus_dir.glob('*.json')
            if not p.name.startswith('_')
        )

    if not annotation_files:
        print("No annotation files found.")
        sys.exit(1)

    print(f"Found {len(annotation_files)} annotation(s)")

    # Evaluate
    evaluator = Evaluator(checklist_dir=args.checklist_dir)
    evaluations = []

    for ann_file in annotation_files:
        print(f"\nEvaluating: {ann_file}")
        eval_result = evaluator.evaluate_article(ann_file)
        evaluations.append(eval_result)
        print_article_report(eval_result, verbose=args.verbose)

    # Aggregate
    if len(evaluations) > 1:
        print_aggregate_report(evaluations)
    elif len(evaluations) == 1:
        print(f"\n  Add more annotated articles for aggregate metrics.")

    # Export
    if args.output:
        export = []
        for e in evaluations:
            export.append({
                'article_id': e.article_id,
                'type_correct': e.type_correct,
                'checklist_correct': e.checklist_correct,
                'recall': round(e.recall, 4),
                'specificity': round(e.specificity, 4),
                'precision': round(e.precision, 4),
                'f1': round(e.f1, 4),
                'accuracy': round(e.accuracy, 4),
                'tp': e.tp, 'tn': e.tn, 'fp': e.fp, 'fn': e.fn,
                'errors': [
                    {'item': c.item_id, 'category': c.category,
                     'system_verdict': c.system_verdict,
                     'confidence': c.system_confidence,
                     'annotator_notes': c.gt_notes}
                    for c in e.comparisons if c.category in ('FP', 'FN')
                ],
            })
        with open(args.output, 'w') as f:
            json.dump(export, f, indent=2, ensure_ascii=False)
        print(f"Results exported to {args.output}")


if __name__ == '__main__':
    main()
