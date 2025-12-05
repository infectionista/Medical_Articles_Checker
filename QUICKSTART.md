# Quick Start Guide

Get started with the Automatic Checklist Applier in 5 minutes!

## 1. Installation

```bash
# Install dependencies
pip install PyPDF2 pdfplumber
```

## 2. List Available Checklists

```bash
python checklist_applier.py --list
```

Output:
```
Available checklists:
  • CONSORT: Consolidated Standards of Reporting Trials
  • PRISMA: Preferred Reporting Items for Systematic Reviews and Meta-Analyses
  • STROBE: Strengthening the Reporting of Observational Studies in Epidemiology
  • GENOMICS: Genomics and Sequence Analysis Reporting Guidelines
```

## 3. Apply a Checklist to Your Article

### For a single article:

```bash
# Text file
python checklist_applier.py my_article.txt -c CONSORT

# PDF file
python checklist_applier.py study.pdf -c PRISMA

# Save report to file
python checklist_applier.py article.txt -c STROBE -o report.md
```

### For multiple articles:

```bash
# Process entire directory
python batch_checker.py articles/ -c CONSORT -o reports/

# Process PDF files
python batch_checker.py pdfs/ -c PRISMA -o output/ -p "*.pdf"
```

## 4. Example Output

Running:
```bash
python checklist_applier.py examples/sample_article.txt -c CONSORT
```

Produces:
```
✓ Loaded CONSORT checklist (37 items)
📄 Parsing article: examples/sample_article.txt
✓ Article loaded (8088 characters)
📋 Applying CONSORT checklist...

============================================================
Compliance: 86.49% (32/37 items)
============================================================
```

## 5. Understanding Reports

Reports show:
- ✅ **Items found**: Checklist items detected in your article
- ❌ **Items not found**: Missing items that should be addressed
- **Match rate**: Percentage of keywords found for each item
- **Compliance %**: Overall checklist compliance score

## Use Cases

### Clinical Trials (CONSORT)
```bash
python checklist_applier.py rct_study.pdf -c CONSORT -o consort_report.md
```

### Systematic Reviews (PRISMA)
```bash
python checklist_applier.py meta_analysis.pdf -c PRISMA -o prisma_report.md
```

### Observational Studies (STROBE)
```bash
python checklist_applier.py cohort_study.txt -c STROBE -o strobe_report.md
```

### Genomics Studies (GENOMICS)
```bash
python checklist_applier.py hiv_sequencing.txt -c GENOMICS -o genomics_report.md
```

## Output Formats

### Markdown (default, best for viewing)
```bash
python checklist_applier.py article.txt -c CONSORT -o report.md -f markdown
```

### Plain Text (simple, no formatting)
```bash
python checklist_applier.py article.txt -c CONSORT -o report.txt -f text
```

### JSON (for programmatic use)
```bash
python checklist_applier.py article.txt -c CONSORT -o report.json -f json
```

## Tips

1. **Manual Review**: Always manually verify the results - this tool assists, not replaces human judgment

2. **False Positives**: The tool may mark items as present if keywords are mentioned, even if not fully addressed

3. **False Negatives**: Items may be missed if different terminology is used

4. **Improve Detection**: Edit the checklist JSON files to add domain-specific keywords

5. **Batch Processing**: Use `batch_checker.py` for processing multiple articles efficiently

## Next Steps

- Read the full [README.md](README.md) for detailed documentation
- Customize checklists in the `checklists/` directory
- Check example reports in `examples/`

## Need Help?

- View all options: `python checklist_applier.py --help`
- Check examples: Look in `examples/` directory
- Read the README: Full documentation in `README.md`

## Common Issues

**"No module named PyPDF2"**
- Solution: `pip install PyPDF2`

**"Checklist not found"**
- Solution: Use `--list` to see available checklists
- Checklist names are case-insensitive (CONSORT = consort)

**Low compliance score**
- Review the detailed report to see which items are missing
- Check if different terminology is used in your article
- Consider adding custom keywords to the checklist JSON
