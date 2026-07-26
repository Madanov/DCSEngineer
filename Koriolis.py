"""
=============================================================================
  CORIOLIS MASS FLOW METER — INTERACTIVE ENGINEERING DIGITAL TWIN
=============================================================================
  Учебно-инженерный стенд принципа работы кориолисового расходомера
  (уровень Emerson Micro Motion / Endress+Hauser / Krohne).

  Стек:  Python 3.12+ · Streamlit · Plotly · NumPy · SciPy · Pandas
  Запуск: streamlit run app.py

  Физическая идея (демонстрационная модель, НЕ метрологический расчёт):
  --------------------------------------------------------------------------
  Трубка возбуждается на собственной частоте (drive mode) — симметричная
  форма колебаний shape_sym(s). При наличии массового расхода на элементы
  жидкости, движущиеся вдоль вибрирующей трубки, действует сила Кориолиса
  Fc = 2·m·(v × ω). Она возбуждает антисимметричную моду shape_anti(s),
  сдвинутую по фазе на 90° относительно drive-моды. Суперпозиция этих двух
  мод даёт «скручивание» (twist) трубки и фазовый сдвиг между датчиками A и B.

      deformation(s, t) = A · [ shape_sym(s)·sin(ωt)
                              + K·ṁ·shape_anti(s)·cos(ωt) ]

  Итог:  Δφ ∝ ṁ,   Δt = Δφ/ω ∝ ṁ,   TwistAngle ∝ Fc ∝ ṁ.
=============================================================================
"""

import time
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from scipy.interpolate import splprep, splev

# =============================================================================
#  ГЛОБАЛЬНЫЕ КОНСТАНТЫ И ЦВЕТОВАЯ СХЕМА
# =============================================================================
BG        = "#05070c"          # почти чёрный фон
PANEL     = "#0b111b"          # фон панелей/графиков
GRID      = "#1b2434"          # сетка
TUBE_CYAN = "#28c8ff"          # трубки — голубые
TUBE_GLOW = "rgba(40,200,255,0.18)"
CORIOLIS  = "#ff8c1a"          # сила Кориолиса — оранжевая
SENSOR    = "#39ff88"          # датчики — зелёные
WHITE     = "#e8eef5"
RED       = "#ff3b5c"          # текущая рабочая точка — красная
SENS_A_C  = "#39ff88"
SENS_B_C  = "#28c8ff"

# --- Геометрия U-трубки (безразмерные единицы) ---
W       = 1.0                  # полуширина U (расстояние легов от оси)
Y_TOP   = 2.2                  # высота верха легов
N_PTS   = 400                  # число точек дискретизации центральной линии
TUBE2_DX = 3.1                 # смещение второй (параллельной) трубки по X

# --- Динамика (демонстрационные, «удобные для глаза» значения) ---
OMEGA_VIS   = 2.0 * np.pi * 0.9   # видимая угловая частота вибрации, рад/с
FREQ_NOM_HZ = 80.0                # номинальная (паспортная) частота трубки, Гц
K_CORIOLIS  = 0.9                 # коэф. связи расход→антисимметричная мода

# Позиции датчиков вдоль дуги s∈[0,1] (экстремумы антисимметричной моды)
S_SENSOR_A = 0.25              # инлет-плечо  (+lobe у shape_anti)
S_SENSOR_B = 0.75              # аутлет-плечо (−lobe у shape_anti)

st.set_page_config(page_title="Coriolis Mass Flow Meter — Digital Twin",
                   layout="wide", page_icon="🌀")


