"""Integration tests for the ``vectorenv`` vectorized-environment library.

Every test exercises one *capability* of the library end to end, driving the
public API through realistic workflows so the implementation is graded on whole
features rather than isolated method calls. All imports go through the top-level
``vectorenv`` package (and its ``types`` / ``types_np`` submodules), so any
reasonable internal organisation is accepted.
"""

import os
import pickle
import time
from glob import glob

import numpy as np
import pytest

from vectorenv import (
    AsynchronousWrapper,
    ConcatEnv,
    Env,
    ExtractDictObWrapper,
    SubprocEnv,
    SubprocError,
    TrajectoryRecorderWrapper,
    Wrapper,
    call_func,
    types,
    types_np,
    unwrap,
)


# ===========================================================================
# Deterministic helper environments (built only on the type system, not on
# multimap / types_np, so each capability test fails independently).
# ===========================================================================


def _build_tree(space, num, value):
    """A tree of numpy arrays matching ``space`` with every leaf filled by
    ``value`` and a leading batch dimension of ``num``."""
    if isinstance(space, types.DictType):
        return {k: _build_tree(space[k], num, value) for k in space.keys()}
    return np.full((num,) + space.shape, value, dtype=np.dtype(space.eltype.dtype_name))


class CountUpEnv(Env):
    """Deterministic environment with no randomness.

    The observation is the within-episode step index (0, 1, ..., episode_len-1),
    broadcast to every leaf of ``space``.  ``first`` is True exactly at the start
    of each episode.  After ``episode_len`` actions the episode restarts.  The
    reward returned after the k-th action (globally) is ``float(k)``.
    """

    def __init__(self, space=None, episode_len=3, num=1):
        if space is None:
            space = types.discrete_scalar(16)
        super().__init__(ob_space=space, ac_space=space, num=num)
        self._ep_len = episode_len
        self._t = 0
        self._global = 0
        self._rew = np.zeros((num,), dtype=np.float32)

    def observe(self):
        ob = _build_tree(self.ob_space, self.num, self._t)
        first = np.full((self.num,), self._t == 0, dtype=bool)
        return self._rew, ob, first

    def act(self, ac):
        self._global += 1
        self._rew = np.full((self.num,), float(self._global), dtype=np.float32)
        self._t = (self._t + 1) % self._ep_len

    def double(self, xs):
        return [x * 2 for x in xs]

    def combine(self, xs, ys):
        return [x + y for x, y in zip(xs, ys)]


# ===========================================================================
# 1. Value-type system (types.py)
# ===========================================================================


def test_valtypes():
    """The value-type system: TensorType/Discrete/Real with their derived
    properties and string forms, value-equality of types, the discrete_scalar
    helper, and the DictType mapping protocol (flat and nested)."""
    # --- TensorType + scalar element types ---
    tt = types.TensorType(eltype=types.Discrete(10), shape=(2, 3))
    assert tt.ndim == 2
    assert tt.size == 6
    assert tt.shape == (2, 3)
    assert isinstance(tt.eltype, types.Discrete)
    assert tt.eltype.n == 10

    real = types.TensorType(eltype=types.Real(), shape=())
    assert real.ndim == 0
    assert real.size == 1

    # Discrete defaults to a 64-bit signed integer dtype; Real to float32
    assert types.Discrete(5).dtype_name == "int64"
    assert types.Real().dtype_name == "float32"
    assert types.Discrete(256, dtype_name="uint8").dtype_name == "uint8"

    # --- discrete_scalar convenience ---
    ds = types.discrete_scalar(4)
    assert isinstance(ds, types.TensorType)
    assert ds.shape == ()
    assert isinstance(ds.eltype, types.Discrete) and ds.eltype.n == 4

    # --- value equality (by kind + contents, not identity) ---
    assert types.discrete_scalar(4) == types.discrete_scalar(4)
    assert types.discrete_scalar(4) != types.discrete_scalar(5)
    assert types.TensorType(eltype=types.Real(), shape=(3,)) == types.TensorType(
        eltype=types.Real(), shape=(3,)
    )
    assert types.TensorType(eltype=types.Real(), shape=(3,)) != types.TensorType(
        eltype=types.Real(), shape=(2,)
    )
    # different eltype kind -> not equal
    assert types.discrete_scalar(2) != types.TensorType(eltype=types.Real(), shape=())

    # --- DictType mapping protocol, flat + nested ---
    d = types.DictType(
        a=types.discrete_scalar(4),
        b=types.TensorType(eltype=types.Real(), shape=(2,)),
    )
    assert len(d) == 2
    assert set(d.keys()) == {"a", "b"}
    assert "a" in d and "z" not in d
    assert d["a"] == types.discrete_scalar(4)
    # values()/items() iterate keys in insertion order and carry the actual
    # value types, not merely a non-empty list.
    assert list(d.values()) == [
        types.discrete_scalar(4),
        types.TensorType(eltype=types.Real(), shape=(2,)),
    ]
    assert list(d.items()) == [
        ("a", types.discrete_scalar(4)),
        ("b", types.TensorType(eltype=types.Real(), shape=(2,))),
    ]

    nested = types.DictType(outer=d, scalar=types.discrete_scalar(2))
    assert nested["outer"]["b"] == types.TensorType(eltype=types.Real(), shape=(2,))
    # DictType equality is structural
    assert nested == types.DictType(
        outer=types.DictType(
            a=types.discrete_scalar(4),
            b=types.TensorType(eltype=types.Real(), shape=(2,)),
        ),
        scalar=types.discrete_scalar(2),
    )
    assert nested != types.DictType(outer=d, scalar=types.discrete_scalar(3))


