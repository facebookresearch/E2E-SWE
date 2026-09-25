# maki

Build `maki`, a header-only C++17 finite-state-machine (FSM) library. Maki
gives users a declarative way to describe transition tables (which events
drive the machine from which source state to which target state, with
optional actions and guards) and then compile them into a strongly typed,
run-to-completion state machine.

All public types live in `namespace maki`. The library is header-only,
does not use RTTI, does not throw except when the user's own action /
entry / exit callbacks do, and depends only on the C++ standard library.

## Dependencies

- A C++17-capable compiler (`g++` is available).

## Build and install contract

The library must install its public headers so that a downstream C++17
program using `#include <maki.hpp>` (no `-I` flag) resolves them via the
default include path. On typical Linux installations that means:

```
/usr/local/include/maki.hpp        # umbrella header
/usr/local/include/maki/*.hpp      # component sub-headers
```

A downstream driver should build and run with:

```
g++ -std=c++17 driver.cpp -o driver
./driver
```

Provide an install step (e.g., a `setup.sh` script that copies the headers
into place). Nothing beyond `g++` should be required at build time.

## Public header layout

The library ships one umbrella `maki.hpp` that includes every public
name — users write `#include <maki.hpp>` and get the whole library. The
API sections below describe every public type, function, and constant;
splitting them into sub-headers under `maki/` is optional as long as
`#include <maki.hpp>` reaches all of them.

## Core concepts

Maki is used in three phases:

1. **Describe:** declare `constexpr` state molds (`state_mold`), a
   transition table (`transition_table`), and wrap them into a
   `machine_conf`.
2. **Instantiate:** define a `struct` that holds the `machine_conf` in a
   `static constexpr auto value` member (the "conf holder"), then use it
   as the template argument of `maki::machine`.
3. **Drive:** call `process_event(event)` on the instantiated machine.

Example:

```cpp
#include <maki.hpp>

struct context {};

struct on_button_press{};
struct off_button_press{};

constexpr auto off = maki::state_mold{};
constexpr auto on  = maki::state_mold{};

constexpr auto table = maki::transition_table{}
    (maki::ini, off)
    (off, on,  maki::event<on_button_press>)
    (on,  off, maki::event<off_button_press>)
;

struct conf {
    static constexpr auto value = maki::machine_conf{}
        .transition_tables(table)
        .context_a<context>()
    ;
};

using machine_t = maki::machine<conf>;

int main() {
    auto m = machine_t{};       // auto-starts, entering `off`
    m.process_event(on_button_press{});   // off -> on
    m.process_event(off_button_press{});  // on  -> off
}
```

## `state_mold` — declaring a state

```cpp
template<class Impl = /* default */>
class state_mold {
public:
    constexpr state_mold();

    // Attach a context type to this state, using one of four constructor
    // signatures (see `state_context_signature`):
    //   context_v<T>()  — T()
    //   context_c<T>()  — T(parent_context&)
    //   context_cm<T>() — T(parent_context&, machine&)
    //   context_m<T>()  — T(machine&)
    template<class T> [[nodiscard]] constexpr auto context_v() const;
    template<class T> [[nodiscard]] constexpr auto context_c() const;
    template<class T> [[nodiscard]] constexpr auto context_cm() const;
    template<class T> [[nodiscard]] constexpr auto context_m() const;

    // Context lifetime: `parent` (default) or `state_activity` (recreated
    // on every entry, destroyed on every exit).
    [[nodiscard]] constexpr auto
    context_lifetime(state_context_lifetime value) const;

    // Entry / internal / exit actions — {entry,internal,exit}_action_SUFFIX
    // with the 8 signature suffixes documented in the "action and guard"
    // section below. Three overload forms:
    //   _SUFFIX(Callable)                — any event (entry/exit only)
    //   _SUFFIX<Event>(Callable)         — one event type
    //   _SUFFIX(event_set, Callable)     — a set of event types
    // Multiple calls append to the ordered action list.

    // Add a transition table for a *composite* state — states declared in
    // the table are sub-states of this state.
    template<class... TransitionTables>
    [[nodiscard]] constexpr auto
    transition_tables(const TransitionTables&... tables) const;

    // Defer one event type or an event_set. Deferred events are held while
    // the state is active and processed after the state exits.
    template<class Event>
    [[nodiscard]] constexpr auto defer() const;
    template<class EventSetImpl>
    [[nodiscard]] constexpr auto
    defer(const event_set<EventSetImpl>& events) const;
};

// Class template argument deduction guide:
state_mold() -> state_mold</* default */>;
```

