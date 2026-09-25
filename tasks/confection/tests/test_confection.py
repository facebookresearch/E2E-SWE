"""Integration tests for the ``cfgforge`` configuration system.

Every test exercises one *capability* of the library end to end, bundling the
distinct behaviors of that capability into a single workflow so a config tool is
graded on whole features rather than on isolated method calls. All imports go
through the top-level ``cfgforge`` package, so any reasonable internal
organisation is allowed.
"""

import configparser
import copy
from enum import Enum
from pathlib import Path
from typing import Annotated, Dict, List, Literal, Optional, Sequence, Set, Tuple, Union

import catalogue
import pydantic
import pytest

from cfgforge import (
    Config,
    ConfigValidationError,
    Schema,
    SimpleFrozenDict,
    SimpleFrozenList,
    registry,
)


# ===========================================================================
# Config format: parsing, serialization, overrides, merge, copy
# ===========================================================================


def test_config_format(tmp_path):
    """The core config-format capability: parse JSON-typed values and nested
    sections, round-trip through str/bytes/disk, apply dot-notation overrides,
    deep-merge configs, and make independent copies that carry metadata."""
    # --- typed value parsing + nesting + Python-literal aliases ---
    cfg = """
[training]
patience = 10
dropout = 0.2
use_vectors = false
tags = ["a", "b"]
limits = {"min": 0, "max": 5}

[training.logging]
level = "INFO"
enabled = True
disabled = None
quoted = "True"

[nlp]
lang = "en"
"""
    config = Config().from_str(cfg, interpolate=False)
    assert config["training"]["patience"] == 10
    assert config["training"]["dropout"] == 0.2
    assert config["training"]["use_vectors"] is False
    assert config["training"]["tags"] == ["a", "b"]
    assert config["training"]["limits"] == {"min": 0, "max": 5}
    # Nested section becomes a nested dict
    assert config["training"]["logging"]["level"] == "INFO"
    # Python-style literals are coerced exactly like their JSON counterparts
    assert config["training"]["logging"]["enabled"] is True
    assert config["training"]["logging"]["disabled"] is None
    # A JSON-quoted "True" must stay a string, not become a bool
    assert config["training"]["logging"]["quoted"] == "True"
    assert isinstance(config["training"]["logging"]["quoted"], str)
    assert config["nlp"]["lang"] == "en"

    # --- str / bytes / disk roundtrip + empty config ---
    data = {
        "training": {"lr": 0.001, "epochs": 10, "schedule": [1, 2, 3]},
        "model": {"name": "cnn", "params": {"width": 64}},
    }
    rt = Config(data)
    restored = Config().from_str(rt.to_str(interpolate=False), interpolate=False)
    assert dict(restored["training"]) == data["training"]
    assert dict(restored["model"]) == data["model"]

    blob = rt.to_bytes(interpolate=False)
    assert isinstance(blob, bytes)
    from_bytes = Config().from_bytes(blob, interpolate=False)
    assert from_bytes["model"]["params"] == {"width": 64}

    path = tmp_path / "config.cfg"
    rt.to_disk(path, interpolate=False)
    assert path.exists()
    from_disk = Config().from_disk(str(path), interpolate=False)
    assert from_disk["training"]["schedule"] == [1, 2, 3]

    assert Config().to_str(interpolate=False) == ""
    assert dict(Config().from_str("", interpolate=False)) == {}

    # --- dot-notation overrides (value re-interpolation + block swap) ---
    result = Config().from_str(
        "[a]\nx = 1\n\n[b]\ny = ${a.x}",
        interpolate=True,
        overrides={"a.x": 42},
    )
    assert result["a"]["x"] == 42
    assert result["b"]["y"] == 42

    result = Config().from_str(
        '[a]\n\n[a.scorer]\n@scorers = "old.v1"\n',
        interpolate=False,
        overrides={"a.scorer": {"@scorers": "new.v1"}},
    )
    assert result["a"]["scorer"]["@scorers"] == "new.v1"

    # --- merge (deep merge, remove_extra, different-@function blocks) ---
    base = Config({"a": {"x": 1, "y": 2, "sub": {"p": 1, "q": 2}}})
    merged = base.merge({"a": {"x": 99, "sub": {"p": 50}, "z": 3}})
    assert merged["a"]["x"] == 99       # overwritten
    assert merged["a"]["y"] == 2        # kept from base
    assert merged["a"]["z"] == 3        # added from updates
    assert merged["a"]["sub"]["p"] == 50
    assert merged["a"]["sub"]["q"] == 2
    assert base["a"]["x"] == 1          # base not mutated

    trimmed = Config({"a": {"x": 1}}).merge(
        {"a": {"x": 9, "extra": "gone"}}, remove_extra=True
    )
    assert trimmed["a"]["x"] == 9
    assert "extra" not in trimmed["a"]

    diff = Config({"a": {"@cats": "meow.v1", "x": 1}}).merge(
        {"a": {"@cats": "woof.v1", "y": 2}}
    )
    assert diff["a"]["@cats"] == "woof.v1"
    assert diff["a"]["y"] == 2
    assert "x" not in diff["a"]

    # --- copy: deep independence + carried-over metadata ---
    src = Config({"a": {"x": [1, 2, 3]}}, is_interpolated=False, section_order=["a"])
    copied = src.copy()
    copied["a"]["x"].append(4)
    assert src["a"]["x"] == [1, 2, 3]
    assert copied["a"]["x"] == [1, 2, 3, 4]
    assert copied.is_interpolated is False
    assert copied.section_order == ["a"]


