# python-dateutil — Powerful Extensions to datetime

Implement `dateutil`, a Python library providing powerful extensions to the standard `datetime` module: natural language date parsing, ISO 8601 parsing, recurrence rules (RFC 5545), relative deltas, timezone handling, and Easter computation.

## Dependencies

- The environment is **offline** — every dependency is already installed and you must not install
  anything (there is no network).
- Runtime dependency: `six` (the standard Python 2/3 compatibility library) is available. Beyond
  that the library relies only on the Python standard library (`datetime`, `calendar`, etc.).
- The IANA timezone database (`/usr/share/zoneinfo`) is present, so name-based and TZif timezone
  resolution works.
- The project is installed by a `setup.sh` that runs **offline** in this environment — provide a
  standard Python build (e.g. a `pyproject.toml` / `setup.py` installable with
  `pip install -e . --no-build-isolation`).

## Package Structure

```python
from dateutil.parser import parse, parserinfo, isoparse, isoparser, ParserError
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
from dateutil.rrule import (rrule, rruleset, rrulestr,
    YEARLY, MONTHLY, WEEKLY, DAILY, HOURLY, MINUTELY, SECONDLY,
    MO, TU, WE, TH, FR, SA, SU)
from dateutil import tz
from dateutil.easter import easter, EASTER_WESTERN, EASTER_ORTHODOX, EASTER_JULIAN
from dateutil.utils import today, default_tzinfo, within_delta
```

`MO, TU, ...` are exported from both `relativedelta` and `rrule` modules (same `weekday` class).

## 1. Date Parsing

`parse(timestr, parserinfo=None, **kwargs)` — parses a wide variety of date/time string formats into a `datetime.datetime`, including `"Jan 1 2024"`, `"01/02/03"`, `"2024-03-15T09:45:30"`, `"12/25/2023 14:30"`, and `"Jan 1 2024 3:30 PM"`. Raises `ParserError` (subclass of `ValueError`) on strings with no recognizable date/time components (e.g. `"hello world"`). Key kwargs: `default` (datetime for missing components, defaults to today at midnight), `dayfirst`, `yearfirst`, `fuzzy`, `fuzzy_with_tokens` (returns `(datetime, tuple_of_skipped_tokens)`), `ignoretz`, `tzinfos` (dict `{name: offset_seconds}` or callable).

Ambiguity resolution for 3 numeric values: default M/D/Y; `dayfirst=True` → D/M/Y; `yearfirst=True` → Y/M/D; both → Y/D/M. Day clamping: default day exceeding target month's max clamps to month end.

`parserinfo` — subclass to override `MONTHS`, `WEEKDAYS`, and other parsing tables. `MONTHS` is a list of 12 `(abbr, full)` tuples. Month and weekday names are matched **case-insensitively** and matching is **Unicode-aware**: a word token is any maximal run of Unicode letters (not restricted to ASCII `A-Z`), so custom names containing accented or non-ASCII letters are recognized when they appear in the input string.

### ISO 8601

`isoparse(dt_str)` — parses ISO 8601 strings: `YYYY-MM-DD`, `YYYYMMDD`, `YYYY-MM`, week dates (`YYYY-Www-D`), ordinal dates (`YYYY-DDD`), with optional time and timezone (`Z`, `+HH:MM`). Supports `24:00:00` (midnight next day). Accepts both `str` and `bytes`.

`isoparser(sep=None)` — parser class with custom separator. Methods: `isoparse()`, `parse_isodate()` → `date`, `parse_isotime()` → `time` (timezone-aware if the input contains a UTC offset), `parse_tzstr(tzstr)` → `tzinfo`.

## 2. Recurrence Rules (RFC 5545)

Frequency constants: `YEARLY, MONTHLY, WEEKLY, DAILY, HOURLY, MINUTELY, SECONDLY`.

Weekday objects: `MO, TU, WE, TH, FR, SA, SU` — callable with ordinal: `FR(+1)` = first Friday, `FR(-1)` = last Friday. The `weekday` class has `.weekday` (0-6) and `.n`.

`rrule(freq, dtstart=None, interval=1, wkst=None, count=None, until=None, bysetpos=None, bymonth=None, bymonthday=None, byweekday=None, byhour=None, byminute=None, bysecond=None, byyearday=None, byweekno=None, cache=False)` — generates recurrence dates per RFC 5545. `bysetpos` selects position within the frequency period. Negative `bymonthday` counts from month end. Weekday ordinals only work with YEARLY and MONTHLY.