State molds are chained builders — every setter returns a new mold with
the setting applied, so they compose:

```cpp
constexpr auto ready = maki::state_mold{}
    .context_v<ready_data>()
    .entry_action_c([](ready_data& d){ d.counter = 0; })
    .internal_action_c<tick>([](ready_data& d){ ++d.counter; })
    .defer<slow_event>()
;
```

## `action` and `guard` — signature-tagged callables

Actions and guards use signature suffixes to declare what arguments the
callable takes. The `action_signature` enum (in `maki/action.hpp`) and
the `guard_signature` enum (in `maki/guard.hpp`) both cover the same set
of signatures:

| suffix | signature                                           |
|--------|-----------------------------------------------------|
| `v`    | `()`                                                |
| `c`    | `(context&)`                                        |
| `cm`   | `(context&, machine&)`                              |
| `cme`  | `(context&, machine&, const event&)`                |
| `ce`   | `(context&, const event&)`                          |
| `m`    | `(machine&)`                                        |
| `me`   | `(machine&, const event&)`                          |
| `e`    | `(const event&)`                                    |

Actions return `void`; guards return `bool`. Const-ness of guard
parameters is mandated (guards receive `const context&`, `const machine&`,
`const event&`).

Free-function builders create the tagged objects:

```cpp
namespace maki {
    // For each SUFFIX in {v, c, cm, cme, ce, m, me, e}:
    template<class Callable>
    constexpr auto action_SUFFIX(const Callable&);   // returns void
    template<class Callable>
    constexpr auto guard_SUFFIX(const Callable&);    // returns bool
}
```

Guards compose via boolean operators, each producing a new guard:

```cpp
auto g = !g1;                    // logical NOT
auto g = g1 && g2;               // logical AND
auto g = g1 || g2;               // logical OR
auto g = g1 != g2;               // logical XOR
```

Composed guards evaluate their operands in order and short-circuit for
`&&` and `||`.

## `transition_table` — the transition rules

```cpp
template<class Impl = /* default */>
class transition_table {
public:
    constexpr transition_table();
    constexpr transition_table(const transition_table&) = default;

    // Append one transition; returns a new transition_table.
    // Signatures accepted (each argument is optional after `target`):
    //   (source, target)
    //   (source, target, event)
    //   (source, target, event, action)
    //   (source, target, event, action, guard)
    //
    // Special cases:
    //   - The very first transition MUST be `(maki::ini, initial_state)`.
    //     From `ini`, the event MUST be `maki::null` (or omitted) and the
    //     guard MUST be `maki::null` (or omitted).
    //   - `source` may be a `state_mold` OR a `state_set` (matches any of
    //     several source states).
    //   - `target` may be a `state_mold`, `maki::fin` (final pseudostate),
    //     or `maki::null` (marks the transition as an internal transition
    //     — no exit/entry actions, just the transition action).
    //   - `event` may be `maki::event<E>`, an `event_set`, or `maki::null`
    //     (null means completion / anonymous transition — fires as soon as
    //     the source state becomes active).
    //   - `action` may be `maki::null` (no action) or any `maki::action<..>`.
    //   - `guard` may be `maki::null` (no guard) or any `maki::guard<..>`.
    template<class Source, class Target, class Event = /* null */,
             class ActionOrNull = /* null */, class GuardOrNull = /* null */>
    constexpr auto operator()(
        const Source& source,
        const Target& target,
        const Event& event = maki::null,
        const ActionOrNull& action = maki::null,
        const GuardOrNull& guard = maki::null
    );
};
```

