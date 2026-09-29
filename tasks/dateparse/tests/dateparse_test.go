// Hidden behavioral test suite for the `dateparse` task.
//
// Drives the public API only (dateparse.ParseFormat / ParseAny / ParseIn / ParseLocal /
// ParseStrict / MustParse + the PreferMonthFirst / RetryAmbiguousDateWithSwap options) through the
// neutral module path `dateparse`. Each test is a single top-level `func Test*` (no t.Run subtests)
// so the CTRF entry count maps 1:1 to test_case_count. Assertions use exact expected values.
//
// time.Local is pinned to UTC in TestMain so that zone-less inputs and the ambiguous-swap retry
// path resolve deterministically regardless of the grading container's timezone.
package dateparse_test

import (
	"os"
	"testing"
	"time"

	"dateparse"
)

func TestMain(m *testing.M) {
	time.Local = time.UTC
	os.Exit(m.Run())
}

// guard converts a panic in the implementation into a clean single-test failure so one bad input
// cannot abort the whole `go test` binary and unfairly zero downstream tests.
func guard(t *testing.T) func() {
	return func() {
		if r := recover(); r != nil {
			t.Fatalf("panic: %v", r)
		}
	}
}

const utcLayout = "2006-01-02T15:04:05.999999999Z07:00"

// fmtEq asserts ParseFormat detects exactly the expected Go reference layout.
func fmtEq(t *testing.T, in, want string) {
	t.Helper()
	got, err := dateparse.ParseFormat(in)
	if err != nil {
		t.Fatalf("ParseFormat(%q) unexpected error: %v", in, err)
	}
	if got != want {
		t.Fatalf("ParseFormat(%q) = %q, want %q", in, got, want)
	}
}

// valEq asserts ParseAny parses to exactly the expected instant (compared in UTC).
func valEq(t *testing.T, in, wantUTC string) {
	t.Helper()
	tm, err := dateparse.ParseAny(in)
	if err != nil {
		t.Fatalf("ParseAny(%q) unexpected error: %v", in, err)
	}
	if got := tm.In(time.UTC).Format(utcLayout); got != wantUTC {
		t.Fatalf("ParseAny(%q).UTC() = %q, want %q", in, got, wantUTC)
	}
}

// fmtErr asserts both ParseFormat and ParseAny reject the input.
func fmtErr(t *testing.T, in string) {
	t.Helper()
	if lay, err := dateparse.ParseFormat(in); err == nil {
		t.Fatalf("ParseFormat(%q) = %q, want error", in, lay)
	}
	if tm, err := dateparse.ParseAny(in); err == nil {
		t.Fatalf("ParseAny(%q) = %v, want error", in, tm.In(time.UTC))
	}
}

func TestIsoDate(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2014-04-26", "2006-01-02")
	valEq(t, "2014-04-26", "2014-04-26T00:00:00Z")
	fmtEq(t, "2014-04-26 17:24:37", "2006-01-02 15:04:05")
	valEq(t, "2014-04-26 17:24:37", "2014-04-26T17:24:37Z")
	fmtEq(t, "2013-04-01 22:43:22", "2006-01-02 15:04:05")
	valEq(t, "2013-04-01 22:43:22", "2013-04-01T22:43:22Z")
}

func TestIsoT(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2009-08-12T22:15:09.99Z", "2006-01-02T15:04:05.00Z")
	valEq(t, "2009-08-12T22:15:09.99Z", "2009-08-12T22:15:09.99Z")
	fmtEq(t, "2006-01-02T15:04:05.000Z", "2006-01-02T15:04:05.000Z")
	valEq(t, "2006-01-02T15:04:05.000Z", "2006-01-02T15:04:05Z")
	fmtEq(t, "2009-08-12T22:15:09Z", "2006-01-02T15:04:05Z")
	valEq(t, "2009-08-12T22:15:09Z", "2009-08-12T22:15:09Z")
}

