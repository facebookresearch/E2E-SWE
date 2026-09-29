# sqlite_modern_cpp

Build `sqlite_modern_cpp`, a header-only modern C++17 wrapper around the C
SQLite3 library (`libsqlite3`). The library exposes a fluent, stream-style
interface that lets the caller build, execute, and consume SQL statements as
C++ expressions, with positional parameter binding, lambda-based result
extraction, and strongly-typed marshalling between C++ values and SQLite
columns. There is no C++ library to compile or link — every public symbol
lives in headers — but every program using the library must still link the
system `libsqlite3` shared library.

## Dependencies

- A C++17-capable compiler (`g++` is available).
- `libsqlite3-dev` — the SQLite3 development headers and shared library.
  The primary `sqlite_modern_cpp` header `#include`s `<sqlite3.h>`, so this
  apt package must be present at both compile time and link time.

## Build contract

After your `/app/setup.sh` is run, a freshly written driver must build
and run with:

```
g++ -std=c++17 driver.cpp -lsqlite3 -o driver
./driver
```

That requires:

1. `libsqlite3-dev` installed (`apt-get install -y libsqlite3-dev`).
2. The primary header installed at `/usr/local/include/sqlite_modern_cpp.h`.
3. The sub-header directory installed at
   `/usr/local/include/sqlite_modern_cpp/` so includes like
   `#include "sqlite_modern_cpp/errors.h"` (transitively pulled in from the
   primary header) resolve.
4. No `sqlite_modern_cpp` library to link, no `ldconfig` step needed — it is
   header-only on the C++ side. Only `-lsqlite3` is required.

`setup.sh` may run `apt-get install` for any extra build tools.

## Namespace

All public symbols live in `namespace sqlite`. The error classes live in
`namespace sqlite::errors`, which is also aliased as `sqlite::exceptions`.
Tests will write `using namespace sqlite;` and access errors as
`errors::<name>`.

## Public API surface

### `class database`

Represents an open SQLite database connection. Owns a `std::shared_ptr<sqlite3>`
that closes the underlying connection when the last reference is dropped.

```cpp
// Three constructors. The string overload accepts both file paths and
// the special ":memory:" path; the u16string overload accepts UTF-16
// paths; the shared_ptr overload adopts an already-open connection.
database(const std::string& db_name, const sqlite_config& config = {});
database(const std::u16string& db_name, const sqlite_config& config = {});
database(std::shared_ptr<sqlite3> db);

// Begin building a SQL statement. Returns a `database_binder` that can be
// further parameter-bound (operator<<) or extracted from (operator>>). The
// const char* / const char16_t* overloads forward to the string ones.
database_binder operator<<(const std::string& sql);
database_binder operator<<(const char* sql);
database_binder operator<<(const std::u16string& sql);
database_binder operator<<(const char16_t* sql);

// Shared connection handle. Same sqlite3* the database owns; can be passed
// to another `database` constructor to share the connection. The adopting
// `database` has full parity with the original — reads, writes, UDF
// registration, `last_insert_rowid()`, and transactions all act on the
// same underlying sqlite3 connection.
std::shared_ptr<sqlite3> connection() const;

// Last inserted rowid on the underlying sqlite3 connection.
sqlite3_int64 last_insert_rowid() const;

// Register a C++ callable as a SQLite scalar function. The function's
// argument types and arity are deduced from the callable. The return
// value of the callable becomes the SQL function's result column value.
// The function is callable from SQL by its registered name. Argument
// and return types may be any of the standard sqlite-marshallable C++
// types — int / sqlite3_int64 / any std::is_integral<T> type,
// float / double, std::string / std::u16string, std::vector<T,A> for
// blobs — using the same conversions as the bind/extract overloads.
template <typename Function>
void define(const std::string& name, Function&& func);

// Register a C++ callable pair as a SQLite aggregate function. `step`
// takes a mutable reference to an accumulator (its first argument)
// followed by one column value; `final_` takes the same accumulator
// reference and returns the aggregated result. The accumulator is
// freshly default-constructed at the start of EVERY aggregation call
// — that is, each `SELECT agg_fn(col) FROM ...` invocation builds a
// new accumulator from scratch, regardless of how many earlier
// aggregations used the same registered name. For an int accumulator
// this means each call starts at 0. The return value of `final_`
// becomes the SQL function's result column value.
template <typename StepFunction, typename FinalFunction>
void define(const std::string& name, StepFunction&& step, FinalFunction&& final_);
```