When `process_event(e)` is called and the machine is in state `S`, the
runtime scans the transition table from top to bottom and picks the first
transition whose source matches (`S` is contained in the source
`state_mold`/`state_set`), whose event matches (`E` is the event type or
belongs to the event set), and whose guard evaluates to `true`. Fires
one transition per event (unless the target enables completion
transitions, which then fire recursively via run-to-completion).

## `machine_conf` — configuring a machine

`maki::machine_conf` is a fluent builder that produces the configuration
consumed by `maki::machine`. All setters return a new configuration
object; the final configuration is stored in a `struct` (the "conf holder")
that exposes it as `static constexpr auto value = ...;` because the
configuration type is not default-constructible.

```cpp
template<class Impl>
class machine_conf {
public:
    constexpr machine_conf();

    // Set the machine's list of transition tables. One region per table.
    // Passing N tables creates N independent (orthogonal) regions; every
    // event is dispatched to every region in order.
    template<class... TransitionTables>
    [[nodiscard]] constexpr auto
    transition_tables(const TransitionTables&... tables) const;

    // Set the machine's context type. Same signature suffixes as state
    // context builders (with only `a` and `am`, since the machine context
    // is instantiated with arguments forwarded from the machine ctor):
    //   context_a<T>()   — T(MachineCtorArgs&&...)
    //   context_am<T>()  — T(MachineCtorArgs&&..., machine&)
    template<class T> [[nodiscard]] constexpr auto context_a() const;
    template<class T> [[nodiscard]] constexpr auto context_am() const;

    // Whether the constructor should call start() (default: true).
    [[nodiscard]] constexpr auto auto_start(bool value) const;

    // Whether run-to-completion is enabled (default: true). If disabled,
    // recursive process_event() calls are not deferred — the second call
    // pre-empts the first, which is unsafe unless the user avoids it.
    [[nodiscard]] constexpr auto run_to_completion(bool value) const;

    // Install a top-level exception handler. If set, every non-const member
    // function of `machine` wraps its body in `try { ... }
    // catch (...) { handler(*this, current_exception()); }`. Handler
    // signature: `void(machine&, const std::exception_ptr&)`.
    template<class Callable>
    [[nodiscard]] constexpr auto catch_mx(const Callable& handler) const;
};
```

Note: `auto_start` and `run_to_completion` take a **runtime** `bool` argument
(e.g. `.auto_start(false)`) — not a template parameter.

## `machine` — the state-machine class template

```cpp
template<class ConfHolder>
class machine {
public:
    static constexpr const auto& conf = ConfHolder::value;
    using context_type = /* deduced from conf */;

    // Constructor: forwards ctx_args to the root context's constructor,
    // then (unless auto_start is false) calls start().
    template<class... ContextArgs>
    explicit machine(ContextArgs&&... ctx_args);

    // Non-copyable, non-movable.
    machine(const machine&) = delete;
    machine(machine&&) = delete;
    machine& operator=(const machine&) = delete;
    machine& operator=(machine&&) = delete;

    // Access the root context.
    context_type& context();
    const context_type& context() const;

    // Whether the (single-region) machine is currently running.
    [[nodiscard]] bool running() const;

    // Start / stop. The template `Event` argument is optional and defaults
    // to `events::start` / `events::stop`. If a custom event is passed,
    // it is forwarded to the entry (start) / exit (stop) actions.
    template<class Event = events::start>
    void start(const Event& event = {});
    template<class Event = events::stop>
    void stop(const Event& event = {});

    // Process an event through the transition table. Under run-to-completion,
    // recursive calls are deferred to an internal queue and processed after
    // the current event finishes.
    template<class Event>
    void process_event(const Event& event);