def test_config_interpolation():
    """Variable interpolation in all its forms: ${section.key}/${key} with type
    preservation, whole-section refs, in-string coercion/unwrapping, $$ escaping,
    transitive + colon refs, refs inside container literals, verbatim round-trip
    of unresolved refs, and deferred .interpolate()."""
    # --- value interpolation: type preserved, same-section refs ---
    config = Config().from_str(
        """
[hyper]
lr = 0.001
use_vectors = true

[training]
learn_rate = ${hyper.lr}
use_vectors = ${hyper.use_vectors}
patience = 10
twice = ${training.patience}
""",
        interpolate=True,
    )
    assert config["training"]["learn_rate"] == 0.001
    assert config["training"]["use_vectors"] is True
    assert config["training"]["twice"] == 10

    # --- whole-section refs, in-string coercion/unwrap, $$ escape ---
    config = Config().from_str(
        """
[logger]
name = "L"
level = "INFO"

[a]
x = 42
y = "hello"

[training]
logger = ${logger}
coerced = "value is ${a.x}"
joined = "${a.y} world"
escaped = "$$100"
""",
        interpolate=True,
    )
    assert config["training"]["logger"] == {"name": "L", "level": "INFO"}
    assert config["training"]["coerced"] == "value is 42"
    assert config["training"]["joined"] == "hello world"
    assert config["training"]["escaped"] == "$100"

    # --- transitive (chained) refs + ${section:key} colon alias ---
    config = Config().from_str(
        """
[a]
base = 0.01

[b]
mid = ${a.base}

[c]
final = ${b.mid}
via_colon = ${a:base}
""",
        interpolate=True,
    )
    assert config["b"]["mid"] == 0.01
    assert config["c"]["final"] == 0.01     # resolved through two hops
    assert config["c"]["via_colon"] == 0.01

    # --- refs inside list/dict literals, multiple refs, container values ---
    config = Config().from_str(
        """
[src]
n = 2
first = "p"
second = "q"
items = [1, 2, 3]
mapping = {"k": 1}

[dst]
in_list = [1, ${src.n}, 3]
joined = "${src.first}-${src.second}"
whole_list = ${src.items}
whole_map = ${src.mapping}
""",
        interpolate=True,
    )
    assert config["dst"]["in_list"] == [1, 2, 3]
    assert config["dst"]["joined"] == "p-q"
    assert config["dst"]["whole_list"] == [1, 2, 3]
    assert config["dst"]["whole_map"] == {"k": 1}

    # --- interpolate=False preserves refs verbatim through a round trip ---
    kept = Config().from_str(
        '[paths]\nroot = "/data"\n\n[train]\ndata = ${paths.root}\nepochs = 10',
        interpolate=False,
    )
    restored = Config().from_str(kept.to_str(interpolate=False), interpolate=False)
    assert restored == kept
    assert restored["train"]["data"] == "${paths.root}"
    assert restored["train"]["epochs"] == 10
    assert restored.interpolate()["train"]["data"] == "/data"

    # --- deferred interpolation: resolve later into a new, independent config ---
    deferred = Config().from_str("[a]\nx = 1\n\n[b]\ny = ${a.x}", interpolate=False)
    assert deferred["b"]["y"] == "${a.x}"
    assert deferred.is_interpolated is False
    interpolated = deferred.interpolate()
    assert interpolated is not deferred
    assert interpolated["b"]["y"] == 1
    assert deferred["b"]["y"] == "${a.x}"   # original untouched


