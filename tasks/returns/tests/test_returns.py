"""
Tests for dry-python/returns — functional programming containers library.

These are end-to-end, program-shaped tests: each test builds one realistic usage
scenario, threads it through several related APIs, and asserts every contract the
scenario touches with exact expected values. A test fails as a unit if any one
contract is wrong — there is no partial credit for getting the easy half right.
Trivial single-method checks are folded into the workflow that uses them.
"""

from __future__ import annotations

import json
import pickle

import pytest

# ============================================================================
# Result — synchronous error handling
# ============================================================================


class TestResultProgram:
    """Result container used as a real error-handling pipeline."""

    def test_result_pipeline_do_notation_and_matching(self):
        """A user parses/validates/recovers, composes with do-notation, and routes
        the outcomes with structural pattern matching — all in one program."""
        from returns.result import Result, Success, Failure

        def parse_int(s: str) -> Result[int, str]:
            try:
                return Success(int(s))
            except ValueError:
                return Failure(f"cannot parse '{s}'")

        def validate_positive(n: int) -> Result[int, str]:
            return Success(n) if n > 0 else Failure("non-positive")

        # bind/map/alt success path, alt-rewrite on parse failure, lash recovery.
        assert (
            parse_int("42").bind(validate_positive).map(lambda n: n * 2)
            .alt(lambda e: f"recovered: {e}")
        ) == Success(84)
        assert (
            parse_int("abc").bind(validate_positive).map(lambda n: n * 2)
            .alt(lambda e: f"recovered: {e}")
        ) == Failure("recovered: cannot parse 'abc'")
        assert parse_int("-5").bind(validate_positive).lash(lambda e: Success(0)) == Success(0)

        # do-notation: combine several Results, short-circuiting on the first failure.
        db = {"a": 10, "b": 20, "c": 30}

        def lookup(key):
            return Success(db[key]) if key in db else Failure(f"missing: {key}")

        assert Result.do(
            x + y + z for x in lookup("a") for y in lookup("b") for z in lookup("c")
        ) == Success(60)
        assert Result.do(
            x + y for x in lookup("a") for y in lookup("zzz")
        ) == Failure("missing: zzz")

        # structural pattern matching routes the outcomes.
        routed = []
        for c in (Success(10), Success(42), Failure("oops")):
            match c:
                case Success(10):
                    routed.append("ten")
                case Success(v):
                    routed.append(f"ok:{v}")
                case Failure(e):
                    routed.append(f"err:{e}")
        assert routed == ["ten", "ok:42", "err:oops"]

    def test_result_apply_constructors_and_unwrap_errors(self):
        """A user applies wrapped functions, builds Results via constructors, swaps,
        extracts values, and triggers UnwrapFailedError (with cause chaining)."""
        from returns.result import Result, Success, Failure
        from returns.primitives.exceptions import UnwrapFailedError

        # applicative apply propagates the first failure.
        assert Success(3).apply(Success(lambda x: x + 7)) == Success(10)
        assert Failure("e").apply(Success(lambda x: x)) == Failure("e")
        assert Success(3).apply(Failure("f")) == Failure("f")

        # constructors, swap, value extraction.
        assert Result.from_value(42) == Success(42)
        assert Result.from_failure("err") == Failure("err")
        assert Result.from_result(Success(1)) == Success(1)
        assert Success(1).swap() == Failure(1)
        assert Failure("x").swap() == Success("x")
        assert Success(10).value_or(0) == 10
        assert Failure("e").value_or(0) == 0
        assert Success(5).unwrap() == 5
        assert Failure("e").failure() == "e"

        # unwrap/failure on the wrong side raise UnwrapFailedError; halted_container
        # is the offending container, and a wrapped Exception chains as __cause__.
        bad = Failure("e")
        with pytest.raises(UnwrapFailedError) as plain:
            bad.unwrap()
        assert plain.value.halted_container is bad
        with pytest.raises(UnwrapFailedError):
            Success(1).failure()
        original = ValueError("boom")
        with pytest.raises(UnwrapFailedError) as chained:
            Failure(original).unwrap()
        assert chained.value.__cause__ is original

    def test_safe_and_attempt_decorators(self):
        """A user wraps unsafe functions with @safe (bare + scoped) and @attempt."""
        from returns.result import Success, Failure, safe, attempt

        @safe
        def parse_json(s: str) -> dict:
            return json.loads(s)

        assert parse_json('{"k": "v"}').map(lambda d: d["k"]) == Success("v")
        failed = parse_json("not json")
        assert isinstance(failed, Failure)
        assert isinstance(failed.failure(), json.JSONDecodeError)

        @safe(exceptions=(ValueError,))
        def strict(s: str) -> int:
            return int(s)

        assert strict("42") == Success(42)
        assert isinstance(strict("abc").failure(), ValueError)

        @safe(exceptions=(ValueError,))
        def only_value_error(x):
            raise TypeError("nope")

        with pytest.raises(TypeError):
            only_value_error(1)

        @attempt
        def process(x: int) -> str:
            if x < 0:
                raise ValueError("negative")
            return str(x)

        assert process(5) == Success("5")
        assert process(-1) == Failure(-1)  # wraps the INPUT, not the exception


# ============================================================================
# Maybe — optional values
# ============================================================================


