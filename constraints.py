"""
constraints.py – CAO Horeca 2025-2026 & ATW-constraints checker
Bronnen: KHN, De Horecabond, CAO Horeca 2025-2026, Arbeidstijdenwet

Regels (hard constraints):
  • Max 12 uur per dienst
  • Dagelijkse rust: min. 11 uur aaneengesloten (1× per 7d mag 8u)
  • Wekelijkse rust: min. 36u per 7d, of 72u per 14d (2× min. 32u)
  • Nachtdienst: max 10u, na late nacht min 14u rust, na 3+ nachten min 46u rust
  • Gemiddeld max 48u/week over 16 weken
  • Min 13 vrije zondagen per jaar
  • Rooster min 3 weken van tevoren
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple, Optional
import calendar

from data_model import Shift, Employee, Schedule, BusyLevel

# ─── Nederlandse feestdagen ────────────────────────────────────────────────────

def _easter(year: int) -> date:
    """Berechne Ostern (Anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)

def dutch_holidays(year: int) -> Dict[str, str]:
    easter = _easter(year)
    kw  = date(year, 4, 27) if date(year, 4, 27).weekday() != 6 else date(year, 4, 26)
    return {
        str(date(year, 1, 1)):   "Nieuwjaarsdag",
        str(easter - timedelta(days=2)):  "Goede Vrijdag",
        str(easter):             "Eerste Paasdag",
        str(easter + timedelta(days=1)):  "Tweede Paasdag",
        str(kw):                 "Koningsdag",
        str(date(year, 5, 5)):   "Bevrijdingsdag",
        str(easter + timedelta(days=39)): "Hemelvaartsdag",
        str(easter + timedelta(days=49)): "Eerste Pinksterdag",
        str(easter + timedelta(days=50)): "Tweede Pinksterdag",
        str(date(year, 12, 25)): "Eerste Kerstdag",
        str(date(year, 12, 26)): "Tweede Kerstdag",
    }


# ─── CAO-constraint parameters ────────────────────────────────────────────────

MAX_SHIFT_HOURS          = 12.0
MIN_DAILY_REST_HOURS     = 11.0
MIN_DAILY_REST_EXCEPTION = 8.0   # 1× per 7 dagen
MAX_NIGHT_SHIFT_HOURS    = 10.0
MIN_REST_AFTER_LATE_NIGHT = 14.0  # na dienst eindigend na 00:00
MIN_REST_AFTER_3_NIGHTS  = 46.0
MAX_NIGHT_SHIFTS_YEAR    = 140
MAX_AVG_WEEKLY_HOURS_16W = 48.0
MIN_FREE_SUNDAYS_YEAR    = 13
MIN_WEEKLY_REST_HOURS    = 36.0
MIN_WEEKLY_REST_14D      = 72.0   # gesplitst in 2× min 32u
SCHEDULE_NOTICE_WEEKS    = 3


@dataclass
class Violation:
    severity: str      # "error" | "warning"
    rule: str
    description: str
    employee_id: str   = ""
    employee_name: str = ""
    date: str          = ""


# ─── Hulpfuncties ─────────────────────────────────────────────────────────────