def test_config_positional_star_sections():
    """Positional/list ``*`` sections: they collect named subsections under the
    "*" key, nest arbitrarily, participate in interpolation, and survive
    serialization round-trips — including a realistic config that also mixes
    nested sections, registry-promise blocks, and JSON list/dict leaves."""
    config = Config().from_str(
        """
[settings]
lr = 0.001

[models]

[models.*.first]
learning_rate = ${settings.lr}

[models.*.second]
learning_rate = 0.01

[models.*.second.sub]
depth = 2
""",
        interpolate=True,
    )
    assert config["models"]["*"]["first"]["learning_rate"] == 0.001
    assert config["models"]["*"]["second"]["learning_rate"] == 0.01
    assert config["models"]["*"]["second"]["sub"] == {"depth": 2}

    restored = Config().from_str(config.to_str(interpolate=True), interpolate=True)
    assert restored["models"]["*"]["first"]["learning_rate"] == 0.001

    # Complex round trip: nested sections + promise blocks + "*" + JSON leaves
    text = """
[paths]
root = "/data"

[training]
seed = 1
dropout = 0.2
layers = [64, 32]
meta = {"a": 1, "b": [2, 3]}

[training.optimizer]
@optimizers = "Adam.v1"
learn_rate = 0.01

[pipeline]

[pipeline.*.tok]
@models = "layer.v1"
width = 8

[pipeline.*.tagger]
@models = "layer.v1"
width = 16
"""
    cfg = Config().from_str(text, interpolate=False)
    restored = Config().from_str(cfg.to_str(interpolate=False), interpolate=False)
    assert restored == cfg
    assert restored["training"]["optimizer"]["@optimizers"] == "Adam.v1"
    assert restored["training"]["layers"] == [64, 32]
    assert restored["training"]["meta"] == {"a": 1, "b": [2, 3]}
    assert restored["pipeline"]["*"]["tok"]["width"] == 8
    assert restored["pipeline"]["*"]["tagger"]["width"] == 16


def test_config_errors():
    """Invalid configs are rejected with ConfigValidationError: malformed syntax,
    structural section errors, bad interpolation, and bad overrides."""
    # Malformed syntax / a value before any section header
    with pytest.raises(ConfigValidationError):
        Config().from_str("[[invalid", interpolate=False)
    with pytest.raises(ConfigValidationError):
        Config().from_str("key = value", interpolate=False)

    # Structural: missing parent section, and a key colliding with a subsection
    with pytest.raises(ConfigValidationError):
        Config().from_str("[a]\nx = 1\n\n[a.b.c]\ny = 2", interpolate=False)
    with pytest.raises(ConfigValidationError):
        Config().from_str("[a]\nb = 1\n\n[a.b]\nc = 2", interpolate=False)

    # Interpolation: unknown variable, and a whole-section ref inside a string.
    # The contract only promises an undefined variable "also raises" (no type):
    # a configparser-backed impl surfaces InterpolationError, a from-scratch impl
    # may raise ConfigValidationError. Accept either, but not bare Exception (which
    # would mask unrelated bugs like KeyError/AttributeError/NameError).
    with pytest.raises((ConfigValidationError, configparser.InterpolationError)):
        Config().from_str("[a]\nx = ${b.y}", interpolate=True)
    with pytest.raises(ConfigValidationError):
        Config().from_str(
            '[defaults]\nlr = 0.001\n\n[a]\nx = "hello ${defaults}"',
            interpolate=True,
        )

    # Overrides: must be a dotted section.key path that points at a real section
    with pytest.raises(ConfigValidationError):
        Config().from_str("[a]\nx = 1", interpolate=False, overrides={"x": 2})
    with pytest.raises(ConfigValidationError):
        Config().from_str("[a]\nx = 1", interpolate=False, overrides={"b.x": 2})


# ===========================================================================
# Function registry: resolving configs into objects
# ===========================================================================


class _resolve_registry(registry):
    optimizers = catalogue.create("conf_test_resolve", "optimizers", entry_points=False)
    schedules = catalogue.create("conf_test_resolve", "schedules", entry_points=False)
    models = catalogue.create("conf_test_resolve", "models", entry_points=False)


@_resolve_registry.optimizers.register("Adam.v1")
def _adam(learn_rate: float = 0.001, beta1: float = 0.9, beta2: float = 0.999):
    return {"learn_rate": learn_rate, "beta1": beta1, "beta2": beta2}


@_resolve_registry.schedules.register("decay.v1")
def _decay(base_rate: float, repeat: int):
    return [base_rate] * repeat


@_resolve_registry.models.register("chain.v1")
def _chain(*layers):
    return list(layers)


@_resolve_registry.models.register("layer.v1")
def _layer(width: int):
    return {"width": width}


