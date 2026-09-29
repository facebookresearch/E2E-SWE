# A units-of-measure library in C

Build a C library for representing physical **units of measure** and converting
numeric values between them. The library models a *system* of units, lets you
construct new units by combining existing ones, decides whether two units are
mutually convertible, and produces **converters** — objects that map a numeric
value in one unit to the equivalent value in another.

## Build & dependencies

- Language: C (C99). Your `setup.sh` (which must build with no network access;
  the toolchain is preinstalled) must build and install the library so a test
  program compiles and links against it with:
  - `#include "udunits2.h"` and `#include "converter.h"` resolving on the
    default include path (install both headers to `/usr/local/include`), and
  - `-ludunits2` linking the library (install to `/usr/local/lib`; run `ldconfig`).
- The only external library needed is the C math library (`-lm`).

## Scope

Units are constructed and exercised **programmatically** through the API below
(create a system, add base units, combine them, build converters). Parsing unit
strings from text and loading a unit database from XML are **out of scope** — you
do not need to implement `ut_parse` or any XML loading.

## Public API (exact names/headers the tests use)

```c
#include "udunits2.h"
#include "converter.h"
```

**Status:** `ut_status` from `ut_get_status()` includes at least `UT_SUCCESS`,
`UT_BAD_ARG`, `UT_NOT_SAME_SYSTEM`, `UT_MEANINGLESS`. A unit-returning function
returns `NULL` and sets the status on failure.

**Unit system**
- `ut_system* ut_new_system(void)` — a system whose only unit is the dimensionless one.
- `void ut_free_system(ut_system*)`; `ut_system* ut_get_system(const ut_unit*)`.
- `ut_unit* ut_new_base_unit(ut_system*)`; `ut_unit* ut_new_dimensionless_unit(ut_system*)`.
- `ut_unit* ut_get_dimensionless_unit_one(const ut_system*)`.
- `ut_status ut_set_second(const ut_unit*)` — designate the system's "second"
  (required before constructing timestamp units).

**Constructing units**
- `ut_unit* ut_clone(const ut_unit*)`; `void ut_free(ut_unit*)`.
- `ut_unit* ut_scale(double factor, const ut_unit*)` — scales `unit` by `factor`. A `factor`
  of `0.0` is an invalid argument: the call returns `NULL` and sets the status to `UT_BAD_ARG`.
- `ut_unit* ut_offset(const ut_unit*, double offset)` — an affine unit displaced from
  `unit`: a value expressed in this affine unit plus `offset` equals the equivalent value
  in `unit`.
- `ut_unit* ut_multiply(const ut_unit*, const ut_unit*)`;
  `ut_unit* ut_divide(const ut_unit* numer, const ut_unit* denom)`;
  `ut_unit* ut_invert(const ut_unit*)`.
- `ut_unit* ut_raise(const ut_unit*, int power)`; `ut_unit* ut_root(const ut_unit*, int root)`.
- `ut_unit* ut_log(double base, const ut_unit* reference)` — a logarithmic unit: its value
  is the base-`base` logarithm of a quantity's ratio to `reference`, and it is convertible to
  `reference`'s dimension.
- `ut_unit* ut_offset_by_time(const ut_unit*, double origin)` — a timestamp unit.

**Inspecting**
- `int ut_is_dimensionless(const ut_unit*)`; `int ut_are_convertible(const ut_unit*, const ut_unit*)`.

**Time**
- `double ut_encode_time(int year, int month, int day, int hour, int minute, double second)`.
- `void ut_decode_time(double value, int* year, int* month, int* day, int* hour,
  int* minute, double* second, double* resolution)` — decodes an encoded time value back into
  its calendar fields; `resolution` receives the resolution of the decoded time in seconds (its
  exact value is unspecified and not relied upon).

**Converters** (`converter.h`)
- `cv_converter* ut_get_converter(const ut_unit* from, const ut_unit* to)` — `NULL` if not convertible.
- `double cv_convert_double(const cv_converter*, double)`; `float cv_convert_float(const cv_converter*, float)`.
- `double* cv_convert_doubles(const cv_converter*, const double* in, size_t n, double* out)`
  and the `float` form — must work correctly when `in == out` (in place).
- `cv_converter* cv_get_scale(double)`; `cv_converter* cv_get_offset(double)`;
  `cv_converter* cv_get_galilean(double slope, double intercept)`;
  `cv_converter* cv_get_log(double base)`; `cv_converter* cv_get_pow(double base)`.
- `cv_converter* cv_combine(cv_converter* first, cv_converter* second)` — the converter
  that applies `first`, then `second`.
- `void cv_free(cv_converter*)`.

## Semantics

Implement conventional units-of-measure semantics. A few behaviors the API
guarantees that are easy to get wrong:

- Combining units composes their dimensions; a unit whose dimensions fully
  cancel is dimensionless. Two units are convertible exactly when their
  dimensions match (dimensionless base units do not affect convertibility).
- Affine (offset) units keep only their multiplicative scale when used in a
  product, power, or root — the additive offset does not carry through such
  operations (and this is not an error).
- An operation that is not well defined on a unit yields `NULL` /
  `UT_MEANINGLESS` rather than a nonsensical unit — including taking a root that
  the unit's dimensions do not admit, and raising, rooting, or multiplying a
  logarithmic unit by a non-dimensionless unit. Multiplying a logarithmic unit
  by a dimensionless unit is allowed.
- Converters returned by `ut_get_converter` and built with `cv_*` are exact for
  the units/parameters involved; converting between two timestamp units accounts
  for both the unit scale and the difference in their origins.

## Notes
- Everything is exercised in-process via the API; no network is used.
- Where exact floating-point equality is not representable, comparisons use a
  small tolerance; emit values with full `double` precision.
- Behaviour not pinned down here should follow from these definitions and from
  conventional units-of-measure behavior.
