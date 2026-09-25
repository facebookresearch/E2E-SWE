// End-to-end raft cluster tests. All tests spin up a 3- or 4-node cluster
// wired over an in-process msg_bus (patterned after upstream test_impls.cxx
// and test_everything_together.cxx — avoids real TCP so tests stay
// deterministic and offline). Each test verifies a documented public-API
// contract of raft_server / state_machine / state_mgr:
//
//   * ElectsLeaderFromColdStart   — raft_event_listener::become_leader fires.
//   * CommitsClientRequestPayload — state_machine::commit fires after a
//                                   client_request is accepted.
//   * AddServerJoinsAndCatchesUp  — raft_server::add_srv completes and the
//                                   joining node's logs_catch_up event fires
//                                   within the deadline.
//   * RemoveServerLeavesClusterFunctional — raft_server::remove_srv completes
//                                   and the remaining nodes still commit
//                                   subsequent client_requests.
//   * SnapshotCreationFiresAtDistance    — with snapshot_distance set, the
//                                   leader invokes state_machine::create_
//                                   snapshot after enough committed entries
//                                   to cross the threshold. Install half
//                                   (leader ships bytes to a partitioned+
//                                   rejoined follower) is compile-tested
//                                   only; the reference cornerstone's
//                                   install path SIGSEGVs when exercised
//                                   end-to-end (root-cause unresolved).
//   * PrevotePreventsTermInflationOnPartition — with prevote enabled, a
//                                   temporarily partitioned follower does
//                                   NOT bump its persisted term by more than
//                                   a small bounded amount before rejoining.
//   * LeaderFailoverElectsNewLeaderAndKeepsCommitting — killing the leader
//                                   forces a new election within 4s and the
//                                   cluster keeps committing client_requests.
//   * ElectionSafetyAtMostOneLeaderPerTerm — for every unique term seen,
//                                   at most one server ever fired
//                                   become_leader at that term.
//   * LogMatchingAllNodesAgreeOnCommittedEntries — after 5 commits, all
//                                   3 nodes' state_machine::commit sequences
//                                   agree byte-for-byte up to the shortest.
//   * MinorityPartitionCannotCommit — leader isolated from all followers
//                                   cannot commit a subsequent
//                                   client_request payload.
//   * LeaderStepsDownOnHigherTermSeen — injecting a vote_request with
//                                   term = leader_term + 5 forces the leader
//                                   to update_term + become_follower.
//   * LogDivergenceForcesFollowerTruncation — a partitioned old leader
//                                   with uncommitted phantom entries has
//                                   them truncated by the new leader's
//                                   append_entries term-mismatch handling.
//   * ElectionRestrictionStaleCandidateLoses — a stale-log candidate with
//                                   a shorter election timeout cannot win
//                                   an election (Raft §5.4.1).
//
// The in-process msg_bus supports set_paused(bool) per DESTINATION port
// (inbound partition) and set_outbound_paused(port, bool) per SOURCE
// port (isolate one node's outbound entirely — used for failover tests
// to fully "kill" the leader without destroying its raft_server).

#include <gtest/gtest.h>

#include <cornerstone/cornerstone.hxx>

#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#include <csignal>
#include <cstring>
#include <execinfo.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <exception>
#include <memory>
#include <mutex>
#include <new>
#include <queue>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

using namespace cornerstone;

// ---------------------------------------------------------------------------
// SIGSEGV backtrace handler — installed at static-init time so it's live
// for every test in the raft_cluster binary. On segfault, dumps up to 64
// stack frames to stderr via glibc's backtrace_symbols_fd (async-safe;
// safer than fprintf in a signal handler). Then re-raises SIGSEGV with
// SIG_DFL so the process still crashes for the test.sh subprocess exit-
// code check. Used to diagnose the install-pipeline crash in
// LateFollowerCatchesUpViaSnapshot — the base image doesn't ship gdb or
// catchsegv, so this is the cheapest path to a usable backtrace.
// ---------------------------------------------------------------------------
namespace {
void sigsegv_backtrace_handler(int sig)
{
    void* frames[64];
    int n = backtrace(frames, 64);
    const char* hdr = "\n=== SIGSEGV backtrace (up to 64 frames) ===\n";
    ssize_t w = ::write(2, hdr, strlen(hdr));
    (void)w;
    backtrace_symbols_fd(frames, n, 2);
    const char* ftr = "=== end SIGSEGV backtrace ===\n";
    w = ::write(2, ftr, strlen(ftr));
    (void)w;
    signal(sig, SIG_DFL);
    raise(sig);
}

struct install_sigsegv_handler_t {
    install_sigsegv_handler_t() { signal(SIGSEGV, sigsegv_backtrace_handler); }
};
install_sigsegv_handler_t _install_sigsegv_handler;
} // namespace

// ---------------------------------------------------------------------------
// Test scaffolding: pause-capable msg_bus + instrumented state_mgr /
// state_machine / rpc_listener / rpc_client. Same shape as upstream
// tests/src/test_impls.cxx so we're testing the same core against the same
// integration harness.
// ---------------------------------------------------------------------------

namespace
{

// state_machine::commit records the payload string for later inspection,
// plus counters + snapshot-byte-round-trip buffers for the install-pipeline
// end-to-end test.
struct commit_recorder
{
    std::mutex mu;
    std::vector<std::string> committed;
    std::atomic<size_t> create_snapshot_calls{0};
    std::atomic<size_t> apply_snapshot_calls{0};
    std::atomic<size_t> save_snapshot_data_calls{0};
    std::atomic<size_t> read_snapshot_data_calls{0};

    // Leader-side: bytes materialized by create_snapshot. Follower-side:
    // bytes received via save_snapshot_data. Both protected by snap_mu.
    std::mutex snap_mu;
    std::vector<byte> snap_bytes;       // leader-produced snapshot payload
    std::vector<byte> received_snap;    // follower-received bytes
    bool applied_snapshot_matches = false;

    void record(buffer& data)
    {
        std::lock_guard<std::mutex> g(mu);
        committed.emplace_back(reinterpret_cast<const char*>(data.data()));
    }

    size_t count()
    {
        std::lock_guard<std::mutex> g(mu);
        return committed.size();
    }

    // Locked snapshot copy of the committed vector for the log-matching
    // invariant test (need to compare per-index equality across nodes).
    std::vector<std::string> snapshot_committed()
    {
        std::lock_guard<std::mutex> g(mu);
        return committed;
    }
};

// Forward decl — the snapshot_byte_registry class is defined a few lines
// below; cluster_state holds a shared_ptr to it so every raft_node in a
// test shares the same registry.
class snapshot_byte_registry;

struct cluster_state
{
    std::unordered_map<int32, std::shared_ptr<commit_recorder>> recorders;
    std::atomic<int> leader_count{0};
    std::atomic<int> current_leader_id{-1};
    std::atomic<int> logs_catch_up_srv{-1};
    std::mutex saved_terms_mu;
    std::unordered_map<int32, ulong> max_saved_term;
    std::shared_ptr<snapshot_byte_registry> snap_registry;

    // Records (term_at_become_leader, srv_id) tuples across the whole
    // test lifetime — for the election-safety invariant test.
    std::mutex leader_events_mu;
    std::vector<std::pair<ulong, int32>> leader_events;

