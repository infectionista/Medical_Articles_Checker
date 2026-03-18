#!/usr/bin/env python3
"""
Demo Pipeline — полный путь проверки научной статьи.

Запуск:
    python demo_pipeline.py test_input/article.pdf
    python demo_pipeline.py test_input/article.md

Что делает:
  1. Конвертирует PDF → текст (если нужно)
  2. Определяет тип исследования и чеклист
  3. Фаза 1-2: ключевые слова + TF-IDF → быстрая оценка
  4. Выводит вердикт для трёх аудиторий (обыватель / студент / специалист)
  5. Спрашивает: «Улучшить оценку с помощью ИИ?»
  6. Фаза 3: LLM (Claude Haiku) → улучшенный вердикт с пояснением что изменилось

Вердикты сохраняются в test_output/<article>_<timestamp>.md
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

# ── UTF-8 everywhere ──
os.environ['PYTHONUTF8'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8'

# ── Load .env ──
_script_dir = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_script_dir, '.env')
if os.path.exists(_env_path):
    with open(_env_path, encoding='utf-8-sig') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _, _v = _line.partition('=')
                _k = _k.strip()
                _v = _v.strip().strip('"').strip("'")
                _v = ''.join(c for c in _v if 32 <= ord(c) <= 126)
                os.environ[_k] = _v

sys.path.insert(0, _script_dir)
os.chdir(_script_dir)

OUTPUT_DIR = os.path.join(_script_dir, 'test_output')
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

_log_lines = []


def log(text: str = ''):
    """Print to console AND collect for file output."""
    print(text)
    _log_lines.append(text)


def divider(title: str = ''):
    if title:
        log(f"\n{'═' * 60}")
        log(f"  {title}")
        log(f"{'═' * 60}\n")
    else:
        log(f"\n{'─' * 60}\n")


def extract_pdf_text(pdf_path: str) -> str:
    """Extract text from PDF using PyPDF2, fallback to pdfplumber, fallback to pymupdf."""
    errors = []

    # --- Attempt 1: PyPDF2 ---
    try:
        import PyPDF2
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            pages = [p.extract_text() or '' for p in reader.pages]
        text = '\n\n'.join(pages)
        if len(text.strip()) > 200:
            return text
        errors.append(f"PyPDF2: extracted only {len(text.strip())} chars (too short)")
    except ImportError:
        errors.append("PyPDF2: not installed")
    except Exception as e:
        errors.append(f"PyPDF2: {e}")

    # --- Attempt 2: pdfplumber ---
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            pages = [p.extract_text() or '' for p in pdf.pages]
        text = '\n\n'.join(pages)
        if len(text.strip()) > 200:
            return text
        errors.append(f"pdfplumber: extracted only {len(text.strip())} chars (too short)")
    except ImportError:
        errors.append("pdfplumber: not installed")
    except Exception as e:
        errors.append(f"pdfplumber: {e}")

    # --- Attempt 3: pymupdf (fitz) ---
    try:
        import fitz  # pymupdf
        doc = fitz.open(pdf_path)
        pages = [page.get_text() for page in doc]
        doc.close()
        text = '\n\n'.join(pages)
        if len(text.strip()) > 200:
            return text
        errors.append(f"pymupdf: extracted only {len(text.strip())} chars (too short)")
    except ImportError:
        errors.append("pymupdf: not installed")
    except Exception as e:
        errors.append(f"pymupdf: {e}")

    # --- All failed ---
    print("  ❌ Не удалось извлечь текст из PDF.")
    print("     Попытки:")
    for err in errors:
        print(f"       • {err}")
    print()
    print("     Установите хотя бы один из:")
    print("       pip install PyPDF2")
    print("       pip install pdfplumber")
    print("       pip install pymupdf")
    sys.exit(1)


def save_output(article_stem: str):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{article_stem}_{timestamp}.md"
    filepath = os.path.join(OUTPUT_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(_log_lines))
    print(f"\n  📄 Результат сохранён: test_output/{filename}")


# ═══════════════════════════════════════════════════════════════════
#  LLM improvement diff — what changed and why
# ═══════════════════════════════════════════════════════════════════

def compute_llm_diff(result_before, result_after):
    """Compare two CheckResults and return list of improved items."""
    before_map = {it.item_id: it for it in result_before.items}
    after_map = {it.item_id: it for it in result_after.items}

    improvements = []
    for item_id, after_item in after_map.items():
        before_item = before_map.get(item_id)
        if not before_item:
            continue

        verdict_rank = {'absent': 0, 'partial': 1, 'present': 2}
        before_rank = verdict_rank.get(before_item.verdict, 0)
        after_rank = verdict_rank.get(after_item.verdict, 0)

        if after_rank > before_rank:
            # Find LLM evidence
            llm_evidence = ''
            for snippet in after_item.evidence_snippets:
                if '[LLM]' in snippet:
                    llm_evidence = snippet.replace('[LLM] ', '')
                    break

            improvements.append({
                'item_id': item_id,
                'section': after_item.section,
                'description': after_item.description,
                'before_verdict': before_item.verdict,
                'after_verdict': after_item.verdict,
                'before_conf': before_item.confidence,
                'after_conf': after_item.confidence,
                'llm_evidence': llm_evidence,
            })

    return improvements


def format_llm_diff_public(improvements, score_before, score_after):
    """Format LLM improvements for a general audience."""
    if not improvements:
        return ''

    lines = []
    lines.append("## 🔍 Что нашёл ИИ-анализ")
    lines.append("")
    lines.append(f"ИИ дополнительно проверил статью и нашёл **{len(improvements)} элемент(ов)**, "
                 f"которые пропустил быстрый анализ.")
    lines.append(f"Оценка повысилась: **{score_before:.0f}% → {score_after:.0f}%**.")
    lines.append("")

    for imp in improvements:
        emoji = '🟢' if imp['after_verdict'] == 'present' else '🟡'
        lines.append(f"- {emoji} **{imp['description'][:60]}** — теперь найден")
        if imp['llm_evidence']:
            # Short evidence for public
            ev = imp['llm_evidence'][:120]
            if len(imp['llm_evidence']) > 120:
                ev += '...'
            lines.append(f"  *ИИ обнаружил: {ev}*")

    lines.append("")
    return '\n'.join(lines)


def format_llm_diff_student(improvements, score_before, score_after):
    """Format LLM improvements for a student audience."""
    if not improvements:
        return ''

    lines = []
    lines.append("## 🔍 Improvements found by AI analysis")
    lines.append("")
    lines.append(f"The AI re-examined **{len(improvements)} item(s)** that keyword matching missed. "
                 f"Score changed: **{score_before:.0f}% → {score_after:.0f}%**.")
    lines.append("")
    lines.append("| Item | Section | Description | Before | After | AI Evidence |")
    lines.append("|------|---------|-------------|--------|-------|-------------|")

    for imp in improvements:
        before_icon = {'absent': '❌', 'partial': '🟡', 'present': '✅'}[imp['before_verdict']]
        after_icon = {'absent': '❌', 'partial': '🟡', 'present': '✅'}[imp['after_verdict']]
        desc = imp['description'][:50]
        sec = imp['section'].split(' - ')[-1] if ' - ' in imp['section'] else imp['section']
        ev = imp['llm_evidence'][:80] + '...' if len(imp['llm_evidence']) > 80 else imp['llm_evidence']
        lines.append(f"| {imp['item_id']} | {sec} | {desc} | {before_icon} {imp['before_verdict']} | "
                     f"{after_icon} {imp['after_verdict']} | {ev} |")

    lines.append("")
    lines.append("**Why did keyword matching miss these?** The automated Phase 1-2 analysis "
                 "looks for specific phrases and statistical patterns. When authors use "
                 "non-standard phrasing or describe concepts indirectly, the AI (Claude Haiku) "
                 "can understand the meaning in context.")
    lines.append("")
    return '\n'.join(lines)


def format_llm_diff_specialist(improvements, score_before, score_after):
    """Format LLM improvements for specialists."""
    if not improvements:
        return ''

    lines = []
    lines.append("## Phase 3 LLM improvements")
    lines.append("")
    lines.append(f"Claude Haiku reclassified **{len(improvements)}/{len(improvements)} items** "
                 f"from absent→partial/present. Score: {score_before:.0f}% → {score_after:.0f}%.")
    lines.append("")

    for imp in improvements:
        before_icon = {'absent': '❌', 'partial': '🟡', 'present': '✅'}[imp['before_verdict']]
        after_icon = {'absent': '❌', 'partial': '🟡', 'present': '✅'}[imp['after_verdict']]
        lines.append(f"**Item {imp['item_id']}** [{imp['section']}] "
                     f"{before_icon} {imp['before_verdict']} → {after_icon} {imp['after_verdict']} "
                     f"(conf: {imp['before_conf']:.0%} → {imp['after_conf']:.0%})")
        lines.append(f"  {imp['description']}")
        if imp['llm_evidence']:
            lines.append(f"  Evidence: _{imp['llm_evidence']}_")
        lines.append("")

    return '\n'.join(lines)


# ═══════════════════════════════════════════════════════════════════
#  Grade label helper
# ═══════════════════════════════════════════════════════════════════

def grade_label(weighted_score: float) -> str:
    """Return grade string from weighted score."""
    if weighted_score >= 80:
        return '🟢 A'
    elif weighted_score >= 60:
        return '🟡 B'
    elif weighted_score >= 45:
        return '🟠 C'
    elif weighted_score >= 30:
        return '🟠 D'
    else:
        return '🔴 F'


# ═══════════════════════════════════════════════════════════════════
#  Main pipeline
# ═══════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Использование: python demo_pipeline.py <article.pdf|article.md>")
        sys.exit(1)

    input_path = sys.argv[1]
    if not os.path.exists(input_path):
        print(f"Файл не найден: {input_path}")
        sys.exit(1)

    article_stem = Path(input_path).stem

    divider("ШАГ 1: Загрузка и конвертация статьи")

    # ── Step 1: Load article text ──
    if input_path.lower().endswith('.pdf'):
        log(f"  Файл: {os.path.basename(input_path)} (PDF)")
        log(f"  Извлекаю текст...")
        t0 = time.time()
        article_text = extract_pdf_text(input_path)
        elapsed = time.time() - t0
        log(f"  ✅ Извлечено {len(article_text):,} символов за {elapsed:.1f}с")
    elif input_path.lower().endswith(('.md', '.txt')):
        log(f"  Файл: {os.path.basename(input_path)} (текст)")
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            article_text = f.read()
        log(f"  ✅ Загружено {len(article_text):,} символов")
    else:
        log(f"  Файл: {os.path.basename(input_path)}")
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
            article_text = f.read()
        log(f"  ✅ Загружено {len(article_text):,} символов")

    if len(article_text.strip()) < 100:
        log("  ❌ Текст слишком короткий. Проверьте файл.")
        sys.exit(1)

    # ── Step 2: Detect study type ──
    divider("ШАГ 2: Определение типа исследования")

    from study_detector import EnhancedStudyTypeDetector
    detector = EnhancedStudyTypeDetector()
    detection = detector.detect(article_text)
    type_info = detector.get_type_info(detection.study_type)
    checklist_name = detector.get_checklist_for_type(detection.study_type)

    log(f"  Тип:       {type_info.get('name_ru', detection.study_type)}")
    log(f"             ({type_info.get('name_en', '')})")
    log(f"  Уверенность: {detection.confidence:.0f}%")
    if detection.subtypes:
        log(f"  Подтипы:   {', '.join(detection.subtypes)}")
    log(f"  Чеклист:   {checklist_name or 'не определён'}")

    if detection.warnings:
        for w in detection.warnings:
            log(f"  ⚠ {w}")

    if not checklist_name:
        log("\n  ❌ Для данного типа исследования нет локального чеклиста.")
        save_output(article_stem)
        sys.exit(1)

    # ── Step 3: Phase 1-2 evaluation (keywords + TF-IDF) ──
    divider("ШАГ 3: Быстрая оценка (ключевые слова + TF-IDF)")

    from enhanced_checker import EnhancedChecker
    checker = EnhancedChecker(checklist_dir='checklists')

    # Temporarily disable LLM
    saved_key = os.environ.pop('ANTHROPIC_API_KEY', None)

    t0 = time.time()
    result_no_llm = checker.check(article_text, checklist_name)
    elapsed = time.time() - t0

    present = sum(1 for i in result_no_llm.items if i.verdict == 'present')
    partial = sum(1 for i in result_no_llm.items if i.verdict == 'partial')
    absent = sum(1 for i in result_no_llm.items if i.verdict == 'absent')

    log(f"  Время:     {elapsed:.1f}с")
    log(f"  Найдено:   {present} из {result_no_llm.total_items} пунктов")
    log(f"  Частично:  {partial}")
    log(f"  Не найдено: {absent}")
    log(f"  Оценка:    {result_no_llm.simple_score:.0f}% (простая) / {result_no_llm.weighted_score:.0f}% (взвешенная)")
    log(f"  Грейд:     {grade_label(result_no_llm.weighted_score)}")

    # Restore API key
    if saved_key:
        os.environ['ANTHROPIC_API_KEY'] = saved_key

    # ── Step 3.5: Quality lenses ──
    divider("ШАГ 3.5: Quality Lenses (external validity)")

    t0 = time.time()
    lenses = checker.evaluate_quality_lenses(article_text)
    tier_verdicts = checker.build_tiered_verdicts(lenses, result_no_llm)
    elapsed = time.time() - t0

    log(f"  Время: {elapsed:.1f}с")

    lens_weights = {'red_flags': 0.30, 'statistical_rigor': 0.25,
                    'reproducibility': 0.20, 'transparency': 0.15,
                    'evidence_strength': 0.10}
    w_sum = sum(lenses[k]['score'] * lens_weights.get(k, 0.1) for k in lenses)
    w_total = sum(lens_weights.get(k, 0.1) for k in lenses)
    composite = w_sum / w_total if w_total > 0 else 0.0
    comp_icon = '🟢' if composite >= 0.7 else '🟡' if composite >= 0.4 else '🔴'
    log(f"  Composite: {comp_icon} {composite:.0%}")

    for name, data in lenses.items():
        sc = data['score']
        icon = '🟢' if sc >= 0.7 else '🟡' if sc >= 0.4 else '🔴'
        log(f"    {icon} {data['label']}: {sc:.0%}")

    log()
    for tier_name, tier_label in [('public', 'Обыватель'), ('student', 'Студент'), ('specialist', 'Специалист')]:
        blocks = tier_verdicts.get(tier_name, [])
        if blocks:
            log(f"  [{tier_label}] {len(blocks)} verdict(s):")
            for b in blocks:
                log(f"    {b['icon']} {b['label']} — {b['message'][:90]}...")
        else:
            log(f"  [{tier_label}] Нет замечаний ✓")

    # ── Step 4: Reports for 3 audiences ──
    for audience, label in [('public', 'ОБЫВАТЕЛЬ'), ('student', 'СТУДЕНТ'), ('specialist', 'СПЕЦИАЛИСТ')]:
        divider(f"ВЕРДИКТ: {label}")
        report = checker.generate_report(
            result_no_llm,
            format='markdown',
            audience=audience,
            study_type=detection.study_type,
            detection_result=detection,
            article_text=article_text,
            lenses=lenses,
            tier_verdicts=tier_verdicts,
        )
        log(report)

    # ── Step 5: Ask about LLM upgrade (always) ──
    divider()

    absent_ratio = absent / result_no_llm.total_items if result_no_llm.total_items else 0
    has_api_key = bool(os.environ.get('ANTHROPIC_API_KEY', ''))

    if absent_ratio <= 0.50:
        log(f"  ℹ️  Быстрый анализ нашёл {present + partial} из {result_no_llm.total_items} пунктов.")
        log(f"     Не найдено: {absent} ({absent_ratio:.0%}).")
    else:
        log(f"  ⚠  {absent} из {result_no_llm.total_items} пунктов не найдены ({absent_ratio:.0%}).")
        log(f"     Быстрый анализ мог пропустить элементы из-за нестандартных формулировок.")

    log(f"     ИИ-анализ может найти дополнительные элементы, распознав смысл в контексте.")
    log()

    if not has_api_key:
        log("  ❌ ANTHROPIC_API_KEY не задан в .env — LLM недоступен.")
        log("     Добавьте ключ в файл .env для активации Phase 3.")
        save_output(article_stem)
        return

    print()
    print("  💡 Запустить ИИ-анализ (Claude Haiku) для углублённой проверки?")
    print("     Стоимость: ~$0.01 за статью")
    print()
    answer = input("     Запустить? [y/N]: ").strip().lower()

    log(f"  → Пользователь выбрал: {answer}")

    if answer not in ('y', 'yes', 'д', 'да'):
        log("\n  Пропущено. Используются результаты без LLM.")
        save_output(article_stem)
        return

    # ── Step 6: Phase 3 — LLM evaluation ──
    divider("ШАГ 4: ИИ-анализ (Claude Haiku)")

    log("  Запрашиваю Claude Haiku (переоценка + комментарий)...")
    t0 = time.time()

    # 6a: Re-evaluate with LLM forced on all absent+partial items
    result_with_llm = checker.check(article_text, checklist_name, force_llm=True)

    present_new = sum(1 for i in result_with_llm.items if i.verdict == 'present')
    partial_new = sum(1 for i in result_with_llm.items if i.verdict == 'partial')
    absent_new = sum(1 for i in result_with_llm.items if i.verdict == 'absent')

    log(f"  Переоценка:")
    log(f"    Найдено:   {present_new} (+{present_new - present})")
    log(f"    Частично:  {partial_new} (+{partial_new - partial})")
    log(f"    Не найдено: {absent_new} ({absent_new - absent})")
    log(f"    Оценка:    {result_with_llm.simple_score:.0f}% (было {result_no_llm.simple_score:.0f}%)")
    log(f"    Грейд:     {grade_label(result_with_llm.weighted_score)} (был {grade_label(result_no_llm.weighted_score)})")

    # 6b: Generate LLM commentary (always — this is the guaranteed value)
    log("  Генерирую экспертный комментарий...")
    commentary = checker.generate_llm_commentary(result_with_llm, article_text, checklist_name)
    elapsed = time.time() - t0

    log(f"  Общее время: {elapsed:.1f}с")

    # ── Compute diff ──
    improvements = compute_llm_diff(result_no_llm, result_with_llm)

    if improvements:
        log(f"\n  📊 ИИ улучшил оценку {len(improvements)} пунктов:")
        for imp in improvements:
            log(f"     • {imp['item_id']:5s} {imp['before_verdict']:>7s} → {imp['after_verdict']:<7s}  {imp['description'][:50]}")

    # Show commentary summary
    if commentary.get('summary'):
        log(f"\n  🤖 ИИ-комментарий: {commentary['summary']}")

    # ── Step 7: Improved reports with diff blocks + commentary ──
    audience_formatters = {
        'public': format_llm_diff_public,
        'student': format_llm_diff_student,
        'specialist': format_llm_diff_specialist,
    }

    # Recompute verdicts with LLM-improved result (once, not per-audience)
    tier_verdicts_llm = checker.build_tiered_verdicts(lenses, result_with_llm)

    tier_map = {'public': 'public', 'student': 'student', 'specialist': 'specialist'}

    for audience, label in [('public', 'УЛУЧШЕННЫЙ ВЕРДИКТ: ОБЫВАТЕЛЬ'),
                            ('student', 'УЛУЧШЕННЫЙ ВЕРДИКТ: СТУДЕНТ'),
                            ('specialist', 'УЛУЧШЕННЫЙ ВЕРДИКТ: СПЕЦИАЛИСТ')]:
        divider(label)

        report = checker.generate_report(
            result_with_llm,
            format='markdown',
            audience=audience,
            study_type=detection.study_type,
            detection_result=detection,
            article_text=article_text,
            lenses=lenses,
            tier_verdicts=tier_verdicts_llm,
        )
        log(report)

        # Add diff block if there are improvements
        if improvements:
            formatter = audience_formatters[audience]
            diff_block = formatter(
                improvements,
                result_no_llm.weighted_score,
                result_with_llm.weighted_score,
            )
            if diff_block:
                log(diff_block)

        # Add LLM commentary — the guaranteed value-add
        if commentary:
            tier_key = tier_map[audience]
            tier_insight = commentary.get('tier_insights', {}).get(tier_key, '')
            item_comments = commentary.get('items', {})

            if tier_insight or item_comments:
                log("\n## 🤖 ИИ-экспертиза\n")
                if tier_insight:
                    log(f"> {tier_insight}\n")

                # Show per-item explanations (limited per tier)
                if item_comments:
                    if audience == 'public':
                        # Public: just show the summary, not per-item
                        pass
                    elif audience == 'student':
                        log("**Разбор пунктов с низкой оценкой:**\n")
                        for item_id, explanation in list(item_comments.items())[:8]:
                            log(f"- **{item_id}:** {explanation}")
                        log("")
                    else:  # specialist
                        log("**Per-item LLM assessment:**\n")
                        for item_id, explanation in item_comments.items():
                            log(f"- **{item_id}:** {explanation}")
                        log("")

    divider()
    score_before = result_no_llm.weighted_score
    score_after = result_with_llm.weighted_score
    grade_before = grade_label(score_before)
    grade_after = grade_label(score_after)
    n_improved = len(improvements)
    has_commentary = bool(commentary.get('summary'))
    log(f"  ✅ Готово!")
    log(f"     Оценка: {score_before:.0f}% ({grade_before}) → {score_after:.0f}% ({grade_after})")
    if n_improved:
        log(f"     ИИ дополнительно нашёл: {n_improved} элемент(ов)")
    if has_commentary:
        log(f"     ИИ-экспертиза: разбор {len(commentary.get('items', {}))} пунктов с пояснениями")
    if not n_improved and not has_commentary:
        log(f"     ИИ подтвердил результаты быстрого анализа — оценка не изменилась.")
    log(f"{'═' * 60}")

    save_output(article_stem)


if __name__ == '__main__':
    main()