class TestMaybeProgram:
    """Maybe container used as a real optional-handling pipeline."""

    def test_maybe_pipeline_do_notation_and_matching(self):
        """A user chains lookups (Nothing short-circuits), composes via do-notation
        (relying on the Nothing singleton), and routes outcomes by matching."""
        from returns.maybe import Maybe, Some, Nothing

        def safe_head(lst):
            return Some(lst[0]) if lst else Nothing

        def safe_get(d, key):
            return Some(d[key]) if key in d else Nothing

        data = {"users": [{"name": "Alice"}]}
        assert (
            safe_get(data, "users").bind(safe_head)
            .bind(lambda u: safe_get(u, "name")).map(str.upper)
        ) == Some("ALICE")
        assert safe_get(data, "missing").bind(safe_head).map(str.upper) is Nothing

        assert Maybe.do(x + y for x in Some(10) for y in Some(20)) == Some(30)
        assert Maybe.do(x + y for x in Some(10) for y in Nothing) is Nothing
        assert Nothing is Maybe.empty

        routed = []
        for c in (Some("hello"), Some("world"), Nothing):
            match c:
                case Some("hello"):
                    routed.append("greeting")
                case Some(v):
                    routed.append(f"some:{v}")
                case _:
                    routed.append("nothing")
        assert routed == ["greeting", "some:world", "nothing"]

    def test_maybe_optional_recovery_and_decorator(self):
        """A user uses bind_optional/or_else_call/from_optional, boolean semantics,
        lash recovery, and the @maybe decorator."""
        from returns.maybe import Maybe, Some, Nothing, maybe

        assert Some(5).bind_optional(lambda x: x * 2 if x > 0 else None) == Some(10)
        assert Some(-1).bind_optional(lambda x: x * 2 if x > 0 else None) is Nothing
        assert Some(5).or_else_call(lambda: 0) == 5
        assert Nothing.or_else_call(lambda: 42) == 42
        assert Maybe.from_optional(42) == Some(42)
        assert Maybe.from_optional(None) is Nothing
        assert Maybe.from_value(None) == Some(None)
        assert bool(Some(0)) is True and bool(Some(None)) is True and bool(Nothing) is False
        assert Nothing.lash(lambda _: Some("default")) == Some("default")
        assert Some(5).lash(lambda _: Some("default")) == Some(5)

        @maybe
        def find_item(items, predicate):
            for item in items:
                if predicate(item):
                    return item
            return None

        assert find_item([1, 2, 3], lambda x: x > 2) == Some(3)
        assert find_item([1, 2, 3], lambda x: x > 10) is Nothing


# ============================================================================
# IO / IOResult — impure computations
# ============================================================================


class TestIOProgram:
    """IO and IOResult used as a real impure pipeline."""

    def test_io_and_ioresult_core_pipeline(self):
        """A user composes IO (map/bind/do/constructors/@impure) and runs an IOResult
        pipeline with the full operation surface (swap, IO-wrapped extraction, binds)."""
        from returns.io import IO, IOResult, IOSuccess, IOFailure, impure
        from returns.result import Success, Failure
        from returns.primitives.exceptions import UnwrapFailedError

        assert IO(1).map(lambda x: x + 1).bind(lambda x: IO(x * 10)) == IO(20)
        assert IO.do(a + b for a in IO(10) for b in IO(20)) == IO(30)
        assert IO.from_value(5) == IO(5) and IO.from_io(IO(42)) == IO(42)

        @impure
        def read_config():
            return {"debug": True}

        assert read_config() == IO({"debug": True})

        def fetch(uid: int) -> IOResult[dict, str]:
            return IOSuccess({"id": uid}) if uid > 0 else IOFailure("invalid uid")

        def email(user: dict) -> IOResult[str, str]:
            return IOSuccess(user["email"]) if "email" in user else IOFailure("no email")

        assert fetch(1).bind(email) == IOFailure("no email")
        assert fetch(-1).bind(email) == IOFailure("invalid uid")
        assert IOSuccess({"email": "a@b.c"}).bind_result(
            lambda u: Success(u["email"]) if "email" in u else Failure("no email")
        ) == IOSuccess("a@b.c")

        assert IOSuccess(1).swap() == IOFailure(1) and IOFailure("e").swap() == IOSuccess("e")
        assert IOSuccess(42).unwrap() == IO(42)
        assert IOFailure("err").failure() == IO("err")
        assert IOSuccess(10).value_or(0) == IO(10) and IOFailure("e").value_or(0) == IO(0)
        with pytest.raises(UnwrapFailedError):
            IOFailure("e").unwrap()
        assert IOFailure(1).alt(lambda e: e + 10) == IOFailure(11)
        assert IOSuccess(1).alt(lambda e: e + 10) == IOSuccess(1)
        assert IOFailure("err").lash(lambda e: IOSuccess("ok")) == IOSuccess("ok")
        assert IOSuccess("a").bind_io(lambda s: IO(s + "z")) == IOSuccess("az")
        assert IOSuccess(5).bind_ioresult(lambda x: IOSuccess(x + 1)) == IOSuccess(6)

    def test_ioresult_constructors_compose_safe_and_matching(self):
        """A user builds IOResult from every source, branches on the inner Result with
        compose_result, wraps failures with @impure_safe, and matches the inner Result."""
        from returns.io import IO, IOResult, IOSuccess, IOFailure, impure_safe
        from returns.result import Success
        from returns.unsafe import unsafe_perform_io

        assert IOResult.from_result(Success(1)) == IOSuccess(1)
        assert IOResult.from_value(1) == IOSuccess(1)
        assert IOResult.from_failure("e") == IOFailure("e")
        assert IOResult.from_io(IO(1)) == IOSuccess(1)
        assert IOResult.from_failed_io(IO("e")) == IOFailure("e")
        assert IOResult.from_typecast(IO(Success(1))) == IOSuccess(1)
        assert IOResult.from_ioresult(IOSuccess(1)) == IOSuccess(1)
        assert IO.from_ioresult(IOSuccess(1)) == IO(Success(1))

        def handle(inner):
            if isinstance(inner, Success):
                return IOSuccess(inner.unwrap() + 100)
            return IOSuccess("recovered:" + inner.failure())

        assert IOSuccess(2).compose_result(handle) == IOSuccess(102)
        assert IOFailure("x").compose_result(handle) == IOSuccess("recovered:x")

        @impure_safe
        def read_file(path: str) -> str:
            if path == "good.txt":
                return "contents"
            raise FileNotFoundError(path)

        assert read_file("good.txt") == IOSuccess("contents")
        failed = read_file("bad.txt")
        assert isinstance(failed, IOFailure)
        wrapped = unsafe_perform_io(failed.failure())
        assert isinstance(wrapped, FileNotFoundError) and wrapped.args == ("bad.txt",)

        routed = []
        for c in (IOSuccess(42.0), IOSuccess(10.0), IOFailure(50)):
            match c:
                case IOSuccess(Success(42.0)):
                    routed.append("forty-two")
                case IOSuccess(inner):
                    routed.append(f"ok:{inner.unwrap()}")
                case IOFailure(_):
                    routed.append("fail")
        assert routed == ["forty-two", "ok:10.0", "fail"]


