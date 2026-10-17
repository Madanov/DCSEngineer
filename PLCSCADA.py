import streamlit as st
import pandas as pd
import numpy as np
import time

# Настройка широкого экрана, чтобы блоки встали в ряд как на схеме
st.set_page_config(layout="wide", page_title="PLC Автономия")

# Заголовок в стиле вашей картинки
st.markdown("<h1 style='text-align: center; color: white;'>PLC МОЖЕТ РАБОТАТЬ <span style='color: #2496ff;'>БЕЗ SCADA</span></h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; font-size: 1.2em;'>Демонстрация независимости нижнего уровня автоматизации</p>", unsafe_allow_html=True)

st.divider()

# --- СИМУЛЯЦИЯ ДАННЫХ ВНУТРИ PLC ---
if "tank_level" not in st.session_state:
    st.session_state.tank_level = 62.3
if "pump_status" not in st.session_state:
    st.session_state.pump_status = "ON"

# Имитация живого процесса автоматики
if st.session_state.pump_status == "ON":
    st.session_state.tank_level += np.random.uniform(-0.5, 0.7)
    if st.session_state.tank_level > 85.0: # Логика защиты внутри PLC
        st.session_state.pump_status = "OFF"
else:
    st.session_state.tank_level -= np.random.uniform(0.2, 0.6)
    if st.session_state.tank_level < 40.0: # Логика включения внутри PLC
        st.session_state.pump_status = "ON"

# Ограничиваем рамки для красоты
st.session_state.tank_level = max(0.0, min(100.0, st.session_state.tank_level))


# --- ИНТЕРФЕЙС И МНЕМОСХЕМА ---

# Главный тумблер управления экспериментом
st.markdown("### 🎛️ Имитация аварии / Обрыва связи верхнего уровня:")
scada_online = st.toggle("Связь со SCADA-системой завода", value=True)

st.write(" ")
st.write(" ")

# Создаем 3 главные колонки как на изображении: [Поле] -> [PLC] -> [Мониторы]
col_field, col_plc, col_monitors = st.columns([1.2, 1.5, 1.8], gap="large")

# 1. ПОЛЕВЫЕ УСТРОЙСТВА
with col_field:
    st.subheader("🔹 Полевые устройства")
    st.caption("(Датчики и исполнительные механизмы)")
    
    with st.container(border=True):
        st.markdown("**📥 Входы (Датчики):**")
        st.metric("Датчик уровня (Tank Level)", f"{st.session_state.tank_level:.1f} %")
        st.metric("Датчик давления", f"{(st.session_state.tank_level * 0.055):.1f} bar")
        
        st.markdown("**📤 Выходы (Сигналы PLC):**")
        pump_color = "🟢" if st.session_state.pump_status == "ON" else "🔴"
        st.markdown(f"{pump_color} **Насос (Pump 1):** {st.session_state.pump_status}")
        st.markdown("🟢 **Клапан 1:** OPEN")

# 2. ЯДРО СИСТЕМЫ - PLC
with col_plc:
    st.subheader("🧠 Уровень PLC")
    st.caption("(Программируемый логический контроллер)")
    
    # Визуальный блок контроллера
    st.success("### [ 💻 SIMATIC PLC ]\n* Логика: **АКТИВНА**\n* Цикл опроса: **10 мс**\n* Защита оборудования: **ОК**")
    
    st.write(" ")
    # Стрелки-индикаторы направления данных
    st.markdown("⬅️ *Прием данных с датчиков (Входы)*")
    st.markdown("⬇️ *Выдача команд на клапаны/насосы (Выходы)*")
    st.markdown("➡️ *Передача данных на HMI панель оператора*")
    if scada_online:
        st.markdown("<p style='color: #00ff00;'>↗️ Передача данных в диспетчерскую (SCADA)</p>", unsafe_allow_html=True)
    else:
        st.markdown("<p style='color: #ff0000;'>❌ <s>↗️ Связь со SCADA заблокирована</s></p>", unsafe_allow_html=True)

# 3. ЭКРАНЫ УПРАВЛЕНИЯ (HMI и SCADA)
with col_monitors:
    
    # ВЕРХНИЙ БЛОК: SCADA
    st.markdown("### 🖥️ SCADA (необязательно)")
    if scada_online:
        with st.container(border=True):
            st.markdown("<p style='color: #00ff00; font-weight: bold;'>🟢 СЕРВЕР СВЯЗИ: РАБОТАЕТ</p>", unsafe_allow_html=True)
            st.caption("Отображение в диспетчерской завода:")
            st.text(f"Архив трендов: Уровень = {st.session_state.tank_level:.1f}%")
            st.text(f"Логирование событий: Насос {st.session_state.pump_status}")
    else:
        # Эффект зачеркивания как на картинке крестом
        st.markdown(
            "<div style='border: 2px solid red; background-color: #331111; padding: 15px; border-radius: 5px; text-align: center;'>"
            "<h2 style='color: red; margin: 0;'>❌ СВЯЗЬ ОБОРВАНА</h2>"
            "<p style='color: gray; margin: 5px 0 0 0;'>SCADA ослепла. Данные на верхний уровень не идут.</p>"
            "</div>", 
            unsafe_allow_html=True
        )
        
    st.write(" ")
    st.write(" ")
    
    # НИЖНИЙ БЛОК: ЛОКАЛЬНЫЙ HMI (РАБОТАЕТ ВСЕГДА)
    st.markdown("### 📱 Локальный HMI (операторский интерфейс)")
    with st.container(border=True):
        st.markdown("<p style='color: #2496ff; font-weight: bold;'>⚡ ПАНЕЛЬ SIMATIC HMI (Активна напрямую от PLC)</p>", unsafe_allow_html=True)
        
        # Эмуляция экрана с вашей картинки
        col_hmi_1, col_hmi_2 = st.columns(2)
        with col_hmi_1:
            st.write("**Tank 1**")
            st.write(f"Level: {st.session_state.tank_level:.1f} %")
            st.write(f"Pressure: {(st.session_state.tank_level * 0.055):.1f} bar")
        with col_hmi_2:
            st.write(f"Pump 1: **{st.session_state.pump_status}**")
            st.write("Valve 1: **OPEN**")
            
        # Интерактивная кнопка прямо на "панели оператора"
        if st.button("Переключить Насос вручную с HMI", use_container_width=True):
            if st.session_state.pump_status == "ON":
                st.session_state.pump_status = "OFF"
            else:
                st.session_state.pump_status = "ON"

st.divider()

# Динамический текстовый вывод-вывод для защиты проекта
if not scada_online:
    st.success(
        "💡 **ЧТО МЫ ВИДИМ НА СХЕМЕ:** Связь со SCADA полностью прервана (перечеркнута красным). "
        "Несмотря на это, **PLC** продолжает получать сигналы с датчиков слева, выполняет внутренние алгоритмы безопасности "
        "и мгновенно передает актуальную графику на **Локальный HMI**. "
        "Система функционирует без потери работоспособности!"
    )
else:
    st.info("ℹ️ Попробуйте выключить тумблер связи со SCADA наверху экрана, чтобы симулировать обрыв линии связи верхнего уровня.")

# Перезапуск для анимации
time.sleep(1.0)
st.rerun()