func TestIsoFractionWidths(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2014-04-26 17:24:37.3186369", "2006-01-02 15:04:05.0000000")
	valEq(t, "2014-04-26 17:24:37.3186369", "2014-04-26T17:24:37.3186369Z")
	fmtEq(t, "2014-05-11 08:20:13,787", "2006-01-02 15:04:05.000")
	valEq(t, "2014-05-11 08:20:13,787", "2014-05-11T08:20:13.787Z")
	fmtEq(t, "2014-04-26 17:24:37.123", "2006-01-02 15:04:05.000")
	valEq(t, "2014-04-26 17:24:37.123", "2014-04-26T17:24:37.123Z")
}

func TestIsoTZOffset(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2012-08-03T18:31:59+00:00", "2006-01-02T15:04:05-07:00")
	valEq(t, "2012-08-03T18:31:59+00:00", "2012-08-03T18:31:59Z")
	fmtEq(t, "2014-04-26 05:24:37 +0000", "2006-01-02 15:04:05 -0700")
	valEq(t, "2014-04-26 05:24:37 +0000", "2014-04-26T05:24:37Z")
	fmtEq(t, "2006-01-02T15:04:05-0700", "2006-01-02T15:04:05-0700")
	valEq(t, "2006-01-02T15:04:05-0700", "2006-01-02T22:04:05Z")
}

func TestIsoTZNamed(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2014-12-16 06:20:00 UTC", "2006-01-02 15:04:05 MST")
	valEq(t, "2014-12-16 06:20:00 UTC", "2014-12-16T06:20:00Z")
}

func TestSlashUSFullYear(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "03/31/2014", "01/02/2006")
	valEq(t, "03/31/2014", "2014-03-31T00:00:00Z")
	fmtEq(t, "4/8/2014 22:05", "1/2/2006 15:04")
	valEq(t, "4/8/2014 22:05", "2014-04-08T22:05:00Z")
	fmtEq(t, "3/31/2014", "1/02/2006")
	valEq(t, "3/31/2014", "2014-03-31T00:00:00Z")
}

func TestSlashUSAsymmetric(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "3/5/2014", "1/2/2006")
	valEq(t, "3/5/2014", "2014-03-05T00:00:00Z")
	fmtEq(t, "3/31/2014 22:05", "1/02/2006 15:04")
	valEq(t, "3/31/2014 22:05", "2014-03-31T22:05:00Z")
}

func TestSlashUSTwoDigitYear(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "08/21/71", "01/02/06")
	valEq(t, "08/21/71", "1971-08-21T00:00:00Z")
	fmtEq(t, "8/8/71", "1/2/06")
	valEq(t, "8/8/71", "1971-08-08T00:00:00Z")
}

func TestSlashWithTime(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "04/02/2014 04:08:09", "01/02/2006 15:04:05")
	valEq(t, "04/02/2014 04:08:09", "2014-04-02T04:08:09Z")
	fmtEq(t, "4/2/2014 04:08:09", "1/2/2006 15:04:05")
	valEq(t, "4/2/2014 04:08:09", "2014-04-02T04:08:09Z")
	fmtEq(t, "04/02/2014 4:8:9", "01/02/2006 3:4:5")
	valEq(t, "04/02/2014 4:8:9", "2014-04-02T04:08:09Z")
}

func TestSlashSingleDigitTimeAMPM(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "04/02/2014 4:8 PM", "01/02/2006 3:4 PM")
	valEq(t, "04/02/2014 4:8 PM", "2014-04-02T16:08:00Z")
	fmtEq(t, "04/02/2014 04:08:09 AM", "01/02/2006 15:04:05 PM")
	valEq(t, "04/02/2014 04:08:09 AM", "2014-04-02T04:08:09Z")
}

func TestColonDateSeparator(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "4:2:2014 04:08:09", "1:2:2006 15:04:05")
	valEq(t, "4:2:2014 04:08:09", "2014-04-02T04:08:09Z")
	fmtEq(t, "04:02:2014 4:8:9", "01:02:2006 3:4:5")
	valEq(t, "04:02:2014 4:8:9", "2014-04-02T04:08:09Z")
}

