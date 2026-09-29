# transitions

Build `transitions`, a lightweight, object-oriented finite state machine library in Python. The library allows users to define states, transitions between states, attach callbacks, and manage state machines on arbitrary Python objects.

## Dependencies

The environment is **offline** — there is no network access, and all dependencies are **already
installed**. Do **not** attempt to install anything (no `pip install`, no `apt-get`). The project
itself is built and installed for you by a `setup.sh` that runs offline against these pre-installed
packages.

The following libraries are available at runtime:

- `six` (Python 2/3 compatibility layer)
- `graphviz` (pure-Python DOT generation, used by the `GraphMachine` diagram support)

## Overview

The library consists of a core state machine module and several extensions:

1. **Core** (`transitions`): `Machine`, `State`, `Transition`, `Event`, `EventData`, `MachineError`
2. **Hierarchical/Nested states** (`transitions.extensions.nesting`): `HierarchicalMachine`, `NestedState`
3. **Markup/Serialization** (`transitions.extensions.markup`): `MarkupMachine`, `HierarchicalMarkupMachine`
4. **Thread-safe locking** (`transitions.extensions.locking`): `LockedMachine`
5. **Factory** (`transitions.extensions.factory`): `MachineFactory`
6. **State features** (`transitions.extensions.states`): `Tags`, `Timeout`, `Volatile`, `Retry`, `Error`, `add_state_features`

## Core Module — `transitions.core`

### `MachineError`

Custom exception (inherits `Exception`) raised for invalid operations (e.g., triggering an event not valid for the current state).

### `State`

Represents a state. Constructor: `State(name, on_enter=None, on_exit=None, ignore_invalid_triggers=None, final=False)`. If `final=True`, entering this state triggers the Machine's `on_final` callbacks. The `name` can be a string or Enum member. The `on_enter` and `on_exit` attributes are mutable lists of callbacks — you can append to them after creation (e.g., `state.on_enter.append(callback)`).

### `EventData`

Holds data about the current event, passed to callbacks when `send_event=True`. Attributes: `state`, `event`, `machine`, `model`, `args`, `kwargs`, `transition`, `error`, `result`.

### `Machine`

The main state machine class.

```python
from transitions import Machine

Machine(model='self', states=None, initial='initial', transitions=None,
        send_event=False, auto_transitions=True, ordered_transitions=False,
        ignore_invalid_triggers=None, before_state_change=None, after_state_change=None,
        name=None, queued=False, prepare_event=None, finalize_event=None,
        model_attribute='state', model_override=False, on_exception=None, on_final=None)
```

Key parameters:
- `model`: Object(s) to manage. `'self'` means the Machine itself. `None` for no initial model. Can be a list.
- `states`: Strings, State objects, dicts (`{'name': ..., 'on_enter': ...}`), or an Enum class.
- `transitions`: Dicts (`{'trigger': ..., 'source': ..., 'dest': ..., 'conditions': ..., 'unless': ..., 'before': ..., 'after': ..., 'prepare': ...}`) or lists `[trigger, source, dest]`. `conditions` are callbacks that must all return `True`. `unless` is the inverse — blocked if any returns `True`.
- `send_event`: If True, callbacks receive an `EventData` object instead of `*args, **kwargs`.
- `auto_transitions`: If True, creates auto-transition methods for every state.
- `queued`: If True, transitions triggered inside callbacks are queued and processed sequentially. In `AsyncMachine`, `queued='model'` gives each model its own independent queue.
- `model_attribute`: Attribute name storing the state (default `'state'`). When customized (e.g., `'status'`), convenience methods become `is_<attribute>_<state>()` and `to_<attribute>_<state>()`.
- `model_override`: If True, the machine binds a generated convenience/trigger method onto a model only when an attribute of that name **already exists** on the model (it overwrites the pre-declared placeholder); names not declared on the model are left unbound. This gate applies to the generated members — `is_<state>()`, `to_<state>()`, `<trigger>()`, `may_<trigger>()`, `trigger`, `may_trigger`. It does **not** apply to the state-storage attribute named by `model_attribute` (default `'state'`): that attribute is always initialized to the initial state and updated on every transition, regardless of `model_override` and whether it pre-exists. So with `model_override=True`, a model that declares `is_A` but neither `state` nor `to_B` will have a working `is_A()` (state is set and `is_A` was declared) while `to_B()` is absent (raising `AttributeError`).
- `name`: Machine name.
- `on_exception`: Callback(s) for handling exceptions in event processing. Catches the exception; state does not change. Note: the model's state attribute is updated to the destination *before* the destination's `on_enter` callbacks run, so if an `on_enter` callback raises with no `on_exception` handler registered, the model is left in the new (destination) state and the machine remains usable for subsequent transitions.
- `on_final`: Callback(s) when a `final=True` state is entered.
- `finalize_event`: Callback(s) after each event completes — runs even on exceptions.

