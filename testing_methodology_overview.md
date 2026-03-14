# Методология тестирования Scientific Article Checker

## Обзор

Тестовая система состоит из **46 тестов** в двух файлах, покрывающих три компонента инструмента: парсер секций, проверщик по чек-листу и детектор типа исследования. Тесты написаны на pytest и используют синтетические тексты статей с заранее размеченными ground truth аннотациями.

---

## 1. Тестовые данные (test fixtures)

Вместо реальных статей (которые подвержены копирайту и не воспроизводимы) тесты используют **синтетические тексты**, специально написанные для тестирования:

**Для чекера (`test_quality.py`):**

- **WELL_STRUCTURED_RCT** — идеально оформленное РКИ (~200 строк), содержащее все 37 пунктов CONSORT: от structured abstract до funding disclosure. Каждый пункт чек-листа намеренно представлен в правильной секции с ожидаемой терминологией. Это эталон «хорошей статьи».
- **POORLY_REPORTED_RCT** — имитация статьи в стиле Gautret et al. (~15 строк): нет рандомизации, нет ослепления, нет расчёта размера выборки, минимальный статистический анализ. Это эталон «плохой статьи».
- **EMPTY_TEXT** и **SHORT_TEXT** — граничные случаи для проверки устойчивости.

**Для детектора (`test_detector.py`):**

- 10 синтетических текстов, по одному на каждый тип исследования: RCT, non-randomized intervention, systematic review, cohort, case-control, case report, genomic, qualitative, diagnostic accuracy. Плюс AMBIGUOUS и EMPTY.

**Ground truth аннотации:**

Для двух основных текстов вручную размечены множества (sets) пунктов CONSORT:
- `WELL_STRUCTURED_EXPECTED_PRESENT` — 34 пункта, которые *точно должны быть найдены*
- `POORLY_REPORTED_EXPECTED_ABSENT` — 22 пункта, которые *точно должны быть не найдены*

Это позволяет считать recall (полноту) и specificity (специфичность) количественно.

---

## 2. Группы тестов для чекера (test_quality.py — 25 тестов)

### 2.1. TestSectionParser — 7 тестов

Проверяют, что парсер секций корректно разбирает текст статьи на IMRaD-структуру.

| Тест | Что проверяет | Метрика |
|------|---------------|---------|
| `test_parse_well_structured` | Обнаружение Abstract, Methods, Results, Discussion | Наличие ключей в dict |
| `test_imrad_complete` | Минимум 4 секции распознаны | len(sections) >= 4 |
| `test_methods_subsections` | Подсекции Methods (participants, randomization, blinding) | len(subsections) >= 2 |
| `test_empty_text` | Пустой текст не вызывает crash | Наличие full_text |
| `test_short_text` | Очень короткий текст обрабатывается | Наличие full_text |
| `test_poorly_structured` | Текст без заголовков обрабатывается | Наличие full_text |
| `test_section_aliases` | Маппинг секций чек-листа → секций статьи | Корректные ключи |

**Зачем:** парсер — фундамент всей системы. Если секции определяются неверно, контекстный матчинг теряет смысл.

### 2.2. TestEnhancedCheckerQuality — 7 тестов

Основные тесты качества — сравнение с ground truth.

| Тест | Что проверяет | Порог |
|------|---------------|-------|
| `test_well_structured_high_compliance` | Хорошая статья получает высокий скор | weighted > 70%, simple > 70% |
| `test_well_structured_ground_truth` | Recall: доля правильно найденных пунктов из ожидаемых | recall >= 80% |
| `test_poorly_reported_low_compliance` | Плохая статья получает низкий скор | weighted < 50% |
| `test_poorly_reported_detects_absence` | Specificity: доля правильно не найденных | specificity >= 70% |
| `test_empty_text_no_crash` | Пустой текст → score = 0, без crash | weighted == 0 |
| `test_short_text_low_score` | Короткий текст → скор близок к нулю | weighted < 20% |
| `test_section_awareness` | Keywords в правильной секции → выше confidence чем в fallback | avg_section >= avg_fallback × 0.8 |

**Зачем:** это ядро оценки. Recall отвечает на вопрос «не пропускаем ли мы реально присутствующие пункты?», specificity — «не находим ли мы то, чего нет?».

### 2.3. TestEvidenceSnippets — 1 тест

