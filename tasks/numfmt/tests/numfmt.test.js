// Hidden e2e suite for the numfmt task (ECMA-376 spreadsheet number/date format engine). Drives the
// public API and asserts EXACT output. All expected values were captured from the reference numfmt
// v3.2.6. Uses Node's built-in test runner.
const { test } = require("node:test");
const assert = require("node:assert");
const n = require("/app/numfmt.js");

// Object/array results compared by JSON-normalized shape (a valid implementation may use any object
// representation, e.g. frozen vs plain); strings/numbers compared directly.
const norm = (x) => (x === undefined ? undefined : JSON.parse(JSON.stringify(x)));

// ---------------------------------------------------------------- format: digits, grouping, scaling
test("format digit placeholders, decimals, and negative sign", () => {
  assert.strictEqual(n.format("#,##0.00", 1234.56), "1,234.56");
  assert.strictEqual(n.format("0.00", -1234.5), "-1234.50");
});

test("format ? placeholder pads with spaces", () => {
  assert.strictEqual(n.format("0.??", 1.5), "1.5 ");
  assert.strictEqual(n.format("??/??", 0.5), " 1/2 ");
});

test("format thousands grouping", () => {
  assert.strictEqual(n.format("#,##0", 1234567), "1,234,567");
});

test("format trailing-comma scaling by thousands", () => {
  assert.strictEqual(n.format("0.0,,", 12200000), "12.2");
  assert.strictEqual(n.format("#,##0,,", 12200000), "12");
  assert.strictEqual(n.format("0,", 12345), "12");
});

test("format percent scales by 100", () => {
  assert.strictEqual(n.format("0%", 0.7), "70%");
  assert.strictEqual(n.format("0.0%", 0.1234), "12.3%");
});

test("format scientific notation", () => {
  assert.strictEqual(n.format("0.00E+00", 12200000), "1.22E+07");
});

test("format fractions (free, fixed-denominator, and mixed)", () => {
  assert.strictEqual(n.format("# ?/?", 1.25), "1 1/4");
  assert.strictEqual(n.format("?/8", 0.5), "4/8");
  assert.strictEqual(n.format("?/?", 0.5), "1/2");
});

// ---------------------------------------------------------------- format: sections, text, conditions
test("format routes a value to the positive/negative/zero section", () => {
  assert.strictEqual(n.format('"P";"N";"Z"', 5), "P");
  assert.strictEqual(n.format('"P";"N";"Z"', -5), "N");
  assert.strictEqual(n.format('"P";"N";"Z"', 0), "Z");
});

test("format sends strings through the text (@) section", () => {
  assert.strictEqual(n.format("0.00", "hello"), "hello");
  assert.strictEqual(n.format('"v="@', "foo"), "v=foo");
});

test("format condition sections select by comparison", () => {
  assert.strictEqual(n.format('[>100]"big";[<=100]"small"', 50), "small");
  assert.strictEqual(n.format('[>100]"big";[<=100]"small"', 150), "big");
});

test("format accounting-style parentheses and skip-width for negatives", () => {
  assert.strictEqual(n.format("#,##0_);(#,##0)", -1234), "(1,234)");
  assert.strictEqual(n.format("#,##0_);(#,##0)", 1234), "1,234 ");
});

test("format prints quoted literals", () => {
  assert.strictEqual(n.format('0 "bells"', 7), "7 bells");
});

// ---------------------------------------------------------------- format: dates & times
test("format a serial date", () => {
  assert.strictEqual(n.format("yyyy-mm-dd", 30962), "1984-10-07");
});

test("format honors the 1900 leap-year bug (serial 60 = 1900-02-29)", () => {
  assert.strictEqual(n.format("yyyy-mm-dd", 59), "1900-02-28");
  assert.strictEqual(n.format("yyyy-mm-dd", 60), "1900-02-29");
  assert.strictEqual(n.format("yyyy-mm-dd", 61), "1900-03-01");
});