# ============================================================================
# Base container protocol (repr/eq/hash/pickle)
# ============================================================================


class TestContainerProtocol:
    """The BaseContainer protocol shared by every container."""

    def test_repr_eq_hash_pickle(self):
        """A user inspects repr/str, compares/hashes, uses containers as dict keys,
        and round-trips them through pickle."""
        from returns.result import Success, Failure
        from returns.maybe import Some, Nothing
        from returns.io import IO, IOSuccess

        assert repr(Success(1)) == "<Success: 1>"
        assert repr(Failure("err")) == "<Failure: err>"
        assert repr(Some(42)) == "<Some: 42>"
        assert repr(Nothing) == "<Nothing>"
        assert repr(IO(1)) == "<IO: 1>"
        assert str(IOSuccess(1)) == "<IOResult: <Success: 1>>"

        assert Success(1) == Success(1) and Success(1) != Failure(1) and Success(1) != Success(2)
        assert hash(Success(1)) == hash(Success(1))
        d = {Success(1): "one", Failure("e"): "err"}
        assert d[Success(1)] == "one" and d[Failure("e")] == "err"

        for c in (Success(42), Failure("err"), Some(10), IO(5)):
            assert pickle.loads(pickle.dumps(c)) == c


# ============================================================================
# Synchronous combinators (pointfree, pipeline, converters, fold, functions, curry)
# ============================================================================


