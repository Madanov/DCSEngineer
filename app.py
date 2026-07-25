import numpy as np
import streamlit as st

st.markdown("# SCADA-симулятор: Управление уровнем в баке (ПИД)")

# Боковая панель с настройками регулятора и возмущений
st.sidebar.header("Настройки контура")
setpoint = st.sidebar.slider(
    "Уставка уровня (Setpoint, %)", 0.0, 100.0, 50.0, 1.0
)
disturbance = st.sidebar.slider(
    "Внешний слив (Возмущение)", 0.05, 0.5, 0.1, 0.01
)

st.sidebar.subheader("Коэффициенты ПИД")
Kp = st.sidebar.slider("Kp (Пропорциональный)", 0.0, 5.0, 1.2, 0.1)
Ki = st.sidebar.slider("Ki (Интегральный)", 0.0, 2.0, 0.2, 0.05)
Kd = st.sidebar.slider("Kd (Дифференциальный)", 0.0, 2.0, 0.1, 0.05)

# Моделирование процесса во времени (100 шагов)
steps = 100
time = np.linspace(0, 50, steps)

level = 20.0  # Начальный уровень воды в баке (%)
integral = 0.0
prev_error = 0.0

levels_history = []
setpoints_history = []
outputs_history = []

for t in time:
    error = setpoint - level
    integral += error * 0.5
    derivative = (error - prev_error) / 0.5

    # Выход ПИД-регулятора (мощность насоса 0-100%)
    output = Kp * error + Ki * integral + Kd * derivative
    output = np.clip(output, 0.0, 100.0)  # Ограничение насоса

    # Физика процесса: приток от насоса минус слив
    inflow = output * 0.8
    outflow = level * disturbance
    level += (inflow - outflow) * 0.2
    level = np.clip(level, 0.0, 100.0)

    levels_history.append(level)
    setpoints_history.append(setpoint)
    outputs_history.append(output)
    prev_error = error

# Визуализация "мнемосхемы" на экране
col1, col2 = st.columns(2)
with col1:
    st.metric(
        label="Текущий уровень (PV)",
        value=f"{levels_history[-1]:.1f} %",
        delta=f"{levels_history[-1] - setpoint:.1f} от уставки",
    )
with col2:
    st.metric(
        label="Мощность насоса (CV)", value=f"{outputs_history[-1]:.1f} %"
    )

# Прогресс-бар как визуализация заполнения бака
st.progress(int(levels_history[-1]), text="Заполнение бака водой")

# График тренда (как в реальной SCADA)
chart_data = {
    "Время": time,
    "Уставка (SP)": setpoints_history,
    "Уровень (PV)": levels_history,
}
st.line_chart(chart_data, x="Время", color=["#2ca02c", "#1f77b4"])
