"""Behavioral tests for a Fiddle-style configuration library.

These tests exercise the library through its public top-level API only
(``import fiddle as fdl`` plus the public submodules ``fiddle.diffing``,
``fiddle.selectors``, ``fiddle.history``, ``fiddle.arg_factory``,
``fiddle.printing``). They never import from internal modules.

Each test models a realistic user workflow -- construct a configuration of
plain Python objects, edit/inspect/compare it, and finally ``build`` it -- and
asserts every contract that workflow touches, so a test fails as a unit if any
single contract is wrong.
"""

import copy
import dataclasses
import importlib
import os
import pickle
import sys
import tempfile
import uuid
from typing import Any, List

import pytest

import fiddle as fdl
from fiddle import arg_factory
from fiddle import daglish
from fiddle import diffing
from fiddle import history
from fiddle import printing
from fiddle import selectors
from fiddle import tagging


# ---------------------------------------------------------------------------
# Fixture objects: a small, plain-Python "training stack". No ML dependencies.
# These stand in for the arbitrary user code that Fiddle configures and builds.
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Dense:
    units: int
    use_bias: bool = True
    activation: str = "relu"
    dtype: str = "float32"


@dataclasses.dataclass
class Sequential:
    layers: List[Any]
    name: str = "model"


@dataclasses.dataclass
class SGD:
    learning_rate: float
    momentum: float = 0.0


@dataclasses.dataclass
class Adam:
    learning_rate: float = 1e-3
    beta1: float = 0.9
    beta2: float = 0.999


@dataclasses.dataclass
class Trainer:
    model: Any
    optimizer: Any
    train_steps: int = 1000


def make_dataset(name, batch_size=32, shuffle=True):
    """A plain factory function (not a class) used to test function configs."""
    return {"name": name, "batch_size": batch_size, "shuffle": shuffle}


def pipeline(*stages, mode="sequential"):
    """A variadic function used to test configuring *args callables."""
    return {"stages": list(stages), "mode": mode}


@dataclasses.dataclass
class Bucket:
    """Holds a mutable list; used to test fresh-per-call construction."""

    items: list


@dataclasses.dataclass
class Pair:
    """Holds two independent mutable lists; used to test multiple factories."""

    first: list
    second: list


@dataclasses.dataclass
class Registry:
    """Holds a dict of sub-components; used to test dict-keyed traversal."""

    components: dict


@dataclasses.dataclass
class Layer:
    """Base layer type; used to test subclass-aware selection."""

    width: int


@dataclasses.dataclass
class DenseLayer(Layer):
    """A Layer subclass; used to test selecting a type and its subclasses."""

    activation: str = "relu"


def configure(base, *, mode="eager", **options):
    """A function with a keyword-only parameter and **kwargs, used to test that
    Config binds the full range of Python parameter kinds."""
    return {"base": base, "mode": mode, "options": options}


# Tags must be declared at module scope (the library forbids defining a Tag
# inside a function or lambda).


class DType(fdl.Tag):
    """Numeric dtype shared across the model."""


class FloatDType(DType):
    """A more specific dtype tag; subclasses DType to test tag inheritance."""


class TagA(fdl.Tag):
    """First tag, used for add/remove/clear tests."""


class TagB(fdl.Tag):
    """Second tag, used for add/remove/clear tests."""


# ---------------------------------------------------------------------------
# Group A -- Core config construction and build (the engine)
# ---------------------------------------------------------------------------