class TestSyncCombinators:
    """The point-free / pipeline / conversion / iteration / function utilities."""

    def test_pointfree_across_containers(self):
        """A user drives flow/pipe pipelines with the point-free surface across
        Result, Maybe, IO, and the reader containers (map_/bind/alt/lash/apply/cond/
        bimap/unify, the bind_* / compose_result family, and bind_context/modify_env)."""
        from returns.pointfree import (
            map_, bind, alt, lash, apply, cond, bimap, unify,
            bind_result, bind_io, bind_ioresult, compose_result, bind_optional,
            bind_context, modify_env,
        )
        from returns.pipeline import flow
        from returns.result import Result, Success, Failure
        from returns.maybe import Maybe, Some, Nothing
        from returns.io import IO, IOSuccess
        from returns.context import RequiresContext, RequiresContextResult

        assert flow(
            Success(5),
            map_(lambda x: x * 2),
            bind(lambda x: Success(x + 1) if x < 20 else Failure("too big")),
            map_(lambda x: f"result: {x}"),
        ) == Success("result: 11")
        assert flow(Failure("boom"), map_(lambda x: x * 2), alt(lambda e: f"h:{e}")) == Failure("h:boom")
        assert flow(Failure("err"), lash(lambda e: Success(f"rec:{e}"))) == Success("rec:err")

        double = map_(lambda x: x * 2)
        assert double(Success(5)) == Success(10) and double(Some(3)) == Some(6) and double(IO(7)) == IO(14)
        assert apply(Success(lambda x: x + 1))(Success(5)) == Success(6)
        assert apply(Some(lambda x: x * 2))(Some(3)) == Some(6)
        assert cond(Result, "yes", "no")(True) == Success("yes")
        assert cond(Result, "yes", "no")(False) == Failure("no")
        assert cond(Maybe, 42)(True) == Some(42) and cond(Maybe, 42)(False) is Nothing

        assert bimap(lambda x: x + 1, lambda e: e + 10)(Success(1)) == Success(2)
        assert bimap(lambda x: x + 1, lambda e: e + 10)(Failure(1)) == Failure(11)
        assert unify(lambda x: Success(x + 1))(Success(2)) == Success(3)
        assert bind_result(lambda x: Success(x + 1))(IOSuccess(2)) == IOSuccess(3)
        assert bind_io(lambda x: IO(x + 1))(IOSuccess(2)) == IOSuccess(3)
        assert bind_ioresult(lambda x: IOSuccess(x + 1))(IOSuccess(2)) == IOSuccess(3)
        assert compose_result(lambda res: IOSuccess(res.unwrap() + 1))(IOSuccess(2)) == IOSuccess(3)
        assert bind_optional(lambda x: x + 1 if x else None)(Some(2)) == Some(3)
        assert bind_optional(lambda x: x + 1 if x else None)(Some(0)) is Nothing

        # reader-track pointfree wrappers (containers evaluate synchronously here).
        assert bind_context(lambda x: RequiresContext.from_value(x * 9))(
            RequiresContextResult.from_value(2)
        )("d") == Success(18)
        assert modify_env(lambda e: e + 10)(
            RequiresContextResult(lambda d: Success(d * 2))
        )(5) == Success(30)

    def test_pipeline_flow_pipe_is_successful_and_managed(self):
        """A user composes with flow/pipe, checks success state across container
        types, and manages a resource lifecycle (acquire/use/release)."""
        from returns.pipeline import flow, pipe, is_successful, managed
        from returns.result import Success, Failure, Result, safe
        from returns.maybe import Some, Nothing
        from returns.io import IOResult, IOSuccess, IOFailure

        @safe
        def parse(s: str) -> int:
            return int(s)

        assert flow(
            "42", parse,
            lambda r: r.map(lambda x: x * 2),
            lambda r: r.bind(lambda x: Success(x + 1) if x < 100 else Success(99)),
            lambda r: r.value_or(-1),
        ) == 85
        assert pipe(int, lambda x: x * 2, str)("5") == "10"

        assert [
            is_successful(c)
            for c in (Success(1), Failure(1), Some(1), Nothing, IOSuccess(1), IOFailure(1))
        ] == [True, False, True, False, True, False]

        events: list = []

        def use_ok(v: str) -> IOResult[str, str]:
            events.append(f"use:{v}")
            return IOSuccess("used")

        def use_fail(v: str) -> IOResult[str, str]:
            events.append(f"use:{v}")
            return IOFailure("use failed")

        def release_ok(v: str, r: Result[str, str]) -> IOResult[None, str]:
            events.append(f"release:{v}:{r}")
            return IOSuccess(None)

        def release_fail(v: str, r: Result[str, str]) -> IOResult[None, str]:
            return IOFailure("release failed")

        events.clear()
        assert managed(use_ok, release_ok)(IOSuccess("res")) == IOSuccess("used")
        assert events == ["use:res", f"release:res:{Success('used')}"]
        assert managed(use_ok, release_fail)(IOSuccess("res")) == IOFailure("release failed")
        events.clear()
        assert managed(use_fail, release_ok)(IOSuccess("res")) == IOFailure("use failed")
        assert events == ["use:res", f"release:res:{Failure('use failed')}"]
        assert managed(use_fail, release_fail)(IOSuccess("res")) == IOFailure("release failed")
        for u in (use_ok, use_fail):
            for rel in (release_ok, release_fail):
                events.clear()
                assert managed(u, rel)(IOFailure("acquire failed")) == IOFailure("acquire failed")
                assert events == []

    def test_converters_and_fold(self):
        """A user converts between Result/Maybe (and flattens), then aggregates
        iterables of containers with Fold.loop/collect/collect_all."""
        from returns.converters import result_to_maybe, maybe_to_result, flatten
        from returns.pipeline import flow
        from returns.pointfree import map_
        from returns.result import Success, Failure
        from returns.maybe import Some, Nothing
        from returns.io import IO
        from returns.iterables import Fold

        assert result_to_maybe(Success(42)) == Some(42)
        assert result_to_maybe(Failure("e")) is Nothing
        assert result_to_maybe(Success(None)) == Some(None)
        assert maybe_to_result(Some(42)) == Success(42)
        assert maybe_to_result(Nothing) == Failure(None)
        assert maybe_to_result(Nothing, "custom") == Failure("custom")
        assert flatten(Success(Success(42))) == Success(42)
        assert flatten(Success(Failure("inner"))) == Failure("inner")
        assert flatten(Failure(Failure("x"))) == Failure(Failure("x"))
        assert flatten(Some(Some(5))) == Some(5)
        assert flatten(IO(IO(3))) == IO(3)
        assert flow(Success(10), result_to_maybe, map_(lambda x: x * 2), maybe_to_result) == Success(20)
        assert flow(Failure("e"), result_to_maybe, map_(lambda x: x * 2), maybe_to_result) == Failure(None)

        assert Fold.loop(
            [Success(1), Success(2), Success(3)], Success(0), lambda x: lambda acc: acc + x
        ) == Success(6)
        assert Fold.loop(
            [Some(1), Some(2), Some(3)], Some(0), lambda x: lambda acc: acc + x
        ) == Some(6)
        assert Fold.collect([Success(1), Success(2), Success(3)], Success(())) == Success((1, 2, 3))
        assert Fold.collect([Success(1), Failure("e"), Success(3)], Success(())) == Failure("e")
        assert Fold.collect([Some(1), Nothing, Some(3)], Some(())) is Nothing
        assert Fold.collect([IO(1), IO(2), IO(3)], IO(())) == IO((1, 2, 3))
        assert Fold.collect([], Success(())) == Success(())
        assert Fold.collect_all(
            [Success(1), Failure("a"), Success(3), Failure("b")], Success(())
        ) == Success((1, 3))
        assert Fold.collect_all([Failure("x"), Failure("y")], Success(())) == Success(())

    def test_functions_and_curry(self):
        """A user composes pure-function helpers and curries/partials functions."""
        from returns.functions import identity, compose, tap, untap, not_, raise_exception
        from returns.pipeline import flow
        from returns.result import Failure
        from returns.curry import curry, partial
        from inspect import getdoc

        assert flow(42, identity, identity) == 42
        assert compose(lambda x: x + 1, lambda x: x * 2)(5) == 12
        log: list = []
        assert tap(log.append)(42) == 42
        assert untap(log.append)(7) is None
        assert log == [42, 7]
        is_odd = not_(lambda x: x % 2 == 0)
        assert is_odd(3) is True and is_odd(4) is False
        with pytest.raises(ValueError):
            Failure(ValueError("boom")).alt(raise_exception)

        @curry
        def add3(a: int, b: int, c: int) -> int:
            return a + b + c

        assert add3(1)(2)(3) == 6 and add3(1, 2)(3) == 6 and add3(1)(2, 3) == 6 and add3(1, 2, 3) == 6

        @curry
        def greet(greeting: str, name: str) -> str:
            return f"{greeting}, {name}!"

        assert greet(greeting="Hello")(name="World") == "Hello, World!"
        assert greet(name="Alice", greeting="Hi") == "Hi, Alice!"

        @curry
        def kwonly(*args: int, by: int) -> tuple:
            return (*args, by)

        assert kwonly(1, 2, 3)(by=10) == (1, 2, 3, 10) and kwonly(by=10) == (10,)

        @curry
        def documented(a: int, b: int) -> int:
            """Add two numbers."""
            return a + b

        first = documented(1)
        assert first(2) == 3 and first(5) == 6  # earlier partial not mutated
        assert getdoc(documented) == "Add two numbers."

        @curry
        def needs_two(a: int, b: int) -> int:
            return a + b

        with pytest.raises(TypeError):
            needs_two(1, 2, 3)
        with pytest.raises(TypeError):
            needs_two(1)(2)(3)
        with pytest.raises(TypeError):
            needs_two(c=1)

        @curry
        def sum_all(*args: int) -> int:
            return sum(args)

        assert sum_all() == 0 and sum_all(1, 2, 3) == 6
        with pytest.raises(TypeError):
            sum_all(1)(2)  # *args cannot be partially applied

        def add(a: int, b: int) -> int:
            return a + b

        assert partial(add, 5)(3) == 8


