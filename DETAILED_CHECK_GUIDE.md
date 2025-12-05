# Detailed Check Guide - Automatic Study Type Detection

## Overview

The `detailed_check.py` script provides **advanced automatic analysis** of research articles by:

1. 🔍 **Auto-detecting the study type** (RCT, cohort, case series, systematic review, etc.)
2. 📋 **Selecting the appropriate appraisal checklist** from the reference table
3. ✅ **Applying the corresponding evaluation**
4. 📊 **Generating comprehensive reports** with recommendations

## Study Types Supported

Based on the comprehensive checklist reference table (`checklist_table.pdf`), the system supports:

### Primary Research Studies
- **Randomized Controlled Trial (RCT)** → RoB 2 / CONSORT
- **Non-randomized Intervention** → ROBINS-I / STROBE
- **Cohort Study** → ROBINS-I / STROBE
- **Case-Control Study** → JBI Case-Control / STROBE
- **Cross-Sectional Study** → JBI Cross-Sectional / STROBE
- **Case Series** → JBI Case Series / STROBE
- **Case Report** → JBI Case Report / STROBE

### Specialized Studies
- **Diagnostic Accuracy** → QUADAS-2
- **Prognostic Factors** → QUIPS
- **Prognostic Model** → PROBAST
- **Genomic/Sequence Analysis** → Custom Genomics Checklist

### Reviews and Guidelines
- **Systematic Review (Interventions)** → AMSTAR 2 / PRISMA
- **Systematic Review (Prognostic)** → AMSTAR 2 + ROBIS / PRISMA
- **Clinical Guidelines** → AGREE II

### Other
- **Health Economic Evaluation** → CHEERS 2022
- **Qualitative Research** → JBI Qualitative
- **Mixed Methods** → MMAT 2018

## Quick Start

### Basic Usage (Auto-Detection)

```bash
# Automatically detect study type and apply appropriate checklist
python detailed_check.py article.pdf
```

The script will:
1. Parse the article
2. Detect the study type
3. Apply the appropriate local checklist
4. Generate detailed reports in `reports/` folder

### Force Specific Study Type

```bash
# If you know the study type, you can force it
python detailed_check.py article.pdf --type case_series
```

### Custom Output Directory

```bash
# Organize reports by project
python detailed_check.py myarticle.pdf -o reports/my_project
```

### List Available Study Types

```bash
# See all supported study types and their checklists
python detailed_check.py --list-types
```

## How Study Type Detection Works

The detection algorithm searches for specific keywords and patterns in the article:

### Detection Patterns

**RCT Detection:**
- Keywords: randomized/randomised, RCT, trial, controlled trial
- Patterns: allocation concealment, intention-to-treat, parallel group
- Weight: High (5)

**Systematic Review Detection:**
- Keywords: systematic review, meta-analysis, PRISMA
- Patterns: search strategy, included studies, forest plot
- Weight: High (5)

**Cohort Study Detection:**
- Keywords: cohort, prospective, retrospective
- Patterns: follow-up, incidence, longitudinal
- Weight: Medium (4)

**Case Series Detection:**
- Keywords: case series, consecutive patients/cases
- Patterns: series of N, no control group
- Weight: Medium-Low (3)

**Genomic Study Detection:**
- Keywords: sequencing, genome, genomic, phylogenetic
- Patterns: bioinformatics, NGS, GenBank
- Weight: Medium (4)

### Confidence Scoring

- Detection confidence is calculated based on:
  - Number of matched keywords
  - Weight of matched patterns
  - Normalized to 0-100% scale

## Output Files

For each analyzed article, the script generates:

### 1. Detailed Report (Markdown)
**File:** `{article_name}_detailed_report.md`

Contains:
- Study type detection results with confidence score
- Recommended appraisal checklist information
- Link to download the recommended checklist
- Local equivalent checklist used
- Compliance summary with progress bar
- Item-by-item detailed results
- Recommendations for missing items

### 2. JSON Results
**File:** `{article_name}_detailed_results.json`

Machine-readable format with:
- All checklist items and results
- Detection metadata
- Compliance scores
- Matched keywords

## Example Workflow

### Analyzing the Wakefield 1998 Article

```bash
# Run automatic detection
python detailed_check.py PIIS0140673697110960.pdf -o reports/wakefield_1998

# Output:
# ✓ Detected: cohort_study (confidence: 50.0%)
# 📋 Recommended checklist: ROBINS-I
# 📊 Applying STROBE checklist...
# Compliance: 68.18% (15/22 items)
```