    // Set of server ids that ever fired become_follower — for the
    // step-down-on-higher-term-seen test.
    std::mutex became_follower_mu;
    std::unordered_set<int32> became_follower_ids;
};

// state_machine that records commit payloads AND implements the full
// snapshot install pipeline as a real byte round-trip:
//
//   Leader side:
//     create_snapshot(s, when_done) -> materialize snap_bytes_ (a small
//       deterministic payload; here it's `<magic>|<last_log_idx>` encoded
//       as bytes, which is enough for the follower to verify equality);
//       stash snap_bytes into commit_recorder.snap_bytes so the follower's
//       side (which holds ITS OWN commit_recorder) can verify byte-for-byte
//       later; store the snapshot in last_snapshot_; invoke when_done(true)
//       from a detached thread (synchronous invocation caused a SIGSEGV
//       earlier because cornerstone's snapshot_and_compact reenters itself).
//     read_snapshot_data(s, offset, data) -> serve bytes from snap_bytes_
//       in chunks; return min(data.size(), snap_bytes_.size() - offset);
//       return 0 when offset >= snap_bytes_.size() (chunk-stream done).
//     last_snapshot() -> the last create_snapshot()d snapshot.
//
//   Follower side:
//     save_snapshot_data(s, offset, data) -> append the received bytes
//       into received_snap_ (positioned at offset).
//     apply_snapshot(s) -> compare received_snap_ against the sender's
//       snap_bytes_ (looked up via a shared registry keyed on
//       s.get_last_log_idx()); set applied_snapshot_matches accordingly.
//
// A "sender_registry" maps <last_log_idx> -> the leader's snap_bytes so
// followers can verify byte equality on apply. This is the missing piece
// that made the zero-byte stub crash cornerstone's install machinery: the
// leader now serves a real payload, the follower saves and reconstructs
// it, and apply_snapshot verifies the round-trip.
class snapshot_byte_registry
{
public:
    void store(ulong last_log_idx, const std::vector<byte>& bytes)
    {
        std::lock_guard<std::mutex> g(mu_);
        by_idx_[last_log_idx] = bytes;
    }
    std::vector<byte> load(ulong last_log_idx)
    {
        std::lock_guard<std::mutex> g(mu_);
        auto it = by_idx_.find(last_log_idx);
        if (it == by_idx_.end()) return {};
        return it->second;
    }

private:
    std::mutex mu_;
    std::unordered_map<ulong, std::vector<byte>> by_idx_;
};

class recording_state_machine : public state_machine
{
public:
    recording_state_machine(std::shared_ptr<commit_recorder> rec,
                            std::shared_ptr<snapshot_byte_registry> reg)
        : rec_(std::move(rec)), reg_(std::move(reg))
    {
    }

    void commit(const ulong, buffer& data, const uptr<log_entry_cookie>&) override { rec_->record(data); }
    void pre_commit(const ulong, buffer&, const uptr<log_entry_cookie>&) override {}
    void rollback(const ulong, buffer&, const uptr<log_entry_cookie>&) override {}

    void save_snapshot_data(snapshot&, const ulong offset, buffer& data) override
    {
        rec_->save_snapshot_data_calls.fetch_add(1);
        size_t n = data.size() - data.pos();
        if (n == 0) return;
        std::lock_guard<std::mutex> g(rec_->snap_mu);
        if (rec_->received_snap.size() < offset + n)
        {
            rec_->received_snap.resize(offset + n, 0);
        }
        // buffer::data() points at the current read position.
        const byte* src = data.data();
        for (size_t i = 0; i < n; ++i) rec_->received_snap[offset + i] = src[i];
    }

    bool apply_snapshot(snapshot& s) override
    {
        rec_->apply_snapshot_calls.fetch_add(1);
        // Look up the leader's original snap_bytes for this snapshot's
        // last_log_idx and verify byte-for-byte equality with what we
        // received via save_snapshot_data.
        std::vector<byte> expected = reg_->load(s.get_last_log_idx());
        {
            std::lock_guard<std::mutex> g(rec_->snap_mu);
            rec_->applied_snapshot_matches =
                (!expected.empty() && expected == rec_->received_snap);
        }
        // ----- IMPORTANT: publish this snapshot as our own last_snapshot_.
        // After apply_snapshot completes on a follower, cornerstone's
        // raft_server may look up term_for_log() for a log index that
        // predates the just-installed snapshot boundary. term_for_log
        // falls through to state_machine_->last_snapshot() for indices <
        // start_index; if we don't publish anything here, that call
        // returns null and the follower dereferences a null snapshot on
        // the next append_entries roundtrip. Reconstruct with the same
        // idx/term/config/size we just installed.
        {
            std::lock_guard<std::mutex> g(snap_mu_);
            last_snapshot_ = cs_new<snapshot>(
                s.get_last_log_idx(), s.get_last_log_term(), s.get_last_config(), s.size());
        }
        return true;
    }

    int read_snapshot_data(snapshot&, const ulong offset, buffer& data) override
    {
        rec_->read_snapshot_data_calls.fetch_add(1);
        std::lock_guard<std::mutex> g(rec_->snap_mu);
        if (offset >= rec_->snap_bytes.size()) return 0;
        size_t cap = data.size() - data.pos();
        size_t n = std::min(cap, rec_->snap_bytes.size() - static_cast<size_t>(offset));
        if (n == 0) return 0;
        // Copy [snap_bytes+offset, +n) into the buffer's remaining region.
        byte* dst = data.data();
        for (size_t i = 0; i < n; ++i) dst[i] = rec_->snap_bytes[offset + i];
        return static_cast<int>(n);
    }

    ptr<snapshot> last_snapshot() override
    {
        std::lock_guard<std::mutex> g(snap_mu_);
        return last_snapshot_;
    }

    ulong last_commit_index() override { return 0; }

    void create_snapshot(snapshot& s, async_result<bool>::handler_type& handler) override
    {
        rec_->create_snapshot_calls.fetch_add(1);
        // Materialize a small deterministic snapshot payload keyed by
        // last_log_idx (the exact bytes don't matter — what matters is the
        // byte-for-byte round-trip through save_snapshot_data +
        // apply_snapshot verification on the receiving side).
        std::string tag = "SNAP|" + std::to_string(s.get_last_log_idx()) + "|"
                          + std::to_string(s.get_last_log_term());
        std::vector<byte> bytes(tag.begin(), tag.end());
        {
            std::lock_guard<std::mutex> g(rec_->snap_mu);
            rec_->snap_bytes = bytes;
        }
        // Publish to the cross-node registry so followers verify equality.
        reg_->store(s.get_last_log_idx(), bytes);
        {
            std::lock_guard<std::mutex> g(snap_mu_);
            last_snapshot_ = cs_new<snapshot>(
                s.get_last_log_idx(), s.get_last_log_term(), s.get_last_config(),
                static_cast<ulong>(bytes.size()));
        }
        // ----- UPSTREAM WORKAROUND: rebuild `s` in-place with correct size.
        // Cornerstone's snapshot_and_compact creates the snapshot object
        // with size=0 (see src/raft_server.cxx:589), passes it to us by
        // reference, then stores our modified copy in `last_snapshot_`.
        // Later, create_sync_snapshot_req reads that snapshot's `.size()`
        // and rejects any snapshot with `size < 1L` — the install path
        // never fires. `snapshot` has no `set_size()` method, so we
        // destroy `s` in-place and reconstruct it with the real size via
        // placement-new. Because raft_server captures `s` via a
        // ptr<snapshot> that aliases the same storage, this repairs the
        // size that create_sync_snapshot_req will later observe. All
        // fields other than `size_` are preserved (idx/term/config).
        {
            ulong idx = s.get_last_log_idx();
            ulong term = s.get_last_log_term();
            ptr<cluster_config> conf = s.get_last_config();
            s.~snapshot();
            new (&s) snapshot(idx, term, conf, static_cast<ulong>(bytes.size()));
        }
        // Defer handler invocation onto a detached thread so we don't
        // reenter raft_server internals (snapshot_and_compact holds a
        // lock while calling us; sync invocation triggered SIGSEGV).
        auto handler_copy = handler;
        std::thread([handler_copy]() mutable {
            bool ok = true;
            ptr<std::exception> no_err;
            handler_copy(ok, no_err);
        }).detach();
    }

private:
    std::shared_ptr<commit_recorder> rec_;
    std::shared_ptr<snapshot_byte_registry> reg_;
    std::mutex snap_mu_;
    ptr<snapshot> last_snapshot_;
};

class mem_log_store : public log_store
{
public:
    mem_log_store() : entries_() { entries_.push_back(cs_new<log_entry>(0L, buffer::alloc(0))); }

    ulong next_slot() const override { std::lock_guard<std::mutex> g(m_); return start_idx_ + entries_.size() - 1; }
    ulong start_index() const override { std::lock_guard<std::mutex> g(m_); return start_idx_; }

    ptr<log_entry> last_entry() const override
    {
        std::lock_guard<std::mutex> g(m_);
        return entries_.back();
    }

    ulong append(ptr<log_entry>& e) override
    {
        std::lock_guard<std::mutex> g(m_);
        entries_.push_back(e);
        return start_idx_ + entries_.size() - 2;
    }

    void write_at(ulong idx, ptr<log_entry>& e) override
    {
        std::lock_guard<std::mutex> g(m_);
        if (idx < start_idx_) throw std::overflow_error("write_at OOB (below start)");
        size_t off = static_cast<size_t>(idx - start_idx_ + 1);
        if (off == 0 || off >= entries_.size()) throw std::overflow_error("write_at OOB (above end)");
        entries_[off] = e;
        if (entries_.size() - off > 1)
        {
            entries_.erase(entries_.begin() + off + 1, entries_.end());
        }
    }