# ============================================================================
# RequiresContext family — dependency injection
# ============================================================================


class TestReaderPrograms:
    """The RequiresContext* readers used as dependency-injection programs."""

    def test_requires_context_di_program(self):
        """A user builds a context-dependent program with map/apply/bind/modify_env,
        constants via from_value/no_args, and dependency access via ask."""
        from returns.context import RequiresContext

        get_host = RequiresContext(lambda c: c["host"])
        get_port = RequiresContext(lambda c: c["port"])
        url = get_port.apply(get_host.map(lambda h: lambda p: f"http://{h}:{p}"))
        assert url({"host": "localhost", "port": 8080}) == "http://localhost:8080"

        def greet(name: str) -> RequiresContext:
            return RequiresContext(lambda style: f"{style} {name}!")

        assert RequiresContext.from_value("Bob").bind(greet)("Hello") == "Hello Bob!"
        assert RequiresContext(lambda x: x * 2).modify_env(lambda d: d + 10)(5) == 30
        assert RequiresContext.from_value(42)(RequiresContext.no_args) == 42
        assert RequiresContext.ask()(5) == 5

    def test_requires_context_result_program(self):
        """A user runs a context+Result DI program over its full method surface."""
        from returns.context import RequiresContext, RequiresContextResult
        from returns.result import Success, Failure

        def lookup(name: str) -> RequiresContextResult:
            def _inner(db):
                return Success(db[name]) if name in db else Failure(f"not found: {name}")
            return RequiresContextResult(_inner)

        db = {"alice": 42}
        assert lookup("alice").map(lambda a: a + 1)(db) == Success(43)
        assert lookup("x").lash(lambda e: RequiresContextResult.from_value(-1))(db) == Success(-1)
        assert lookup("x").alt(lambda e: f"ERR:{e}")(db) == Failure("ERR:not found: x")
        assert RequiresContextResult.from_value(10).bind_result(
            lambda x: Success(x * 2) if x > 5 else Failure("small")
        )("d") == Success(20)

        assert RequiresContextResult.from_value(1).swap()("d") == Failure(1)
        assert RequiresContextResult.from_failure("e").swap()("d") == Success("e")
        assert RequiresContextResult.from_result(Success(9))("d") == Success(9)
        assert RequiresContextResult.ask()("deps") == Success("deps")
        assert RequiresContextResult.from_value(99)(RequiresContextResult.no_args) == Success(99)
        assert RequiresContextResult.from_value(10).bind(
            lambda x: RequiresContextResult.from_value(x + 1)
        )("d") == Success(11)
        assert RequiresContextResult.from_value(3).apply(
            RequiresContextResult.from_value(lambda x: x + 5)
        )("d") == Success(8)
        assert RequiresContextResult.from_value(2).bind_context(
            lambda x: RequiresContext.from_value(x * 100)
        )("d") == Success(200)
        assert RequiresContextResult.from_value(2).bind_context_result(
            lambda x: RequiresContextResult.from_value(x * 3)
        )("d") == Success(6)
        assert RequiresContextResult(lambda d: Success(d * 2)).modify_env(lambda e: e + 10)(5) == Success(30)

    def test_requires_context_ioresult_program(self):
        """A user runs a context+IO+Result DI program over its full surface."""
        from returns.context import RequiresContext, RequiresContextIOResult
        from returns.io import IO, IOSuccess, IOFailure
        from returns.result import Success

        assert RequiresContextIOResult.from_value(42)("any") == IOSuccess(42)
        assert RequiresContextIOResult.from_failure("err")("d") == IOFailure("err")
        assert RequiresContextIOResult.from_value(10).map(lambda x: x * 2)("d") == IOSuccess(20)
        assert RequiresContextIOResult.from_failure("err").lash(
            lambda e: RequiresContextIOResult.from_value("rec")
        )("d") == IOSuccess("rec")
        assert RequiresContextIOResult.from_failure("e").alt(lambda x: x + "!")("d") == IOFailure("e!")

        assert RequiresContextIOResult.from_value(2).bind(
            lambda x: RequiresContextIOResult.from_value(x + 3)
        )("d") == IOSuccess(5)
        assert RequiresContextIOResult.from_value(2).bind_result(lambda x: Success(x + 3))("d") == IOSuccess(5)
        assert RequiresContextIOResult.from_value(2).bind_io(lambda x: IO(x + 3))("d") == IOSuccess(5)
        assert RequiresContextIOResult.from_value(2).bind_ioresult(lambda x: IOSuccess(x + 3))("d") == IOSuccess(5)
        assert RequiresContextIOResult.from_value(2).bind_context(
            lambda x: RequiresContext.from_value(x * 10)
        )("d") == IOSuccess(20)
        assert RequiresContextIOResult.from_value(2).compose_result(
            lambda res: RequiresContextIOResult.from_value(res.unwrap() + 1)
        )("d") == IOSuccess(3)

        assert RequiresContextIOResult.from_result(Success(1))("d") == IOSuccess(1)
        assert RequiresContextIOResult.from_io(IO(1))("d") == IOSuccess(1)
        assert RequiresContextIOResult.from_failed_io(IO("e"))("d") == IOFailure("e")
        assert RequiresContextIOResult.from_ioresult(IOSuccess(1))("d") == IOSuccess(1)
        assert RequiresContextIOResult.ask()("deps") == IOSuccess("deps")
        assert RequiresContextIOResult.from_value(1).swap()("d") == IOFailure(1)
        assert RequiresContextIOResult.from_value(3).apply(
            RequiresContextIOResult.from_value(lambda x: x + 5)
        )("d") == IOSuccess(8)
        assert RequiresContextIOResult(lambda d: IOSuccess(d * 2)).modify_env(lambda e: e + 10)(5) == IOSuccess(30)

    def test_requires_context_future_result_program(self):
        """A user runs a context+Future+Result async DI program over its full surface."""
        import anyio
        from returns.context import RequiresContextFutureResult
        from returns.future import Future, FutureResult
        from returns.io import IO, IOSuccess, IOFailure
        from returns.result import Success

        def cfg(key: str) -> RequiresContextFutureResult:
            def _inner(config):
                if key in config:
                    return FutureResult.from_value(config[key])
                return FutureResult.from_failure(f"missing: {key}")
            return RequiresContextFutureResult(_inner)

        config = {"host": "localhost"}
        assert anyio.run(cfg("host").map(str.upper)(config).awaitable) == IOSuccess("LOCALHOST")
        assert anyio.run(cfg("nope")(config).awaitable) == IOFailure("missing: nope")
        assert anyio.run(RequiresContextFutureResult.from_value(1).swap()("d").awaitable) == IOFailure(1)
        assert anyio.run(
            RequiresContextFutureResult.from_failure("err")
            .lash(lambda e: RequiresContextFutureResult.from_value("rec"))("d").awaitable
        ) == IOSuccess("rec")

        rcfr = RequiresContextFutureResult
        assert anyio.run(rcfr.from_value(2).bind(lambda x: rcfr.from_value(x + 3))("d").awaitable) == IOSuccess(5)
        assert anyio.run(rcfr.from_value(2).bind_result(lambda x: Success(x + 3))("d").awaitable) == IOSuccess(5)
        assert anyio.run(rcfr.from_value(2).bind_io(lambda x: IO(x + 3))("d").awaitable) == IOSuccess(5)
        assert anyio.run(rcfr.from_value(2).bind_ioresult(lambda x: IOSuccess(x + 3))("d").awaitable) == IOSuccess(5)
        assert anyio.run(rcfr.from_value(2).bind_future(lambda x: Future.from_value(x * 2))("d").awaitable) == IOSuccess(4)
        assert anyio.run(rcfr.from_value(2).bind_future_result(lambda x: FutureResult.from_value(x * 2))("d").awaitable) == IOSuccess(4)

        async def plus100(x: int) -> int:
            return x + 100

        async def times5(x: int) -> RequiresContextFutureResult:
            return rcfr.from_value(x * 5)

        assert anyio.run(rcfr.from_value(2).bind_awaitable(plus100)("d").awaitable) == IOSuccess(102)
        assert anyio.run(rcfr.from_value(2).bind_async(times5)("d").awaitable) == IOSuccess(10)
        assert anyio.run(rcfr.from_failure("e").alt(lambda x: x + "!")("d").awaitable) == IOFailure("e!")
        assert anyio.run(rcfr.from_value(3).apply(rcfr.from_value(lambda x: x + 1))("d").awaitable) == IOSuccess(4)
        assert anyio.run(
            rcfr.from_value(2).compose_result(lambda res: rcfr.from_value(res.unwrap() + 1))("d").awaitable
        ) == IOSuccess(3)
        assert anyio.run(rcfr.from_result(Success(1))("d").awaitable) == IOSuccess(1)
        assert anyio.run(rcfr.from_io(IO(1))("d").awaitable) == IOSuccess(1)
        assert anyio.run(rcfr.from_ioresult(IOSuccess(1))("d").awaitable) == IOSuccess(1)
        assert anyio.run(rcfr.from_future(Future.from_value(1))("d").awaitable) == IOSuccess(1)
        assert anyio.run(rcfr.from_future_result(FutureResult.from_value(1))("d").awaitable) == IOSuccess(1)
        assert anyio.run(rcfr.ask()("deps").awaitable) == IOSuccess("deps")
        assert anyio.run(
            rcfr(lambda d: FutureResult.from_value(d * 2)).modify_env(lambda e: e + 10)(5).awaitable
        ) == IOSuccess(30)