class TestConfigAndBuild:
    def test_build_nested_config_constructs_full_object_graph(self):
        """Configuring nested Configs and calling build() constructs the whole
        object graph, applying explicit values and leaving defaults intact."""
        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Sequential)
        cfg.model.layers = [fdl.Config(Dense, units=8), fdl.Config(Dense, units=4)]
        cfg.model.layers[1].activation = "gelu"
        cfg.optimizer = fdl.Config(Adam, learning_rate=0.01)
        cfg.train_steps = 50

        trainer = fdl.build(cfg)

        assert isinstance(trainer, Trainer)
        assert trainer.train_steps == 50
        assert trainer.model.name == "model"  # default preserved
        assert [layer.units for layer in trainer.model.layers] == [8, 4]
        assert trainer.model.layers[0].activation == "relu"  # default
        assert trainer.model.layers[1].activation == "gelu"  # explicit
        assert trainer.optimizer == Adam(learning_rate=0.01)

    def test_build_function_config_calls_function(self):
        """A Config wrapping a plain function calls it with configured args."""
        cfg = fdl.Config(make_dataset, name="train")
        cfg.batch_size = 128
        result = fdl.build(cfg)
        assert result == {"name": "train", "batch_size": 128, "shuffle": True}

    def test_build_preserves_shared_nodes(self):
        """A sub-config referenced from several places -- via attributes and via
        multiple list positions -- builds into a single shared object; nodes
        that are not shared build to distinct objects; and independent builds
        produce independent object graphs."""
        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Sequential, layers=[shared, fdl.Config(Dense, units=2), shared])
        cfg.optimizer = shared  # also referenced from an attribute

        built = fdl.build(cfg)
        # Same node reached three ways -> one object.
        assert built.optimizer is built.model.layers[0]
        assert built.model.layers[0] is built.model.layers[2]
        # A genuinely different node is a different object.
        assert built.model.layers[0] is not built.model.layers[1]
        assert built.optimizer.learning_rate == 0.5

        # Independent builds produce independent object graphs.
        other = fdl.build(cfg)
        assert other.optimizer is not built.optimizer

    def test_setting_unknown_argument_raises_type_error(self):
        """Setting an argument the target callable does not accept is rejected
        immediately with TypeError, not deferred to build time."""
        with pytest.raises(TypeError):
            fdl.Config(Dense, nonexistent_arg=1)
        cfg = fdl.Config(Dense, units=4)
        with pytest.raises(AttributeError):
            cfg.nonexistent_arg = 1

    def test_build_missing_required_argument_reports_path(self):
        """Building a config that is missing a required argument raises
        TypeError, and the message identifies the path to the failing
        sub-config."""
        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Sequential, layers=[])
        cfg.optimizer = fdl.Config(SGD)  # SGD.learning_rate is required, unset
        with pytest.raises(TypeError) as exc_info:
            fdl.build(cfg)
        # The error names the path to the offending sub-config.
        assert "optimizer" in str(exc_info.value)

    def test_introspection_helpers_reflect_explicit_arguments(self):
        """ordered_arguments returns only explicitly-set arguments, and
        get_callable returns the configured callable."""
        cfg = fdl.Config(Adam, learning_rate=0.2)
        assert fdl.ordered_arguments(cfg) == {"learning_rate": 0.2}
        cfg.beta1 = 0.8
        assert fdl.ordered_arguments(cfg) == {"learning_rate": 0.2, "beta1": 0.8}
        assert fdl.get_callable(cfg) is Adam

    def test_mutation_helpers_update_and_retarget_configs(self):
        """assign sets multiple arguments at once and update_callable swaps the
        target callable while keeping compatible arguments."""
        cfg = fdl.Config(SGD, learning_rate=0.1)
        fdl.assign(cfg, learning_rate=0.05, momentum=0.9)
        assert fdl.build(cfg) == SGD(learning_rate=0.05, momentum=0.9)

        adam_cfg = fdl.Config(Adam, learning_rate=0.3)
        fdl.update_callable(adam_cfg, SGD)
        assert fdl.get_callable(adam_cfg) is SGD
        assert fdl.build(adam_cfg) == SGD(learning_rate=0.3)

    def test_config_accepts_positional_arguments(self):
        """Positional arguments passed to Config are bound to the target's
        parameters by position, just like calling the callable directly."""
        cfg = fdl.Config(Dense, 16)  # units bound positionally
        assert fdl.build(cfg) == Dense(units=16)

    def test_partial_nested_inside_config_builds_to_a_factory_slot(self):
        """When a Partial is nested inside a Config, build constructs the outer
        object normally but leaves a callable factory at the Partial's slot."""
        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Dense, units=8)
        cfg.optimizer = fdl.Partial(Adam, learning_rate=0.01)  # a factory slot
        built = fdl.build(cfg)
        assert built.model == Dense(units=8)
        assert callable(built.optimizer)
        assert built.optimizer() == Adam(learning_rate=0.01)

    def test_build_traverses_plain_containers_of_configs(self):
        """build recurses into plain lists and dicts, building any Config it
        finds, even when the top-level value is not itself a Buildable."""
        structure = {
            "first": fdl.Config(Dense, units=1),
            "rest": [fdl.Config(Dense, units=2), fdl.Config(Dense, units=3)],
        }
        out = fdl.build(structure)
        assert out["first"] == Dense(units=1)
        assert [layer.units for layer in out["rest"]] == [2, 3]

    def test_config_supports_variadic_callables(self):
        """A Config for a function with *args binds positional arguments into
        the variadic parameter while keyword-only arguments are set by name."""
        cfg = fdl.Config(pipeline, "tokenize", "embed", "encode")
        cfg.mode = "parallel"
        assert fdl.build(cfg) == {
            "stages": ["tokenize", "embed", "encode"],
            "mode": "parallel",
        }

    def test_config_binds_keyword_only_and_var_keyword_parameters(self):
        """A Config binds the full range of parameter kinds: a keyword-only
        parameter is set by name, and extra keyword arguments are routed into a
        ``**kwargs`` parameter."""
        cfg = fdl.Config(configure, base="x", mode="lazy", alpha=1, beta=2)
        assert fdl.build(cfg) == {
            "base": "x",
            "mode": "lazy",
            "options": {"alpha": 1, "beta": 2},
        }

    def test_positional_arguments_support_indexing_slicing_and_deletion(self):
        """The positional arguments of a variadic Config are addressable by
        index: an individual position can be read, a slice can be read, a
        position can be deleted (shifting the later ones down), and a position
        can be reassigned -- with build() reflecting the final sequence."""
        cfg = fdl.Config(pipeline, "tokenize", "embed", "encode")
        assert cfg[0] == "tokenize"
        assert cfg[0:2] == ["tokenize", "embed"]

        del cfg[1]  # remove "embed"; "encode" shifts down into index 1
        assert cfg[1] == "encode"

        cfg[1] = "decode"  # reassign that position
        assert fdl.build(cfg) == {
            "stages": ["tokenize", "decode"],
            "mode": "sequential",
        }

    def test_ordered_arguments_can_include_defaults(self):
        """ordered_arguments returns only explicitly-set arguments by default,
        but with include_defaults=True it also reports every argument left at
        its default value."""
        cfg = fdl.Config(Adam, learning_rate=0.2)
        assert fdl.ordered_arguments(cfg) == {"learning_rate": 0.2}
        assert fdl.ordered_arguments(cfg, include_defaults=True) == {
            "learning_rate": 0.2,
            "beta1": 0.9,
            "beta2": 0.999,
        }

    def test_update_callable_rejects_or_drops_incompatible_arguments(self):
        """update_callable refuses by default to retarget a config when an
        already-set argument is invalid for the new callable; passing
        drop_invalid_args=True drops those arguments and keeps the rest."""
        cfg = fdl.Config(Adam, learning_rate=0.3, beta1=0.8)
        with pytest.raises(TypeError):
            fdl.update_callable(cfg, SGD)  # SGD has no beta1 parameter

        cfg2 = fdl.Config(Adam, learning_rate=0.3, beta1=0.8)
        fdl.update_callable(cfg2, SGD, drop_invalid_args=True)
        assert fdl.get_callable(cfg2) is SGD
        assert fdl.ordered_arguments(cfg2) == {"learning_rate": 0.3}
        assert fdl.build(cfg2) == SGD(learning_rate=0.3)

    def test_build_detects_cycles(self):
        """A configuration that refers to itself (directly or transitively)
        contains a cycle; build refuses to construct it (raising ValueError)
        rather than recursing forever."""
        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Dense, units=2)
        cfg.optimizer = cfg  # cycle: the trainer is its own optimizer
        with pytest.raises(ValueError):
            fdl.build(cfg)


