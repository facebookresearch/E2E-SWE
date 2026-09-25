"""Integration tests for python-dateutil — powerful extensions to the standard datetime module."""

import datetime
import calendar

from dateutil.parser import parse, parserinfo, isoparse, ParserError
from dateutil.parser import isoparser
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU
from dateutil.rrule import (
    rrule, rruleset, rrulestr,
    YEARLY, MONTHLY, WEEKLY, DAILY, HOURLY, MINUTELY, SECONDLY,
    MO as RR_MO, TU as RR_TU, WE as RR_WE, TH as RR_TH,
    FR as RR_FR, SA as RR_SA, SU as RR_SU,
)
from dateutil import tz
from dateutil.easter import easter, EASTER_WESTERN, EASTER_ORTHODOX, EASTER_JULIAN
from dateutil.utils import today, default_tzinfo, within_delta


# ---------------------------------------------------------------------------
# Parser — bundled core tests
# ---------------------------------------------------------------------------

class TestParserCore:
    """Bundled tests for parser: ambiguity, defaults, clamping, parserinfo,
    timezone, ignoretz, tzinfos."""

    def test_parser_core(self):
        """Ambiguous date resolution, default filling, day clamping, custom
        parserinfo, timezone-aware parsing, ignoretz, and tzinfos mapping."""
        # Default M/D/Y
        dt = parse("01/02/03")
        assert dt.month == 1 and dt.day == 2

        # dayfirst -> D/M/Y
        dt = parse("01/02/03", dayfirst=True)
        assert dt.day == 1 and dt.month == 2

        # yearfirst -> Y/M/D
        dt = parse("01/02/03", yearfirst=True)
        assert dt.year == 2001 and dt.month == 2 and dt.day == 3

        # Both -> Y/D/M
        dt = parse("01/02/03", yearfirst=True, dayfirst=True)
        assert dt.year == 2001 and dt.day == 2 and dt.month == 3

        # Default fills missing components
        default = datetime.datetime(2020, 6, 15, 12, 0, 0)
        dt = parse("March", default=default)
        assert dt == datetime.datetime(2020, 3, 15, 12, 0, 0)

        # Day clamping: Jan 31 default + "February 2023" -> Feb 28
        default = datetime.datetime(2023, 1, 31)
        dt = parse("February 2023", default=default)
        assert dt.month == 2 and dt.day == 28

        # Day clamping in leap year: Jan 31 default + "February 2024" -> Feb 29
        default = datetime.datetime(2024, 1, 31)
        dt = parse("February 2024", default=default)
        assert dt.month == 2 and dt.day == 29

        # Custom parserinfo with German month names
        class GermanParserInfo(parserinfo):
            MONTHS = [
                ("Jan", "Januar"), ("Feb", "Februar"), ("Mär", "März"),
                ("Apr", "April"), ("Mai", "Mai"), ("Jun", "Juni"),
                ("Jul", "Juli"), ("Aug", "August"), ("Sep", "September"),
                ("Okt", "Oktober"), ("Nov", "November"), ("Dez", "Dezember"),
            ]
        dt = parse("15 März 2024", parserinfo=GermanParserInfo())
        assert dt == datetime.datetime(2024, 3, 15)
        dt = parse("1 Oktober 2023", parserinfo=GermanParserInfo())
        assert dt == datetime.datetime(2023, 10, 1)

        # Timezone-aware parsing
        dt = parse("2024-01-15 10:30:00 UTC")
        assert dt.tzinfo is not None
        assert dt.utcoffset() == datetime.timedelta(0)

        dt = parse("2024-01-15 10:30:00 +05:30")
        assert dt.utcoffset() == datetime.timedelta(hours=5, minutes=30)

        # ignoretz strips timezone
        dt = parse("2024-01-15 10:30:00 UTC", ignoretz=True)
        assert dt.tzinfo is None

        # tzinfos dict for custom timezone abbreviations
        tzinfos = {"CST": -6 * 3600, "CDT": -5 * 3600}
        dt = parse("2024-07-15 10:30:00 CDT", tzinfos=tzinfos)
        assert dt.utcoffset() == datetime.timedelta(hours=-5)
        dt = parse("2024-01-15 10:30:00 CST", tzinfos=tzinfos)
        assert dt.utcoffset() == datetime.timedelta(hours=-6)


# ---------------------------------------------------------------------------
# Parser — fuzzy, formats, errors
# ---------------------------------------------------------------------------