Alternatively, force case_series type:

```bash
python detailed_check.py PIIS0140673697110960.pdf --type case_series -o reports/wakefield_1998

# Output:
# 🔧 Forced study type: case_series
# 📋 Recommended checklist: JBI Case Series
# 📊 Applying STROBE checklist...
# Compliance: 68.18% (15/22 items)
```

## Checklist Reference Table

The system uses a comprehensive reference table (`checklist_table.pdf`) that maps:

| Study Type | Recommended Checklist | URL | Local Equivalent |
|------------|----------------------|-----|------------------|
| RCT | RoB 2 | [Link](https://www.riskofbias.info/welcome/rob-2-0-tool/current-version-of-rob-2) | CONSORT |
| Cohort | ROBINS-I | [Link](https://www.riskofbias.info/welcome/robins-i-v2) | STROBE |
| Case Series | JBI Case Series | [Link](https://jbi.global/critical-appraisal-tools) | STROBE |
| Systematic Review | AMSTAR 2 | [Link](https://amstar.ca) | PRISMA |
| Genomic | Custom | - | GENOMICS |

## Interpreting Results

### High Confidence Detection (>75%)
- Clear indicators of study type present
- Multiple keywords matched
- Trust the auto-detection

### Medium Confidence Detection (40-75%)
- Some indicators present
- Consider reviewing the detection
- May want to force specific type

### Low Confidence Detection (<40%)
- Ambiguous or unclear study type
- Recommend forcing the correct type
- Or use manual `checklist_applier.py`

## When to Use Each Tool

### Use `detailed_check.py` when:
- ✅ You want automatic study type detection
- ✅ You need comprehensive analysis with recommendations
- ✅ You want both local checklist application AND reference to external tools
- ✅ Analyzing multiple diverse studies

### Use `checklist_applier.py` when:
- ✅ You know exactly which checklist to apply
- ✅ You want quick, simple checklist application
- ✅ Processing multiple studies of the same type

### Use `batch_checker.py` when:
- ✅ Processing many articles of the same type
- ✅ Bulk analysis with consistent checklist

## Advanced Features

### Extending Detection Patterns

To add new study type detection patterns, edit `detailed_check.py`:

```python
self.detection_patterns = {
    "your_study_type": {
        "keywords": [
            r'\byour_keyword\b',
            r'\banother_pattern\b'
        ],
        "weight": 4
    }
}
```

### Adding New Study Types

Add to `STUDY_TYPE_CHECKLISTS` dictionary:

```python
"your_type": {
    "name_en": "Your Study Type",
    "checklist": "Recommended Checklist Name",
    "url": "https://checklist-url.com",
    "description": "Description",
    "local_checklist": "LOCAL_CHECKLIST_NAME"
}
```

## Troubleshooting

### "Unknown study type" detected
- Article doesn't match any detection patterns
- Use `--type` to force the correct type
- Or add custom detection patterns

### Low confidence score
- Article uses non-standard terminology
- Consider forcing the study type with `--type`
- Review the detailed report to verify

### Local checklist not available
- Some specialized checklists don't have local equivalents
- Download from the provided URL
- Use closest equivalent (e.g., STROBE for observational studies)

## Best Practices

1. **Review Detection Results**
   - Always check the confidence score
   - Verify the detected type matches your understanding
   - Use `--type` to override if needed

2. **Combine with Manual Review**
   - Automated detection is a starting point
   - Expert judgment still essential
   - Use recommended checklists from reference table

3. **Use Appropriate Checklists**
   - Follow the reference table recommendations
   - Download specialized checklists when needed
   - Local equivalents are approximations

4. **Organize Reports**
   - Use meaningful output directories
   - Keep reports with the analyzed articles
   - Version control for reproducibility

## References

- **Checklist Reference Table:** `checklist_table.pdf`
- **RoB 2:** https://www.riskofbias.info/
- **JBI Tools:** https://jbi.global/critical-appraisal-tools
- **EQUATOR Network:** https://www.equator-network.org/

## Citation

When using this tool in research, please cite:
1. The appropriate reporting guideline (CONSORT, PRISMA, STROBE, etc.)
2. The specific appraisal tool recommended for your study type
3. The checklist reference table used for mapping

---

**Questions or Issues?**
- Check the main README.md for general usage
- Review QUICKSTART.md for basic examples
- See examples in `reports/` directory
