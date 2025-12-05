# Automatic Checklist Applier for Research Articles

An automated tool to apply standard research reporting checklists to scientific articles. Supports CONSORT, PRISMA, STROBE, and custom genomics reporting guidelines.

## 🆕 NEW: Detailed Check with Auto-Detection

The new `detailed_check.py` script automatically:
- 🔍 **Detects study type** from article content
- 📋 **Selects appropriate checklist** from comprehensive reference table
- ✅ **Applies evaluation** using local equivalent checklists
- 📊 **Recommends external tools** for comprehensive appraisal

**Supports 18+ study types** including RCTs, cohort studies, case series, systematic reviews, diagnostic accuracy, prognostic studies, and more!

See [DETAILED_CHECK_GUIDE.md](DETAILED_CHECK_GUIDE.md) for complete documentation.

## Features

- ✅ **Multiple Checklists**: CONSORT, PRISMA, STROBE, Genomics
- 🤖 **Auto-Detection**: Automatic study type detection (NEW!)
- 📋 **18+ Study Types**: Comprehensive coverage of research designs (NEW!)
- 📄 **Format Support**: Text files (.txt, .md) and PDF files (.pdf)
- 🔍 **Keyword Matching**: Intelligent keyword-based item detection
- 📊 **Detailed Reports**: Generate compliance reports in text, markdown, or JSON
- 🎯 **Compliance Score**: Automatic calculation of checklist compliance percentage
- 🔧 **Extensible**: Easy to add custom checklists

## Supported Checklists

### CONSORT (Consolidated Standards of Reporting Trials)
For randomized controlled trials - 37 items covering trial design, methods, results, and reporting.

### PRISMA (Preferred Reporting Items for Systematic Reviews)
For systematic reviews and meta-analyses - 27 items covering search strategy, screening, and synthesis.

### STROBE (Strengthening the Reporting of Observational Studies)
For observational studies (cohort, case-control, cross-sectional) - 22 items covering study design and analysis.

### GENOMICS (Genomics and Sequence Analysis)
For genomic and sequence analysis studies - 22 items covering sequencing, bioinformatics, and data sharing.

## Installation

1. Clone or download this repository

2. Install required dependencies:
```bash
pip install -r requirements.txt
```

## Usage

### Quick Start: Auto-Detection (Recommended!)

**NEW:** Let the system automatically detect study type and apply the appropriate checklist:

```bash
# Automatic study type detection
python detailed_check.py article.pdf
```

The script will:
1. Detect the study type (RCT, cohort, case series, etc.)
2. Recommend the appropriate appraisal checklist
3. Apply the local equivalent
4. Generate comprehensive reports

See [DETAILED_CHECK_GUIDE.md](DETAILED_CHECK_GUIDE.md) for full documentation.

### Manual Checklist Selection

If you know which checklist to use:

List available checklists:
```bash
python checklist_applier.py --list
```

Apply a specific checklist to an article:
```bash
python checklist_applier.py article.txt -c CONSORT
```

### Advanced Usage

Apply PRISMA checklist to a PDF and save markdown report:
```bash
python checklist_applier.py systematic_review.pdf -c PRISMA -o report.md -f markdown
```

Apply genomics checklist with JSON output:
```bash
python checklist_applier.py hiv_study.txt -c GENOMICS -o results.json -f json
```

Use case-sensitive keyword matching:
```bash
python checklist_applier.py article.txt -c STROBE --case-sensitive
```

### Command-Line Options

```
positional arguments:
  article               Path to article file (txt, pdf)

optional arguments:
  -h, --help           Show help message and exit
  -c, --checklist      Checklist to apply (CONSORT, PRISMA, STROBE, GENOMICS)
  -o, --output         Output file for report
  -f, --format         Output format: text, markdown, json (default: markdown)
  --list              List available checklists
  --case-sensitive    Use case-sensitive keyword matching
```

## Python API Usage

```python
from checklist_applier import ChecklistApplier

# Initialize the applier
applier = ChecklistApplier()

# Parse an article
article_text = applier.parse_article('my_article.pdf')

# Apply a checklist
results = applier.apply_checklist(article_text, 'CONSORT')

# Generate and save report
applier.save_report(results, 'consort_report.md', 'markdown')

# Or get report as string
report = applier.generate_report(results, 'text')
print(report)
```

## Report Output

The tool generates comprehensive reports showing:

- **Compliance Summary**: Overall compliance percentage and item counts
- **Detailed Results**: Section-by-section breakdown of each checklist item
- **Keyword Matching**: Which keywords were found in the article
- **Missing Items**: Items not detected with expected keywords

### Example Report (Markdown)

```markdown
# CONSORT Checklist Report

**Compliance:** 85% (31/37 items)

## Title and Abstract
✅ Item 1a: Identification as a randomised trial
   - Found keywords: randomized, RCT, trial
   - Match rate: 75%

❌ Item 1b: Structured summary
   - Expected keywords: abstract, background, methods...

...
```

## Adding Custom Checklists

You can add your own checklists by creating a JSON file in the `checklists/` directory:

```json
{
  "name": "CUSTOM",
  "full_name": "My Custom Checklist",
  "description": "Description of the checklist",
  "version": "1.0",
  "items": [
    {
      "section": "Section Name",
      "item": "1",
      "description": "Item description",
      "keywords": ["keyword1", "keyword2", "keyword3"]
    }
  ]
}
```

## How It Works

1. **Article Parsing**: Extracts text from PDF or text files
2. **Keyword Matching**: Searches for checklist-specific keywords in the article
3. **Item Detection**: Marks items as "found" if relevant keywords are detected
4. **Compliance Calculation**: Calculates percentage based on detected items
5. **Report Generation**: Creates detailed, formatted reports

## Limitations

- **Keyword-based matching**: Detection is based on keywords, not semantic understanding
- **False positives**: May mark items as present when only tangentially mentioned
- **False negatives**: May miss items if different terminology is used
- **Context-blind**: Does not verify if information is complete or adequate

## Best Practices

1. **Manual Review**: Always manually review reports - this tool assists but doesn't replace human judgment
2. **Multiple Formats**: Try both text and PDF parsing if results seem incomplete
3. **Custom Keywords**: Modify checklist JSON files to add discipline-specific keywords
4. **Complementary Use**: Use alongside manual checklist review for best results

## File Structure

```
hiv_seq/
├── checklist_applier.py       # Main application
├── checklists/                # Checklist definitions
│   ├── consort.json          # CONSORT checklist
│   ├── prisma.json           # PRISMA checklist
│   ├── strobe.json           # STROBE checklist
│   └── genomics.json         # Genomics checklist
├── requirements.txt          # Python dependencies
├── README.md                 # This file
└── examples/                 # Example articles and reports
```

## Contributing

To contribute new checklists or improvements:

1. Add checklist JSON files to `checklists/` directory
2. Follow the existing JSON structure
3. Include comprehensive keywords for each item
4. Test with real articles from the target domain

## References

- **CONSORT**: http://www.consort-statement.org/
- **PRISMA**: http://www.prisma-statement.org/
- **STROBE**: https://www.strobe-statement.org/
- **Genomics Standards**: Various genomics and bioinformatics reporting guidelines

## License

This tool is provided as-is for research and educational purposes.

## Citation

If you use this tool in your research, please cite the relevant reporting guideline (CONSORT, PRISMA, STROBE, etc.).