| Тест | Что проверяет | Порог |
|------|---------------|-------|
| `test_snippets_provided` | У найденных пунктов есть цитата из текста | >= 70% present items имеют snippets |

**Зачем:** evidence snippets — это объяснимость (explainability). Пользователь должен видеть, *почему* система решила, что пункт выполнен.

### 2.4. TestSectionCoverage — 2 теста

| Тест | Что проверяет | Порог |
|------|---------------|-------|
| `test_section_coverage_keys` | Отчёт содержит покрытие по основным секциям | >= 3 секции |
| `test_methods_coverage_detail` | Methods имеет хорошее покрытие для хорошей статьи | > 40% |

**Зачем:** покрытие по секциям — ключевая метрика для авторов. «У вас слабый Methods» полезнее чем просто общий %.

### 2.5. TestConfidenceScoring — 3 теста

| Тест | Что проверяет | Порог |
|------|---------------|-------|
| `test_confidence_range` | Все confidence в диапазоне [0.0, 1.0] | Строгие границы |
| `test_high_confidence_items` | Много keywords + правильная секция → высокий confidence | >= 0.5 |
| `test_verdict_consistency` | Verdict согласован с confidence (present → >= 0.5; absent → < 0.6) | Логическая согласованность |

**Зачем:** система использует 4-уровневый verdict (present/partial/absent/explicitly_absent) вместо бинарного. Тесты гарантируют, что confidence и verdict не противоречат друг другу.

### 2.6. TestReportGeneration — 3 теста

| Тест | Что проверяет |
|------|---------------|
| `test_markdown_report` | Markdown содержит заголовки и имя чек-листа |
| `test_json_report` | JSON валиден и содержит все поля |
| `test_text_report` | Текстовый отчёт содержит FOUND/MISSING |

**Зачем:** отчёт — финальный продукт для пользователя. Тесты гарантируют, что все три формата генерируются без ошибок.

### 2.7. TestEnhancedVsOriginal — 2 теста (регрессионные)

| Тест | Что проверяет |
|------|---------------|
| `test_no_generic_keyword_false_positives` | Статья без abstract → item 1b (structured abstract) НЕ детектится с confidence < 0.6 |
| `test_distinguishes_well_vs_poorly_reported` | Разрыв между хорошей и плохой статьёй >= 25 пунктов |

**Зачем:** это регрессионные тесты, фиксирующие конкретные баги старого чекера. Первый тест ловит проблему, когда слова "background", "methods", "results" встречались в тексте и создавали ложное срабатывание на structured abstract. Второй гарантирует, что система различает качественные и некачественные статьи.

---

## 3. Группы тестов для детектора (test_detector.py — 21 тест)

### 3.1. TestCorrectClassification — 10 тестов

Каждый тест подаёт синтетический текст определённого типа исследования и проверяет, что детектор выдаёт правильную классификацию.

| Тест | Входной текст | Ожидаемый тип |
|------|---------------|---------------|
| `test_true_rct_detected` | Текст с double-blind, placebo-controlled, CONSORT | `randomized_controlled_trial` (confidence > 60%) |
| `test_non_randomized_not_rct` | Open-label, non-randomized, single-arm | `non_randomized_intervention` (НЕ RCT) |
| `test_rct_not_in_scores_for_non_randomized` | То же | RCT score <= 0 |
| `test_systematic_review` | PRISMA, meta-analysis, forest plot | `systematic_review_interventions` |
| `test_cohort_study` | Prospective cohort, person-years, hazard ratio | `cohort_study` |
| `test_case_control` | Case-control, odds ratio, matched controls | `case_control` |
| `test_case_report` | Single case, rare case, we report | `case_report` |
| `test_genomic_study` | Whole-genome sequencing, NGS, GenBank | `genomic_study` |
| `test_qualitative` | Semi-structured interviews, thematic analysis | `qualitative` |
| `test_diagnostic_accuracy` | Sensitivity/specificity, ROC, QUADAS | `diagnostic_accuracy` |

**Зачем:** детектор определяет, какой чек-лист применять. Неверная классификация → неверный чек-лист → бесполезный отчёт.

### 3.2. TestNegativePatterns — 3 теста

Критическая группа: проверяет, что **негативные паттерны** работают и подавляют ложные срабатывания.