# A BaseModel-returning + BaseModel-consuming pair, for pydantic arg coercion.
class _Dim(pydantic.BaseModel):
    length: int


@_resolve_registry.models.register("Dim.v1")
def _make_dim(length: int) -> _Dim:
    return _Dim(length=length)


@_resolve_registry.optimizers.register("arch.v1")
def _arch(foo: str, dim: _Dim) -> str:
    # dim must arrive as a constructed _Dim instance, not a raw dict
    return f"{foo}:{dim.length}"


def test_registry_resolve():
    """The end-to-end resolution capability: turn @-promise blocks into the
    objects their functions return, with defaults filled, nested promises
    resolved depth-first, "*" positional args (both promise blocks and scalars),
    resolve-time overrides, pydantic-BaseModel argument coercion, and the lookup
    helpers (has/get/is_promise/get_constructor)."""
    # --- canonical resolve + signature defaults ---
    resolved = _resolve_registry.resolve(
        Config().from_str(
            '[optimizer]\n@optimizers = "Adam.v1"\nlearn_rate = 0.01',
            interpolate=False,
        )
    )
    assert resolved["optimizer"] == {"learn_rate": 0.01, "beta1": 0.9, "beta2": 0.999}

    # --- nested promise argument (depth-first) + "*" promise-block positionals ---
    nested = _resolve_registry.resolve(
        Config(
            {
                "optimizer": {
                    "@optimizers": "Adam.v1",
                    "learn_rate": {
                        "@schedules": "decay.v1",
                        "base_rate": 0.1,
                        "repeat": 3,
                    },
                }
            }
        )
    )
    assert nested["optimizer"]["learn_rate"] == [0.1, 0.1, 0.1]
    assert nested["optimizer"]["beta1"] == 0.9

    positional = _resolve_registry.resolve(
        Config(
            {
                "model": {
                    "@models": "chain.v1",
                    "*": {
                        "a": {"@models": "layer.v1", "width": 8},
                        "b": {"@models": "layer.v1", "width": 16},
                    },
                }
            }
        )
    )
    assert positional["model"] == [{"width": 8}, {"width": 16}]

    # --- "*" block of scalars passed as positional *args in declaration order ---
    scalars = _resolve_registry.resolve(
        Config({"layers": {"@models": "chain.v1", "*": {"a": 1, "b": 2, "c": 3}}})
    )
    assert scalars["layers"] == [1, 2, 3]

    # --- overrides applied before resolution ---
    overridden = _resolve_registry.resolve(
        Config({"optimizer": {"@optimizers": "Adam.v1", "learn_rate": 0.01}}),
        overrides={"optimizer.learn_rate": 0.5},
    )
    assert overridden["optimizer"]["learn_rate"] == 0.5
    assert overridden["optimizer"]["beta1"] == 0.9

    # --- pydantic BaseModel argument arrives as a constructed instance ---
    # (both when supplied as plain config keys and via a nested promise)
    direct = _resolve_registry.resolve(
        Config().from_str(
            '[model]\n@optimizers = "arch.v1"\nfoo = "test"\n\n[model.dim]\nlength = 6'
        )
    )
    assert direct["model"] == "test:6"
    via_promise = _resolve_registry.resolve(
        Config().from_str(
            '[model]\n@optimizers = "arch.v1"\nfoo = "test"\n\n'
            '[model.dim]\n@models = "Dim.v1"\nlength = 6'
        )
    )
    assert via_promise["model"] == "test:6"

    # --- lookup API: has / get / is_promise / get_constructor + errors ---
    assert _resolve_registry.has("optimizers", "Adam.v1") is True
    assert _resolve_registry.has("optimizers", "missing") is False
    assert _resolve_registry.has("nonexistent", "x") is False
    assert _resolve_registry.get("optimizers", "Adam.v1") is _adam
    with pytest.raises(ValueError):
        _resolve_registry.get("nonexistent", "x")
    assert registry.is_promise({"@optimizers": "Adam.v1", "lr": 1}) is True
    assert registry.is_promise({"lr": 1}) is False
    assert _resolve_registry.get_constructor({"@optimizers": "Adam.v1"}) == (
        "optimizers",
        "Adam.v1",
    )
    with pytest.raises(ConfigValidationError):
        _resolve_registry.get_constructor({"@a": "x.v1", "@b": "y.v1"})