    ptr<std::vector<ptr<log_entry>>> log_entries(ulong start, ulong end) override
    {
        std::lock_guard<std::mutex> g(m_);
        if (start >= end || start < start_idx_) return nullptr;
        size_t s = static_cast<size_t>(start - start_idx_ + 1);
        size_t e_off = static_cast<size_t>(end - start_idx_ + 1);
        if (s >= entries_.size()) return nullptr;
        if (e_off > entries_.size()) e_off = entries_.size();
        auto v = cs_new<std::vector<ptr<log_entry>>>();
        for (size_t i = s; i < e_off; ++i) v->push_back(entries_[i]);
        return v;
    }

    ptr<log_entry> entry_at(ulong idx) override
    {
        std::lock_guard<std::mutex> g(m_);
        if (idx < start_idx_) return nullptr;
        size_t off = static_cast<size_t>(idx - start_idx_ + 1);
        if (off == 0 || off >= entries_.size()) return nullptr;
        return entries_[off];
    }

    ulong term_at(ulong idx) override
    {
        std::lock_guard<std::mutex> g(m_);
        if (idx < start_idx_) return 0;
        size_t off = static_cast<size_t>(idx - start_idx_ + 1);
        if (off == 0 || off >= entries_.size()) return 0;
        return entries_[off]->get_term();
    }

    bufptr pack(ulong, int32) override { return buffer::alloc(0); }
    void apply_pack(ulong, buffer&) override {}

    bool compact(ulong last_log_index) override
    {
        std::lock_guard<std::mutex> g(m_);
        if (last_log_index < start_idx_) return true;
        size_t drop = static_cast<size_t>(last_log_index - start_idx_ + 1);
        if (drop >= entries_.size()) drop = entries_.size() - 1;
        entries_.erase(entries_.begin() + 1, entries_.begin() + 1 + drop);
        start_idx_ = last_log_index + 1;
        return true;
    }

private:
    mutable std::mutex m_;
    std::vector<ptr<log_entry>> entries_;
    ulong start_idx_{1};
};

class mem_state_mgr : public state_mgr
{
public:
    mem_state_mgr(int32 srv_id, std::vector<ptr<srv_config>> cluster, cluster_state* cs)
        : srv_id_(srv_id), cluster_(std::move(cluster)), cs_(cs)
    {
    }

    ptr<cluster_config> load_config() override
    {
        auto c = cs_new<cluster_config>();
        for (const auto& s : cluster_) c->get_servers().push_back(s);
        return c;
    }
    void save_config(const cluster_config&) override {}

    void save_state(const srv_state& s) override
    {
        if (!cs_) return;
        std::lock_guard<std::mutex> g(cs_->saved_terms_mu);
        auto& cur = cs_->max_saved_term[srv_id_];
        if (s.get_term() > cur) cur = s.get_term();
    }
    ptr<srv_state> read_state() override { return cs_new<srv_state>(); }

    ptr<log_store> load_log_store() override
    {
        std::lock_guard<std::mutex> g(mu_);
        if (!ls_) ls_ = cs_new<mem_log_store>();
        return ls_;
    }
    int32 server_id() override { return srv_id_; }
    void system_exit(const int) override {}

private:
    int32 srv_id_;
    std::vector<ptr<srv_config>> cluster_;
    cluster_state* cs_;
    std::mutex mu_;
    ptr<mem_log_store> ls_;
};

class null_logger : public logger
{
public:
    void debug(const std::string&) override {}
    void info(const std::string&) override {}
    void warn(const std::string&) override {}
    void err(const std::string&) override {}
};

// In-memory message bus routing req_msg / async<resp_msg> between servers.
// Supports per-port set_paused(bool). While paused, incoming messages are
// dropped and the sender's async_result immediately errors — same shape as
// a TCP connection failure.
class msg_bus
{
public:
    using message = std::pair<ptr<req_msg>, ptr<async_result<ptr<resp_msg>>>>;

    class queue
    {
    public:
        queue() : stopped_(false), paused_(false) {}

        void enqueue(const message& m)
        {
            {
                std::lock_guard<std::mutex> g(mu_);
                if (!paused_ && !stopped_)
                {
                    q_.push(m);
                    cv_.notify_one();
                    return;
                }
            }
            // Release the queue lock BEFORE firing the callback so a slow
            // handler can't stall the bus. Simulate "connection refused".
            ptr<std::exception> err = cs_new<std::runtime_error>("partition");
            ptr<resp_msg> no_resp;
            m.second->set_result(no_resp, err);
        }

        message dequeue()
        {
            std::unique_lock<std::mutex> lk(mu_);
            cv_.wait(lk, [this]() { return (!q_.empty() && !paused_) || stopped_; });
            if (stopped_ && q_.empty()) return {nullptr, nullptr};
            message m = q_.front();
            q_.pop();
            return m;
        }

        void set_paused(bool p)
        {
            { std::lock_guard<std::mutex> g(mu_); paused_ = p; }
            cv_.notify_all();
        }

        void stop()
        {
            { std::lock_guard<std::mutex> g(mu_); stopped_ = true; }
            cv_.notify_all();
        }

    private:
        std::mutex mu_;
        std::condition_variable cv_;
        std::queue<message> q_;
        bool stopped_;
        bool paused_;
    };

    msg_bus(const std::vector<std::string>& ports)
    {
        for (const auto& p : ports) queues_[p] = std::make_shared<queue>();
    }

    std::shared_ptr<queue> get(const std::string& port)
    {
        auto it = queues_.find(port);
        if (it == queues_.end()) throw std::runtime_error("bad port: " + port);
        return it->second;
    }

    void stop_all() { for (auto& kv : queues_) kv.second->stop(); }

    // Source-port outbound blocking: if set, any mem_rpc_client whose
    // self_port matches this will immediately fail sends with an
    // rpc_exception (no message ever enters any dest queue). This
    // simulates a full network isolation of one node (both directions
    // dropped from that node's outbound perspective). Used by the
    // failover test to "kill" the leader without needing to destroy
    // its raft_server (which would UAF asio timers).
    void set_outbound_paused(const std::string& src_port, bool p)
    {
        std::lock_guard<std::mutex> g(outbound_mu_);
        outbound_paused_[src_port] = p;
    }

    bool is_outbound_paused(const std::string& src_port)
    {
        std::lock_guard<std::mutex> g(outbound_mu_);
        auto it = outbound_paused_.find(src_port);
        return it != outbound_paused_.end() && it->second;
    }

private:
    std::unordered_map<std::string, std::shared_ptr<queue>> queues_;
    std::mutex outbound_mu_;
    std::unordered_map<std::string, bool> outbound_paused_;
};

class mem_rpc_client : public rpc_client
{
public:
    mem_rpc_client(std::shared_ptr<msg_bus::queue> dst,
                   std::string self_port,
                   std::shared_ptr<msg_bus> bus)
        : dst_(std::move(dst)), self_port_(std::move(self_port)), bus_(std::move(bus))
    {
    }

    void send(ptr<req_msg>& req, rpc_handler& when_done) override
    {
        // Check source-port outbound block first (simulates our node
        // being fully isolated — even outbound sends fail immediately).
        if (bus_ && bus_->is_outbound_paused(self_port_))
        {
            ptr<rpc_exception> ex = cs_new<rpc_exception>("outbound_blocked", req);
            ptr<resp_msg> none;
            when_done(none, ex);
            return;
        }

        auto result = cs_new<async_result<ptr<resp_msg>>>();
        result->when_ready([req, when_done](ptr<resp_msg>& resp, const ptr<std::exception>& err) {
            if (err)
            {
                ptr<rpc_exception> ex = cs_new<rpc_exception>(err->what(), req);
                ptr<resp_msg> none;
                when_done(none, ex);
            }
            else
            {
                ptr<rpc_exception> none;
                when_done(resp, none);
            }
        });

        // Deep-copy req + its log_entries so sender and receiver don't share
        // mutable state (matches upstream test_impls.cxx).
        auto copy = cs_new<req_msg>(req->get_term(), req->get_type(), req->get_src(), req->get_dst(),
                                    req->get_last_log_term(), req->get_last_log_idx(), req->get_commit_idx());
        for (const auto& e : req->log_entries())
        {
            bufptr b = buffer::copy(e->get_buf());
            copy->log_entries().push_back(cs_new<log_entry>(e->get_term(), std::move(b), e->get_val_type()));
        }
        dst_->enqueue({copy, result});
    }

private:
    std::shared_ptr<msg_bus::queue> dst_;
    std::string self_port_;
    std::shared_ptr<msg_bus> bus_;
};

class mem_rpc_factory : public rpc_client_factory
{
public:
    // Per-node factory: `self_port` is the port of the node this factory
    // was built for. All clients created from this factory tag their
    // outbound sends with this self_port so msg_bus::set_outbound_paused
    // can isolate them.
    mem_rpc_factory(std::shared_ptr<msg_bus> bus, std::string self_port)
        : bus_(std::move(bus)), self_port_(std::move(self_port))
    {
    }

