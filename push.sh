#!/bin/bash
# Quick push script for Sci_Art_Checker
# Usage: ./push.sh "commit message"
# Or just: ./push.sh  (auto-generates message with timestamp)

cd "$(dirname "$0")"

# Check if there are any changes
if git diff --quiet && git diff --cached --quiet && [ -z "$(git ls-files --others --exclude-standard)" ]; then
    echo "✓ Nothing to push — working tree is clean."
    exit 0
fi

# Show what's changed
echo "=== Changes to commit ==="
git status --short
echo ""

# Stage all changes (tracked + new files, excluding .DS_Store)
git add -A
git reset HEAD -- .DS_Store 2>/dev/null

# Commit message
if [ -n "$1" ]; then
    MSG="$1"
else
    MSG="Update $(date '+%Y-%m-%d %H:%M')"
fi

git commit -m "$MSG"

# Push
git push origin main

echo ""
echo "✓ Pushed to GitHub successfully."
