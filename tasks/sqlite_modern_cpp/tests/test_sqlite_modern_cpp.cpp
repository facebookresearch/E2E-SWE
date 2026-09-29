// sqlite_modern_cpp WRG task — hidden test suite (gtest version).
//
// One TEST per behaviour, ported 1:1 from the pytest+subprocess+g++ version in
// CPP/sqlite_modern_cpp/tests/test_sqlite_modern_cpp.py. Where the pytest
// version compiled a tiny C++ driver per test and asserted on exact stdout
// strings, this version exercises the API directly and asserts on values via
// EXPECT_EQ / EXPECT_THROW etc. — no subprocess, no string parsing.
//
// The grader compiles this single file against the agent's installed
// sqlite_modern_cpp header(s) + libsqlite3 + gtest + pthread, runs the
// resulting binary with --gtest_output=xml, and converts the JUnit XML to
// CTRF JSON.
//
// All databases are in-memory (":memory:") except the readonly test which
// needs a real path so two connections can open the same file.

#include <gtest/gtest.h>
#include <sqlite_modern_cpp.h>

#include <cstdio>
#include <memory>
#include <optional>
#include <string>
#include <tuple>
#include <variant>
#include <vector>

using namespace sqlite;


// --- 1. Schema/insert/select with lambda + last_insert_rowid --------------
TEST(SqliteModernCpp, SchemaInsertSelectLambdaAndLastInsertRowid) {
    database db(":memory:");
    db << "create table books (id integer primary key, title text, author text, year integer);";
    db << "insert into books (title, author, year) values (?, ?, ?);" << "Dune" << "Herbert" << 1965;
    db << "insert into books (title, author, year) values (?, ?, ?);" << "Foundation" << "Asimov" << 1951;
    db << "insert into books (title, author, year) values (?, ?, ?);" << "The Hobbit" << "Tolkien" << 1937;

    EXPECT_EQ(db.last_insert_rowid(), 3);

    int count = 0;
    db << "select count(*) from books;" >> count;
    EXPECT_EQ(count, 3);

    // Multi-row, multi-column lambda extraction in SELECT order.
    std::vector<std::tuple<std::string, std::string, int>> rows;
    db << "select title, author, year from books where year < ? order by year;" << 1960
       >> [&](std::string title, std::string author, int year) {
           rows.emplace_back(std::move(title), std::move(author), year);
       };

    ASSERT_EQ(rows.size(), 2u);
    EXPECT_EQ(std::get<0>(rows[0]), "The Hobbit");
    EXPECT_EQ(std::get<1>(rows[0]), "Tolkien");
    EXPECT_EQ(std::get<2>(rows[0]), 1937);
    EXPECT_EQ(std::get<0>(rows[1]), "Foundation");
    EXPECT_EQ(std::get<1>(rows[1]), "Asimov");
    EXPECT_EQ(std::get<2>(rows[1]), 1951);
}


// --- 2. Prepared statement reuse: ++, reset, execute, used ----------------
TEST(SqliteModernCpp, PreparedStatementReuseIncrementResetExecuteUsed) {
    database db(":memory:");
    db << "create table nums (n integer);";

    // Repeated insert via prepared statement + `++` (execute + reset).
    auto ins = db << "insert into nums values (?);";
    for (int i = 1; i <= 5; ++i) {
        ins << i;
        ins++;
    }
    int total = 0;
    db << "select sum(n) from nums;" >> total;
    EXPECT_EQ(total, 15);

    // reset() clears bindings and lets the same statement be re-executed.
    auto sel = db << "select n from nums where n > ?;";
    sel << 3;
    int hits = 0;
    sel >> [&](int) { ++hits; };
    EXPECT_EQ(hits, 2);

    sel.reset();
    sel << 0;
    hits = 0;
    sel >> [&](int) { ++hits; };
    EXPECT_EQ(hits, 5);

    // explicit execute() without extraction.
    auto del = db << "delete from nums where n = ?;";
    del << 2;
    del.execute();
    int remaining = 0;
    db << "select count(*) from nums;" >> remaining;
    EXPECT_EQ(remaining, 4);

    // used() reports whether the statement has been executed.
    auto chk = db << "select 1;";
    EXPECT_FALSE(chk.used());
    int v = 0;
    chk >> v;
    EXPECT_TRUE(chk.used());
}