# ---------------------------------------------------------------------------
# Group B -- Partial, ArgFactory, and casting
# ---------------------------------------------------------------------------


class TestPartialAndArgFactory:
    def test_partial_builds_into_a_reusable_factory(self):
        """Building a Partial yields a callable that constructs the object when
        invoked, and accepts late-bound overrides at call time."""
        partial = fdl.Partial(Dense, units=16)
        factory = fdl.build(partial)
        assert callable(factory)
        assert factory() == Dense(units=16)
        assert factory(activation="tanh") == Dense(units=16, activation="tanh")

    def test_multiple_arg_factories_are_independent_per_call(self):
        """A Partial with two ArgFactory arguments gives each call its own fresh
        value for both, and the two values are independent of each other."""
        partial = fdl.Partial(Pair)
        partial.first = fdl.ArgFactory(list)
        partial.second = fdl.ArgFactory(list)
        make = fdl.build(partial)

        a = make()
        b = make()
        a.first.append(1)
        assert a.first == [1]
        assert a.second == []  # the other factory arg is untouched
        assert b.first == []  # a separate call is unaffected
        assert a.first is not a.second
        assert a.first is not b.first

    def test_cast_converts_between_config_partial_and_arg_factory(self):
        """cast converts a configuration to another buildable type, preserving
        the set arguments. Config -> Partial changes build() from 'construct the
        object' to 'return a factory'; Config -> ArgFactory yields an ArgFactory
        that, cast back to a Config, still builds the original object."""
        cfg = fdl.Config(Dense, units=32, activation="elu")

        as_partial = fdl.cast(fdl.Partial, cfg)
        assert isinstance(as_partial, fdl.Partial)
        assert fdl.build(as_partial)() == Dense(units=32, activation="elu")

        as_arg_factory = fdl.cast(fdl.ArgFactory, cfg)
        assert isinstance(as_arg_factory, fdl.ArgFactory)
        # Arguments survive the ArgFactory cast: cast back to Config and build.
        round_tripped = fdl.cast(fdl.Config, as_arg_factory)
        assert fdl.build(round_tripped) == Dense(units=32, activation="elu")

    def test_nested_arg_factory_keeps_config_sharing_but_refreshes_factory(self):
        """Inside a built Partial, an ArgFactory argument is rebuilt fresh on
        every call, while a plain Config argument is built once and shared
        across every call of the same factory."""
        partial = fdl.Partial(Trainer)
        partial.model = fdl.ArgFactory(list)  # fresh value per call
        partial.optimizer = fdl.Config(Adam, learning_rate=0.5)  # built once, shared
        make = fdl.build(partial)

        first = make()
        second = make()
        assert first.model is not second.model  # ArgFactory: fresh each call
        assert first.optimizer is second.optimizer  # Config: shared across calls


# ---------------------------------------------------------------------------
# Group C -- Tags
# ---------------------------------------------------------------------------