func TestDottedDate(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "3.31.2014", "1.02.2006")
	valEq(t, "3.31.2014", "2014-03-31T00:00:00Z")
	fmtEq(t, "3.3.2014", "1.2.2006")
	valEq(t, "3.3.2014", "2014-03-03T00:00:00Z")
	fmtEq(t, "08.21.71", "01.02.06")
	valEq(t, "08.21.71", "1971-08-21T00:00:00Z")
}

func TestYearFirstSlash(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2014/3/31", "2006/1/02")
	valEq(t, "2014/3/31", "2014-03-31T00:00:00Z")
	fmtEq(t, "2014/4/2", "2006/1/2")
	valEq(t, "2014/4/2", "2014-04-02T00:00:00Z")
	fmtEq(t, "2014/04/02 04:08:09", "2006/01/02 15:04:05")
	valEq(t, "2014/04/02 04:08:09", "2014-04-02T04:08:09Z")
}

func TestYearFirstSlashSingleDigitTime(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2014/4/2 04:08", "2006/1/2 15:04")
	valEq(t, "2014/4/2 04:08", "2014-04-02T04:08:00Z")
	fmtEq(t, "2014/4/2 04:08:09 AM", "2006/1/2 15:04:05 PM")
	valEq(t, "2014/4/2 04:08:09 AM", "2014-04-02T04:08:09Z")
}

func TestDashYMDTime(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2014-04-02 4:8", "2006-01-02 3:4")
	valEq(t, "2014-04-02 4:8", "2014-04-02T04:08:00Z")
	fmtEq(t, "2014-04-26 05:24:37 PM", "2006-01-02 15:04:05 PM")
	valEq(t, "2014-04-26 05:24:37 PM", "2014-04-26T17:24:37Z")
}

func TestMonthNameUS(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "May 8, 2009 5:57:51 PM", "Jan 2, 2006 3:04:05 PM")
	valEq(t, "May 8, 2009 5:57:51 PM", "2009-05-08T17:57:51Z")
	fmtEq(t, "oct 7, 1970", "Jan 2, 2006")
	valEq(t, "oct 7, 1970", "1970-10-07T00:00:00Z")
	fmtEq(t, "September 17, 2012 10:09am PST-08", "January 02, 2006 15:04am MST-07")
	valEq(t, "September 17, 2012 10:09am PST-08", "2012-09-17T18:09:00Z")
}

func TestMonthNameSingleDigitTime(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "May 8, 2009 5:7:51 PM", "Jan 2, 2006 3:4:05 PM")
	valEq(t, "May 8, 2009 5:7:51 PM", "2009-05-08T17:07:51Z")
}

func TestMonthNameApostropheYear(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "oct 7, '70", "Jan 2, '06")
	valEq(t, "oct 7, '70", "1970-10-07T00:00:00Z")
	fmtEq(t, "Sept. 7, '70", "Jan. 2, '06")
	valEq(t, "Sept. 7, '70", "1970-09-07T00:00:00Z")
}

func TestDayMonthYear(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "7 oct 1970", "2 Jan 2006")
	valEq(t, "7 oct 1970", "1970-10-07T00:00:00Z")
	fmtEq(t, "13 Feb 2013", "02 Jan 2006")
	valEq(t, "13 Feb 2013", "2013-02-13T00:00:00Z")
	fmtEq(t, "7 September 1970", "2 January 2006")
	valEq(t, "7 September 1970", "1970-09-07T00:00:00Z")
}

func TestDayMonthYearFull(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "02 January 2006", "02 January 2006")
	valEq(t, "02 January 2006", "2006-01-02T00:00:00Z")
}

func TestMonthAbbrDash(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2013-Feb-03", "2006-Jan-02")
	valEq(t, "2013-Feb-03", "2013-02-03T00:00:00Z")
}