# ===========================================================================
# 2. multimap: structure-preserving traversal of trees
# ===========================================================================


def test_multimap():
    """multimap applies a function at each leaf of one or more aligned trees
    (plain dicts and DictTypes), returning a tree of the same structure;
    leaves are anything that is not a dict/DictType, keys are visited
    deterministically, and structural mismatches are rejected."""
    # --- single leaf (not a dict) ---
    assert types.multimap(lambda x: x + 1, 41) == 42

    # --- flat + nested dict trees, multiple inputs combined leaf-wise ---
    out = types.multimap(
        lambda x, y: x * 10 + y,
        {"a": 1, "b": {"c": 2, "d": 3}},
        {"a": 4, "b": {"c": 5, "d": 6}},
    )
    assert out == {"a": 14, "b": {"c": 25, "d": 36}}

    # --- a DictType is also a tree; leaves are the TensorTypes ---
    space = types.DictType(
        x=types.discrete_scalar(3),
        y=types.DictType(z=types.TensorType(eltype=types.Real(), shape=(2,))),
    )
    shapes = types.multimap(lambda tt: tt.shape, space)
    assert shapes == {"x": (), "y": {"z": (2,)}}

    # --- keys are visited in SORTED order (so tree ops are deterministic
    # regardless of dict construction order). Build with keys out of order and
    # record the visit order via the leaves' values. ---
    visited = []
    out_of_order = types.DictType(
        c=types.discrete_scalar(3),
        a=types.discrete_scalar(1),
        b=types.discrete_scalar(2),
    )
    types.multimap(lambda tt: visited.append(tt.eltype.n), out_of_order)
    assert visited == [1, 2, 3]  # sorted keys a, b, c -> n = 1, 2, 3

    # --- structure mismatch is rejected ---
    with pytest.raises(Exception):
        types.multimap(lambda x, y: x, {"a": 1}, {"b": 1})
    with pytest.raises(Exception):
        types.multimap(lambda x, y: x, {"a": 1, "b": 2}, {"a": 1})


# ===========================================================================
# 3. types_np: the numpy tree-operation layer (dtype/zeros/sample/concat/
#    stack/split) -- one capability, exercised end to end
# ===========================================================================