class TestTags:
    def test_set_tagged_updates_every_tagged_argument_at_once(self):
        """A tag attached to several arguments lets set_tagged override all of
        them in a single call, reflected in the built objects."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [fdl.Config(Dense, units=8), fdl.Config(Dense, units=4)]
        fdl.add_tag(cfg.layers[0], "dtype", DType)
        fdl.add_tag(cfg.layers[1], "dtype", DType)

        assert fdl.get_tags(cfg.layers[0], "dtype") == frozenset({DType})

        fdl.set_tagged(cfg, tag=DType, value="bfloat16")
        built = fdl.build(cfg)
        assert built.layers[0].dtype == "bfloat16"
        assert built.layers[1].dtype == "bfloat16"

    def test_remove_and_clear_tags(self):
        """remove_tag detaches one tag and clear_tags removes all tags from an
        argument, after which set_tagged no longer affects it."""
        cfg = fdl.Config(Dense, units=8)
        fdl.add_tag(cfg, "activation", TagA)
        fdl.add_tag(cfg, "activation", TagB)
        assert fdl.get_tags(cfg, "activation") == frozenset({TagA, TagB})

        fdl.remove_tag(cfg, "activation", TagA)
        assert fdl.get_tags(cfg, "activation") == frozenset({TagB})

        fdl.clear_tags(cfg, "activation")
        assert fdl.get_tags(cfg, "activation") == frozenset()

    def test_list_and_materialize_tags(self):
        """list_tags reports every tag used in a config, and materialize_tags
        replaces tagged-value defaults with concrete values in-place."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [fdl.Config(Dense, units=8)]
        fdl.add_tag(cfg.layers[0], "activation", TagA)
        assert tagging.list_tags(cfg) == frozenset({TagA})

        cfg2 = fdl.Config(Dense, units=4)
        cfg2.dtype = DType.new(default="float16")
        tagging.materialize_tags(cfg2)
        assert fdl.ordered_arguments(cfg2)["dtype"] == "float16"

    def test_tagged_value_default_override_and_materialize(self):
        """A TaggedValue builds to its default until the tag is given a concrete
        value via set_tagged; thereafter build uses that value, and
        materialize_tags freezes in the set value (not the original default)."""
        cfg = fdl.Config(Dense, units=4)
        cfg.dtype = DType.new(default="float16")
        assert fdl.build(cfg).dtype == "float16"  # default used until overridden

        fdl.set_tagged(cfg, tag=DType, value="int8")
        assert fdl.build(cfg).dtype == "int8"  # override takes effect

        tagging.materialize_tags(cfg)
        assert fdl.ordered_arguments(cfg)["dtype"] == "int8"  # frozen as set value
        assert fdl.build(cfg).dtype == "int8"

    def test_set_tagged_and_list_tags_respect_tag_subclasses(self):
        """Setting a value by a parent tag also updates values carrying a
        subclass of that tag, and list_tags can expand a config's tags to
        include the superclasses they inherit from."""
        cfg = fdl.Config(Dense, units=4)
        cfg.dtype = FloatDType.new(default="float16")  # FloatDType subclasses DType
        assert fdl.build(cfg).dtype == "float16"

        fdl.set_tagged(cfg, tag=DType, value="int8")  # set via the PARENT tag
        assert fdl.build(cfg).dtype == "int8"

        assert tagging.list_tags(cfg) == frozenset({FloatDType})
        assert tagging.list_tags(cfg, add_superclasses=True) == frozenset(
            {FloatDType, DType}
        )

    def test_tagged_value_with_multiple_tags_is_settable_by_any_tag(self):
        """A tagged value declared with several tags reports all of them and
        can be set through any one of them."""
        cfg = fdl.Config(Dense, units=4)
        cfg.dtype = fdl.TaggedValue(tags=(TagA, TagB), default="float16")
        assert fdl.build(cfg).dtype == "float16"
        assert fdl.get_tags(cfg, "dtype") == frozenset({TagA, TagB})

        fdl.set_tagged(cfg, tag=TagA, value="int8")  # set via just one of the tags
        assert fdl.build(cfg).dtype == "int8"


# ---------------------------------------------------------------------------
# Group D -- Selectors
# ---------------------------------------------------------------------------


class TestSelectors:
    def test_select_by_type_overrides_all_matching_nodes(self):
        """Selecting every node of a given type and setting an attribute
        applies the override across the whole config graph at once."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [
            fdl.Config(Dense, units=8),
            fdl.Config(Dense, units=16),
            fdl.Config(Dense, units=32),
        ]
        selectors.select(cfg, Dense).set(use_bias=False)
        built = fdl.build(cfg)
        assert [layer.use_bias for layer in built.layers] == [False, False, False]
        # Units were untouched.
        assert [layer.units for layer in built.layers] == [8, 16, 32]

    def test_select_by_tag_replaces_all_tagged_values(self):
        """Selecting by tag and replacing the value updates every argument
        carrying that tag, regardless of where it sits in the graph."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [fdl.Config(Dense, units=8), fdl.Config(Dense, units=16)]
        fdl.add_tag(cfg.layers[0], "dtype", DType)
        fdl.add_tag(cfg.layers[1], "dtype", DType)

        selectors.select(cfg, tag=DType).replace(value="int8")
        built = fdl.build(cfg)
        assert [layer.dtype for layer in built.layers] == ["int8", "int8"]

    def test_selector_get_reads_values_and_check_nonempty_guards_empty(self):
        """A type selection can read an attribute from every matching node via
        get(), and asking for a non-empty selection over a type that does not
        appear in the graph raises instead of silently selecting nothing."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [fdl.Config(Dense, units=8), fdl.Config(Dense, units=16)]

        selection = selectors.select(cfg, Dense)
        assert list(selection.get("units")) == [8, 16]

        with pytest.raises(ValueError):
            list(selectors.select(cfg, Adam, check_nonempty=True).get("learning_rate"))

    def test_select_can_match_subclasses_of_a_type(self):
        """Selecting a base type matches configs of that type and its
        subclasses; match_subclasses=False restricts the selection to the exact
        type only."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [fdl.Config(Layer, width=1), fdl.Config(DenseLayer, width=2)]

        # Exact-type only: just the Layer node (both nodes carry `width`, so
        # reading it from the selection counts the matched configurations).
        assert len(list(selectors.select(cfg, Layer, match_subclasses=False).get("width"))) == 1
        # Including subclasses: both Layer and DenseLayer.
        assert len(list(selectors.select(cfg, Layer, match_subclasses=True).get("width"))) == 2

        selectors.select(cfg, Layer, match_subclasses=True).set(width=9)
        built = fdl.build(cfg)
        assert [layer.width for layer in built.layers] == [9, 9]


# ---------------------------------------------------------------------------
# Group E -- Copying
# ---------------------------------------------------------------------------


class TestCopying:
    def test_copy_with_applies_overrides_keeps_other_args_and_sharing(self):
        """copy_with returns a modified clone -- the override is applied, other
        arguments are preserved, the original is left unchanged, and internal
        sharing is preserved so the clone still shares its sub-node on build."""
        original = fdl.Config(Dense, units=8, activation="relu")
        clone = fdl.copy_with(original, units=64)
        assert clone.units == 64
        assert clone.activation == "relu"  # other args preserved
        assert original.units == 8  # original untouched

        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer, model=shared, optimizer=shared)
        clone2 = fdl.copy_with(cfg, train_steps=10)
        assert clone2.model is clone2.optimizer  # sharing preserved in the clone
        built = fdl.build(clone2)
        assert built.model is built.optimizer

    def test_deepcopy_with_breaks_sharing_with_original(self):
        """deepcopy_with produces an independent graph; editing the copy does
        not affect the original."""
        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer, model=shared, optimizer=shared)
        clone = fdl.deepcopy_with(cfg)
        clone.optimizer.learning_rate = 0.001
        assert cfg.optimizer.learning_rate == 0.5
        # Internal sharing is still preserved within the deep copy.
        assert clone.model is clone.optimizer