    // State access. `state<StateMold>()` returns the `maki::state` object
    // corresponding to the given state_mold. Only valid on single-region
    // machines.
    template<const auto& StateMold>
    [[nodiscard]] const auto& state() const;

    // Whether the state created by `StateMold` is currently active. Only
    // valid on single-region machines.
    template<const auto& StateMold>
    [[nodiscard]] bool is() const;
};
```

## `state` — one live state within a machine

```cpp
template<class Impl>
class state {
public:
    // For composite states: whether the state created by `StateMold` is
    // active inside this composite state. Only valid if this state is
    // composite and has one region.
    template<const auto& StateMold>
    [[nodiscard]] bool is() const;

    // The state's local context (if it has one). For `parent`-lifetime
    // state data this returns a reference to the stored value; for
    // `state_activity`-lifetime state data this returns an optional-like
    // handle whose `has_value()` is `true` iff the state is currently
    // active, and whose `operator->` / `operator*` yield the stored value.
    [[nodiscard]] const auto& context() const;
};
```

## Predefined objects

- `maki::ini` (of type `maki::ini_t`) — the initial pseudostate. Used as
  the source of the first transition in a table to designate the initial
  state.
- `maki::fin` (of type `maki::fin_t`) — the final pseudostate. Used as
  the target of a transition to mark termination.
- `maki::null` (of type `maki::null_t`) — placeholder for a null event,
  null action, null guard, or null target (which marks the transition as
  internal).
- `maki::undefined` (of type `state_mold<..>`) — the "undefined" state
  mold. The machine lands here after an uncaught exception in a transition
  (see Semantics summary items 13-14); use as a transition source to recover.
- `maki::events::start`, `maki::events::stop` — default events passed to
  `start()` / `stop()` when the user does not provide one.

## `event_t` and `event_set`

`maki::event_t<E>` is an empty tag type; `maki::event<E>` is a `constexpr`
variable of type `event_t<E>`. Pass `maki::event<E>` wherever the API
wants a single event type.

`maki::event_set<Impl>` describes a *set* of event types. It supports:

- `event_set{maki::event<E>}` — construct a single-element set.
- `.contains<E>()` and `.contains(maki::event<E>)` — membership predicate.
- Operators (all `constexpr`, `x` and `y` may each be `event_set` or
  `event<E>`):
  - `!x`         — complement.
  - `x || y`     — union.
  - `s1 && s2`   — intersection (both operands `event_set`).
- `maki::all_events` — universal `event_set`.
- `maki::no_event`   — empty `event_set`.

## `state_set`

`maki::state_set<Impl>` is the state-side analogue of `event_set`. It
supports:

- Operators (all `constexpr`, `x` and `y` may each be `state_set` or
  `state_mold`):
  - `!x`       — complement.
  - `x || y`   — union.
  - `s1 && s2` — intersection (both operands `state_set`).
- `maki::all_states`, `maki::no_state` — sentinels.

Use `state_set` values as transition-table sources when the same
transition should fire from many states.

## Usage examples

The following snippets demonstrate the shape of each part of the API in
isolation. They are library documentation — sketches, not compilable
programs — meant to show how the pieces compose in practice.

### `!state_mold` as a transition source

```cpp
constexpr auto off = maki::state_mold{};
constexpr auto s1  = maki::state_mold{};
constexpr auto s2  = maki::state_mold{};

constexpr auto table = maki::transition_table{}
    (maki::ini, off)
    (off, s1, maki::event<start_evt>)
    (s1,  s2, maki::event<step_evt>)
    (!off, off, maki::event<power_off>)   // state_set source
;
// The `!` operator complements a `state_mold` to produce a `state_set`,
// so `!off` fires from any state other than `off`.
```

### `entry_action_ce<Event>(Callable)` — event-typed entry action

```cpp
struct login_evt { std::string user; };
struct ctx { std::string last_user; };

