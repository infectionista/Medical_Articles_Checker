#!/usr/bin/env python3
"""
Batch benchmark: run checker against ALL annotated articles in eval_corpus.

Usage:
    python3 benchmark_all.py [--recalibrate]

Outputs:
    - Per-article agreement and Cohen's kappa
    - Aggregate confusion matrix across all articles
    - Per-checklist breakdown
    - Systematic bias analysis (under/overestimate)
    - If --recalibrate: optimal threshold search
"""

import json
import sys
import os
import re
from pathlib import Path
from collections import Counter, defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent))

from enhanced_checker import EnhancedChecker, normalize_pdf_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VERDICT_ORDER = ['present', 'partial', 'absent']

CHECKLIST_KEY_MAP = {
    'CONSORT': 'consort_items',
    'STROBE': 'strobe_items',
    'PRISMA': 'prisma_items',
    'GENOMICS': 'genomics_items',
    'QUADAS2': 'quadas2_items',
    'JBI_CASE_SERIES': 'jbi_case_series_items',
    'TREND': 'trend_items',
    'STARD': 'stard_items',
    'CARE': 'care_items',
    'CHEERS': 'cheers_items',
}


def gt_to_verdict(present_val) -> str:
    """Convert ground truth bool to verdict string."""
    if present_val is True:
        return 'present'
    elif present_val is False:
        return 'absent'
    else:
        return 'skip'  # null = N/A, skip in benchmark


def checker_verdict_normalize(v: str) -> str:
    if v == 'explicitly_absent':
        return 'absent'
    return v


def cohens_kappa(matrix: dict, labels: list) -> float:
    total = sum(matrix.values())
    if total == 0:
        return 0.0
    po = sum(matrix.get((l, l), 0) for l in labels) / total
    pe = 0.0
    for l in labels:
        row = sum(matrix.get((l, p), 0) for p in labels) / total
        col = sum(matrix.get((t, l), 0) for t in labels) / total
        pe += row * col
    if pe >= 1.0:
        return 1.0
    return (po - pe) / (1 - pe)


def extract_text(filepath: str) -> str:
    """Extract text from PDF or read MD file."""
    if filepath.endswith('.md'):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()

    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
    except Exception:
        pass

    if not text:
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(filepath)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text += t + "\n"
        except Exception:
            pass

    return text


# ---------------------------------------------------------------------------
# Main benchmark
# ---------------------------------------------------------------------------