    ptr<rpc_client> create_client(const std::string& endpoint) override
    {
        return cs_new<mem_rpc_client>(bus_->get(endpoint), self_port_, bus_);
    }

private:
    std::shared_ptr<msg_bus> bus_;
    std::string self_port_;
};

class mem_rpc_listener : public rpc_listener
{
public:
    mem_rpc_listener(std::shared_ptr<msg_bus::queue> q) : queue_(std::move(q)), stopped_(false) {}

    void listen(ptr<msg_handler>& handler) override
    {
        std::thread t([this, handler]() {
            while (!stopped_.load())
            {
                auto msg = queue_->dequeue();
                if (!msg.first) break;
                ptr<resp_msg> resp = handler->process_req(*msg.first);
                if (stopped_.load()) break;
                ptr<std::exception> no_err;
                msg.second->set_result(resp, no_err);
            }
        });
        t.detach();
    }

    void stop() override { stopped_.store(true); queue_->stop(); }

private:
    std::shared_ptr<msg_bus::queue> queue_;
    std::atomic<bool> stopped_;
};

class event_watcher : public raft_event_listener
{
public:
    event_watcher(cluster_state& cs, int32 id) : cs_(cs), id_(id) {}

    void on_event(raft_event ev) override
    {
        if (ev == raft_event::become_leader)
        {
            cs_.leader_count.fetch_add(1);
            cs_.current_leader_id.store(id_);
            // Sample the term at become_leader for the election-safety
            // invariant test. mem_state_mgr::save_state populates
            // max_saved_term BEFORE become_leader fires (raft persists
            // term before transitioning), so this read is well-defined.
            ulong term = 0;
            {
                std::lock_guard<std::mutex> g(cs_.saved_terms_mu);
                auto it = cs_.max_saved_term.find(id_);
                if (it != cs_.max_saved_term.end()) term = it->second;
            }
            std::lock_guard<std::mutex> g(cs_.leader_events_mu);
            cs_.leader_events.emplace_back(term, id_);
        }
        else if (ev == raft_event::become_follower)
        {
            std::lock_guard<std::mutex> g(cs_.became_follower_mu);
            cs_.became_follower_ids.insert(id_);
        }
        else if (ev == raft_event::logs_catch_up)
        {
            cs_.logs_catch_up_srv.store(id_);
        }
    }

private:
    cluster_state& cs_;
    int32 id_;
};

struct raft_node
{
    ptr<raft_server> server;
    ptr<rpc_listener> listener;
};

// Parameters differ across tests (prevote flag, snapshot_distance) — keep
// the constructor explicit to avoid accidental cross-test coupling.
// The `rpc` arg is retained for backwards-compat but ignored — bring_up
// now creates a per-node factory internally so each node's outbound sends
// can be independently blocked via msg_bus::set_outbound_paused.
raft_node bring_up(int32 srv_id,
                   const std::vector<ptr<srv_config>>& config_cluster,
                   const std::shared_ptr<msg_bus>& bus,
                   const std::shared_ptr<mem_rpc_factory>& /*rpc unused*/,
                   const std::shared_ptr<asio_service>& sched,
                   cluster_state& cs,
                   bool enable_prevote = false,
                   int32 snapshot_distance = 0,
                   int32 election_timeout_lower_ms = 200,
                   int32 election_timeout_upper_ms = 400)
{
    auto rec = std::make_shared<commit_recorder>();
    cs.recorders[srv_id] = rec;
    if (!cs.snap_registry) cs.snap_registry = std::make_shared<snapshot_byte_registry>();

    auto listener = cs_new<mem_rpc_listener>(bus->get("port" + std::to_string(srv_id)));
    auto smgr = cs_new<mem_state_mgr>(srv_id, config_cluster, &cs);
    auto sm = cs_new<recording_state_machine>(rec, cs.snap_registry);
    auto lg = cs_new<null_logger>();
    ptr<delayed_task_scheduler> scheduler = sched;
    // Per-node factory tagged with this node's self_port so outbound
    // isolation (msg_bus::set_outbound_paused) works.
    ptr<rpc_client_factory> rpc_factory =
        cs_new<mem_rpc_factory>(bus, "port" + std::to_string(srv_id));
    ptr<raft_event_listener> watcher = cs_new<event_watcher>(cs, srv_id);

    raft_params* p = new raft_params();
    (*p).with_election_timeout_lower(election_timeout_lower_ms)
        .with_election_timeout_upper(election_timeout_upper_ms)
        .with_hb_interval(75)
        .with_max_append_size(100)
        .with_rpc_failure_backoff(25)
        .with_prevote_enabled(enable_prevote);
    if (snapshot_distance > 0)
    {
        // Explicitly set the sync block size — the default (0) is fine when
        // snapshot is disabled but the install path uses it as a chunk-size
        // in cornerstone's internals; leaving it at 0 has caused crashes.
        p->with_snapshot_enabled(snapshot_distance)
            .with_reserved_log_items(0)
            .with_snapshot_sync_block_size(4096);
    }

    context* ctx = new context(smgr, sm, listener, lg, rpc_factory, scheduler, watcher, p);
    auto server = cs_new<raft_server>(ctx);
    ptr<msg_handler> handler = server;
    listener->listen(handler);

    return {server, listener};
}

std::vector<ptr<srv_config>> make_three_node_cluster()
{
    return {cs_new<srv_config>(1, std::string("port1")),
            cs_new<srv_config>(2, std::string("port2")),
            cs_new<srv_config>(3, std::string("port3"))};
}

// Send one client_request via `client`; on non-accepted responses, forward
// once to the leader whose id is in resp->get_dst().
void send_client_request(const std::shared_ptr<mem_rpc_factory>& rpc,
                         ptr<rpc_client>& client,
                         const std::string& payload,
                         std::atomic<bool>& done,
                         std::condition_variable& cv)
{
    auto msg = cs_new<req_msg>(0, msg_type::client_request, 0, 1, 0, 0, 0);
    bufptr buf = buffer::alloc(payload.size() + 1);
    buf->put(payload);
    buf->pos(0);
    msg->log_entries().push_back(cs_new<log_entry>(0, std::move(buf)));

    rpc_handler cb = [&done, &cv, &rpc, payload](ptr<resp_msg>& resp, const ptr<rpc_exception>& err) {
        if (err) return;
        if (resp && resp->get_accepted())
        {
            done.store(true);
            cv.notify_all();
        }
        else if (resp && resp->get_dst() > 0)
        {
            ptr<rpc_client> retry = rpc->create_client("port" + std::to_string(resp->get_dst()));
            auto retry_msg = cs_new<req_msg>(0, msg_type::client_request, 0, 1, 0, 0, 0);
            bufptr b2 = buffer::alloc(payload.size() + 1);
            b2->put(payload);
            b2->pos(0);
            retry_msg->log_entries().push_back(cs_new<log_entry>(0, std::move(b2)));
            rpc_handler cb2 = [&done, &cv](ptr<resp_msg>& r2, const ptr<rpc_exception>&) {
                if (r2 && r2->get_accepted())
                {
                    done.store(true);
                    cv.notify_all();
                }
            };
            retry->send(retry_msg, cb2);
        }
    };
    client->send(msg, cb);
}

// Best-effort teardown so tests that fail early don't leak listener threads.
void tear_down(std::vector<raft_node>& nodes, std::shared_ptr<asio_service>& sched)
{
    for (auto& n : nodes) n.listener->stop();
    sched->stop();
    std::this_thread::sleep_for(std::chrono::milliseconds(200));
}

} // namespace

// ---------------------------------------------------------------------------
// TESTS
// ---------------------------------------------------------------------------

// TEST — after starting a 3-node cluster from cold, exactly one node must
// transition into the leader state within a bounded window. The
// raft_event_listener::become_leader callback is the documented public
// signal for this transition.
TEST(RaftCluster, ElectsLeaderFromColdStart)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(2000));

    EXPECT_GE(cs.leader_count.load(), 1) << "no node became leader within 2 s";
    int leader_id = cs.current_leader_id.load();
    EXPECT_GE(leader_id, 1);
    EXPECT_LE(leader_id, 3);

    tear_down(nodes, sched);
}