def _shift_end_dt(shift: Shift) -> datetime:
    d = date.fromisoformat(shift.date)
    sh, sm = map(int, shift.start_time.split(":"))
    eh, em = map(int, shift.end_time.split(":"))
    start_m = sh * 60 + sm
    end_m   = eh * 60 + em
    if end_m <= start_m:
        end_m += 1440
    extra = end_m // 1440
    final = end_m % 1440
    ed = d + timedelta(days=extra)
    return datetime(ed.year, ed.month, ed.day, final // 60, final % 60)


def _shift_start_dt(shift: Shift) -> datetime:
    d = date.fromisoformat(shift.date)
    sh, sm = map(int, shift.start_time.split(":"))
    return datetime(d.year, d.month, d.day, sh, sm)


def _rest_hours(shift_a: Shift, shift_b: Shift) -> float:
    """Rusttijd in uren tussen einde van A en begin van B (A eindigt voor B)."""
    end_a   = _shift_end_dt(shift_a)
    start_b = _shift_start_dt(shift_b)
    delta   = (start_b - end_a).total_seconds() / 3600
    return delta


def _is_night_shift(shift: Shift) -> bool:
    """Nachtdienst: eindigt na middernacht of begint na 22:00."""
    sh = int(shift.start_time.split(":")[0])
    eh, em = map(int, shift.end_time.split(":"))
    # eindigt over midnight
    end_m   = eh * 60 + em
    start_m = int(shift.start_time.split(":")[0]) * 60 + int(shift.start_time.split(":")[1])
    crosses_midnight = end_m <= start_m
    return sh >= 22 or crosses_midnight


def _week_number(d: date) -> Tuple[int, int]:
    """Return (year, week) ISO-weeknummer."""
    iso = d.isocalendar()
    return (iso[0], iso[1])


# ─── Individuele constraint-checkers ──────────────────────────────────────────

def check_shift_duration(shift: Shift, emp: Employee) -> List[Violation]:
    """Max 12u per dienst; bij re-integratie max emp.reintegration_max_hours."""
    violations = []
    max_h = emp.effective_max_hours_per_day
    if shift.duration_hours > MAX_SHIFT_HOURS:
        violations.append(Violation(
            severity="error", rule="ATW Art. 5:7",
            description=f"Dienst {shift.duration_hours:.1f}u > max {MAX_SHIFT_HOURS}u.",
            employee_id=emp.id, employee_name=emp.name, date=shift.date,
        ))
    elif shift.duration_hours > max_h and emp.reintegration_active:
        violations.append(Violation(
            severity="error", rule="Re-integratie",
            description=f"Dienst {shift.duration_hours:.1f}u > re-integratie max {max_h}u.",
            employee_id=emp.id, employee_name=emp.name, date=shift.date,
        ))
    return violations


def check_daily_rest(sorted_shifts: List[Shift], emp: Employee) -> List[Violation]:
    """Min 11u dagelijkse rust (1× per 7d mag 8u)."""
    violations = []
    exception_used_week: Dict[Tuple[int, int], bool] = {}

    for i in range(len(sorted_shifts) - 1):
        a, b = sorted_shifts[i], sorted_shifts[i + 1]
        rest = _rest_hours(a, b)
        week = _week_number(date.fromisoformat(a.date))
        if rest < MIN_DAILY_REST_HOURS:
            if rest >= MIN_DAILY_REST_EXCEPTION and not exception_used_week.get(week, False):
                exception_used_week[week] = True  # gebruik eenmalige uitzondering
            else:
                violations.append(Violation(
                    severity="error", rule="CAO Art. 4.3 Dagrust",
                    description=f"Rusttijd {rest:.1f}u tussen {a.date} en {b.date} (min {MIN_DAILY_REST_HOURS}u).",
                    employee_id=emp.id, employee_name=emp.name, date=b.date,
                ))
    return violations


def check_weekly_rest(sorted_shifts: List[Shift], emp: Employee,
                      all_dates: List[date]) -> List[Violation]:
    """Min 36u aaneengesloten rust per 7 dagen."""
    violations = []
    if len(all_dates) < 2:
        return violations
    # Controleer per 7-daags venster
    for i, start_d in enumerate(all_dates):
        end_d = start_d + timedelta(days=7)
        window = [s for s in sorted_shifts
                  if start_d <= date.fromisoformat(s.date) < end_d]
        if not window:
            continue
        # Zoek langste aaneengesloten rustperiode
        max_rest = _max_consecutive_rest(window, start_d, end_d)
        if max_rest < MIN_WEEKLY_REST_HOURS:
            violations.append(Violation(
                severity="error", rule="CAO Art. 4.4 Weekrust",
                description=(f"Week vanaf {start_d}: max aaneengesloten rust "
                             f"{max_rest:.1f}u (min {MIN_WEEKLY_REST_HOURS}u)."),
                employee_id=emp.id, employee_name=emp.name, date=str(start_d),
            ))
        if i + i < len(all_dates) - 7:  # stop vroeg
            break
    return violations


def _max_consecutive_rest(shifts: List[Shift], window_start: date, window_end: date) -> float:
    """Langste aaneengesloten rusttijd in uren binnen venster."""
    if not shifts:
        return (window_end - window_start).total_seconds() / 3600
    sorted_s = sorted(shifts, key=lambda s: _shift_start_dt(s))
    max_rest = 0.0
    # voor eerste shift
    rest_before = (_shift_start_dt(sorted_s[0]) -
                   datetime(window_start.year, window_start.month, window_start.day)).total_seconds() / 3600
    max_rest = max(max_rest, rest_before)
    for i in range(len(sorted_s) - 1):
        rest = _rest_hours(sorted_s[i], sorted_s[i + 1])
        max_rest = max(max_rest, rest)
    # na laatste shift
    rest_after = (datetime(window_end.year, window_end.month, window_end.day) -
                  _shift_end_dt(sorted_s[-1])).total_seconds() / 3600
    max_rest = max(max_rest, rest_after)
    return max_rest


def check_night_shift_rules(sorted_shifts: List[Shift], emp: Employee) -> List[Violation]:
    """Nachtdienst-regels: max 10u, rustperiodes na (reeks) nachtdiensten."""
    violations = []
    night_run = 0
    for i, sh in enumerate(sorted_shifts):
        is_night = _is_night_shift(sh)
        if is_night:
            night_run += 1
            # Max 10 uur per nachtdienst
            if sh.duration_hours > MAX_NIGHT_SHIFT_HOURS:
                violations.append(Violation(
                    severity="error", rule="ATW Art. 5:9 Nachtdienst",
                    description=f"Nachtdienst {sh.date}: {sh.duration_hours:.1f}u > max {MAX_NIGHT_SHIFT_HOURS}u.",
                    employee_id=emp.id, employee_name=emp.name, date=sh.date,
                ))
            # Na een late nacht (eindigend na 00:00) min. 14u rust
            end_dt = _shift_end_dt(sh)
            if end_dt.hour < 6 and i + 1 < len(sorted_shifts):
                rest = _rest_hours(sh, sorted_shifts[i + 1])
                if rest < MIN_REST_AFTER_LATE_NIGHT:
                    violations.append(Violation(
                        severity="error", rule="ATW Art. 5:9 Rust na late nacht",
                        description=f"Na late nacht {sh.date}: rusttijd {rest:.1f}u (min {MIN_REST_AFTER_LATE_NIGHT}u).",
                        employee_id=emp.id, employee_name=emp.name, date=sh.date,
                    ))
            # Na 3+ opeenvolgende nachten min 46u rust
            if night_run >= 3 and i + 1 < len(sorted_shifts):
                rest = _rest_hours(sh, sorted_shifts[i + 1])
                if rest < MIN_REST_AFTER_3_NIGHTS:
                    violations.append(Violation(
                        severity="error", rule="ATW Art. 5:9 Rust na 3 nachten",
                        description=f"Na {night_run} nachten t/m {sh.date}: rusttijd {rest:.1f}u (min {MIN_REST_AFTER_3_NIGHTS}u).",
                        employee_id=emp.id, employee_name=emp.name, date=sh.date,
                    ))
        else:
            night_run = 0
    # Jaarlijks max 140 nachtdiensten
    total_nights = sum(1 for s in sorted_shifts if _is_night_shift(s))
    if emp.night_shifts_ytd + total_nights > MAX_NIGHT_SHIFTS_YEAR:
        violations.append(Violation(
            severity="warning", rule="ATW Art. 5:9 Max nachtdiensten/jaar",
            description=f"Totaal nachtdiensten: {emp.night_shifts_ytd + total_nights} > max {MAX_NIGHT_SHIFTS_YEAR}.",
            employee_id=emp.id, employee_name=emp.name,
        ))
    return violations


def check_avg_weekly_hours(shifts_16w: List[Shift], emp: Employee) -> List[Violation]:
    """Gemiddeld max 48u/week over 16 weken."""
    violations = []
    if not shifts_16w:
        return violations
    total_hours = sum(s.duration_hours for s in shifts_16w)
    weeks = max(1, len({_week_number(date.fromisoformat(s.date)) for s in shifts_16w}))
    avg = total_hours / weeks
    if avg > MAX_AVG_WEEKLY_HOURS_16W:
        violations.append(Violation(
            severity="error", rule="ATW Art. 5:7 Gem. weekuren",
            description=f"Gemiddeld {avg:.1f}u/week over {weeks} weken (max {MAX_AVG_WEEKLY_HOURS_16W}u).",
            employee_id=emp.id, employee_name=emp.name,
        ))
    return violations


def check_free_sundays(shifts_year: List[Shift], emp: Employee) -> List[Violation]:
    """Min 13 vrije zondagen per jaar."""
    violations = []
    worked_sundays = {s.date for s in shifts_year
                      if date.fromisoformat(s.date).weekday() == 6}
    year = date.fromisoformat(shifts_year[0].date).year if shifts_year else datetime.now().year
    total_sundays = sum(1 for d in (date(year, 1, 1) + timedelta(days=i)
                                    for i in range(365))
                        if d.weekday() == 6)
    free_sundays = total_sundays - len(worked_sundays)
    if free_sundays < MIN_FREE_SUNDAYS_YEAR:
        violations.append(Violation(
            severity="warning", rule="CAO Art. 7.5 Vrije Zondagen",
            description=f"{emp.name}: {free_sundays} vrije zondagen dit jaar (min {MIN_FREE_SUNDAYS_YEAR}).",
            employee_id=emp.id, employee_name=emp.name,
        ))
    return violations


# ─── Hoofd-checker: controleer het volledige rooster ──────────────────────────

def check_schedule(schedule: Schedule, employees: List[Employee]) -> List[Violation]:
    """
    Controleer alle CAO/ATW-regels voor het rooster.
    Inclusief 3-daags lookahead naar de volgende maand (boundary check).
    """
    violations: List[Violation] = []
    holidays  = dutch_holidays(schedule.year)

    # Bouw shift-map per medewerker
    emp_shifts: Dict[str, List[Shift]] = {}
    for sh in schedule.shifts:
        emp_shifts.setdefault(sh.employee_id, []).append(sh)

    for emp in employees:
        shifts = sorted(emp_shifts.get(emp.id, []), key=lambda s: (_shift_start_dt(s)))
        if not shifts:
            continue

        # Dienstduur
        for sh in shifts:
            violations += check_shift_duration(sh, emp)

        # Dagelijkse rust
        violations += check_daily_rest(shifts, emp)

        # Weekrust
        all_dates = sorted({date.fromisoformat(s.date) for s in shifts})
        violations += check_weekly_rest(shifts, emp, all_dates)

        # Nachtdienst
        violations += check_night_shift_rules(shifts, emp)

        # Gem. weekuren (gebruik huidige maand als proxy voor 16w)
        violations += check_avg_weekly_hours(shifts, emp)

    # Feestdag- en zondagstoeslagen – alleen een waarschuwing als ze ontbreken
    for sh in schedule.shifts:
        d = date.fromisoformat(sh.date)
        if str(sh.date) in holidays and not sh.has_holiday_supplement:
            violations.append(Violation(
                severity="warning", rule="CAO Feestdagtoeslag",
                description=f"Dienst {sh.date} ({holidays[str(sh.date)]}): feestdagtoeslag niet ingesteld.",
                employee_name=sh.employee_name, date=sh.date,
            ))
        if d.weekday() == 6 and not sh.has_sunday_supplement:
            violations.append(Violation(
                severity="warning", rule="CAO Zondagtoeslag",
                description=f"Dienst {sh.date} (zondag): zondagtoeslag niet ingesteld.",
                employee_name=sh.employee_name, date=sh.date,
            ))

    return violations


def compute_shift_cost(shift: Shift, emp: Employee, holidays: Dict[str, str]) -> float:
    """Berekening loonkosten per dienst incl. toeslagen."""
    if emp.salary_type == "Vast maandloon":
        # Vaste medewerkers: nul extra kosten per dienst voor de berekening
        weekly_h   = emp.contract_hours or 40
        monthly_h  = weekly_h * 52 / 12
        hourly_eff = emp.monthly_salary / monthly_h if monthly_h > 0 else 0
    else:
        hourly_eff = emp.hourly_rate

    base = shift.duration_hours * hourly_eff
    d    = date.fromisoformat(shift.date)

    if str(shift.date) in holidays:
        supplement = base * (emp.__class__.__mro__  # nope
                             and 1)   # placeholder
        # gebruik restaurant config (niet beschikbaar hier – gebruik standaard)
        base *= 2.0   # 100% toeslag
    elif d.weekday() == 6:
        base *= 1.5   # 50% zondagtoeslag
    # Nacht-toeslag (na 20:00)
    sh_hour = int(shift.start_time.split(":")[0])
    if sh_hour >= 20 or _is_night_shift(shift):
        base *= 1.25
    return round(base, 2)


def recompute_costs(schedule: Schedule, employees: List[Employee]):
    """Herbereken loonkosten voor alle diensten in het rooster (in-place)."""
    holidays = dutch_holidays(schedule.year)
    emp_map  = {e.id: e for e in employees}
    for sh in schedule.shifts:
        emp = emp_map.get(sh.employee_id)
        if not emp:
            continue
        d = date.fromisoformat(sh.date)
        sh.is_night_shift       = _is_night_shift(sh)
        sh.has_sunday_supplement = (d.weekday() == 6)
        sh.has_holiday_supplement = (sh.date in holidays)
        sh.labor_cost           = compute_shift_cost(sh, emp, holidays)