Special transition syntax:
- Source `'*'`: wildcard, matches all states.
- Dest `'='`: reflexive, destination equals source.
- Dest `None`: internal transition (no state change, no enter/exit callbacks).

**Methods:**
- `models` — the public list of registered models that `add_model`/`remove_model` maintain and `dispatch` iterates over.
- `add_model(model, initial=None)` — register a model with the machine (appends to `models`).
- `remove_model(model)` — unregister a model (removes it from `models`).
- `add_state`/`add_states`, `add_transition`/`add_transitions`, `add_ordered_transitions`, `get_state`, `set_state` (no callbacks fired), `get_triggers`, `get_transitions`, `remove_transition`, `dispatch` (trigger on all models).
- `add_ordered_transitions(states=None, trigger='next_state', loop=True, loop_includes_initial=True, conditions=None, ...)` wires the machine's states into a chain advanced by a single auto-generated trigger, named `next_state` by default. With `loop=False` the last state has no outgoing transition, so triggering once more raises `MachineError`; with `loop=True` (default) the chain cycles back to the first state. `conditions` are applied to each step, so a failing condition leaves the state unchanged and returns `False`.

**Model convenience methods:** `model.trigger(name)`, `model.may_trigger(name)`, `model.is_<state>()`, `model.to_<state>()`, `model.may_<trigger>()`, `model.<trigger>()`. Trigger methods return `True` on success, `False` when blocked. Trigger names cannot be the same as `model_attribute` (raises `ValueError`).

**Callback execution order:** Machine-level prepare runs first, then transition-level prepare, then conditions. If conditions pass, the before callbacks run (machine-level then transition-level), then state exit/enter. When the destination state has `final=True`, `on_final` fires here — immediately after the destination's `on_enter` callbacks and before the after callbacks. Then the after callbacks run (transition-level then machine-level), and finally `finalize_event` (which always runs, even on exceptions). So a transition into a final state produces: exit → enter → on_final → after → finalize_event. Callbacks registered both globally and per-transition run twice (no deduplication).

**Dynamic callback resolution:** If the model has methods named `on_enter_<state>` or `on_exit_<state>`, they are automatically called on state entry/exit without explicit registration.

**Custom Transition class:** Subclass `Transition` and set `Machine.transition_cls` to customize transition behavior. The `execute(self, event_data)` method is called when the transition fires.

## Hierarchical/Nested States — `transitions.extensions.nesting`

### `NestedState`

Extends `State` for substates. Its constructor accepts the same parameters as `State` plus an `on_final` callback(s) parameter (so `on_final` is also a valid state-dict key); for a final nested state it fires the state's own `on_final`, and for a parallel parent it fires once when all parallel children are final. Class attribute `separator` controls the delimiter used in nested state naming. Methods: `add_substate(state)`, `add_substates(states)`. Substates attached programmatically via `add_substate`/`add_substates` on a `NestedState` behave identically to declaring them under the dict `'children'` key: when the parent `NestedState` is later passed to a `HierarchicalMachine` (via the constructor's `states` or `add_states`), each attached child is registered as an addressable `Parent<sep>Child` state (e.g. `B_1`) — transitionable and referenceable exactly like a dict-declared child. The child `State` objects need not also appear as separate entries in the top-level `states` list; they are discovered from the parent's attached substates.

### `NestedTransition`

The hierarchical counterpart of `Transition`, also exposed from `transitions.extensions.nesting`. `HierarchicalMachine` uses it as its default `transition_cls`. To customize transition behavior on a `HierarchicalMachine`, set `transition_cls` to a subclass of `NestedTransition` (not the base `Transition`).

### `HierarchicalMachine`

Extends `Machine` for nested states. States can have `'children'` and `'initial'` substate.

```python
states = ['A', {'name': 'B', 'children': ['1', '2'], 'initial': '1'}]
```

Substates named `Parent<sep>Child` (e.g., `B_1`). Transitioning to parent enters initial child. Transitions from parent apply to all children. `is_<parent>(allow_substates=True)` checks ancestry. States can also define their own `'transitions'` within the state dict. Sibling transitions (e.g., `A_1` → `A_2`) do NOT fire the parent's `on_exit`/`on_enter` — only the children's callbacks fire.

