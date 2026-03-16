#!/usr/bin/env python3
"""
Eval v8: hybrid approach (keywords + TF-IDF semantic matching + optional LLM).
Handles the two unreadable PDFs by using uploaded OCR versions.
"""

import json
import sys
import os
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from evaluate import Evaluator, print_article_report, print_aggregate_report

# Map annotation IDs that have unreadable PDFs to uploaded OCR paths
UPLOAD_OVERRIDES = {
    'stampfer_1991_estrogen_cohort': '/sessions/affectionate-kind-allen/mnt/uploads/POSTMENOPAUSAL ESTROGEN THERAPY AND CARDIOVASCULAR DISEASE.pdf',
    'halpin_1982_reyes_case_control': "/sessions/affectionate-kind-allen/mnt/uploads/Reye's Syndrome Study Data Extraction.pdf",
}


def read_pdf(path):
    import PyPDF2
    try:
        with open(path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            return '\n'.join(page.extract_text() or '' for page in reader.pages)
    except Exception as e:
        print(f"  ERROR reading {path}: {e}")
        return ""


def main():
    evaluator = Evaluator(checklist_dir='checklists')
    annotation_files = sorted(glob.glob('eval_corpus/annotations/*.json'))
    annotation_files = [f for f in annotation_files if '_TEMPLATE' not in f]

    print(f"Eval v8 — hybrid approach (keywords + TF-IDF semantic)")
    print(f"Found {len(annotation_files)} annotation(s)\n")

    evaluations = []
    for ann_file in annotation_files:
        ann = json.load(open(ann_file))
        article_id = ann['article']['id']

        # Check if this article needs an upload override
        article_text = None
        if article_id in UPLOAD_OVERRIDES:
            upload_path = UPLOAD_OVERRIDES[article_id]
            if os.path.exists(upload_path):
                article_text = read_pdf(upload_path)
                if article_text and len(article_text) > 500:
                    print(f"  Using uploaded OCR for {article_id} ({len(article_text)} chars)")
                else:
                    article_text = None
                    print(f"  WARNING: Upload override too short for {article_id}")

        print(f"Evaluating: {ann_file}")
        eval_result = evaluator.evaluate_article(ann_file, article_text=article_text)
        evaluations.append(eval_result)
        print_article_report(eval_result, verbose=False)

    if len(evaluations) > 1:
        print_aggregate_report(evaluations)


if __name__ == '__main__':
    main()