# =============================================================================
#  1. ГЕОМЕТРИЯ ТРУБКИ  (spline через ключевые точки + равномерная дуга)
# =============================================================================
@st.cache_data(show_spinner=False)
def build_centerline():
    """
    Строит гладкую центральную линию U-трубки B-сплайном (scipy splprep),
    затем перепараметризует её по длине дуги, чтобы точки были равномерны
    (это нужно для равномерного движения частиц потока).

    Возвращает:
        s   : нормированная дуговая координата [0..1]           (N_PTS,)
        bx  : базовые X центральной линии                        (N_PTS,)
        by  : базовые Y центральной линии                        (N_PTS,)
        nx  : X-компонента единичной нормали к линии             (N_PTS,)
        ny  : Y-компонента единичной нормали к линии             (N_PTS,)
    """
    # --- ключевые точки U (инлет-лег → дно → аутлет-лег) ---
    theta = np.linspace(np.pi, 2.0 * np.pi, 22)           # полукруг снизу
    arc_x = W * np.cos(theta)
    arc_y = W * np.sin(theta)                              # уходит в −W (дно)

    left_y  = np.linspace(Y_TOP, 0.0, 14)                  # левый лег (вниз)
    right_y = np.linspace(0.0, Y_TOP, 14)                  # правый лег (вверх)

    # (стыки лег↔дуга совпадают по координатам — убираем дубли,
    #  иначе scipy.splprep выдаёт "Invalid inputs")
    kx = np.concatenate([np.full_like(left_y[:-1], -W), arc_x, np.full_like(right_y[1:], W)])
    ky = np.concatenate([left_y[:-1],                   arc_y, right_y[1:]])

    # --- гладкий сплайн через точки ---
    tck, _ = splprep([kx, ky], s=0.0, k=3)
    u_fine = np.linspace(0.0, 1.0, N_PTS * 3)
    fx, fy = splev(u_fine, tck)
    fx, fy = np.asarray(fx), np.asarray(fy)

    # --- перепараметризация по длине дуги (равномерные точки) ---
    seg = np.hypot(np.diff(fx), np.diff(fy))
    arclen = np.concatenate([[0.0], np.cumsum(seg)])
    arclen /= arclen[-1]
    s = np.linspace(0.0, 1.0, N_PTS)
    bx = np.interp(s, arclen, fx)
    by = np.interp(s, arclen, fy)

    # --- единичные нормали (перпендикуляр к касательной) ---
    tx = np.gradient(bx)
    ty = np.gradient(by)
    tnorm = np.hypot(tx, ty) + 1e-12
    tx, ty = tx / tnorm, ty / tnorm
    nx, ny = -ty, tx                                       # поворот касательной на 90°

    return s, bx, by, nx, ny


# --- Модальные формы (векторные, NumPy) ---
def shape_sym(s):
    """Симметричная drive-мода: максимум на дне U, нули на опорах."""
    return np.sin(np.pi * s)


def shape_anti(s):
    """Антисимметричная кориолисова мода: +lobe / −lobe, нуль в центре."""
    return np.sin(2.0 * np.pi * s)


# =============================================================================
#  2. РАСПРЕДЕЛЁННАЯ ДЕФОРМАЦИЯ  deformation(s, t, ṁ)
# =============================================================================
def calculate_deformation(bx, by, nx, ny, s, t, mdot_norm, amplitude,
                           omega=OMEGA_VIS, drive_sign=1.0):
    """
    Векторно вычисляет положение каждой точки трубки как суперпозицию
    drive-моды (sin) и антисимметричной кориолисовой моды (cos, +90°).

        w(s,t) = A·[ shape_sym(s)·sin(ωt) + K·ṁ·shape_anti(s)·cos(ωt) ]

    Смещение прикладывается ВДОЛЬ НОРМАЛИ к центральной линии — это даёт
    физичный распределённый изгиб (а не сдвиг всей трубки вверх-вниз).

    Параметры:
        mdot_norm  : нормированный расход [0..1]
        amplitude  : амплитуда вибрации A
        drive_sign : ±1 — для двух трубок, вибрирующих в противофазе

    Возвращает:
        X, Y     : координаты деформированной трубки       (N_PTS,)
        w        : величина смещения вдоль нормали          (N_PTS,)
        v        : мгновенная скорость точек dw/dt          (N_PTS,)
        c_local  : локальная интенсивность силы Кориолиса   (N_PTS,) [0..1]
    """
    sym  = shape_sym(s)
    anti = shape_anti(s)

    drive = drive_sign * amplitude * sym * np.sin(omega * t)
    cor   = drive_sign * amplitude * K_CORIOLIS * mdot_norm * anti * np.cos(omega * t)
    w = drive + cor

    # мгновенная скорость dw/dt (для визуализации/градиента)
    v = drive_sign * amplitude * omega * (
        sym * np.cos(omega * t) - K_CORIOLIS * mdot_norm * anti * np.sin(omega * t)
    )

    # локальная кориолисова интенсивность ∝ |v_drive · anti| · ṁ  → градиент вдоль трубки
    c_local = np.abs(anti) * mdot_norm

    X = bx + w * nx
    Y = by + w * ny
    return X, Y, w, v, c_local


