import time
import numpy as np
import pandas as pd
import streamlit as st

# =========================================================
#  Эмулятор узла: Бак + Насос + ПИД по уровню
#  Датчики: уровень (PV/SP/OV), давление, расход, скорость насоса
# =========================================================

st.set_page_config(page_title="ПИД-контур: Бак-Насос", layout="wide")

G = 9.81            # ускорение свободного падения, м/с^2
RHO = 1000.0        # плотность жидкости (вода), кг/м^3

# ----------------- ПИД-регулятор -----------------
class PID:
    def __init__(self, kp, ki, kd, out_min=0.0, out_max=100.0):
        self.kp, self.ki, self.kd = kp, ki, kd
        self.out_min, self.out_max = out_min, out_max
        self.integral = 0.0
        self.prev_error = 0.0

    def compute(self, pv, sp, dt):
        error = pv - sp          # direct-acting: уровень выше уставки -> больше откачки
        p = self.kp * error
        self.integral += error * dt
        i = self.ki * self.integral
        d = self.kd * (error - self.prev_error) / dt if dt > 0 else 0.0
        self.prev_error = error
        out = p + i + d
        # clamp + back-calculation anti-windup
        if out > self.out_max:
            out = self.out_max
            if self.ki != 0:
                self.integral = (self.out_max - p - d) / self.ki
        elif out < self.out_min:
            out = self.out_min
            if self.ki != 0:
                self.integral = (self.out_min - p - d) / self.ki
        return out, error


# ----------------- Инициализация состояния -----------------
def init_state():
    ss = st.session_state
    ss.setdefault("level", 5.0)         # уровень, м
    ss.setdefault("ov", 0.0)            # выход ПИД (команда на насос), %
    ss.setdefault("pump_speed", 0.0)    # фактическая скорость насоса, %
    ss.setdefault("flow", 0.0)          # расход, м3/ч
    ss.setdefault("pressure", 0.0)      # давление на подаче, бар
    ss.setdefault("history", [])        # тренды
    ss.setdefault("running", False)
    ss.setdefault("t", 0.0)
    ss.setdefault("pid_integral", 0.0)
    ss.setdefault("pid_prev_error", 0.0)

init_state()

# ----------------- Сайдбар: настройки -----------------
st.sidebar.title("⚙️ Управление")

with st.sidebar.expander("▶️ Симуляция", expanded=True):
    dt = st.number_input("Шаг интегрирования dt, с", 0.05, 2.0, 0.5, 0.05)
    sim_speed = st.slider("Ускорение времени (x)", 1, 20, 5)
    col_r1, col_r2 = st.columns(2)
    if col_r1.button("▶️ Старт / ⏸ Пауза", use_container_width=True):
        st.session_state.running = not st.session_state.running
    if col_r2.button("🔄 Сброс", use_container_width=True):
        st.session_state.level = 5.0
        st.session_state.ov = 0.0
        st.session_state.pump_speed = 0.0
        st.session_state.history = []
        st.session_state.t = 0.0
        st.session_state.pid_integral = 0.0
        st.session_state.pid_prev_error = 0.0
        st.session_state.running = False

with st.sidebar.expander("🛢️ Параметры бака", expanded=False):
    tank_area = st.number_input("Площадь сечения A, м²", 0.5, 100.0, 10.0, 0.5)
    tank_height = st.number_input("Высота бака H_max, м", 1.0, 50.0, 10.0, 0.5)

with st.sidebar.expander("💧 Приток (имитация заполнения)", expanded=True):
    q_in = st.slider("Приток Qin, м³/ч", 0.0, 200.0, 40.0, 1.0)
    q_pump_max = st.slider("Макс. производительность насоса, м³/ч", 10.0, 400.0, 120.0, 5.0)

with st.sidebar.expander("🎛️ ПИД-регулятор", expanded=True):
    mode = st.radio("Режим", ["AUTO", "MANUAL"], horizontal=True)
    setpoint = st.slider("Уставка уровня SP, м", 0.0, float(tank_height), 5.0, 0.1)
    kp = st.number_input("Kp", 0.0, 500.0, 20.0, 0.5)
    ki = st.number_input("Ki", 0.0, 100.0, 2.0, 0.1)
    kd = st.number_input("Kd", 0.0, 100.0, 1.0, 0.1)
    manual_ov = st.slider("Ручной выход OV, %", 0.0, 100.0, 0.0, 1.0)
    pump_on = st.toggle("Насос ВКЛ", value=True)
    tau_pump = st.number_input("Постоянная времени насоса τ, с", 0.1, 60.0, 3.0, 0.1)

with st.sidebar.expander("🚨 Аларм-лимиты", expanded=False):
    st.caption("Уровень, м")
    lvl_hi = st.number_input("Level HH (высокий)", value=8.0, key="lvl_hi")
    lvl_lo = st.number_input("Level LL (низкий)", value=1.0, key="lvl_lo")
    st.caption("Давление, бар")
    prs_hi = st.number_input("Press HH", value=6.0, key="prs_hi")
    prs_lo = st.number_input("Press LL", value=0.5, key="prs_lo")
    st.caption("Расход, м³/ч")
    flw_hi = st.number_input("Flow HH", value=150.0, key="flw_hi")
    flw_lo = st.number_input("Flow LL", value=5.0, key="flw_lo")