// TEST — sending a client_request through any node results in the log
// entry being committed on the cluster: state_machine::commit fires on
// the leader with the client's payload. If we happen to hit a follower
// first, the resp_msg carries dst=leader_id — the harness retries against
// the leader and the commit fires there.
TEST(RaftCluster, CommitsClientRequestPayload)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);

    ptr<rpc_client> client = rpc->create_client("port1");
    std::atomic<bool> done{false};
    std::mutex m; std::condition_variable cv;
    send_client_request(rpc, client, "hello raft", done, cv);

    {
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(3000), [&]() { return done.load(); });
    }
    EXPECT_TRUE(done.load()) << "client request was never accepted";

    std::this_thread::sleep_for(std::chrono::milliseconds(400));
    size_t total = 0;
    bool committed_payload = false;
    for (const auto& kv : cs.recorders)
    {
        for (const auto& payload : kv.second->snapshot_committed())
        {
            ++total;
            if (payload == "hello raft") committed_payload = true;
        }
    }
    EXPECT_GT(total, static_cast<size_t>(0))
        << "no state_machine::commit callback fired anywhere in the cluster";
    EXPECT_TRUE(committed_payload)
        << "the client payload \"hello raft\" was not the value committed by any node";

    tear_down(nodes, sched);
}

// TEST — add_srv chains join_cluster + sync_log + a cluster-config commit,
// after which the new node's raft_event_listener fires logs_catch_up. The
// documented public contract is: add_srv returns a non-null async_result AND
// the new node observes catch-up within a bounded deadline (5 s here —
// election (<=0.4s) + join_cluster round-trip + log sync + commit is
// normally <=2s on the in-memory bus). The new node starts with a solo
// cluster_config; the leader tells it about the real cluster via
// join_cluster_request.
TEST(RaftCluster, AddServerJoinsAndCatchesUp)
{
    auto three = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(
        std::vector<std::string>{"port1", "port2", "port3", "port4"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, three, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, three, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, three, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());
    raft_node& leader = nodes[leader_id - 1];

    // Node 4 starts with its own solo cluster_config; leader will instruct
    // it about the real cluster via join_cluster.
    std::vector<ptr<srv_config>> solo = {cs_new<srv_config>(4, std::string("port4"))};
    nodes.push_back(bring_up(4, solo, bus, rpc, sched, cs));

    srv_config new_srv(4, std::string("port4"));
    ptr<async_result<bool>> ar = leader.server->add_srv(new_srv);
    ASSERT_NE(ar, nullptr) << "add_srv returned null async_result";

    // Wait up to 5 s for logs_catch_up on node 4.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (std::chrono::steady_clock::now() < deadline &&
           cs.logs_catch_up_srv.load() != 4)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    EXPECT_EQ(cs.logs_catch_up_srv.load(), 4)
        << "node 4 never reported logs_catch_up within 5 s of add_srv";

    tear_down(nodes, sched);
}

// TEST — remove_srv drops a follower from the cluster; the two remaining
// nodes must still form a quorum and commit subsequent client_requests.
// One behavioral contract: cluster liveness survives a follower removal.
TEST(RaftCluster, RemoveServerLeavesClusterFunctional)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());
    int32 victim = (leader_id == 1) ? 2 : 1;

    raft_node& leader = nodes[leader_id - 1];
    ptr<async_result<bool>> ar = leader.server->remove_srv(victim);
    ASSERT_NE(ar, nullptr) << "remove_srv returned null async_result";

    // Wait up to 3 s for the config change to commit.
    std::this_thread::sleep_for(std::chrono::milliseconds(3000));

    // The cluster must still be functional: a follow-up client_request
    // must be accepted (the remaining nodes still form a majority — 2 of
    // the remaining 2).
    std::atomic<bool> done{false};
    std::mutex m; std::condition_variable cv;
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(leader_id));
    send_client_request(rpc, client, "after-remove", done, cv);
    {
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(3000), [&]() { return done.load(); });
    }
    EXPECT_TRUE(done.load()) << "post-removal client_request was never accepted — "
                                "cluster did not survive remove_srv";

    tear_down(nodes, sched);
}

// TEST — with snapshot_distance set on all nodes and a leader that has
// committed enough client_requests to cross the distance threshold, the
// leader must invoke state_machine::create_snapshot to materialize a
// snapshot for later log compaction. This is the CREATION half of the
// snapshot pipeline; the install-on-follower half (leader ships bytes to
// a partitioned-then-rejoined follower) is compile-tested only — the
// reference cornerstone's install_snapshot code path SIGSEGVs when
// exercised end-to-end even with a fully stateful state_machine mock
// (leader-side read_snapshot_data serving real bytes, follower-side
// save_snapshot_data accumulating them, apply_snapshot verifying
// byte-for-byte equality against a shared registry). Handed back to the
// coordinator as an infeasible-in-this-harness constraint — see
// report.txt GT EVAL RESULT section for the full attempt log.
TEST(RaftCluster, SnapshotCreationFiresAtDistance)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    // snapshot_distance = 3 -> leader triggers create_snapshot after
    // ~3 committed entries beyond the last snapshot.
    // reserved_log_items = 0 -> compaction is aggressive.
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs, /*prevote=*/false, /*snap=*/3));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs, /*prevote=*/false, /*snap=*/3));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs, /*prevote=*/false, /*snap=*/3));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());

    // Drive enough commits (>>3) to cross the snapshot_distance threshold.
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(leader_id));
    for (int i = 0; i < 10; ++i)
    {
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, client, "req_" + std::to_string(i), done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(500), [&]() { return done.load(); });
    }

    // Give the leader's commit_in_bg loop time to advance commit_idx and
    // trigger the snapshot pipeline.
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));

    // Behavioral contract: state_machine::create_snapshot fired at least
    // once — meaning the leader detected that the committed-entry count
    // exceeded snapshot_distance and initiated snapshot materialization.
    size_t create_calls = 0;
    for (const auto& kv : cs.recorders)
        create_calls += kv.second->create_snapshot_calls.load();
    EXPECT_GT(create_calls, static_cast<size_t>(0))
        << "state_machine::create_snapshot never fired on the leader after "
           "10 commits with snapshot_distance=3";

    tear_down(nodes, sched);
}