# =============================================================================
#  3. ФАЗОВЫЙ СДВИГ, ЗАДЕРЖКА, УГОЛ СКРУЧИВАНИЯ, СИЛА КОРИОЛИСА
# =============================================================================
def calculate_phase_shift(mdot_norm, omega=OMEGA_VIS):
    """
    Демонстрационная модель ключевых выходных величин расходомера.
    Все зависимости линейны по массовому расходу (как в реальном приборе
    в рабочем диапазоне): Δφ ∝ ṁ,  Δt = Δφ/ω,  Twist ∝ Fc ∝ ṁ.

    Возвращает словарь метрик (в удобных инженерных единицах).
    """
    phase_deg   = 25.0 * mdot_norm                     # фазовый сдвиг, °
    phase_rad   = np.deg2rad(phase_deg)
    delta_t_us  = phase_rad / omega * 1e6              # задержка Δt, мкс
    twist_deg   = 12.0 * mdot_norm                     # угол скручивания, °
    coriolis_N  = 100.0 * mdot_norm                    # оценка силы Кориолиса, Н
    return {
        "mdot_pct":   mdot_norm * 100.0,
        "phase_deg":  phase_deg,
        "phase_rad":  phase_rad,
        "delta_t_us": delta_t_us,
        "twist_deg":  twist_deg,
        "coriolis_N": coriolis_N,
        "freq_hz":    FREQ_NOM_HZ,
    }


# =============================================================================
#  4. ЛЕВАЯ ЧАСТЬ — АНИМАЦИЯ РАСХОДОМЕРА (2D или 3D)
# =============================================================================
def _sensor_xy(bx, by, nx, ny, s, s_target, w_val):
    """Возвращает XY точки датчика на деформированной трубке при дуге s_target."""
    i = int(np.argmin(np.abs(s - s_target)))
    return bx[i] + w_val[i] * nx[i], by[i] + w_val[i] * ny[i], i


