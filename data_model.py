"""
data_model.py – Datamodellen voor McDonald's Management Dashboard
CAO Horeca 2025-2026 / ATW-compliant roostersysteem
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime
from enum import Enum
import json
import uuid


# ─── Enumeraties ────────────────────────────────────────────────────────────────

class SalaryType(str, Enum):
    HOURLY  = "Uurloon"
    MONTHLY = "Vast maandloon"

class BusyLevel(str, Enum):
    QUIET    = "Rustig"
    NORMAL   = "Normaal"
    BUSY     = "Druk"
    VERY_BUSY = "Zeer druk"

class ShiftRole(str, Enum):
    CREW          = "Crew"
    CREW_TRAINER  = "Crew Trainer"
    SHIFT_MANAGER = "Shift Manager"
    MANAGER       = "Manager"
    DRIVE_THRU    = "Drive-Thru"
    KITCHEN       = "Keuken"
    COUNTER       = "Balie"

class LeaveType(str, Enum):
    SICK         = "Ziek"
    VACATION     = "Vakantie"
    SPECIAL      = "Bijzonder verlof"
    SWAP         = "Ruil"
    REINTEGRATION = "Re-integratie"


# ─── Hulp-dataklassen ───────────────────────────────────────────────────────────

@dataclass
class EmployeeAvailability:
    """Beschikbaarheid per weekdag (0=Ma … 6=Zo) + optionele tijdvensters."""
    days: Dict[int, bool] = field(
        default_factory=lambda: {i: True for i in range(7)}
    )
    # {"0": ["06:00", "22:00"], ...}
    windows: Dict[str, List[str]] = field(default_factory=dict)

    def is_available(self, weekday: int) -> bool:
        return self.days.get(weekday, True)

    def window_for(self, weekday: int):
        """Return (start, end) strings or None."""
        return self.windows.get(str(weekday))


@dataclass
class LeaveEntry:
    id: str          = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_date: str  = ""
    end_date: str    = ""
    leave_type: str  = LeaveType.VACATION.value
    approved: bool   = False
    notes: str       = ""


@dataclass
class SickEntry:
    id: str            = field(default_factory=lambda: str(uuid.uuid4())[:8])
    start_date: str    = ""
    end_date: str      = ""
    reason: str        = ""
    reintegration: bool = False


@dataclass
class Training:
    id: str              = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str            = ""
    date_completed: str  = ""
    expiry_date: str     = ""
    notes: str           = ""


# ─── Hoofdklassen ──────────────────────────────────────────────────────────────

@dataclass
class Employee:
    id: str           = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str         = ""
    contract_hours: float = 32.0          # uren per week
    salary_type: str  = SalaryType.HOURLY.value
    hourly_rate: float = 12.50            # €/uur
    monthly_salary: float = 0.0
    role: str         = ShiftRole.CREW.value
    availability: EmployeeAvailability = field(default_factory=EmployeeAvailability)
    blackout_dates: List[str] = field(default_factory=list)   # ["YYYY-MM-DD"]
    seniority_years: float = 0.0
    # Verlof
    vacation_days_total: float = 25.0
    vacation_days_used: float  = 0.0
    leave_log: List[LeaveEntry] = field(default_factory=list)
    sick_log:  List[SickEntry]  = field(default_factory=list)
    # Re-integratie
    reintegration_active: bool    = False
    reintegration_max_hours: float = 6.0
    reintegration_end_date: str   = ""
    # HR-gegevens
    start_date: str     = ""
    end_date: str       = ""
    date_of_birth: str  = ""
    email: str          = ""
    phone: str          = ""
    notes: str          = ""
    trainings: List[Training] = field(default_factory=list)
    # Jaarlijkse tellers
    night_shifts_ytd: int   = 0
    free_sundays_ytd: int   = 0
    total_hours_ytd: float  = 0.0

    @property
    def vacation_remaining(self) -> float:
        return self.vacation_days_total - self.vacation_days_used

    @property
    def effective_max_hours_per_day(self) -> float:
        return self.reintegration_max_hours if self.reintegration_active else 12.0

    def is_blacked_out(self, date_str: str) -> bool:
        if date_str in self.blackout_dates:
            return True
        for s in self.sick_log:
            end = s.end_date or s.start_date
            if s.start_date <= date_str <= end:
                return True
        for lv in self.leave_log:
            if not lv.approved:
                continue
            end = lv.end_date or lv.start_date
            if lv.start_date <= date_str <= end:
                return True
        return False

    def is_available_on(self, date_str: str) -> bool:
        if self.is_blacked_out(date_str):
            return False
        from datetime import date
        d = date.fromisoformat(date_str)
        return self.availability.is_available(d.weekday())


@dataclass
class Shift:
    id: str             = field(default_factory=lambda: str(uuid.uuid4())[:8])
    employee_id: str    = ""
    employee_name: str  = ""
    date: str           = ""          # "YYYY-MM-DD"
    start_time: str     = "09:00"
    end_time: str       = "17:00"
    role: str           = ShiftRole.CREW.value
    break_minutes: int  = 30          # manager stelt handmatig in
    notes: str          = ""
    is_night_shift: bool        = False
    has_sunday_supplement: bool = False
    has_holiday_supplement: bool = False
    labor_cost: float   = 0.0

    @property
    def duration_hours(self) -> float:
        """Bruto dienstduur in uren (inclusief pauze)."""
        try:
            sh, sm = map(int, self.start_time.split(":"))
            eh, em = map(int, self.end_time.split(":"))
            start_m = sh * 60 + sm
            end_m   = eh * 60 + em
            if end_m <= start_m:          # kruist middernacht
                end_m += 24 * 60
            return (end_m - start_m) / 60.0
        except Exception:
            return 0.0

    @property
    def net_hours(self) -> float:
        """Netto betaalde uren (bruto minus onbetaalde pauze — per CAO doorgaans betaald)."""
        return self.duration_hours   # pauzes zijn per CAO betaald

    def end_datetime(self):
        from datetime import date, timedelta
        d = date.fromisoformat(self.date)
        sh, sm = map(int, self.start_time.split(":"))
        eh, em = map(int, self.end_time.split(":"))
        start_m = sh * 60 + sm
        end_m   = eh * 60 + em
        if end_m <= start_m:
            end_m += 24 * 60
        extra_days = end_m // (24 * 60)
        final_m    = end_m % (24 * 60)
        end_date   = d + timedelta(days=extra_days)
        return datetime(end_date.year, end_date.month, end_date.day,
                        final_m // 60, final_m % 60)

    def start_datetime(self):
        d = __import__("datetime").date.fromisoformat(self.date)
        sh, sm = map(int, self.start_time.split(":"))
        return datetime(d.year, d.month, d.day, sh, sm)


@dataclass
class DayConfig:
    date: str              = ""
    busy_level: str        = BusyLevel.NORMAL.value
    notes: str             = ""
    min_staff_override: Optional[int] = None
    is_holiday: bool       = False
    holiday_name: str      = ""


@dataclass
class RestaurantConfig:
    name: str              = "McDonald's"
    location: str          = ""
    open_time: str         = "06:00"
    close_time: str        = "23:00"
    drive_thru_enabled: bool = True
    drive_thru_open: str   = "06:00"
    drive_thru_close: str  = "01:00"
    min_crew_quiet: int    = 2
    min_crew_normal: int   = 3
    min_crew_busy: int     = 5
    min_crew_very_busy: int = 8
    sunday_supplement_pct: float  = 50.0
    holiday_supplement_pct: float = 100.0
    night_supplement_pct: float   = 25.0   # na 20:00

    def min_crew_for_level(self, level: str) -> int:
        mapping = {
            BusyLevel.QUIET.value:    self.min_crew_quiet,
            BusyLevel.NORMAL.value:   self.min_crew_normal,
            BusyLevel.BUSY.value:     self.min_crew_busy,
            BusyLevel.VERY_BUSY.value: self.min_crew_very_busy,
        }
        return mapping.get(level, self.min_crew_normal)


@dataclass
class Schedule:
    id: str          = field(default_factory=lambda: str(uuid.uuid4())[:8])
    month: int       = 1
    year: int        = 2025
    restaurant: RestaurantConfig = field(default_factory=RestaurantConfig)
    shifts: List[Shift]         = field(default_factory=list)
    day_configs: List[DayConfig] = field(default_factory=list)
    labor_budget: float = 0.0
    version: int        = 1
    created_at: str     = field(default_factory=lambda: datetime.now().isoformat())
    last_modified: str  = field(default_factory=lambda: datetime.now().isoformat())

    def get_day_config(self, date_str: str) -> DayConfig:
        for dc in self.day_configs:
            if dc.date == date_str:
                return dc
        return DayConfig(date=date_str)

    def get_shifts_for_date(self, date_str: str) -> List[Shift]:
        return [s for s in self.shifts if s.date == date_str]

    def get_shifts_for_employee(self, emp_id: str) -> List[Shift]:
        return [s for s in self.shifts if s.employee_id == emp_id]

    def touch(self):
        self.last_modified = datetime.now().isoformat()
        self.version += 1


@dataclass
class AppState:
    employees: List[Employee]          = field(default_factory=list)
    current_schedule: Optional[Schedule] = None
    restaurant: RestaurantConfig       = field(default_factory=RestaurantConfig)
    schedule_history: List[dict]       = field(default_factory=list)   # geserialiseerde snapshots

    def get_employee(self, emp_id: str) -> Optional[Employee]:
        return next((e for e in self.employees if e.id == emp_id), None)

    def snapshot(self):
        """Sla huidige rooster op in history (voor undo)."""
        if self.current_schedule:
            snap = json.dumps(asdict(self.current_schedule), default=str)
            self.schedule_history.append(snap)
            if len(self.schedule_history) > 20:
                self.schedule_history.pop(0)

    def undo(self) -> bool:
        if not self.schedule_history:
            return False
        snap = json.loads(self.schedule_history.pop())
        self.current_schedule = _schedule_from_dict(snap)
        return True

    def to_dict(self) -> dict:
        return json.loads(json.dumps(asdict(self), default=str))

    @classmethod
    def from_dict(cls, data: dict) -> "AppState":
        state = cls()
        if "restaurant" in data and data["restaurant"]:
            state.restaurant = _restaurant_from_dict(data["restaurant"])
        if "employees" in data:
            state.employees = [_employee_from_dict(ed) for ed in data["employees"]]
        if "current_schedule" in data and data["current_schedule"]:
            state.current_schedule = _schedule_from_dict(data["current_schedule"])
        state.schedule_history = data.get("schedule_history", [])
        return state


# ─── Deserialise-hulpfuncties ──────────────────────────────────────────────────

def _safe_init(cls, data: dict):
    valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
    return cls(**valid)


def _restaurant_from_dict(d: dict) -> RestaurantConfig:
    return _safe_init(RestaurantConfig, d)


def _employee_from_dict(d: dict) -> Employee:
    emp = _safe_init(Employee, {k: v for k, v in d.items()
                                if k not in ("availability", "leave_log", "sick_log", "trainings")})
    if "availability" in d and d["availability"]:
        av = d["availability"]
        emp.availability = EmployeeAvailability(
            days={int(k): v for k, v in av.get("days", {}).items()},
            windows=av.get("windows", {}),
        )
    emp.leave_log = [_safe_init(LeaveEntry, lv) for lv in d.get("leave_log", [])]
    emp.sick_log  = [_safe_init(SickEntry,  sk) for sk in d.get("sick_log",  [])]
    emp.trainings = [_safe_init(Training,   tr) for tr in d.get("trainings", [])]
    return emp


def _shift_from_dict(d: dict) -> Shift:
    return _safe_init(Shift, d)


def _schedule_from_dict(d: dict) -> Schedule:
    sched = _safe_init(Schedule, {k: v for k, v in d.items()
                                  if k not in ("restaurant", "shifts", "day_configs")})
    if "restaurant" in d and d["restaurant"]:
        sched.restaurant = _restaurant_from_dict(d["restaurant"])
    sched.shifts     = [_shift_from_dict(sh)   for sh in d.get("shifts",      [])]
    sched.day_configs = [_safe_init(DayConfig, dc) for dc in d.get("day_configs", [])]
    return sched