constexpr auto logged_in = maki::state_mold{}
    .context_v<ctx>()
    .entry_action_ce<login_evt>(
        [](ctx& c, const login_evt& e) {
            c.last_user = e.user;
        }
    )
;
// The event type (`login_evt`) is a template parameter; the callable is the
// runtime argument. The callable receives the state's context and the
// entering event.
```

### Composite state with entry / exit + inner transitions

```cpp
struct ctx { int outer_entries = 0; int outer_exits = 0; };

constexpr auto idle = maki::state_mold{};
constexpr auto busy = maki::state_mold{};

constexpr auto session_table = maki::transition_table{}
    (maki::ini, idle)
    (idle, busy, maki::event<request>)
    (busy, idle, maki::event<done>)
;

constexpr auto session = maki::state_mold{}
    .transition_tables(session_table)
    .entry_action_c([](ctx& c){ ++c.outer_entries; })
    .exit_action_c ([](ctx& c){ ++c.outer_exits;   })
;
// Entering `session` fires session's entry action, THEN runs
// session_table's `ini` transition (entering `idle`). Exiting `session`
// fires the current inner state's exit BEFORE session's exit action.
```

### `.auto_start(false)` and `.run_to_completion(true)` — runtime bool

```cpp
struct conf {
    static constexpr auto value = maki::machine_conf{}
        .transition_tables(table)
        .context_a<ctx>()
        .auto_start(false)         // do NOT auto-start; caller invokes start()
        .run_to_completion(true)   // enable RTC queue (also the default)
    ;
};
// Both take a runtime `bool` argument. There is no template form.
```

### `machine::context()` vs `machine::state<S>().context()`

```cpp
struct root_ctx  { int global = 0; };
struct state_ctx { int local  = 0; };

constexpr auto s = maki::state_mold{}.context_v<state_ctx>();
constexpr auto table = maki::transition_table{}(maki::ini, s);

struct conf {
    static constexpr auto value = maki::machine_conf{}
        .transition_tables(table)
        .context_a<root_ctx>();
};

auto m = maki::machine<conf>{};
m.context().global = 1;                  // machine-level (root) context
m.state<s>().context().local = 2;        // state-level (per-state) context
```

### Run-to-completion — recursive `process_event` from an action

```cpp
struct ctx { int step = 0; };
struct outer_evt{}; struct inner_evt{};

constexpr auto s0 = maki::state_mold{}
    .internal_action_cm<outer_evt>(
        [](ctx& c, auto& mach) {
            c.step = 1;
            mach.process_event(inner_evt{});   // queued, NOT re-entered
            c.step = 2;                          // still inside the outer action
        }
    )
;
constexpr auto s1 = maki::state_mold{}
    .entry_action_c([](ctx& c){ c.step = 3; })   // fires after outer action returns
;
constexpr auto table = maki::transition_table{}
    (maki::ini, s0)
    (s0, s1, maki::event<inner_evt>)
;
// Contract: from inside an action, `process_event` enqueues the event on
// the RTC queue. The queued event fires after the current dispatch drains.
```

### `defer<E>()` and `defer(event_set{...})`

```cpp
struct init_done{};
struct do_work{};
struct other_work{};

constexpr auto initializing = maki::state_mold{}
    .defer<do_work>()
    // Or a set: .defer(maki::event<do_work> || maki::event<other_work>)
;
constexpr auto ready = maki::state_mold{}
    .internal_action_c<do_work>([](auto& c){ ++c.processed; })
;

constexpr auto table = maki::transition_table{}
    (maki::ini, initializing)
    (initializing, ready, maki::event<init_done>)
;
// Events matching the deferred set are held while `initializing` is active.
// On the transition to `ready`, they are re-dispatched in FIFO order.
```

### State data — `parent` vs `state_activity` lifetime

```cpp
struct counter { int n = 0; };