def draw_tubes(geom, t, mdot_norm, amplitude, mode_3d=False, show_trail=True):
    """
    Главная визуализация: две U-трубки, свечение, след (motion trail),
    частицы потока, стрелки силы Кориолиса, датчики A/B, градиент
    локальной силы Кориолиса вдоль трубки.
    """
    s, bx, by, nx, ny = geom
    fig = go.Figure()

    # --- обе трубки (drive_sign = +1 и −1: противофазная вибрация) ---
    tubes = []
    for dx, sign in [(0.0, +1.0), (TUBE2_DX, -1.0)]:
        X, Y, w, v, c_local = calculate_deformation(
            bx, by, nx, ny, s, t, mdot_norm, amplitude, drive_sign=sign)
        tubes.append((dx, sign, X + dx, Y, w, v, c_local))

    # ---------- MOTION TRAIL (след предыдущих положений) ----------
    if show_trail and not mode_3d:
        for k, alpha in [(3, 0.06), (2, 0.10), (1, 0.16)]:
            tt = t - k * 0.06
            for dx, sign in [(0.0, +1.0), (TUBE2_DX, -1.0)]:
                Xg, Yg, *_ = calculate_deformation(
                    bx, by, nx, ny, s, tt, mdot_norm, amplitude, drive_sign=sign)
                fig.add_trace(go.Scatter(
                    x=Xg + dx, y=Yg, mode="lines",
                    line=dict(color=f"rgba(40,200,255,{alpha})", width=6),
                    hoverinfo="skip", showlegend=False))

    # ---------- ТРУБКИ: свечение + основная линия + градиент Кориолиса ----------
    for dx, sign, X, Y, w, v, c_local in tubes:
        if not mode_3d:
            # 1) широкое полупрозрачное «свечение»
            fig.add_trace(go.Scatter(
                x=X, y=Y, mode="lines", hoverinfo="skip", showlegend=False,
                line=dict(color=TUBE_GLOW, width=22)))
            fig.add_trace(go.Scatter(
                x=X, y=Y, mode="lines", hoverinfo="skip", showlegend=False,
                line=dict(color=TUBE_GLOW, width=12)))
            # 2) основная голубая линия
            fig.add_trace(go.Scatter(
                x=X, y=Y, mode="lines", hoverinfo="skip", showlegend=False,
                line=dict(color=TUBE_CYAN, width=5)))
            # 3) градиент локальной силы Кориолиса (cyan→orange) поверх
            if mdot_norm > 0.02:
                fig.add_trace(go.Scatter(
                    x=X, y=Y, mode="markers", showlegend=False,
                    marker=dict(size=5, color=c_local, colorscale=[
                        [0.0, "rgba(40,200,255,0)"], [1.0, CORIOLIS]],
                        cmin=0, cmax=1),
                    hovertext=[f"v={vv:+.2f}" for vv in v],
                    hoverinfo="text"))

    # ---------- 3D-РЕЖИМ ----------
    if mode_3d:
        fig = go.Figure()
        for dx, sign in [(0.0, +1.0), (TUBE2_DX, -1.0)]:
            sym, anti = shape_sym(s), shape_anti(s)
            zdrive = sign * amplitude * sym * np.sin(OMEGA_VIS * t)
            zcor   = sign * amplitude * K_CORIOLIS * mdot_norm * anti * np.cos(OMEGA_VIS * t)
            Z = zdrive + zcor
            cl = np.abs(anti) * mdot_norm
            fig.add_trace(go.Scatter3d(
                x=bx + dx, y=by, z=Z, mode="lines",
                line=dict(color=cl, colorscale=[[0, TUBE_CYAN], [1, CORIOLIS]],
                          width=9, cmin=0, cmax=1),
                showlegend=False, hoverinfo="skip"))
        fig.update_layout(
            scene=dict(
                xaxis=dict(visible=False), yaxis=dict(visible=False),
                zaxis=dict(visible=False), bgcolor=BG,
                aspectmode="data",
                camera=dict(eye=dict(x=1.6, y=1.6, z=0.9))),
            paper_bgcolor=BG, margin=dict(l=0, r=0, t=10, b=0), height=620)
        return fig

    # ---------- ЧАСТИЦЫ ПОТОКА (движущиеся вдоль трубки) ----------
    flow_speed = 0.12 + 0.9 * mdot_norm
    base_p = (np.linspace(0, 1, 12) + flow_speed * t) % 1.0
    for dx, sign, X, Y, w, v, c_local in tubes:
        pidx = (base_p * (N_PTS - 1)).astype(int)
        fig.add_trace(go.Scatter(
            x=X[pidx], y=Y[pidx], mode="markers", showlegend=False,
            marker=dict(size=9, color="#bfefff", symbol="circle",
                        line=dict(color=TUBE_CYAN, width=1)),
            opacity=0.9, hoverinfo="skip"))

    # ---------- ДАТЧИКИ A/B + СТРЕЛКИ СИЛЫ КОРИОЛИСА ----------
    dx0, sign0, X0, Y0, w0, v0, c0 = tubes[0]
    ax_x, ay_y, iA = _sensor_xy(bx, by, nx, ny, s, S_SENSOR_A, w0)
    bx_x, by_y, iB = _sensor_xy(bx, by, nx, ny, s, S_SENSOR_B, w0)
    ax_x += dx0; bx_x += dx0

    # датчики (зелёные)
    fig.add_trace(go.Scatter(
        x=[ax_x, bx_x], y=[ay_y, by_y], mode="markers+text",
        marker=dict(size=16, color=SENSOR, symbol="square",
                    line=dict(color="#0a3", width=2)),
        text=["A", "B"], textposition="top center",
        textfont=dict(color=SENSOR, size=14), showlegend=False,
        hovertext=[f"Sensor A · pos={w0[iA]:+.3f}",
                   f"Sensor B · pos={w0[iB]:+.3f}"], hoverinfo="text"))

    # стрелки силы Кориолиса (оранжевые, длина ∝ ṁ, противоположно направлены)
    Lc = 0.15 + 0.9 * mdot_norm
    if mdot_norm > 0.01:
        for (sx, sy, ni, direction) in [
            (ax_x, ay_y, iA, +1.0), (bx_x, by_y, iB, -1.0)]:
            fig.add_annotation(
                x=sx + direction * nx[ni] * Lc, y=sy + direction * ny[ni] * Lc,
                ax=sx, ay=sy, xref="x", yref="y", axref="x", ayref="y",
                showarrow=True, arrowhead=3, arrowsize=1.6,
                arrowwidth=3, arrowcolor=CORIOLIS)

    # ---------- ПОДПИСИ / ОФОРМЛЕНИЕ ----------
    span = max(1e-6, mdot_norm)
    fig.add_annotation(x=-W, y=Y_TOP + 0.25, text="▼ FLOW IN", showarrow=False,
                       font=dict(color=SENSOR, size=12))
    fig.add_annotation(x=W, y=Y_TOP + 0.25, text="FLOW OUT ▲", showarrow=False,
                       font=dict(color=SENSOR, size=12))
    fig.add_annotation(x=TUBE2_DX, y=-W - 0.35, text="Dual-tube counter-vibration",
                       showarrow=False, font=dict(color="#5a6b82", size=11))

    fig.update_layout(
        paper_bgcolor=BG, plot_bgcolor=BG,
        xaxis=dict(visible=False, range=[-1.8, TUBE2_DX + 1.8],
                   scaleanchor="y", scaleratio=1),
        yaxis=dict(visible=False, range=[-1.9, Y_TOP + 0.7]),
        margin=dict(l=0, r=0, t=10, b=0), height=620, showlegend=False)
    return fig