def test_registry_fill():
    """registry.fill fills each promise's missing arguments from the function
    signature (preserving provided values + the @-key, recursing into nested
    promises, passing unknown functions through unchanged) and, on a config
    loaded with interpolate=False, fills defaults while keeping ${...} refs."""
    filled = _resolve_registry.fill(
        Config().from_str(
            """
[optimizer]
@optimizers = "Adam.v1"
learn_rate = 0.05

[extras]

[extras.unknown]
@models = "unknown.v9"
""",
            interpolate=False,
        )
    )
    assert isinstance(filled, Config)
    assert filled["optimizer"]["@optimizers"] == "Adam.v1"
    assert filled["optimizer"]["learn_rate"] == 0.05   # preserved
    assert filled["optimizer"]["beta1"] == 0.9         # filled
    assert filled["optimizer"]["beta2"] == 0.999       # filled
    assert filled["extras"]["unknown"] == {"@models": "unknown.v9"}  # untouched

    # Fill on an uninterpolated config: defaults fill, ${...} refs preserved
    config = Config().from_str(
        """
[hyper]
rate = 0.01

[optimizer]
@optimizers = "Adam.v1"
learn_rate = ${hyper.rate}
""",
        interpolate=False,
    )
    filled2 = _resolve_registry.fill(config)
    assert filled2["optimizer"]["learn_rate"] == "${hyper.rate}"   # variable kept
    assert filled2["optimizer"]["beta1"] == 0.9                    # default filled
    assert filled2["optimizer"]["beta2"] == 0.999


# ===========================================================================
# Function registry: argument validation against type hints
# ===========================================================================


class _typed_registry(registry):
    fns = catalogue.create("conf_test_typed", "fns", entry_points=False)


@_typed_registry.fns.register("typed.v1")
def _typed(flag: bool, count: int, ratio: float, mode, items):
    return (flag, count, ratio, mode, items)


@_typed_registry.fns.register("containers.v1")
def _containers(
    mapping: Dict[str, int],
    matrix: List[List[int]],
    names: List[str],
    scalar_or_list: Union[int, List[int]],
):
    return (mapping, matrix, names, scalar_or_list)


def test_registry_argument_validation():
    """Promise arguments are validated against the function signature before
    resolution: missing-required / unexpected / top-level-promise errors, the
    documented numeric strictness and coercion rules, Literal/Optional, and
    structural element-by-element checking of containers and Union members.
    Validation never coerces — valid values reach the function unchanged."""
    # --- structural argument errors ---
    with pytest.raises(ConfigValidationError):   # wrong type
        _resolve_registry.resolve(
            Config({"s": {"@schedules": "decay.v1", "base_rate": "x", "repeat": 3}})
        )
    with pytest.raises(ConfigValidationError):   # missing required
        _resolve_registry.resolve(
            Config({"s": {"@schedules": "decay.v1", "base_rate": 0.1}})
        )
    with pytest.raises(ConfigValidationError):   # unexpected argument
        _resolve_registry.resolve(
            Config({"o": {"@optimizers": "Adam.v1", "nope": 1}})
        )
    with pytest.raises(ConfigValidationError):   # top level is a single promise
        _resolve_registry.resolve(Config({"@optimizers": "Adam.v1"}))

    # --- numeric strictness + coercion, values passed through unchanged ---
    @_typed_registry.fns.register("constrained.v2")
    def _constrained_v2(
        choice: Literal["a", "b"], nums: List[int], maybe: Optional[int]
    ):
        return (choice, nums, maybe)

    ok = _typed_registry.resolve(
        Config(
            {
                "x": {
                    "@fns": "typed.v1",
                    "flag": True,
                    "count": 3,
                    "ratio": 5,       # int accepted where float is expected
                    "mode": "free",   # unannotated -> anything
                    "items": [1, 2],
                }
            }
        )
    )
    assert ok["x"] == (True, 3, 5, "free", [1, 2])   # no coercion

    with pytest.raises(ConfigValidationError):   # bool is strict: 1 is not a bool
        _typed_registry.resolve(
            Config({"x": {"@fns": "typed.v1", "flag": 1, "count": 3,
                          "ratio": 1.0, "mode": "m", "items": []}})
        )
    with pytest.raises(ConfigValidationError):   # int rejects bool
        _typed_registry.resolve(
            Config({"x": {"@fns": "typed.v1", "flag": True, "count": True,
                          "ratio": 1.0, "mode": "m", "items": []}})
        )

    # --- Literal membership, List element types, Optional ---
    good = _typed_registry.resolve(
        Config({"x": {"@fns": "constrained.v2", "choice": "a",
                      "nums": [1, 2, 3], "maybe": None}})
    )
    assert good["x"] == ("a", [1, 2, 3], None)
    with pytest.raises(ConfigValidationError):   # Literal violated
        _typed_registry.resolve(
            Config({"x": {"@fns": "constrained.v2", "choice": "z",
                          "nums": [1, 2], "maybe": 1}})
        )
    with pytest.raises(ConfigValidationError):   # List element wrong type
        _typed_registry.resolve(
            Config({"x": {"@fns": "constrained.v2", "choice": "a",
                          "nums": [1, "two"], "maybe": 1}})
        )

    # --- container + Union validation, element by element ---
    base = {
        "@fns": "containers.v1",
        "mapping": {"a": 1, "b": 2},
        "matrix": [[1, 2], [3]],
        "names": ["p", "q"],
        "scalar_or_list": 5,
    }
    okc = _typed_registry.resolve(Config({"x": dict(base)}))
    assert okc["x"] == ({"a": 1, "b": 2}, [[1, 2], [3]], ["p", "q"], 5)
    okc2 = _typed_registry.resolve(Config({"x": {**base, "scalar_or_list": [1, 2, 3]}}))
    assert okc2["x"][3] == [1, 2, 3]
    for bad in (
        {**base, "mapping": {"a": "notint"}},   # dict value wrong type
        {**base, "matrix": [[1, "x"]]},          # nested list element wrong type
        {**base, "names": ["p", 3]},             # list element wrong type
        {**base, "scalar_or_list": "str"},       # matches neither Union member
        {**base, "scalar_or_list": [1, "x"]},    # list-branch element wrong type
    ):
        with pytest.raises(ConfigValidationError):
            _typed_registry.resolve(Config({"x": bad}))


