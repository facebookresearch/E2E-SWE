# cornerstone

`cornerstone` is a lightweight, complete implementation of the Raft consensus
algorithm as a C++17 library. It provides a `raft_server` — a state machine that
runs leader election, log replication, snapshotting, and cluster-membership
change — plus the supporting primitives (byte buffers, serialization, a
filesystem-backed log store, an asio-based RPC/timer scheduler, and small
smart-pointer + async utilities).

The library does not ship a bundled state machine, storage service, or RPC
transport concrete implementation beyond the asio-based one below. Users
provide their own by implementing four small interfaces (`state_machine`,
`state_mgr`, `rpc_listener`, `rpc_client_factory`) and hand them to
`raft_server` via a `context`.

All public types live in `namespace cornerstone`.

---

## Dependencies

- A C++17 (or newer) compiler with the standard library and pthreads
  (`-std=c++17 -pthread` on GCC/Clang).
- **asio** 1.22.x, standalone header-only mode, installed system-wide with
  `#include <asio.hpp>` resolving without a `-I` flag. Compile every
  translation unit that transitively includes an asio symbol with
  `-DASIO_STANDALONE -DASIO_HAS_STD_CHRONO`.
- No other third-party dependencies.

---

## Build and install contract

Provide a `setup.sh` in the repo root that runs offline (no network) and
produces exactly two install artifacts:

1. Public headers copied to `/usr/local/include/cornerstone/` — one file
   per public header, with the umbrella at
   `/usr/local/include/cornerstone/cornerstone.hxx`. A downstream program
   compiled with

   ```
   g++ -std=c++17 -DASIO_STANDALONE -DASIO_HAS_STD_CHRONO driver.cpp \
       -lcornerstone -lpthread
   ```

   (no `-I` flag) must be able to resolve `#include <cornerstone/cornerstone.hxx>`.

2. A static archive `/usr/local/lib/libcornerstone.a` containing every
   compiled `.cxx` translation unit, position-independent, linkable via
   `-lcornerstone`.

The static-archive layout is required — this is what `-lcornerstone`
resolves against.

---

## Umbrella header

`<cornerstone/cornerstone.hxx>` transitively includes every public header
below. Downstream code should `#include <cornerstone/cornerstone.hxx>` and
get the whole surface. Individual headers may also be included directly at
the same path (`<cornerstone/buffer.hxx>`, `<cornerstone/raft_server.hxx>`,
etc.) but the umbrella is the recommended entry point.

---

## Core aliases and macros

Type aliases:

- `typedef uint64_t ulong;` — the library's canonical unsigned 64-bit type.
- `typedef unsigned char byte;`
- `typedef int32_t int32;`
- `uint` is used in one public signature (`raft_server::replicate_log` — see
  below); treat as `uint32_t`.

Smart-pointer aliases:

```cpp
template <typename T>
using ptr = std::shared_ptr<T>;

template <typename T>
using wptr = std::weak_ptr<T>;

template <typename T, typename Deleter = std::default_delete<T>>
using uptr = std::unique_ptr<T, Deleter>;

template <typename T, typename... Args>
ptr<T> cs_new(Args&&... args);          // forwards to std::make_shared
```

Every interface class (`state_machine`, `state_mgr`, `rpc_listener`,
`rpc_client`, `rpc_client_factory`, `logger`, `raft_event_listener`,
`log_store`, `delayed_task_scheduler`) has a public default constructor,
a virtual destructor, and is non-copyable — user subclasses can
`class Foo : public state_machine {…}` freely and hold `ptr<Foo>`
handles.

---

## Raft consensus

### `raft_server`

Header: `<cornerstone/raft_server.hxx>`. Constructed from a `context*` (the
library takes ownership through `std::unique_ptr`). Non-copyable.

```cpp
class raft_server {
public:
    raft_server(context* ctx);
    virtual ~raft_server();

    ptr<resp_msg> process_req(req_msg& req);

    ptr<async_result<bool>> add_srv(const srv_config& srv);
    ptr<async_result<bool>> remove_srv(const int srv_id);

    ptr<async_result<bool>> append_entries(std::vector<bufptr>& logs);
    bool                    replicate_log(bufptr& log,
                                          const ptr<void>& cookie,
                                          uint cookie_tag);

    bool is_leader() const;
};
```

Contracts:

- `process_req(req_msg&)` is the entry point every incoming RPC message
  flows through. An `rpc_listener` implementation delivers deserialized
  `req_msg` objects to a `raft_server` (which implements the
  `msg_handler` alias — see below) and returns the produced `resp_msg` to
  the caller. Every `msg_type` variant is dispatched from here.