// --- 3. Type marshalling: int, int64, double, string, u16, blobs ---------
TEST(SqliteModernCpp, TypeMarshallingPrimitivesAndBlobs) {
    database db(":memory:");
    db << "create table types (i int, big bigint, d real, s text, w text, bi blob, bc blob, bd blob);";

    int i = 42;
    sqlite3_int64 big = 9000000000000LL;  // > 2^32, doesn't fit in 32-bit int
    double d = 3.14159265358979;
    std::string s = "ascii-string";
    std::u16string w = u"utf16";
    std::vector<int> bi{1, 2, 3, 4};
    std::vector<char> bc{'a', 'b', 'c'};
    std::vector<double> bd{1.5, 2.5, 3.5};

    db << "insert into types values (?, ?, ?, ?, ?, ?, ?, ?);"
       << i << big << d << s << w << bi << bc << bd;

    int ri = 0; sqlite3_int64 rbig = 0; double rd = 0;
    std::string rs; std::u16string rw;
    std::vector<int> rbi; std::vector<char> rbc; std::vector<double> rbd;
    db << "select * from types;"
       >> [&](int a, sqlite3_int64 b, double c, std::string e, std::u16string f,
              std::vector<int> g, std::vector<char> h, std::vector<double> j) {
           ri = a; rbig = b; rd = c; rs = e; rw = f; rbi = g; rbc = h; rbd = j;
       };

    EXPECT_EQ(ri, 42);
    EXPECT_EQ(rbig, 9000000000000LL);
    EXPECT_DOUBLE_EQ(rd, 3.14159265358979);
    EXPECT_EQ(rs, "ascii-string");
    EXPECT_EQ(rw.size(), 5u);
    EXPECT_EQ(rw, u"utf16");

    ASSERT_EQ(rbi.size(), 4u);
    EXPECT_EQ(rbi[0], 1);
    EXPECT_EQ(rbi[1], 2);
    EXPECT_EQ(rbi[2], 3);
    EXPECT_EQ(rbi[3], 4);

    ASSERT_EQ(rbc.size(), 3u);
    EXPECT_EQ(rbc[0], 'a');
    EXPECT_EQ(rbc[1], 'b');
    EXPECT_EQ(rbc[2], 'c');

    ASSERT_EQ(rbd.size(), 3u);
    EXPECT_DOUBLE_EQ(rbd[0], 1.5);
    EXPECT_DOUBLE_EQ(rbd[1], 2.5);
    EXPECT_DOUBLE_EQ(rbd[2], 3.5);

    // Automatic conversion: stored INTEGER extracted as std::string.
    std::string count_str;
    db << "select count(*) from types;" >> count_str;
    EXPECT_EQ(count_str, "1");
}


// --- 4. NULL handling via unique_ptr / nullptr / std::optional ------------
TEST(SqliteModernCpp, NullHandlingUniquePtrNullptrAndOptional) {
    database db(":memory:");
    db << "create table t (id integer primary key, age integer, name text);";

    // Bind nullptr literal directly to insert NULL.
    db << "insert into t values (?, ?, ?);" << 1 << 30 << "alice";
    db << "insert into t values (?, ?, ?);" << 2 << nullptr << nullptr;

    // Bind a populated unique_ptr<T> (becomes the underlying value).
    std::unique_ptr<int> ageP(new int(45));
    std::unique_ptr<std::string> nameP(new std::string("carol"));
    db << "insert into t values (?, ?, ?);" << 3 << ageP << nameP;

    // Bind an empty unique_ptr<T> (becomes NULL).
    std::unique_ptr<int> ageNull;
    std::unique_ptr<std::string> nameNull;
    db << "insert into t values (?, ?, ?);" << 4 << ageNull << nameNull;

    // Row 1: both non-null.
    {
        int got_age = -1;
        std::string got_name;
        bool age_set = false, name_set = false;
        db << "select age, name from t where id = ?;" << 1
           >> [&](std::unique_ptr<int> a, std::unique_ptr<std::string> n) {
               age_set = static_cast<bool>(a);
               name_set = static_cast<bool>(n);
               if (a) got_age = *a;
               if (n) got_name = *n;
           };
        EXPECT_TRUE(age_set);
        EXPECT_TRUE(name_set);
        EXPECT_EQ(got_age, 30);
        EXPECT_EQ(got_name, "alice");
    }

    // Row 2: both NULL (bound as nullptr literal).
    {
        bool age_set = true, name_set = true;
        db << "select age, name from t where id = ?;" << 2
           >> [&](std::unique_ptr<int> a, std::unique_ptr<std::string> n) {
               age_set = static_cast<bool>(a);
               name_set = static_cast<bool>(n);
           };
        EXPECT_FALSE(age_set);
        EXPECT_FALSE(name_set);
    }

    // Row 4: both NULL (bound via empty unique_ptr).
    {
        bool age_set = true, name_set = true;
        db << "select age, name from t where id = ?;" << 4
           >> [&](std::unique_ptr<int> a, std::unique_ptr<std::string> n) {
               age_set = static_cast<bool>(a);
               name_set = static_cast<bool>(n);
           };
        EXPECT_FALSE(age_set);
        EXPECT_FALSE(name_set);
    }

    // Row 5: std::optional round-trip — value + nullopt.
    std::optional<int> someAge = 99;
    std::optional<std::string> noName;
    db << "insert into t values (?, ?, ?);" << 5 << someAge << noName;
    {
        std::optional<int> got_age;
        std::optional<std::string> got_name;
        db << "select age, name from t where id = ?;" << 5
           >> [&](std::optional<int> a, std::optional<std::string> n) {
               got_age = a;
               got_name = n;
           };
        ASSERT_TRUE(got_age.has_value());
        EXPECT_EQ(*got_age, 99);
        EXPECT_FALSE(got_name.has_value());
    }

    // Row 6: nullopt -> NULL; value -> stored value.
    std::optional<int> none;
    db << "insert into t values (?, ?, ?);" << 6 << none << std::optional<std::string>("zzz");
    {
        std::optional<int> got_age;
        std::optional<std::string> got_name;
        db << "select age, name from t where id = ?;" << 6
           >> [&](std::optional<int> a, std::optional<std::string> n) {
               got_age = a;
               got_name = n;
           };
        EXPECT_FALSE(got_age.has_value());
        ASSERT_TRUE(got_name.has_value());
        EXPECT_EQ(*got_name, "zzz");
    }
}