# ===========================================================================
# Function registry: extended type-annotation validation
# ===========================================================================


class _ext_registry(registry):
    fns = catalogue.create("conf_test_ext", "fns", entry_points=False)


@_ext_registry.fns.register("paths.v1")
def _paths(out: Path, items: Sequence[int], label: Annotated[str, "doc"], count: int):
    return {"out": out, "items": items, "label": label, "count": count}


@_ext_registry.fns.register("coll.v1")
def _coll(pair: Tuple[int, str], rest: Tuple[int, ...], uniq: Set[int]):
    return {"pair": pair, "rest": rest, "uniq": sorted(uniq)}


class _Color(str, Enum):
    RED = "red"
    GREEN = "green"


@_ext_registry.fns.register("enum.v1")
def _pick(color: _Color, retries: int = 2):
    return {"color": color, "retries": retries}


def test_registry_extended_types():
    """Richer annotations validated against JSON/config values: Path (accepts a
    string), Sequence[int], Annotated[T, ...] (as T), Tuple (fixed per-position
    and uniform), Set[T], and enum.Enum membership — all checked element-wise and
    never coerced (the function receives the original values)."""
    # --- Path / Sequence / Annotated, passed through uncoerced ---
    resolved = _ext_registry.resolve(
        Config().from_str(
            '[x]\n@fns = "paths.v1"\nout = "/tmp/model"\nitems = [1, 2, 3]\n'
            'label = "run"\ncount = 4',
            interpolate=False,
        )
    )
    assert resolved["x"] == {
        "out": "/tmp/model",   # Path arg supplied as a str, kept as a str
        "items": [1, 2, 3],
        "label": "run",
        "count": 4,
    }
    for bad in (
        {"out": 42, "items": [1, 2], "label": "r", "count": 1},      # Path <- int
        {"out": "/p", "items": [1, "x"], "label": "r", "count": 1},  # Sequence[int] elem
        {"out": "/p", "items": [1, 2], "label": 5, "count": 1},      # Annotated[str] <- int
        {"out": "/p", "items": [1, 2], "label": "r", "count": "x"},  # int <- non-numeric str
    ):
        with pytest.raises(ConfigValidationError):
            _ext_registry.resolve(Config({"x": {"@fns": "paths.v1", **bad}}))

    # --- Tuple (fixed + uniform) and Set, via a programmatic Config ---
    coll = _ext_registry.resolve(
        Config({"c": {"@fns": "coll.v1", "pair": (1, "a"), "rest": (1, 2, 3),
                      "uniq": {1, 2}}})
    )
    assert coll["c"] == {"pair": (1, "a"), "rest": (1, 2, 3), "uniq": [1, 2]}
    cbase = {"@fns": "coll.v1", "pair": (1, "a"), "rest": (1, 2, 3), "uniq": {1, 2}}
    for bad in (
        {**cbase, "pair": (1, 2)},     # second element is not a str
        {**cbase, "pair": (1,)},       # wrong length for a fixed tuple
        {**cbase, "rest": (1, "a")},   # uniform-tuple element wrong type
        {**cbase, "uniq": {1, "x"}},   # set element wrong type
    ):
        with pytest.raises(ConfigValidationError):
            _ext_registry.resolve(Config({"c": bad}))

    # --- enum.Enum membership (str-enum value accepted; non-member rejected) ---
    picked = _ext_registry.resolve(
        Config().from_str('[e]\n@fns = "enum.v1"\ncolor = "red"', interpolate=False)
    )
    assert picked["e"]["color"] == "red"
    assert picked["e"]["retries"] == 2   # signature default filled
    with pytest.raises(ConfigValidationError):
        _ext_registry.resolve(
            Config().from_str('[e]\n@fns = "enum.v1"\ncolor = "blue"', interpolate=False)
        )