# ---------------------------------------------------------------------------
# Group F -- Diffing
# ---------------------------------------------------------------------------


class TestDiffing:
    def test_build_diff_empty_for_equal_configs_nonempty_for_changes(self):
        """build_diff reports no changes between two equal configs, and a
        non-empty diff for differing ones that, when applied, reproduces the
        new config. (The exact number of changes is an implementation detail of
        the diff's granularity and is not asserted.)"""
        base = fdl.Config(Dense, units=8, activation="relu", dtype="float32")
        same = fdl.Config(Dense, units=8, activation="relu", dtype="float32")
        assert len(diffing.build_diff(base, same).changes) == 0

        changed = fdl.Config(Dense, units=16, activation="gelu", dtype="float32")
        diff = diffing.build_diff(base, changed)
        assert len(diff.changes) > 0
        target = fdl.Config(Dense, units=8, activation="relu", dtype="float32")
        diffing.apply_diff(diff, target)
        assert fdl.build(target) == Dense(units=16, activation="gelu", dtype="float32")

    def test_diff_roundtrip_with_combined_changes(self):
        """A single diff over a nested graph that simultaneously modifies, adds,
        and removes arguments (at several depths) round-trips: applying it to a
        copy of `old` reproduces `new` exactly when built."""
        old = fdl.Config(
            Trainer,
            model=fdl.Config(
                Sequential, layers=[fdl.Config(Dense, units=8, activation="relu")]
            ),
            optimizer=fdl.Config(Adam, learning_rate=0.1, beta1=0.9),
        )
        new = fdl.Config(
            Trainer,
            model=fdl.Config(
                Sequential, layers=[fdl.Config(Dense, units=16)], name="net"
            ),
            optimizer=fdl.Config(Adam, learning_rate=0.2),
        )
        diff = diffing.build_diff(old, new)
        target = fdl.deepcopy_with(old)
        diffing.apply_diff(diff, target)
        assert fdl.build(target) == fdl.build(new)

    def test_diff_reconstructs_shared_nodes(self):
        """Diffing a config whose two slots hold distinct sub-configs against
        one where a single sub-config is shared, then applying the diff,
        reconstructs that sharing -- the slots build to one shared object."""
        shared = fdl.Config(Adam, learning_rate=0.5)
        old = fdl.Config(
            Trainer,
            model=fdl.Config(Adam, learning_rate=0.1),
            optimizer=fdl.Config(Adam, learning_rate=0.2),
        )
        new = fdl.Config(Trainer, model=shared, optimizer=shared)
        diff = diffing.build_diff(old, new)

        target = fdl.Config(
            Trainer,
            model=fdl.Config(Adam, learning_rate=0.1),
            optimizer=fdl.Config(Adam, learning_rate=0.2),
        )
        diffing.apply_diff(diff, target)
        assert target.model is target.optimizer  # sharing restored in the config
        built = fdl.build(target)
        assert built.model is built.optimizer  # and preserved through build
        assert built.model.learning_rate == 0.5

    def test_diff_captures_tag_changes(self):
        """A diff captures tags added (or removed) between two configs, and
        applying it reproduces the tag on the target; configs with identical
        tags diff as empty."""
        old = fdl.Config(Dense, units=4)
        new = fdl.Config(Dense, units=4)
        fdl.add_tag(new, "activation", DType)

        diff = diffing.build_diff(old, new)
        assert len(diff.changes) > 0  # the added tag is a change

        target = fdl.Config(Dense, units=4)
        diffing.apply_diff(diff, target)
        assert fdl.get_tags(target, "activation") == frozenset({DType})

        # Two configs carrying the same tag diff to nothing.
        a = fdl.Config(Dense, units=4)
        b = fdl.Config(Dense, units=4)
        fdl.add_tag(a, "activation", DType)
        fdl.add_tag(b, "activation", DType)
        assert len(diffing.build_diff(a, b).changes) == 0


# ---------------------------------------------------------------------------
# Group G -- History
# ---------------------------------------------------------------------------


class TestHistory:
    def test_argument_history_records_edits_in_order(self):
        """A config tracks the sequence of values assigned to each argument, in
        the order the edits were made."""
        cfg = fdl.Config(Dense, units=1)
        cfg.units = 2
        cfg.units = 3
        recorded = [entry.new_value for entry in cfg.__argument_history__["units"]]
        assert recorded == [1, 2, 3]

    def test_history_records_change_kind_order_and_can_be_suspended(self):
        """History entries record the kind of change (a value assignment vs a
        tag update) and a monotonically increasing sequence id; tag changes are
        recorded too; and suspend_tracking() stops new entries from being added
        while the edit itself still takes effect."""
        cfg = fdl.Config(Dense, units=1)
        cfg.units = 2
        fdl.add_tag(cfg, "activation", TagA)

        units_history = cfg.__argument_history__["units"]
        assert all(e.kind == history.ChangeKind.NEW_VALUE for e in units_history)
        seq_ids = [e.sequence_id for e in units_history]
        assert seq_ids == sorted(seq_ids) and len(set(seq_ids)) == len(seq_ids)

        # Attaching a tag is recorded as a tag-update entry.
        tag_history = cfg.__argument_history__["activation"]
        assert tag_history[-1].kind == history.ChangeKind.UPDATE_TAGS

        # suspend_tracking() suppresses new history while still applying the edit.
        before = len(cfg.__argument_history__["units"])
        with history.suspend_tracking():
            cfg.units = 3
        assert cfg.units == 3  # edit applied
        assert len(cfg.__argument_history__["units"]) == before  # but not recorded


