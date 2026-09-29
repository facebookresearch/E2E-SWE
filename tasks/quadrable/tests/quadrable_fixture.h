// Shared gtest fixture for every quadrable test module. Each TEST_F gets a
// fresh LMDB environment rooted at a unique /tmp tempdir + a fresh
// `quadrable::Quadrable` instance with its DBIs initialized. This mirrors the
// upstream check.cpp lmdb::env::create + set_max_dbs + set_mapsize + open
// dance so every test starts from a truly empty tree.
//
// This header is a test fixture, not a library header -- it lives under
// /tests/ and is not part of the coverage measurement's header allowlist.

#pragma once

#include <gtest/gtest.h>
#include <quadrable.h>

#include <cstdlib>
#include <memory>
#include <string>

namespace quadrable_test {

// Wraps an LMDB env at a tempdir. Constructed in SetUp() so the env open() is
// deferred until fixture setup rather than at class-instance construction
// (`lmdb::env::create()` returns by-value; we need to hold it and then open()
// on the same instance).
class QuadrableFixture : public ::testing::Test {
  protected:
    std::string db_dir;
    std::unique_ptr<lmdb::env> env_ptr;
    quadrable::Quadrable db;

    void SetUp() override {
        char tmpl[] = "/tmp/quadtest_XXXXXX";
        char* dir = mkdtemp(tmpl);
        ASSERT_NE(dir, nullptr) << "mkdtemp failed";
        db_dir = dir;

        env_ptr = std::make_unique<lmdb::env>(lmdb::env::create());
        env_ptr->set_max_dbs(64);
        // 1 GiB mapsize -- generous enough for every test in the suite;
        // upstream check.cpp uses 1 TiB but that's overkill here.
        env_ptr->set_mapsize(1UL * 1024UL * 1024UL * 1024UL);
        env_ptr->open(db_dir.c_str(), MDB_CREATE, 0664);

        auto txn = lmdb::txn::begin(*env_ptr, nullptr, 0);
        db.init(txn);
        txn.commit();
    }

    void TearDown() override {
        // Release the env (closes file descriptors, unmaps memory) BEFORE
        // deleting the tempdir. lmdb::env's destructor calls mdb_env_close.
        env_ptr.reset();
        if (!db_dir.empty()) {
            std::string cmd = "rm -rf '" + db_dir + "'";
            // Silence -Wunused-result: shell rm failure at teardown is not a
            // test failure signal (the test already passed/failed on its own).
            (void)!std::system(cmd.c_str());
        }
    }

    // Convenience: open a fresh writable transaction against the fixture env.
    // Callers own the returned txn (commit or abort themselves).
    lmdb::txn beginTxn() { return lmdb::txn::begin(*env_ptr, nullptr, 0); }
};

}  // namespace quadrable_test