// TEST — a temporarily isolated follower that missed enough commits to fall
// off the leader's compacted log MUST be caught up via the install_snapshot
// pipeline (NOT via append_entries replay of the individual missing entries).
//
// Preconditions: snapshot_distance = 3 on all nodes, reserved_log_items = 0
// (aggressive compaction), full isolation of the victim so it neither
// receives commits nor wins spurious elections during the isolation window.
//
// Behavioral contract exercised on the resumed victim:
//   1. state_machine::save_snapshot_data() fires ≥ 1x (leader streams the
//      snapshot bytes chunk-by-chunk via install_snapshot RPC).
//   2. state_machine::apply_snapshot() fires ≥ 1x (victim installs the
//      streamed snapshot as its new state).
//   3. Byte-for-byte round-trip: the leader-side bytes emitted by
//      create_snapshot() match the bytes reassembled from save_snapshot_data
//      on the victim, verified via snapshot_byte_registry.
//
// This test also exercises the null-return path in
// raft_server::request_append_entries(peer&) that upstream guards with
// system_exit(-1)+null (see solve.sh git-apply patch for the defensive
// counterpart).
TEST(RaftCluster, LateFollowerCatchesUpViaSnapshot)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    // snapshot_distance = 3 -> leader triggers create_snapshot after
    // ~3 committed entries beyond the last snapshot.
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs, /*prevote=*/false, /*snap=*/3));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs, /*prevote=*/false, /*snap=*/3));
    // Node 3 = victim. Give it a LONGER election timeout so during the
    // partition it won't call spurious elections that could later disrupt
    // term stability once it rejoins (defense-in-depth; full outbound block
    // already stops its RPCs, but the timer still fires locally).
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs, /*prevote=*/false, /*snap=*/3,
                             /*election_timeout_lower_ms=*/1500,
                             /*election_timeout_upper_ms=*/2500));

    // Wait for stable leader election + initial config replication (during
    // which every node's log grows to include the leader's initial config
    // entry, so peer[3].next_log_idx advances past 1 — required for the
    // install-path condition `last_log_idx > 0`).
    std::this_thread::sleep_for(std::chrono::milliseconds(2500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());
    ASSERT_NE(leader_id, 3) << "victim node 3 should not have won leadership";

    // PRIMING COMMIT (before isolation): drive one client_request to ensure
    // peer[3].matched_idx advances past 0 while node 3 is still healthy.
    // Without this, leader might track peer[3].next_log_idx = 1 forever
    // (which would prevent the install path from firing — the condition
    // `last_log_idx > 0` requires next_log_idx >= 2).
    {
        ptr<rpc_client> client0 = rpc->create_client("port" + std::to_string(leader_id));
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, client0, "priming", done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(1000), [&]() { return done.load(); });
        // Extra settle time so heartbeat propagates the commit_idx bump to
        // node 3 and matched_idx / next_log_idx sync fully.
        std::this_thread::sleep_for(std::chrono::milliseconds(300));
    }

    // FULL isolation of node 3: block outbound (its rpc_client sends fail
    // immediately) AND inbound (its listener queue rejects new messages).
    // Do this AFTER the priming commit so leader has real per-peer state
    // for node 3 (next_log_idx >= 2).
    bus->set_outbound_paused("port3", true);
    bus->get("port3")->set_paused(true);

    // Drive enough commits (>>3) to cross snapshot_distance AND to make
    // the victim's next_log_idx fall FAR behind the leader's compacted
    // start_index. With snapshot_distance=3 and 15 commits, we expect
    // multiple snapshot rounds; each compaction advances start_index.
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(leader_id));
    for (int i = 0; i < 15; ++i)
    {
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, client, "late_snap_" + std::to_string(i), done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(500), [&]() { return done.load(); });
    }

    // Give the leader's commit_in_bg loop time to advance commit_idx,
    // fire create_snapshot, and compact the log.
    std::this_thread::sleep_for(std::chrono::milliseconds(2500));

    // Precondition sanity: leader-side create_snapshot fired at least once.
    // Without this, the install_snapshot path can't possibly fire on
    // the victim (there's nothing to install).
    size_t create_calls = 0;
    for (const auto& kv : cs.recorders)
        create_calls += kv.second->create_snapshot_calls.load();
    ASSERT_GT(create_calls, static_cast<size_t>(0))
        << "leader never created a snapshot despite 15 commits with distance=3";

    auto victim_rec = cs.recorders[3];
    ASSERT_NE(victim_rec, nullptr);

    // Un-isolate node 3. Leader detects that peer[3].next_log_idx <
    // starting_idx and switches from append_entries -> create_sync_snapshot_req.
    bus->set_outbound_paused("port3", false);
    bus->get("port3")->set_paused(false);

    // POLL for install pipeline completion instead of a fixed sleep.
    // The pipeline is:
    //   leader -> install_snapshot_request (streamed chunks) ->
    //   follower::save_snapshot_data() per chunk ->
    //   final: follower::apply_snapshot() ->
    //   leader receives ack, advances peer.next_log_idx, resumes append.
    // Poll up to 10 s at 100 ms interval, exit early once apply_snapshot
    // has fired at least once.
    const auto install_deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
    while (std::chrono::steady_clock::now() < install_deadline &&
           victim_rec->apply_snapshot_calls.load() == 0)
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    // Extra 200 ms settle for the byte-equality check in apply_snapshot to
    // populate `applied_snapshot_matches`.
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    // BEHAVIORAL CONTRACT 1: victim received snapshot chunks via
    // save_snapshot_data (proves the leader took the install path, not
    // append_entries).
    EXPECT_GT(victim_rec->save_snapshot_data_calls.load(), static_cast<size_t>(0))
        << "victim (node 3) never received install_snapshot chunks — leader "
           "may have used append_entries instead of snapshot install, or "
           "the install pipeline stalled before streaming any chunks";

    // BEHAVIORAL CONTRACT 2: victim finalized the snapshot install by
    // calling apply_snapshot (proves the install pipeline completed the
    // handshake, not just started it).
    EXPECT_GT(victim_rec->apply_snapshot_calls.load(), static_cast<size_t>(0))
        << "victim (node 3) received install_snapshot chunks but never "
           "called apply_snapshot to finalize the install";

    // BEHAVIORAL CONTRACT 3: byte-for-byte round-trip. The leader's
    // create_snapshot() published its bytes to the shared registry; the
    // victim's apply_snapshot() looked them up and compared against what
    // it received via save_snapshot_data. This proves the transport
    // preserved every byte (offset+chunk streaming is lossless).
    {
        std::lock_guard<std::mutex> g(victim_rec->snap_mu);
        EXPECT_TRUE(victim_rec->applied_snapshot_matches)
            << "victim's applied snapshot bytes did not match leader's "
               "create_snapshot() output — the install_snapshot streaming "
               "path corrupted or reordered the bytes";
    }

    tear_down(nodes, sched);
}

// TEST — with prevote_enabled=true, a temporarily partitioned follower
// does NOT inflate its persisted term through rounds of failed elections
// (the prevote_request check short-circuits before the term is bumped).
// Documented contract: raft_params::with_prevote_enabled(true) prevents
// disruptive term inflation on a rejoining node. The +2 ceiling vs the
// leader's term is a generous bound: without prevote, the partitioned
// node would inflate by many terms in the ~2 s partition window.
TEST(RaftCluster, PrevotePreventsTermInflationOnPartition)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs, /*prevote=*/true));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs, /*prevote=*/true));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs, /*prevote=*/true));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());
    int32 victim = (leader_id == 3) ? 2 : 3;

    ulong leader_term_before;
    {
        std::lock_guard<std::mutex> g(cs.saved_terms_mu);
        leader_term_before = cs.max_saved_term[leader_id];
    }
    (void)leader_term_before;

    // Partition the victim: no heartbeats reach it; its election timeout
    // will fire, but prevote must prevent it from actually bumping its
    // term through repeated candidacies.
    bus->get("port" + std::to_string(victim))->set_paused(true);
    std::this_thread::sleep_for(std::chrono::milliseconds(2000));
    bus->get("port" + std::to_string(victim))->set_paused(false);
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    ulong victim_term_after;
    ulong leader_term_after;
    {
        std::lock_guard<std::mutex> g(cs.saved_terms_mu);
        victim_term_after = cs.max_saved_term[victim];
        leader_term_after = cs.max_saved_term[leader_id];
    }

    // With prevote, the victim's term should not run more than 2 ahead of
    // the leader's term. Without prevote it would inflate to many
    // increments (one per failed election attempt over 2 seconds).
    EXPECT_LE(victim_term_after, leader_term_after + 2)
        << "partitioned follower's term inflated to " << victim_term_after
        << " while leader's is " << leader_term_after
        << " — prevote did not gate the election";

    tear_down(nodes, sched);
}

// ---------------------------------------------------------------------------
// Raft correctness-invariant tests (Vector A — pull landing DOWN toward
// hard by testing Raft semantics, not just API shape).
// ---------------------------------------------------------------------------

// TEST — kill the current leader (isolate its outbound + stop its listener).
// A different node must fire become_leader within 3 s and the cluster must
// keep committing: a client_request sent to a surviving node results in
// state_machine::commit firing on the new leader. The single most important
// Raft integration invariant — agents commonly wire election but not failover.
TEST(RaftCluster, LeaderFailoverElectsNewLeaderAndKeepsCommitting)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 old_leader = static_cast<int32>(cs.current_leader_id.load());

    // "Kill" the leader:
    // (1) block its outbound so followers stop receiving heartbeats
    //     (this is the essential piece — closing inbound alone doesn't
    //     stop the leader's outbound timers from resetting follower election
    //     timers).
    // (2) stop its listener so it no longer processes incoming.
    bus->set_outbound_paused("port" + std::to_string(old_leader), true);
    nodes[old_leader - 1].listener->stop();

    // Wait up to 4 s for a new leader to be elected (election timeout upper
    // bound 400 ms + a couple of retries for candidate collisions).
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
    int32 new_leader = -1;
    while (std::chrono::steady_clock::now() < deadline)
    {
        int32 cur = static_cast<int32>(cs.current_leader_id.load());
        if (cur > 0 && cur != old_leader)
        {
            new_leader = cur;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    ASSERT_NE(new_leader, -1)
        << "no new leader was elected within 4 s after killing the old leader";
    EXPECT_NE(new_leader, old_leader);

    // Cluster must still commit: send a client_request to the new leader
    // and check state_machine::commit fires with the payload.
    std::atomic<bool> done{false};
    std::mutex m; std::condition_variable cv;
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(new_leader));
    size_t pre_count = 0;
    for (const auto& kv : cs.recorders)
        if (kv.first != old_leader) pre_count += kv.second->count();

    send_client_request(rpc, client, "after-failover", done, cv);
    {
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(3000), [&]() { return done.load(); });
    }
    EXPECT_TRUE(done.load()) << "post-failover client_request was never accepted";

    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    size_t post_count = 0;
    for (const auto& kv : cs.recorders)
        if (kv.first != old_leader) post_count += kv.second->count();
    EXPECT_GT(post_count, pre_count)
        << "no state_machine::commit fired on surviving nodes after failover — "
           "the new leader did not replicate the post-failover client_request";

    tear_down(nodes, sched);
}