def test_types_np():
    """The numpy tree-operation layer as a whole: dtype() maps element types,
    zeros()/sample() materialise (zero/random, right shape+dtype+range,
    rng-deterministic) trees over nested dict spaces, and concat/stack/split are
    leaf-wise over trees (split cuts at *indices*, not sizes), with a
    concat->split round trip."""
    # --- dtype mapping ---
    assert types_np.dtype(types.discrete_scalar(4)) == np.dtype("int64")
    assert types_np.dtype(types.TensorType(eltype=types.Real(), shape=(2,))) == np.dtype(
        "float32"
    )
    assert types_np.dtype(
        types.TensorType(eltype=types.Discrete(256, dtype_name="uint8"), shape=())
    ) == np.dtype("uint8")

    space = types.DictType(
        img=types.TensorType(eltype=types.Discrete(256, dtype_name="uint8"), shape=(4, 4)),
        val=types.TensorType(eltype=types.Real(), shape=()),
    )

    # --- zeros: batch shape prepended to every leaf, right dtypes, all zero ---
    z = types_np.zeros(space, bshape=(5,))
    assert z["img"].shape == (5, 4, 4)
    assert z["img"].dtype == np.dtype("uint8")
    assert z["val"].shape == (5,)
    assert z["val"].dtype == np.dtype("float32")
    assert not z["img"].any() and not z["val"].any()

    # --- sample: shapes/dtypes match, discrete values in range, reproducible ---
    s1 = types_np.sample(space, bshape=(7,), rng=np.random.RandomState(0))
    s2 = types_np.sample(space, bshape=(7,), rng=np.random.RandomState(0))
    assert s1["img"].shape == (7, 4, 4) and s1["img"].dtype == np.dtype("uint8")
    assert s1["val"].shape == (7,) and s1["val"].dtype == np.dtype("float32")
    assert (0 <= s1["img"]).all() and (s1["img"] < 256).all()
    assert np.array_equal(s1["img"], s2["img"])  # same seed -> same draw
    assert np.array_equal(s1["val"], s2["val"])

    # discrete range is respected for a tiny n
    small = types_np.sample(types.discrete_scalar(2), bshape=(200,), rng=np.random.RandomState(1))
    assert set(np.unique(small).tolist()).issubset({0, 1})

    # --- concat / stack / split over arrays and trees ---
    # --- plain arrays ---
    assert np.array_equal(
        types_np.concat([np.array([1, 2]), np.array([3, 4, 5])]), np.array([1, 2, 3, 4, 5])
    )
    stacked = types_np.stack([np.array([1, 2]), np.array([3, 4])])
    assert stacked.shape == (2, 2)
    assert np.array_equal(stacked, np.array([[1, 2], [3, 4]]))

    # split takes indices to cut at, not section sizes
    parts = types_np.split(np.array([1, 2, 3, 4]), [1, 3, 4])
    assert [p.tolist() for p in parts] == [[1], [2, 3], [4]]

    # --- trees: concat distributes over dict leaves ---
    t1 = {"a": np.array([1, 2]), "b": {"c": np.array([10])}}
    t2 = {"a": np.array([3]), "b": {"c": np.array([20, 30])}}
    cat = types_np.concat([t1, t2])
    assert np.array_equal(cat["a"], np.array([1, 2, 3]))
    assert np.array_equal(cat["b"]["c"], np.array([10, 20, 30]))

    # --- concat then split round-trips a batch back into per-item slices ---
    merged = types_np.concat(
        [{"a": np.array([1, 1])}, {"a": np.array([2, 2, 2])}]
    )
    back = types_np.split(merged, [2, 5])
    assert np.array_equal(back[0]["a"], np.array([1, 1]))
    assert np.array_equal(back[1]["a"], np.array([2, 2, 2]))


# ===========================================================================
# 4. The Env interaction protocol + call_func
# ===========================================================================


def test_env_interface():
    """The Env contract: the (reward, ob, first) observe() convention with the
    documented shapes/dtypes, a default get_info() of `num` empty dicts, the
    default callmethod() dispatch to a named method, and the call_func helper
    that imports and invokes a "module:function"."""
    env = CountUpEnv(space=types.discrete_scalar(8), episode_len=3, num=4)
    assert env.num == 4
    assert env.ob_space == types.discrete_scalar(8)
    assert env.ac_space == types.discrete_scalar(8)

    rew, ob, first = env.observe()
    assert rew.shape == (4,) and rew.dtype == np.dtype("float32")
    assert ob.shape == (4,)
    assert first.shape == (4,) and first.dtype == np.dtype("bool")
    assert first.all()  # brand new -> start of episode
    assert (ob == 0).all()

    env.act(np.zeros((4,), dtype=np.int64))
    rew, ob, first = env.observe()
    assert not first.any()
    assert (ob == 1).all()

    # default get_info: one empty dict per environment
    info = env.get_info()
    assert info == [{}, {}, {}, {}]

    # default callmethod dispatches to the named method
    assert env.callmethod("double", [1, 2, 3, 4]) == [2, 4, 6, 8]

    # the base Env leaves observe()/act() unimplemented
    with pytest.raises(NotImplementedError):
        Env(types.discrete_scalar(2), types.discrete_scalar(2), 1).observe()

    # --- call_func: "module:function" lookup + kwargs invocation ---
    made = call_func("vectorenv.types:discrete_scalar", n=5)
    assert made == types.discrete_scalar(5)