- `add_srv(srv_config)` initiates the join sequence for a new server. The
  returned `async_result<bool>` completes with `true` once the new server
  has been accepted into the cluster. See "Membership change" below for
  the joining node's contract.
- `remove_srv(int srv_id)` initiates removal of `srv_id` from the cluster.
  The returned `async_result<bool>` completes with `true` once the removal
  is committed. The remaining nodes must continue to accept
  `client_request`s if they still form a majority of the new
  configuration.
- `append_entries(std::vector<bufptr>&)` and
  `replicate_log(bufptr&, ptr<void>, uint)` are the two ways to submit
  user log payloads. Both are convenience wrappers around the leader's
  replication path; if the current node is not the leader they forward
  to the leader.
- `is_leader()` returns whether this node currently believes itself to
  be the leader.

`msg_handler` is a type alias (in `rpc_listener.hxx`):
`typedef raft_server msg_handler;` — an `rpc_listener` accepts
`ptr<msg_handler>&`.

### `raft_params`

Header: `<cornerstone/raft_params.hxx>`. A plain-data struct that holds
all cluster-wide tunable timings and thresholds, with fluent setters that
each return `raft_params&` so calls can be chained. The `raft_server`
receives a `raft_params*` through the `context` and takes ownership.

Each setter accepts a value; the library provides sensible defaults for
callers that leave a knob unset.

Fluent setters:

```cpp
raft_params& with_election_timeout_upper(int32 ms);
raft_params& with_election_timeout_lower(int32 ms);
raft_params& with_hb_interval(int32 ms);
raft_params& with_rpc_failure_backoff(int32 ms);
raft_params& with_max_append_size(int32 entries);
raft_params& with_log_sync_batch_size(int32 n);
raft_params& with_log_sync_stopping_gap(int32 n);
raft_params& with_snapshot_enabled(int32 distance);
raft_params& with_snapshot_sync_block_size(int32 sz);
raft_params& with_reserved_log_items(int n);
raft_params& with_prevote_enabled(bool);
raft_params& with_defensive_prevote(bool);
int          max_hb_interval() const;
```

All the timing setters accept milliseconds. The election timeout must be
randomized per election between the lower and upper bound. `hb_interval`
is the heartbeat period. `rpc_failure_backoff` is added to a peer's
heartbeat interval when its RPC fails, up to `max_hb_interval()`.

`max_append_size` caps the number of log entries batched into a single
`append_entries_request`. `log_sync_batch_size` and
`log_sync_stopping_gap` control the join-catch-up path: the leader sends
a joining server this many entries per `sync_log_request`, switching to
regular `append_entries` when `leader_commit_idx - caught_up_idx <
log_sync_stopping_gap`.

`with_snapshot_enabled(distance)` enables snapshotting: when the leader's
commit index has advanced by more than `distance` beyond the last
snapshot, the leader triggers `state_machine::create_snapshot`. See
"Snapshot install" below. `with_reserved_log_items(n)` controls how many
committed log entries the leader keeps after a snapshot before compacting.

`with_prevote_enabled(true)` turns on the prevote optimization; see
"Prevote" below. `with_defensive_prevote(bool)` controls whether a peer
only accepts a `prevote_request` when the peer itself thinks an election
is legitimate (default `true`) — set `false` to accept prevote requests
whenever the requester's term and log index look plausible.

`raft_params` is non-copyable.

### `raft_event` and `raft_event_listener`

Header: `<cornerstone/events.hxx>`.

```cpp
enum class raft_event {
    become_leader   = 1,
    become_follower,
    logs_catch_up,
};

class raft_event_listener {
public:
    virtual void on_event(raft_event event) = 0;
};
```

The `raft_server` invokes `on_event` on the user-supplied listener at
the following moments:

- `become_leader` — this node has just transitioned into the leader
  role (won an election).
- `become_follower` — this node has just transitioned into the follower
  role (either from candidate after losing an election, or from leader
  after seeing a higher term).
- `logs_catch_up` — this node was joining the cluster (typically after
  `add_srv` on the leader) and has now caught up to the leader's commit
  index.

### `state_machine`

Header: `<cornerstone/state_machine.hxx>`. User implements this to receive
committed log entries and to participate in snapshotting.

```cpp
class state_machine {
public:
    virtual void commit(const ulong log_idx,
                        buffer& data,
                        const uptr<log_entry_cookie>& cookie) = 0;
    virtual void pre_commit(const ulong log_idx,
                            buffer& data,
                            const uptr<log_entry_cookie>& cookie) = 0;
    virtual void rollback(const ulong log_idx,
                          buffer& data,
                          const uptr<log_entry_cookie>& cookie) = 0;

    virtual void save_snapshot_data(snapshot& s,
                                    const ulong offset,
                                    buffer& data) = 0;
    virtual bool apply_snapshot(snapshot& s) = 0;
    virtual int  read_snapshot_data(snapshot& s,
                                    const ulong offset,
                                    buffer& data) = 0;

    virtual ptr<snapshot> last_snapshot() = 0;
    virtual ulong         last_commit_index() = 0;

    virtual void create_snapshot(snapshot& s,
                                 async_result<bool>::handler_type& when_done) = 0;
};
```