# ============================================================================
# Future / FutureResult — async composition
# ============================================================================


class TestAsyncPrograms:
    """Future and FutureResult used as real async programs."""

    def test_future_program(self):
        """A user composes a Future (map/bind/bind_io/bind_awaitable/bind_async/apply,
        constructors, async do-notation) and the @future/@asyncify decorators."""
        import anyio
        from returns.future import Future, FutureResult, future, asyncify, async_identity
        from returns.io import IO
        from returns.result import Success

        assert anyio.run(
            Future.from_value(5).map(lambda x: x * 2).bind(lambda x: Future.from_value(x + 1)).awaitable
        ) == IO(11)
        assert anyio.run(Future.from_value(3).bind_io(lambda x: IO(x * 10)).awaitable) == IO(30)
        assert anyio.run(Future.from_value(3).apply(Future.from_value(lambda x: x + 10)).awaitable) == IO(13)
        assert anyio.run(Future.from_io(IO(7)).awaitable) == IO(7)
        assert anyio.run(Future.from_future(Future.from_value(99)).awaitable) == IO(99)
        assert anyio.run(Future.from_future_result(FutureResult.from_value(5)).awaitable) == IO(Success(5))

        async def add_one(x: int) -> int:
            return x + 1

        async def async_double(x: int) -> Future:
            return Future.from_value(x * 2)

        assert anyio.run(Future.from_value(5).bind_awaitable(add_one).awaitable) == IO(6)
        assert anyio.run(Future.from_value(5).bind_async(async_double).awaitable) == IO(10)

        async def _do():
            return await Future.do(
                a + b async for a in Future.from_value(10) async for b in Future.from_value(20)
            ).awaitable()

        assert anyio.run(_do) == IO(30)

        @future
        async def compute(x: int) -> int:
            return x + 1

        @asyncify
        def double(x: int) -> int:
            return x * 2

        assert anyio.run(compute(1).awaitable) == IO(2)
        assert anyio.run(double, 5) == 10
        assert anyio.run(async_identity, 42) == 42

    def test_future_result_program(self):
        """A user runs a fallible async pipeline (FutureResult) over its full bind
        surface, every constructor, and the @future_safe decorator."""
        import anyio
        from returns.future import Future, FutureResult, FutureSuccess, FutureFailure, future_safe
        from returns.io import IO, IOSuccess, IOFailure
        from returns.result import Success, Failure
        from returns.unsafe import unsafe_perform_io

        assert anyio.run(
            FutureResult.from_value(5).map(lambda x: x * 2)
            .bind_result(lambda x: Success(x + 1)).bind(lambda x: FutureResult.from_value(x * 3)).awaitable
        ) == IOSuccess(33)
        assert anyio.run(
            FutureResult.from_failure("err").map(lambda x: x * 2)
            .bind(lambda x: FutureResult.from_value(x)).awaitable
        ) == IOFailure("err")
        assert anyio.run(FutureResult.from_failure(1).alt(lambda e: e + 10).awaitable) == IOFailure(11)
        assert anyio.run(
            FutureResult.from_failure("err").lash(lambda e: FutureResult.from_value("rec")).awaitable
        ) == IOSuccess("rec")

        assert anyio.run(FutureResult.from_value(1).swap().awaitable) == IOFailure(1)
        assert anyio.run(FutureResult.from_value(5).bind_io(lambda x: IO(x + 10)).awaitable) == IOSuccess(15)
        assert anyio.run(FutureResult.from_value(5).bind_ioresult(lambda x: IOSuccess(x + 1)).awaitable) == IOSuccess(6)
        assert anyio.run(FutureResult.from_value(5).bind_future(lambda x: Future.from_value(x * 2)).awaitable) == IOSuccess(10)

        async def plus_one(x: int) -> int:
            return x + 1

        async def times_ten(x: int) -> FutureResult:
            return FutureResult.from_value(x * 10)

        assert anyio.run(FutureResult.from_value(5).bind_awaitable(plus_one).awaitable) == IOSuccess(6)
        assert anyio.run(FutureResult.from_value(5).bind_async(times_ten).awaitable) == IOSuccess(50)
        assert anyio.run(FutureResult.from_value(3).apply(FutureResult.from_value(lambda x: x + 1)).awaitable) == IOSuccess(4)
        assert anyio.run(
            FutureResult.from_value(2).compose_result(lambda res: FutureResult.from_value(res.unwrap() + 100)).awaitable
        ) == IOSuccess(102)

        assert anyio.run(FutureResult.from_result(Success(42)).awaitable) == IOSuccess(42)
        assert anyio.run(FutureResult.from_result(Failure("e")).awaitable) == IOFailure("e")
        assert anyio.run(FutureSuccess(1).awaitable) == IOSuccess(1)
        assert anyio.run(FutureFailure("e").awaitable) == IOFailure("e")
        assert anyio.run(FutureResult.from_io(IO(1)).awaitable) == IOSuccess(1)
        assert anyio.run(FutureResult.from_failed_io(IO("e")).awaitable) == IOFailure("e")
        assert anyio.run(FutureResult.from_ioresult(IOSuccess(1)).awaitable) == IOSuccess(1)
        assert anyio.run(FutureResult.from_future(Future.from_value(1)).awaitable) == IOSuccess(1)
        assert anyio.run(FutureResult.from_failed_future(Future.from_value("e")).awaitable) == IOFailure("e")
        assert anyio.run(FutureResult.from_typecast(Future.from_value(Success(7))).awaitable) == IOSuccess(7)

        @future_safe
        async def divide(a: int, b: int) -> float:
            return a / b

        assert anyio.run(divide(10, 2).awaitable) == IOSuccess(5.0)
        failed = anyio.run(divide(10, 0).awaitable)
        assert isinstance(failed, IOFailure)
        assert isinstance(unsafe_perform_io(failed.failure()), ZeroDivisionError)

    def test_pointfree_async_and_reawaitable(self):
        """A user drives Futures with the point-free async binds, reuses a single Future
        by deriving two containers from it, and re-awaits with the ReAwaitable primitive."""
        import anyio
        from returns.pointfree import bind_future, bind_awaitable, bind_async
        from returns.future import Future, FutureResult, future
        from returns.io import IO, IOSuccess
        from returns.primitives.reawaitable import ReAwaitable, reawaitable

        # bind_future is part of the FutureResult interface (instruction.md §6).
        assert anyio.run(
            bind_future(lambda x: Future.from_value(x + 1))(FutureResult.from_value(2)).awaitable
        ) == IOSuccess(3)

        async def plus_one(x: int) -> int:
            return x + 1

        async def times_three(x: int) -> Future:
            return Future.from_value(x * 3)

        assert anyio.run(bind_awaitable(plus_one)(Future.from_value(2)).awaitable) == IO(3)
        assert anyio.run(bind_async(times_three)(Future.from_value(2)).awaitable) == IO(6)

        # A single Future can be reused: deriving two containers from it via .map and
        # running each awaits the underlying coroutine more than once. The coroutine
        # body must still run exactly once (its result is reused), so calls == [1].
        calls: list = []

        @future
        async def make() -> int:
            calls.append(1)
            return 99

        source = make()
        plus = source.map(lambda x: x + 1)
        minus = source.map(lambda x: x - 1)
        assert anyio.run(plus.awaitable) == IO(100)
        assert anyio.run(minus.awaitable) == IO(98)
        assert calls == [1]

        # The same guarantee is available directly as a reusable primitive: a ReAwaitable
        # wrapper may be awaited repeatedly but runs its coroutine once, and @reawaitable
        # gives every CALL its own independently re-awaitable result.
        class_calls: list = []
        deco_calls: list = []

        async def _main():
            async def coro():
                class_calls.append(1)
                return 99

            wrapped = ReAwaitable(coro())

            @reawaitable
            async def compute(x: int) -> int:
                deco_calls.append(x)
                return x * 2

            first = compute(5)
            second = compute(6)
            return (
                (await wrapped), (await wrapped),
                (await first), (await first),
                (await second), (await second),
            )

        assert anyio.run(_main) == (99, 99, 10, 10, 12, 12)
        assert class_calls == [1] and deco_calls == [5, 6]