# =============================================================================
#  5. ПРАВАЯ ЧАСТЬ — ОСЦИЛЛОГРАФ (Sensor A / Sensor B)
# =============================================================================
def draw_sensor_signals(t, metrics, omega=OMEGA_VIS):
    """
    Осциллограф двух датчиков. Сигналы — синусоиды одинаковой частоты,
    разнесённые по фазе на Δφ(ṁ). Текущие точки (t) отмечены.
        sA(τ) = sin(ωτ + Δφ/2),   sB(τ) = sin(ωτ − Δφ/2)
    """
    dphi = metrics["phase_rad"]
    span = 2.2 * (2 * np.pi / omega)                # окно ~2.2 периода
    tau = np.linspace(t - span, t, 400)
    sA = np.sin(omega * tau + dphi / 2.0)
    sB = np.sin(omega * tau - dphi / 2.0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=tau, y=sA, mode="lines", name="Sensor A",
                             line=dict(color=SENS_A_C, width=2.5)))
    fig.add_trace(go.Scatter(x=tau, y=sB, mode="lines", name="Sensor B",
                             line=dict(color=SENS_B_C, width=2.5)))
    # текущие точки (момент прохождения)
    fig.add_trace(go.Scatter(
        x=[t, t], y=[np.sin(omega * t + dphi / 2), np.sin(omega * t - dphi / 2)],
        mode="markers", marker=dict(size=10, color=RED), showlegend=False))
    fig.add_annotation(x=t, y=1.25, showarrow=False,
                       text=f"Δφ = {metrics['phase_deg']:.1f}°   |   Δt = {metrics['delta_t_us']:.0f} µs",
                       font=dict(color=WHITE, size=12))
    _style(fig, "Oscilloscope · Sensor A / B", "time", "amplitude", height=250)
    fig.update_yaxes(range=[-1.4, 1.5])
    fig.update_layout(legend=dict(orientation="h", y=1.18, x=0,
                                  font=dict(color=WHITE)))
    return fig