# ---------------------------------------------------------------------------
# Group H -- Materialize defaults
# ---------------------------------------------------------------------------


class TestMaterialize:
    def test_materialize_defaults_makes_implicit_defaults_explicit(self):
        """materialize_defaults turns unset arguments with defaults into
        explicitly-set arguments, without changing what build produces."""
        cfg = fdl.Config(Adam, learning_rate=0.2)
        assert fdl.ordered_arguments(cfg) == {"learning_rate": 0.2}
        before = fdl.build(cfg)

        fdl.materialize_defaults(cfg)
        assert fdl.ordered_arguments(cfg) == {
            "learning_rate": 0.2,
            "beta1": 0.9,
            "beta2": 0.999,
        }
        assert fdl.build(cfg) == before


# ---------------------------------------------------------------------------
# Group I -- Printing
# ---------------------------------------------------------------------------


class TestPrinting:
    def test_flattened_printing_lists_each_leaf_argument(self):
        """as_str_flattened renders one 'path: value' line per leaf argument of
        a nested config."""
        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Sequential, layers=[fdl.Config(Dense, units=8)])
        cfg.optimizer = fdl.Config(Adam, learning_rate=0.01)
        text = printing.as_str_flattened(cfg)
        assert "model.layers[0].units: int = 8" in text
        assert "optimizer.learning_rate: float = 0.01" in text

        # The dict form maps exactly the set leaf paths to their values -- the
        # full mapping, so a partial or over-broad implementation is rejected.
        assert printing.as_dict_flattened(cfg) == {
            "model.layers[0].units": 8,
            "optimizer.learning_rate": 0.01,
        }


# ---------------------------------------------------------------------------
# Group J -- arg_factory module (standalone)
# ---------------------------------------------------------------------------


class TestArgFactoryModule:
    def test_supply_defaults_creates_fresh_default_per_call(self):
        """arg_factory.supply_defaults with default_factory gives each call its
        own freshly-constructed default argument."""

        @arg_factory.supply_defaults
        def collect(item, into=arg_factory.default_factory(list)):
            into.append(item)
            return into

        first = collect("a")
        second = collect("b")
        assert first == ["a"]
        assert second == ["b"]
        assert first is not second

    def test_partial_binds_factories_positionally_by_keyword_and_skips_overrides(self):
        """arg_factory.partial binds a factory to a parameter (positionally or by
        keyword) so each call gets a fresh value; binding several at once gives
        each its own fresh value; and supplying a factory-bound argument
        explicitly at call time bypasses the factory for that call."""

        def attach(tags, label):
            tags.append(label)
            return tags

        # Positional binding consumes the first parameter; fresh list per call.
        bind_positional = arg_factory.partial(attach, list)
        assert bind_positional("a") == ["a"]
        assert bind_positional("b") == ["b"]  # not shared with the previous call

        # Keyword binding; an explicit value at call time bypasses the factory.
        bind_kw = arg_factory.partial(attach, tags=list)
        assert bind_kw(label="a") == ["a"]
        assert bind_kw(tags=["seed"], label="x") == ["seed", "x"]

        # Several factory-bound arguments at once, each independent and fresh.
        def combine(items, mapping):
            return items, mapping

        build_record = arg_factory.partial(combine, items=list, mapping=dict)
        first = build_record()
        second = build_record()
        first[0].append(1)
        first[1]["k"] = "v"
        assert first == ([1], {"k": "v"})
        assert second == ([], {})  # fresh, independent containers
        assert first[0] is not second[0]


# ---------------------------------------------------------------------------
# Group K -- DAG traversal (paths)
# ---------------------------------------------------------------------------


