import time
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# =========================================================
#  Эмулятор узла: Бак + Насос + ПИД по уровню
#  Датчики: уровень (PV/SP/OV), давление, расход, скорость насоса
#  + Динамическая мнемосхема (SVG), как на SCADA
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
        st.session_state.flow = 0.0
        st.session_state.pressure = 0.0
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

    if mode == "AUTO":
        ov, _ = pid.compute(ss.level, setpoint, dt)
        ss.pid_integral = pid.integral
        ss.pid_prev_error = pid.prev_error
    else:
        ov = manual_ov
    if not pump_on:
        ov = 0.0
    ss.ov = ov

    # фактическая скорость насоса (апериодическое звено 1-го порядка)
    ss.pump_speed += (ov - ss.pump_speed) / max(tau_pump, 1e-3) * dt
    ss.pump_speed = float(np.clip(ss.pump_speed, 0.0, 100.0))

    # расход насоса от фактической скорости, м3/ч
    q_out = (ss.pump_speed / 100.0) * q_pump_max if ss.level > 0 else 0.0
    ss.flow = q_out

    # материальный баланс (м3/ч -> м3/с)
    dh = ((q_in - q_out) / 3600.0) / tank_area * dt
    ss.level = float(np.clip(ss.level + dh, 0.0, tank_height))

    # давление на подаче: напор насоса + статический столб
    static_head = RHO * G * ss.level / 1e5
    ss.pressure = (ss.pump_speed / 100.0) ** 2 * p_max + static_head if pump_on else static_head

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


# ----------------- Мнемосхема (SVG, как на SCADA) -----------------
def alarm_state(value, lo, hi):
    if value >= hi:
        return "HH", "#e74c3c"
    if value <= lo:
        return "LL", "#3498db"
    return "OK", "#2ecc71"


