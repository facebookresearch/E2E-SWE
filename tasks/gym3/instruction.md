# vectorenv

Build `vectorenv`, a small library for **vectorized reinforcement-learning
environments**: a batch of `num` independent episodes is stepped together behind
one object. The library defines a value-type system for describing
observation/action spaces as (possibly nested) trees of tensors, numpy helpers
that operate over those trees, a base environment interface, and a set of
composable environments and wrappers (batching, observation extraction,
trajectory recording, asynchronous stepping, and running an environment in a
subprocess).

The public API is importable from the top level and from two submodules:

```python
from vectorenv import (
    Env,
    Wrapper,
    unwrap,
    ConcatEnv,
    ExtractDictObWrapper,
    TrajectoryRecorderWrapper,
    AsynchronousWrapper,
    SubprocEnv,
    SubprocError,
    call_func,
    types,
    types_np,
)
```

## Dependencies

The environment is **offline**: every dependency is already installed and there
is no network. **Do not install anything** — no `pip install`, no downloads. The
project itself is installed for you by a `setup.sh` that runs offline (an
editable install against the pre-installed dependencies).

- `numpy` is the only required runtime dependency and is already installed.
- `cloudpickle` is already installed and is used by `SubprocEnv` as a fallback
  serializer (see *SubprocEnv*). Even though it is available, importing
  `vectorenv` must not *require* it: the top-level import must succeed without
  triggering a hard dependency on `cloudpickle`.

## The value-type system (`vectorenv.types`)

Spaces are described by **value types**. The base class is `ValType`; the two
concrete kinds are tensors and dicts.

Element (scalar) types describe the entries of a tensor:

- `Real(dtype_name="float32")` — continuous values. `dtype_name` is a numpy
  floating dtype name.
- `Discrete(n, dtype_name="int64")` — integers in the range `[0, n)`.
  `dtype_name` is an integer numpy dtype name; `n` is readable as `.n`.

Both expose their `.dtype_name`.

`TensorType(eltype, shape)` is a tensor of `eltype` with `shape` (a tuple of
ints; `()` for a scalar). It exposes:

- `.eltype`, `.shape`
- `.ndim` — number of dimensions
- `.size` — number of elements (the product of `shape`; `1` for a scalar)

`discrete_scalar(n)` is a convenience for a scalar (`shape == ()`) `TensorType`
whose element type is `Discrete(n)`.

`DictType(**name2type)` is a (possibly nested) mapping from string names to value
types. It behaves like a read-only mapping: `len(d)`, `d.keys()`, `d.values()`,
`d.items()`, `d[key]`, and `key in d`.

Value types support **value equality**: two are equal iff they are the same kind
and have the same contents (for a `DictType`, the same names mapping to equal
value types, recursively). Equality must not be identity-based.

### `multimap`

`multimap(f, *xs)` applies `f` at each **leaf** of one or more aligned trees and
returns a new tree of the same structure. A *tree* is a (possibly nested) `dict`,
a (possibly nested) `DictType`, or any other object (a leaf). At an internal
node, the result is a plain `dict`; at a leaf, the result is `f(*leaves)`. All
`xs` must share the same structure (same nesting and same keys at every level);
a structural mismatch is an error.

At each internal node the keys are visited in **sorted** order. This makes every
tree operation deterministic regardless of how a `dict` / `DictType` was
constructed — in particular `sample` consumes its `rng` leaf-by-leaf in
sorted-key order, so two equal spaces built with different key insertion orders
sample identically.

```python
multimap(lambda a, b: a + b, {"x": 1, "y": {"z": 2}}, {"x": 10, "y": {"z": 20}})
# -> {"x": 11, "y": {"z": 22}}
```

## Numpy operations over trees (`vectorenv.types_np`)

These materialize and manipulate trees of numpy arrays that match a value type.
A *batch shape* (`bshape`) is a tuple prepended to each leaf's `shape`.