class TestTraversal:
    def test_iterate_yields_every_node_with_its_path(self):
        """Iterating a config graph visits every nested value together with a
        structured path describing how to reach it from the root."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [fdl.Config(Dense, units=8), fdl.Config(Dense, units=4)]

        units_by_path = {}
        for value, path in daglish.iterate(cfg, memoized=False):
            if isinstance(value, fdl.Config) and fdl.get_callable(value) is Dense:
                units_by_path[daglish.path_str(path)] = value.units

        assert units_by_path == {".layers[0]": 8, ".layers[1]": 4}

    def test_follow_path_resolves_a_path_to_its_value(self):
        """A structured path can be followed from the root to fetch the value
        it points at."""
        cfg = fdl.Config(Sequential)
        cfg.layers = [fdl.Config(Dense, units=8), fdl.Config(Dense, units=4)]

        path = [daglish.Attr("layers"), daglish.Index(1), daglish.Attr("units")]
        assert daglish.path_str(path) == ".layers[1].units"
        assert daglish.follow_path(cfg, path) == 4

    def test_memoized_and_non_memoized_traversal_of_shared_nodes(self):
        """Iterating a graph that contains a shared node visits it once in
        memoized mode but once per referencing path in non-memoized mode; the
        full set of paths reaching the shared node can be collected by id."""
        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Sequential)
        cfg.layers = [shared, fdl.Config(Dense, units=2), shared]

        memoized_paths = [
            daglish.path_str(p)
            for value, p in daglish.iterate(cfg, memoized=True)
            if value is shared
        ]
        assert memoized_paths == [".layers[0]"]  # visited once

        all_paths = [
            daglish.path_str(p)
            for value, p in daglish.iterate(cfg, memoized=False)
            if value is shared
        ]
        assert all_paths == [".layers[0]", ".layers[2]"]  # once per path

        by_id = daglish.collect_paths_by_id(cfg, memoizable_only=True)
        assert [daglish.path_str(p) for p in by_id[id(shared)]] == [
            ".layers[0]",
            ".layers[2]",
        ]

    def test_dict_keyed_traversal_uses_key_path_elements(self):
        """Traversing a config with a dict-valued argument reaches the entries
        via Key path elements, rendered as ['key']; a path built from Key can be
        followed back to the value."""
        cfg = fdl.Config(
            Registry,
            components={
                "enc": fdl.Config(Dense, units=8),
                "dec": fdl.Config(Dense, units=4),
            },
        )

        units_by_path = {}
        for value, path in daglish.iterate(cfg, memoized=False):
            if isinstance(value, fdl.Config) and fdl.get_callable(value) is Dense:
                units_by_path[daglish.path_str(path)] = value.units
        assert units_by_path == {".components['enc']": 8, ".components['dec']": 4}

        path = [daglish.Attr("components"), daglish.Key("enc"), daglish.Attr("units")]
        assert daglish.path_str(path) == ".components['enc'].units"
        assert daglish.follow_path(cfg, path) == 8


# ---------------------------------------------------------------------------
# Group L -- End-to-end workflows (multiple features composed)
# ---------------------------------------------------------------------------


class TestWorkflows:
    def test_tag_select_copy_build_workflow(self):
        """A realistic workflow: build a base config, set a tagged value across
        the graph, override an attribute on every layer via a selector, then
        derive a variant with copy_with. The base and the variant build to the
        expected objects, and editing the variant does not disturb the base."""
        base = fdl.Config(Sequential)
        base.layers = [fdl.Config(Dense, units=8), fdl.Config(Dense, units=16)]
        fdl.add_tag(base.layers[0], "dtype", DType)
        fdl.add_tag(base.layers[1], "dtype", DType)
        fdl.set_tagged(base, tag=DType, value="bfloat16")
        selectors.select(base, Dense).set(use_bias=False)

        variant = fdl.copy_with(base, name="variant")

        built_base = fdl.build(base)
        built_variant = fdl.build(variant)

        # The selector + tag edits are reflected in both builds.
        for built in (built_base, built_variant):
            assert [layer.dtype for layer in built.layers] == ["bfloat16", "bfloat16"]
            assert [layer.use_bias for layer in built.layers] == [False, False]
            assert [layer.units for layer in built.layers] == [8, 16]

        # Only the variant carries the new name; the base keeps its default.
        assert built_base.name == "model"
        assert built_variant.name == "variant"


# ---------------------------------------------------------------------------
# Group M -- Object protocol (equality, hashing, copy/pickle)
# ---------------------------------------------------------------------------


class TestObjectProtocol:
    def test_equality_is_dag_structure_aware_and_configs_are_unhashable(self):
        """Config equality compares the target, the arguments, and the sharing
        structure: two configs that are value-equal but differ in whether a
        sub-config is shared are unequal. A Config and a Partial of the same
        target are unequal, and configs are unhashable."""
        a = fdl.Config(Adam, learning_rate=0.1)
        b = fdl.Config(Adam, learning_rate=0.1)
        assert a == b  # same target, same arguments

        shared = fdl.Config(Trainer, model=a, optimizer=a)  # one node, two slots
        distinct = fdl.Config(Trainer, model=a, optimizer=b)  # two equal-but-distinct
        assert shared != distinct  # value-equal but different sharing structure

        assert fdl.Config(Adam) != fdl.Partial(Adam)  # configuration type matters

        with pytest.raises(TypeError):
            hash(a)

    def test_copy_deepcopy_and_pickle_preserve_shared_node_identity(self):
        """copy, deepcopy, and pickle round-trips preserve a config's internal
        sharing: a sub-config referenced from two slots is still a single
        shared node afterwards. deepcopy is independent of the original, while a
        shallow copy keeps sharing the original's sub-nodes."""
        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer, model=shared, optimizer=shared)

        deep = copy.deepcopy(cfg)
        assert deep.model is deep.optimizer  # sharing preserved within the copy
        assert deep.model is not cfg.model  # but independent of the original

        shallow = copy.copy(cfg)
        assert shallow.model is cfg.model  # shallow copy shares the originals

        restored = pickle.loads(pickle.dumps(cfg))
        assert restored == cfg
        assert restored.model is restored.optimizer  # sharing survives serialization


# ---------------------------------------------------------------------------
# Group N -- JSON serialization (round-trip)
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_json_round_trip_preserves_values(self):
        """A nested configuration serialized to JSON and loaded back is equal to
        the original and builds to the same objects."""
        from fiddle.experimental import serialization

        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Sequential, layers=[fdl.Config(Dense, units=8)])
        cfg.optimizer = fdl.Config(Adam, learning_rate=0.01)
        cfg.train_steps = 50

        serialized = serialization.dump_json(cfg)
        assert isinstance(serialized, str)
        restored = serialization.load_json(serialized)

        assert restored == cfg
        assert fdl.build(restored) == fdl.build(cfg)

    def test_json_round_trip_reconstructs_shared_nodes(self):
        """A node shared across two slots is restored as a single shared node
        after a JSON round-trip."""
        from fiddle.experimental import serialization

        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer, model=shared, optimizer=shared)

        restored = serialization.load_json(serialization.dump_json(cfg))
        assert restored == cfg
        assert restored.model is restored.optimizer


# ---------------------------------------------------------------------------
# Group O -- Code generation (Config -> Python source, graded by round-trip)
# ---------------------------------------------------------------------------


def _run_new_codegen_fixture(src):
    """Execute a new_codegen-produced module string and return the result of its
    config_fixture(). The generated module is plain Python (no decorator), so a
    bare exec is sufficient."""
    namespace = {}
    exec(compile(src, "<generated_config>", "exec"), namespace)
    return namespace["config_fixture"]()


