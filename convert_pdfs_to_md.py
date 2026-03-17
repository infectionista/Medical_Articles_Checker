#!/usr/bin/env python3
"""
One-time converter: extract text from all article PDFs → .md files.

Usage:
  python convert_pdfs_to_md.py

Creates a .md file alongside each .pdf in eval_corpus/articles/.
The eval script reads .md first (instant), falls back to PDF only if needed.

Tries PyPDF2 first, then pdfplumber. Skips if .md already exists
(use --force to overwrite).
"""

import os
import sys
import glob
import argparse
import subprocess
import time

ARTICLES_DIR = os.path.join(os.path.dirname(__file__) or '.', 'eval_corpus', 'articles')
TIMEOUT = 30  # seconds per PDF


def extract_with_pypdf2(pdf_path):
    """Extract text using PyPDF2."""
    import PyPDF2
    with open(pdf_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return '\n\n'.join(pages)


def extract_with_pdfplumber(pdf_path):
    """Extract text using pdfplumber (better for complex layouts)."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        pages = []
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages.append(text)
        return '\n\n'.join(pages)


def extract_in_subprocess(pdf_path, method='pypdf2'):
    """Run extraction in a subprocess with timeout (handles hanging PDFs)."""
    if method == 'pypdf2':
        script = f'''
import sys, PyPDF2
with open({pdf_path!r}, "rb") as f:
    r = PyPDF2.PdfReader(f)
    for p in r.pages:
        t = p.extract_text()
        if t:
            sys.stdout.buffer.write(t.encode("utf-8", errors="ignore"))
            sys.stdout.buffer.write(b"\\n\\n")
'''
    else:
        script = f'''
import sys, pdfplumber
with pdfplumber.open({pdf_path!r}) as pdf:
    for p in pdf.pages:
        t = p.extract_text()
        if t:
            sys.stdout.buffer.write(t.encode("utf-8", errors="ignore"))
            sys.stdout.buffer.write(b"\\n\\n")
'''
    try:
        result = subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, timeout=TIMEOUT,
        )
        if result.returncode == 0:
            return result.stdout.decode('utf-8', errors='ignore')
    except subprocess.TimeoutExpired:
        pass
    except Exception:
        pass
    return None


def main():
    parser = argparse.ArgumentParser(description='Convert article PDFs to markdown')
    parser.add_argument('--force', action='store_true', help='Overwrite existing .md files')
    parser.add_argument('--dir', default=ARTICLES_DIR, help='Articles directory')
    args = parser.parse_args()

    pdf_files = sorted(glob.glob(os.path.join(args.dir, '*.pdf')))
    print(f"Found {len(pdf_files)} PDFs in {args.dir}\n")

    stats = {'ok': 0, 'short': 0, 'failed': 0, 'skipped': 0}

    for pdf_path in pdf_files:
        basename = os.path.basename(pdf_path)
        md_path = pdf_path.rsplit('.', 1)[0] + '.md'
        md_name = os.path.basename(md_path)

        if os.path.exists(md_path) and not args.force:
            print(f"  SKIP  {basename} (already has .md)")
            stats['skipped'] += 1
            continue

        print(f"  CONV  {basename}...", end=' ', flush=True)
        t0 = time.time()

        # Try PyPDF2 first (faster)
        text = extract_in_subprocess(pdf_path, 'pypdf2')

        # If failed or too short, try pdfplumber
        if not text or len(text) < 500:
            text2 = extract_in_subprocess(pdf_path, 'pdfplumber')
            if text2 and len(text2) > (len(text or '')):
                text = text2

        elapsed = time.time() - t0

        if text and len(text) > 500:
            # Clean up: fix line-break hyphenation, collapse whitespace
            import re
            text = re.sub(r'-\s*\n\s*', '', text)
            text = re.sub(r'\n{3,}', '\n\n', text)

            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(text)

            print(f"{len(text):,} chars -> {md_name} ({elapsed:.1f}s)")
            stats['ok'] += 1
        elif text:
            # Write even short text (scanned PDFs) but mark as short
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(f"<!-- WARNING: Only {len(text)} chars extracted. Likely a scanned PDF. -->\n\n")
                f.write(text)

            print(f"SHORT ({len(text)} chars) -> {md_name} ({elapsed:.1f}s)")
            stats['short'] += 1
        else:
            print(f"FAILED ({elapsed:.1f}s)")
            stats['failed'] += 1

    print(f"\nDone: {stats['ok']} OK, {stats['short']} short, "
          f"{stats['failed']} failed, {stats['skipped']} skipped")


if __name__ == '__main__':
    main()