func TestDayMonthAbbrDashYear(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "02-Jan-06", "02-Jan-06")
	valEq(t, "02-Jan-06", "2006-01-02T00:00:00Z")
	fmtEq(t, "02-Jan-2006 15:04:05 -0700", "02-Jan-2006 15:04:05 -0700")
	valEq(t, "02-Jan-2006 15:04:05 -0700", "2006-01-02T22:04:05Z")
}

func TestANSIC(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Mon Jan  2 15:04:05 2006", "Jan  2 15:04:05 2006")
	valEq(t, "Mon Jan  2 15:04:05 2006", "2006-01-02T15:04:05Z")
}

func TestRubyDate(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Mon Jan 02 15:04:05 -0700 2006", "Jan 02 15:04:05 -0700 2006")
	valEq(t, "Mon Jan 02 15:04:05 -0700 2006", "2006-01-02T22:04:05Z")
}

func TestUnixDate(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Mon Jan  2 15:04:05 MST 2006", "Jan  2 15:04:05 MST 2006")
	valEq(t, "Mon Jan  2 15:04:05 MST 2006", "2006-01-02T15:04:05Z")
}

func TestWeekdayTZOffsetYear(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Mon Aug 10 15:44:11 PST-0700 2015", "Jan 02 15:04:05 MST-0700 2006")
	valEq(t, "Mon Aug 10 15:44:11 PST-0700 2015", "2015-08-10T22:44:11Z")
	fmtEq(t, "Mon Aug 10 15:44:11 UTC+0000 2015", "Jan 02 15:04:05 MST-0700 2006")
	valEq(t, "Mon Aug 10 15:44:11 UTC+0000 2015", "2015-08-10T15:44:11Z")
}

func TestRFC1123Named(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Fri, 03 Jul 2015 08:08:08 MST", "Mon, 02 Jan 2006 15:04:05 MST")
	valEq(t, "Fri, 03 Jul 2015 08:08:08 MST", "2015-07-03T08:08:08Z")
}

func TestRFC1123Offset(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Thu, 03 Jul 2017 08:08:04 +0100", "Mon, 02 Jan 2006 15:04:05 -0700")
	valEq(t, "Thu, 03 Jul 2017 08:08:04 +0100", "2017-07-03T07:08:04Z")
}

func TestRFC1123SingleDigitTime(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Fri, 03 Jul 2015 8:8:8 MST", "Mon, 02 Jan 2006 3:4:5 MST")
	valEq(t, "Fri, 03 Jul 2015 8:8:8 MST", "2015-07-03T08:08:08Z")
}

func TestGlibcAnsi(t *testing.T) {
	defer guard(t)()
	// This glibc/ANSI format keeps the trailing `UTC` literal in ParseFormat (a repo quirk that
	// diverges from the general named-zone -> MST rule), so assert only the parsed instant.
	valEq(t, "Mon 02 Jan 2006 03:04:05 PM UTC", "2006-01-02T15:04:05Z")
}

func TestJSFullGMT(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "Fri Jul 03 2015 18:04:07 GMT+0100 (GMT Daylight Time)", "Jan 02 2006 15:04:05 MST-0700")
	valEq(t, "Fri Jul 03 2015 18:04:07 GMT+0100 (GMT Daylight Time)", "2015-07-03T17:04:07Z")
}

func TestAtKeyword(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "September 17, 2012 at 5:00pm UTC-05", "January 02, 2006 at 3:04pm MST-07")
	valEq(t, "September 17, 2012 at 5:00pm UTC-05", "2012-09-17T17:00:00Z")
	fmtEq(t, "May 17, 2012 AT 10:09am PST-08", "Jan 02, 2006 AT 15:04am MST-07")
	valEq(t, "May 17, 2012 AT 10:09am PST-08", "2012-05-17T18:09:00Z")
}