| Тест | Что проверяет |
|------|---------------|
| `test_non_randomized_penalizes_rct` | Текст с "non-randomized" даёт RCT-скор ниже, чем без него |
| `test_open_label_penalizes_rct` | "Open-label" снижает RCT-скор |
| `test_uncontrolled_penalizes_rct` | "Uncontrolled" обнуляет RCT-скор |

**Зачем:** это была главная проблема — слово "randomized" внутри "non-randomized" давало баллы за RCT. Негативные паттерны вычитают баллы при обнаружении отрицающего контекста.

### 3.3. TestChecklistMapping — 4 теста

| Тест | Тип → Чек-лист |
|------|----------------|
| RCT → CONSORT | Randomized controlled trial → CONSORT |
| Non-randomized → STROBE | Non-randomized intervention → STROBE |
| Systematic review → PRISMA | Systematic review → PRISMA |
| Genomic → GENOMICS | Genomic study → GENOMICS |

**Зачем:** проверяет, что маппинг тип → чек-лист корректен. Ошибка здесь означает применение неправильного чек-листа.

### 3.4. TestEdgeCases — 4 теста

| Тест | Что проверяет |
|------|---------------|
| `test_empty_text` | Пустой текст → type="unknown", confidence=0 |
| `test_ambiguous_text` | Неоднозначный текст → confidence < 80% |
| `test_all_study_types_have_patterns` | Все 18 типов из маппинга имеют detection patterns |
| `test_warnings_on_close_match` | Близкие скоры генерируют предупреждение |

**Зачем:** система должна корректно сообщать о неуверенности, а не угадывать.

---

## 4. Ключевые метрики качества

### Результаты на текущих данных

| Метрика | Хорошая статья (синт.) | Плохая статья (синт.) |
|---------|------------------------|-----------------------|
| Weighted score | **75.6%** | **2.3%** |
| Simple score | **86.5%** | **2.7%** |
| Present items | 32/37 | 1/37 |
| Discrimination gap | **73.3 пункта** | — |

### Что означают пороги в тестах

- **Recall >= 80%** — система не пропускает более 20% реально присутствующих пунктов
- **Specificity >= 70%** — система не находит более 30% реально отсутствующих пунктов (false positive rate < 30%)
- **Discrimination gap >= 25** — система чётко различает хорошие и плохие статьи
- **Confidence consistency** — verdict «present» только при confidence >= 0.5, «absent» при < 0.6

### Что тесты НЕ покрывают (известные ограничения)

- **Реальные PDF-статьи** — только синтетические тексты. Извлечение текста из PDF может ухудшать качество
- **Другие чек-листы** — ground truth пока только для CONSORT, нет для PRISMA/STROBE/GENOMICS
- **Мультиязычность** — тесты только на английском
- **Семантический анализ** — система использует keyword matching, не NLP. Перефразированные пункты могут быть пропущены
- **Межсекционные ссылки** — «see Methods for details» в Results не учитывается

---

## 5. Архитектура тестового пайплайна

```
test_quality.py (25 тестов)                test_detector.py (21 тест)
├── TestSectionParser [7]                  ├── TestCorrectClassification [10]
│   └── section_parser.py                  │   └── study_detector.py
├── TestEnhancedCheckerQuality [7]         ├── TestNegativePatterns [3]
│   └── enhanced_checker.py                │   └── Негативный контекст
│       └── section_parser.py              ├── TestChecklistMapping [4]
│       └── checklists/consort.json        │   └── Тип → чек-лист
├── TestEvidenceSnippets [1]               └── TestEdgeCases [4]
├── TestSectionCoverage [2]                    └── Граничные случаи
├── TestConfidenceScoring [3]
├── TestReportGeneration [3]
└── TestEnhancedVsOriginal [2]
    └── Регрессионные тесты
```

Запуск: `pytest tests/ -v`

---

## 6. Как расширять тесты

Для добавления нового чек-листа (например, PRISMA):

1. Создать синтетический текст `WELL_STRUCTURED_SYSTEMATIC_REVIEW`
2. Разметить `EXPECTED_PRESENT` и `EXPECTED_ABSENT` множества
3. Добавить тесты по аналогии с `TestEnhancedCheckerQuality`, но с `checker.check(text, 'PRISMA')`

Для тестирования на реальных статьях:

1. Извлечь текст из PDF
2. Вручную разметить ground truth (какие пункты реально присутствуют)
3. Сравнить с результатом системы
4. Зафиксировать как regression test
