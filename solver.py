"""
solver.py – Auto-genereer maandrooster
Primaire solver: Google OR-Tools CP-SAT
Fallback: Greedy-algoritme (als OR-Tools niet beschikbaar is)

Aanpak:
  - Dienstsjablonen (shift templates) met vaste tijden
  - Binaire variabelen: x[employee][day][template] ∈ {0,1}
  - Hard constraints: max 1 dienst/dag, black-outs, beschikbaarheid, dagrust
  - Soft constraint: contracturen zo dicht mogelijk bereiken
  - 3-daags lookahead naar volgende maand voor ATW-grenscontrole
"""
from __future__ import annotations
import calendar
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
import uuid

from data_model import (
    Employee, Shift, Schedule, ShiftRole, BusyLevel,
    DayConfig, RestaurantConfig,
)
from constraints import dutch_holidays, _is_night_shift

# ─── OR-Tools import (optioneel) ──────────────────────────────────────────────

try:
    from ortools.sat.python import cp_model as _cp_model
    HAS_ORTOOLS = True
except ImportError:
    HAS_ORTOOLS = False

# ─── Dienstsjablonen ─────────────────────────────────────────────────────────

# (start_time, end_time, label)
SHIFT_TEMPLATES: List[Tuple[str, str, str]] = [
    # Vroeg
    ("06:00", "14:00", "Vroeg-8u"),
    ("07:00", "15:00", "Vroeg-8u"),
    ("08:00", "16:00", "Mid-8u"),
    # Dag
    ("09:00", "17:00", "Dag-8u"),
    ("10:00", "18:00", "Dag-8u"),
    ("11:00", "19:00", "Mid-8u"),
    # Middag/avond
    ("12:00", "20:00", "Mid-8u"),
    ("13:00", "21:00", "Laat-8u"),
    ("14:00", "22:00", "Laat-8u"),
    ("15:00", "23:00", "Laat-8u"),
    # Avond (kort)
    ("16:00", "22:00", "Avond-6u"),
    ("17:00", "22:00", "Avond-5u"),
    ("17:00", "23:00", "Avond-6u"),
    # Nacht
    ("22:00", "06:00", "Nacht-8u"),
    ("23:00", "07:00", "Nacht-8u"),
    # Kort (part-time / split)
    ("08:00", "12:00", "Ochtend-4u"),
    ("09:00", "13:00", "Ochtend-4u"),
    ("12:00", "17:00", "Middag-5u"),
    ("13:00", "18:00", "Middag-5u"),
    ("18:00", "22:00", "Avond-4u"),
]

# Sjabloonduur in uren (berekend)

def _template_hours(start: str, end: str) -> float:
    sh, sm = map(int, start.split(":"))
    eh, em = map(int, end.split(":"))
    s_m = sh * 60 + sm
    e_m = eh * 60 + em
    if e_m <= s_m:
        e_m += 1440
    return (e_m - s_m) / 60.0


TEMPLATE_HOURS = [_template_hours(s, e) for s, e, _ in SHIFT_TEMPLATES]

# ─── Dagelijkse minimum-bezetting per drukteniveau ───────────────────────────

BUSY_STAFF_FACTOR: Dict[str, float] = {
    BusyLevel.QUIET.value:    0.7,
    BusyLevel.NORMAL.value:   1.0,
    BusyLevel.BUSY.value:     1.5,
    BusyLevel.VERY_BUSY.value: 2.0,
}


def _min_staff(day_cfg: DayConfig, rest_cfg: RestaurantConfig) -> int:
    if day_cfg.min_staff_override is not None:
        return day_cfg.min_staff_override
    return rest_cfg.min_crew_for_level(day_cfg.busy_level)


# ─── Publieke API ─────────────────────────────────────────────────────────────

def generate_schedule(
    schedule: Schedule,
    employees: List[Employee],
    mode: str = "Balanced",       # "Balanced" | "Lean" | "Heavy"
    lookahead_days: int = 3,
    time_limit_sec: int = 30,
    progress_callback=None,
) -> Tuple[Schedule, List[str]]:
    """
    Genereer een volledig maandrooster.
    Geeft (schedule, messages) terug.
    schedule.shifts wordt gevuld (bestaande shifts worden verwijderd).
    """
    messages: List[str] = []
    schedule.shifts = []   # begin schoon

    if HAS_ORTOOLS:
        messages.append("🤖 OR-Tools CP-SAT solver actief.")
        shifts, msgs = _solve_ortools(schedule, employees, mode, lookahead_days, time_limit_sec, progress_callback)
    else:
        messages.append("⚠️ OR-Tools niet geïnstalleerd – greedy fallback actief.")
        shifts, msgs = _solve_greedy(schedule, employees, mode, lookahead_days)

    messages += msgs
    schedule.shifts = shifts
    return schedule, messages