// `parent` (default): counter lives with the enclosing container.
constexpr auto persistent = maki::state_mold{}
    .context_v<counter>();

// `state_activity`: counter is constructed on entry, destroyed on exit.
constexpr auto transient = maki::state_mold{}
    .context_v<counter>()
    .context_lifetime(maki::state_context_lifetime::state_activity);

// Access shape depends on lifetime:
//   m.state<persistent>().context().n         -- direct reference
//   m.state<transient >().context().has_value() -- optional-like handle
//   m.state<transient >().context()->n         -- deref while state is active
```

### Guard operators composed in a transition table

```cpp
struct evt { bool a; bool b; };
constexpr auto is_a = maki::guard_e([](const evt& e){ return e.a; });
constexpr auto is_b = maki::guard_e([](const evt& e){ return e.b; });

constexpr auto start = maki::state_mold{};
constexpr auto both  = maki::state_mold{};
constexpr auto only  = maki::state_mold{};
constexpr auto none  = maki::state_mold{};

constexpr auto table = maki::transition_table{}
    (maki::ini, start)
    (start, both, maki::event<evt>, maki::null, is_a && is_b)   // AND
    (start, only, maki::event<evt>, maki::null, is_a != is_b)   // XOR
    (start, none, maki::event<evt>, maki::null, !is_a && !is_b) // both false
;
// Guards compose via !, &&, ||, != to produce new guards. The transition
// table is scanned top-to-bottom; the first row whose guard yields true
// fires.
```

### `event_set` composition + `contains<E>()`

```cpp
struct click{}; struct hover{}; struct scroll{};

// Two-element set (union of two individual events):
constexpr auto mouse_input = maki::event<click> || maki::event<hover>;

// Compile-time membership predicate:
static_assert(mouse_input.template contains<click>());
static_assert(!mouse_input.template contains<scroll>());

// Complement and intersection:
constexpr auto not_click = !maki::event<click>;
constexpr auto both      = mouse_input &&
                           (maki::event<click> || maki::event<scroll>);
// `both` contains only `click`.

// Sentinels: maki::all_events / maki::no_event.
```

### `state_set` complement, union, intersection

```cpp
constexpr auto a = maki::state_mold{};
constexpr auto b = maki::state_mold{};
constexpr auto c = maki::state_mold{};

constexpr auto anywhere_but_a = !a;                    // complement
constexpr auto b_or_c         = b || c;                // union
constexpr auto both           = (a || b) && (b || c);  // intersection -> {b}

// Use as a transition-table source:
constexpr auto table = maki::transition_table{}
    (maki::ini, a)
    (b_or_c, a, maki::event<pause>)   // fires from `b` or `c` only
;
```

### `catch_mx` handler + `maki::undefined` recovery

```cpp
struct ctx { int caught = 0; };
struct trigger{}; struct rescue{};

constexpr auto off = maki::state_mold{};
constexpr auto on  = maki::state_mold{}
    .entry_action_c([](ctx&){ throw std::runtime_error{"crashed"}; });

constexpr auto table = maki::transition_table{}
    (maki::ini, off)
    (off, on, maki::event<trigger>)
    (maki::undefined, off, maki::event<rescue>)   // recovery source
;

struct conf {
    static constexpr auto value = maki::machine_conf{}
        .transition_tables(table)
        .context_a<ctx>()
        .catch_mx([](auto& m, const std::exception_ptr&){ ++m.context().caught; });
};
// When `on`'s entry throws, `catch_mx` runs, the machine lands in
// `maki::undefined`, and dispatching `rescue` transitions back to `off`.
```

### Custom event forwarded through `.start(evt)`

```cpp
struct init_payload { std::string user; };
struct ctx { std::string user; };

constexpr auto initial = maki::state_mold{}
    .entry_action_ce<init_payload>(
        [](ctx& c, const init_payload& p){ c.user = p.user; }
    );

constexpr auto table = maki::transition_table{}(maki::ini, initial);