test("format month and weekday names", () => {
  assert.strictEqual(n.format("d mmm yyyy", 30962), "7 Oct 1984");
  assert.strictEqual(n.format("mmmm", 30962), "October");
  assert.strictEqual(n.format("dddd", 30962), "Sunday");
});

test("format 12-hour time with AM/PM", () => {
  assert.strictEqual(n.format("h:mm AM/PM", 0.5), "12:00 PM");
});

test("format elapsed-time codes accumulate and sign negatives", () => {
  assert.strictEqual(n.format("[h]:mm", 1.5), "36:00");
  assert.strictEqual(n.format("[h]:mm", -1.5), "-12:00");
});

// ---------------------------------------------------------------- format: General, coercion, rounding
test("format General switches to scientific for large magnitudes", () => {
  assert.strictEqual(n.format("General", 123456789012), "1.23457E+11");
  assert.strictEqual(n.format("General", 1234.5), "1234.5");
});

test("format coerces booleans and empty values", () => {
  assert.strictEqual(n.format("General", true), "TRUE");
  assert.strictEqual(n.format("0.00", null), "");
});

test("format uses half-away-from-zero rounding", () => {
  assert.strictEqual(n.format("0", 2.5), "3");
  assert.strictEqual(n.format("0", 3.5), "4");
});

test("format output does not include color markup", () => {
  assert.strictEqual(n.format("[Red]0;[Blue]-0", -3), "-3");
});

// ---------------------------------------------------------------- formatColor
test("formatColor returns the matching section's color, or null", () => {
  assert.strictEqual(n.formatColor("[Red]0;[Blue]-0", -3), "blue");
  assert.strictEqual(n.formatColor("[Red]0;[Blue]-0", 3), "red");
  assert.strictEqual(n.formatColor("0", 3), null);
});

// ---------------------------------------------------------------- parseValue
test("parseValue of a plain integer (General → no z)", () => {
  assert.deepStrictEqual(norm(n.parseValue("-123")), { v: -123 });
});

test("parseValue infers a currency format", () => {
  assert.deepStrictEqual(norm(n.parseValue("$1,234")), { v: 1234, z: "$#,##0" });
});

test("parseValue infers a percent format and divides by 100", () => {
  assert.deepStrictEqual(norm(n.parseValue("50%")), { v: 0.5, z: "0%" });
});

test("parseValue treats parentheses as negative", () => {
  assert.deepStrictEqual(norm(n.parseValue("(1,234)")), { v: -1234, z: "#,##0" });
});

test("parseValue parses a date to a serial with an inferred format", () => {
  assert.deepStrictEqual(norm(n.parseValue("07 October 1984")), { v: 30962, z: "dd mmmm yyyy" });
});

test("parseValue parses a time to a fraction of a day", () => {
  assert.deepStrictEqual(norm(n.parseValue("11:12:13")), { v: 0.4668171296296296, z: "hh:mm:ss" });
});

test("parseValue parses booleans and returns null for unrecognized input", () => {
  assert.deepStrictEqual(norm(n.parseValue("true")), { v: true });
  assert.strictEqual(n.parseValue("not a number"), null);
});

// ---------------------------------------------------------------- getFormatInfo / getFormatDateInfo
test("getFormatInfo of a grouped number format", () => {
  assert.deepStrictEqual(norm(n.getFormatInfo("#,##0.00")), {
    type: "grouped", isDate: false, isText: false, isPercent: false, maxDecimals: 2, scale: 1,
    color: 0, parentheses: 0, grouped: 1, code: ",2", level: 10.2 });
});

test("getFormatInfo of a percent format", () => {
  assert.deepStrictEqual(norm(n.getFormatInfo("0.0%")), {
    type: "percent", isDate: false, isText: false, isPercent: true, maxDecimals: 1, scale: 100,
    color: 0, parentheses: 0, grouped: 0, code: "P1", level: 10.6 });
});