class TestParserFuzzy:
    """Tests for fuzzy parsing, format handling, and error reporting."""

    def test_parser_fuzzy_formats_errors(self):
        """Fuzzy parsing extracts dates from prose, fuzzy_with_tokens returns
        non-date fragments, various string formats, and ParserError on failure."""
        dt = parse("The date is January 15, 2024", fuzzy=True)
        assert dt == datetime.datetime(2024, 1, 15)

        dt, tokens = parse("We met on January 15, 2024 for lunch",
                           fuzzy_with_tokens=True)
        assert dt == datetime.datetime(2024, 1, 15)
        assert isinstance(tokens, tuple)
        joined = " ".join(tokens)
        assert "We met on" in joined or "met" in joined
        assert "lunch" in joined or "for lunch" in joined

        # Various formats
        assert parse("15 January 2024") == datetime.datetime(2024, 1, 15)

        dt = parse("12/25/2023 14:30")
        assert dt.month == 12 and dt.day == 25 and dt.hour == 14 and dt.minute == 30

        dt = parse("2024-03-15T09:45:30")
        assert dt == datetime.datetime(2024, 3, 15, 9, 45, 30)

        dt = parse("Jan 1 2024 3:30 PM")
        assert dt.hour == 15 and dt.minute == 30

        # ParserError on garbage
        import pytest
        with pytest.raises((ParserError, ValueError)):
            parse("this is not a date at all xyz")


# ---------------------------------------------------------------------------
# ISO parser
# ---------------------------------------------------------------------------

class TestISOParser:
    """Tests for ISO 8601 date/time parsing — all formats and class methods."""

    def test_isoparse_all_formats_and_class(self):
        """Parse ISO 8601 in all formats: standard, compact, year-month, week
        dates, ordinal, midnight 24:00, UTC Z, offsets, sub-seconds, bytes.
        isoparser with custom separator, parse_isodate, parse_isotime, parse_tzstr."""
        # Full datetime with offset
        dt = isoparse("2024-01-15T10:30:45+05:00")
        assert dt == datetime.datetime(2024, 1, 15, 10, 30, 45,
                                       tzinfo=tz.tzoffset(None, 18000))

        # Standard date
        assert isoparse("2024-03-15").date() == datetime.date(2024, 3, 15)
        # Compact date
        assert isoparse("20240315").date() == datetime.date(2024, 3, 15)
        # Year-month
        assert isoparse("2024-03").date() == datetime.date(2024, 3, 1)
        # Week date (exact date: ISO week 3, Wednesday = Jan 17)
        dt = isoparse("2024-W03-3")
        assert dt.date() == datetime.date(2024, 1, 17)
        # Ordinal date (day 32 = Feb 1)
        assert isoparse("2024-032").date() == datetime.date(2024, 2, 1)

        # Midnight 24:00 = next day 00:00
        assert isoparse("2024-01-15T24:00:00") == datetime.datetime(2024, 1, 16, 0, 0, 0)

        # UTC Z
        dt = isoparse("2024-01-15T10:30:00Z")
        assert dt.utcoffset() == datetime.timedelta(0)

        # Sub-seconds
        assert isoparse("2024-01-15T10:30:45.123456").microsecond == 123456

        # Bytes input
        dt = isoparse(b"2024-01-15T10:30:00")
        assert dt == datetime.datetime(2024, 1, 15, 10, 30, 0)

        # isoparser class methods
        p = isoparser(sep=" ")
        dt = p.isoparse("2024-01-15 10:30:00")
        assert dt == datetime.datetime(2024, 1, 15, 10, 30, 0)

        p = isoparser()
        assert p.parse_isodate("2024-03-15") == datetime.date(2024, 3, 15)
        assert p.parse_isodate("20240315") == datetime.date(2024, 3, 15)

        t = p.parse_isotime("14:30:00+02:00")
        assert t.hour == 14 and t.minute == 30
        assert t.utcoffset() == datetime.timedelta(hours=2)

        assert p.parse_tzstr("Z").utcoffset(None) == datetime.timedelta(0)
        assert p.parse_tzstr("+05:30").utcoffset(None) == datetime.timedelta(hours=5, minutes=30)
        assert p.parse_tzstr("-08:00").utcoffset(None) == datetime.timedelta(hours=-8)


# ---------------------------------------------------------------------------
# rrule — bundled basic tests
# ---------------------------------------------------------------------------