struct conf {
    static constexpr auto value = maki::machine_conf{}
        .transition_tables(table)
        .context_a<ctx>()
        .auto_start(false);
};

auto m = maki::machine<conf>{};
m.start(init_payload{"alice"});   // forwarded to initial's entry_action_ce
// Calling `.start()` with no argument passes `events::start` instead; only
// entry actions filtered on `events::start` see that default event.
```

### All 8 action-signature suffixes

```cpp
struct ctx {};
struct ev{};

constexpr auto a_v   = maki::action_v ([]{});
constexpr auto a_c   = maki::action_c ([](ctx&){});
constexpr auto a_cm  = maki::action_cm([](ctx&, auto&){});
constexpr auto a_cme = maki::action_cme([](ctx&, auto&, const ev&){});
constexpr auto a_ce  = maki::action_ce ([](ctx&, const ev&){});
constexpr auto a_m   = maki::action_m ([](auto&){});
constexpr auto a_me  = maki::action_me ([](auto&, const ev&){});
constexpr auto a_e   = maki::action_e  ([](const ev&){});
// Suffix meaning: v=(), c=(ctx&), cm=(ctx&,machine&),
// cme=(ctx&,machine&,const event&), ce=(ctx&,const event&),
// m=(machine&), me=(machine&,const event&), e=(const event&).
// The same 8 suffixes are used by entry_action_*, exit_action_*,
// internal_action_*, and guard_*. Guard bodies must return bool and
// their reference parameters are const-qualified.
```

### `context_a<T>()` vs `context_am<T>()` at machine scope

```cpp
struct wide_ctx { int n; std::string s; };

// `context_a<T>()`: T's constructor receives the arguments forwarded from
// the machine constructor.
struct conf_a {
    static constexpr auto value = maki::machine_conf{}
        .transition_tables(table)
        .context_a<wide_ctx>();
};
auto m1 = maki::machine<conf_a>{42, std::string{"hello"}};
// -> wide_ctx(42, "hello")

// `context_am<T>()`: T's constructor receives the forwarded arguments AND
// a reference to the enclosing machine, e.g. T(int, std::string, machine&).
```

### Internal transition (target `maki::null`) + `internal_action_*`

```cpp
struct ctx { int entries = 0; int exits = 0; int pulses = 0; };
struct pulse{};

constexpr auto also_pulse = maki::action_c([](ctx& c){ ++c.pulses; });

constexpr auto s = maki::state_mold{}
    .entry_action_c([](ctx& c){ ++c.entries; })
    .exit_action_c ([](ctx& c){ ++c.exits;   })
    .internal_action_c<pulse>([](ctx& c){ ++c.pulses; })
;

constexpr auto table = maki::transition_table{}
    (maki::ini, s)
    (s, maki::null, maki::event<pulse>, also_pulse)   // null target -> internal
;
// Both forms — the state's `internal_action_*` and a transition row whose
// target is `maki::null` — fire without exit/entry actions and without
// changing the active state.
```

### Completion transition (event `maki::null`)

```cpp
struct go{};
constexpr auto s0 = maki::state_mold{};
constexpr auto s1 = maki::state_mold{};
constexpr auto s2 = maki::state_mold{};

constexpr auto table = maki::transition_table{}
    (maki::ini, s0)
    (s0, s1, maki::event<go>)
    (s1, s2, maki::null)   // completion transition
;
// A completion transition fires as soon as its source state is entered,
// with no external event required. Dispatching one `go` walks the chain
// s0 -> s1 -> s2 under the same run-to-completion pass; a chain of
// completion transitions unrolls in a single dispatch.
```

### Orthogonal regions (N transition tables in one `machine_conf`)

```cpp
struct e_toggle{}; struct e_advance{};

constexpr auto locked   = maki::state_mold{};
constexpr auto unlocked = maki::state_mold{};
constexpr auto ready    = maki::state_mold{};
constexpr auto busy     = maki::state_mold{};