test("getFormatInfo reports type/code/level for datetime, text, and general", () => {
  const dt = norm(n.getFormatInfo("yyyy-mm-dd hh:mm:ss"));
  assert.deepStrictEqual([dt.type, dt.isDate, dt.level], ["datetime", true, 10.8]);
  const tx = norm(n.getFormatInfo("@"));
  assert.deepStrictEqual([tx.type, tx.isText, tx.level], ["text", true, 15]);
  const gn = norm(n.getFormatInfo("General"));
  assert.deepStrictEqual([gn.type, gn.maxDecimals, gn.level], ["general", 9, 0]);
});

test("getFormatDateInfo reports which fields a pattern uses and the clock type", () => {
  assert.deepStrictEqual(norm(n.getFormatDateInfo("h:mm AM/PM")), {
    year: false, month: false, day: false, hours: true, minutes: true, seconds: false, clockType: 12 });
  assert.deepStrictEqual(norm(n.getFormatDateInfo("yyyy-mm-dd")), {
    year: true, month: true, day: true, hours: false, minutes: false, seconds: false, clockType: 24 });
});

// ---------------------------------------------------------------- date serials
test("dateToSerial converts [y,m,d] arrays (with the 1900 leap gap)", () => {
  assert.strictEqual(n.dateToSerial([1978, 5, 17]), 28627);
  assert.strictEqual(n.dateToSerial([1900, 2, 28]), 59);
  assert.strictEqual(n.dateToSerial([1900, 3, 1]), 61);
});

test("dateFromSerial converts a serial to [y,m,d,h,mi,s]", () => {
  assert.deepStrictEqual(norm(n.dateFromSerial(28627)), [1978, 5, 17, 0, 0, 0]);
  assert.deepStrictEqual(norm(n.dateFromSerial(60)), [1900, 2, 29, 0, 0, 0]);
});

// ---------------------------------------------------------------- predicates & utilities
test("isDateFormat / isPercentFormat / isTextFormat", () => {
  assert.deepStrictEqual([n.isDateFormat("yyyy"), n.isDateFormat("0.00")], [true, false]);
  assert.deepStrictEqual([n.isPercentFormat("0%"), n.isPercentFormat("0.0")], [true, false]);
  assert.deepStrictEqual([n.isTextFormat("@"), n.isTextFormat("#;@")], [true, false]);
});

test("isValidFormat accepts valid patterns and rejects broken / over-sectioned ones", () => {
  assert.deepStrictEqual(
    [n.isValidFormat("0.00"), n.isValidFormat("[foo"), n.isValidFormat("0;0;0;0;0")],
    [true, false, false]);
});

test("round uses half-away-from-zero", () => {
  assert.deepStrictEqual([n.round(2.5), n.round(3.5), n.round(-2.5), n.round(1.2345, 2)], [3, 4, -3, 1.23]);
});

test("dec2frac splits a decimal into [numerator, denominator]", () => {
  assert.deepStrictEqual(norm(n.dec2frac(0.25)), [1, 4]);
  assert.deepStrictEqual(norm(n.dec2frac(0.3333333)), [1, 3]);
});

test("tokenize breaks a pattern into typed tokens", () => {
  assert.deepStrictEqual(norm(n.tokenize("0.0%")), [
    { type: "zero", value: "0", raw: "0" }, { type: "point", value: ".", raw: "." },
    { type: "zero", value: "0", raw: "0" }, { type: "percent", value: "%", raw: "%" }]);
});

// ================================================================ enrichment: harder surface
test("format General adapts precision and only goes scientific past ~11 digits", () => {
  assert.strictEqual(n.format("General", 0.0001), "0.0001");
  assert.strictEqual(n.format("General", 0.0000001), "0.0000001");
  assert.strictEqual(n.format("General", -1234.5), "-1234.5");
  assert.strictEqual(n.format("General", 1000000), "1000000");
  assert.strictEqual(n.format("General", 12345678901), "12345678901");
});