# ===========================================================================
# 5. Wrapper delegation + unwrap + ExtractDictObWrapper
# ===========================================================================


class AddInfo(Wrapper):
    """A wrapper that tags each info dict, to prove get_info is overridable."""

    def __init__(self, env, tag):
        super().__init__(env)
        self._tag = tag

    def get_info(self):
        infos = [dict(info) for info in self.env.get_info()]
        for info in infos:
            info["tag"] = self._tag
        return infos


def test_wrapper_and_unwrap():
    """Wrappers transparently forward the Env interface and inherit spaces/num
    from the wrapped env, individual methods can be overridden, unwrap() peels
    every wrapper off, and ExtractDictObWrapper narrows a dict observation to a
    single key (adjusting ob_space accordingly)."""
    base = CountUpEnv(space=types.discrete_scalar(8), episode_len=2, num=3)
    wrapped = AddInfo(base, tag="x")

    # spaces + num inherited from the wrapped env
    assert wrapped.num == 3
    assert wrapped.ob_space == base.ob_space
    assert wrapped.ac_space == base.ac_space

    # observe/act forwarded unchanged
    rew, ob, first = wrapped.observe()
    assert ob.shape == (3,) and first.all()

    # overridden get_info is used
    assert wrapped.get_info() == [{"tag": "x"}] * 3

    # unwrap peels every layer back to the base env
    assert unwrap(AddInfo(wrapped, tag="y")) is base
    assert unwrap(base) is base

    # --- ExtractDictObWrapper: narrow a dict observation to one key ---
    dict_space = types.DictType(
        rgb=types.TensorType(eltype=types.Discrete(256, dtype_name="uint8"), shape=(2,)),
        scalar=types.discrete_scalar(4),
    )
    denv = CountUpEnv(space=dict_space, episode_len=2, num=2)
    extracted = ExtractDictObWrapper(denv, key="scalar")
    assert extracted.ob_space == types.discrete_scalar(4)
    _rew, ob, _first = extracted.observe()
    assert isinstance(ob, np.ndarray)  # no longer a dict
    assert ob.shape == (2,)
    # the live extracted leaf is returned, not a right-shaped placeholder:
    # CountUpEnv fills every leaf with the within-episode step index (0 at start)
    assert (ob == 0).all()
    extracted.act(np.zeros((2,), dtype=np.int64))
    _rew, ob, _first = extracted.observe()
    assert (ob == 1).all()  # advanced to step index 1 after one act()


# ===========================================================================
# 6. ConcatEnv: combine environments into one batched environment
# ===========================================================================