def build_mimic_svg(ss):
    """Возвращает динамический SVG-мнемокадр узла Бак-Насос."""
    # --- уровень жидкости в баке ---
    tank_x, tank_y, tank_w, tank_h = 60, 60, 200, 300
    fill_frac = min(ss.level / tank_height, 1.0)
    fill_h = tank_h * fill_frac
    fill_y = tank_y + (tank_h - fill_h)

    lvl_st, lvl_col = alarm_state(ss.level, lvl_lo, lvl_hi)
    liquid_col = {"HH": "#e74c3c", "LL": "#5dade2", "OK": "#2e86de"}[lvl_st]

    prs_st, prs_col = alarm_state(ss.pressure, prs_lo, prs_hi)
    flw_st, flw_col = alarm_state(ss.flow, flw_lo, flw_hi)

    # --- насос ---
    pump_running = pump_on and ss.pump_speed > 0.5
    pump_col = "#27ae60" if pump_running else "#7f8c8d"
    # скорость анимации ротора зависит от скорости насоса
    rot_dur = max(0.2, 3.0 - (ss.pump_speed / 100.0) * 2.8) if pump_running else 0
    rotor_anim = (f'<animateTransform attributeName="transform" type="rotate" '
                  f'from="0 620 250" to="360 620 250" dur="{rot_dur}s" '
                  f'repeatCount="indefinite"/>') if pump_running else ""

    # --- поток в трубе (бегущие штрихи) ---
    flow_active = ss.flow > 0.1
    flow_col = flw_col if flow_active else "#95a5a6"
    flow_dash_anim = ('<animate attributeName="stroke-dashoffset" from="40" to="0" '
                      'dur="0.7s" repeatCount="indefinite"/>') if flow_active else ""

    # уровни уставки и алармов на баке (линии)
    def y_of_level(v):
        return tank_y + tank_h - tank_h * min(max(v / tank_height, 0), 1)

    sp_y = y_of_level(setpoint)
    hh_y = y_of_level(lvl_hi)
    ll_y = y_of_level(lvl_lo)

    def tag(cx, cy, label, value, unit, color, state):
        blink = ('<animate attributeName="opacity" values="1;0.25;1" dur="0.8s" '
                 'repeatCount="indefinite"/>') if state != "OK" else ""
        return f'''
        <g>
          <rect x="{cx-45}" y="{cy-16}" width="90" height="46" rx="6"
                fill="#1c2833" stroke="{color}" stroke-width="2">{blink}</rect>
          <text x="{cx}" y="{cy}" fill="#f4d03f" font-size="13"
                font-weight="bold" text-anchor="middle">{label}</text>
          <text x="{cx}" y="{cy+18}" fill="{color}" font-size="14"
                font-weight="bold" text-anchor="middle">{value:.1f} {unit}</text>
        </g>'''

    svg = f'''
    <svg viewBox="0 0 820 430" width="100%" style="background:#0e1621;border-radius:10px;">
      <!-- Заголовок -->
      <text x="20" y="28" fill="#aeb6bf" font-size="15" font-weight="bold">
        МНЕМОСХЕМА: T-101 → P-101</text>

      <!-- ===== БАК ===== -->
      <rect x="{tank_x}" y="{tank_y}" width="{tank_w}" height="{tank_h}"
            fill="#141d29" stroke="#5d6d7e" stroke-width="3" rx="8"/>
      <!-- жидкость -->
      <rect x="{tank_x+3}" y="{fill_y}" width="{tank_w-6}" height="{fill_h}"
            fill="{liquid_col}" opacity="0.85" rx="4">
        <animate attributeName="height" values="{fill_h};{fill_h}" dur="0.3s"/>
      </rect>
      <!-- линия уставки SP -->
      <line x1="{tank_x}" y1="{sp_y}" x2="{tank_x+tank_w}" y2="{sp_y}"
            stroke="#f1c40f" stroke-width="2" stroke-dasharray="8 4"/>
      <text x="{tank_x+tank_w+6}" y="{sp_y+4}" fill="#f1c40f" font-size="11">SP</text>
      <!-- линии HH / LL -->
      <line x1="{tank_x}" y1="{hh_y}" x2="{tank_x+tank_w}" y2="{hh_y}"
            stroke="#e74c3c" stroke-width="1.5" stroke-dasharray="4 3"/>
      <text x="{tank_x+tank_w+6}" y="{hh_y+4}" fill="#e74c3c" font-size="11">HH</text>
      <line x1="{tank_x}" y1="{ll_y}" x2="{tank_x+tank_w}" y2="{ll_y}"
            stroke="#3498db" stroke-width="1.5" stroke-dasharray="4 3"/>
      <text x="{tank_x+tank_w+6}" y="{ll_y+4}" fill="#3498db" font-size="11">LL</text>
      <text x="{tank_x+tank_w/2}" y="{tank_y-8}" fill="#aeb6bf" font-size="13"
            text-anchor="middle" font-weight="bold">БАК T-101</text>

      <!-- Датчик уровня LT (слева) -->
      <line x1="{tank_x}" y1="{fill_y}" x2="{tank_x-30}" y2="{fill_y}"
            stroke="#f4d03f" stroke-width="2"/>
      <circle cx="{tank_x-30}" cy="{fill_y}" r="6" fill="#f4d03f"/>

      <!-- ===== ТРУБА: дно бака -> расходомер -> насос ===== -->
      <!-- вертикальный участок вниз -->
      <line x1="{tank_x+tank_w/2}" y1="{tank_y+tank_h}" x2="{tank_x+tank_w/2}" y2="400"
            stroke="#566573" stroke-width="10"/>
      <!-- горизонтальный участок к насосу -->
      <line x1="{tank_x+tank_w/2}" y1="400" x2="620" y2="400"
            stroke="#566573" stroke-width="10"/>
      <!-- бегущий поток -->
      <line x1="{tank_x+tank_w/2}" y1="400" x2="620" y2="400"
            stroke="{flow_col}" stroke-width="5" stroke-dasharray="14 26">
        {flow_dash_anim}
      </line>

      <!-- Расходомер FT (на горизонтальной трубе) -->
      <rect x="400" y="385" width="30" height="30" fill="#1c2833"
            stroke="{flw_col}" stroke-width="2" rx="4"/>
      <text x="415" y="405" fill="#f4d03f" font-size="12"
            font-weight="bold" text-anchor="middle">FT</text>

      <!-- ===== НАСОС P-101 ===== -->
      <line x1="620" y1="400" x2="620" y2="280" stroke="#566573" stroke-width="10"/>
      <circle cx="620" cy="250" r="34" fill="{pump_col}"
              stroke="#ecf0f1" stroke-width="3"/>
      <g>
        <polygon points="620,225 630,250 620,275 610,250" fill="#ecf0f1"/>
        <polygon points="595,250 620,240 645,250 620,260" fill="#ecf0f1"/>
        {rotor_anim}
      </g>
      <text x="620" y="305" fill="#aeb6bf" font-size="13"
            text-anchor="middle" font-weight="bold">НАСОС P-101</text>
      <text x="620" y="322" fill="{pump_col}" font-size="12"
            text-anchor="middle" font-weight="bold">
        {"РАБОТА" if pump_running else "СТОП"} • {ss.pump_speed:.0f}%</text>

      <!-- Труба нагнетания (вверх от насоса) + датчик давления -->
      <line x1="620" y1="216" x2="620" y2="150" stroke="#566573" stroke-width="10"/>
      <line x1="620" y1="150" x2="760" y2="150" stroke="#566573" stroke-width="10"/>
      <polygon points="760,140 785,150 760,160" fill="#566573"/>

      <!-- Датчик давления PT (на нагнетании) -->
      <line x1="655" y1="150" x2="655" y2="120" stroke="{prs_col}" stroke-width="2"/>
      <circle cx="655" cy="115" r="6" fill="{prs_col}"/>

      <!-- ===== БИРКИ ДАТЧИКОВ ===== -->
      {tag(tank_x-30, 40, "LT-101", ss.level, "м", lvl_col, lvl_st)}
      {tag(655, 70, "PT-101", ss.pressure, "бар", prs_col, prs_st)}
      {tag(415, 340, "FT-101", ss.flow, "м³/ч", flw_col, flw_st)}
    </svg>
    '''
    return svg


