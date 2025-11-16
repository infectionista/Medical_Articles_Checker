#!/usr/bin/env python3
"""
Визуализация результатов анализа из JSON
"""
import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Для работы без GUI

def create_visualizations():
    """Создать визуализации на основе JSON данных"""

    # Загрузка данных
    results = []
    for json_file in Path("reports").rglob("*_detailed_results.json"):
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            data['filename'] = json_file.parent.name  # Название папки
            results.append(data)

    if not results:
        print("❌ Нет данных для визуализации")
        return

    # Создаем фигуру с несколькими графиками
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Анализ качества научных статей', fontsize=16, fontweight='bold')

    # График 1: Круговая диаграмма соответствия
    ax1 = axes[0, 0]
    names = [r['filename'] for r in results]
    compliances = [r['compliance_percentage'] for r in results]

    colors = ['#4CAF50' if c >= 70 else '#FFC107' if c >= 50 else '#F44336' for c in compliances]
    ax1.bar(range(len(names)), compliances, color=colors, alpha=0.7, edgecolor='black')
    ax1.set_ylabel('Соответствие (%)', fontsize=10)
    ax1.set_title('Степень соответствия чек-листу', fontsize=12, fontweight='bold')
    ax1.set_xticks(range(len(names)))
    ax1.set_xticklabels(names, rotation=45, ha='right', fontsize=8)
    ax1.axhline(y=70, color='green', linestyle='--', alpha=0.5, label='Отлично (70%)')
    ax1.axhline(y=50, color='orange', linestyle='--', alpha=0.5, label='Удовл. (50%)')
    ax1.legend(fontsize=8)
    ax1.grid(axis='y', alpha=0.3)

    # График 2: Найдено vs не найдено (stacked bar)
    ax2 = axes[0, 1]
    found = [r['items_found'] for r in results]
    not_found = [r['items_not_found'] for r in results]

    x = range(len(names))
    ax2.bar(x, found, label='Найдено', color='#4CAF50', alpha=0.7)
    ax2.bar(x, not_found, bottom=found, label='Не найдено', color='#F44336', alpha=0.7)
    ax2.set_ylabel('Количество пунктов', fontsize=10)
    ax2.set_title('Распределение пунктов чек-листа', fontsize=12, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels(names, rotation=45, ha='right', fontsize=8)
    ax2.legend(fontsize=9)
    ax2.grid(axis='y', alpha=0.3)

    # График 3: Pie chart для первой статьи
    ax3 = axes[1, 0]
    if results:
        r = results[0]
        sections = {}
        for item in r['items']:
            section = item['section']
            sections[section] = sections.get(section, 0) + (1 if item['found'] else 0)

        if sections:
            ax3.pie(sections.values(), labels=sections.keys(), autopct='%1.1f%%',
                   startangle=90, textprops={'fontsize': 7})
            ax3.set_title(f'Соответствие по секциям\n({r["filename"]})',
                         fontsize=11, fontweight='bold')

    # График 4: Сводная таблица
    ax4 = axes[1, 1]
    ax4.axis('off')

    table_data = [['Статья', 'Тип', 'Чек-лист', 'Соотв.']]
    for r in results:
        table_data.append([
            r['filename'][:20],
            r.get('detected_study_type', 'N/A')[:15],
            r.get('checklist_name', 'N/A'),
            f"{r['compliance_percentage']:.1f}%"
        ])

    table = ax4.table(cellText=table_data, cellLoc='left',
                     loc='center', colWidths=[0.35, 0.25, 0.2, 0.15])
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 2)

    # Стилизация шапки таблицы
    for i in range(4):
        table[(0, i)].set_facecolor('#4CAF50')
        table[(0, i)].set_text_props(weight='bold', color='white')

    ax4.set_title('Сводная таблица', fontsize=12, fontweight='bold', pad=20)

    plt.tight_layout()
    output_file = 'analysis_dashboard.png'
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    print(f"✅ Визуализация сохранена: {output_file}")

    return output_file

if __name__ == "__main__":
    print("\n📊 Создание визуализации из JSON данных...\n")
    create_visualizations()
    print("\n💡 JSON позволяет легко создавать графики и дашборды!")