def run_batch_benchmark(recalibrate: bool = False):
    base = Path(__file__).resolve().parent
    ann_dir = base / "eval_corpus" / "annotations"
    art_dir = base / "eval_corpus" / "articles"

    checker = EnhancedChecker()

    # Collect all data points: (gt_verdict, checker_verdict, confidence, checklist, article_id, item_id)
    all_points = []
    per_article = {}
    per_checklist = defaultdict(list)

    annotation_files = sorted([
        f for f in ann_dir.glob("*.json")
        if not f.name.startswith('_')
    ])

    print(f"\n{'='*70}")
    print(f"  BATCH BENCHMARK — {len(annotation_files)} annotated articles")
    print(f"{'='*70}\n")

    for ann_file in annotation_files:
        with open(ann_file) as f:
            ann = json.load(f)

        article = ann.get('article', {})
        study = ann.get('study_type', {})
        article_id = article.get('id', ann_file.stem)
        checklist_name = study.get('expected_checklist', '')
        title = article.get('title', '?')[:50]
        art_file = article.get('file', '')

        if not checklist_name or checklist_name not in checker.list_checklists():
            print(f"  ⏭ {article_id}: checklist '{checklist_name}' not supported, skipping")
            continue

        # Get ground truth items
        items_key = CHECKLIST_KEY_MAP.get(checklist_name)
        if not items_key or items_key not in ann:
            print(f"  ⏭ {article_id}: no items key '{items_key}' in annotation, skipping")
            continue

        gt_items = ann[items_key]

        # Find article file — annotations reference "articles/<name>.pdf"
        # but files may be in eval_corpus/articles/ or eval_corpus/ root
        art_path = None
        candidates_to_try = []

        # 1) Direct path from annotation (relative to project root)
        p1 = base / "eval_corpus" / art_file
        candidates_to_try.append(p1)
        candidates_to_try.append(p1.with_suffix('.md'))

        # 2) Just the filename in articles/ dir
        fname = Path(art_file).name
        p2 = art_dir / fname
        candidates_to_try.append(p2)
        candidates_to_try.append(p2.with_suffix('.md'))

        # 3) Filename in eval_corpus/ root
        p3 = base / "eval_corpus" / fname
        candidates_to_try.append(p3)
        candidates_to_try.append(p3.with_suffix('.md'))

        for candidate in candidates_to_try:
            if candidate.exists():
                art_path = candidate
                break

        if art_path is None:
            # Glob search in both dirs
            for search_dir in [art_dir, base / "eval_corpus"]:
                for ext in ['*.md', '*.pdf']:
                    for match in search_dir.glob(ext):
                        if fname.split('.')[0].lower() in match.stem.lower():
                            art_path = match
                            break
                    if art_path:
                        break
                if art_path:
                    break

        if art_path is None:
            print(f"  ⏭ {article_id}: file not found ({art_file}), skipping")
            continue

        # Extract text
        text = extract_text(str(art_path))
        if not text or len(text) < 500:
            print(f"  ⏭ {article_id}: text extraction failed ({len(text)} chars), skipping")
            continue
        text = normalize_pdf_text(text)

        # Run checker
        try:
            result = checker.check(text, checklist_name)
        except Exception as e:
            print(f"  ❌ {article_id}: checker error: {e}")
            continue

        # Build checker results dict
        checker_map = {}
        for item in result.items:
            checker_map[item.item_id] = {
                'verdict': checker_verdict_normalize(item.verdict),
                'confidence': item.confidence,
            }

        # Compare
        article_agree = 0
        article_total = 0
        article_confusion = Counter()

        for item_id, gt_data in gt_items.items():
            if not isinstance(gt_data, dict) or 'present' not in gt_data:
                continue

            gt_v = gt_to_verdict(gt_data['present'])
            if gt_v == 'skip':
                continue

            ch = checker_map.get(item_id, {})
            ch_v = ch.get('verdict', 'absent')
            conf = ch.get('confidence', 0.0)

            # For binary GT (no "partial"), map checker partial → present or absent
            # based on which it's closer to. But also keep raw for analysis.
            point = {
                'gt': gt_v,
                'checker': ch_v,
                'confidence': conf,
                'checklist': checklist_name,
                'article_id': article_id,
                'item_id': item_id,
            }
            all_points.append(point)
            per_checklist[checklist_name].append(point)

            # Binary agreement: gt is present/absent; checker is present/partial/absent
            # For agreement: present matches present, absent matches absent
            # partial in checker is a grey zone
            if gt_v == ch_v:
                article_agree += 1
            elif gt_v == 'present' and ch_v == 'partial':
                pass  # underestimate
            elif gt_v == 'absent' and ch_v == 'partial':
                pass  # overestimate

            article_confusion[(gt_v, ch_v)] += 1
            article_total += 1

        if article_total == 0:
            continue

        agree_rate = article_agree / article_total
        kappa = cohens_kappa(article_confusion, VERDICT_ORDER)

        per_article[article_id] = {
            'checklist': checklist_name,
            'title': title,
            'total': article_total,
            'agree': article_agree,
            'rate': agree_rate,
            'kappa': kappa,
            'confusion': dict(article_confusion),
            'checker_score': result.weighted_score,
        }

        emoji = "🟢" if agree_rate >= 0.7 else "🟡" if agree_rate >= 0.5 else "🔴"
        print(f"  {emoji} {article_id[:40]:<40} {checklist_name:<12} "
              f"agree={article_agree:>2}/{article_total:<2} ({agree_rate:>5.0%})  "
              f"κ={kappa:>6.3f}  score={result.weighted_score:>5.1f}%")

    # =========================================================================
    # AGGREGATE
    # =========================================================================
    print(f"\n{'='*70}")
    print(f"  AGGREGATE RESULTS ({len(all_points)} item evaluations)")
    print(f"{'='*70}\n")

    # Global confusion matrix
    global_confusion = Counter()
    for p in all_points:
        global_confusion[(p['gt'], p['checker'])] += 1

    print("  Confusion Matrix (rows=Expert, cols=Checker):")
    print(f"  {'':>12} {'present':>10} {'partial':>10} {'absent':>10} {'Total':>8}")
    for true_v in VERDICT_ORDER:
        row = [global_confusion.get((true_v, pred_v), 0) for pred_v in VERDICT_ORDER]
        row_total = sum(row)
        if row_total > 0:
            print(f"  {true_v:>12} {row[0]:>10} {row[1]:>10} {row[2]:>10} {row_total:>8}")
    print()

    # Global metrics
    total_exact = sum(1 for p in all_points if p['gt'] == p['checker'])
    if not all_points:
        print("  ❌ No data points collected. Check file paths.")
        return

    print(f"  Exact agreement: {total_exact}/{len(all_points)} ({total_exact/len(all_points)*100:.1f}%)")

    # Binary agreement: treat checker's partial as uncertain
    # Option A: partial → present (lenient)
    lenient_agree = sum(1 for p in all_points
                        if (p['gt'] == p['checker']) or
                        (p['gt'] == 'present' and p['checker'] == 'partial'))
    print(f"  Lenient agreement (partial→present): {lenient_agree}/{len(all_points)} "
          f"({lenient_agree/len(all_points)*100:.1f}%)")

    # Option B: partial → absent (strict)
    strict_agree = sum(1 for p in all_points
                       if (p['gt'] == p['checker']) or
                       (p['gt'] == 'absent' and p['checker'] == 'partial'))
    print(f"  Strict agreement (partial→absent): {strict_agree}/{len(all_points)} "
          f"({strict_agree/len(all_points)*100:.1f}%)")

    kappa_global = cohens_kappa(global_confusion, VERDICT_ORDER)
    print(f"  Cohen's κ (3-class): {kappa_global:.3f}")

    # Binary kappa (mapping partial → present for lenient)
    binary_confusion = Counter()
    for p in all_points:
        gt_bin = p['gt']
        ch_bin = 'present' if p['checker'] in ('present', 'partial') else 'absent'
        binary_confusion[(gt_bin, ch_bin)] += 1
    kappa_binary = cohens_kappa(binary_confusion, ['present', 'absent'])
    print(f"  Cohen's κ (binary, partial→present): {kappa_binary:.3f}")
    print()

    # --- Bias analysis ---
    underest = sum(1 for p in all_points if p['gt'] == 'present' and p['checker'] in ('partial', 'absent'))
    overest = sum(1 for p in all_points if p['gt'] == 'absent' and p['checker'] in ('present', 'partial'))
    print(f"  Systematic bias:")
    print(f"    Underestimates (expert=present, checker=partial/absent): {underest}")
    print(f"    Overestimates  (expert=absent, checker=present/partial): {overest}")
    print(f"    Bias ratio: {underest}:{overest}")
    print()

    # --- Per-checklist breakdown ---
    print(f"  {'='*70}")
    print(f"  PER-CHECKLIST BREAKDOWN")
    print(f"  {'='*70}\n")

    print(f"  {'Checklist':<16} {'N':>4} {'Exact%':>7} {'Lenient%':>9} "
          f"{'Under':>6} {'Over':>5} {'κ(bin)':>7}")

    for cl_name in sorted(per_checklist.keys()):
        pts = per_checklist[cl_name]
        n = len(pts)
        exact = sum(1 for p in pts if p['gt'] == p['checker'])
        lenient = sum(1 for p in pts
                      if (p['gt'] == p['checker']) or
                      (p['gt'] == 'present' and p['checker'] == 'partial'))
        under = sum(1 for p in pts if p['gt'] == 'present' and p['checker'] in ('partial', 'absent'))
        over = sum(1 for p in pts if p['gt'] == 'absent' and p['checker'] in ('present', 'partial'))

        bc = Counter()
        for p in pts:
            gt_bin = p['gt']
            ch_bin = 'present' if p['checker'] in ('present', 'partial') else 'absent'
            bc[(gt_bin, ch_bin)] += 1
        kb = cohens_kappa(bc, ['present', 'absent'])

        print(f"  {cl_name:<16} {n:>4} {exact/n*100:>6.1f}% {lenient/n*100:>8.1f}% "
              f"{under:>6} {over:>5} {kb:>7.3f}")

    # =========================================================================
    # RECALIBRATION
    # =========================================================================
    if recalibrate:
        print(f"\n{'='*70}")
        print(f"  THRESHOLD RECALIBRATION")
        print(f"{'='*70}\n")

        # For binary classification (present vs absent), find optimal confidence threshold
        # that maximizes agreement with ground truth.
        # Items with gt=present should have high confidence; gt=absent should have low.

        confidences_present = [p['confidence'] for p in all_points if p['gt'] == 'present']
        confidences_absent = [p['confidence'] for p in all_points if p['gt'] == 'absent']

        print(f"  Ground truth 'present' items ({len(confidences_present)}):")
        print(f"    Mean confidence: {sum(confidences_present)/len(confidences_present):.3f}")
        print(f"    Median: {sorted(confidences_present)[len(confidences_present)//2]:.3f}")
        print(f"    Min: {min(confidences_present):.3f}, Max: {max(confidences_present):.3f}")
        print(f"    <0.25: {sum(1 for c in confidences_present if c < 0.25)}")
        print(f"    <0.50: {sum(1 for c in confidences_present if c < 0.50)}")
        print(f"    <0.60: {sum(1 for c in confidences_present if c < 0.60)}")
        print()

        print(f"  Ground truth 'absent' items ({len(confidences_absent)}):")
        print(f"    Mean confidence: {sum(confidences_absent)/len(confidences_absent):.3f}" if confidences_absent else "    (none)")
        if confidences_absent:
            print(f"    Median: {sorted(confidences_absent)[len(confidences_absent)//2]:.3f}")
            print(f"    >0.25: {sum(1 for c in confidences_absent if c > 0.25)}")
            print(f"    >0.50: {sum(1 for c in confidences_absent if c > 0.50)}")
        print()

        # Search for optimal thresholds
        print("  Threshold search (binary: present vs absent):")
        print(f"  {'Threshold':>10} {'Accuracy':>10} {'Precision':>10} {'Recall':>10} {'F1':>10} {'κ':>10}")

        best_f1 = 0
        best_thresh = 0

        for thresh_x10 in range(5, 70, 5):
            thresh = thresh_x10 / 100.0
            tp = sum(1 for p in all_points if p['gt'] == 'present' and p['confidence'] >= thresh)
            fp = sum(1 for p in all_points if p['gt'] == 'absent' and p['confidence'] >= thresh)
            fn = sum(1 for p in all_points if p['gt'] == 'present' and p['confidence'] < thresh)
            tn = sum(1 for p in all_points if p['gt'] == 'absent' and p['confidence'] < thresh)

            acc = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) > 0 else 0
            prec = tp / (tp + fp) if (tp + fp) > 0 else 0
            rec = tp / (tp + fn) if (tp + fn) > 0 else 0
            f1 = 2 * prec * rec / (prec + rec) if (prec + rec) > 0 else 0

            cm = Counter()
            for p in all_points:
                pred = 'present' if p['confidence'] >= thresh else 'absent'
                cm[(p['gt'], pred)] += 1
            k = cohens_kappa(cm, ['present', 'absent'])

            marker = " ← best" if f1 > best_f1 else ""
            if f1 > best_f1:
                best_f1 = f1
                best_thresh = thresh

            print(f"  {thresh:>10.2f} {acc:>10.1%} {prec:>10.1%} {rec:>10.1%} {f1:>10.3f} {k:>10.3f}{marker}")

        print(f"\n  ★ Optimal binary threshold: {best_thresh:.2f} (F1={best_f1:.3f})")
        print(f"    Current threshold for 'present': 0.60")
        print(f"    Current threshold for 'partial': 0.25")

        # Also search for two-threshold (present/partial/absent)
        print(f"\n  Two-threshold search (present/partial/absent):")
        print(f"  {'T_present':>10} {'T_partial':>10} {'Exact%':>8} {'κ(3-way)':>10}")

        best_kappa3 = -1
        best_t = (0.6, 0.25)

        for tp_x10 in range(30, 75, 5):
            for ta_x10 in range(5, tp_x10, 5):
                tp_thresh = tp_x10 / 100.0
                ta_thresh = ta_x10 / 100.0

                cm3 = Counter()
                exact3 = 0
                for p in all_points:
                    if p['confidence'] >= tp_thresh:
                        pred = 'present'
                    elif p['confidence'] >= ta_thresh:
                        pred = 'partial'
                    else:
                        pred = 'absent'
                    cm3[(p['gt'], pred)] += 1
                    if p['gt'] == pred:
                        exact3 += 1

                k3 = cohens_kappa(cm3, VERDICT_ORDER)
                if k3 > best_kappa3:
                    best_kappa3 = k3
                    best_t = (tp_thresh, ta_thresh)

        print(f"\n  ★ Optimal thresholds: present≥{best_t[0]:.2f}, partial≥{best_t[1]:.2f}")
        print(f"    Cohen's κ (3-way): {best_kappa3:.3f}")
        print(f"    vs current (0.60/0.25): κ={kappa_global:.3f}")

    # --- Save summary ---
    summary_path = base / "ground_truth" / "batch_benchmark_results.json"
    summary_path.parent.mkdir(exist_ok=True)
    summary = {
        'total_articles': len(per_article),
        'total_items': len(all_points),
        'exact_agreement': total_exact / len(all_points) if all_points else 0,
        'lenient_agreement': lenient_agree / len(all_points) if all_points else 0,
        'kappa_3class': round(kappa_global, 3),
        'kappa_binary': round(kappa_binary, 3),
        'underestimates': underest,
        'overestimates': overest,
        'per_article': {
            k: {'checklist': v['checklist'], 'agree_rate': round(v['rate'], 3),
                 'kappa': round(v['kappa'], 3), 'checker_score': v['checker_score']}
            for k, v in per_article.items()
        },
    }
    if recalibrate:
        summary['optimal_binary_threshold'] = best_thresh
        summary['optimal_present_threshold'] = best_t[0]
        summary['optimal_partial_threshold'] = best_t[1]
        summary['optimal_kappa_3class'] = round(best_kappa3, 3)

    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n  📄 Results saved: {summary_path}")


if __name__ == "__main__":
    recal = "--recalibrate" in sys.argv
    run_batch_benchmark(recalibrate=recal)