func TestMonthCommaYearTime(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "September 17, 2012, 10:10:09", "January 02, 2006, 15:04:05")
	valEq(t, "September 17, 2012, 10:10:09", "2012-09-17T10:10:09Z")
	fmtEq(t, "September 17, 2012 09:01:00", "January 02, 2006 15:04:05")
	valEq(t, "September 17, 2012 09:01:00", "2012-09-17T09:01:00Z")
}

func TestPostgresNanoOffset(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2012-08-03 8:1:59.257000000 +0000", "2006-01-02 3:4:05.000000000 -0700")
	valEq(t, "2012-08-03 8:1:59.257000000 +0000", "2012-08-03T08:01:59.257Z")
}

func TestCompactDate(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "20140601", "20060102")
	valEq(t, "20140601", "2014-06-01T00:00:00Z")
	fmtEq(t, "20140722105203", "20060102150405")
	valEq(t, "20140722105203", "2014-07-22T10:52:03Z")
}

func TestCompactYYMMDD(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "171113 14:14:20", "060102 15:04:05")
	valEq(t, "171113 14:14:20", "2017-11-13T14:14:20Z")
}

func TestYearOnly(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "2014", "2006")
	valEq(t, "2014", "2014-01-01T00:00:00Z")
}

func TestUnixSeconds(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "1332151919", "1332151919")
	valEq(t, "1332151919", "2012-03-19T10:11:59Z")
}

func TestUnixMicros(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "1384216367111222", "1384216367111222")
	valEq(t, "1384216367111222", "2013-11-12T00:32:47.111222Z")
}

func TestUnixNanos(t *testing.T) {
	defer guard(t)()
	fmtEq(t, "1384216367111222333", "1384216367111222333")
	valEq(t, "1384216367111222333", "2013-11-12T00:32:47.111222333Z")
}

func TestPlusOffsetDateOnly(t *testing.T) {
	defer guard(t)()
	valEq(t, "2020-07-20+08:00", "2020-07-19T16:00:00Z")
}

// ----- error / rejection cases -----

func TestErrorTooShort(t *testing.T) {
	defer guard(t)()
	fmtErr(t, "3")
}

func TestErrorGibberish(t *testing.T) {
	defer guard(t)()
	fmtErr(t, "xyzq-baad")
}

func TestErrorMonthOutOfRange(t *testing.T) {
	defer guard(t)()
	fmtErr(t, "2009-15-12T22:15Z")
}

func TestErrorDashDMYNotSupported(t *testing.T) {
	defer guard(t)()
	// dd-mm-yyyy with dash separators is not a recognized format.
	fmtErr(t, "29-06-2016")
	fmtErr(t, "3-31-2014")
}

func TestErrorLeadingSpace(t *testing.T) {
	defer guard(t)()
	fmtErr(t, " 2018-01-02 17:08:09 -07:00")
}

func TestErrorBadTZOffset(t *testing.T) {
	defer guard(t)()
	fmtErr(t, "2019-05-29T08:41-047")
}

// ----- ambiguity: default MM/DD, ParseStrict, and options -----

func TestAmbiguousDefaultsMonthFirst(t *testing.T) {
	defer guard(t)()
	// Default leans US (month first): 04/02/2014 => Feb 4... no, April 2.
	valEq(t, "04/02/2014", "2014-04-02T00:00:00Z")
	fmtEq(t, "04/02/2014", "01/02/2006")
}

func TestAmbiguousMonthOverflowIsError(t *testing.T) {
	defer guard(t)()
	// 31 cannot be a month and the default is month-first, so this is rejected.
	fmtErr(t, "31/03/2014")
}

func TestParseStrictRejectsAmbiguous(t *testing.T) {
	defer guard(t)()
	if _, err := dateparse.ParseStrict("04/02/2014"); err == nil {
		t.Fatalf("ParseStrict(ambiguous) = nil error, want error")
	}
	// A non-ambiguous unslashed ISO date parses fine under ParseStrict.
	tm, err := dateparse.ParseStrict("2014-04-02")
	if err != nil {
		t.Fatalf("ParseStrict(2014-04-02) unexpected error: %v", err)
	}
	if got := tm.In(time.UTC).Format(utcLayout); got != "2014-04-02T00:00:00Z" {
		t.Fatalf("ParseStrict(2014-04-02) = %q", got)
	}
}

