#!/usr/bin/env python3
"""
ASCII визуализация результатов из JSON (не требует matplotlib)
"""
import json
from pathlib import Path

def load_results():
    """Загрузить все результаты"""
    results = []
    for json_file in Path("reports").rglob("*_detailed_results.json"):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data['filename'] = json_file.parent.name
            results.append(data)
    return results

def create_bar_chart(value, max_value=100, width=50):
    """Создать ASCII bar chart"""
    filled = int((value / max_value) * width)
    bar = "█" * filled + "░" * (width - filled)
    return bar

def visualize_compliance(results):
    """Визуализация степени соответствия"""
    print("\n" + "="*80)
    print("  СТЕПЕНЬ СООТВЕТСТВИЯ ЧЕК-ЛИСТУ")
    print("="*80 + "\n")

    for r in results:
        name = r['filename'][:30].ljust(30)
        compliance = r['compliance_percentage']
        bar = create_bar_chart(compliance, 100, 40)

        # Цветовой индикатор
        if compliance >= 70:
            indicator = "🟢 ОТЛИЧНО"
        elif compliance >= 50:
            indicator = "🟡 УДОВЛ."
        else:
            indicator = "🔴 НИЗКО"

        print(f"{name} │ {bar} │ {compliance:5.1f}% {indicator}")

    print()

def visualize_sections(results):
    """Визуализация по секциям для каждой статьи"""
    print("\n" + "="*80)
    print("  ДЕТАЛИЗАЦИЯ ПО СЕКЦИЯМ")
    print("="*80 + "\n")

    for r in results:
        print(f"\n📄 {r['filename']}")
        print(f"   Тип: {r.get('detected_study_type', 'N/A')}")
        print(f"   Чек-лист: {r.get('checklist_name', 'N/A')}\n")

        # Группировка по секциям
        sections = {}
        for item in r['items']:
            section = item['section']
            if section not in sections:
                sections[section] = {'found': 0, 'total': 0}
            sections[section]['total'] += 1
            if item['found']:
                sections[section]['found'] += 1

        # Вывод секций
        for section, stats in sections.items():
            found = stats['found']
            total = stats['total']
            percent = (found / total * 100) if total > 0 else 0
            bar = create_bar_chart(percent, 100, 25)

            section_name = section[:35].ljust(35)
            print(f"   {section_name} │ {bar} │ {found}/{total} ({percent:.0f}%)")

        print()

def create_comparison_table(results):
    """Таблица сравнения"""
    print("\n" + "="*100)
    print("  СРАВНИТЕЛЬНАЯ ТАБЛИЦА")
    print("="*100 + "\n")

    # Заголовок
    print(f"{'Статья':<35} {'Тип исследования':<25} {'Чек-лист':<12} {'Найдено':<12} {'Соотв.':<10}")
    print("-"*100)

    # Данные
    for r in results:
        name = r['filename'][:33]
        study_type = r.get('detected_study_type', 'N/A')[:23]
        checklist = r.get('checklist_name', 'N/A')[:10]
        found_ratio = f"{r['items_found']}/{r['total_items']}"
        compliance = f"{r['compliance_percentage']:.1f}%"

        print(f"{name:<35} {study_type:<25} {checklist:<12} {found_ratio:<12} {compliance:<10}")

    print("\n" + "="*100 + "\n")