p_max = 5.0  # напор насоса при 100% скорости (без статики), бар

# ----------------- Шаг симуляции -----------------
def simulate_step(dt):
    ss = st.session_state
    pid = PID(kp, ki, kd)
    pid.integral = ss.pid_integral
    pid.prev_error = ss.pid_prev_error

    # --- выход ПИД (команда OV) ---
    if mode == "AUTO":
        ov, _ = pid.compute(ss.level, setpoint, dt)
        ss.pid_integral = pid.integral
        ss.pid_prev_error = pid.prev_error
    else:
        ov = manual_ov
    if not pump_on:
        ov = 0.0
    ss.ov = ov

    # --- фактическая скорость насоса (апериодическое звено 1-го порядка) ---
    ss.pump_speed += (ov - ss.pump_speed) / max(tau_pump, 1e-3) * dt
    ss.pump_speed = float(np.clip(ss.pump_speed, 0.0, 100.0))

    # --- расход насоса от фактической скорости, м3/ч ---
    q_out = (ss.pump_speed / 100.0) * q_pump_max if ss.level > 0 else 0.0
    ss.flow = q_out

    # --- материальный баланс (м3/ч -> м3/с) ---
    dh = ((q_in - q_out) / 3600.0) / tank_area * dt
    ss.level = float(np.clip(ss.level + dh, 0.0, tank_height))

    # --- давление на подаче: напор насоса + статический столб ---
    static_head = RHO * G * ss.level / 1e5
    ss.pressure = (ss.pump_speed / 100.0) ** 2 * p_max + static_head if pump_on else static_head

    # --- время + история ---
    ss.t += dt
    ss.history.append({
        "t": round(ss.t, 1),
        "PV (уровень), м": ss.level,
        "SP (уставка), м": setpoint,
        "OUT (выход ПИД), %": ss.ov,
        "Скорость насоса, %": ss.pump_speed,
        "Расход, м³/ч": ss.flow,
        "Давление, бар": ss.pressure,
    })
    ss.history = ss.history[-600:]


if st.session_state.running:
    for _ in range(sim_speed):
        simulate_step(dt)

# ----------------- Отрисовка -----------------
st.title("🏭 ПИД-контур регулирования уровня: Бак → Насос")

def alarm_badge(value, lo, hi):
    if value >= hi:
        return "🔴 HH"
    if value <= lo:
        return "🔵 LL"
    return "🟢 OK"

ss = st.session_state
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Уровень PV, м", f"{ss.level:.2f}", alarm_badge(ss.level, lvl_lo, lvl_hi))
c2.metric("Выход ПИД OUT, %", f"{ss.ov:.1f}", "🟢 ВКЛ" if pump_on else "⚪ ВЫКЛ")
c3.metric("Скорость насоса, %", f"{ss.pump_speed:.1f}")
c4.metric("Давление, бар", f"{ss.pressure:.2f}", alarm_badge(ss.pressure, prs_lo, prs_hi))
c5.metric("Расход, м³/ч", f"{ss.flow:.1f}", alarm_badge(ss.flow, flw_lo, flw_hi))

st.progress(min(ss.level / tank_height, 1.0),
            text=f"Заполнение бака: {ss.level/tank_height*100:.0f}%")

st.divider()

# ========== ЕДИНЫЙ ТРЕНД ПИД С ВЫБОРОМ ПАРАМЕТРОВ ==========
st.subheader("📈 Тренд работы ПИД-регулятора")

pid_signals = {
    "PV (уровень), м":     "PV — уровень (process value)",
    "SP (уставка), м":     "SP — уставка (setpoint)",
    "OUT (выход ПИД), %":  "OUT — выход ПИД на насос",
    "Скорость насоса, %":  "Скорость насоса (факт.)",
}

# Чекбоксы для включения/выключения сигналов
st.caption("Выбери, какие параметры показывать на тренде:")
cols = st.columns(len(pid_signals))
selected = []
defaults = [True, True, True, True]
for (key, label), col, dflt in zip(pid_signals.items(), cols, defaults):
    if col.checkbox(label, value=dflt, key=f"chk_{key}"):
        selected.append(key)

if ss.history and selected:
    df = pd.DataFrame(ss.history).set_index("t")
    st.line_chart(df[selected], height=380)
elif not selected:
    st.warning("Выбери хотя бы один параметр для отображения.")
else:
    st.info("Нажми ▶️ Старт в сайдбаре, чтобы запустить симуляцию.")

st.divider()

# Дополнительные тренды процесса
if ss.history:
    df = pd.DataFrame(ss.history).set_index("t")
    colA, colB = st.columns(2)
    with colA:
        st.subheader("🌊 Расход, м³/ч")
        st.line_chart(df[["Расход, м³/ч"]])
    with colB:
        st.subheader("📊 Давление, бар")
        st.line_chart(df[["Давление, бар"]])

# Авто-обновление
if ss.running:
    time.sleep(dt)
    st.rerun()