# ===========================================================================
# Schema validation (the pydantic-free Schema base class; pydantic also accepted)
# ===========================================================================


class _Training(Schema):
    patience: int
    dropout: float = 0.2
    use_vectors: bool = False


class _Nlp(Schema):
    lang: str


class _Full(Schema):
    training: _Training
    nlp: _Nlp


class _SubList(Schema):
    n: int = 1
    tags: List[str] = []


class _TopList(Schema):
    sub: _SubList


def test_schema_validation():
    """The schema capability: Config.validate (nested schemas, missing-required,
    wrong-type, extra=forbid), fill_defaults (recurse, Optional->None, required
    not invented, extra stripped), from_str(schema=) fill+validate, overrides +
    a List[str] field, and a pydantic BaseModel used anywhere a Schema is."""
    # --- validate: nested ok, missing required, wrong type, extra=forbid ---
    Config({"training": {"patience": 10, "dropout": 0.2}, "nlp": {"lang": "en"}}).validate(_Full)
    with pytest.raises(ConfigValidationError):
        Config({"training": {"dropout": 0.5}, "nlp": {"lang": "en"}}).validate(_Full)
    with pytest.raises(ConfigValidationError):
        Config({"training": {"patience": "nope"}, "nlp": {"lang": "en"}}).validate(_Full)

    class _Strict(Schema):
        model_config = {"extra": "forbid"}
        x: int
        y: str = "d"

    with pytest.raises(ConfigValidationError):
        Config({"x": 1, "z": "extra"}).validate(_Strict)

    # --- fill_defaults: recurse, returns self, required not invented ---
    config = Config({"training": {"patience": 10}})
    result = config.fill_defaults(_Full)
    assert result is config
    assert config["training"]["dropout"] == 0.2
    assert config["training"]["use_vectors"] is False
    assert "nlp" not in config   # required nested section absent -> not invented

    class _Opt(Schema):
        name: str
        description: Optional[str] = None

    opt = Config({"name": "t"})
    opt.fill_defaults(_Opt)
    assert opt["description"] is None   # Optional -> None

    class _StrictTrain(Schema):
        model_config = {"extra": "forbid"}
        patience: int = 10
        dropout: float = 0.2

    class _StrictTop(Schema):
        model_config = {"extra": "forbid"}
        training: _StrictTrain

    stripped = Config({"training": {"patience": 5, "extra_field": "x"}})
    stripped.fill_defaults(_StrictTop)
    assert stripped["training"]["dropout"] == 0.2
    assert "extra_field" not in stripped["training"]   # extra stripped

    # --- from_str(schema=) fills + validates in one step ---
    parsed = Config().from_str(
        '[training]\npatience = 10\n\n[nlp]\nlang = "en"',
        interpolate=False,
        schema=_Full,
    )
    assert parsed["training"]["patience"] == 10
    assert parsed["training"]["dropout"] == 0.2
    assert parsed["training"]["use_vectors"] is False
    with pytest.raises(ConfigValidationError):
        Config().from_str(
            '[training]\ndropout = 0.5\n\n[nlp]\nlang = "en"',
            interpolate=False,
            schema=_Full,
        )

    # --- from_str: overrides + schema + a List[str] field ---
    cfg = Config().from_str(
        '[sub]\nn = 5\ntags = ["a", "b"]',
        interpolate=False,
        overrides={"sub.n": 9},
        schema=_TopList,
    )
    assert cfg["sub"]["n"] == 9
    assert cfg["sub"]["tags"] == ["a", "b"]
    cfg2 = Config().from_str("[sub]\nn = 5", interpolate=False, schema=_TopList)
    assert cfg2["sub"]["tags"] == []   # default filled
    with pytest.raises(ConfigValidationError):
        Config().from_str(
            '[sub]\nn = 5\ntags = ["a", 3]', interpolate=False, schema=_TopList
        )

    # --- a pydantic BaseModel works anywhere a Schema is accepted ---
    class PInner(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(extra="forbid")
        name: str
        value: int = 10

    class POuter(pydantic.BaseModel):
        section: PInner

    pyd = Config().from_str(
        '[section]\nname = "test"', interpolate=False, schema=POuter
    )
    assert pyd["section"]["name"] == "test"
    assert pyd["section"]["value"] == 10   # default filled from pydantic model
    with pytest.raises(ConfigValidationError):
        Config().from_str(
            '[section]\nname = "x"\nvalue = "not-an-int"',
            interpolate=False,
            schema=POuter,
        )
    with pytest.raises(ConfigValidationError):
        Config({"section": {"name": "x", "extra": 1}}).validate(POuter)


class _BaseCfg(Schema):
    name: str
    retries: int = 3


class _DerivedCfg(_BaseCfg):
    timeout: float = 1.5


def test_schema_inheritance():
    """A Schema subclass inherits its parent schemas' fields: inherited defaults
    fill alongside the subclass's own, inherited required fields are enforced, and
    inherited field types are validated."""
    cfg = Config({"name": "svc"})
    cfg.fill_defaults(_DerivedCfg)
    assert cfg["retries"] == 3       # inherited from _BaseCfg
    assert cfg["timeout"] == 1.5     # declared on _DerivedCfg

    Config({"name": "svc", "retries": 5, "timeout": 2.0}).validate(_DerivedCfg)

    with pytest.raises(ConfigValidationError):   # inherited required missing
        Config({"retries": 5}).validate(_DerivedCfg)
    with pytest.raises(ConfigValidationError):   # inherited field wrong type
        Config({"name": "svc", "retries": "no"}).validate(_DerivedCfg)


# ===========================================================================
# Error object contract and frozen collections
# ===========================================================================


def test_error_object_and_frozen_collections():
    """ConfigValidationError exposes its structured contract (errors / error_types
    / text / from_error), and SimpleFrozenDict/SimpleFrozenList read like their
    built-ins but raise on any mutation and deep-copy back to their frozen type."""
    # --- a real validation failure exposes structured errors + text ---
    with pytest.raises(ConfigValidationError) as exc_info:
        Config({"training": {"dropout": 0.5}, "nlp": {"lang": "en"}}).validate(_Full)
    e = exc_info.value
    assert isinstance(e.errors, list) and e.errors
    assert all("loc" in err and "msg" in err for err in e.errors)
    assert any(
        "patience" in [str(p) for p in err.get("loc", [])]
        or "patience" in str(err.get("msg", ""))
        for err in e.errors
    )
    assert isinstance(e.text, str) and e.text

    # --- error_types aggregation + from_error inheritance/override ---
    original = ConfigValidationError(
        errors=[{"loc": ["a", "b"], "msg": "bad", "type": "value_error"}],
        title="Original",
        desc="original desc",
        parent="root",
    )
    assert original.error_types == {"value_error"}
    assert "root" in original.text and "a" in original.text and "b" in original.text
    new = ConfigValidationError.from_error(original, title="New title")
    assert new.title == "New title"
    assert new.desc == "original desc"   # inherited
    assert new.errors == original.errors

    # --- frozen dict: reads, mutation raises (custom message), deepcopy type ---
    d = SimpleFrozenDict({"a": 1, "b": [1, 2]})
    assert d["a"] == 1
    with pytest.raises(NotImplementedError):
        d["c"] = 3
    with pytest.raises(NotImplementedError):
        d.update({"c": 3})
    with pytest.raises(NotImplementedError):
        d.pop("a")
    with pytest.raises(NotImplementedError, match="custom message"):
        SimpleFrozenDict(error="custom message")["x"] = 1
    d_copy = copy.deepcopy(d)
    assert isinstance(d_copy, SimpleFrozenDict)
    assert d_copy["b"] == [1, 2] and d_copy["b"] is not d["b"]

    # --- frozen list: reads, every mutator raises, deepcopy type ---
    lst = SimpleFrozenList([1, 2, 3])
    assert lst[0] == 1
    for mutate in (
        lambda: lst.append(4),
        lambda: lst.extend([4]),
        lambda: lst.insert(0, 4),
        lambda: lst.pop(),
        lambda: lst.sort(),
    ):
        with pytest.raises(NotImplementedError):
            mutate()
    lst_copy = copy.deepcopy(lst)
    assert isinstance(lst_copy, SimpleFrozenList)
    assert lst_copy == [1, 2, 3]