### `class database_binder`

Returned from `database::operator<<`. Holds a prepared SQLite statement plus
its current bind index. Move-only (not copyable).

The free-function `operator<<` (bind) and `operator>>` (extract) overloads
listed below must be able to access `database_binder`'s internal statement
handle, current bind index, and executed/extracted state. Implementations
typically achieve this by declaring those operators as `friend` of
`database_binder`, but a public-accessor design that exposes the same state
is equally acceptable. Whichever pattern is chosen, the chain syntax
`db << sql << v1 << v2 >> [&](...){...}` must compile and execute end-to-end.

```cpp
// Re-execute support.
void reset();          // Clear bindings and reset execution state.
void execute();        // Run the statement to completion without extraction.
void used(bool state); // Set the executed-state flag.
bool used() const;     // Query the executed-state flag.
```

When a `database_binder` is destroyed without ever having been extracted
from and without an active exception, it is executed implicitly. This makes
`db << "delete from t;";` a single-line statement. The implicit-execute
rule also applies to chained temporaries with bound parameters:
`db << "insert into t values (?, ?);" << x << y;` runs the statement when
the temporary chain is destroyed at end-of-full-expression. Because the
destructor runs synchronously at the semicolon, the next statement
observing `database::last_insert_rowid()` sees the inserted row's id
without any explicit flush/sync — the implicit execute completes (and
any error throws) before control reaches the following statement.

#### Binding parameters

The bind-operator side of `database_binder::operator<<` takes any of these
types as a positional parameter for the next `?` placeholder. The
overloads must also accept rvalue `database_binder` arguments, since
`database::operator<<(const std::string&)` returns a `database_binder`
prvalue and the chain `db << "..." << x << y` invokes successive bind
operators on the result of the previous link. Either provide rvalue-ref
overloads (`database_binder&& operator<<(database_binder&&, T)`
returning `database_binder&&`) or use a by-value `database_binder`
parameter; lvalue-only signatures will fail to compile the chain
syntax exercised throughout the test suite.

```cpp
// Integral types — int, short, long, long long, sqlite3_int64,
// any std::is_integral<T>::value type. Forwarded to sqlite3_bind_int /
// sqlite3_bind_int64 as appropriate.
database_binder& operator<<(database_binder& db, int);
database_binder& operator<<(database_binder& db, sqlite3_int64);
// Floating-point.
database_binder& operator<<(database_binder& db, float);
database_binder& operator<<(database_binder& db, double);
// Text — UTF-8 (std::string) or UTF-16 (std::u16string). C-string and
// string-literal forms must also be accepted (overloads for
// const char*, const char(&)[N], const char16_t*, const char16_t(&)[N]
// forwarding to the std::string / std::u16string variants), so
// `db << "insert into t values (?);" << "Dune";` compiles without an
// explicit std::string cast.
database_binder& operator<<(database_binder& db, const std::string&);
database_binder& operator<<(database_binder& db, const std::u16string&);
database_binder& operator<<(database_binder& db, const char*);
template <std::size_t N>
database_binder& operator<<(database_binder& db, const char (&)[N]);
database_binder& operator<<(database_binder& db, const char16_t*);
template <std::size_t N>
database_binder& operator<<(database_binder& db, const char16_t (&)[N]);
// Blob — std::vector<T> where T is integral or floating-point.
template <typename T, typename A>
database_binder& operator<<(database_binder& db, const std::vector<T, A>&);
// NULL — bind literal nullptr.
database_binder& operator<<(database_binder& db, std::nullptr_t);
// Nullable — std::unique_ptr<T> (binds value or NULL if empty) and
// std::optional<T> (binds value or NULL if !has_value()).
template <typename T>
database_binder& operator<<(database_binder& db, const std::unique_ptr<T>&);
template <typename OptionalT>
database_binder& operator<<(database_binder& db, const std::optional<OptionalT>&);
// std::variant — binds whichever alternative is currently active.
template <typename ...Args>
database_binder& operator<<(database_binder& db, const std::variant<Args...>&);
```

