import streamlit as st
import pandas as pd
import numpy as np
import time

st.set_page_config(layout="wide", page_title="PLC Автономия")

# Красивый заголовок
st.markdown("<h1 style='text-align: center;'>МОЖЕТ ЛИ PLC РАБОТАТЬ БЕЗ SCADA?</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; font-size: 1.2em; color: gray;'>Интерактивная архитектура процесса автоматизации</p>", unsafe_allow_html=True)

# Инициализация параметров бака
if "level" not in st.session_state:
    st.session_state.level = 62.3
if "pump" not in st.session_state:
    st.session_state.pump = "ON"

# Логика PLC (эмуляция работы контроллера на нижнем уровне)
if st.session_state.pump == "ON":
    st.session_state.level += np.random.uniform(-0.4, 0.8)
    if st.session_state.level > 80.0:
        st.session_state.pump = "OFF"
else:
    st.session_state.level -= np.random.uniform(0.3, 0.6)
    if st.session_state.level < 45.0:
        st.session_state.pump = "ON"

st.session_state.level = max(0.0, min(100.0, st.session_state.level))
pressure = st.session_state.level * 0.055

# --- ПАНЕЛЬ УПРАВЛЕНИЯ ЭКСПЕРИМЕНТОМ ---
st.write(" ")
col_tgl, col_hmi_btn = st.columns([1, 1])
with col_tgl:
    scada_online = st.toggle("🔌 Связь со SCADA-системой (Верхний уровень)", value=False)
with col_hmi_btn:
    if st.button("📱 Нажать кнопку пуска/стопа на физ. панели HMI"):
        st.session_state.pump = "OFF" if st.session_state.pump == "ON" else "ON"

st.write(" ")

# --- ОТРИСОВКА СХЕМЫ (ГРАФА) КАК НА КАРТИНКЕ ---

# Задаем цвета и стили в зависимости от тумблера
scada_node_color = "#1E293B" if scada_online else "#451a1a"
scada_text_color = "#2496ff" if scada_online else "#ef4444"
scada_label = f"🖥️ SCADA СИСТЕМА\\n(Верхний уровень)\\n\\n[СТАТУС: РАБОТА]\\nАрхив: Уровень={st.session_state.level:.1f}%" if scada_online else "❌ SCADA ОТКЛЮЧЕНА\\n(Диспетчер ослеп)\\n\\n[НЕТ СВЯЗИ]"
scada_edge_color = "#2496ff" if scada_online else "#ef4444"
scada_edge_style = "solid" if scada_online else "dashed"
scada_edge_label = "Данные телеметрии" if scada_online else "СВЯЗЬ РАЗОРВАНА (-X-)"

# Код графа на языке DOT (Graphviz)
dot_code = f"""
digraph G {{
    background="transparent";
    rankdir=LR;
    node [fontname="Arial", fontsize=12, shape=box, style="filled,rounded", color="#475569", fontcolor="white", penwidth=2];
    edge [fontname="Arial", fontsize=10, fontcolor="#94a3b8", penwidth=2.5];

    # Блок 1: Полевые устройства
    FIELD [label="🔹 ПОЛЕВЫЕ УСТРОЙСТВА\\n\\n📥 Датчик уровня: {st.session_state.level:.1f} %\\n📥 Датчик давления: {pressure:.1f} bar", fillcolor="#0f172a"];
    
    # Блок 2: Выходы (Исполнительные механизмы)
    ACTUATORS [label="⚙️ ВЫХОДЫ И ИСПОЛНИТЕЛИ\\n\\n📤 Насос Pump 1: {st.session_state.pump}\\n📤 Клапан Valve 1: OPEN", fillcolor="#0f172a"];

    # Блок 3: Контроллер PLC (Центральное звено)
    PLC [label="🧠 ЦЕНТРАЛЬНЫЙ PLC\\n(Siemens Simatic)\\n\\nЛогика: АКТИВНА\\nЦикл опроса: 10мс", fillcolor="#064e3b", color="#10b981", fontsize=14];

    # Блок 4: Локальный HMI
    HMI [label="📱 ЛОКАЛЬНЫЙ HMI\\n(Панель оператора у станка)\\n\\nЭкран Танка: {st.session_state.level:.1f} %\\nНасос: {st.session_state.pump}", fillcolor="#1e3a8a", color="#3b82f6"];

    # Блок 5: SCADA верхнего уровня
    SCADA [label="{scada_label}", fillcolor="{scada_node_color}", color="{scada_text_color}", fontcolor="{scada_text_color}"];

    # Связи и потоки данных (Стрелки)
    FIELD -> PLC [label="  Сигналы датчиков", color="#10b981"];
    PLC -> ACTUATORS [label="  Команды управления", color="#10b981", dir=forward];
    PLC -> HMI [label="  Интерфейс (Profinet)", color="#3b82f6", dir=both];
    
    # Динамическая стрелка к SCADA
    PLC -> SCADA [label="  {scada_edge_label}", color="{scada_edge_color}", style="{scada_edge_style}"];
}}
"""

# Отрендерить красивую интерактивную схему во всю ширину
st.graphviz_chart(dot_code, use_container_width=True)

st.divider()

# Стенд защиты аргументов
st.markdown("### 📊 Главный вывод для защиты работы перед комиссией:")
if not scada_online:
    st.error(
        "🔥 **Наглядное доказательство:** Обратите внимание на схему выше. Линия связи между PLC и SCADA разорвана, "
        "блок SCADA изолирован и окрашен в красный цвет. При этом левая (технологическая) часть схемы продолжает "
        "работать автономно: датчики передают данные в PLC, PLC управляет насосом, а оператор полностью контролирует "
        "ситуацию через локальный HMI экран. Процесс НЕ остановился!"
    )
else:
    st.info("💡 Отключите тумблер связи сверху, чтобы продемонстрировать автономность нижнего уровня автоматизации (PLC + HMI).")

# Автообновление для симуляции реального времени
time.sleep(1.0)
st.rerun()
