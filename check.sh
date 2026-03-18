#!/bin/bash
# Usage: ./check.sh path/to/article.pdf
# Or:    ./check.sh path/to/article.md

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -z "$1" ]; then
    echo "Использование: ./check.sh <статья.pdf или статья.md>"
    exit 1
fi

# Resolve input to absolute path before cd
if [[ "$1" = /* ]]; then
    INPUT="$1"
else
    INPUT="$(pwd)/$1"
fi

cd "$SCRIPT_DIR"

/opt/homebrew/bin/python3 demo_pipeline.py "$INPUT"