#### Extracting results

The extract-operator side of `database_binder::operator>>` runs the
statement and consumes its rows. Because it runs the statement, any
`operator>>` extraction also sets the executed-state flag: `used()`
returns true after an extraction (in any of the three forms below), just
as after `execute()`, and stays true until the next `reset()`. Three
forms:

```cpp
// 1. Single-row extraction into a bare value of any sqlite-marshallable
//    type. SQLite performs implicit type conversion when the column type
//    and the requested C++ type don't match (e.g. INTEGER -> std::string).
template <typename Result>
void operator>>(Result& value);

// 2. Single-row, multi-column extraction into a tuple of references
//    (use std::tie(a, b, ...)).
template <typename ...Types>
void operator>>(std::tuple<Types...>&& values);

// Row-count contract for forms (1) and (2):
//   sqlite::errors::no_rows   — the result set has zero rows.
//   sqlite::errors::more_rows — the result set has more than one row.
// Both apply to single-value extraction AND the std::tie tuple form,
// since both consume exactly one row.

// 3. Multi-row extraction via callback. The callable is invoked once
//    per row in SELECT order, with the row's columns expanded into
//    positional arguments to match the callable's parameter list. The
//    library deduces the per-column C++ type from the callable's
//    declared parameter types (typically via a function_traits helper
//    on the callable's signature) and constructs each argument fresh
//    per row from the corresponding SQLite column. Lambda parameters
//    may be passed by value or by reference; the library moves
//    extracted values into the parameters, so move-only types such as
//    std::unique_ptr<T> and std::optional<T> are supported as by-value
//    parameters.
template <typename Function>
void operator>>(Function&& func);
```

#### Re-executing a statement

```cpp
// Post-increment: equivalent to `db.execute(); db.reset();` in one go.
// Idiomatic for inserting many rows through one prepared statement
// (`stmt << v1 << v2; stmt++;` per row).
database_binder& operator++(database_binder& db, int);
```

After `execute()` returns, the statement holds "already executed" state.
Calling `execute()` again without an intervening `reset()` throws
`sqlite::errors::reexecution`.

### `enum class OpenFlags` and `struct sqlite_config`

```cpp
enum class OpenFlags {
    READONLY,
    READWRITE,
    CREATE,
    NOMUTEX,
    FULLMUTEX,
    SHAREDCACHE,
    PRIVATECACH,
    URI
};

OpenFlags operator|(const OpenFlags& a, const OpenFlags& b);

enum class Encoding {
    ANY,
    UTF8,
    UTF16
};

struct sqlite_config {
    OpenFlags  flags    = OpenFlags::READWRITE | OpenFlags::CREATE;
    const char* zVfs    = nullptr;
    Encoding   encoding = Encoding::ANY;
};
```

The flag values mirror the underlying `SQLITE_OPEN_*` constants. Pass a
`sqlite_config` as the second `database` constructor argument to control how
the connection is opened.

### Exception hierarchy — `<sqlite_modern_cpp.h>`

The library never returns SQLite error codes to the caller; instead it
throws. The base class lives in `namespace sqlite`; every derived class
lives in `namespace sqlite::errors`.