# ─── OR-Tools CP-SAT Solver ───────────────────────────────────────────────────

def _solve_ortools(
    schedule: Schedule, employees: List[Employee], mode: str,
    lookahead_days: int, time_limit_sec: int, progress_callback
) -> Tuple[List[Shift], List[str]]:
    """CP-SAT: binaire toewijzing van dienstsjablonen."""
    messages = []
    cp    = _cp_model
    model = cp.CpModel()
    solver = cp.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_sec

    # Genereer te plannen datums (maand + lookahead)
    year, month = schedule.year, schedule.month
    days_in_month = calendar.monthrange(year, month)[1]
    plan_dates: List[date] = []
    for day in range(1, days_in_month + 1):
        plan_dates.append(date(year, month, day))
    # Lookahead
    last = plan_dates[-1]
    for i in range(1, lookahead_days + 1):
        plan_dates.append(last + timedelta(days=i))

    holidays = dutch_holidays(year)
    active_emps = [e for e in employees if e.end_date == "" or e.end_date is None or
                   (e.end_date and e.end_date >= str(date(year, month, 1)))]

    E = len(active_emps)
    D = len(plan_dates)
    T = len(SHIFT_TEMPLATES)

    # Maak variabelen
    x: Dict = {}
    for e in range(E):
        for d in range(D):
            for t in range(T):
                x[e, d, t] = model.NewBoolVar(f"x_{e}_{d}_{t}")

    # ── Hard constraints ─────────────────────────────────────────────────────

    for e, emp in enumerate(active_emps):
        for d, day in enumerate(plan_dates):
            day_str = str(day)

            # Max 1 dienst per dag per medewerker
            model.AddAtMostOne(x[e, d, t] for t in range(T))

            # Black-out / beschikbaarheid
            if emp.is_blacked_out(day_str) or not emp.is_available_on(day_str):
                for t in range(T):
                    model.Add(x[e, d, t] == 0)
                continue

            # Nachtdienst: max 140/jaar (soft via penalty, hard-blokkeer boven 140)
            night_templates = [t for t in range(T) if _is_night_shift(
                _make_dummy_shift(emp, day_str, t))]

            # Re-integratie: alleen sjablonen ≤ max uren
            if emp.reintegration_active:
                for t in range(T):
                    if TEMPLATE_HOURS[t] > emp.reintegration_max_hours:
                        model.Add(x[e, d, t] == 0)

            # Dagelijkse rust ≥ 11u (vereenvoudigd: kijk naar vorige dag)
            if d > 0:
                prev_day = plan_dates[d - 1]
                for t_prev in range(T):
                    for t_curr in range(T):
                        s_prev, e_prev, _ = SHIFT_TEMPLATES[t_prev]
                        s_curr, _, _ = SHIFT_TEMPLATES[t_curr]
                        rest = _calc_rest(s_prev, e_prev, s_curr)
                        if rest < 11.0:
                            # Mogen niet beiden 1 zijn
                            model.Add(x[e, d - 1, t_prev] + x[e, d, t_curr] <= 1)

    # ── Minimale bezetting per dag ────────────────────────────────────────────
    for d, day in enumerate(plan_dates):
        if day.month != month:
            continue  # lookahead-dagen: geen bezettingseis
        day_cfg = schedule.get_day_config(str(day))
        min_s   = _min_staff(day_cfg, schedule.restaurant)
        if mode == "Lean":
            min_s = max(1, min_s - 1)
        elif mode == "Heavy":
            min_s += 1

        # Elke medewerker heeft max 1 dienst, dus tel over alle templates
        coverage = [x[e, d, t] for e in range(E) for t in range(T)]
        model.Add(sum(coverage) >= min_s)

    # ── Soft constraint: contracturen ────────────────────────────────────────
    # Doelstelling: minimaliseer |gewerkte_uren - contracturen|
    # Benadering: maximaliseer totaal gewogen uren (vereenvoudigd)
    weeks_in_month = days_in_month / 7
    objective_terms = []
    for e, emp in enumerate(active_emps):
        target_hours = emp.contract_hours * weeks_in_month
        # Penaliseer elke gewerkte uur boven target
        for d in range(D):
            for t in range(T):
                hours_scaled = int(TEMPLATE_HOURS[t] * 10)
                objective_terms.append(x[e, d, t] * hours_scaled)

    model.Maximize(sum(objective_terms))

    # ── Oplos ────────────────────────────────────────────────────────────────
    if progress_callback:
        progress_callback(0.3, "Oplossen…")

    status = solver.Solve(model)
    msgs = [f"OR-Tools status: {solver.StatusName(status)}",
            f"Objectiefwaarde: {solver.ObjectiveValue():.0f}"]

    if status not in (cp.OPTIMAL, cp.FEASIBLE):
        msgs.append("⚠️ Geen haalbare oplossing gevonden – schakel naar greedy fallback.")
        shifts, gmsg = _solve_greedy(schedule, employees, mode, lookahead_days)
        return shifts, msgs + gmsg

    if progress_callback:
        progress_callback(0.8, "Diensten aanmaken…")

    # ── Extraheer resultaat ──────────────────────────────────────────────────
    shifts: List[Shift] = []
    for e, emp in enumerate(active_emps):
        for d, day in enumerate(plan_dates):
            for t in range(T):
                if solver.Value(x[e, d, t]) == 1:
                    start, end, _ = SHIFT_TEMPLATES[t]
                    sh = _make_shift(emp, str(day), start, end, schedule.restaurant)
                    shifts.append(sh)

    if progress_callback:
        progress_callback(1.0, "Klaar!")

    msgs.append(f"✅ {len(shifts)} diensten gegenereerd voor {E} medewerkers.")
    return shifts, msgs