# ============================================================================
# Library-authoring primitives (trampolines, HKT) and extraction utilities
# ============================================================================


class TestLibraryAuthoring:
    """Stack-safe recursion and the HKT machinery for custom containers."""

    def test_trampoline_computes_and_is_stack_safe(self):
        """A user expresses accumulating recursion as trampolines: correct results
        AND no stack overflow at depths that would otherwise raise RecursionError."""
        from returns.trampolines import Trampoline, trampoline

        @trampoline
        def factorial(n: int, acc: int = 1):
            return acc if n <= 1 else Trampoline(factorial, n - 1, acc * n)

        @trampoline
        def fib_sum(n: int, a: int = 0, b: int = 1) -> int:
            return a if n <= 0 else Trampoline(fib_sum, n - 1, b, a + b)

        @trampoline
        def count_down(n: int) -> int:
            return 0 if n <= 0 else Trampoline(count_down, n - 1)

        assert factorial(10) == 3628800
        assert fib_sum(10) == 55
        assert count_down(100_000) == 0  # would RecursionError without trampolining

    def test_hkt_custom_container(self):
        """A user authors a custom container that participates in the HKT machinery:
        a SupportsKind1 subclass plus a generic @kinded function that uses dekind to
        recover the concrete type. The container manages its own storage, so the test
        depends only on the public HKT API — not on any returns-internal attribute."""
        from returns.primitives.hkt import SupportsKind1, kinded, dekind

        class Box(SupportsKind1["Box", int]):
            def __init__(self, value: int) -> None:
                self._value = value

            def __eq__(self, other: object) -> bool:
                return isinstance(other, Box) and self._value == other._value

            def map(self, function):
                return Box(function(self._value))

        @kinded
        def double(container):
            return dekind(container).map(lambda x: x * 2)

        assert double(Box(5)) == Box(10) and double(Box(5)) != Box(11)
        box = Box(3)
        assert dekind(box) is box  # dekind is a runtime no-op