```cpp
namespace sqlite {
    class sqlite_exception : public std::runtime_error {
    public:
        int          get_code() const;           // primary SQLite error code (lower 8 bits, e.g. SQLITE_CONSTRAINT = 19)
        int          get_extended_code() const;  // full SQLite extended error code (e.g. SQLITE_CONSTRAINT_PRIMARYKEY = 1555)
        std::string  get_sql() const;            // SQL text that produced the error
    };
    // get_code() and get_extended_code() must return distinct values
    // when SQLite returns an extended code (the latter carries the full
    // 32-bit extended value from sqlite3_extended_errcode; the former is
    // that value masked to the lower 8 bits). Returning the masked
    // primary code from both accessors is not acceptable.

    namespace errors {
        // REQUIRED — one class per SQLite primary error code, all derived
        // from sqlite_exception. Names match the SQLite codes, lowercased
        // and with the SQLITE_ prefix removed:
        //   constraint, busy, locked, readonly, ioerr, corrupt, notfound,
        //   full, cantopen, protocol, empty, schema, toobig, mismatch,
        //   misuse, nolfs, auth, format, range, notadb, notice, warning,
        //   perm, abort, nomem, interrupt, error, internal
        //
        // REQUIRED — extended-code subclasses (each derived from its
        // primary class). The library must define and throw these for the
        // matching SQLite extended codes; the tests catch several of them
        // by name and a generic catch on the primary class is NOT
        // sufficient:
        //   constraint_check, constraint_commithook, constraint_foreignkey,
        //   constraint_function, constraint_notnull, constraint_primarykey,
        //   constraint_trigger, constraint_unique, constraint_vtab,
        //   constraint_rowid
        //   abort_rollback
        //   busy_recovery, busy_snapshot
        //   locked_sharedcache
        //   ioerr_read, ioerr_write, ioerr_fsync (and the rest of the
        //     SQLITE_IOERR_* family)
        //   corrupt_vtab
        //   cantopen_notempdir, cantopen_isdir (and the rest of the
        //     SQLITE_CANTOPEN_* family)
        //   notice_recover_wal, notice_recover_rollback
        //   warning_autoindex
        //   auth_user
        //
        // Dispatch rule: when an SQLite error fires, the library throws
        // the most specific extended-code subclass listed above whose
        // SQLite code matches; otherwise it throws the primary class;
        // otherwise it throws sqlite_exception directly. Specifically, a
        // PRIMARY KEY constraint violation must throw
        // errors::constraint_primarykey (not the parent errors::constraint).

        // Additional library-specific errors.
        class more_rows       : public sqlite_exception {};  // single-value extraction got > 1 row
        class no_rows         : public sqlite_exception {};  // single-value extraction got 0 rows
        class reexecution     : public sqlite_exception {};  // execute() called twice without reset()
        class more_statements : public sqlite_exception {};  // multiple ;-separated statements not supported
    }

    namespace exceptions = errors;  // alias
}
```

## Behaviour notes

- **`:memory:` databases.** Passing the string `":memory:"` to the
  `database` constructor opens an in-memory database (no file is created).
- **One statement per prepare.** Only one SQL statement per `database_binder`
  is allowed. SQL strings containing any non-empty second `;`-separated
  statement raise `sqlite::errors::more_statements`. Trailing whitespace
  or comments after the first statement's terminating `;` do not trigger
  the error; only a second non-empty statement does.
- **Implicit execute on destruction.** A `database_binder` that has never
  been executed and is not unwound by an in-flight exception is executed
  by its destructor. `db << "...";` therefore runs the statement when the
  temporary goes out of scope.
- **Type conversion on extraction.** Extracting a value into a C++ type
  whose SQLite type doesn't match the column type triggers SQLite's
  built-in conversion rules (INTEGER -> TEXT, REAL -> TEXT, etc.). For
  `std::variant<Ts...>` extraction, the actual SQLite column type
  determines which `Ts...` alternative receives the value; if no
  alternative is suitable for that column type the conversion throws
  `sqlite::errors::mismatch`. Nullable alternatives (`std::optional<T>`,
  `std::unique_ptr<T>`) in the variant receive NULL columns; a variant
  whose alternatives are all non-nullable raises
  `sqlite::errors::mismatch` when the column is NULL.
- **Transactions.** Plain SQL strings drive transactions:
  `db << "begin;"`, `db << "commit;"`, `db << "rollback;"`.
- **Encoding.** `std::string` parameters are bound as UTF-8 text;
  `std::u16string` as UTF-16. Extracting into `std::string` yields UTF-8,
  into `std::u16string` yields UTF-16.
- **NULL handling.** Binding `nullptr`, an empty `std::unique_ptr<T>`, or
  an empty `std::optional<T>` produces a SQL NULL value. Extracting a
  NULL column into `std::unique_ptr<T>` or `std::optional<T>` yields a
  null/empty wrapper.

## Includes

The single include `#include <sqlite_modern_cpp.h>` is enough to access the
entire public API used by the test suite — `database`, `database_binder`,
`sqlite_config`, `OpenFlags`, `Encoding`, `sqlite_exception`, and every
class in `sqlite::errors::*`. Tests may rely on this single-include
contract.
