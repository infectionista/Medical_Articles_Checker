#!/usr/bin/env python3
"""
Benchmark: compare automated checker results against expert ground truth.

Usage:
    python3 benchmark.py test_input/prostate_cancer_screening.pdf

Outputs:
    - Per-item comparison table (checker vs expert)
    - Confusion matrix (present/partial/absent)
    - Precision, recall, F1 for each verdict class
    - Agreement rate and Cohen's kappa
    - List of disagreements with analysis
"""

import json
import sys
import os
from pathlib import Path
from collections import Counter

# --- project imports ---
sys.path.insert(0, str(Path(__file__).resolve().parent))

from enhanced_checker import EnhancedChecker, normalize_pdf_text
from study_detector import EnhancedStudyTypeDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VERDICT_ORDER = ['present', 'partial', 'absent']


def verdict_to_num(v: str) -> int:
    """Map verdict to ordinal: present=2, partial=1, absent=0."""
    return {'present': 2, 'partial': 1, 'absent': 0}.get(v, -1)


def cohens_kappa(matrix: dict, labels: list) -> float:
    """Compute Cohen's kappa from a confusion dict {(true, pred): count}."""
    total = sum(matrix.values())
    if total == 0:
        return 0.0

    # Observed agreement
    po = sum(matrix.get((l, l), 0) for l in labels) / total

    # Expected agreement
    pe = 0.0
    for l in labels:
        row = sum(matrix.get((l, p), 0) for p in labels) / total
        col = sum(matrix.get((t, l), 0) for t in labels) / total
        pe += row * col

    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def extract_pdf_text(pdf_path: str) -> str:
    """Extract text from PDF using available libraries."""
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception:
        pass

    if not text:
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(pdf_path)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        except Exception:
            pass

    return text


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_benchmark(pdf_path: str, force_llm: bool = False):
    """Run checker on article and compare with ground truth."""

    pdf_path = Path(pdf_path)
    article_id = pdf_path.stem

    # Load ground truth
    gt_path = Path(__file__).resolve().parent / "ground_truth" / f"{article_id}.json"
    if not gt_path.exists():
        print(f"❌ No ground truth found: {gt_path}")
        print(f"   Available: {list((Path(__file__).resolve().parent / 'ground_truth').glob('*.json'))}")
        sys.exit(1)

    with open(gt_path) as f:
        gt = json.load(f)

    gt_items = gt["items"]
    checklist_name = gt["checklist"]

    print(f"\n{'='*60}")
    print(f"  BENCHMARK: {gt['title'][:50]}...")
    print(f"  Checklist: {checklist_name} | Expert: {gt['annotator']['name']}")
    print(f"{'='*60}\n")

    # Extract text
    print("  Extracting text from PDF...")
    article_text = extract_pdf_text(str(pdf_path))
    if not article_text:
        print("  ❌ Could not extract text from PDF")
        sys.exit(1)
    article_text = normalize_pdf_text(article_text)
    print(f"  ✅ {len(article_text):,} chars extracted\n")

    # Run checker
    print("  Running automated checker...")
    checker = EnhancedChecker()
    result = checker.check(article_text, checklist_name, force_llm=force_llm)
    print(f"  ✅ Checker score: {result.weighted_score}% (weighted), {result.simple_score}% (simple)\n")

    # Build comparison
    checker_verdicts = {}
    for item in result.items:
        v = item.verdict
        if v == 'explicitly_absent':
            v = 'absent'
        checker_verdicts[item.item_id] = {
            'verdict': v,
            'confidence': item.confidence,
        }

    # --- Per-item comparison ---
    print(f"  {'Item':<6} {'Expert':<10} {'Checker':<10} {'Conf':>5}  {'Match':>5}  Note")
    print(f"  {'-'*6} {'-'*10} {'-'*10} {'-'*5}  {'-'*5}  {'-'*30}")

    agreements = 0
    disagreements = []
    confusion = Counter()

    for item_id, gt_data in sorted(gt_items.items()):
        gt_verdict = gt_data["verdict"]
        ch = checker_verdicts.get(item_id, {})
        ch_verdict = ch.get("verdict", "???")
        conf = ch.get("confidence", 0)

        match = "✅" if gt_verdict == ch_verdict else "❌"
        if gt_verdict == ch_verdict:
            agreements += 1
        else:
            disagreements.append({
                'item': item_id,
                'expert': gt_verdict,
                'checker': ch_verdict,
                'conf': conf,
                'note': gt_data.get('note', ''),
            })

        confusion[(gt_verdict, ch_verdict)] += 1

        note = gt_data.get("note", "")[:40]
        print(f"  {item_id:<6} {gt_verdict:<10} {ch_verdict:<10} {conf:>5.0%}  {match:>5}  {note}")

    total = len(gt_items)
    print(f"\n  {'='*60}")
    print(f"  AGREEMENT: {agreements}/{total} ({agreements/total*100:.0f}%)")
    print(f"  {'='*60}\n")

    # --- Confusion matrix ---
    print("  Confusion Matrix (rows=Expert, cols=Checker):")
    print(f"  {'':>12} {'present':>10} {'partial':>10} {'absent':>10} {'Total':>8}")
    for true_v in VERDICT_ORDER:
        row = [confusion.get((true_v, pred_v), 0) for pred_v in VERDICT_ORDER]
        row_total = sum(row)
        print(f"  {true_v:>12} {row[0]:>10} {row[1]:>10} {row[2]:>10} {row_total:>8}")
    print()

    # --- Per-class precision/recall ---
    print("  Per-class metrics:")
    print(f"  {'Class':<12} {'Precision':>10} {'Recall':>10} {'F1':>10} {'Support':>10}")
    for v in VERDICT_ORDER:
        tp = confusion.get((v, v), 0)
        fp = sum(confusion.get((t, v), 0) for t in VERDICT_ORDER if t != v)
        fn = sum(confusion.get((v, p), 0) for p in VERDICT_ORDER if p != v)

        prec = tp / (tp + fp) if (tp + fp) > 0 else 0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0
        support = tp + fn

        print(f"  {v:<12} {prec:>10.2f} {rec:>10.2f} {f1:>10.2f} {support:>10}")
    print()

    # --- Cohen's kappa ---
    kappa = cohens_kappa(confusion, VERDICT_ORDER)
    kappa_label = (
        "poor" if kappa < 0.2 else
        "fair" if kappa < 0.4 else
        "moderate" if kappa < 0.6 else
        "substantial" if kappa < 0.8 else
        "almost perfect"
    )
    print(f"  Cohen's κ = {kappa:.3f} ({kappa_label})")

    # --- Disagreement analysis ---
    if disagreements:
        print(f"\n  {'='*60}")
        print(f"  DISAGREEMENTS ({len(disagreements)} items):")
        print(f"  {'='*60}\n")

        # Categorize
        overestimates = [d for d in disagreements if verdict_to_num(d['checker']) > verdict_to_num(d['expert'])]
        underestimates = [d for d in disagreements if verdict_to_num(d['checker']) < verdict_to_num(d['expert'])]

        if underestimates:
            print(f"  🔽 Checker UNDERESTIMATES ({len(underestimates)} items):")
            print(f"     Items the checker scored lower than the expert.")
            for d in underestimates:
                print(f"     • {d['item']}: checker={d['checker']} (conf={d['conf']:.0%}), "
                      f"expert={d['expert']}")
                print(f"       → {d['note']}")
            print()

        if overestimates:
            print(f"  🔼 Checker OVERESTIMATES ({len(overestimates)} items):")
            print(f"     Items the checker scored higher than the expert.")
            for d in overestimates:
                print(f"     • {d['item']}: checker={d['checker']} (conf={d['conf']:.0%}), "
                      f"expert={d['expert']}")
                print(f"       → {d['note']}")
            print()

    # --- Save results ---
    results_path = Path(__file__).resolve().parent / "ground_truth" / f"{article_id}_benchmark.json"
    results = {
        "article_id": article_id,
        "checklist": checklist_name,
        "force_llm": force_llm,
        "checker_weighted_score": result.weighted_score,
        "checker_simple_score": result.simple_score,
        "agreement_rate": round(agreements / total, 3),
        "cohens_kappa": round(kappa, 3),
        "total_items": total,
        "agreements": agreements,
        "disagreements_count": len(disagreements),
        "underestimates": len([d for d in disagreements if verdict_to_num(d['checker']) < verdict_to_num(d['expert'])]),
        "overestimates": len([d for d in disagreements if verdict_to_num(d['checker']) > verdict_to_num(d['expert'])]),
        "per_item": {
            item_id: {
                "expert": gt_items[item_id]["verdict"],
                "checker": checker_verdicts.get(item_id, {}).get("verdict", "???"),
                "match": gt_items[item_id]["verdict"] == checker_verdicts.get(item_id, {}).get("verdict", "???"),
            }
            for item_id in gt_items
        },
    }
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  📄 Results saved: {results_path.name}\n")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 benchmark.py <pdf_path> [--llm]")
        sys.exit(1)

    pdf = sys.argv[1]
    use_llm = "--llm" in sys.argv

    run_benchmark(pdf, force_llm=use_llm)