// TEST — Election safety: for every unique term ever observed, at most one
// server ever fired become_leader at that term. Drive one leader turnover
// (kill L1 -> L2 elected) and inspect the (term, srv_id) tuples recorded
// by event_watcher. A split-brain bug where two nodes both win at the
// same term would show up here.
TEST(RaftCluster, ElectionSafetyAtMostOneLeaderPerTerm)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 first_leader = static_cast<int32>(cs.current_leader_id.load());

    // Kill first leader to force at least one turnover.
    bus->set_outbound_paused("port" + std::to_string(first_leader), true);
    nodes[first_leader - 1].listener->stop();
    std::this_thread::sleep_for(std::chrono::milliseconds(3000));

    // Snapshot the leader_events vector.
    std::vector<std::pair<ulong, int32>> events;
    {
        std::lock_guard<std::mutex> g(cs.leader_events_mu);
        events = cs.leader_events;
    }
    ASSERT_GE(events.size(), static_cast<size_t>(2))
        << "expected >=2 become_leader events after one turnover; got " << events.size();

    // Group by term; every unique term must have at most one distinct srv_id.
    std::unordered_map<ulong, std::unordered_set<int32>> by_term;
    for (const auto& [term, srv] : events) by_term[term].insert(srv);
    for (const auto& [term, srvs] : by_term)
    {
        EXPECT_LE(srvs.size(), static_cast<size_t>(1))
            << "election safety violated: term " << term << " had "
            << srvs.size() << " distinct leaders";
    }

    tear_down(nodes, sched);
}

// TEST — Log matching property: after 5 client_requests commit, all three
// nodes' state_machine::commit sequences must agree byte-for-byte at every
// index up to min(node_i.count). This is the cornerstone (pun intended) of
// Raft's replication contract — an agent whose leader commits but doesn't
// propagate, or whose follower rewrites the log incorrectly, fails here.
TEST(RaftCluster, LogMatchingAllNodesAgreeOnCommittedEntries)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());

    // Send 5 distinct client_requests to the leader.
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(leader_id));
    for (int i = 0; i < 5; ++i)
    {
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, client, "log-match-" + std::to_string(i), done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(1000), [&]() { return done.load(); });
    }
    // Give replication time to propagate to followers.
    std::this_thread::sleep_for(std::chrono::milliseconds(1000));

    // Compare committed sequences across all 3 nodes at every shared index.
    std::vector<std::vector<std::string>> per_node;
    for (int32 sid = 1; sid <= 3; ++sid)
        per_node.push_back(cs.recorders[sid]->snapshot_committed());
    size_t min_len = per_node[0].size();
    for (const auto& v : per_node) min_len = std::min(min_len, v.size());
    ASSERT_GT(min_len, static_cast<size_t>(0))
        << "no node received any commit — replication is entirely broken";

    for (size_t i = 0; i < min_len; ++i)
    {
        EXPECT_EQ(per_node[0][i], per_node[1][i])
            << "log-matching violated at commit index " << i
            << ": node 1 has '" << per_node[0][i]
            << "', node 2 has '" << per_node[1][i] << "'";
        EXPECT_EQ(per_node[0][i], per_node[2][i])
            << "log-matching violated at commit index " << i
            << ": node 1 has '" << per_node[0][i]
            << "', node 3 has '" << per_node[2][i] << "'";
    }

    tear_down(nodes, sched);
}

// TEST — Minority partition cannot commit: pause both follower ports so
// the leader can't replicate to any peer (quorum unreachable). A specific
// unique payload sent to the leader must NEVER show up in any node's
// state_machine::commit sequence, even after 3 s. Agents that
// optimistically commit without quorum ACK, or that commit locally on
// the leader before replication, fail here.
TEST(RaftCluster, MinorityPartitionCannotCommit)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());

    // Pause BOTH follower inbound ports. Leader's heartbeats and
    // append_entries to followers fail immediately (msg_bus::enqueue
    // detects paused and fires error callback synchronously). Followers'
    // outbound still works but their inbound is dead — so vote_requests
    // between followers also fail, no new leader can emerge.
    for (int32 sid = 1; sid <= 3; ++sid)
    {
        if (sid == leader_id) continue;
        bus->get("port" + std::to_string(sid))->set_paused(true);
    }

    // Send a distinctive client_request to the (now partitioned) leader.
    // The leader may accept it into its own log (uncommitted) but must
    // never advance commit_idx since quorum is impossible.
    const std::string tag = "MINORITY-PART-" + std::to_string(std::rand());
    std::atomic<bool> done{false};
    std::mutex m; std::condition_variable cv;
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(leader_id));
    send_client_request(rpc, client, tag, done, cv);
    {
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(500), [&]() { return done.load(); });
    }
    // Whether `done` fires or not is not the contract — the contract is
    // that our specific payload never commits anywhere.

    std::this_thread::sleep_for(std::chrono::milliseconds(3000));

    for (int32 sid = 1; sid <= 3; ++sid)
    {
        auto committed = cs.recorders[sid]->snapshot_committed();
        for (const auto& payload : committed)
        {
            EXPECT_EQ(payload.find(tag), std::string::npos)
                << "server " << sid << " committed the minority-partition payload '"
                << payload << "' — commit without quorum acknowledgement is a safety violation";
        }
    }

    tear_down(nodes, sched);
}

// TEST — Leader steps down on higher term seen. Inject a hand-crafted
// vote_request with term = leader_term + 5 directly onto the leader's
// queue (bypassing mem_rpc_client). The leader must (a) persist the new
// higher term via save_state (so max_saved_term for it >= leader_term+5),
// and (b) fire the become_follower event.
TEST(RaftCluster, LeaderStepsDownOnHigherTermSeen)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 leader_id = static_cast<int32>(cs.current_leader_id.load());

    ulong leader_term_before;
    {
        std::lock_guard<std::mutex> g(cs.saved_terms_mu);
        leader_term_before = cs.max_saved_term[leader_id];
    }

    // Pick an existing follower id as the src so cornerstone doesn't
    // reject the message for coming from an unknown server.
    int32 fake_src = (leader_id == 2) ? 3 : 2;

    // Construct a vote_request with a much higher term. Direct-enqueue
    // onto the leader's msg_bus queue (bypassing mem_rpc_client so we
    // don't need a matching listener on our end). The async_result's
    // response never gets observed — we care about the side effect on
    // the leader's persisted state, not the return value.
    ulong high_term = leader_term_before + 5;
    auto fake = cs_new<req_msg>(
        high_term, msg_type::vote_request, fake_src, leader_id,
        /*last_log_term=*/0, /*last_log_idx=*/0, /*commit_idx=*/0);
    auto result = cs_new<async_result<ptr<resp_msg>>>();
    bus->get("port" + std::to_string(leader_id))->enqueue({fake, result});

    // Give the leader a moment to process, update_term, save_state, and
    // fire become_follower.
    std::this_thread::sleep_for(std::chrono::milliseconds(1000));

    ulong leader_term_after;
    {
        std::lock_guard<std::mutex> g(cs.saved_terms_mu);
        leader_term_after = cs.max_saved_term[leader_id];
    }
    EXPECT_GE(leader_term_after, high_term)
        << "leader's persisted term (" << leader_term_after
        << ") did not advance past the higher term seen (" << high_term
        << ") — update_term / save_state not called on higher-term RPC";

    bool became_follower;
    {
        std::lock_guard<std::mutex> g(cs.became_follower_mu);
        became_follower = cs.became_follower_ids.count(leader_id) > 0;
    }
    EXPECT_TRUE(became_follower)
        << "leader did not fire become_follower after seeing higher term "
        << high_term << " — election safety could be violated";

    tear_down(nodes, sched);
}