# =============================================================================
#  6. ХАРАКТЕРИСТИЧЕСКИЕ ГРАФИКИ (рабочая точка — красная)
# =============================================================================
def _char_figure(x_curve, y_curve, x_pt, y_pt, title, ylab, ytick=""):
    """Общий помощник: белая кривая + голубая заливка + красная рабочая точка."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x_curve, y=y_curve, mode="lines",
                             line=dict(color=TUBE_CYAN, width=3),
                             fill="tozeroy", fillcolor="rgba(40,200,255,0.08)",
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=[x_pt], y=[y_pt], mode="markers",
                             marker=dict(size=13, color=RED,
                                         line=dict(color="#fff", width=1)),
                             showlegend=False,
                             hovertext=[f"{x_pt:.0f}% → {y_pt:.2f}{ytick}"],
                             hoverinfo="text"))
    _style(fig, title, "Mass Flow, %", ylab, height=215)
    return fig


def draw_phase_graph(metrics):
    """ГРАФИК 1: Mass Flow → Phase Shift."""
    x = np.linspace(0, 100, 100)
    y = 25.0 * x / 100.0
    return _char_figure(x, y, metrics["mdot_pct"], metrics["phase_deg"],
                        "① Mass Flow → Phase Shift", "Δφ, °", "°")


def draw_twist_graph(metrics):
    """ГРАФИК 2: Mass Flow → Tube Twist Angle."""
    x = np.linspace(0, 100, 100)
    y = 12.0 * x / 100.0
    return _char_figure(x, y, metrics["mdot_pct"], metrics["twist_deg"],
                        "② Mass Flow → Twist Angle", "Twist, °", "°")


def draw_massflow_graph(metrics, omega=OMEGA_VIS):
    """ГРАФИК 3: Mass Flow → Sensor Delay (Δt)."""
    x = np.linspace(0, 100, 100)
    y = np.deg2rad(25.0 * x / 100.0) / omega * 1e6      # мкс
    return _char_figure(x, y, metrics["mdot_pct"], metrics["delta_t_us"],
                        "③ Mass Flow → Sensor Delay", "Δt, µs", "µs")


# =============================================================================
#  7. ОФОРМЛЕНИЕ ГРАФИКОВ (тёмная инженерная тема)
# =============================================================================
def _style(fig, title, xlab, ylab, height=240):
    fig.update_layout(
        title=dict(text=title, font=dict(color=WHITE, size=14), x=0.01),
        paper_bgcolor=PANEL, plot_bgcolor=PANEL,
        font=dict(color=WHITE, size=11),
        margin=dict(l=45, r=15, t=40, b=35), height=height)
    fig.update_xaxes(title_text=xlab, gridcolor=GRID, zerolinecolor=GRID,
                     color="#93a2b8")
    fig.update_yaxes(title_text=ylab, gridcolor=GRID, zerolinecolor=GRID,
                     color="#93a2b8")


# =============================================================================
#  8. ANIMATION CONTROLLER
# =============================================================================
def init_state():
    ss = st.session_state
    ss.setdefault("t", 0.0)
    ss.setdefault("playing", True)
    ss.setdefault("speed", 1.0)


def update_animation():
    """Продвигает модельное время t при статусе Play. Возвращает t."""
    ss = st.session_state
    if ss.playing:
        ss.t += 0.05 * ss.speed
    return ss.t


# =============================================================================
#  9. ГЛОБАЛЬНЫЙ CSS (тёмная тема, инженерный вид)
# =============================================================================
def inject_css():
    st.markdown(f"""
    <style>
      .stApp {{ background:{BG}; }}
      section[data-testid="stSidebar"] {{ background:{PANEL}; }}
      h1,h2,h3,h4,p,span,label {{ color:{WHITE} !important; }}
      div[data-testid="stMetricValue"] {{ color:{TUBE_CYAN} !important; }}
      div[data-testid="stMetricLabel"] {{ color:#8ea1bd !important; }}
      .formula-box {{ background:{PANEL}; border:1px solid {GRID};
        border-radius:12px; padding:14px 16px; margin-top:8px; }}
    </style>""", unsafe_allow_html=True)


# =============================================================================
#  10. MAIN
# =============================================================================
def main():
    init_state()
    inject_css()
    ss = st.session_state
    geom = build_centerline()

    # ------------------------- ЗАГОЛОВОК -------------------------
    st.markdown(
        f"<h2 style='margin-bottom:0'>🌀 Coriolis Mass Flow Meter — "
        f"<span style='color:{TUBE_CYAN}'>Digital Twin</span></h2>"
        f"<p style='color:#7f90a8;margin-top:2px'>Интерактивная демонстрация "
        f"принципа кориолисового расходомера · вибрация · сила Кориолиса · "
        f"скручивание · фазовый сдвиг</p>", unsafe_allow_html=True)

    # ------------------------- ПАНЕЛЬ УПРАВЛЕНИЯ (SIDEBAR) -------------------------
    with st.sidebar:
        st.header("🎛️ Панель управления")

        mdot_pct = st.slider("Mass Flow ṁ", 0.0, 100.0, 45.0, 1.0,
                             help="Массовый расход, % (0–100 kg/s)")
        mdot_norm = mdot_pct / 100.0

        st.markdown("**Управление анимацией**")
        c1, c2, c3 = st.columns(3)
        if c1.button("▶ Play", use_container_width=True):
            ss.playing = True
        if c2.button("⏸ Pause", use_container_width=True):
            ss.playing = False
        if c3.button("⟳ Reset", use_container_width=True):
            ss.t = 0.0
            ss.playing = False

        ss.speed = st.slider("Скорость анимации ×", 0.1, 3.0, 1.0, 0.1)
        amplitude = st.slider("Tube Amplitude A", 0.05, 0.45, 0.28, 0.01,
                              help="Амплитуда вибрации трубки")

        st.divider()
        mode_3d = st.toggle("🧊 3D-режим (вращаемый)", value=False)
        show_trail = st.toggle("💫 Motion trail (след)", value=True)

        status = "🟢 RUN" if ss.playing else "⏸ PAUSE"
        st.caption(f"Статус: **{status}**  ·  t = {ss.t:5.2f} c")

    # ------------------------- ОБНОВЛЕНИЕ ВРЕМЕНИ И МЕТРИК -------------------------
    t = update_animation()
    metrics = calculate_phase_shift(mdot_norm)

    # ------------------------- ДВУХКОЛОНОЧНЫЙ LAYOUT -------------------------
    left, right = st.columns([1.15, 1.0], gap="medium")

    # ===== ЛЕВО: АНИМАЦИЯ =====
    with left:
        st.markdown("##### 🏭 Анимация расходомера")
        fig_tubes = draw_tubes(geom, t, mdot_norm, amplitude,
                               mode_3d=mode_3d, show_trail=show_trail)
        st.plotly_chart(fig_tubes, use_container_width=True,
                        config={"displayModeBar": False}, key="tubes")

    # ===== ПРАВО: ОСЦИЛЛОГРАФ + ПАРАМЕТРЫ + ГРАФИКИ =====
    with right:
        st.markdown("##### 📟 Осциллограф датчиков")
        st.plotly_chart(draw_sensor_signals(t, metrics),
                        use_container_width=True,
                        config={"displayModeBar": False}, key="osc")

        # --- численные параметры ---
        st.markdown("##### 📊 Параметры (real-time)")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Mass Flow", f"{metrics['mdot_pct']:.0f} %")
        m2.metric("Phase Shift", f"{metrics['phase_deg']:.1f} °")
        m3.metric("Twist Angle", f"{metrics['twist_deg']:.1f} °")
        m4.metric("Sensor Delay", f"{metrics['delta_t_us']:.0f} µs")
        m5, m6, m7 = st.columns(3)
        m5.metric("Tube Frequency", f"{metrics['freq_hz']:.0f} Hz")
        m6.metric("Tube Amplitude", f"{amplitude:.2f}")
        m7.metric("Coriolis Force", f"{metrics['coriolis_N']:.0f} N")

    # ------------------------- НИЖНИЙ РЯД: 3 ГРАФИКА -------------------------
    st.markdown("##### 📈 Характеристики: Mass Flow → выходные параметры")
    g1, g2, g3 = st.columns(3)
    with g1:
        st.plotly_chart(draw_phase_graph(metrics), use_container_width=True,
                        config={"displayModeBar": False}, key="g_phase")
    with g2:
        st.plotly_chart(draw_twist_graph(metrics), use_container_width=True,
                        config={"displayModeBar": False}, key="g_twist")
    with g3:
        st.plotly_chart(draw_massflow_graph(metrics), use_container_width=True,
                        config={"displayModeBar": False}, key="g_delay")

    # ------------------------- БЛОК ФОРМУЛ -------------------------
    st.markdown("##### 🧮 Физические соотношения (демонстрационная модель)")
    fc1, fc2 = st.columns(2)
    with fc1:
        st.latex(r"\vec{F_c} = 2\,m\,(\vec{v}\times\vec{\omega})")
        st.latex(r"\Delta t \;\propto\; \dot{m}")
    with fc2:
        st.latex(r"\text{Phase Shift}\;\propto\;\dot{m}")
        st.latex(r"\text{Twist Angle}\;\propto\;F_c")

    # ------------------------- ЦИКЛ АНИМАЦИИ -------------------------
    if ss.playing:
        time.sleep(0.03)          # ~ плавное обновление кадров
        st.rerun()


if __name__ == "__main__":
    main()
