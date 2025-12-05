#!/usr/bin/env python3
"""
Демонстрация преимуществ JSON: сравнительный анализ статей
"""
import json
from pathlib import Path
from typing import List, Dict

def load_all_results() -> List[Dict]:
    """Загрузить все JSON результаты"""
    results = []
    reports_dir = Path("reports")

    for json_file in reports_dir.rglob("*_detailed_results.json"):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data['filename'] = json_file.stem
            results.append(data)

    return results

def compare_articles(results: List[Dict]):
    """Сравнительный анализ статей"""
    print("╔════════════════════════════════════════════════════════════════╗")
    print("║         СРАВНИТЕЛЬНЫЙ АНАЛИЗ СТАТЕЙ (из JSON)                 ║")
    print("╚════════════════════════════════════════════════════════════════╝\n")

    # Таблица сравнения
    print(f"{'Статья':<40} {'Тип':<15} {'Чек-лист':<12} {'Соответствие':<12}")
    print("─" * 85)

    for r in results:
        name = r['filename'][:38] + ".." if len(r['filename']) > 40 else r['filename']
        study_type = r.get('detected_study_type', 'N/A')[:13]
        checklist = r.get('checklist_name', 'N/A')
        compliance = f"{r.get('compliance_percentage', 0):.1f}%"

        # Цветовой индикатор (для терминалов с поддержкой ANSI)
        if r.get('compliance_percentage', 0) >= 70:
            indicator = "🟢"
        elif r.get('compliance_percentage', 0) >= 50:
            indicator = "🟡"
        else:
            indicator = "🔴"

        print(f"{name:<40} {study_type:<15} {checklist:<12} {compliance:<8} {indicator}")

    print("\n" + "=" * 85 + "\n")

    # Статистика
    print("📊 АГРЕГИРОВАННАЯ СТАТИСТИКА:\n")

    avg_compliance = sum(r['compliance_percentage'] for r in results) / len(results)
    print(f"   • Средняя степень соответствия: {avg_compliance:.1f}%")

    total_items = sum(r['total_items'] for r in results)
    total_found = sum(r['items_found'] for r in results)
    print(f"   • Всего проверено пунктов: {total_items}")
    print(f"   • Найдено: {total_found} ({total_found/total_items*100:.1f}%)")

    # Наиболее частые проблемы
    print("\n🔍 ЧАСТО ОТСУТСТВУЮЩИЕ ЭЛЕМЕНТЫ:\n")

    missing_items = {}
    for r in results:
        for item in r.get('items', []):
            if not item['found']:
                key = item['description']
                missing_items[key] = missing_items.get(key, 0) + 1

    # Топ-5 проблем
    top_missing = sorted(missing_items.items(), key=lambda x: x[1], reverse=True)[:5]
    for i, (desc, count) in enumerate(top_missing, 1):
        desc_short = desc[:70] + "..." if len(desc) > 70 else desc
        print(f"   {i}. {desc_short}")
        print(f"      Отсутствует в {count}/{len(results)} статьях")
        print()

def export_to_csv(results: List[Dict], output_file: str = "comparison.csv"):
    """Экспорт в CSV для Excel"""
    import csv

    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Файл', 'Тип исследования', 'Чек-лист',
            'Всего пунктов', 'Найдено', 'Не найдено',
            'Соответствие %', 'Уверенность детекции %'
        ])

        for r in results:
            writer.writerow([
                r.get('filename', ''),
                r.get('detected_study_type', ''),
                r.get('checklist_name', ''),
                r.get('total_items', 0),
                r.get('items_found', 0),
                r.get('items_not_found', 0),
                round(r.get('compliance_percentage', 0), 2),
                round(r.get('detection_confidence', 0), 2)
            ])

    print(f"✅ Экспортировано в {output_file}")

def main():
    results = load_all_results()

    if not results:
        print("❌ Не найдено JSON файлов с результатами")
        return

    print(f"\n📁 Найдено {len(results)} результатов анализа\n")

    # Сравнительный анализ
    compare_articles(results)

    # Экспорт в CSV
    export_to_csv(results)
    print(f"\n💡 Это возможно благодаря структурированному формату JSON!")

if __name__ == "__main__":
    main()