When `'children'` is an Enum class, each substate's name in the nested path is the Enum member's **name** (`member.name`), not its value or `str(member)`. So a member `INIT` under parent `'active'` is addressable as `'active_INIT'` (with the configured separator), and `'initial': Phase.INIT` selects that substate. While the active leaf substate is an enum member, the model's state attribute holds the **bare Enum member** (e.g. `Phase.INIT`), not the dotted string path — so `model.state == Phase.INIT` while `is_active(allow_substates=True)` is also True.

**Parallel states:** Use `'parallel'` key instead of `'children'` to enter multiple substates simultaneously:

```python
states = ['A', {'name': 'P', 'parallel': [
    {'name': '1', 'children': ['a', 'b'], 'initial': 'a'},
    {'name': '2', 'children': ['x', 'y'], 'initial': 'x'}
]}]
m = HierarchicalMachine(states=states, initial='A')
m.to_P()
# m.state == ['P_1_a', 'P_2_x']  (a list of active substates)
```

When in parallel states, the model's state attribute becomes a list of active substates. Parallel branches can themselves contain parallel children, and the state value nests to match: one entry per branch of a parallel parent, in declaration order — the branch's active leaf name, or a nested list when that branch is itself parallel. A parallel state value can be fed straight back as `initial=` to reconstruct a machine already in that parallel configuration. A state dict may carry its own `on_final` key (callback(s)), registering a per-state final callback separate from the Machine-level `on_final`. For a parallel parent, this per-state `on_final` fires once, when ALL of its parallel children have reached final states — at which point the Machine-level `on_final` also fires. (Both the per-state and the Machine-level callbacks fire on that same all-children-final transition.) Until then the Machine-level `on_final` is deferred: a branch reaching a `final=True` substate while a sibling branch is still non-final does not fire it. Reflexive transitions in one parallel branch do not affect sibling branches. When the same trigger name is defined as a branch-local transition in more than one currently-active parallel branch, firing that trigger once fires the matching transition in every branch that defines it, so all such branches advance in the single call (this concurrent broadcast is distinct from the reflexive-isolation note above, which concerns a reflexive transition in one branch not touching its siblings).

**Blueprint reuse:** Embed an entire HierarchicalMachine instance as children of a state. Use `'remap'` to redirect terminal states of the child machine to states in the parent: `{'name': 'B', 'children': child_machine, 'remap': {'finished': 'A'}}`. Remap chains cascade through multiple nesting levels.

## Markup/Serialization — `transitions.extensions.markup`

### `MarkupMachine`

Extends `Machine`. Serialize to dict via `.markup` property. Reconstruct with `MarkupMachine(markup=dict)`. `auto_transitions_markup` (bool, default False) controls whether auto-transitions appear in the markup.

The `.markup` property returns a dict that captures the full machine configuration — states, transitions, and settings — in a form suitable for reconstruction. The dict mirrors the constructor input format so it can be fed straight back as `markup=`:

- Top-level keys include `'name'` (the machine name, without any internal suffix), `'initial'` (the initial state), `'model_attribute'` (always present, default `'state'`), `'states'`, and `'transitions'`, alongside the machine settings (`'auto_transitions'`, `'send_event'`, `'queued'`, `'model_override'`, `'ignore_invalid_triggers'`, etc.).
- `'states'` is an **ordered list of dicts**, one per state, each carrying a `'name'` key. A state's registered callbacks are serialized under the same keys used in the constructor input (`'on_enter'`, `'on_exit'`, ...), with each callback preserved as its name string (so a state declared with `on_enter='log_enter'` round-trips to a dict whose `'on_enter'` value contains `'log_enter'`).
- `'transitions'` is a list of dicts, each with `'trigger'`, `'source'`, and `'dest'` keys (plus `'conditions'`/`'unless'` when present), mirroring the constructor transition format.

### `HierarchicalMarkupMachine`

Combines `MarkupMachine` and `HierarchicalMachine`. The markup mirrors the nested constructor input format verbatim: a nested state's dict carries a `'children'` key (an ordered list of child state dicts, each with its own `'name'`), a `'transitions'` list of dicts (`'trigger'`/`'source'`/`'dest'`) for transitions declared inside that state, and an `'initial'` key naming the initial substate — preserved through serialization so the markup can be fed straight back to reconstruct the machine.

## Async State Machines — `transitions.extensions.asyncio`

### `AsyncMachine`

Extends `Machine` for asynchronous callback processing using `asyncio`. Trigger methods become coroutines that must be `await`ed.

```python
from transitions.extensions.asyncio import AsyncMachine
```

Same constructor parameters as `Machine`. Callbacks (before, after, on_enter, on_exit, conditions) can be async functions — they will be awaited automatically. Synchronous callbacks also work.