def _load_generated_module(src):
    """Write generated source to an importable temporary module and import it.
    auto_config fixtures must read their own source, so they cannot be exec'd
    from a string and need to live in a real importable file."""
    name = "fdl_generated_%s" % uuid.uuid4().hex
    directory = tempfile.mkdtemp()
    with open(os.path.join(directory, name + ".py"), "w") as handle:
        handle.write(src)
    sys.path.insert(0, directory)
    try:
        importlib.invalidate_caches()
        return importlib.import_module(name)
    finally:
        sys.path.remove(directory)


class TestCodegen:
    def test_new_codegen_round_trips_nested_and_function_configs(self):
        """new_codegen emits Python source whose config_fixture() rebuilds an
        equal configuration -- for a graph of class configs plus a function
        config -- and the rebuilt config builds to the same objects."""
        from fiddle.codegen import codegen

        cfg = fdl.Config(Trainer)
        cfg.model = fdl.Config(Sequential, layers=[fdl.Config(Dense, units=8)])
        cfg.optimizer = fdl.Config(make_dataset, name="opt")

        regenerated = _run_new_codegen_fixture(codegen.new_codegen(cfg))
        assert regenerated == cfg
        assert fdl.build(regenerated) == fdl.build(cfg)

    def test_new_codegen_preserves_shared_nodes(self):
        """Generated code reconstructs a shared sub-configuration as a single
        shared node -- both when referenced from two attributes and when
        referenced from two list positions."""
        from fiddle.codegen import codegen

        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer, model=shared, optimizer=shared)
        regen = _run_new_codegen_fixture(codegen.new_codegen(cfg))
        assert regen == cfg
        assert regen.model is regen.optimizer  # one shared node, not two copies

        shared2 = fdl.Config(Adam, learning_rate=0.25)
        listed = fdl.Config(
            Sequential, layers=[shared2, fdl.Config(Dense, units=2), shared2]
        )
        regen2 = _run_new_codegen_fixture(codegen.new_codegen(listed))
        assert regen2 == listed
        assert regen2.layers[0] is regen2.layers[2]
        assert regen2.layers[0] is not regen2.layers[1]

    def test_new_codegen_round_trips_partial_and_arg_factory(self):
        """Generated code preserves a Partial (builds to a factory) and an
        ArgFactory (fresh value per call) at their slots."""
        from fiddle.codegen import codegen

        cfg = fdl.Config(
            Trainer,
            model=fdl.Config(Dense, units=4),
            optimizer=fdl.Partial(Adam, learning_rate=0.1),
        )
        regen = _run_new_codegen_fixture(codegen.new_codegen(cfg))
        assert regen == cfg
        assert isinstance(regen.optimizer, fdl.Partial)
        assert fdl.build(regen).optimizer() == Adam(learning_rate=0.1)

        partial = fdl.Partial(Bucket)
        partial.items = fdl.ArgFactory(list)
        regen_p = _run_new_codegen_fixture(codegen.new_codegen(partial))
        assert regen_p == partial
        make = fdl.build(regen_p)
        first, second = make(), make()
        first.items.append("x")
        assert second.items == []  # fresh list each call survived the round-trip
        assert first.items is not second.items

    def test_new_codegen_round_trips_variadic_positional_arguments(self):
        """Generated code reproduces the positional/variadic arguments and the
        keyword argument of a function config."""
        from fiddle.codegen import codegen

        cfg = fdl.Config(pipeline, "tokenize", "embed", "encode")
        cfg.mode = "parallel"
        regen = _run_new_codegen_fixture(codegen.new_codegen(cfg))
        assert regen == cfg
        assert fdl.build(regen) == {
            "stages": ["tokenize", "embed", "encode"],
            "mode": "parallel",
        }

    def test_new_codegen_emits_named_sub_fixtures_preserving_sharing(self):
        """With sub_fixtures, new_codegen emits a separate named function for a
        requested node; a node shared across the graph becomes a single
        sub-fixture whose one result is reused, so sharing is preserved."""
        from fiddle.codegen import codegen

        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer, model=shared, optimizer=shared)
        src = codegen.new_codegen(cfg, sub_fixtures={"optimizer_fixture": shared})
        assert "def optimizer_fixture(" in src  # a named sub-fixture was emitted

        regen = _run_new_codegen_fixture(src)
        assert regen == cfg
        assert regen.model is regen.optimizer

    def test_auto_config_codegen_round_trips_via_as_buildable(self):
        """auto_config_codegen emits an @auto_config fixture whose
        as_buildable() reconstructs an equal configuration, preserving shared
        nodes."""
        from fiddle.codegen import codegen

        shared = fdl.Config(Adam, learning_rate=0.5)
        cfg = fdl.Config(Trainer, model=shared, optimizer=shared)
        module = _load_generated_module(codegen.auto_config_codegen(cfg))
        regen = module.config_fixture.as_buildable()
        assert regen == cfg
        assert regen.model is regen.optimizer

    def test_legacy_codegen_dot_syntax_round_trips(self):
        """codegen_dot_syntax emits imperative build_config() code that
        reconstructs an equal configuration."""
        from fiddle.codegen import codegen

        cfg = fdl.Config(Dense, units=8, activation="gelu")
        node = codegen.codegen_dot_syntax(cfg)
        src = "\n".join(node.lines())
        namespace = {}
        exec(compile(src, "<legacy_generated>", "exec"), namespace)
        regen = namespace["build_config"]()
        assert regen == cfg
        assert fdl.build(regen) == Dense(units=8, activation="gelu")