func TestParseStrictRejectsResolvableSlash(t *testing.T) {
	defer guard(t)()
	// Even when only one interpretation is valid, slash m/d dates are treated as ambiguous.
	if _, err := dateparse.ParseStrict("04/22/2014"); err == nil {
		t.Fatalf("ParseStrict(04/22/2014) = nil error, want error")
	}
}

func TestPreferMonthFirstFalse(t *testing.T) {
	defer guard(t)()
	// With month-first disabled, 04/02/2014 is day/month/year => 2014-02-04.
	tm, err := dateparse.ParseAny("04/02/2014", dateparse.PreferMonthFirst(false))
	if err != nil {
		t.Fatalf("ParseAny(PreferMonthFirst(false)) error: %v", err)
	}
	if got := tm.In(time.UTC).Format(utcLayout); got != "2014-02-04T00:00:00Z" {
		t.Fatalf("PreferMonthFirst(false) 04/02/2014 = %q, want 2014-02-04T00:00:00Z", got)
	}
	lay, err := dateparse.ParseFormat("04/02/2014", dateparse.PreferMonthFirst(false))
	if err != nil || lay != "02/01/2006" {
		t.Fatalf("ParseFormat(PreferMonthFirst(false)) = %q, %v; want 02/01/2006", lay, err)
	}
}

func TestRetryAmbiguousDateWithSwap(t *testing.T) {
	defer guard(t)()
	// 31/03/2014 fails month-first, but with swap retry it becomes 2014-03-31.
	tm, err := dateparse.ParseAny("31/03/2014", dateparse.RetryAmbiguousDateWithSwap(true))
	if err != nil {
		t.Fatalf("ParseAny(RetryAmbiguousDateWithSwap) error: %v", err)
	}
	if got := tm.In(time.UTC).Format(utcLayout); got != "2014-03-31T00:00:00Z" {
		t.Fatalf("RetryAmbiguousDateWithSwap 31/03/2014 = %q, want 2014-03-31T00:00:00Z", got)
	}
}

// ----- ParseIn / ParseLocal / MustParse -----

func TestParseInLocation(t *testing.T) {
	defer guard(t)()
	loc, err := time.LoadLocation("America/New_York")
	if err != nil {
		t.Skipf("tzdata unavailable: %v", err)
	}
	tm, err := dateparse.ParseIn("2014-04-26 05:24:37", loc)
	if err != nil {
		t.Fatalf("ParseIn error: %v", err)
	}
	// 05:24:37 EDT (-04:00) == 09:24:37 UTC.
	if got := tm.In(time.UTC).Format(utcLayout); got != "2014-04-26T09:24:37Z" {
		t.Fatalf("ParseIn NY = %q, want 2014-04-26T09:24:37Z", got)
	}
}

func TestParseLocalUTC(t *testing.T) {
	defer guard(t)()
	// time.Local is pinned to UTC in TestMain, so a zone-less date resolves at UTC midnight.
	tm, err := dateparse.ParseLocal("oct 7, 1970")
	if err != nil {
		t.Fatalf("ParseLocal error: %v", err)
	}
	if got := tm.In(time.UTC).Format(utcLayout); got != "1970-10-07T00:00:00Z" {
		t.Fatalf("ParseLocal = %q, want 1970-10-07T00:00:00Z", got)
	}
}

func TestMustParse(t *testing.T) {
	defer guard(t)()
	tm := dateparse.MustParse("2020-07-20+08:00")
	if got := tm.In(time.UTC).Format(utcLayout); got != "2020-07-19T16:00:00Z" {
		t.Fatalf("MustParse = %q, want 2020-07-19T16:00:00Z", got)
	}
}
