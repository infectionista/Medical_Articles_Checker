#!/usr/bin/env python3
"""
Eval v8: hybrid approach (keywords + TF-IDF semantic + smart LLM fallback).

IMPORTANT: Run convert_pdfs_to_md.py first to extract article text.
The evaluator reads .md files (instant) and only falls back to PDF if needed.

Architecture:
  Phase 1-2:  keyword matching in sections + full text  (fast, free)
  Phase 2.5:  TF-IDF cosine similarity                  (fast, free)
  Phase 3:    Claude Haiku LLM — ONLY when >50% items   (paid, ~$0.01/article)
              are still "absent" after Phase 1-2.5
"""

# Force UTF-8 before any imports
import os
os.environ['PYTHONUTF8'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'
os.environ['LC_ALL'] = 'en_US.UTF-8'

# Force load .env, overwriting any existing env vars (fixes kириллица in shell env)
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path, encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ[_k.strip()] = _v.strip()

import json
import sys
import glob
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))


def main():
    sys.stdout.reconfigure(line_buffering=True)

    from enhanced_checker import HAS_SKLEARN
    api_key_set = bool(os.environ.get('ANTHROPIC_API_KEY', ''))

    print("=" * 60)
    print("  Eval v8 — hybrid approach")
    print("=" * 60)
    print(f"  Phase 1-2:  keywords ............ OK")
    print(f"  Phase 2.5:  TF-IDF semantic ..... {'OK' if HAS_SKLEARN else 'OFF (pip install scikit-learn)'}")
    llm = 'OK' if api_key_set else 'OFF (set ANTHROPIC_API_KEY in .env)'
    print(f"  Phase 3:    LLM fallback ........ {llm}  (uses raw HTTP, no SDK needed)")
    print(f"  LLM triggers when: >50% items absent after Phase 1-2.5")
    print()

    # Check for .md files
    md_count = len(glob.glob('eval_corpus/articles/*.md'))
    pdf_count = len(glob.glob('eval_corpus/articles/*.pdf'))
    print(f"  Articles: {pdf_count} PDFs, {md_count} pre-extracted .md files")
    if md_count == 0:
        print("  ⚠  No .md files found. Run: python convert_pdfs_to_md.py")
        print("     (without .md files, some PDFs may hang or extract poorly)")
    print()

    annotation_files = sorted(glob.glob('eval_corpus/annotations/*.json'))
    annotation_files = [f for f in annotation_files if '_TEMPLATE' not in f]
    total = len(annotation_files)

    from evaluate import Evaluator, print_article_report, print_aggregate_report
    evaluator = Evaluator(checklist_dir='checklists')

    evaluations = []
    skipped = []

    for i, ann_file in enumerate(annotation_files, 1):
        ann = json.load(open(ann_file))
        article_id = ann['article']['id']

        print(f"[{i:2d}/{total}] {article_id}...", end=' ', flush=True)
        t0 = time.time()

        try:
            result = evaluator.evaluate_article(ann_file)
            elapsed = time.time() - t0

            if result.evaluated_items == 0:
                print(f"no items evaluated ({elapsed:.1f}s)")
                skipped.append(article_id)
                continue

            evaluations.append(result)
            print(f"done ({elapsed:.1f}s)")
            print_article_report(result, verbose=False)

        except Exception as e:
            elapsed = time.time() - t0
            print(f"ERROR ({elapsed:.1f}s): {e}")
            skipped.append(article_id)

    if skipped:
        print(f"\n  SKIPPED ({len(skipped)}): {', '.join(skipped)}")

    if len(evaluations) > 1:
        print_aggregate_report(evaluations)

    print(f"\n  Evaluated {len(evaluations)}/{total} articles")


if __name__ == '__main__':
    main()