// TEST — Log divergence forces follower truncation. An isolated leader
// accepts client_requests locally (phantom entries — uncommitted, higher-
// term-in-old-term); after rejoining, the new leader's append_entries
// term-mismatch handling must force it to write_at-truncate the phantoms
// and accept the new leader's post-partition commits. Raft's log-conflict
// resolution invariant.
TEST(RaftCluster, LogDivergenceForcesFollowerTruncation)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs));

    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 old_leader = static_cast<int32>(cs.current_leader_id.load());

    // Drive 2 committed entries — pre_A, pre_B — through the whole cluster.
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(old_leader));
    for (const std::string& payload : {"pre_A", "pre_B"})
    {
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, client, payload, done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(1000), [&]() { return done.load(); });
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    // Isolate old leader OUTBOUND only. Inbound stays open so we can still
    // send phantom client_requests to it. Old leader can't replicate, so
    // followers will time out and elect a new leader.
    bus->set_outbound_paused("port" + std::to_string(old_leader), true);

    // Immediately send 2 phantom client_requests to the (still-thinks-it's-
    // leader) old leader. It appends them locally at its own term but never
    // commits (outbound paused -> no quorum ACK).
    // Wait for done=false is expected since accepted=true only fires on commit.
    for (const std::string& payload : {"phantom_1", "phantom_2"})
    {
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, client, payload, done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(300), [&]() { return done.load(); });
    }

    // Wait for the majority (2 remaining) to elect a new leader.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(4);
    int32 new_leader = -1;
    while (std::chrono::steady_clock::now() < deadline)
    {
        int32 cur = static_cast<int32>(cs.current_leader_id.load());
        if (cur > 0 && cur != old_leader)
        {
            new_leader = cur;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }
    ASSERT_NE(new_leader, -1) << "no new leader emerged after old-leader outbound isolation";

    // Drive 2 more commits via the new leader.
    ptr<rpc_client> new_client = rpc->create_client("port" + std::to_string(new_leader));
    for (const std::string& payload : {"post_A", "post_B"})
    {
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, new_client, payload, done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(1000), [&]() { return done.load(); });
    }

    // Unpause old leader's outbound so the new leader can now push its
    // authoritative log into the (now former) old leader, forcing phantom
    // truncation.
    bus->set_outbound_paused("port" + std::to_string(old_leader), false);
    std::this_thread::sleep_for(std::chrono::milliseconds(3000));

    // Assertions on the OLD-leader (now-follower) node's committed sequence:
    //   (a) contains pre_A, pre_B, post_A, post_B in order (log-matching)
    //   (b) contains NO "phantom" entry (phantoms never committed — they
    //       existed only in old-leader's local log and got truncated)
    auto rec_old = cs.recorders[old_leader]->snapshot_committed();

    for (const auto& p : rec_old)
    {
        EXPECT_EQ(p.find("phantom"), std::string::npos)
            << "old leader committed a phantom entry after partition: '" << p
            << "' — Raft log divergence not resolved correctly";
    }

    std::vector<std::string> expected = {"pre_A", "pre_B", "post_A", "post_B"};
    size_t exp_idx = 0;
    for (const auto& p : rec_old)
    {
        if (exp_idx < expected.size() && p == expected[exp_idx]) exp_idx++;
    }
    EXPECT_EQ(exp_idx, expected.size())
        << "old leader's committed sequence does not include all 4 expected "
           "entries in order — log-matching after truncation failed";

    tear_down(nodes, sched);
}

// TEST — Election restriction (Raft §5.4.1): a candidate with a stale log
// cannot win an election even if its timeout fires first. Node 3 (victim)
// is partitioned early so it misses 5 commits, then given a SHORTER
// election timeout so it fires elections first when unpaused. The other
// up-to-date majority node must ultimately win the election because the
// stale candidate's log doesn't satisfy the up-to-date check in
// handle_vote_req.
TEST(RaftCluster, ElectionRestrictionStaleCandidateLoses)
{
    auto cluster = make_three_node_cluster();
    auto bus = std::make_shared<msg_bus>(std::vector<std::string>{"port1", "port2", "port3"});
    auto rpc = std::make_shared<mem_rpc_factory>(bus, std::string("harness"));
    auto sched = std::make_shared<asio_service>();
    cluster_state cs;

    // FULLY isolate node 3 (victim) BEFORE bringing up any node, so it can
    // never win (or even participate in) the initial election. Otherwise
    // there's a ~10 ms race between bring_up and set_paused where node 3's
    // (SHORTER) election timeout fires and it wins the initial term. Both
    // inbound (set_paused on port3 queue) AND outbound (set_outbound_paused
    // for port3 source) must be blocked.
    bus->set_outbound_paused("port3", true);
    bus->get("port3")->set_paused(true);

    // Bring up nodes 1 and 2 with default timeouts (200-400 ms) and
    // node 3 (victim) with SHORTER timeouts (100-150 ms). Also enable
    // prevote on all 3 so node 3's failed elections don't inflate its
    // term uncontrollably during the partition window (which would
    // muddy the assertion signal).
    std::vector<raft_node> nodes;
    nodes.push_back(bring_up(1, cluster, bus, rpc, sched, cs, /*prevote=*/true));
    nodes.push_back(bring_up(2, cluster, bus, rpc, sched, cs, /*prevote=*/true));
    nodes.push_back(bring_up(3, cluster, bus, rpc, sched, cs, /*prevote=*/true,
                             /*snap=*/0, /*election_timeout_lower_ms=*/100,
                             /*election_timeout_upper_ms=*/150));

    // Wait for majority (nodes 1+2) to elect a leader among themselves.
    std::this_thread::sleep_for(std::chrono::milliseconds(1500));
    ASSERT_GE(cs.leader_count.load(), 1);
    int32 majority_leader = static_cast<int32>(cs.current_leader_id.load());
    ASSERT_NE(majority_leader, 3) << "victim shouldn't have been leader (it's partitioned)";
    int32 other_maj = (majority_leader == 1) ? 2 : 1;

    // Drive 5 commits via the majority. Victim (node 3) sees none.
    ptr<rpc_client> client = rpc->create_client("port" + std::to_string(majority_leader));
    for (int i = 0; i < 5; ++i)
    {
        std::atomic<bool> done{false};
        std::mutex m; std::condition_variable cv;
        send_client_request(rpc, client, "commit_" + std::to_string(i), done, cv);
        std::unique_lock<std::mutex> lk(m);
        cv.wait_for(lk, std::chrono::milliseconds(1000), [&]() { return done.load(); });
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(500));

    // Confirm majority_leader and other_maj both received all 5 commits.
    ASSERT_GE(cs.recorders[majority_leader]->count(), static_cast<size_t>(5));
    ASSERT_GE(cs.recorders[other_maj]->count(), static_cast<size_t>(5));
    ASSERT_EQ(cs.recorders[3]->count(), static_cast<size_t>(0))
        << "victim shouldn't have any commits (partitioned)";

    // Simultaneously: fully un-isolate victim (BOTH inbound and outbound)
    // and kill the current leader. The victim (SHORTER timeout) will
    // start election attempts first. The election restriction contract
    // says: victim's log is stale, so its prevote/vote requests must be
    // rejected by up-to-date peers; the OTHER majority node must
    // eventually win the election.
    bus->set_outbound_paused("port3", false);
    bus->get("port3")->set_paused(false);
    bus->set_outbound_paused("port" + std::to_string(majority_leader), true);
    nodes[majority_leader - 1].listener->stop();

    // Wait up to 5 s for a new leader to emerge.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    int32 final_leader = -1;
    while (std::chrono::steady_clock::now() < deadline)
    {
        int32 cur = static_cast<int32>(cs.current_leader_id.load());
        if (cur > 0 && cur != majority_leader)
        {
            final_leader = cur;
            break;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    // The election restriction invariant: victim (id=3, stale log) must
    // NOT be the new leader. The other majority node (id=other_maj) is
    // the only correct outcome.
    EXPECT_NE(final_leader, 3)
        << "election restriction violated: victim (stale log) won election";
    EXPECT_EQ(final_leader, other_maj)
        << "expected majority up-to-date node (" << other_maj
        << ") to win; got " << final_leader;

    // Victim's max_saved_term must be > 0 (it participated in initial
    // election even before partition, and/or tried after unpause).
    ulong victim_term;
    {
        std::lock_guard<std::mutex> g(cs.saved_terms_mu);
        victim_term = cs.max_saved_term[3];
    }
    EXPECT_GT(victim_term, static_cast<ulong>(0))
        << "victim never participated in any election — test setup is broken";

    tear_down(nodes, sched);
}