constexpr auto region_lock  = maki::transition_table{}
    (maki::ini, locked)
    (locked, unlocked, maki::event<e_toggle>);

constexpr auto region_state = maki::transition_table{}
    (maki::ini, ready)
    (ready, busy, maki::event<e_advance>);

struct conf {
    static constexpr auto value = maki::machine_conf{}
        .transition_tables(region_lock, region_state)   // N tables => N regions
        .context_a<ctx>();
};
// Every event is dispatched to every region in order; each region only
// transitions if one of its own rows matches the event.
```

## Semantics summary — the specification

1. **Auto-start.** If `machine_conf::auto_start` is unset or `true`, the
   `machine` constructor calls `start()` after constructing the context.
2. **`is<S>()` and initial state.** After a successful `start()`, the
   initial state (target of the `ini` transition) becomes active.
   `machine::is<S>()` returns whether `S` is currently active in the
   single region of the machine.
3. **Event dispatch matches on type.** `process_event(E{})` picks the
   first transition in the current region's transition table whose source
   is currently active AND whose event type is `E` (or whose event set
   contains `E`) AND whose guard evaluates to `true`.
4. **Transition ordering.** On a successful transition:
   - the source state's exit action(s) fire (matching the event type);
   - the transition's action fires;
   - the target state is made active;
   - the target state's entry action(s) fire (matching the event type).
5. **Internal transition.** A transition whose target is `maki::null`
   fires the transition action but does not run exit or entry actions and
   does not change the active state. Similarly, a state's
   `internal_action_*` fires without any exit or entry.
6. **Completion transition.** A transition whose event is `maki::null`
   fires immediately after the target state is entered, without needing
   an external event. Chains of completion transitions unroll during a
   single event dispatch.
7. **Run-to-completion.** With RTC enabled (default), a recursive call to
   `process_event` from inside an action does not re-enter — the recursive
   event is queued and processed after the current dispatch completes.
8. **Event deferral.** A state that declares `.defer<E>()` (or
   `.defer(event_set{...})`) holds events of that type while it is active
   without dispatching them. When the state exits, deferred events are
   re-dispatched in the order they arrived.
9. **State data.** A state with `.context_v<Data>()` (or one of the
   other context signature variants) owns a `Data` instance accessible
   via `machine::state<S>().context()`. Default lifetime is `parent` (the
   data lives as long as the enclosing container); with
   `.context_lifetime(state_context_lifetime::state_activity)` the data
   is instantiated on entry and destroyed on exit, and `state<S>::context()`
   returns an optional-like handle whose `has_value()` reflects whether
   the state is currently active.
10. **Composite state.** A state with `.transition_tables(...)` is a
    composite — the tables describe its internal FSM. Entering the
    composite runs its own `ini` transition; the inner state may be
    queried via `machine::state<Outer>().is<Inner>()` on single-region
    composites. Re-entering a composite resets its inner region to the
    initial substate.
11. **Orthogonal regions.** `machine_conf::transition_tables(t0, t1, ...)`
    with N tables creates N independent regions. Every event is dispatched
    to every region in order; each region's transitions fire independently.
12. **State-set source.** A source that is a `state_set` matches every
    state in the set; e.g. `!off` fires from any state other than `off`.
13. **Exceptions without `catch_mx`.** If a user callback throws during a
    transition, the exception propagates out of `process_event` and the
    machine is left in the `maki::undefined` state (the source's exit
    action has already run, and the target's entry action was interrupted).
14. **Exceptions with `catch_mx`.** If a `catch_mx` handler is configured,
    the exception is intercepted by the handler; the machine is still left
    in the `maki::undefined` state, and the handler may drive a recovery
    transition (e.g. `(maki::undefined, off, maki::event<rescue>)`).

The behavior specified above is the library's contract; everything not
documented is at your discretion — you are free to organise the
implementation however you like as long as the observable behavior above
holds.