def test_concat_env():
    """ConcatEnv stacks several environments into one: num is the sum, observe()
    concatenates rewards/observations/firsts along the batch axis, act() splits
    the batched action back to each sub-env, get_info() concatenates, and
    callmethod() chunks each per-env argument list before dispatching."""
    space = types.discrete_scalar(8)
    env_a = CountUpEnv(space=space, episode_len=3, num=2)
    env_b = CountUpEnv(space=space, episode_len=3, num=3)
    env = ConcatEnv([AddInfo(env_a, "a"), AddInfo(env_b, "b")])

    assert env.num == 5
    assert env.ob_space == space and env.ac_space == space

    rew, ob, first = env.observe()
    assert rew.shape == (5,) and ob.shape == (5,) and first.shape == (5,)
    assert first.all() and (ob == 0).all()

    # act() routes the right slice of the batched action to each sub-env, so the
    # per-env counters advance and observe() reflects it
    env.act(np.zeros((5,), dtype=np.int64))
    _rew, ob, first = env.observe()
    assert (ob == 1).all() and not first.any()

    # get_info concatenates each sub-env's info list, in order
    assert env.get_info() == [{"tag": "a"}, {"tag": "a"}, {"tag": "b"}, {"tag": "b"}, {"tag": "b"}]

    # callmethod chunks each length-`num` argument into per-env sublists,
    # dispatches, and concatenates the per-env results back to length `num`
    assert env.callmethod("double", [1, 2, 3, 4, 5]) == [2, 4, 6, 8, 10]
    # multiple positional arguments are each chunked the same way
    assert env.callmethod("combine", [1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == [
        11,
        22,
        33,
        44,
        55,
    ]
    with pytest.raises(Exception):  # wrong total length
        env.callmethod("double", [1, 2, 3])

    # mismatched sub-env spaces are rejected
    with pytest.raises(Exception):
        ConcatEnv([CountUpEnv(space=types.discrete_scalar(8)), CountUpEnv(space=types.discrete_scalar(9))])


# ===========================================================================
# 7. TrajectoryRecorderWrapper: persist whole episodes
# ===========================================================================


def test_trajectory_recorder(tmp_path):
    """Recording episodes from a plain tensor space: each completed episode is
    written as its own pickle with reward/ob/act/info entries of length
    episode_len, the right number of files is produced for sub-envs of different
    episode lengths, and the stored observations/actions/rewards line up with
    what was fed in (act[i] follows ob[i]; reward[i] follows act[i])."""
    ep_a, ep_b = 3, 4
    env = ConcatEnv(
        [
            CountUpEnv(space=types.discrete_scalar(64), episode_len=ep_a, num=1),
            CountUpEnv(space=types.discrete_scalar(64), episode_len=ep_b, num=1),
        ]
    )
    env = TrajectoryRecorderWrapper(env, directory=str(tmp_path))
    n_acts = 12
    action = np.array([5, 7], dtype=np.int64)
    for _ in range(n_acts):
        env.act(action)

    files = sorted(glob(os.path.join(str(tmp_path), "*.pickle")))
    assert len(files) == (n_acts // ep_a) + (n_acts // ep_b)

    trajs = []
    for fp in files:
        with open(fp, "rb") as f:
            trajs.append(pickle.load(f))
    lengths = sorted(len(t["ob"]) for t in trajs)
    assert lengths == sorted([ep_a] * (n_acts // ep_a) + [ep_b] * (n_acts // ep_b))

    for t in trajs:
        L = len(t["ob"])
        assert len(t["act"]) == L and len(t["reward"]) == L and len(t["info"]) == L
        # observations within an episode are the step indices 0..L-1
        assert [int(x) for x in t["ob"]] == list(range(L))
        # act[i] is the action taken after seeing ob[i]
        fed = 5 if L == ep_a else 7
        assert [int(x) for x in t["act"]] == [fed] * L
        # reward[i] is the reward that resulted from act[i]: stored post-act, in
        # order (the env's reward is its global step count, so consecutive here)
        rewards = np.asarray(t["reward"])
        assert rewards.shape == (L,)
        assert np.all(np.diff(rewards) == 1)
        # info[i] corresponds to ob[i] (default diagnostics are empty dicts)
        assert all(isinstance(x, dict) for x in t["info"])


# ===========================================================================
# 8. TrajectoryRecorderWrapper: nested dict observation/action spaces
# ===========================================================================


def test_trajectory_recorder_dict(tmp_path):
    """Recording episodes from a NESTED DICT space: ob/act are stored as trees of
    arrays mirroring the space, each leaf is a length-episode_len sequence, the
    per-step values land in the right leaf, and the file count / reward alignment
    match the tensor case. (A strictly harder scenario than the tensor one: the
    recorder must split and accumulate a tree per environment.)"""
    ep_a, ep_b = 3, 4
    n_acts = 12
    dspace = types.DictType(
        a=types.TensorType(eltype=types.Discrete(64), shape=(2,)),
        b=types.DictType(c=types.discrete_scalar(64)),
    )
    env = ConcatEnv(
        [
            CountUpEnv(space=dspace, episode_len=ep_a, num=1),
            CountUpEnv(space=dspace, episode_len=ep_b, num=1),
        ]
    )
    env = TrajectoryRecorderWrapper(env, directory=str(tmp_path))
    action = {"a": np.zeros((2, 2), dtype=np.int64), "b": {"c": np.zeros((2,), dtype=np.int64)}}
    for _ in range(n_acts):
        env.act(action)

    files = sorted(glob(os.path.join(str(tmp_path), "*.pickle")))
    assert len(files) == (n_acts // ep_a) + (n_acts // ep_b)

    trajs = []
    for fp in files:
        with open(fp, "rb") as f:
            trajs.append(pickle.load(f))
    lengths = sorted(len(t["ob"]["b"]["c"]) for t in trajs)
    assert lengths == sorted([ep_a] * (n_acts // ep_a) + [ep_b] * (n_acts // ep_b))

    for t in trajs:
        L = len(t["ob"]["b"]["c"])
        # the observation/action trees mirror the space at every level
        assert set(t["ob"].keys()) == {"a", "b"} and set(t["ob"]["b"].keys()) == {"c"}
        assert t["ob"]["a"].shape == (L, 2)
        assert t["act"]["a"].shape == (L, 2)
        assert len(t["act"]["b"]["c"]) == L
        # per-step within-episode index recorded into every leaf of the tree
        assert [int(x) for x in t["ob"]["b"]["c"]] == list(range(L))
        assert [int(row[0]) for row in t["ob"]["a"]] == list(range(L))
        # reward/info still aligned
        assert np.all(np.diff(np.asarray(t["reward"])) == 1)
        assert all(isinstance(x, dict) for x in t["info"])


# ===========================================================================
# 9. AsynchronousWrapper: run act() off-thread
# ===========================================================================


class SlowAct(Wrapper):
    def __init__(self, env, delay):
        super().__init__(env)
        self._delay = delay
        self.acts = []

    def act(self, ac):
        time.sleep(self._delay)
        self.env.act(ac)
        self.acts.append(int(ac[0]))


class BoomOnAct(Wrapper):
    def act(self, ac):
        raise RuntimeError("boom")


def test_async_wrapper():
    """AsynchronousWrapper runs act() on a background worker: act() returns
    before the work is done, observe()/get_info() block until every pending
    act() has finished, actions still execute in submission order, and an
    exception raised inside act() surfaces on the next observe()."""
    delay = 0.05
    n = 6
    slow = SlowAct(CountUpEnv(episode_len=100), delay=delay)
    env = AsynchronousWrapper(slow)

    start = time.time()
    for i in range(n):
        env.act(np.array([i], dtype=np.int64))
    submit_elapsed = time.time() - start
    assert submit_elapsed < delay * n  # act() did not block on the work

    env.observe()  # blocks until all queued acts complete
    assert time.time() - start >= delay * n
    assert slow.acts == list(range(n))  # executed in order

    # exception inside act surfaces on the next observe
    boom = AsynchronousWrapper(BoomOnAct(CountUpEnv(episode_len=100)))
    boom.observe()
    boom.act(np.array([0], dtype=np.int64))
    with pytest.raises(RuntimeError):
        boom.observe()


# ===========================================================================
# 10. SubprocEnv: run an environment in a child process
# ===========================================================================


def test_subproc_env():
    """SubprocEnv builds an environment in a separate process from a (possibly
    closure-captured) factory and proxies the whole interface across the process
    boundary -- spaces, observe/act, and callmethod -- while errors in the child
    are re-raised in the parent as SubprocError (at creation directly, and for
    act on the following observe, since act returns nothing)."""

    def make_env():
        import numpy as np
        from vectorenv import Env, types

        class _Sub(Env):
            def __init__(self):
                super().__init__(types.discrete_scalar(2), types.discrete_scalar(2), num=1)
                self._rew = np.zeros((1,), dtype=np.float32)

            def observe(self):
                return self._rew, np.zeros((1,), dtype=np.int64), np.ones((1,), dtype=bool)

            def act(self, ac):
                self._rew = np.ones((1,), dtype=np.float32)

            def square(self, x):
                return x * x

        return _Sub()

    env = SubprocEnv(env_fn=make_env)
    try:
        assert env.num == 1
        assert env.ob_space == types.discrete_scalar(2)
        rew, ob, first = env.observe()
        assert rew[0] == 0.0 and ob[0] == 0 and bool(first[0]) is True
        env.act(np.zeros((1,), dtype=np.int64))
        rew, _ob, _first = env.observe()
        assert rew[0] == 1.0
        # callmethod is proxied to the child object
        assert env.callmethod("square", 3) == 9
    finally:
        env.close()

    # an exception while creating the env surfaces immediately as SubprocError
    def boom_create():
        raise ValueError("nope")

    with pytest.raises(SubprocError):
        SubprocEnv(env_fn=boom_create)

    # an exception during act surfaces on the following observe()
    def make_boom_act():
        from vectorenv import Env, types
        import numpy as np

        class _Boom(Env):
            def __init__(self):
                super().__init__(types.discrete_scalar(2), types.discrete_scalar(2), num=1)

            def observe(self):
                return (
                    np.zeros((1,), dtype=np.float32),
                    np.zeros((1,), dtype=np.int64),
                    np.ones((1,), dtype=bool),
                )

            def act(self, ac):
                raise RuntimeError("act failed")

        return _Boom()

    env2 = SubprocEnv(env_fn=make_boom_act)
    try:
        env2.observe()
        env2.act(np.zeros((1,), dtype=np.int64))
        with pytest.raises(SubprocError):
            env2.observe()
    finally:
        env2.close()