// --- 5. Single-value + tuple extraction + auto-convert --------------------
TEST(SqliteModernCpp, SingleValueAndTupleExtraction) {
    database db(":memory:");
    db << "create table p (id integer, age integer, name text);";
    db << "insert into p values (?, ?, ?);" << 1 << 30 << "alice";
    db << "insert into p values (?, ?, ?);" << 2 << 40 << "bob";

    // Single value extraction (single column, single row).
    int single_count = 0;
    db << "select count(*) from p;" >> single_count;
    EXPECT_EQ(single_count, 2);

    int single_age = 0;
    db << "select age from p where id = ?;" << 2 >> single_age;
    EXPECT_EQ(single_age, 40);

    // std::tie for multi-column single-row.
    int age = 0;
    std::string name;
    db << "select age, name from p where id = ?;" << 1 >> std::tie(age, name);
    EXPECT_EQ(age, 30);
    EXPECT_EQ(name, "alice");

    // Automatic conversion: integer column extracted as std::string.
    std::string str_age;
    db << "select age from p where id = ?;" << 2 >> str_age;
    EXPECT_EQ(str_age, "40");
}


// --- 6. Transactions: begin / commit / rollback ---------------------------
TEST(SqliteModernCpp, TransactionsBeginCommitAndRollback) {
    database db(":memory:");
    db << "create table accounts (id integer primary key, balance integer);";
    db << "insert into accounts values (1, 100);";
    db << "insert into accounts values (2, 50);";

    // Committed transaction persists all changes.
    db << "begin;";
    db << "update accounts set balance = balance - 30 where id = 1;";
    db << "update accounts set balance = balance + 30 where id = 2;";
    db << "commit;";

    int b1 = 0, b2 = 0;
    db << "select balance from accounts where id = 1;" >> b1;
    db << "select balance from accounts where id = 2;" >> b2;
    EXPECT_EQ(b1, 70);
    EXPECT_EQ(b2, 80);

    // Rolled-back transaction reverts; mid-transaction reads see the in-flight write.
    db << "begin;";
    db << "update accounts set balance = balance - 999 where id = 1;";
    int mid = 0;
    db << "select balance from accounts where id = 1;" >> mid;
    EXPECT_EQ(mid, -929);
    db << "rollback;";

    int after = 0;
    db << "select balance from accounts where id = 1;" >> after;
    EXPECT_EQ(after, 70);
}