Query methods (available on both `rrule` and `rruleset` instances): iteration, `__getitem__` (indexing and slicing), `.count()`, `.before(dt, inc=False)`, `.after(dt, inc=False)`, `.between(after, before, inc=False)`. `str(rrule)` produces an RFC 5545 string representation parseable by `rrulestr`.

`rruleset` — combines rules: `.rrule(rule)`, `.rdate(dt)`, `.exrule(rule)`, `.exdate(dt)`. Inherits query methods. Its occurrences are the RFC 5545 recurrence set determined by the inclusion (`.rrule`/`.rdate`) and exclusion (`.exrule`/`.exdate`) contributions it was given.

`rrulestr(s, dtstart=None, ...)` — parses RFC 5545 text (RRULE, RDATE, EXRULE, EXDATE, DTSTART lines). Returns `rrule` or `rruleset`.

## 3. Relative Deltas

`relativedelta(dt1=None, dt2=None, years=0, months=0, days=0, weeks=0, hours=0, minutes=0, seconds=0, microseconds=0, year=None, month=None, day=None, weekday=None, hour=None, minute=None, second=None, microsecond=None)`

Two modes: diff mode (`relativedelta(dt1, dt2)` computes the signed difference such that `dt2 + delta == dt1`, with all components sharing a consistent sign direction — e.g. a backward diff yields all-negative components) and keyword mode (plural components ADD, singular components REPLACE). Supports addition and subtraction with `datetime` and `date` objects. Month-end clamping when adding months. Weekday shifting applied after all other arithmetic: `weekday=FR` finds next Friday (including today); `weekday=FR(-1)` finds previous Friday (including today); `weekday=MO(+2)` finds 2nd next Monday (including today as the 1st if today is Monday).

Supports `+`, `-`, `*` (scalar), negation, `abs()` (component-wise), `==`, `bool()` (false when empty), addition/subtraction between relativedeltas. `weeks` property maps to/from `days`.

## 4. Timezone Handling

`tz.tzutc()` — UTC. `tz.tzoffset(name, offset)` — fixed offset (seconds). `tz.tzlocal()` — system local timezone. `tz.tzstr(s)` — parses POSIX TZ strings (e.g. `"EST5EDT,M3.2.0/2,M11.1.0/2"`). `tz.tzfile(fileobj)` — reads TZif binary files; `fileobj` may be either a filesystem path/filename string (e.g. `tz.tzfile("/usr/share/zoneinfo/US/Eastern")`) or an open binary file object. `tz.gettz(name)` — resolves timezone by name (IANA, UTC/GMT, POSIX). `tz.UTC` — singleton.

DST edge cases: `tz.datetime_exists(dt)` (False during spring-forward gap), `tz.datetime_ambiguous(dt)` (True during fall-back overlap), `tz.resolve_imaginary(dt)`, `tz.enfold(dt, fold=1)` (returns a new datetime with the fold attribute set; fold=0 = first occurrence during overlap, fold=1 = second).

`resolve_imaginary(dt)` returns `dt` unchanged if it already exists; if `dt` falls in a spring-forward gap it shifts the wall-clock time FORWARD by the size of the gap (the difference between the post- and pre-transition UTC offsets), preserving the original minutes/seconds.

Equality: `tzutc() == tzoffset(None, 0)`.

## 5. Easter

`easter(year, method=EASTER_WESTERN)` → `datetime.date`. Constants: `EASTER_JULIAN=1`, `EASTER_ORTHODOX=2`, `EASTER_WESTERN=3`.

The three methods differ in which computus and calendar the returned date uses:

- `EASTER_WESTERN` — the Gregorian (Anonymous/Meeus) computus; the date most Western churches use.
- `EASTER_JULIAN` — the Julian computus, returned as the date **on the Julian calendar** with **no** Julian→Gregorian conversion (the Julian month/day placed directly into a `date`).
- `EASTER_ORTHODOX` — the **same** Julian computus as `EASTER_JULIAN`, but the result is converted to the (proleptic) Gregorian calendar by adding the century-dependent Julian/Gregorian day offset (13 days for years 1900–2099). It therefore lags `EASTER_JULIAN` by that offset.

## 6. Utilities

`today(tzinfo=None)` — current date at midnight. `default_tzinfo(dt, tzinfo)` — attach tzinfo to naive dt, leave aware unchanged. `within_delta(dt1, dt2, delta)` — True if `abs(dt1 - dt2) <= abs(delta)`.