Usage: trigger methods are coroutines driven by `asyncio.run()`:

```python
async def run():
    m = AsyncMachine(states=['A', 'B'], transitions=[['go', 'A', 'B']], initial='A')
    await m.go()
asyncio.run(run())
```

### `HierarchicalAsyncMachine`

Combines `HierarchicalMachine` and `AsyncMachine` — supports nested states with async callbacks.

```python
from transitions.extensions.asyncio import HierarchicalAsyncMachine
```

### `AsyncTimeout`

Async variant of `Timeout` state feature. Uses `asyncio.sleep` instead of threading timers. Used with `add_state_features` on `AsyncMachine`.

## Diagrams — `transitions.extensions.diagrams`

### `GraphMachine`

Extends `Machine` (via `MarkupMachine`) to generate Graphviz DOT diagrams of the state machine. Requires the `graphviz` Python package.

```python
from transitions.extensions.diagrams import GraphMachine
```

Constructor accepts all `Machine` parameters plus: `title` (graph label), `show_conditions` (bool, display condition names on edges), `show_state_attributes` (bool).

`get_graph()` returns a `graphviz.Digraph` object. The `.source` attribute contains the DOT language string. The current (active) state is highlighted with distinct styling (color/fill). Transitions appear as labeled edges; conditions appear in edge labels when `show_conditions=True`.

For hierarchical states, can be combined with `HierarchicalMachine` via multiple inheritance (e.g. `MachineFactory.get_predefined(graph=True, nested=True)`). Each parent state that has children is rendered as a grouped Graphviz subgraph named `cluster_<parent>` (using the parent's name), so the DOT `.source` contains a `subgraph cluster_<parent>` block for every nested parent.

## Thread-safe Locking — `transitions.extensions.locking`

### `LockedMachine`

Extends `Machine` with threading locks around event triggers. Same API as `Machine`. Accepts a `machine_context` parameter for custom context managers: it takes **either a single context manager or a list of context managers**, and each one is entered (in declaration order) around every event trigger and exited afterward. When omitted, the machine uses a default internal lock. Passing a single context manager object (e.g. `machine_context=ctx`) is the canonical usage and must be accepted — it is treated the same as a one-element list.

**Picklability:** Machines support `pickle.dumps`/`pickle.loads`, including `LockedMachine` and the hierarchical/factory-composed locked variants (e.g. `LockedHierarchicalMachine` from `MachineFactory`). The unpickled machine is an independent copy that preserves the current state (including a nested state like `'B_1'`) and remains fully functional (e.g. `is_B()` / `is_B(allow_substates=True)` and further triggers), with no shared mutable state linking it back to the original.

## Factory — `transitions.extensions.factory`

### `MachineFactory`

`MachineFactory.get_predefined(graph=False, nested=False, locked=False)` returns a Machine class combining requested features. `get_predefined(nested=True, locked=True)` returns `LockedHierarchicalMachine`.

## State Features — `transitions.extensions.states`

### `add_state_features(*features)`

Decorator that composes state feature mix-ins into a Machine subclass:

```python
@add_state_features(Tags, Timeout, Volatile, Retry, Error)
class CustomMachine(Machine):
    pass
```

### `Tags`

Adds tag support: `{'name': 'A', 'tags': ['important']}`. Access via `state.is_<tag>` (True if tag present, False otherwise).

### `Timeout`

Timer starts on state entry; fires `on_timeout` callbacks if not exited in time. `{'name': 'B', 'timeout': 5.0, 'on_timeout': 'handle_timeout'}`. Timer cancelled on exit.

### `Volatile`

Fresh scope object created on each state entry, deleted on exit. `{'name': 'A', 'volatile': dict}`. Access via `model.scope`.

### `Retry`

Limits self-transitions. `{'name': 'retrying', 'retries': 3, 'on_failure': 'to_failed'}`. A self-transition that would exceed the limit is refused; the `on_failure` callback(s) are invoked on the model instead of raising. The retry counter resets when the state is entered from a different state.

### `Error`

Rejects entry into *terminal* (dead-end) states that are not marked as accepted. A state is checked on entry only when it is both **not** marked accepted **and** has no outgoing transitions (no trigger leaves it); entering such a state raises `MachineError`. Mark a state accepted with `'accepted': True` or `'tags': ['accepted']` to exempt it. `state.is_accepted` checks the flag. Ordinary intermediate states — even unmarked ones — are entered normally as long as they still have at least one outgoing transition, so a machine only raises when it would otherwise be stuck in an unaccepted dead end.