Contracts:

- `commit(log_idx, data, cookie)` is called for every committed log entry
  in order. `data` is the entry's payload buffer; `cookie` is the object
  attached to the entry via `replicate_log(..., cookie, cookie_tag)` on
  the leader side (empty on other nodes).
- `pre_commit` / `rollback` are optional lifecycle hooks called before
  commit and if the entry is later rolled back (for user-side write-ahead
  bookkeeping). They may be implemented as no-ops.
- `last_commit_index()` returns the user's own record of the highest
  committed index; the library uses this only for progress reporting.

### Snapshot install

Snapshotting is disabled by default (`raft_params::with_snapshot_enabled(0)`).
When enabled with a positive distance, snapshot creation and installation
flow through four `state_machine` methods. Failing to implement any of the
four correctly will break the install pipeline — even if `commit` is
correct in isolation.

The complete contract:

1. **Snapshot creation on the leader.** When the leader's commit index
   has advanced by more than `snapshot_distance` beyond the last snapshot,
   the leader calls `state_machine::create_snapshot(snapshot& s,
   async_result<bool>::handler_type& when_done)`. The user is responsible
   for materializing the snapshot however they wish (write it to disk,
   remember it in memory, whatever) and **must invoke `when_done(true, {})`
   when done**. Until `when_done` is invoked with success, the leader
   will not compact its log — and without compaction, no downstream
   `install_snapshot_request` is ever issued to a lagging peer. Calling
   `when_done(false, err)` signals that the snapshot failed; the leader
   will retry later.
2. **The materialized snapshot must be returned from `last_snapshot()`.**
   Once the leader begins shipping the snapshot to a peer, it reads the
   snapshot metadata via `state_machine::last_snapshot()` on the leader
   side. Returning `nullptr` here disables install.
3. **The install RPC on the sender.** When the leader detects that a
   peer's `next_log_idx` is below the leader's `log_store::start_index()`
   (i.e. the peer is asking for a log entry that has already been
   compacted), the leader ships `install_snapshot_request` messages
   instead of `append_entries_request`. Each request carries a
   `snapshot_sync_req` (see "Serialization" below) with a chunk of
   payload obtained from `state_machine::read_snapshot_data(s, offset,
   data)`. The user fills `data` with the bytes for `[offset,
   offset+data.size())` and returns the number of bytes written; **a
   return value of `0` signals "no more data" and terminates the chunk
   stream**.
4. **Apply on the receiver.** As each `install_snapshot_request` arrives
   on a follower, the receiver calls `state_machine::save_snapshot_data(s,
   offset, data)`, in order, letting the user persist the chunk. After
   the final chunk (`snapshot_sync_req::is_done() == true`), the receiver
   calls `state_machine::apply_snapshot(s)` exactly once. The user
   returns `true` on success; the log store's `start_index` then advances
   to `s.get_last_log_idx() + 1`.

### Prevote

Prevote is disabled by default. With `with_prevote_enabled(true)`, the
election path gains an extra round:

- A follower whose election timeout fires **first sends
  `prevote_request` to every peer** and only bumps its own term into a
  new election if it receives prevote grants from a majority. If the
  prevote does not carry a majority, the follower's persisted term does
  NOT increment.
- A peer receiving `prevote_request` responds with a grant only when it
  believes an election is legitimate. With `with_defensive_prevote(true)`
  (the default), "legitimate" means the peer itself is currently in
  prevote or already thinks it has lost contact with the leader; with
  `with_defensive_prevote(false)`, the peer grants any prevote whose
  term and last log index look plausible relative to its own.
- This prevents a partitioned or delayed follower from disrupting the
  cluster on reconnect — a rejoining follower's persisted term will
  stay bounded (only bumped by legitimate elections it observes from
  peers) rather than inflating unboundedly through failed election
  attempts.

### Membership change

`add_srv(const srv_config&)` and `remove_srv(int)` are the two membership
operations. Both are only meaningful when called on the current leader; on
a non-leader they forward to the leader (or fail if there is none).

`add_srv` runs the following sequence on the leader:

1. Send a `join_cluster_request` (a `req_msg` of type
   `msg_type::join_cluster_request`) to the joining server's endpoint.