class TestRRuleBasics:
    """Bundled tests for basic rrule patterns, query methods, and sub-day."""

    def test_rrule_basics_and_query(self):
        """MONTHLY on 31st skips short months, negative bymonthday, weekly
        byweekday, yearly/daily/interval patterns, query methods (before,
        after, between, count, indexing), and sub-day frequencies."""
        # Monthly on 31st skips short months
        r = rrule(MONTHLY, count=7, dtstart=datetime.datetime(2024, 1, 31))
        months = [d.month for d in list(r)]
        for m in months:
            assert calendar.monthrange(2024 if m >= 1 else 2025, m)[1] == 31

        # Negative bymonthday: -1 = last day of month (leap-year aware Feb 29)
        r = rrule(MONTHLY, count=4, bymonthday=-1,
                  dtstart=datetime.datetime(2024, 1, 1))
        assert [d.date() for d in list(r)] == [
            datetime.date(2024, 1, 31),
            datetime.date(2024, 2, 29),
            datetime.date(2024, 3, 31),
            datetime.date(2024, 4, 30),
        ]

        # Weekly on TU and TH
        r = rrule(WEEKLY, count=6, byweekday=[RR_TU, RR_TH],
                  dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert len(dates) == 6
        for dt in dates:
            assert dt.weekday() in (1, 3)

        # First Monday in November (YEARLY)
        r = rrule(YEARLY, count=4, bymonth=11, byweekday=RR_MO(+1),
                  dtstart=datetime.datetime(2020, 1, 1))
        dates = list(r)
        assert len(dates) == 4
        for dt in dates:
            assert dt.month == 11 and dt.weekday() == 0 and 1 <= dt.day <= 7

        # Daily at 9:00 and 17:00
        r = rrule(DAILY, count=8, byhour=[9, 17], byminute=[0], bysecond=[0],
                  dtstart=datetime.datetime(2024, 1, 1, 0, 0, 0))
        dates = list(r)
        assert len(dates) == 8
        assert set(d.hour for d in dates) == {9, 17}

        # Every 3 months
        r = rrule(MONTHLY, interval=3, count=4,
                  dtstart=datetime.datetime(2024, 1, 15))
        assert [d.month for d in list(r)] == [1, 4, 7, 10]

        # Query methods: before, after, between
        r = rrule(MONTHLY, dtstart=datetime.datetime(2024, 1, 15))
        ref = datetime.datetime(2024, 6, 1)
        assert r.before(ref) == datetime.datetime(2024, 5, 15)
        assert r.after(ref) == datetime.datetime(2024, 6, 15)
        between = r.between(datetime.datetime(2024, 3, 1),
                            datetime.datetime(2024, 8, 1))
        assert len(between) == 5
        assert between[0] == datetime.datetime(2024, 3, 15)
        assert between[-1] == datetime.datetime(2024, 7, 15)

        # count
        r2 = rrule(DAILY, dtstart=datetime.datetime(2024, 1, 1),
                   until=datetime.datetime(2024, 1, 31))
        assert r2.count() == 31

        # Indexing and slicing
        r3 = rrule(DAILY, count=10, dtstart=datetime.datetime(2024, 1, 1))
        assert r3[0] == datetime.datetime(2024, 1, 1)
        assert r3[5] == datetime.datetime(2024, 1, 6)
        assert r3[-1] == datetime.datetime(2024, 1, 10)
        assert list(r3[2:5]) == [
            datetime.datetime(2024, 1, 3),
            datetime.datetime(2024, 1, 4),
            datetime.datetime(2024, 1, 5),
        ]

        # Sub-day: HOURLY filtered to specific hours
        r = rrule(HOURLY, count=6, byhour=[9, 12, 17], byminute=[0], bysecond=[0],
                  dtstart=datetime.datetime(2024, 1, 1, 0, 0, 0))
        dates = list(r)
        assert len(dates) == 6
        assert dates[0] == datetime.datetime(2024, 1, 1, 9, 0, 0)
        assert dates[1] == datetime.datetime(2024, 1, 1, 12, 0, 0)
        assert dates[2] == datetime.datetime(2024, 1, 1, 17, 0, 0)
        assert dates[3] == datetime.datetime(2024, 1, 2, 9, 0, 0)

        # MINUTELY every 15 minutes
        r = rrule(MINUTELY, interval=15, count=4,
                  dtstart=datetime.datetime(2024, 1, 1, 9, 0, 0))
        dates = list(r)
        assert dates == [
            datetime.datetime(2024, 1, 1, 9, 0),
            datetime.datetime(2024, 1, 1, 9, 15),
            datetime.datetime(2024, 1, 1, 9, 30),
            datetime.datetime(2024, 1, 1, 9, 45),
        ]

        # SECONDLY every 30 seconds
        r = rrule(SECONDLY, interval=30, count=4,
                  dtstart=datetime.datetime(2024, 1, 1, 0, 0, 0))
        dates = list(r)
        assert dates[1] == datetime.datetime(2024, 1, 1, 0, 0, 30)
        assert dates[2] == datetime.datetime(2024, 1, 1, 0, 1, 0)
        assert dates[3] == datetime.datetime(2024, 1, 1, 0, 1, 30)


# ---------------------------------------------------------------------------
# rrule — hard edge cases
# ---------------------------------------------------------------------------

class TestRRuleHard:
    """Tests for rrule edge cases that require deep RFC 5545 understanding."""

    def test_rrule_monthly_ordinals_and_setpos(self):
        """MONTHLY with weekday ordinals (last Friday, 2nd Tuesday) and
        complex bysetpos with multiple byweekday values."""
        # Last Friday of each month
        r = rrule(MONTHLY, count=6, byweekday=RR_FR(-1),
                  dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert len(dates) == 6
        for dt in dates:
            assert dt.weekday() == 4
            next_fri = dt + datetime.timedelta(days=7)
            assert next_fri.month != dt.month

        # 2nd Tuesday of each month
        r = rrule(MONTHLY, count=4, byweekday=RR_TU(+2),
                  dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert len(dates) == 4
        for dt in dates:
            assert dt.weekday() == 1
            assert 8 <= dt.day <= 14

        # Last weekday (Mon-Fri) of January and July via bysetpos=-1
        r = rrule(MONTHLY, count=4, bymonth=[1, 7],
                  byweekday=[RR_MO, RR_TU, RR_WE, RR_TH, RR_FR],
                  bysetpos=-1,
                  dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert len(dates) == 4
        for dt in dates:
            assert dt.month in (1, 7)
            assert dt.weekday() < 5
            next_day = dt + datetime.timedelta(days=1)
            while next_day.month == dt.month:
                assert next_day.weekday() >= 5, (
                    f"Found later weekday {next_day} in same month as {dt}")
                next_day += datetime.timedelta(days=1)

    def test_rrule_byyearday_byweekno(self):
        """byyearday selects the Nth day of the year (leap-year aware).
        byweekno selects ISO week numbers (week 1 can start in prior year)."""
        # byyearday=100: April 9 in 2024 (leap), April 10 in 2025 (non-leap)
        r = rrule(YEARLY, count=3, byyearday=100,
                  dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert dates[0].date() == datetime.date(2024, 4, 9)
        assert dates[1].date() == datetime.date(2025, 4, 10)
        assert dates[2].date() == datetime.date(2026, 4, 10)

        # byweekno=1, Monday: ISO week 1 can fall in the prior calendar year
        r = rrule(YEARLY, count=3, byweekno=1, byweekday=RR_MO,
                  dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert dates[0].date() == datetime.date(2024, 1, 1)
        assert dates[1].date() == datetime.date(2024, 12, 30)
        assert dates[2].date() == datetime.date(2025, 12, 29)

    def test_rrule_str_roundtrip_and_setpos_quarterly(self):
        """str(rrule) round-trips through rrulestr. Last business day of each
        quarter via bymonth+byweekday+bysetpos=-1."""
        # Simple daily rule round-trip
        r = rrule(DAILY, count=5, dtstart=datetime.datetime(2024, 1, 1))
        s = str(r)
        r2 = rrulestr(s)
        assert list(r) == list(r2)

        # Monthly with weekday ordinal round-trip (tests BYDAY sign encoding)
        r = rrule(MONTHLY, count=6, byweekday=RR_FR(-1),
                  dtstart=datetime.datetime(2024, 1, 1))
        s = str(r)
        r2 = rrulestr(s)
        assert list(r) == list(r2)

        # Last business day of each quarter (bysetpos with bymonth)
        r = rrule(MONTHLY, count=4, bymonth=[3, 6, 9, 12],
                  byweekday=[RR_MO, RR_TU, RR_WE, RR_TH, RR_FR],
                  bysetpos=-1,
                  dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert len(dates) == 4
        for dt in dates:
            assert dt.month in (3, 6, 9, 12)
            assert dt.weekday() < 5
            next_day = dt + datetime.timedelta(days=1)
            while next_day.month == dt.month:
                assert next_day.weekday() >= 5
                next_day += datetime.timedelta(days=1)


# ---------------------------------------------------------------------------
# rruleset + rrulestr
# ---------------------------------------------------------------------------

class TestRRuleSet:
    """Tests for rruleset and rrulestr parsing."""

    def test_rruleset_and_rrulestr(self):
        """rruleset with rrule + exdate + exrule + rdate. rrulestr parses
        RFC 5545 strings including DTSTART, multiline EXDATE, and RDATE."""
        # rruleset: daily + exclusions + extra date
        rs = rruleset()
        rs.rrule(rrule(DAILY, count=31, dtstart=datetime.datetime(2024, 1, 1)))
        rs.exdate(datetime.datetime(2024, 1, 3))
        rs.exdate(datetime.datetime(2024, 1, 5))
        rs.exrule(rrule(WEEKLY, byweekday=[RR_SA, RR_SU],
                        dtstart=datetime.datetime(2024, 1, 1), count=10))
        rs.rdate(datetime.datetime(2024, 2, 14))

        dates = list(rs)
        days = [d.day for d in dates if d.month == 1]
        assert 3 not in days
        assert 5 not in days
        for dt in dates:
            if dt.month == 1:
                assert dt.weekday() < 5
        assert datetime.datetime(2024, 2, 14) in dates

        # rruleset with overlapping rules deduplicates
        rs2 = rruleset()
        rs2.rrule(rrule(DAILY, count=5, dtstart=datetime.datetime(2024, 1, 1)))
        rs2.rrule(rrule(DAILY, count=5, dtstart=datetime.datetime(2024, 1, 3)))
        dates2 = list(rs2)
        assert len(dates2) == 7
        assert dates2[0] == datetime.datetime(2024, 1, 1)
        assert dates2[-1] == datetime.datetime(2024, 1, 7)

        # rrulestr: basic RRULE
        r = rrulestr("RRULE:FREQ=MONTHLY;COUNT=3;BYDAY=FR;BYSETPOS=-1",
                     dtstart=datetime.datetime(2024, 1, 1))
        dates = list(r)
        assert len(dates) == 3
        for dt in dates:
            assert dt.weekday() == 4

        # rrulestr: DTSTART in the string
        r = rrulestr("DTSTART:20240101T000000\nRRULE:FREQ=DAILY;COUNT=3")
        dates = list(r)
        assert dates[0] == datetime.datetime(2024, 1, 1)
        assert len(dates) == 3

        # rrulestr: multiline with EXDATE
        s = ("DTSTART:20240101T000000\n"
             "RRULE:FREQ=DAILY;COUNT=7\n"
             "EXDATE:20240103T000000\n"
             "EXDATE:20240105T000000")
        rs = rrulestr(s)
        dates = list(rs)
        assert len(dates) == 5
        excluded_days = {d.day for d in dates}
        assert 3 not in excluded_days
        assert 5 not in excluded_days

        # rrulestr: multiline with RDATE
        s = ("DTSTART:20240101T000000\n"
             "RRULE:FREQ=MONTHLY;BYMONTHDAY=1;COUNT=3\n"
             "RDATE:20240115T000000")
        rs = rrulestr(s)
        dates = list(rs)
        assert datetime.datetime(2024, 1, 15) in dates
        assert len(dates) == 4


# ---------------------------------------------------------------------------
# relativedelta — bundled core tests
# ---------------------------------------------------------------------------

class TestRelativeDeltaCore:
    """Bundled tests for relativedelta clamping, overflow, and operators."""

    def test_relativedelta_core_operators(self):
        """Month-end clamping, leap year, year overflow, combined absolute+relative,
        multiplication, negation, addition/subtraction of deltas, equality, bool, weeks."""
        # Jan 31 + 1 month = Feb 28 (non-leap)
        assert (datetime.datetime(2023, 1, 31) + relativedelta(months=1)
                == datetime.datetime(2023, 2, 28))
        # Jan 31 + 1 month = Feb 29 (leap year)
        assert (datetime.datetime(2024, 1, 31) + relativedelta(months=1)
                == datetime.datetime(2024, 2, 29))
        # Mar 31 + 1 month = Apr 30
        assert (datetime.datetime(2024, 3, 31) + relativedelta(months=1)
                == datetime.datetime(2024, 4, 30))
        # Feb 29 - 1 year = Feb 28
        assert (datetime.datetime(2024, 2, 29) + relativedelta(years=-1)
                == datetime.datetime(2023, 2, 28))
        # Year overflow: Nov + 3 months = Feb next year
        assert (datetime.datetime(2024, 11, 15) + relativedelta(months=3)
                == datetime.datetime(2025, 2, 15))

        # Absolute (singular) replaces; relative (plural) adds
        dt = datetime.datetime(2024, 3, 15, 10, 30, 0)
        assert (dt + relativedelta(year=2025, month=6)
                == datetime.datetime(2025, 6, 15, 10, 30, 0))

        # Combined: months=1 + day=1 -> first of next month
        assert (datetime.datetime(2024, 1, 15) + relativedelta(months=1, day=1)
                == datetime.datetime(2024, 2, 1))

        # Multiplication
        rd = relativedelta(months=1, days=5)
        rd3 = rd * 3
        assert (datetime.datetime(2024, 1, 1) + rd3
                == datetime.datetime(2024, 4, 16))

        # Negation
        neg = -relativedelta(months=2, days=10)
        assert (datetime.datetime(2024, 6, 15) + neg
                == datetime.datetime(2024, 4, 5))

        # Addition and subtraction of relativedeltas
        rd1 = relativedelta(months=1, days=5)
        rd2 = relativedelta(months=2, days=-3)
        added = rd1 + rd2
        assert added.months == 3 and added.days == 2
        subtracted = rd1 - rd2
        assert subtracted.months == -1 and subtracted.days == 8

        # Equality
        assert relativedelta(months=1) == relativedelta(months=1)
        assert relativedelta(months=1) != relativedelta(months=2)

        # Bool: empty relativedelta is falsy
        assert not bool(relativedelta())
        assert bool(relativedelta(months=1))

        # Weeks property
        rd_w = relativedelta(weeks=2)
        assert rd_w.days == 14

        # weekday=MO(+1) from Monday: today counts as 1st occurrence
        dt_mon = datetime.datetime(2024, 1, 1)  # Monday
        result = dt_mon + relativedelta(weekday=MO(+1))
        assert result == datetime.datetime(2024, 1, 1)


# ---------------------------------------------------------------------------
# relativedelta — hard edge cases
# ---------------------------------------------------------------------------

class TestRelativeDeltaHard:
    """Tests for relativedelta edge cases that trip up implementations."""

    def test_relativedelta_weekday_shifting(self):
        """Weekday shifting: next Friday, previous Friday, 2nd Monday, and
        weekday applied after month arithmetic (clamping then shift)."""
        dt = datetime.datetime(2024, 1, 3)  # Wednesday

        # Next Friday (including today)
        result = dt + relativedelta(weekday=FR)
        assert result == datetime.datetime(2024, 1, 5)

        # Previous Friday
        result = dt + relativedelta(weekday=FR(-1))
        assert result.weekday() == 4
        assert result < dt

        # 2nd Monday from Jan 1 (Monday) — today counts as 1st occurrence
        dt2 = datetime.datetime(2024, 1, 1)
        result = dt2 + relativedelta(weekday=MO(+2))
        assert result == datetime.datetime(2024, 1, 8)

        # Chained: Jan 31 + 1 month (clamp to Feb 29) + weekday=FR -> Mar 1
        result = datetime.datetime(2024, 1, 31) + relativedelta(months=1, weekday=FR)
        assert result == datetime.datetime(2024, 3, 1)

    def test_relativedelta_diff_and_abs(self):
        """Diff mode computes normalized difference with consistent signs.
        abs() produces component-wise absolute values."""
        # Forward diff
        dt1 = datetime.datetime(2025, 6, 15, 14, 30, 0)
        dt2 = datetime.datetime(2023, 2, 28, 10, 0, 0)
        delta = relativedelta(dt1, dt2)
        assert delta.years == 2
        assert delta.months == 3
        assert delta.days == 18
        assert delta.hours == 4
        assert delta.minutes == 30
        assert dt2 + delta == dt1

        # Backward diff: components have consistent negative signs
        dt1 = datetime.datetime(2023, 1, 15, 8, 0, 0)
        dt2 = datetime.datetime(2024, 6, 20, 14, 30, 0)
        delta = relativedelta(dt1, dt2)
        assert delta.years == -1
        assert delta.months == -5
        assert dt2 + delta == dt1

        # abs(): each relative component independently abs'd
        rd = relativedelta(years=-2, months=3, days=-5, hours=-1)
        a = abs(rd)
        assert a.years == 2 and a.months == 3 and a.days == 5 and a.hours == 1


# ---------------------------------------------------------------------------
# Timezone — basics + IANA + POSIX TZ + Easter + Utils
# ---------------------------------------------------------------------------

class TestTzBasicsAndMore:
    """Bundled tests for basic tz types, IANA names with DST, POSIX TZ strings,
    Easter computation, and utility functions."""

    def test_tz_basics_iana_tzstr_easter_utils(self):
        """tzutc, tzoffset, tzlocal, equality. IANA gettz with winter/summer DST.
        POSIX TZ strings. Easter dates. Utility functions."""
        # tzutc
        utc = tz.tzutc()
        dt = datetime.datetime(2024, 6, 15, 12, 0, tzinfo=utc)
        assert dt.utcoffset() == datetime.timedelta(0)
        assert dt.dst() == datetime.timedelta(0)
        assert dt.tzname() == "UTC"

        # tzoffset
        eastern = tz.tzoffset("EST", -5 * 3600)
        dt = datetime.datetime(2024, 6, 15, 12, 0, tzinfo=eastern)
        assert dt.utcoffset() == datetime.timedelta(hours=-5)
        assert dt.dst() == datetime.timedelta(0)
        assert dt.tzname() == "EST"

        # tzlocal
        local = tz.tzlocal()
        now = datetime.datetime.now(local)
        offset = now.utcoffset()
        assert offset is not None
        assert datetime.timedelta(hours=-12) <= offset <= datetime.timedelta(hours=14)

        # Equality: tzutc() == tzoffset(None, 0)
        assert tz.tzutc() == tz.tzoffset(None, 0)

        # IANA: US/Eastern with winter/summer DST
        eastern_iana = tz.gettz("US/Eastern")
        assert eastern_iana is not None, "US/Eastern timezone data not available"
        dt_winter = datetime.datetime(2024, 1, 15, 12, 0, tzinfo=eastern_iana)
        assert dt_winter.utcoffset() == datetime.timedelta(hours=-5)
        dt_summer = datetime.datetime(2024, 7, 15, 12, 0, tzinfo=eastern_iana)
        assert dt_summer.utcoffset() == datetime.timedelta(hours=-4)

        # POSIX TZ string: EST5EDT
        eastern_str = tz.tzstr("EST5EDT,M3.2.0/2,M11.1.0/2")
        dt_w = datetime.datetime(2024, 1, 15, 12, 0, tzinfo=eastern_str)
        assert dt_w.utcoffset() == datetime.timedelta(hours=-5)
        dt_s = datetime.datetime(2024, 7, 15, 12, 0, tzinfo=eastern_str)
        assert dt_s.utcoffset() == datetime.timedelta(hours=-4)

        # POSIX TZ string: PST8PDT
        pacific_str = tz.tzstr("PST8PDT,M3.2.0/2,M11.1.0/2")
        dt_w = datetime.datetime(2024, 1, 15, 12, 0, tzinfo=pacific_str)
        assert dt_w.utcoffset() == datetime.timedelta(hours=-8)
        dt_s = datetime.datetime(2024, 7, 15, 12, 0, tzinfo=pacific_str)
        assert dt_s.utcoffset() == datetime.timedelta(hours=-7)

        # Exact DST transition boundary for EST5EDT (2nd Sunday in March at 2 AM)
        dt_pre = datetime.datetime(2024, 3, 10, 1, 59, tzinfo=eastern_str)
        assert dt_pre.utcoffset() == datetime.timedelta(hours=-5)
        dt_post = datetime.datetime(2024, 3, 10, 3, 0, tzinfo=eastern_str)
        assert dt_post.utcoffset() == datetime.timedelta(hours=-4)

        # Easter: Western, Orthodox, Julian
        assert easter(2024) == datetime.date(2024, 3, 31)
        assert easter(2025) == datetime.date(2025, 4, 20)
        assert easter(2023) == datetime.date(2023, 4, 9)
        assert easter(2000) == datetime.date(2000, 4, 23)
        assert easter(2024, EASTER_ORTHODOX) == datetime.date(2024, 5, 5)
        assert easter(2025, EASTER_ORTHODOX) == datetime.date(2025, 4, 20)
        assert easter(2024, EASTER_JULIAN) == datetime.date(2024, 4, 22)

        # Utilities
        t = today()
        assert t.hour == 0 and t.minute == 0 and t.second == 0
        assert t.date() == datetime.date.today()

        t = today(utc)
        assert t.tzinfo == utc and t.hour == 0

        dt1 = datetime.datetime(2024, 1, 1, 12, 0, 0)
        dt2 = datetime.datetime(2024, 1, 1, 12, 0, 30)
        assert within_delta(dt1, dt2, datetime.timedelta(minutes=1))
        assert not within_delta(dt1, dt2, datetime.timedelta(seconds=10))

        # default_tzinfo
        naive = datetime.datetime(2024, 1, 1, 12, 0)
        assert default_tzinfo(naive, utc).tzinfo is utc
        aware = datetime.datetime(2024, 1, 1, 12, 0,
                                  tzinfo=tz.tzoffset("EST", -5 * 3600))
        assert default_tzinfo(aware, utc).tzinfo is not utc


# ---------------------------------------------------------------------------
# Timezone — DST edge cases (always hard)
# ---------------------------------------------------------------------------

class TestTzDSTEdgeCases:
    """Tests for DST edge cases — spring-forward gaps and fall-back overlaps."""

    def test_tz_dst_edge_cases(self):
        """Spring-forward gap: imaginary times don't exist and are resolved.
        Fall-back overlap: ambiguous times are detected."""
        eastern = tz.gettz("US/Eastern")
        assert eastern is not None, "US/Eastern timezone data not available"

        # 2:30 AM during spring-forward gap doesn't exist
        dt_imaginary = datetime.datetime(2024, 3, 10, 2, 30, tzinfo=eastern)
        assert not tz.datetime_exists(dt_imaginary)
        # 3:30 AM exists (after transition)
        assert tz.datetime_exists(datetime.datetime(2024, 3, 10, 3, 30, tzinfo=eastern))

        # resolve_imaginary moves it forward past the gap
        resolved = tz.resolve_imaginary(dt_imaginary)
        assert tz.datetime_exists(resolved)
        assert resolved.hour == 3 and resolved.minute == 30

        # 1:30 AM during fall-back is ambiguous
        dt_ambig = datetime.datetime(2024, 11, 3, 1, 30, tzinfo=eastern)
        assert tz.datetime_ambiguous(dt_ambig)
        # Noon is not ambiguous
        assert not tz.datetime_ambiguous(
            datetime.datetime(2024, 11, 3, 12, 0, tzinfo=eastern))


# ---------------------------------------------------------------------------
# Timezone — enfold, tzfile, fold-aware offsets
# ---------------------------------------------------------------------------

class TestTzEnfoldTzfile:
    """Tests for tzfile, enfold fold disambiguation, and fold-aware offsets."""

    def test_tz_enfold_tzfile(self):
        """tzfile reads TZif binary data. enfold distinguishes fold=0/1 with
        different UTC offsets during fall-back."""
        import os
        zoneinfo_path = "/usr/share/zoneinfo/US/Eastern"
        if not os.path.exists(zoneinfo_path):
            zoneinfo_path = "/usr/share/zoneinfo/America/New_York"
        assert os.path.exists(zoneinfo_path), "TZif file not found"

        eastern = tz.tzfile(zoneinfo_path)
        assert datetime.datetime(2024, 1, 15, 12, 0, tzinfo=eastern).utcoffset() == \
            datetime.timedelta(hours=-5)
        assert datetime.datetime(2024, 7, 15, 12, 0, tzinfo=eastern).utcoffset() == \
            datetime.timedelta(hours=-4)

        # enfold: fold=0 (first occurrence, EDT=-4) vs fold=1 (second, EST=-5)
        eastern_gettz = tz.gettz("US/Eastern")
        assert eastern_gettz is not None
        dt_ambig = datetime.datetime(2024, 11, 3, 1, 30, tzinfo=eastern_gettz)
        dt_fold0 = tz.enfold(dt_ambig, fold=0)
        dt_fold1 = tz.enfold(dt_ambig, fold=1)
        assert dt_fold0.fold == 0
        assert dt_fold1.fold == 1
        assert dt_fold0.utcoffset() == datetime.timedelta(hours=-4)
        assert dt_fold1.utcoffset() == datetime.timedelta(hours=-5)
