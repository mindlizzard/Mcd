"""
ui.py – Streamlit UI: alle 9 tabs voor het McDonald's Management Dashboard
Mobiel-first, touch-friendly, Plotly Gantt, data_editor
"""
from __future__ import annotations
import calendar
import json
import uuid
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

import streamlit as st

from data_model import (
    AppState, Employee, EmployeeAvailability, Shift, Schedule,
    DayConfig, RestaurantConfig, LeaveEntry, SickEntry, Training,
    SalaryType, BusyLevel, ShiftRole, LeaveType,
)
from constraints import dutch_holidays, check_schedule, Violation

# ─── Helpers ─────────────────────────────────────────────────────────────────

NL_MONTHS = ["", "Januari", "Februari", "Maart", "April", "Mei", "Juni",
             "Juli", "Augustus", "September", "Oktober", "November", "December"]
NL_DAYS   = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"]

ROLE_OPTIONS        = [r.value for r in ShiftRole]
BUSY_OPTIONS        = [b.value for b in BusyLevel]
SALARY_OPTIONS      = [s.value for s in SalaryType]
LEAVE_TYPE_OPTIONS  = [l.value for l in LeaveType]


def _state() -> AppState:
    return st.session_state.app_state


def _save_snapshot():
    _state().snapshot()


def _ensure_schedule():
    """Maak een leeg rooster als er geen is."""
    state = _state()
    if state.current_schedule is None:
        now = datetime.now()
        state.current_schedule = Schedule(
            month=now.month, year=now.year,
            restaurant=state.restaurant,
        )


def _emp_options() -> Dict[str, str]:
    """Return {id: naam} mapping."""
    return {e.id: e.name for e in _state().employees}


def _violation_badge(violations: List[Violation]):
    errors   = [v for v in violations if v.severity == "error"]
    warnings = [v for v in violations if v.severity == "warning"]
    if errors:
        st.error(f"🚨 {len(errors)} CAO-overtredingen")
    if warnings:
        st.warning(f"⚠️ {len(warnings)} waarschuwingen")
    if not violations:
        st.success("✅ Geen CAO-overtredingen")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 – Restaurant & Maand
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab1():
    st.subheader("🏪 Restaurant & Maandconfiguratie")
    state = _state()
    r     = state.restaurant

    col1, col2 = st.columns(2)
    with col1:
        r.name     = st.text_input("Naam restaurant", r.name)
        r.location = st.text_input("Locatie / adres", r.location)
        r.open_time  = st.text_input("Openingstijd", r.open_time)
        r.close_time = st.text_input("Sluitingstijd", r.close_time)
    with col2:
        r.drive_thru_enabled = st.checkbox("Drive-Thru aanwezig", r.drive_thru_enabled)
        if r.drive_thru_enabled:
            r.drive_thru_open  = st.text_input("Drive-Thru open",  r.drive_thru_open)
            r.drive_thru_close = st.text_input("Drive-Thru sluit", r.drive_thru_close)
        r.sunday_supplement_pct  = st.number_input("Zondagtoeslag %",  value=r.sunday_supplement_pct,  step=5.0)
        r.holiday_supplement_pct = st.number_input("Feestdagtoeslag %", value=r.holiday_supplement_pct, step=5.0)

    st.divider()
    st.subheader("📅 Maand selecteren")
    _ensure_schedule()
    sched = state.current_schedule

    col1, col2 = st.columns(2)
    with col1:
        sched.month = st.selectbox("Maand", range(1, 13),
                                   index=sched.month - 1,
                                   format_func=lambda m: NL_MONTHS[m])
    with col2:
        sched.year = st.number_input("Jaar", min_value=2024, max_value=2030,
                                     value=sched.year)

    sched.restaurant = r
    sched.labor_budget = st.number_input(
        "💰 Loonbudget maand (€)", min_value=0.0, value=sched.labor_budget, step=500.0)

    # ── Drukke dagen ───────────────────────────────────────────────────────
    st.divider()
    st.subheader("📊 Drukke dagen instellen")
    year, month = sched.year, sched.month
    days_in_month = calendar.monthrange(year, month)[1]
    holidays = dutch_holidays(year)

    existing_cfg = {dc.date: dc for dc in sched.day_configs}
    new_day_configs = []

    # Toon in een responsive grid (7 kolommen = een week)
    weeks = []
    first_weekday = date(year, month, 1).weekday()
    week = [None] * first_weekday
    for day in range(1, days_in_month + 1):
        week.append(day)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        week += [None] * (7 - len(week))
        weeks.append(week)

    # Header
    header_cols = st.columns(7)
    for i, dn in enumerate(NL_DAYS):
        header_cols[i].markdown(f"**{dn}**")

    for week in weeks:
        cols = st.columns(7)
        for col_idx, day in enumerate(week):
            if day is None:
                cols[col_idx].write("")
                continue
            d        = date(year, month, day)
            date_str = str(d)
            dc       = existing_cfg.get(date_str, DayConfig(date=date_str))
            is_hol   = date_str in holidays
            is_sun   = d.weekday() == 6

            label = f"**{day}**"
            if is_hol:
                label += f"\n🎉 {holidays[date_str][:8]}"
            if is_sun:
                label += "\n🌟"

            with cols[col_idx]:
                st.markdown(label)
                dc.busy_level = st.selectbox(
                    "##" + date_str, BUSY_OPTIONS,
                    index=BUSY_OPTIONS.index(dc.busy_level),
                    key=f"busy_{date_str}", label_visibility="collapsed"
                )
                dc.is_holiday  = is_hol
                dc.holiday_name = holidays.get(date_str, "")
            new_day_configs.append(dc)

    sched.day_configs = new_day_configs

    # ── Roosterpublicatie herinnering ──────────────────────────────────────
    publish_date = date(year, month, 1) - timedelta(weeks=3)
    if date.today() > publish_date:
        st.warning(f"⏰ Het rooster voor {NL_MONTHS[month]} {year} moet uiterlijk "
                   f"{publish_date.strftime('%d-%m-%Y')} gepubliceerd zijn (CAO: 3 weken van tevoren)!")
    else:
        st.info(f"ℹ️ Publicatiedeadline rooster: **{publish_date.strftime('%d-%m-%Y')}**")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 – Medewerkers Beheren
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab2():
    st.subheader("👥 Medewerkersbeheer")
    state = _state()

    # ── Importeer CSV / Excel ──────────────────────────────────────────────
    with st.expander("📥 Importeer medewerkers (CSV)", expanded=False):
        uploaded = st.file_uploader("Upload CSV", type=["csv"], key="emp_csv_upload")
        if uploaded:
            from utils import import_employees_csv
            content = uploaded.read().decode("utf-8")
            new_emps, errors = import_employees_csv(content)
            if errors:
                for e in errors:
                    st.warning(e)
            if new_emps:
                if st.button(f"Voeg {len(new_emps)} medewerkers toe"):
                    state.employees += new_emps
                    st.success(f"{len(new_emps)} medewerkers toegevoegd!")
                    st.rerun()

    # ── Exporteer CSV ────────────────────────────────────────────────────
    if state.employees:
        from utils import export_employees_csv
        csv_data = export_employees_csv(state.employees)
        st.download_button("📤 Exporteer medewerkerslijst (CSV)", csv_data.encode(),
                           "medewerkers.csv", "text/csv", use_container_width=True)

    st.divider()

    # ── Nieuwe medewerker toevoegen ──────────────────────────────────────
    with st.expander("➕ Nieuwe medewerker toevoegen", expanded=len(state.employees) == 0):
        with st.form("new_employee_form"):
            col1, col2, col3 = st.columns(3)
            with col1:
                new_name  = st.text_input("Naam *")
                new_role  = st.selectbox("Functie", ROLE_OPTIONS)
                new_start = st.date_input("Startdatum", value=date.today())
            with col2:
                new_ch    = st.number_input("Contracturen/week", 0.0, 48.0, 32.0, 4.0)
                new_stype = st.selectbox("Salaristype", SALARY_OPTIONS)
                new_rate  = st.number_input("Uurloon €", 0.0, 50.0, 13.50, 0.10)
            with col3:
                new_msalary = st.number_input("Maandsalaris €", 0.0, 10000.0, 0.0, 50.0)
                new_senior  = st.number_input("Senioriteit (jaar)", 0.0, 40.0, 0.0, 0.5)
                new_email   = st.text_input("E-mail")

            # Beschikbaarheid
            st.markdown("**Beschikbaarheid:**")
            avail_cols = st.columns(7)
            avail_days = {}
            for i, dn in enumerate(NL_DAYS):
                avail_days[i] = avail_cols[i].checkbox(dn, True, key=f"nav_{i}")

            submitted = st.form_submit_button("➕ Toevoegen", use_container_width=True, type="primary")
            if submitted:
                if not new_name.strip():
                    st.error("Naam is verplicht")
                else:
                    emp = Employee(
                        name=new_name.strip(), role=new_role,
                        contract_hours=new_ch, salary_type=new_stype,
                        hourly_rate=new_rate, monthly_salary=new_msalary,
                        seniority_years=new_senior, start_date=str(new_start),
                        email=new_email,
                        availability=EmployeeAvailability(days=avail_days),
                    )
                    state.employees.append(emp)
                    st.success(f"✅ {new_name} toegevoegd!")
                    st.rerun()

    st.divider()

    # ── Medewerkerslijst ─────────────────────────────────────────────────
    if not state.employees:
        st.info("Nog geen medewerkers. Voeg een medewerker toe via het formulier hierboven.")
        return

    for idx, emp in enumerate(state.employees):
        with st.expander(f"👤 {emp.name} | {emp.role} | {emp.contract_hours}u/w", expanded=False):
            _render_employee_detail(emp, idx)