# ----------------- Отрисовка -----------------
st.title("🏭 ПИД-контур регулирования уровня: Бак → Насос")

ss = st.session_state


def alarm_badge(value, lo, hi):
    if value >= hi:
        return "🔴 HH"
    if value <= lo:
        return "🔵 LL"
    return "🟢 OK"


c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Уровень PV, м", f"{ss.level:.2f}", alarm_badge(ss.level, lvl_lo, lvl_hi))
c2.metric("Выход ПИД OUT, %", f"{ss.ov:.1f}", "🟢 ВКЛ" if pump_on else "⚪ ВЫКЛ")
c3.metric("Скорость насоса, %", f"{ss.pump_speed:.1f}")
c4.metric("Давление, бар", f"{ss.pressure:.2f}", alarm_badge(ss.pressure, prs_lo, prs_hi))
c5.metric("Расход, м³/ч", f"{ss.flow:.1f}", alarm_badge(ss.flow, flw_lo, flw_hi))

st.divider()

# ================= ДИНАМИЧЕСКАЯ МНЕМОСХЕМА =================
st.subheader("🖥️ Мнемосхема процесса (SCADA)")
components.html(build_mimic_svg(ss), height=450)

st.divider()

# ========== ЕДИНЫЙ ТРЕНД ПИД С ВЫБОРОМ ПАРАМЕТРОВ ==========
st.subheader("📈 Тренд работы ПИД-регулятора")

pid_signals = {
    "PV (уровень), м":     "PV — уровень (process value)",
    "SP (уставка), м":     "SP — уставка (setpoint)",
    "OUT (выход ПИД), %":  "OUT — выход ПИД на насос",
    "Скорость насоса, %":  "Скорость насоса (факт.)",
}

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