def create_html_dashboard(results):
    """Создать простой HTML дашборд"""
    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Анализ качества статей</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
        h1 { color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }
        h2 { color: #34495e; margin-top: 30px; }
        .article-card { background: #fff; border: 2px solid #e0e0e0; border-radius: 8px; padding: 20px; margin: 15px 0; }
        .article-title { font-size: 18px; font-weight: bold; color: #2c3e50; margin-bottom: 10px; }
        .progress-bar { width: 100%; height: 30px; background: #e0e0e0; border-radius: 15px; overflow: hidden; margin: 10px 0; }
        .progress-fill { height: 100%; background: linear-gradient(90deg, #4CAF50, #8BC34A); display: flex; align-items: center; padding-left: 10px; color: white; font-weight: bold; }
        .progress-fill.medium { background: linear-gradient(90deg, #FFC107, #FFD54F); }
        .progress-fill.low { background: linear-gradient(90deg, #F44336, #E57373); }
        .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-top: 15px; }
        .stat-box { background: #f8f9fa; padding: 15px; border-radius: 5px; text-align: center; }
        .stat-value { font-size: 24px; font-weight: bold; color: #3498db; }
        .stat-label { font-size: 12px; color: #7f8c8d; margin-top: 5px; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e0e0e0; }
        th { background: #3498db; color: white; font-weight: bold; }
        tr:hover { background: #f5f5f5; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Анализ качества научных статей</h1>
        <p>Автоматический анализ на основе стандартных чек-листов (CONSORT, STROBE, PRISMA)</p>
"""

    for r in results:
        compliance = r['compliance_percentage']
        progress_class = "low" if compliance < 50 else ("medium" if compliance < 70 else "")

        html += f"""
        <div class="article-card">
            <div class="article-title">📄 {r['filename']}</div>
            <div style="color: #7f8c8d; margin-bottom: 10px;">
                <strong>Тип:</strong> {r.get('detected_study_type', 'N/A')} |
                <strong>Чек-лист:</strong> {r.get('checklist_name', 'N/A')}
            </div>

            <div class="progress-bar">
                <div class="progress-fill {progress_class}" style="width: {compliance}%;">
                    {compliance:.1f}%
                </div>
            </div>

            <div class="stats">
                <div class="stat-box">
                    <div class="stat-value">{r['total_items']}</div>
                    <div class="stat-label">Всего пунктов</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value" style="color: #4CAF50;">{r['items_found']}</div>
                    <div class="stat-label">Найдено ✓</div>
                </div>
                <div class="stat-box">
                    <div class="stat-value" style="color: #F44336;">{r['items_not_found']}</div>
                    <div class="stat-label">Не найдено ✗</div>
                </div>
            </div>
        </div>
"""

    # Сводная таблица
    html += """
        <h2>Сравнительная таблица</h2>
        <table>
            <tr>
                <th>Статья</th>
                <th>Тип исследования</th>
                <th>Чек-лист</th>
                <th>Соответствие</th>
                <th>Уверенность</th>
            </tr>
"""

    for r in results:
        html += f"""
            <tr>
                <td>{r['filename']}</td>
                <td>{r.get('detected_study_type', 'N/A')}</td>
                <td>{r.get('checklist_name', 'N/A')}</td>
                <td><strong>{r['compliance_percentage']:.1f}%</strong></td>
                <td>{r.get('detection_confidence', 0):.0f}%</td>
            </tr>
"""

    html += """
        </table>

        <div style="margin-top: 30px; padding: 15px; background: #e3f2fd; border-radius: 5px; border-left: 4px solid #2196F3;">
            <strong>💡 Примечание:</strong> Этот дашборд автоматически сгенерирован из JSON файлов.
            JSON формат позволяет легко создавать интерактивные визуализации и дашборды!
        </div>
    </div>
</body>
</html>
"""

    with open('dashboard.html', 'w', encoding='utf-8') as f:
        f.write(html)

    print("✅ HTML дашборд создан: dashboard.html")

def main():
    results = load_results()

    if not results:
        print("❌ Нет данных для визуализации")
        return

    print(f"\n📁 Загружено {len(results)} результатов из JSON файлов\n")

    # ASCII визуализации
    visualize_compliance(results)
    visualize_sections(results)
    create_comparison_table(results)

    # HTML дашборд
    create_html_dashboard(results)

    print("\n" + "="*80)
    print("💡 ВСЕ ЭТО ВОЗМОЖНО БЛАГОДАРЯ JSON!")
    print("="*80)
    print("\nПреимущества JSON:")
    print("  ✓ Структурированные данные легко обрабатывать программно")
    print("  ✓ Можно создавать визуализации, графики, дашборды")
    print("  ✓ Легко экспортировать в CSV, HTML, Excel")
    print("  ✓ Возможность агрегировать данные из нескольких источников")
    print("  ✓ Удобно для автоматизации и CI/CD")
    print()

if __name__ == "__main__":
    main()