// --- 7. Exception hierarchy + metadata accessors --------------------------
TEST(SqliteModernCpp, ExceptionHierarchyAndMetadata) {
    database db(":memory:");
    db << "create table person (id integer primary key not null, name text not null);";

    // Duplicate primary key throws errors::constraint_primarykey (a constraint).
    db << "insert into person (id, name) values (?, ?);" << 1 << "alice";

    // Catch as the most specific class to confirm it's actually thrown
    // (rather than just sqlite_exception).
    bool got_pk = false;
    int code = -1, ecode = -1;
    std::string sql_text;
    try {
        db << "insert into person (id, name) values (?, ?);" << 1 << "alice";
    } catch (errors::constraint_primarykey& e) {
        got_pk = true;
        code = e.get_code();
        ecode = e.get_extended_code();
        sql_text = e.get_sql();
    }
    EXPECT_TRUE(got_pk);
    EXPECT_EQ(code, SQLITE_CONSTRAINT);  // primary code = 19
    EXPECT_EQ(code, 19);
    EXPECT_EQ(ecode, 1555);              // PRIMARYKEY extended code
    EXPECT_NE(sql_text.find("insert into person"), std::string::npos);

    // The base sqlite_exception catches every sqlite error.
    bool got_base = false;
    try {
        db << "insert into person (id, name) values (?, ?);" << 1 << "alice";
    } catch (sqlite_exception&) {
        got_base = true;
    }
    EXPECT_TRUE(got_base);

    // constraint_primarykey derives from constraint derives from sqlite_exception.
    try {
        db << "insert into person (id, name) values (?, ?);" << 1 << "alice";
    } catch (errors::constraint& e) {
        // Just confirm catching as the primary class also works.
        EXPECT_EQ(e.get_code(), SQLITE_CONSTRAINT);
    } catch (...) {
        FAIL() << "expected catch as errors::constraint";
    }

    // no_rows: single-value extraction with empty result.
    EXPECT_THROW(
        {
            int v = 0;
            db << "select id from person where id = ?;" << 999 >> v;
        },
        errors::no_rows);

    // more_rows: single-value extraction with > 1 matching row.
    db << "insert into person (id, name) values (?, ?);" << 2 << "bob";
    EXPECT_THROW(
        {
            int v = 0;
            db << "select id from person;" >> v;
        },
        errors::more_rows);

    // more_statements: only one statement per prepare is supported.
    EXPECT_THROW(
        { db << "select 1; select 2;"; },
        errors::more_statements);
}


// --- 8. User-defined scalar and aggregate functions -----------------------
TEST(SqliteModernCpp, UserDefinedScalarAndAggregateFunctions) {
    database db(":memory:");

    // Scalar UDF: returns sum of three ints.
    db.define("triple_sum", [](int a, int b, int c) { return a + b + c; });
    int s = 0;
    db << "select triple_sum(?, ?, ?);" << 10 << 20 << 30 >> s;
    EXPECT_EQ(s, 60);

    // Scalar UDF with string args.
    db.define("dashjoin", [](std::string a, std::string b) { return a + "-" + b; });
    std::string out;
    db << "select dashjoin('foo', 'bar');" >> out;
    EXPECT_EQ(out, "foo-bar");

    // Aggregate UDF: step(ctx, val) accumulates into ctx; final(ctx) returns.
    db.define(
        "sum_squares",
        [](int& acc, int v) { acc += v * v; },
        [](int& acc) { return acc; });

    db << "create table nums (n integer);";
    for (int i = 1; i <= 5; ++i) db << "insert into nums values (?);" << i;

    int agg = 0;
    db << "select sum_squares(n) from nums;" >> agg;
    EXPECT_EQ(agg, 55);  // 1+4+9+16+25

    // Scalar UDF composed inside an aggregate.
    db.define("inc", [](int x) { return x + 1; });
    int total = 0;
    db << "select sum(inc(n)) from nums;" >> total;
    EXPECT_EQ(total, 20);  // 2+3+4+5+6
}


// --- 9. OpenFlags::READONLY + sqlite_config + writes throw ----------------
TEST(SqliteModernCpp, SqliteConfigFlagsReadonlyAndLastInsertRowid) {
    // Two connections to the same on-disk DB; can't use ":memory:" here.
    const std::string path = std::string(::testing::TempDir()) + "/ro.db";
    std::remove(path.c_str());

    {
        database wdb(path);
        wdb << "create table t (n int);";
        wdb << "insert into t values (?);" << 7;
        wdb << "insert into t values (?);" << 14;
        EXPECT_EQ(wdb.last_insert_rowid(), 2);
    }

    sqlite_config cfg;
    cfg.flags = OpenFlags::READONLY;
    database db(path, cfg);

    int sum = 0;
    db << "select sum(n) from t;" >> sum;
    EXPECT_EQ(sum, 21);

    EXPECT_THROW(
        { db << "insert into t values (?);" << 99; },
        errors::readonly);

    std::remove(path.c_str());
}