test("format combines grouping, decimals, and thousands scaling", () => {
  assert.strictEqual(n.format("#,##0.0,,", 1234567890), "1,234.6");
});

test("format two-digit and fixed-denominator fractions", () => {
  assert.strictEqual(n.format("# ??/??", 3.14159), "3  1/7 ");
  assert.strictEqual(n.format("?/16", 0.3), "5/16");
});

test("format # suppresses absent digits (including a bare decimal point)", () => {
  assert.strictEqual(n.format("#", 0), "");
  assert.strictEqual(n.format("#.##", 0), ".");
});

test("format a currency pattern with a colored parenthesized negative section", () => {
  assert.strictEqual(n.format("$#,##0.00;[Red]($#,##0.00)", 1234.5), "$1,234.50");
  assert.strictEqual(n.format("$#,##0.00;[Red]($#,##0.00)", -1234.5), "($1,234.50)");
});

test("format disambiguates m as minute vs month by context", () => {
  assert.strictEqual(n.format("h:mm:ss", 0.5208333333333334), "12:30:00");
  assert.strictEqual(n.format("mm/dd", 30962), "10/07");
});

test("format a combined date-time pattern", () => {
  assert.strictEqual(n.format("yyyy-mm-dd hh:mm:ss", 30962.5208333333), "1984-10-07 12:30:00");
});

test("format mmmmm gives the single-letter month", () => {
  assert.strictEqual(n.format("mmmmm", 30962), "O");
});

test("format elapsed [m] and [s] counters", () => {
  assert.strictEqual(n.format("[m]", 1.5), "2160");
  assert.strictEqual(n.format("[s]", 0.5), "43200");
});

test("parseValue of a negative currency and scientific input", () => {
  assert.deepStrictEqual(norm(n.parseValue("-$1,234.50")), { v: -1234.5, z: "$#,##0.00" });
  assert.deepStrictEqual(norm(n.parseValue("1.5E3")), { v: 1500, z: "0.00E+00" });
});

test("parseValue of an ISO date and a 12-hour time", () => {
  assert.deepStrictEqual(norm(n.parseValue("1984-10-07")), { v: 30962, z: "yyyy-mm-dd" });
  assert.deepStrictEqual(norm(n.parseValue("3:30 PM")), { v: 0.6458333333333334, z: "h:mm AM/PM" });
});

test("getFormatInfo of a currency format", () => {
  assert.deepStrictEqual(norm(n.getFormatInfo("$#,##0.00;[Red]($#,##0.00)")), {
    type: "currency", isDate: false, isText: false, isPercent: false, maxDecimals: 2, scale: 1,
    color: 1, parentheses: 0, grouped: 1, code: "C2-", level: 10.4 });
});

test("getFormatInfo type/code/level for scientific, date, fraction, and plain number", () => {
  const pick = (p) => { const i = norm(n.getFormatInfo(p)); return [i.type, i.code, i.level]; };
  assert.deepStrictEqual(pick("0.00E+00"), ["scientific", "S2", 6]);
  assert.deepStrictEqual(pick("yyyy-mm-dd"), ["date", "G", 10.8]);
  assert.deepStrictEqual(pick("# ?/?"), ["fraction", "G", 2]);
  assert.deepStrictEqual(pick("0.000"), ["number", "F3", 4]);
});

test("getFormatDateInfo reports seconds for an elapsed sub-second pattern", () => {
  assert.deepStrictEqual(norm(n.getFormatDateInfo("[h]:mm:ss.000")), {
    year: false, month: false, day: false, hours: true, minutes: true, seconds: true, clockType: 24 });
});