class TestExtractionUtilities:
    """User-facing extraction utilities over unwrappable containers."""

    def test_partition_and_unwrap_or_failure(self):
        """A user splits results with partition and extracts either side with
        unwrap_or_failure (IO-wrapped for IOResult)."""
        from returns.methods.partition import partition
        from returns.methods.unwrap_or_failure import unwrap_or_failure
        from returns.result import Success, Failure
        from returns.io import IO, IOSuccess, IOFailure

        successes, failures = partition([Success(1), Failure("a"), Success(3), Failure("b")])
        assert successes == [1, 3] and failures == ["a", "b"]
        assert partition([]) == ([], [])
        assert partition([Success(1), Success(2)]) == ([1, 2], [])

        assert unwrap_or_failure(Success(42)) == 42
        assert unwrap_or_failure(Failure("err")) == "err"
        assert unwrap_or_failure(IOSuccess(1)) == IO(1)
        assert unwrap_or_failure(IOFailure("e")) == IO("e")


# ============================================================================
# Capstone — a realistic multi-container application
# ============================================================================


class TestCapstone:
    """A realistic program spanning safe/Result/Maybe/pointfree/Fold/context."""

    def test_validation_and_collection_workflow(self):
        """Validate raw inputs with @safe, convert to Maybe and back, look records up
        through a context-dependent Result, and aggregate with Fold + is_successful."""
        from returns.result import safe, Success, Failure
        from returns.converters import result_to_maybe
        from returns.pipeline import flow, is_successful
        from returns.pointfree import map_
        from returns.maybe import Some, Nothing
        from returns.context import RequiresContextResult
        from returns.iterables import Fold

        @safe
        def validate_age(age_str: str) -> int:
            age = int(age_str)
            if age < 0 or age > 150:
                raise ValueError(f"invalid age: {age}")
            return age

        # @safe result -> Maybe -> pointfree map, on both paths.
        assert flow(validate_age("42"), result_to_maybe, map_(lambda x: x * 2)) == Some(84)
        assert flow(validate_age("bad"), result_to_maybe) is Nothing

        # context-dependent lookups aggregated with Fold.collect (short-circuit on miss).
        def fetch(item_id: int) -> RequiresContextResult:
            def _inner(dbase):
                return Success(dbase[item_id]) if item_id in dbase else Failure(f"not found: {item_id}")
            return RequiresContextResult(_inner)

        dbase = {1: "apple", 2: "banana", 3: "cherry"}
        assert Fold.collect([fetch(i)(dbase) for i in (1, 2, 3)], Success(())) == Success(("apple", "banana", "cherry"))
        assert Fold.collect([fetch(i)(dbase) for i in (1, 99)], Success(())) == Failure("not found: 99")

        # collect_all keeps the valid ages; is_successful flags each input.
        results = [validate_age(s) for s in ("25", "30", "bad", "45")]
        assert Fold.collect_all(results, Success(())) == Success((25, 30, 45))
        assert [is_successful(r) for r in results] == [True, True, False, True]