// --- 10. Shared connection between database instances ---------------------
TEST(SqliteModernCpp, SharedConnectionBetweenDatabaseInstances) {
    database db(":memory:");
    db << "create table x (n int);";
    db << "insert into x values (1);";
    db << "insert into x values (2);";

    // Get the shared sqlite3 handle the db owns.
    auto conn = db.connection();
    int total = 0;
    {
        // Second database object sharing the same sqlite3 connection.
        database db2(conn);
        db2 << "select sum(n) from x;" >> total;
    }
    EXPECT_EQ(total, 3);

    // A write via db2 is visible from db (same underlying connection).
    int total2 = 0;
    {
        database db2(conn);
        db2 << "insert into x values (97);";
    }
    db << "select sum(n) from x;" >> total2;
    EXPECT_EQ(total2, 100);
}


// --- 11. Prepared statement re-execution requires reset -------------------
TEST(SqliteModernCpp, PreparedStatementReexecutionRequiresReset) {
    database db(":memory:");

    auto stmt = db << "select ?;";
    stmt << 1;
    stmt.execute();

    // Second execute() without intervening reset() throws.
    EXPECT_THROW(stmt.execute(), errors::reexecution);

    // After reset() + re-bind, execute() succeeds again.
    stmt.reset();
    stmt << 2;
    // Should not throw.
    EXPECT_NO_THROW(stmt.execute());
}


// --- 12. Variant column dispatch by SQLite type ---------------------------
//
// Variant uses non-overlapping value-type alternatives: one each for TEXT,
// INTEGER, and REAL. With this layout the spec's dispatch rule ("the actual
// SQLite column type determines which alternative receives the value")
// fully determines the result without depending on an unspecified
// tie-breaker between overlapping alternatives.
//
// std::string is placed first so the library's text-dispatch machinery can
// terminate immediately, and no nullable alternative is included so the
// spec's "if no alternative is suitable... throws errors::mismatch" branch
// is exercised by the NULL row.
TEST(SqliteModernCpp, VariantColumnDispatchBySqliteType) {
    database db(":memory:");
    db << "create table mixed (val);";  // dynamically typed column
    db << "insert into mixed values (?);" << 100;
    db << "insert into mixed values (?);" << 3.14;
    db << "insert into mixed values (?);" << "hello";
    db << "insert into mixed values (?);" << nullptr;

    using V = std::variant<std::string, sqlite3_int64, double>;

    struct Row {
        std::size_t index;
        std::string s;
        sqlite3_int64 i;
        double d;
    };
    std::vector<Row> rows;

    // First three rows: each has a distinct SQLite value type with exactly one
    // matching variant alternative.
    db << "select val from mixed where rowid <= 3 order by rowid;" >> [&](V v) {
        Row r{v.index(), {}, 0, 0.0};
        if (v.index() == 0)      r.s = std::get<0>(v);
        else if (v.index() == 1) r.i = std::get<1>(v);
        else if (v.index() == 2) r.d = std::get<2>(v);
        rows.push_back(std::move(r));
    };

    ASSERT_EQ(rows.size(), 3u);

    // R1: INTEGER 100 -> alternative #1 (sqlite3_int64), the sole integral alternative.
    EXPECT_EQ(rows[0].index, 1u);
    EXPECT_EQ(rows[0].i, 100);

    // R2: REAL 3.14 -> alternative #2 (double), the sole floating-point alternative.
    EXPECT_EQ(rows[1].index, 2u);
    EXPECT_NEAR(rows[1].d, 3.14, 1e-9);

    // R3: TEXT "hello" -> alternative #0 (std::string), the sole text alternative.
    EXPECT_EQ(rows[2].index, 0u);
    EXPECT_EQ(rows[2].s, "hello");

    // R4 with a non-nullable variant: no alternative is nullable, so per spec
    // the conversion raises errors::mismatch.
    EXPECT_THROW(
        { db << "select val from mixed where rowid = 4;" >> [&](V) {}; },
        errors::mismatch);

    // R4 with a nullable alternative present: per spec, "nullable alternatives
    // receive NULL columns" — std::optional<int> is engaged but empty.
    using VNullable = std::variant<std::string, std::optional<int>>;
    bool null_to_optional = false;
    db << "select val from mixed where rowid = 4;" >> [&](VNullable v) {
        null_to_optional = (v.index() == 1 && !std::get<1>(v).has_value());
    };
    EXPECT_TRUE(null_to_optional);
}