- `dtype(tt)` — the numpy dtype for a `TensorType` (from its element type).
- `zeros(vt, bshape)` — a tree of zero arrays, each leaf shaped
  `bshape + leaf.shape` with the leaf's dtype.
- `sample(vt, bshape, rng=None)` — a tree of random arrays of the same shapes and
  dtypes. `Discrete` leaves are integers in `[0, n)`; `Real` leaves are standard
  normal values. Sampling uses `rng` (a `numpy.random.RandomState`) when given,
  otherwise the global numpy RNG; passing the same freshly-seeded `rng` therefore
  reproduces the same draw.
- `concat(xs, axis=0)` / `stack(xs, axis=0)` — leaf-wise `numpy.concatenate` /
  `numpy.stack` over a list of same-structure trees.
- `split(x, sections)` — leaf-wise split of a tree. **`sections` are the indices
  to cut at** (cumulative positions), not sizes: splitting a length-4 leaf at
  `[1, 3, 4]` yields the slices `[0:1]`, `[1:3]`, `[3:4]`. It returns exactly
  `len(sections)` pieces — the *i*-th piece is `x[sections[i-1]:sections[i]]` —
  and any elements past the final index are not returned (unlike `numpy.split`,
  there is no trailing remainder piece).

## The environment interface

`Env(ob_space, ac_space, num)` stores `.ob_space`, `.ac_space`, and `.num` (the
number of simultaneous episodes). The agent interacts through `observe()` and
`act()`.

`observe()` returns a tuple **`(reward, ob, first)`** describing the state after
the most recent `act()` (or the initial state if none):

- `reward`: a `float32` array of shape `(num,)` — the reward from the last
  `act()`. The very first reward (before any action) is ignored by convention.
- `ob`: the observation matching `ob_space`, with `(num,)` prepended to each
  leaf's shape (a single array for a tensor space, a tree of arrays for a
  `DictType` space).
- `first`: a `bool` array of shape `(num,)` — `True` for each environment whose
  episode has just (re)started. It is all-`True` for a freshly created env.

`observe()` is idempotent — calling it repeatedly does not advance the
environment. `act(ac)` applies an action matching `ac_space` (again with `(num,)`
prepended to each leaf). The usual rollout is:

```python
reward, ob, first = env.observe()   # initial reward ignored; first is all True
env.act(ac0)
reward, ob, first = env.observe()   # reward caused by ac0
env.act(ac1)
...
```

`get_info()` returns a list of `num` dicts of side-channel diagnostics not seen
by the agent; the base implementation returns `num` empty dicts.

`callmethod(method, *args, **kwargs)` invokes the named method on the underlying
object and returns its result **unchanged** — it does not wrap, re-batch, or
post-process the value. By convention the *called method* returns one entry per
environment (a list of length `num`), but `callmethod` itself neither enforces
nor constructs that: a method returning a scalar makes `callmethod` return that
scalar. (Batching/proxying environments override this — see *ConcatEnv* — and
pass each argument as a list with one entry per environment.)

On the base `Env`, `observe()` and `act()` are abstract and raise
`NotImplementedError`; concrete environments and wrappers implement them.

## Wrappers

`Wrapper(env, ob_space=None, ac_space=None)` wraps a `vectorenv` environment. It
keeps the wrapped env as `.env`, inherits its `num`, and defaults `ob_space` /
`ac_space` to the wrapped env's. By default it forwards `observe`, `act`,
`get_info`, and `callmethod` to `.env`; subclasses override the methods they
change.

`unwrap(env)` returns the innermost environment with all `Wrapper` layers
removed (and returns a non-wrapped env unchanged).

`ExtractDictObWrapper(env, key)` adapts an environment whose observation is a
`DictType`: its `ob_space` becomes `env.ob_space[key]`, and `observe()` returns
`ob[key]` (the selected leaf/subtree) in place of the full dict.

## `ConcatEnv`

`ConcatEnv(envs)` combines several environments — which must all share the same
`ob_space` and the same `ac_space` — into a single environment with
`num == sum(env.num)`:

- `observe()` concatenates the sub-environments' `reward`, `ob`, and `first`
  along the batch axis (in `envs` order).
- `act(ac)` splits the batched action along the batch axis and routes each slice
  to the corresponding sub-environment, in order.
- `get_info()` is the sub-environments' info lists concatenated.
- `callmethod(method, *args, **kwargs)` treats each positional and keyword
  argument as a list of length `num`, splits it into per-sub-env chunks, calls
  `callmethod` on each sub-env with its chunk, and concatenates the returned
  lists back into one list of length `num`.

Combining environments with mismatched spaces, or calling `callmethod` with an
argument list whose length is not `num`, is an error.

## `TrajectoryRecorderWrapper`

`TrajectoryRecorderWrapper(env, directory, filename_prefix="")` records each
completed episode, **per environment**, to its own file in `directory` (created
if missing). For environment `i`, the wrapper accumulates a trajectory until the
post-`act()` `first[i]` is `True` again (its episode has ended), then writes that
trajectory to disk and starts a new one.

A trajectory is a dict with keys `"ob"`, `"act"`, `"reward"`, `"info"`, all
aligned along a common leading step axis of length equal to the episode length,
so that step `i` of each satisfies:

- `act[i]` is the action taken after observing `ob[i]`,
- `reward[i]` is the reward that resulted from `act[i]`,
- `info[i]` corresponds to `ob[i]`.

`reward` is a 1-D numpy array of shape `(episode_len,)` and `info` is a list of
`episode_len` dicts. `ob` and `act` preserve the observation/action structure
with the step axis carried on each **leaf**, not at the top level — they are
**not** a Python list of per-step values. Concretely:

- For a plain tensor space, `ob` (and `act`) is a single numpy array of shape
  `(episode_len,) + leaf.shape`, so `ob[i]` is step `i`'s observation.
- For a `DictType` space, `ob` (and `act`) is a tree of arrays that mirrors the
  space at every level: it has the same nested keys, and each leaf is a numpy
  array of shape `(episode_len,) + leaf.shape` holding that leaf's value stacked
  over the episode's steps.

Each episode is saved as a separate file named `<filename_prefix><index>.pickle`
in Python `pickle` format (loadable with `pickle.load`), where `index` is a
zero-padded, monotonically increasing episode counter.

## `AsynchronousWrapper`

`AsynchronousWrapper(env)` runs `act()` on a single background worker thread so
that `act()` returns immediately without waiting for the underlying step. Both
`observe()` and `get_info()` first block until every queued `act()` has finished.
Queued actions run in the order they were submitted. An exception raised inside a
background `act()` is re-raised from the next `observe()` / `get_info()`.

## `SubprocEnv`

`SubprocEnv(env_fn, env_kwargs=None, daemon=True)` creates the environment in a
new subprocess by calling `env_fn(**env_kwargs)` there, then proxies the whole
environment interface across the process boundary: `ob_space`, `ac_space`, `num`,
and `observe` / `act` / `get_info` / `callmethod` all operate on the remote
environment (`callmethod` returns the remote method's result unchanged). Use a
fresh "spawn" process so the child does not inherit the parent's state.

`env_fn` (and `env_kwargs`) are sent to the child by serialization: try `pickle`
first and fall back to `cloudpickle` when `pickle` cannot serialize it (for
example a closure or locally-defined factory). Provide a `close()` method.

Errors raised in the child are surfaced in the parent as `SubprocError`
(a subclass of `Exception`):

- an error while creating the environment is raised directly from the
  `SubprocEnv(...)` constructor;
- because `act()` returns nothing, an error raised inside the child's `act()`
  surfaces on the **next** `observe()`.

## `call_func`

`call_func(fn_path, **kwargs)` takes `fn_path` of the form
`"module.path:function_name"`, imports the module, looks up the function, calls
it with `**kwargs`, and returns the result.

## setup.sh

The project is installed offline with an editable install. Because the build
backend is pre-installed and the environment has no network, the install must
skip build isolation:

```bash
pip install -e . --no-build-isolation
```
