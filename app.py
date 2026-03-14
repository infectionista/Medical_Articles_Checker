#!/usr/bin/env python3
"""
Scientific Article Checker — Streamlit Web App

A browser-based tool for evaluating scientific articles against
standard reporting checklists (CONSORT, PRISMA, STROBE, GENOMICS).

Run:  streamlit run app.py
Deploy: streamlit deploy (free on Streamlit Community Cloud)
"""

import streamlit as st
import json
import tempfile
from pathlib import Path

from section_parser import SectionParser
from enhanced_checker import EnhancedChecker
from study_detector import EnhancedStudyTypeDetector, STUDY_TYPE_CHECKLISTS


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Scientific Article Checker",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Initialize components (cached)
# ---------------------------------------------------------------------------

@st.cache_resource
def load_checker():
    return EnhancedChecker(checklist_dir="checklists")

@st.cache_resource
def load_detector():
    return EnhancedStudyTypeDetector()

@st.cache_resource
def load_parser():
    return SectionParser()


checker = load_checker()
detector = load_detector()
parser = load_parser()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🔬 Article Checker")
    st.markdown("Evaluate scientific articles against standard reporting checklists.")

    st.divider()

    st.subheader("Available Checklists")
    for name in checker.list_checklists():
        cl = checker.checklists[name]
        st.markdown(f"**{name}** — {cl['full_name']}")
        st.caption(f"{len(cl['items'])} items · {cl['description']}")

    st.divider()
    st.caption(
        "Built with [Enhanced Checker](https://github.com/infectionista/Medical_Articles_Checker) · "
        "Context-aware matching · Weighted scoring"
    )


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

st.title("Scientific Article Checker")
st.markdown(
    "Upload a research article and get an instant compliance report "
    "against standard reporting guidelines."
)

# --- File upload ---
col_upload, col_options = st.columns([2, 1])

with col_upload:
    uploaded_file = st.file_uploader(
        "Upload article (PDF or TXT)",
        type=["pdf", "txt", "md"],
        help="Drag & drop or click to browse. Supports PDF, TXT, and Markdown.",
    )

with col_options:
    audience = st.radio(
        "Report level:",
        options=["public", "student", "specialist"],
        format_func=lambda x: {
            'public': '👤 General public (patient/reader)',
            'student': '🎓 Student (learning critical appraisal)',
            'specialist': '🔬 Specialist (researcher/clinician)',
        }[x],
        index=1,
        help="Choose the level of detail and language for the report.",
    )
    auto_detect = st.checkbox("Auto-detect study type", value=True)
    manual_checklist = st.selectbox(
        "Or choose checklist manually:",
        options=["(auto)"] + checker.list_checklists(),
        disabled=auto_detect,
    )
    show_evidence = st.checkbox("Show evidence snippets", value=True)