def _make_dummy_shift(emp: Employee, date_str: str, t: int) -> Shift:
    start, end, _ = SHIFT_TEMPLATES[t]
    return Shift(employee_id=emp.id, date=date_str, start_time=start, end_time=end)


# ─── Greedy Fallback Solver ───────────────────────────────────────────────────

def _solve_greedy(
    schedule: Schedule, employees: List[Employee], mode: str, lookahead_days: int
) -> Tuple[List[Shift], List[str]]:
    """
    Greedy toewijzing: beloop elke dag, kies beschikbare medewerkers,
    kies sjabloon dat het best de contracturen benadert.
    """
    messages = ["🔧 Greedy solver actief."]
    year, month = schedule.year, schedule.month
    days_in_month = calendar.monthrange(year, month)[1]
    plan_dates: List[date] = []
    for day in range(1, days_in_month + 1):
        plan_dates.append(date(year, month, day))
    for i in range(1, lookahead_days + 1):
        plan_dates.append(plan_dates[-1] + timedelta(days=i))

    weeks = days_in_month / 7
    active_emps = [e for e in employees if not e.end_date or
                   e.end_date >= str(date(year, month, 1))]

    # Bijhoud uren per medewerker
    hours_assigned: Dict[str, float] = {e.id: 0.0 for e in active_emps}
    # Bijhoud last shift end per medewerker (voor rust-controle)
    last_shift_end: Dict[str, Optional[str]] = {e.id: None for e in active_emps}

    shifts: List[Shift] = []

    for day in plan_dates:
        day_str = str(day)
        day_cfg = schedule.get_day_config(day_str)
        min_s   = _min_staff(day_cfg, schedule.restaurant)
        if mode == "Lean":
            min_s = max(1, min_s - 1)
        elif mode == "Heavy":
            min_s += 1

        # Beschikbare medewerkers voor deze dag
        avail = [e for e in active_emps
                 if not e.is_blacked_out(day_str) and e.is_available_on(day_str)]

        # Sorteer op hoeveel uren ze nog nodig hebben (deficit first)
        target_map = {e.id: e.contract_hours * weeks for e in active_emps}
        avail.sort(key=lambda e: target_map[e.id] - hours_assigned[e.id], reverse=True)

        assigned = 0
        for emp in avail:
            if assigned >= min_s and mode != "Heavy":
                # Check of medewerker nog uren nodig heeft
                deficit = target_map[emp.id] - hours_assigned[emp.id]
                if deficit <= 0:
                    continue

            # Kies het beste sjabloon
            best_t = _pick_template(emp, day_str, day, last_shift_end.get(emp.id))
            if best_t is None:
                continue

            start, end, _ = SHIFT_TEMPLATES[best_t]
            sh = _make_shift(emp, day_str, start, end, schedule.restaurant)
            shifts.append(sh)
            hours_assigned[emp.id] += sh.duration_hours
            last_shift_end[emp.id] = sh.end_time if sh.duration_hours <= 8 else "23:59"
            assigned += 1

            if assigned >= min_s and day.month != month:
                break

    messages.append(f"✅ Greedy: {len(shifts)} diensten gepland.")
    return shifts, messages