def _render_employee_detail(emp: Employee, idx: int):
    """Toon detailpaneel voor één medewerker."""
    state = _state()

    tabs = st.tabs(["📋 Basis", "📅 Beschikbaarheid", "🤒 Ziek / Verlof", "🎓 Trainingen", "🗑️ Verwijderen"])

    with tabs[0]:
        col1, col2, col3 = st.columns(3)
        with col1:
            emp.name           = st.text_input("Naam", emp.name, key=f"en_{emp.id}")
            emp.role           = st.selectbox("Functie", ROLE_OPTIONS,
                                              index=ROLE_OPTIONS.index(emp.role), key=f"er_{emp.id}")
            emp.start_date     = st.text_input("Startdatum", emp.start_date, key=f"esd_{emp.id}")
            emp.end_date       = st.text_input("Einddatum (of leeg)", emp.end_date or "", key=f"eed_{emp.id}")
        with col2:
            emp.contract_hours = st.number_input("Contracturen/week", 0.0, 48.0,
                                                  emp.contract_hours, 4.0, key=f"ech_{emp.id}")
            emp.salary_type    = st.selectbox("Salaristype", SALARY_OPTIONS,
                                              index=SALARY_OPTIONS.index(emp.salary_type), key=f"est_{emp.id}")
            emp.hourly_rate    = st.number_input("Uurloon €", 0.0, 50.0,
                                                  emp.hourly_rate, 0.10, key=f"ehr_{emp.id}")
            emp.monthly_salary = st.number_input("Maandsalaris €", 0.0, 10000.0,
                                                  emp.monthly_salary, 50.0, key=f"ems_{emp.id}")
        with col3:
            emp.seniority_years = st.number_input("Senioriteit (jaar)", 0.0, 40.0,
                                                   emp.seniority_years, 0.5, key=f"esn_{emp.id}")
            emp.email   = st.text_input("E-mail", emp.email or "", key=f"eml_{emp.id}")
            emp.phone   = st.text_input("Telefoon", emp.phone or "", key=f"phn_{emp.id}")
            emp.notes   = st.text_area("Notities", emp.notes or "", key=f"ent_{emp.id}", height=80)

        # Re-integratie
        st.markdown("**Re-integratie:**")
        emp.reintegration_active = st.checkbox("Re-integratie actief", emp.reintegration_active,
                                               key=f"eri_{emp.id}")
        if emp.reintegration_active:
            c1, c2 = st.columns(2)
            emp.reintegration_max_hours = c1.number_input("Max uren/dag", 1.0, 12.0,
                                                           emp.reintegration_max_hours, 0.5,
                                                           key=f"erm_{emp.id}")
            emp.reintegration_end_date  = c2.text_input("Eindedatum re-integratie",
                                                         emp.reintegration_end_date or "",
                                                         key=f"ere_{emp.id}")

        # Handmatige black-out datums
        st.markdown("**Handmatige uitsluitdatums (bijv. vakantie/vrij):**")
        bo_str = st.text_area("Datums (één per regel, YYYY-MM-DD)",
                              "\n".join(emp.blackout_dates), key=f"ebo_{emp.id}", height=80)
        emp.blackout_dates = [d.strip() for d in bo_str.split("\n") if d.strip()]

    with tabs[1]:
        st.markdown("**Beschikbaarheid per weekdag:**")
        cols = st.columns(7)
        for i, dn in enumerate(NL_DAYS):
            emp.availability.days[i] = cols[i].checkbox(dn, emp.availability.days.get(i, True),
                                                        key=f"avd_{emp.id}_{i}")
        st.markdown("**Tijdvensters (optioneel, bijv. 08:00 – 20:00):**")
        for i, dn in enumerate(NL_DAYS):
            if emp.availability.days.get(i, True):
                c1, c2 = st.columns(2)
                win = emp.availability.windows.get(str(i), ["", ""])
                start_w = c1.text_input(f"{dn} van", win[0] if win else "", key=f"ws_{emp.id}_{i}")
                end_w   = c2.text_input(f"{dn} tot",  win[1] if win else "", key=f"we_{emp.id}_{i}")
                if start_w and end_w:
                    emp.availability.windows[str(i)] = [start_w, end_w]

    with tabs[2]:
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**🤒 Ziekmelding toevoegen:**")
            sick_start = st.date_input("Ziek vanaf", key=f"ss_{emp.id}")
            sick_end   = st.date_input("Hersteld op (leeglaten = nog ziek)", key=f"se_{emp.id}")
            sick_note  = st.text_input("Reden / opmerkingen", key=f"sn_{emp.id}")
            sick_reint = st.checkbox("Re-integratie starten", key=f"sri_{emp.id}")
            if st.button("➕ Ziekmelding opslaan", key=f"sb_{emp.id}"):
                emp.sick_log.append(SickEntry(
                    start_date=str(sick_start),
                    end_date=str(sick_end) if sick_end else "",
                    reason=sick_note, reintegration=sick_reint,
                ))
                # Voeg ook toe als blackout
                d = sick_start
                while d <= (sick_end or sick_start):
                    emp.blackout_dates.append(str(d))
                    d += timedelta(days=1)
                st.success("Ziekmelding opgeslagen!")
                st.rerun()

            if emp.sick_log:
                st.markdown("**Ziektehistorie:**")
                for sk in emp.sick_log:
                    st.markdown(f"• {sk.start_date} – {sk.end_date or 'nog ziek'}: {sk.reason}")

        with col2:
            st.markdown("**🏖️ Verlof aanvragen / goedkeuren:**")
            lv_start = st.date_input("Verlof vanaf", key=f"ls_{emp.id}")
            lv_end   = st.date_input("Verlof t/m",   key=f"le_{emp.id}")
            lv_type  = st.selectbox("Type verlof", LEAVE_TYPE_OPTIONS, key=f"lt_{emp.id}")
            lv_appr  = st.checkbox("Goedgekeurd", key=f"la_{emp.id}")
            if st.button("➕ Verlof opslaan", key=f"lvb_{emp.id}"):
                lv = LeaveEntry(start_date=str(lv_start), end_date=str(lv_end),
                                leave_type=lv_type, approved=lv_appr)
                emp.leave_log.append(lv)
                if lv_appr:
                    d = lv_start
                    while d <= lv_end:
                        emp.blackout_dates.append(str(d))
                        d += timedelta(days=1)
                    # Update verlofsaldo
                    emp.vacation_days_used += (lv_end - lv_start).days + 1
                st.success("Verlof opgeslagen!")
                st.rerun()

            # Verlofoverzicht
            remaining = emp.vacation_remaining
            st.metric("Verlofdagen resterend", f"{remaining:.0f} / {emp.vacation_days_total:.0f}")
            if emp.leave_log:
                st.markdown("**Verlofhistorie:**")
                for lv in emp.leave_log:
                    status = "✅" if lv.approved else "⏳"
                    st.markdown(f"{status} {lv.start_date} – {lv.end_date}: {lv.leave_type}")

    with tabs[3]:
        st.markdown("**🎓 Training / certificaat toevoegen:**")
        col1, col2 = st.columns(2)
        tr_name  = col1.text_input("Naam training", key=f"tn_{emp.id}")
        tr_date  = col1.date_input("Datum behaald", key=f"td_{emp.id}")
        tr_exp   = col2.date_input("Vervaldatum", key=f"tex_{emp.id}")
        tr_notes = col2.text_input("Notities", key=f"tno_{emp.id}")
        if st.button("➕ Training opslaan", key=f"trb_{emp.id}"):
            emp.trainings.append(Training(
                name=tr_name, date_completed=str(tr_date),
                expiry_date=str(tr_exp), notes=tr_notes,
            ))
            st.success("Training opgeslagen!")
            st.rerun()

        if emp.trainings:
            st.markdown("**Trainingsoverzicht:**")
            for tr in emp.trainings:
                exp_ok = tr.expiry_date >= str(date.today()) if tr.expiry_date else True
                icon   = "✅" if exp_ok else "⚠️"
                st.markdown(f"{icon} **{tr.name}** – behaald: {tr.date_completed} "
                            f"| verloopdatum: {tr.expiry_date or '–'}")

    with tabs[4]:
        st.error("⚠️ Verwijder deze medewerker permanent?")
        if st.button(f"🗑️ Ja, verwijder {emp.name}", key=f"del_{emp.id}", type="primary"):
            state.employees = [e for e in state.employees if e.id != emp.id]
            st.success(f"{emp.name} verwijderd.")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 – Bezetting & Forecast
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab3():
    import plotly.graph_objects as go
    import plotly.express as px
    import numpy as np

    st.subheader("📊 Bezetting & Forecast")
    _ensure_schedule()
    sched = _state().current_schedule

    # ── Bell Curve: verwacht drukte per uur ───────────────────────────────
    st.markdown("### 🔔 Verwachte drukte per uur (bell curve)")
    hours = list(range(6, 24))
    # Typisch McDonald's-patroon: piek lunch 12-13u, avondpiek 17-19u
    base = np.array([1, 2, 3, 5, 8, 10, 9, 7, 5, 6, 8, 9, 7, 5, 4, 3, 3, 2])[:len(hours)]
    fig_bell = go.Figure()
    fig_bell.add_trace(go.Scatter(
        x=hours, y=base, mode="lines+markers",
        fill="tozeroy", fillcolor="rgba(220,0,0,0.15)",
        line=dict(color="#DD0000", width=3),
        name="Verwachte drukte"
    ))
    fig_bell.update_layout(
        xaxis_title="Uur", yaxis_title="Relatieve drukte",
        height=280, margin=dict(l=10, r=10, t=20, b=30),
        xaxis=dict(tickvals=hours, ticktext=[f"{h}:00" for h in hours]),
    )
    st.plotly_chart(fig_bell, use_container_width=True)

    # ── Heatmap: bezetting per dag per uur ────────────────────────────────
    if sched and sched.shifts:
        st.markdown("### 🗓️ Bezettingsheatmap (dag × uur)")
        year, month = sched.year, sched.month
        days_in_month = calendar.monthrange(year, month)[1]

        # Bouw matrix: rows = uur (6..23), cols = dag (1..31)
        matrix = [[0] * (days_in_month + 1) for _ in range(18)]  # uur 6..23
        for sh in sched.shifts:
            d = date.fromisoformat(sh.date)
            if d.month != month or d.year != year:
                continue
            sh_h = int(sh.start_time.split(":")[0])
            eh   = int(sh.end_time.split(":")[0])
            if int(sh.end_time.split(":")[0]) <= sh_h:
                eh += 24
            for h in range(max(6, sh_h), min(24, eh)):
                row = h - 6
                if 0 <= row < 18:
                    matrix[row][d.day] += 1

        import pandas as pd
        df = pd.DataFrame(
            matrix,
            index=[f"{h}:00" for h in range(6, 24)],
            columns=[str(d) for d in range(0, days_in_month + 1)],
        ).iloc[:, 1:]
        df.columns = [str(d) for d in range(1, days_in_month + 1)]

        fig_heat = px.imshow(
            df, color_continuous_scale="Reds",
            labels={"x": "Dag", "y": "Uur", "color": "Medewerkers"},
            height=400, aspect="auto"
        )
        fig_heat.update_layout(margin=dict(l=10, r=10, t=20, b=30))
        st.plotly_chart(fig_heat, use_container_width=True)

    # ── Drukke dagen overzicht ────────────────────────────────────────────
    if sched and sched.day_configs:
        st.markdown("### 📌 Drukke dagen overzicht")
        busy_days = [(dc.date, dc.busy_level)
                     for dc in sched.day_configs if dc.busy_level != BusyLevel.NORMAL.value]
        if busy_days:
            for date_str, level in sorted(busy_days):
                d    = date.fromisoformat(date_str)
                icon = {"Druk": "🟡", "Zeer druk": "🔴", "Rustig": "🟢"}.get(level, "⚪")
                st.markdown(f"{icon} **{d.strftime('%d %B')}** – {level}")
        else:
            st.info("Geen afwijkende dagen ingesteld.")
    else:
        st.info("Genereer eerst een rooster om de heatmap te zien (Tab 5).")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 – Constraints & Regels
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab4():
    st.subheader("⚙️ CAO & ATW Constraints")

    _ensure_schedule()
    state = _state()
    sched = state.current_schedule

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### 📋 Geldende CAO-regels (CAO Horeca 2025-2026)")
        rules = [
            ("Max 12 uur per dienst", "ATW Art. 5:7"),
            ("Min 11 uur dagelijkse rust (1× per 7d: 8u)", "CAO Art. 4.3"),
            ("Min 36 uur weekrust per 7 dagen", "CAO Art. 4.4"),
            ("Nachtdienst max 10 uur", "ATW Art. 5:9"),
            ("Na late nacht (>00:00): min 14u rust", "ATW Art. 5:9"),
            ("Na 3+ nachtdiensten: min 46u rust", "ATW Art. 5:9"),
            ("Max 140 nachtdiensten per jaar", "ATW Art. 5:9"),
            ("Gem. max 48u/week over 16 weken", "ATW Art. 5:7"),
            ("Min 13 vrije zondagen per jaar", "CAO Art. 7.5"),
            ("Rooster min 3 weken van tevoren", "CAO Art. 5.2"),
            ("Zondagtoeslag 50%", "CAO Loon"),
            ("Feestdagtoeslag 100%", "CAO Loon"),
            ("3-daags lookahead volgende maand", "ATW Grenscontrole"),
        ]
        for rule, ref in rules:
            st.markdown(f"✅ **{rule}** *(bron: {ref})*")

    with col2:
        st.markdown("#### ⚡ Live compliance-check")
        if sched and sched.shifts:
            violations = check_schedule(sched, state.employees)
            _violation_badge(violations)
            if violations:
                with st.expander("Toon alle schendingen"):
                    for v in violations:
                        icon = "🚨" if v.severity == "error" else "⚠️"
                        st.markdown(
                            f"{icon} **{v.rule}**  \n"
                            f"{v.description}  \n"
                            f"*Medewerker: {v.employee_name or '–'}, Datum: {v.date or '–'}*"
                        )
        else:
            st.info("Genereer eerst een rooster (Tab 5) voor de compliance-check.")

    st.divider()
    st.markdown("#### 🔧 Minimale bezetting per niveau")
    r = state.restaurant
    col1, col2, col3, col4 = st.columns(4)
    r.min_crew_quiet    = col1.number_input("🟢 Rustig", 1, 20, r.min_crew_quiet)
    r.min_crew_normal   = col2.number_input("⚪ Normaal", 1, 20, r.min_crew_normal)
    r.min_crew_busy     = col3.number_input("🟡 Druk", 1, 20, r.min_crew_busy)
    r.min_crew_very_busy = col4.number_input("🔴 Zeer druk", 1, 20, r.min_crew_very_busy)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 – Auto-Generate Maandrooster
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab5():
    st.subheader("🤖 Automatisch Maandrooster Genereren")
    state = _state()
    _ensure_schedule()
    sched = state.current_schedule

    if not state.employees:
        st.warning("⚠️ Voeg eerst medewerkers toe (Tab 2) voordat je een rooster genereert.")
        return

    col1, col2 = st.columns(2)
    with col1:
        mode = st.radio("📊 Planningsmodus", ["Balanced", "Lean", "Heavy"], horizontal=True,
                        help="Balanced = contracturen, Lean = minimale bezetting, Heavy = maximale dekking")
        lookahead = st.slider("3-daags lookahead (ATW boundary)", 0, 7, 3)
        time_limit = st.slider("Solver tijdslimiet (sec)", 10, 120, 30)
    with col2:
        st.markdown("**📌 Samenvatting:**")
        st.markdown(f"- Maand: **{NL_MONTHS[sched.month]} {sched.year}**")
        st.markdown(f"- Medewerkers: **{len(state.employees)}**")
        st.markdown(f"- Budget: **€{sched.labor_budget:,.0f}**")
        st.markdown(f"- Drukke dagen: **{sum(1 for dc in sched.day_configs if dc.busy_level in [BusyLevel.BUSY.value, BusyLevel.VERY_BUSY.value])}**")

    st.info("⚠️ Het genereren wist het bestaande rooster voor deze maand. Maak een back-up via Tab 8.")

    if st.button("🚀 Genereer rooster", type="primary", use_container_width=True):
        _save_snapshot()
        progress_bar = st.progress(0, "Solver starten…")

        def progress_cb(pct, msg):
            progress_bar.progress(pct, msg)

        from solver import generate_schedule
        with st.spinner("Rooster wordt berekend…"):
            updated_sched, messages = generate_schedule(
                sched, state.employees, mode=mode,
                lookahead_days=lookahead, time_limit_sec=time_limit,
                progress_callback=progress_cb,
            )
            state.current_schedule = updated_sched
            from constraints import recompute_costs
            recompute_costs(updated_sched, state.employees)

        progress_bar.progress(1.0, "✅ Klaar!")
        for msg in messages:
            st.info(msg)

        # Compliance direct checken
        violations = check_schedule(updated_sched, state.employees)
        _violation_badge(violations)
        st.success(f"✅ {len(updated_sched.shifts)} diensten gepland. Ga naar Tab 6 om te bewerken.")
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 6 – Rooster Bewerken
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab6():
    import plotly.figure_factory as ff
    import plotly.express as px
    import pandas as pd

    st.subheader("✏️ Rooster Bewerken")
    state = _state()
    _ensure_schedule()
    sched = state.current_schedule

    if not sched or not sched.shifts:
        st.info("Genereer eerst een rooster via Tab 5.")
        return

    # ── Undo / Redo ────────────────────────────────────────────────────────
    col_undo, col_add, col_viol = st.columns([1, 2, 2])
    with col_undo:
        if st.button("↩️ Ongedaan maken", use_container_width=True):
            if state.undo():
                st.success("Laatste wijziging ongedaan gemaakt.")
                st.rerun()
            else:
                st.warning("Geen historisch rooster beschikbaar.")

    # ── Dag-filter ─────────────────────────────────────────────────────────
    year, month = sched.year, sched.month
    days_in_month = calendar.monthrange(year, month)[1]
    day_options = [date(year, month, d) for d in range(1, days_in_month + 1)]
    selected_day = st.selectbox(
        "📅 Bekijk dag", day_options,
        format_func=lambda d: f"{NL_DAYS[d.weekday()]} {d.day} {NL_MONTHS[d.month]}",
        key="edit_day_select"
    )
    day_str = str(selected_day)

    # ── Gantt Chart ────────────────────────────────────────────────────────
    st.markdown(f"#### 📊 Gantt: {NL_DAYS[selected_day.weekday()]} {selected_day.day} {NL_MONTHS[month]}")
    day_shifts = sched.get_shifts_for_date(day_str)

    if day_shifts:
        gantt_data = []
        for sh in day_shifts:
            d_obj = date.fromisoformat(sh.date)
            sh_h, sh_m = map(int, sh.start_time.split(":"))
            eh, em     = map(int, sh.end_time.split(":"))
            start_dt   = datetime(d_obj.year, d_obj.month, d_obj.day, sh_h, sh_m)
            end_m      = eh * 60 + em
            s_m        = sh_h * 60 + sh_m
            if end_m <= s_m:
                end_m += 1440
            extra = end_m // 1440
            final = end_m % 1440
            end_d_obj = d_obj + timedelta(days=extra)
            end_dt = datetime(end_d_obj.year, end_d_obj.month, end_d_obj.day,
                              final // 60, final % 60)
            gantt_data.append(dict(
                Task=sh.employee_name, Start=start_dt, Finish=end_dt,
                Resource=sh.role, Cost=f"€{sh.labor_cost:.2f}"
            ))

        df_gantt = pd.DataFrame(gantt_data)
        colors_map = {role: color for role, color in zip(
            [r.value for r in ShiftRole],
            px.colors.qualitative.Set2
        )}

        fig = px.timeline(
            df_gantt, x_start="Start", x_end="Finish",
            y="Task", color="Resource",
            color_discrete_map=colors_map,
            hover_data=["Cost"],
            height=max(250, len(day_shifts) * 35),
        )
        fig.update_layout(margin=dict(l=5, r=5, t=15, b=5), showlegend=True)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Geen diensten op deze dag.")

    # ── Data Editor ────────────────────────────────────────────────────────
    st.markdown(f"#### 📝 Diensten bewerken – {day_str}")

    emp_map = _emp_options()
    if day_shifts:
        import pandas as pd
        df = pd.DataFrame([{
            "ID":         sh.id,
            "Medewerker": sh.employee_name,
            "Begin":      sh.start_time,
            "Einde":      sh.end_time,
            "Functie":    sh.role,
            "Pauze (min)": sh.break_minutes,
            "Notities":   sh.notes,
            "Kosten €":   round(sh.labor_cost, 2),
        } for sh in day_shifts])

        edited_df = st.data_editor(
            df, key=f"edit_df_{day_str}", use_container_width=True,
            column_config={
                "ID": st.column_config.TextColumn("ID", disabled=True, width="small"),
                "Medewerker": st.column_config.TextColumn("Medewerker"),
                "Begin": st.column_config.TextColumn("Begin", help="HH:MM"),
                "Einde": st.column_config.TextColumn("Einde", help="HH:MM"),
                "Functie": st.column_config.SelectboxColumn("Functie", options=ROLE_OPTIONS),
                "Pauze (min)": st.column_config.NumberColumn("Pauze", min_value=0, max_value=60),
                "Notities": st.column_config.TextColumn("Notities"),
                "Kosten €": st.column_config.NumberColumn("Kosten €", disabled=True),
            },
            hide_index=True,
            num_rows="dynamic",
        )
        if st.button("💾 Wijzigingen opslaan", key=f"save_{day_str}", type="primary"):
            _save_snapshot()
            # Verwijder alle shifts van deze dag
            sched.shifts = [s for s in sched.shifts if s.date != day_str]
            # Voeg bewerkte shifts toe
            for _, row in edited_df.iterrows():
                emp_name = row["Medewerker"]
                emp_obj  = next((e for e in state.employees if e.name == emp_name), None)
                sh = Shift(
                    id=row["ID"] if row["ID"] else str(uuid.uuid4())[:8],
                    employee_id=emp_obj.id if emp_obj else "",
                    employee_name=emp_name,
                    date=day_str,
                    start_time=row["Begin"],
                    end_time=row["Einde"],
                    role=row["Functie"],
                    break_minutes=int(row["Pauze (min)"]),
                    notes=row["Notities"] or "",
                )
                sched.shifts.append(sh)
            from constraints import recompute_costs
            recompute_costs(sched, state.employees)
            sched.touch()
            st.success("✅ Wijzigingen opgeslagen!")
            st.rerun()

    # ── Dienst toevoegen ──────────────────────────────────────────────────
    with st.expander("➕ Dienst toevoegen", expanded=False):
        with st.form(f"add_shift_{day_str}"):
            col1, col2, col3 = st.columns(3)
            emp_names = [e.name for e in state.employees]
            sel_emp  = col1.selectbox("Medewerker", emp_names)
            sel_role = col1.selectbox("Functie", ROLE_OPTIONS)
            sel_start = col2.text_input("Begintijd (HH:MM)", "09:00")
            sel_end   = col2.text_input("Eindtijd (HH:MM)", "17:00")
            sel_break = col3.number_input("Pauze (min)", 0, 60, 30)
            sel_notes = col3.text_input("Notities", "")
            if st.form_submit_button("➕ Dienst toevoegen", type="primary"):
                _save_snapshot()
                emp_obj = next((e for e in state.employees if e.name == sel_emp), None)
                if emp_obj:
                    sh = Shift(
                        employee_id=emp_obj.id, employee_name=sel_emp,
                        date=day_str, start_time=sel_start, end_time=sel_end,
                        role=sel_role, break_minutes=sel_break, notes=sel_notes,
                    )
                    from constraints import recompute_costs
                    sched.shifts.append(sh)
                    recompute_costs(sched, state.employees)
                    sched.touch()
                    st.success(f"Dienst toegevoegd voor {sel_emp}!")
                    st.rerun()

    # ── Dienst ruilen ─────────────────────────────────────────────────────
    with st.expander("🔄 Dienst ruilen", expanded=False):
        st.markdown("Selecteer twee medewerkers en hun diensten worden op deze dag geruild.")
        emp_names = list({sh.employee_name for sh in day_shifts})
        if len(emp_names) >= 2:
            col1, col2 = st.columns(2)
            swap_a = col1.selectbox("Medewerker A", emp_names, key="swap_a")
            swap_b = col2.selectbox("Medewerker B", [e for e in emp_names if e != swap_a], key="swap_b")
            if st.button("🔄 Ruil diensten", type="secondary"):
                _save_snapshot()
                for sh in sched.shifts:
                    if sh.date == day_str and sh.employee_name == swap_a:
                        emp_b = next((e for e in state.employees if e.name == swap_b), None)
                        sh.employee_name = swap_b
                        sh.employee_id   = emp_b.id if emp_b else sh.employee_id
                    elif sh.date == day_str and sh.employee_name == swap_b:
                        emp_a = next((e for e in state.employees if e.name == swap_a), None)
                        sh.employee_name = swap_a
                        sh.employee_id   = emp_a.id if emp_a else sh.employee_id
                sched.touch()
                st.success(f"Diensten van {swap_a} en {swap_b} geruild!")
                st.rerun()

    # ── AI-suggesties ──────────────────────────────────────────────────────
    with st.expander("🤖 AI-suggesties", expanded=False):
        violations = check_schedule(sched, state.employees)
        day_viols  = [v for v in violations if v.date == day_str]
        if day_viols:
            st.warning(f"⚠️ {len(day_viols)} CAO-schendingen op {day_str}:")
            for v in day_viols:
                st.markdown(f"• **{v.rule}**: {v.description}")
                # Suggestie
                if "dagrust" in v.rule.lower():
                    st.info("💡 Tip: Verschuif de begintijd van de volgende dienst 11 uur na het einde van de vorige dienst.")
                elif "nacht" in v.rule.lower():
                    st.info("💡 Tip: Verkort de nachtdienst tot max 10 uur, of plan 46u rust na 3+ nachten.")
        else:
            st.success("✅ Geen CAO-schendingen op deze dag.")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 7 – Rapportage & KPI's
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab7():
    import plotly.graph_objects as go
    import plotly.express as px

    st.subheader("📈 Rapportage & KPI-dashboard")
    state = _state()
    _ensure_schedule()
    sched = state.current_schedule

    if not sched or not sched.shifts:
        st.info("Genereer eerst een rooster (Tab 5) voor de rapportage.")
        return

    from utils import compute_kpis
    kpis = compute_kpis(sched, state.employees)

    # ── KPI-kaarten ───────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Loonkosten", kpis["Totale loonkosten"])
    col2.metric("📊 Budget-afwijking", kpis["Budget-afwijking"])
    col3.metric("⏱️ Totaal uren", kpis["Totale diensturen"])
    col4.metric("⚠️ CAO-check", kpis["CAO-overtredingen"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("🏋️ Overtijd", kpis["Overtijduren"])
    col2.metric("📋 Contractafwijking", kpis["Gem. contractafwijking/emp"])
    col3.metric("🤒 Verzuim %", kpis["Ziekteverzuim (maand)"])
    col4.metric("👥 Medewerkers", kpis["Actieve medewerkers"])

    st.divider()

    # ── Uren per medewerker vs contract ───────────────────────────────────
    st.markdown("#### 📊 Uren per medewerker vs. contracturen")
    weeks = calendar.monthrange(sched.year, sched.month)[1] / 7
    emp_actual  = {e.name: 0.0 for e in state.employees}
    emp_target  = {e.name: e.contract_hours * weeks for e in state.employees}
    for sh in sched.shifts:
        if sh.employee_name in emp_actual:
            emp_actual[sh.employee_name] += sh.duration_hours

    names   = list(emp_actual.keys())
    actuals = [emp_actual[n] for n in names]
    targets = [emp_target[n] for n in names]

    fig_bar = go.Figure()
    fig_bar.add_trace(go.Bar(name="Gepland", x=names, y=actuals,
                              marker_color="#4CAF50"))
    fig_bar.add_trace(go.Bar(name="Contract-target", x=names, y=targets,
                              marker_color="#2196F3", opacity=0.6))
    fig_bar.update_layout(barmode="overlay", height=320,
                           margin=dict(l=5, r=5, t=15, b=5),
                           yaxis_title="Uren",
                           legend=dict(orientation="h", y=1.1))
    st.plotly_chart(fig_bar, use_container_width=True)

    # ── Kosten per dag ─────────────────────────────────────────────────────
    st.markdown("#### 💰 Loonkosten per dag")
    year, month = sched.year, sched.month
    days_in_month = calendar.monthrange(year, month)[1]
    cost_per_day = {str(date(year, month, d)): 0.0 for d in range(1, days_in_month + 1)}
    for sh in sched.shifts:
        if sh.date in cost_per_day:
            cost_per_day[sh.date] += sh.labor_cost

    fig_cost = go.Figure(go.Bar(
        x=list(cost_per_day.keys()),
        y=list(cost_per_day.values()),
        marker_color="#DD0000",
    ))
    if sched.labor_budget > 0:
        daily_budget = sched.labor_budget / days_in_month
        fig_cost.add_hline(y=daily_budget, line_dash="dash", line_color="green",
                           annotation_text=f"Dagbudget €{daily_budget:.0f}")
    fig_cost.update_layout(height=300, margin=dict(l=5, r=5, t=15, b=5),
                           yaxis_title="Kosten (€)")
    st.plotly_chart(fig_cost, use_container_width=True)

    # ── Alle KPI's tabel ──────────────────────────────────────────────────
    st.markdown("#### 📋 Alle KPI's")
    import pandas as pd
    df_kpi = pd.DataFrame(list(kpis.items()), columns=["KPI", "Waarde"])
    st.dataframe(df_kpi, use_container_width=True, hide_index=True)

    # ── CAO compliance ────────────────────────────────────────────────────
    st.markdown("#### 🔍 CAO Compliance Rapport")
    violations = check_schedule(sched, state.employees)
    _violation_badge(violations)
    if violations:
        import pandas as pd
        df_viol = pd.DataFrame([{
            "Ernst": v.severity, "Regel": v.rule,
            "Beschrijving": v.description, "Medewerker": v.employee_name,
            "Datum": v.date,
        } for v in violations])
        st.dataframe(df_viol, use_container_width=True, hide_index=True,
                     column_config={
                         "Ernst": st.column_config.TextColumn("Ernst", width="small"),
                     })


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 8 – Export
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab8():
    st.subheader("📤 Export")
    state = _state()
    _ensure_schedule()
    sched = state.current_schedule

    if not sched:
        st.info("Maak eerst een rooster (Tab 5).")
        return

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("#### 📊 Excel Export")
        try:
            from utils import export_schedule_excel
            excel_data = export_schedule_excel(sched, state.employees)
            st.download_button(
                "📥 Download Rooster (Excel)",
                excel_data,
                f"rooster_{sched.year}_{sched.month:02d}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True, type="primary"
            )
        except ImportError as e:
            st.warning(f"openpyxl vereist: `pip install openpyxl` ({e})")

        st.markdown("#### 📋 CSV Export")
        from utils import export_employees_csv
        csv_emps = export_employees_csv(state.employees)
        st.download_button("📥 Medewerkerslijst (CSV)", csv_emps.encode(),
                           "medewerkers.csv", "text/csv", use_container_width=True)

        # JSON backup
        from utils import state_to_json
        st.markdown("#### 💾 JSON Backup (volledige state)")
        json_data = state_to_json(state)
        st.download_button("📥 Download JSON Backup", json_data.encode(),
                           "backup_rooster.json", "application/json",
                           use_container_width=True)

        # JSON restore
        st.markdown("#### 📂 JSON Herstellen")
        uploaded_json = st.file_uploader("Upload JSON backup", type=["json"],
                                         key="json_restore")
        if uploaded_json:
            from utils import state_from_json
            try:
                new_state = state_from_json(uploaded_json.read().decode("utf-8"))
                if st.button("✅ Herstel uit backup", type="primary"):
                    st.session_state.app_state = new_state
                    st.success("Backup hersteld!")
                    st.rerun()
            except Exception as ex:
                st.error(f"Fout bij herstellen: {ex}")

    with col2:
        st.markdown("#### 📅 iCal Export")
        try:
            from utils import export_ical_full, export_ical_employee
            # Volledig team
            ical_full = export_ical_full(sched)
            st.download_button("📥 Team iCal (alle medewerkers)",
                               ical_full,
                               f"team_rooster_{sched.year}_{sched.month:02d}.ics",
                               "text/calendar", use_container_width=True)
            # Per medewerker
            st.markdown("**Per medewerker:**")
            for emp in state.employees:
                emp_shifts = sched.get_shifts_for_employee(emp.id)
                if emp_shifts:
                    ical_emp = export_ical_employee(emp_shifts, emp.name)
                    st.download_button(
                        f"📅 {emp.name}",
                        ical_emp,
                        f"rooster_{emp.name.replace(' ', '_')}_{sched.month:02d}.ics",
                        "text/calendar", key=f"ical_{emp.id}",
                    )
        except ImportError as e:
            st.warning(f"icalendar vereist: `pip install icalendar` ({e})")

        st.markdown("#### 🖨️ PDF Export")
        try:
            from utils import export_schedule_pdf
            pdf_data = export_schedule_pdf(sched, state.employees)
            st.download_button("📥 Download Rooster (PDF)",
                               pdf_data,
                               f"rooster_{sched.year}_{sched.month:02d}.pdf",
                               "application/pdf", use_container_width=True, type="primary")
        except ImportError as e:
            st.warning(f"reportlab vereist: `pip install reportlab` ({e})")
        except Exception as ex:
            st.error(f"PDF-fout: {ex}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 9 – HR Module
# ═══════════════════════════════════════════════════════════════════════════════

def render_tab9():
    st.subheader("👔 HR Module")
    state = _state()

    if not state.employees:
        st.info("Voeg eerst medewerkers toe (Tab 2).")
        return

    hr_tabs = st.tabs(["📋 Dossiers", "🏖️ Verlof", "🤒 Verzuim", "🎓 Trainingen",
                        "🔔 HR-Alerts", "📊 HR-Rapportages"])

    with hr_tabs[0]:
        st.markdown("#### 📋 Personeelsdossiers")
        for emp in state.employees:
            with st.expander(f"👤 {emp.name} | {emp.role} | Senioriteit: {emp.seniority_years:.1f}j"):
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown(f"**Startdatum:** {emp.start_date or '–'}")
                    st.markdown(f"**Einddatum:** {emp.end_date or 'Onbepaald'}")
                    st.markdown(f"**E-mail:** {emp.email or '–'}")
                    st.markdown(f"**Telefoon:** {emp.phone or '–'}")
                with col2:
                    st.markdown(f"**Contracturen:** {emp.contract_hours}u/week")
                    st.markdown(f"**Salaristype:** {emp.salary_type}")
                    rate = f"€{emp.hourly_rate}/u" if emp.salary_type == "Uurloon" else f"€{emp.monthly_salary}/maand"
                    st.markdown(f"**Salaris:** {rate}")
                    st.markdown(f"**Verlof resterend:** {emp.vacation_remaining:.0f} dagen")

                if emp.notes:
                    st.markdown(f"**Notities:** {emp.notes}")

    with hr_tabs[1]:
        st.markdown("#### 🏖️ Verlofoverzicht alle medewerkers")
        for emp in state.employees:
            pending = [lv for lv in emp.leave_log if not lv.approved]
            approved = [lv for lv in emp.leave_log if lv.approved]
            if pending or approved:
                st.markdown(f"**{emp.name}** (resterend: {emp.vacation_remaining:.0f}d)")
                for lv in pending:
                    col1, col2, col3 = st.columns([3, 1, 1])
                    col1.markdown(f"⏳ {lv.start_date} – {lv.end_date}: {lv.leave_type}")
                    if col2.button("✅ Goedkeuren", key=f"appr_{lv.id}"):
                        lv.approved = True
                        d = date.fromisoformat(lv.start_date)
                        end = date.fromisoformat(lv.end_date) if lv.end_date else d
                        while d <= end:
                            if str(d) not in emp.blackout_dates:
                                emp.blackout_dates.append(str(d))
                            d += timedelta(days=1)
                        emp.vacation_days_used += (end - date.fromisoformat(lv.start_date)).days + 1
                        st.rerun()
                    if col3.button("❌ Afwijzen", key=f"rej_{lv.id}"):
                        emp.leave_log = [l for l in emp.leave_log if l.id != lv.id]
                        st.rerun()
                for lv in approved:
                    st.markdown(f"✅ {lv.start_date} – {lv.end_date}: {lv.leave_type}")

    with hr_tabs[2]:
        st.markdown("#### 🤒 Ziekteverzuim Tracker")
        total_sick = sum(len(e.sick_log) for e in state.employees)
        active_sick = [e for e in state.employees
                       if any(not sk.end_date or sk.end_date >= str(date.today())
                              for sk in e.sick_log)]
        col1, col2 = st.columns(2)
        col1.metric("Actief ziek", len(active_sick))
        col2.metric("Ziekte-meldingen totaal", total_sick)

        for emp in state.employees:
            active = [sk for sk in emp.sick_log
                      if not sk.end_date or sk.end_date >= str(date.today())]
            if active:
                st.error(f"🤒 **{emp.name}** – ziek")
                for sk in active:
                    st.markdown(f"  Ziek sinds: {sk.start_date} | Reden: {sk.reason or '–'}")
                    st.markdown(f"  Re-integratie: {'Ja' if sk.reintegration else 'Nee'}")
                    if st.button(f"✅ Hersteld melden – {emp.name}", key=f"rec_{sk.id}"):
                        sk.end_date = str(date.today())
                        st.success(f"{emp.name} hersteld gemeld!")
                        st.rerun()

    with hr_tabs[3]:
        st.markdown("#### 🎓 Trainings- & Certificaatoverzicht")
        today = str(date.today())
        for emp in state.employees:
            if emp.trainings:
                expired = [t for t in emp.trainings if t.expiry_date and t.expiry_date < today]
                expiring_soon = [t for t in emp.trainings
                                 if t.expiry_date and today <= t.expiry_date <=
                                 str(date.today() + timedelta(days=30))]
                if expired:
                    st.error(f"⚠️ **{emp.name}**: {len(expired)} verlopen certificaat(en)")
                    for t in expired:
                        st.markdown(f"  🔴 {t.name} – verlopen: {t.expiry_date}")
                if expiring_soon:
                    st.warning(f"⏰ **{emp.name}**: {len(expiring_soon)} certificaat(en) verlopen binnenkort")
                    for t in expiring_soon:
                        st.markdown(f"  🟡 {t.name} – verloopt: {t.expiry_date}")

    with hr_tabs[4]:
        st.markdown("#### 🔔 HR-Alerts")
        today = date.today()
        alerts = []

        for emp in state.employees:
            # Contractverloop
            if emp.end_date:
                try:
                    end = date.fromisoformat(emp.end_date)
                    days_left = (end - today).days
                    if 0 < days_left <= 30:
                        alerts.append(("🔴", f"{emp.name}: contract verloopt over {days_left} dagen ({emp.end_date})"))
                    elif days_left <= 0:
                        alerts.append(("⚫", f"{emp.name}: contract verlopen op {emp.end_date}"))
                except ValueError:
                    pass

            # Verjaardag
            if emp.date_of_birth:
                try:
                    dob = date.fromisoformat(emp.date_of_birth)
                    birthday_this_year = date(today.year, dob.month, dob.day)
                    days_to_bday = (birthday_this_year - today).days
                    if 0 <= days_to_bday <= 7:
                        age = today.year - dob.year
                        alerts.append(("🎂", f"{emp.name}: verjaardag over {days_to_bday} dagen ({age} jaar)"))
                except ValueError:
                    pass

            # Verlopen certificaten
            for tr in emp.trainings:
                if tr.expiry_date and tr.expiry_date < str(today):
                    alerts.append(("📜", f"{emp.name}: certificaat '{tr.name}' verlopen ({tr.expiry_date})"))

        if alerts:
            for icon, msg in alerts:
                st.warning(f"{icon} {msg}")
        else:
            st.success("✅ Geen lopende HR-alerts.")

    with hr_tabs[5]:
        st.markdown("#### 📊 HR-Rapportages")
        import plotly.express as px

        # Verzuimpercentage
        year_days = 365
        total_sick_days = 0
        for emp in state.employees:
            for sk in emp.sick_log:
                try:
                    start = date.fromisoformat(sk.start_date)
                    end   = date.fromisoformat(sk.end_date) if sk.end_date else date.today()
                    total_sick_days += (end - start).days + 1
                except ValueError:
                    pass
        working_days_total = len(state.employees) * (year_days * 5 / 7)
        sick_pct = (total_sick_days / working_days_total * 100) if working_days_total > 0 else 0

        col1, col2, col3 = st.columns(3)
        col1.metric("Verzuimpercentage (jaarbasis)", f"{sick_pct:.1f}%")
        col2.metric("Totale ziektedagen", total_sick_days)
        col3.metric("Medewerkers", len(state.employees))

        # Functieverhouding
        role_counts = {}
        for emp in state.employees:
            role_counts[emp.role] = role_counts.get(emp.role, 0) + 1
        if role_counts:
            fig_pie = px.pie(
                names=list(role_counts.keys()),
                values=list(role_counts.values()),
                title="Functieverdeling",
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_pie.update_layout(height=300, margin=dict(l=5, r=5, t=30, b=5))
            st.plotly_chart(fig_pie, use_container_width=True)

        # Senioriteitsverdeling
        if state.employees:
            senior_data = [(e.name, e.seniority_years) for e in state.employees]
            senior_data.sort(key=lambda x: -x[1])
            fig_senior = px.bar(
                x=[s[1] for s in senior_data],
                y=[s[0] for s in senior_data],
                orientation="h",
                labels={"x": "Jaren", "y": "Medewerker"},
                title="Senioriteit medewerkers",
                color_discrete_sequence=["#DD0000"],
            )
            fig_senior.update_layout(height=max(200, len(state.employees) * 25),
                                     margin=dict(l=5, r=5, t=30, b=5))
            st.plotly_chart(fig_senior, use_container_width=True)
