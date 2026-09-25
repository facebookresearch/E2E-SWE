# A reactive dataflow library (C++)

## Overview

This task asks you to build the core of a small **reactive dataflow** library in C++ —
the kind of machinery that sits underneath a spreadsheet, a build system, or a UI
data-binding layer. The central idea is easy to state: you describe values and how they
depend on one another, and the library keeps everything consistent for you. Change an
input, and every value derived from it is recomputed automatically, in the right order,
and anything watching is notified.

The interesting part — and what this task is really about — is getting the *propagation*
exactly right: which values recompute, when, how many times, and in what order. Your
library is exercised through its public interface: a grader assembles a dependency
graph, changes some inputs, and then checks both the resulting values and the exact
number of recomputations and notifications that happened along the way. Producing the
right final numbers is not enough on its own — the propagation behaviour itself has to
match.

## How the library is packaged

The library is **header-only** and targets **C++17**. Everything lives in the namespace
`ureact`, and a single umbrella header, `<ureact/ureact.hpp>`, should pull in the entire
public interface described below. Your `setup.sh` must run with no network access and
install the headers under `/usr/local/include`, so that a program can be built against
the library with `c++ -std=c++17 -I/usr/local/include`. Depend only on the C++ standard
library — no third-party packages, no threads, no GUI, no networking.

## Signals: values that change over time

The first building block is the **signal**, which represents a value that varies over
time. There are two flavours. A `ureact::var_signal<T>` is a mutable *input* — a value
you set directly. A `ureact::signal<T>` is a read-only handle to a value that is either
an input or, more often, computed from other signals; a `var_signal<T>` is usable
anywhere a `signal<T>` is expected.

Every reactive graph is rooted in a `ureact::context`, which owns the signals, events,
and observers created against it. You construct one directly — `ureact::context ctx;` —
and pass it to the factory calls (`make_var`, `make_source`) and to transactions.

You create an input by calling `make_var(context, initial_value)`, which hands back a
`var_signal<T>`. You read the current value of any signal with its `.get()` method, and
you push a new value into an input with the `<<=` operator, as in `temperature <<= 21`.

Derived signals are where things get interesting. The most convenient way to build one
is with ordinary operators: writing `ureact::signal<int> total = subtotal + tax;` gives
you a signal whose value always equals `subtotal.get() + tax.get()` and which keeps
itself up to date as those inputs change. Arithmetic and comparison operators work this
way. For anything more involved, use `lift`: `lift(source_signal, fn)` produces a new
signal whose value is `fn` applied to the source's value, recomputed whenever the source
changes. When a computation draws on several signals at once, bundle them together with
`with(...)` and hand the bundle to `lift` — for example `lift(with(a, b, c), fn)`, where
`fn` receives the three current values and returns the result.

## Observers: reacting to changes

Computing values is only half the story; often you want to *do something* when a value
changes. `observe(subject, callback)` registers `callback` to be invoked, with the new
value, every time `subject` changes. It returns a `ureact::observer` handle whose
lifetime controls the subscription — as long as you hold the handle, the callback stays
active — so the caller keeps it alive for as long as the observation should last.

## Events: things that happen

Not everything is a continuous value. The library also models **events** — discrete
occurrences such as a button press or a message arriving. An `event_source<E>` is where
events originate; you make one with `make_source<E>(context)` and fire an event by
calling `source.emit(value)` (the forms `source(value)` and `source << value` do the
same thing). A read-only view of a stream is an `events<E>`.

A family of adaptors lets you build stream pipelines and bridge back to signals:

`fold(stream, initial, fn)` returns a signal that maintains a running accumulator:
starting from `initial`, each event updates it as `accumulator = fn(event,
accumulator)`, and the signal always reflects the latest accumulator. `merge(a, b, ...)`
combines several streams into one that fires for every event from any of its sources.
`hold(stream, initial)` produces a signal that simply remembers the value carried by the
most recent event (taking `initial` until the first one arrives). `filter(stream,
predicate)` yields a stream that passes along only the events for which `predicate(event)`
is true, and `transform(stream, fn)` yields a stream of `fn(event)` for each incoming
event. Finally, `snapshot(trigger, target)` returns a signal that, each time the
`trigger` stream fires, samples and remembers the current value of the `target` signal,
ignoring changes to `target` that happen between triggers.

## Dynamic graphs: flatten

The dependency graph need not be fixed. A signal can even hold *another signal* as its
value, and `flatten(outer)` — where `outer` is a `signal<signal<T>>` — gives you a
`signal<T>` that always reflects the value of whichever inner signal `outer` currently
holds. Switching `outer` to a different inner signal re-points the dependency on the fly.

## Transactions: grouping changes

By default a change takes effect the moment you make it. Sometimes you want several
changes to land together as one coherent update. A `ureact::transaction` is an RAII
scope for exactly that: write `{ ureact::transaction t(ctx); /* several changes */ }`,
and the changes made inside are collected and applied together when the scope ends.

## How it must behave

The grader pins the following down through values **and** exact recompute / notification
counts. *What* must hold is listed here; the propagation strategy that achieves it is
yours to design.

- **It stays consistent.** After a change, every signal transitively derived from it
  reflects the new state, and the observers of anything that changed have been notified.
- **It is glitch-free.** No computation runs on a half-updated graph. A given signal is
  recomputed at most once in response to a single change, and only once its inputs have
  settled — so a value reachable by two different paths from the same input is never
  recomputed from a mix of old and new inputs.
- **It prunes by value.** Propagation only continues where a value actually changed,
  compared with `==`. Assigning an input a value equal to what it already holds does
  nothing at all; likewise, if a computed signal re-evaluates to the value it already
  had, the things depending on it are not recomputed.
- **It batches transactions.** Everything done inside a transaction takes effect as a
  single update when the outermost transaction scope closes; nested transactions do not
  trigger their own updates.
- **Events arrive within an update.** Every event is delivered to whatever depends on it
  within the update it belongs to, in the order it occurred.
- **It handles a changing graph.** `flatten` follows the inner signal currently
  selected; once a different inner signal is selected, the previous one no longer affects
  the result; and the result stays consistent even though the dependency graph was
  rewired underneath it.

## Notes

- Behaviour is deterministic and single-threaded, and the grader's comparisons are
  exact.
- Anything not spelled out here should follow naturally from the guarantees above.