test("dateToSerial and dateFromSerial carry the time-of-day fraction", () => {
  assert.strictEqual(n.dateToSerial([1984, 10, 7, 12, 30, 0]), 30962.520833333332);
  assert.deepStrictEqual(norm(n.dateFromSerial(30962.5208333333)), [1984, 10, 7, 12, 30, 0]);
});

test("round to negative places, and half-away at 0.5", () => {
  assert.deepStrictEqual([n.round(12345, -2), n.round(0.5), n.round(-0.5)], [12300, 1, -1]);
});

test("dec2frac honors numerator/denominator digit limits", () => {
  assert.deepStrictEqual(norm(n.dec2frac(0.333, 1, 1)), [1, 3]);
  assert.deepStrictEqual(norm(n.dec2frac(3.14159, 3, 3)), [355, 113]);
  assert.deepStrictEqual(norm(n.dec2frac(2.71828, 4, 4)), [1264, 465]);
  assert.deepStrictEqual(norm(n.dec2frac(0.66666, 1, 1)), [2, 3]);
});

test("tokenize a multi-section pattern with color and parentheses", () => {
  assert.deepStrictEqual(norm(n.tokenize("[Red]#,##0.00;(#,##0.00)")), [
    { type: "color", value: "Red", raw: "[Red]" }, { type: "hash", value: "#", raw: "#" },
    { type: "group", value: ",", raw: "," }, { type: "hash", value: "#", raw: "#" },
    { type: "hash", value: "#", raw: "#" }, { type: "zero", value: "0", raw: "0" },
    { type: "point", value: ".", raw: "." }, { type: "zero", value: "0", raw: "0" },
    { type: "zero", value: "0", raw: "0" }, { type: "break", value: ";", raw: ";" },
    { type: "paren", value: "(", raw: "(" }, { type: "hash", value: "#", raw: "#" },
    { type: "group", value: ",", raw: "," }, { type: "hash", value: "#", raw: "#" },
    { type: "hash", value: "#", raw: "#" }, { type: "zero", value: "0", raw: "0" },
    { type: "point", value: ".", raw: "." }, { type: "zero", value: "0", raw: "0" },
    { type: "zero", value: "0", raw: "0" }, { type: "paren", value: ")", raw: ")" }]);
});

test("isDateFormat on elapsed codes, and isValidFormat on a plain and empty pattern", () => {
  assert.deepStrictEqual([n.isDateFormat("[h]:mm"), n.isValidFormat("0.0"), n.isValidFormat("")], [true, true, true]);
});

test("parseLocale splits a BCP-47 tag and throws on a malformed one", () => {
  assert.deepStrictEqual(norm(n.parseLocale("en-US")), { lang: "en_US", language: "en", territory: "US" });
  assert.throws(() => n.parseLocale("!!!"), (e) => e.name === "SyntaxError");
});

// ================================================================ re-enrichment: harder fair surface
test("format engineering scientific snaps the exponent to a multiple of the mantissa width", () => {
  assert.strictEqual(n.format("##0.0E+0", 12200000), "12.2E+6");
  assert.strictEqual(n.format("##0.0E+0", 1234), "1.2E+3");
  assert.strictEqual(n.format("0.0E+0", 0.00012), "1.2E-4");
});

test("format fraction uses the continued-fraction convergent, not the closest fraction", () => {
  assert.strictEqual(n.format("??/??", 0.123), " 8/65");
  assert.strictEqual(n.format("# ??/??", 2.71828), "2 51/71");
});

test("format fraction right-aligns the numerator and left-aligns the denominator", () => {
  assert.strictEqual(n.format("???/???", 0.14159), " 16/113");
  assert.strictEqual(n.format("?/?", 0.7), "2/3");
});

test("format General caps at nine significant digits and goes scientific for large magnitudes", () => {
  assert.strictEqual(n.format("General", 0.3333333333333333), "0.333333333");
  assert.strictEqual(n.format("General", 1234567890123), "1.23457E+12");
});