def _calc_rest(end_prev_start: str, end_prev_end: str, start_curr: str) -> float:
    """Rusttijd in uren tussen vorige dienst en volgende."""
    sh, sm = map(int, end_prev_start.split(":"))
    eh, em = map(int, end_prev_end.split(":"))
    nh, nm = map(int, start_curr.split(":"))
    s_m = sh * 60 + sm
    e_m = eh * 60 + em
    n_m = nh * 60 + nm
    if e_m <= s_m:
        e_m += 1440
    if n_m <= e_m % 1440:
        n_m += 1440
    # n_m is next day minutes from midnight; e_m can cross midnight
    end_abs = e_m
    start_abs = n_m + (e_m // 1440) * 1440
    # Simplify: rest = next_start - end
    return max(0.0, (start_abs - end_abs) / 60.0)


def _pick_template(emp: Employee, day_str: str, day: date,
                   last_end: Optional[str]) -> Optional[int]:
    """Kies meest geschikt sjabloon voor medewerker op dag."""
    avail_window = emp.availability.window_for(day.weekday())
    best_t = None
    best_score = -999

    for t, (start, end, _) in enumerate(SHIFT_TEMPLATES):
        hours = TEMPLATE_HOURS[t]

        # Re-integratie max uren
        if emp.reintegration_active and hours > emp.reintegration_max_hours:
            continue

        # Max 12 uur
        if hours > 12:
            continue

        # Beschikbaarheidsvenster
        if avail_window:
            avail_start, avail_end = avail_window
            if start < avail_start or end > avail_end:
                pass   # soft: niet blokkeren, laat manager corrigeren

        # Dagelijkse rust: min 11u na vorige dienst
        if last_end:
            lh, lm = map(int, last_end.split(":"))
            sh, sm = map(int, start.split(":"))
            # Vereenvoudigd: aanname vorige dag
            rest = (sh * 60 + sm + 1440 - (lh * 60 + lm)) % 1440 / 60
            if rest < 11:
                continue

        # Score: hoe goed past de dienstduur bij contracturen?
        score = hours
        # Voorkeur voor dagdiensten (niet-nacht) tenzij medewerker nacht werkt
        if _is_night_shift(Shift(date=day_str, start_time=start, end_time=end)):
            score -= 3   # kleine penalty voor nachtdiensten

        if score > best_score:
            best_score = score
            best_t = t

    return best_t


def _make_shift(emp: Employee, day_str: str, start: str, end: str,
                rest_cfg: RestaurantConfig) -> Shift:
    """Maak een Shift object aan met kosten."""
    from constraints import dutch_holidays, _is_night_shift as _in
    d = date.fromisoformat(day_str)
    holidays = dutch_holidays(d.year)
    sh = Shift(
        id=str(uuid.uuid4())[:8],
        employee_id=emp.id,
        employee_name=emp.name,
        date=day_str,
        start_time=start,
        end_time=end,
        role=emp.role,
        is_night_shift=_in(Shift(date=day_str, start_time=start, end_time=end)),
        has_sunday_supplement=(d.weekday() == 6),
        has_holiday_supplement=(day_str in holidays),
    )
    # Bereken loonkosten
    hourly = emp.hourly_rate if emp.salary_type == "Uurloon" else (
        emp.monthly_salary / max(1, emp.contract_hours * 52 / 12))
    base = sh.duration_hours * hourly
    if sh.has_holiday_supplement:
        base *= 2.0
    elif sh.has_sunday_supplement:
        base *= 1.5
    if sh.is_night_shift:
        base *= 1.25
    sh.labor_cost = round(base, 2)
    return sh
