"""User-facing behaviour of ``wrapt.WeakFunctionProxy``: a weak reference proxy
that works with plain functions and bound methods, rebinding at call time and
raising ``ReferenceError`` (and firing an optional callback) once the instance
is gone."""

import gc

import pytest

import wrapt


class Worker:
    def __init__(self, label):
        self.label = label

    def describe(self):
        return f"worker:{self.label}"


def test_weak_proxy_forwards_calls_while_referent_alive():
    """While the referent is alive the proxy forwards calls and returns the
    result — for both a bound method (rebound at call time) and a plain
    function."""

    worker = Worker("A")
    assert wrapt.WeakFunctionProxy(worker.describe)() == "worker:A"

    def add(a, b):
        return a + b

    assert wrapt.WeakFunctionProxy(add)(2, 3) == 5


def test_weak_proxy_raises_and_fires_callback_after_instance_collected():
    """Once the bound instance is garbage collected, calling the proxy raises
    ReferenceError and the optional expiry callback is invoked with the proxy."""

    expired = []
    worker = Worker("B")
    proxy = wrapt.WeakFunctionProxy(
        worker.describe, callback=lambda p: expired.append(p)
    )

    del worker
    gc.collect()

    assert len(expired) == 1 and expired[0] is proxy
    with pytest.raises(ReferenceError):
        proxy()