# --- Process ---
if uploaded_file is not None:
    # Read file content
    with st.spinner("Reading article..."):
        if uploaded_file.type == "application/pdf":
            try:
                import PyPDF2
                reader = PyPDF2.PdfReader(uploaded_file)
                article_text = ""
                for page in reader.pages:
                    article_text += page.extract_text() + "\n"
            except ImportError:
                st.error("PyPDF2 is required for PDF files. Install with: `pip install PyPDF2`")
                st.stop()
            except Exception as e:
                st.error(f"Error reading PDF: {e}")
                st.stop()
        else:
            article_text = uploaded_file.read().decode("utf-8", errors="ignore")

    if not article_text.strip():
        st.error("Could not extract text from the file. Try a different format.")
        st.stop()

    st.success(f"Loaded: **{uploaded_file.name}** ({len(article_text):,} characters)")

    # --- Study type detection ---
    if auto_detect:
        detection = detector.detect(article_text)
        type_info = STUDY_TYPE_CHECKLISTS.get(detection.study_type, {})
        local_checklist = detector.get_checklist_for_type(detection.study_type)

        col_type, col_conf = st.columns([3, 1])
        with col_type:
            st.info(
                f"**Detected study type:** {type_info.get('name_en', detection.study_type)}\n\n"
                f"Recommended checklist: **{type_info.get('checklist', 'N/A')}** · "
                f"Using local: **{local_checklist or 'STROBE'}**"
            )
            if detection.warnings:
                for w in detection.warnings:
                    st.warning(w)
        with col_conf:
            st.metric("Detection confidence", f"{detection.confidence:.0f}%")

        checklist_name = local_checklist or "STROBE"
    else:
        checklist_name = manual_checklist if manual_checklist != "(auto)" else "CONSORT"

    # --- Section parsing ---
    with st.spinner("Parsing article sections..."):
        sections = parser.parse(article_text)
        summary = parser.get_section_summary(sections)

    with st.expander("Article Structure", expanded=False):
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.metric("Total words", f"{summary['total_words']:,}")
            st.metric("Sections found", summary['total_sections'])
        with col_s2:
            st.metric("IMRaD complete", "Yes" if summary['imrad_complete'] else "No")
            st.metric("Has abstract", "Yes" if summary['has_abstract'] else "No")

        for name, info in summary['sections'].items():
            subs = f" ({', '.join(info['subsections'])})" if info['subsections'] else ""
            st.caption(f"**{name}** — {info['words']} words{subs}")

    # --- Run checklist ---
    with st.spinner(f"Applying {checklist_name} checklist..."):
        result = checker.check(article_text, checklist_name, sections=sections)

    # --- Overall Quality Assessment ---
    st.divider()

    grade_colors = {'A': '🟢', 'B': '🔵', 'C': '🟡', 'D': '🟠', 'F': '🔴'}
    grade_emoji = grade_colors.get(result.grade, '⚪')

    st.header(f"Reporting Quality: {grade_emoji} Grade {result.grade}")
    st.subheader(result.grade_label)

    # Top-level metrics
    col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
    with col_m1:
        st.metric(
            "Quality Score",
            f"{result.weighted_score:.1f}%",
            help="Weighted reporting quality score (0–100%)",
        )
    with col_m2:
        st.metric("Fully Reported", f"{result.present_count}")
    with col_m3:
        st.metric("Partially Reported", f"{result.partial_count}")
    with col_m4:
        st.metric("Missing", f"{result.absent_count}")
    with col_m5:
        st.metric("Total Items", f"{result.total_items}")

    # Progress bar
    st.progress(min(result.weighted_score / 100, 1.0))

    # Critical missing items warning
    critical_missing = [
        i for i in result.items
        if i.verdict in ('absent', 'explicitly_absent') and i.weight >= 1.1
    ]
    if critical_missing:
        with st.expander(f"⚠️ {len(critical_missing)} critical items missing (high-weight)", expanded=True):
            for item in critical_missing:
                st.markdown(f"- **Item {item.item_id}** ({item.section}): {item.description}")

    # --- Audience-specific report ---
    st.divider()
    detected_type = detection.study_type if auto_detect else ''
    audience_report = checker.generate_report(result, 'markdown', audience=audience,
                                              study_type=detected_type)
    with st.expander("📋 Full Report", expanded=(audience != 'specialist')):
        st.markdown(audience_report)

    # --- Section coverage ---
    st.subheader("Section Coverage")

    coverage_cols = st.columns(len(result.section_coverage))
    for i, (sec, cov) in enumerate(sorted(result.section_coverage.items())):
        with coverage_cols[i % len(coverage_cols)]:
            color = "green" if cov >= 70 else "orange" if cov >= 40 else "red"
            st.markdown(f"**{sec}**")
            st.progress(cov / 100)
            st.caption(f"{cov:.0f}%")

    # --- Detailed items ---
    st.subheader("Detailed Item Results")

    # Filter controls
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        verdict_filter = st.multiselect(
            "Filter by verdict",
            options=["present", "partial", "absent", "explicitly_absent"],
            default=["present", "partial", "absent", "explicitly_absent"],
        )
    with filter_col2:
        section_filter = st.multiselect(
            "Filter by section",
            options=sorted(set(
                i.section.split(' - ')[0] for i in result.items
            )),
            default=[],
        )

    # Items display
    current_section = None
    for item in result.items:
        if item.verdict not in verdict_filter:
            continue
        base_section = item.section.split(' - ')[0] if ' - ' in item.section else item.section
        if section_filter and base_section not in section_filter:
            continue

        if base_section != current_section:
            current_section = base_section
            st.markdown(f"### {current_section}")

        icon = {
            'present': '✅',
            'partial': '🟡',
            'absent': '❌',
            'explicitly_absent': '🚫',
        }.get(item.verdict, '❓')

        with st.container():
            col_icon, col_desc, col_conf = st.columns([0.5, 8, 1.5])

            with col_icon:
                st.markdown(f"## {icon}")

            with col_desc:
                st.markdown(f"**Item {item.item_id}:** {item.description}")

                if item.matched_keywords:
                    st.caption(
                        f"Keywords: {', '.join(item.matched_keywords)} "
                        f"({item.keyword_match_ratio:.0%} match) · "
                        f"Found in: {', '.join(set(item.matched_in_sections))}"
                    )

                if show_evidence and item.evidence_snippets:
                    st.caption(f"📝 _{item.evidence_snippets[0]}_")

            with col_conf:
                conf_pct = item.confidence * 100
                st.metric("Conf.", f"{conf_pct:.0f}%", label_visibility="collapsed")

    # --- Export ---
    st.divider()
    st.subheader("Export Report")

    export_col1, export_col2, export_col3 = st.columns(3)

    with export_col1:
        md_report = checker.generate_report(result, 'markdown', audience=audience,
                                            study_type=detected_type if auto_detect else '')
        st.download_button(
            "📄 Download Markdown",
            data=md_report,
            file_name=f"{uploaded_file.name.rsplit('.', 1)[0]}_report.md",
            mime="text/markdown",
        )

    with export_col2:
        json_report = checker.generate_report(result, 'json')
        st.download_button(
            "📊 Download JSON",
            data=json_report,
            file_name=f"{uploaded_file.name.rsplit('.', 1)[0]}_report.json",
            mime="application/json",
        )

    with export_col3:
        text_report = checker.generate_report(result, 'text')
        st.download_button(
            "📝 Download Text",
            data=text_report,
            file_name=f"{uploaded_file.name.rsplit('.', 1)[0]}_report.txt",
            mime="text/plain",
        )

else:
    # Landing page when no file is uploaded
    st.markdown("---")

    st.markdown("""
    ### How it works

    1. **Upload** your article (PDF or text)
    2. **Auto-detection** identifies the study type (RCT, systematic review, cohort, etc.)
    3. **Section parsing** splits the article into IMRaD sections
    4. **Context-aware matching** checks each checklist item in the expected section
    5. **Weighted scoring** gives you a nuanced compliance score

    ### Supported checklists

    | Checklist | Study Type | Items |
    |-----------|-----------|-------|
    | CONSORT 2010 | Randomized Controlled Trials | 37 |
    | PRISMA 2020 | Systematic Reviews & Meta-analyses | varies |
    | STROBE | Observational Studies | varies |
    | GENOMICS | Genomic/Sequence Analysis | varies |

    ### What makes this different?

    Unlike simple keyword searches, this tool uses **section-aware matching** —
    it checks whether "randomization" appears in the Methods section, not just
    anywhere in the text. This dramatically reduces false positives and gives
    you a reliable compliance assessment.
    """)