2. Once the joining server responds, ship it a stream of `sync_log_request`
   messages carrying batched log entries (batched at
   `log_sync_batch_size`), until the gap falls below
   `log_sync_stopping_gap`.
3. Switch to regular `append_entries` and, once the joining server has
   caught up to the leader's commit index, commit a `cluster_config`
   change that adds the new server. The `raft_event_listener` on the
   joining node fires `logs_catch_up`.

The joining server's own `state_mgr::load_config()` may return any
initial cluster configuration (empty, single-member, or already
containing the target cluster) — the leader will overwrite it via
`state_mgr::save_config(...)` as part of the join.

`remove_srv(int srv_id)` commits a `cluster_config` change that removes
`srv_id` from the cluster. Once committed, the remaining servers form
the new cluster; any subsequent `client_request` that the new cluster
can commit (i.e. reach a majority of the new membership) commits
normally. Removing the leader is legal but forces a new election.

Neither operation pins an exact log-index assignment — the leader
assigns indices monotonically as part of normal append. The public
contract is exactly the `async_result<bool>` completion +
`raft_event_listener` event described above.

### `msg_type`

Header: `<cornerstone/msg_type.hxx>`.

```cpp
enum msg_type { client_request = 0x5, /* … other protocol variants … */ };
```

`msg_type` tags every RPC variant that flows through
`raft_server::process_req`. `client_request` is the only variant the
public client-side API pins by name (see "Client-side convention for
`client_request`" below). The remaining protocol variants
(`vote_request`, `append_entries_request`, `install_snapshot_request`,
`prevote_request`, `add_server_request`, `remove_server_request`,
`sync_log_request`, `join_cluster_request`, `leave_cluster_request`, and
their `_response` counterparts) are used internally by the raft state
machine — enumerator names must exist so the raft server can dispatch
on them, but their integer values are not part of the wire contract
this library exposes to users.

### `req_msg`, `resp_msg`

Headers: `<cornerstone/req_msg.hxx>`, `<cornerstone/resp_msg.hxx>`.
Non-copyable. Both share these accessors: `get_term()`, `get_type()`,
`get_src()`, `get_dst()`.

```cpp
class req_msg {
public:
    req_msg(ulong term, msg_type type, int32 src, int32 dst,
            ulong last_log_term, ulong last_log_idx, ulong commit_idx);

    ulong get_last_log_idx() const;
    ulong get_last_log_term() const;
    ulong get_commit_idx() const;
    std::vector<ptr<log_entry>>& log_entries();
};

class resp_msg {
public:
    resp_msg(ulong term, msg_type type, int32 src, int32 dst,
             ulong next_idx = 0L, bool accepted = false);

    ulong get_next_idx() const;
    bool  get_accepted() const;
    void  accept(ulong next_idx);
};
```

Client-side convention for `client_request`: a client sends a `req_msg` of
type `msg_type::client_request` to any server. If that server is the
leader, it processes the request; the leader's `resp_msg` carries
`get_accepted() == true` on acceptance. If the server is not the leader,
the `resp_msg` has `get_accepted() == false` and `get_dst()` set to the
leader's server id — the client retries against that leader.

### `srv_config`, `cluster_config`, `srv_state`

Headers: `<cornerstone/srv_config.hxx>`, `<cornerstone/cluster_config.hxx>`,
`<cornerstone/srv_state.hxx>`.

```cpp
class srv_config {
public:
    srv_config(int32 id, const std::string& endpoint);
    int32               get_id() const;
    const std::string&  get_endpoint() const;
    bufptr              serialize() const;
    static ptr<srv_config> deserialize(buffer& buf);
};

class cluster_config {
public:
    cluster_config(ulong log_idx = 0, ulong prev_log_idx = 0);
    ulong                          get_log_idx() const;
    ulong                          get_prev_log_idx() const;
    void                           set_log_idx(ulong log_idx);
    std::list<ptr<srv_config>>&    get_servers();
    ptr<srv_config>                get_server(int id) const;
    bufptr                         serialize();
    static ptr<cluster_config>     deserialize(buffer& buf);
};

class srv_state {
public:
    srv_state();
    ulong get_term() const;
    void  set_term(ulong term);
    int   get_voted_for() const;
    void  set_voted_for(int voted_for);
};
```

`cluster_config::set_log_idx(idx)` moves `log_idx_` to `idx` while
copying the previous value into `prev_log_idx_`.

### `state_mgr`

Header: `<cornerstone/state_mgr.hxx>`. User implements this so the
library can persist and load the two pieces of raft state that must
survive a restart.

```cpp
class state_mgr {
public:
    virtual ptr<cluster_config> load_config()                    = 0;
    virtual void                save_config(const cluster_config& c) = 0;
    virtual void                save_state(const srv_state& s)       = 0;
    virtual ptr<srv_state>      read_state()                      = 0;
    virtual ptr<log_store>      load_log_store()                  = 0;
    virtual int32               server_id()                       = 0;
    virtual void                system_exit(const int exit_code)  = 0;
};
```

Contracts:

- `save_state` is invoked whenever the raft node's `srv_state` changes
  (term, vote). The user must persist and, on restart, `read_state()`
  must return the last-persisted value.
- `load_log_store` is invoked once at startup; the returned
  `ptr<log_store>` is used for the lifetime of the node.
- `system_exit(exit_code)` is invoked when the library wants the process
  to terminate.

### `context`

Header: `<cornerstone/context.hxx>`. Non-copyable. Holds every
user-supplied dependency plus the `raft_params` for the node. Ownership
of the `raft_params*` transfers to the `context` (which stores it as a
`uptr<raft_params>`). Passing `nullptr` for `params` causes the context
to default-construct one.

```cpp
struct context {
    context(const ptr<state_mgr>&           mgr,
            const ptr<state_machine>&       m,
            const ptr<rpc_listener>&        listener,
            const ptr<logger>&              l,
            const ptr<rpc_client_factory>&  cli_factory,
            const ptr<delayed_task_scheduler>& scheduler,
            const ptr<raft_event_listener>& event_listener,
            raft_params*                    params = nullptr);
};
```

All constructor arguments are exposed as public members so the raft
server can wire them without accessor calls.

---

## Log storage

### `log_val_type`

Header: `<cornerstone/log_val_type.hxx>`. Tag for the variant that a
`log_entry` carries.

```cpp
enum log_val_type {
    app_log,          // user application payload
    conf,             // cluster_config change
    cluster_server,   // srv_config payload (add-server)
    log_pack,         // packed batch of entries
    snp_sync_req,     // snapshot_sync_req payload
};
```

### `log_entry` and `log_entry_cookie`

Header: `<cornerstone/log_entry.hxx>`. `log_entry` is non-copyable.
`log_entry_cookie` is an opaque type passed to `state_machine::commit` as
`const uptr<log_entry_cookie>&`. It is set on a log entry via
`log_entry::set_cookie(uint tag, const ptr<void>& value)`.

```cpp
class log_entry {
public:
    log_entry(ulong term,
              bufptr&& buff,
              log_val_type value_type = log_val_type::app_log);

    ulong                          get_term() const;
    void                           set_term(ulong term);
    log_val_type                   get_val_type() const;
    buffer&                        get_buf() const;
    void                           set_cookie(uint tag, const ptr<void>& value);
    const uptr<log_entry_cookie>&  get_cookie() const;

    bufptr                         serialize();
    static ptr<log_entry>          deserialize(buffer& buf);
    static ulong                   term_in_buffer(buffer& buf);
};
```

Contracts:

- `serialize()` produces a `bufptr` whose contents are `term` (as ulong)
  followed by `value_type` (as byte) followed by the entry's payload
  bytes.
- `deserialize(buf)` reads back a `log_entry` in the same order.
- `term_in_buffer(buf)` peeks the leading term value **without advancing
  `buf.pos()`**. This lets callers see an entry's term without consuming
  the buffer.
- `get_buf()` throws `std::runtime_error` if the entry was constructed
  with a null buffer.

### `log_store`

Header: `<cornerstone/log_store.hxx>`. Pure virtual interface —
`fs_log_store` is one implementation; users may provide their own.
Log indices start at 1.

```cpp
class log_store {
public:
    virtual ulong          next_slot() const           = 0;
    virtual ulong          start_index() const         = 0;
    virtual ptr<log_entry> last_entry() const          = 0;

    virtual ulong          append(ptr<log_entry>& entry)                    = 0;
    virtual void           write_at(ulong index, ptr<log_entry>& entry)     = 0;
    virtual ptr<std::vector<ptr<log_entry>>>
                           log_entries(ulong start, ulong end)              = 0;
    virtual ptr<log_entry> entry_at(ulong index)                            = 0;
    virtual ulong          term_at(ulong index)                             = 0;

    virtual bufptr         pack(ulong index, int32 cnt)                     = 0;
    virtual void           apply_pack(ulong index, buffer& pack)            = 0;
    virtual bool           compact(ulong last_log_index)                    = 0;
};
```

Contracts (implementations must uphold these):

- `start_index()` returns the smallest log index still present. Starts at
  `1` on a fresh store. After `compact(N)` succeeds, advances to `N+1`.
- `next_slot()` returns the log index that would be assigned to the next
  `append()` — i.e. `last_appended_index + 1`. Starts at `1`.
- `last_entry()` returns the most recently appended entry, or a dummy
  entry with `get_term() == 0` (and any payload) when the store is empty.
- `entry_at(i)` returns the entry at index `i`, or `nullptr` if `i` is
  outside `[start_index(), next_slot())`.
- `term_at(i)` returns the term of the entry at index `i`, or `0` if `i`
  is outside `[start_index(), next_slot())`.
- `append(entry)` appends `entry` at index `next_slot()`; returns the
  assigned index. `next_slot()` advances by one.
- `write_at(idx, entry)` overwrites the entry at `idx` **and drops
  every entry at index > `idx`**. `next_slot()` becomes `idx + 1`. This
  is how a follower reconciles a conflicting suffix with the leader.
- `log_entries(start, end)` returns entries in the range `[start, end)`
  as a `ptr<std::vector<ptr<log_entry>>>`, or `nullptr` if the range is
  empty or out of bounds.
- `pack(idx, cnt)` produces an opaque buffer encoding `cnt` consecutive
  entries starting at `idx`. `apply_pack(idx, pack)` installs those
  entries into a different store starting at `idx` such that
  `entry_at(idx+k)` on the destination equals the source's
  `entry_at(idx+k)` byte-for-byte for every `0 <= k < cnt`.
- `compact(last_log_index)` drops every entry at index `<= last_log_index`.
  On success, `start_index()` advances to `last_log_index + 1` and
  `next_slot()` is unchanged. Returns `true` on success.

### `fs_log_store`

Header: `<cornerstone/fs_log_store.hxx>`. A concrete `log_store`
implementation backed by three files inside a user-supplied folder.
Non-copyable.

```cpp
class fs_log_store : public log_store {
public:
    fs_log_store(const std::string& log_folder, int buf_size = -1);
    ~fs_log_store();

    // ... every log_store method implemented ...

    void close();
};
```

- The constructor opens (or creates) storage inside `log_folder`.
  `buf_size` is the size (in entries) of the in-memory ring buffer used
  to accelerate reads; `-1` picks a library default.
- On destruction (or explicit `close()`), storage is flushed. The
  observable contract is that a fresh `fs_log_store` on the same folder
  sees the previously-appended entries and their exact bytes (this is
  the crash-recovery contract). The on-disk file layout itself is not
  part of the public specification.

---

## Serialization primitives

### `buffer` and `bufptr`

Header: `<cornerstone/buffer.hxx>`. `buffer` is non-copyable and
non-constructible directly — instances are always held through the
`bufptr` alias.

```cpp
class buffer;
using bufptr = uptr<buffer, void (*)(buffer*)>;

class buffer {
public:
    static bufptr alloc(const size_t size);
    static bufptr copy(const buffer& buf);

    size_t size() const;
    size_t pos()  const;
    void   pos(size_t p);

    int32       get_int();
    ulong       get_ulong();
    byte        get_byte();
    void        get(bufptr& dst);
    const char* get_str();
    byte*       data() const;

    void put(byte b);
    void put(int32 val);
    void put(ulong val);
    void put(const std::string& str);
    void put(const buffer& buf);
};

std::ostream& operator<<(std::ostream& out, buffer& buf);
std::istream& operator>>(std::istream& in,  buffer& buf);
```

Contracts:

- `alloc(size)` allocates a buffer with the given usable size. The
  library may use different internal headers depending on `size` (a
  compact 16-bit-size header for sizes below `0x8000`, a wider 32-bit
  header with a flag bit set for `size >= 0x8000` up to just under
  `0x80000000`) — the public surface is identical in either case, but
  the size and pos accessors must return the size the caller asked for
  and the current read/write position respectively. Requesting a size at
  or above `0x80000000` throws `std::out_of_range`.
- `copy(src)` allocates a new buffer sized for `src.size() - src.pos()`
  and copies those remaining bytes into it. The returned buffer has
  `pos() == 0`; the source is unchanged.
- `pos()` returns the current read/write cursor; `pos(p)` moves it,
  clamping to `size()` if `p` exceeds it.
- `size()` returns the buffer's usable byte capacity.
- `data()` returns a pointer to the buffer's usable byte region at the
  current position.
- Each `put(...)` writes the encoded value at the current `pos()` and
  advances the cursor by the number of bytes written. Attempting to
  write past `size()` throws `std::overflow_error`.
- Each `get_*()` reads the encoded value at the current `pos()` and
  advances the cursor by the number of bytes read. Attempting to read
  past `size()` throws `std::overflow_error`.
- `put(int32)` and `put(ulong)` use **little-endian** encoding across
  4 and 8 bytes respectively; `put(byte)` writes one byte. The library
  exposes the compile-time size constants `sz_int`, `sz_ulong`, `sz_byte`
  (equal to `sizeof(int32)`, `sizeof(ulong)`, `sizeof(byte)`) that
  callers can use in size arithmetic against `pos()`.
- `put(const std::string&)` writes the string bytes **followed by a
  trailing null byte** and advances by `str.length() + 1`.
  `get_str()` reads a C-string from the current position (up to the next
  null byte or `size()`) and advances by `strlen(...) + 1`. Returns
  `nullptr` if no valid null-terminated string is available.
- `put(const buffer& src)` copies `src.size() - src.pos()` bytes from
  `src` into the destination at the destination's current `pos()` and
  advances by that many bytes.
- `get(bufptr& dst)` copies `dst.size() - dst.pos()` bytes from the
  source at the source's `pos()` into `dst`, advancing the source
  cursor.
- `operator<<(ostream, buffer&)` writes the remaining bytes
  (`size() - pos()`) to the stream; `operator>>(istream, buffer&)`
  reads up to `size() - pos()` bytes from the stream into the buffer.
  Both throw `std::ios::failure` on stream error.

### `snapshot`, `snapshot_sync_req`

Headers: `<cornerstone/snapshot.hxx>`,
`<cornerstone/snapshot_sync_req.hxx>`. All non-copyable.

```cpp
class snapshot {
public:
    snapshot(ulong last_log_idx,
             ulong last_log_term,
             const ptr<cluster_config>& last_config,
             ulong size = 0);

    ulong                       get_last_log_idx() const;
    ulong                       get_last_log_term() const;
    ulong                       size() const;
    const ptr<cluster_config>&  get_last_config() const;

    bufptr                      serialize();
    static ptr<snapshot>        deserialize(buffer& buf);
};

class snapshot_sync_req {
public:
    snapshot_sync_req(const ptr<snapshot>& s,
                      ulong offset,
                      bufptr&& buf,
                      bool done);

    snapshot&  get_snapshot() const;
    ulong      get_offset() const;
    buffer&    get_data() const;
    bool       is_done() const;

    bufptr                          serialize();
    static ptr<snapshot_sync_req>   deserialize(buffer& buf);
};
```

Round-trip contracts: for each of `srv_config`, `cluster_config`,
`snapshot`, `snapshot_sync_req`, `log_entry`, calling `deserialize` on
the result of `serialize()` (with the buffer's `pos()` reset to `0`)
must reconstruct an equivalent object with every accessor returning the
same value; nested types (`cluster_config`'s `srv_config` list,
`snapshot`'s `cluster_config`, `snapshot_sync_req`'s inner `snapshot`
and payload) round-trip in the same way. For `snapshot_sync_req` the
payload bytes must survive verbatim.

---

## Async and scheduling

### `async_result<T>`

Header: `<cornerstone/async.hxx>`. Non-copyable. A future-like value
that can be completed (`set_result`) once, and observed either by
blocking (`get()`) or by attaching a continuation (`when_ready`).

```cpp
template <typename T, typename E = ptr<std::exception>>
class async_result {
public:
    typedef std::function<void(T&, const E&)> handler_type;

    async_result();
    explicit async_result(T& result);
    explicit async_result(handler_type& handler);

    template <typename H>
    void when_ready(H&& handler);

    template <typename Res, typename Err>
    void set_result(Res&& result, Err&& err);

    T& get();
};
```

Contracts:

- `set_result(result, err)` completes the async result. If a handler
  has been registered via `when_ready`, that handler is invoked once
  with `(result, err)`. Any thread blocked in `get()` wakes.
- `when_ready(handler)` registers a continuation. If the result is
  already available at registration time, the handler is invoked
  synchronously with the stored `(result, err)`.
- `get()` blocks until the result is available. If `err` is non-null,
  `get()` throws the `err` value (as-is — an `E` = `ptr<std::exception>`
  is thrown by pointer, not dereferenced). Otherwise it returns a
  reference to the stored result.

`rpc_handler` is
`async_result<ptr<resp_msg>, ptr<rpc_exception>>::handler_type`.

### `delayed_task`, `timer_task<void>`, `delayed_task_scheduler`

Headers: `<cornerstone/delayed_task.hxx>`,
`<cornerstone/timer_task.hxx>`,
`<cornerstone/delayed_task_scheduler.hxx>`. All non-copyable.

```cpp
class delayed_task {
public:
    void  cancel();           // subsequent fire is a no-op
    void  reset();             // clears the cancelled flag

protected:
    virtual void exec() = 0;
};

template <typename T> class timer_task;

template <>
class timer_task<void> : public delayed_task {
public:
    using executor = std::function<void()>;
    explicit timer_task(executor& e);
};

class delayed_task_scheduler {
public:
    virtual void schedule(ptr<delayed_task>& task, int32 milliseconds) = 0;
    void         cancel(ptr<delayed_task>& task);   // non-virtual wrapper
protected:
    virtual void cancel_impl(ptr<delayed_task>& task) = 0;
};
```

Contracts:

- `schedule(task, ms)` arranges for the scheduler to fire `task`
  approximately `ms` milliseconds from now. The scheduler owns the timing;
  callers must not assume tighter than millisecond precision.
- `cancel(task)` cancels the pending fire and marks the task cancelled.
  Wrapping `cancel_impl` and marking non-virtual in the interface is
  intentional: subclasses only override `cancel_impl`, not `cancel`.
- After a `cancel` + `reset` + `schedule` sequence, the task fires again
  normally.

### RPC transport interfaces

Headers: `<cornerstone/rpc_cli.hxx>`,
`<cornerstone/rpc_cli_factory.hxx>`, `<cornerstone/rpc_listener.hxx>`,
`<cornerstone/rpc_exception.hxx>`.

```cpp
using rpc_handler = async_result<ptr<resp_msg>, ptr<rpc_exception>>::handler_type;

class rpc_client {
public:
    virtual void send(ptr<req_msg>& req, rpc_handler& when_done) = 0;
};

class rpc_client_factory {
public:
    virtual ptr<rpc_client> create_client(const std::string& endpoint) = 0;
};

class rpc_listener {
public:
    virtual void listen(ptr<msg_handler>& handler) = 0;   // msg_handler = raft_server
    virtual void stop() = 0;
};

class rpc_exception : public std::exception {
public:
    rpc_exception(const std::string& err, ptr<req_msg> req);
    ptr<req_msg>       req() const;
    const char*        what() const throw() override;
};
```

Contracts:

- `rpc_client::send(req, when_done)` sends the request and invokes
  `when_done(response, exception)` when the peer responds (or the
  transport reports failure — in which case `response` is null and
  `exception` is populated with an `rpc_exception` carrying `req`).
- `rpc_client_factory::create_client(endpoint)` returns a fresh
  `rpc_client` that will deliver messages to `endpoint`. The library
  calls this once per peer during raft startup and reuses the returned
  client.
- `rpc_listener::listen(handler)` starts an accept loop on whatever
  transport the implementation uses. For every inbound `req_msg`, the
  listener invokes `handler->process_req(req)` and delivers the returned
  `resp_msg` back to the sender. `stop()` shuts the loop down.

---

## Utility primitives

### `strfmt<N>` and typedefs

Header: `<cornerstone/strfmt.hxx>`. A small printf-style formatter with
a compile-time-sized internal buffer (no allocation). Non-copyable.

```cpp
template <int N>
class strfmt {
public:
    strfmt(const char* fmt);

    template <typename... Args>
    const char* fmt(Args... args);
};
```

`fmt(...)` calls `snprintf` into the internal buffer using the format
string passed to the constructor and returns a pointer to the buffer.
The pointer is valid until the next call to `fmt`.

### `logger` and `asio_service`

Headers: `<cornerstone/logger.hxx>`, `<cornerstone/asio_service.hxx>`.

`logger` is the pure virtual interface every log destination
implements:

```cpp
class logger {
public:
    virtual void debug(const std::string& log_line) = 0;
    virtual void info(const std::string& log_line)  = 0;
    virtual void warn(const std::string& log_line)  = 0;
    virtual void err(const std::string& log_line)   = 0;
};
```

`asio_service` implements both `delayed_task_scheduler` and
`rpc_client_factory` on top of asio. Non-copyable.

```cpp
class asio_service : public delayed_task_scheduler,
                     public rpc_client_factory {
public:
    enum log_level {
        debug, info, warnning, error,
        // preserve typo verbatim; ordering matters
        // (debug < info < warnning < error)
    };

    asio_service();
    ~asio_service();

    void         schedule(ptr<delayed_task>& task, int32 ms) override;
    ptr<logger>  create_logger(log_level level,
                               const std::string& log_file);
    void         stop();
};
```

Contracts:

- `asio_service()` spins up an asio io-service backed by a small
  background thread pool. `stop()` shuts it down.
- `create_logger(level, log_file)` returns a `logger` implementation
  that writes to `log_file` and **filters messages by level**: a call
  to `logger::debug/info/warn/err` is emitted iff its severity is at
  or above the level supplied here, using the ordering above. Setting
  `level = debug` emits everything; setting `level = warnning` drops
  `debug` and `info` calls and emits only `warn` and `err` calls. The
  exact line format (whether lines are prefixed with a timestamp or a
  level tag) is an implementation detail; only the message text needs
  to appear in the output.

---
