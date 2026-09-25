# jurigged

Build `jurigged`, a library for **live update of Python code**: a running program
redefines its own functions, methods and classes *in place*, so every object that
already exists — the function objects, classes, instances built earlier, closures,
and any held reference — picks up the new behaviour without being re-created and
without a restart. Redefinition works at the **source level**: parse a module into
definitions, diff an old version against a new one, and apply only the differences.

All names below import from the top-level package (`from jurigged import
make_recoder, registry, watch, Watcher, glob_filter, virtual_file`, plus
`__version__`). `OutOfSyncException` is in `jurigged.recode`; `redirect` and
`redirect_code` in `jurigged.rescript`. Lay the code out however you like as long
as these import paths resolve.

## Dependencies

The environment is **offline**: every dependency is **already installed** and there is
no network — do **not** install, download, or fetch anything. The project is installed
for you by a `setup.sh` that runs offline (an editable install against the pre-installed
dependencies). Build only against what is present.

The following runtime libraries are pre-installed and available to import:

- **`codefind`** — the low-level swap of a code object across every live function that
  uses it (`codefind.conform`, `codefind.get_functions`). The swap requires the old and
  new code objects to have the **same free variables**; a redefinition that would change
  them cannot be conformed directly and must be handled another way (see below).
- **`ovld`** — multiple dispatch, for dispatching behaviour over the different definition
  and object kinds (modules, functions, classes, code objects).
- **`watchdog`** — filesystem-watching primitives backing the `watch` / `Watcher` API.
- **`blessed`** — terminal formatting utilities.

## In-place redefinition

A redefinition mutates the existing object rather than rebinding a name:

- The function object stays the same (`old_ref is module.fn`) but runs the new
  body. The update reaches **every** live reference — aliases, default arguments,
  container entries, and all closures from one factory — not just the bound name.
- Redefining a method, or a whole class, updates instances created earlier: the
  class keeps its identity, changed methods take effect, new methods become
  callable on old instances, and instance state is preserved.
- A redefined closure factory re-syncs the new inner body onto closures already
  created from it, each keeping its captured values.
- A definition whose source is unchanged keeps its identity (reordering
  definitions in a file disturbs nothing else).
- Module-level statements (variable assignments, imports) are treated as
  definitions too — added, changed, or removed like functions and classes.

This applies to plain functions, methods, classmethods, staticmethods, properties,
`async def`, generators, and nested functions. For **decorated** functions, editing
the body and reloading updates the code inside the wrapper while the decorator
stays in effect — even when the decorator returns a non-function object.

**`super()` and free variables.** A redefined method that calls `super()` must keep
working (its code implicitly closes over `__class__`). When a redefinition changes
a nested function's free variables so the new code cannot be conformed, apply it
anyway by re-evaluating the definition fresh.

**Live execution.** Redefinition only affects code that runs afterwards:

- A call already on the stack (including recursion), and any generator or coroutine
  already created, finishes on its original code; only later calls use the new code.
- Reloading a file re-runs only the top-level statements whose source changed;
  unchanged statements (and the state they produced) are left alone.
- Redefining a class does not re-run `__init__` on existing instances (they keep
  their state), though changed methods do take effect.

## Recoders — `jurigged.recode`

`make_recoder(obj, deletable=False)` returns a recoder focused on `obj` — a module,
function, method, code object, or class.

- `patch(new_source)` — redefine the focus; `new_source` must define the same name,
  otherwise `ValueError`. With `deletable=True`, `patch("")` deletes the focus (its
  name leaves the module) and a later `patch` re-creates it.
- `patch_module(new_source)` — apply at module level, ignoring the focus; may add
  new top-level names (functions, classes, or module-level variables) while
  changing existing ones.
- `commit()` — write changes to the source file (untouched until then),
  reconstructing it so everything except the changed definitions is preserved
  **byte-for-byte** (comments, blank lines, unchanged definitions).
- `revert()` — reload from disk, dropping uncommitted changes but keeping committed
  ones.
- `repatch()` — re-apply this recoder's latest patch.

**Concurrent recoders.** Two recoders on one file share the live code. A recoder
goes **out-of-sync** when another recoder patches the shared live code after it (a
`patch`, not the on-disk `commit`); your own `patch` (or `repatch`) makes you
committable again. An out-of-sync `commit()` raises `OutOfSyncException`.

## Registry — `jurigged.register`

`registry` (also `jurigged.registry`) maps files to their parsed form.

- `registry.find(obj)` → `(codefile, definition)` for a module, function, code
  object, or class. Objects from the same file share one `codefile`; a function and
  its `__code__` give the same `definition`.
- `codefile.refresh()` — re-read the file and live-apply the diff: edited
  definitions updated, new ones added, removed ones deleted from the module.
- `codefile.commit()` — as a recoder's `commit()`.
- `definition.dotpath()` — the module-qualified dotted path, ending in the
  object's own name (e.g. `module.build`, `module.Widget`).

## Watching — `jurigged.watch` / `Watcher`

- `watch(pattern="./*.py", ..., autostart=True)` — register files matching
  `pattern` and return a `Watcher` that reloads them on change; `autostart=False`
  returns it without starting the watch thread.
- `Watcher.refresh(path)` reloads one file. `Watcher.prerun` and `Watcher.postrun`
  are event sources with a `register(callback)` method, called with
  `(path, codefile)` before and after a refresh.
- `glob_filter(pattern)` → a `matcher(filename) -> bool`. A relative pattern is
  resolved against the current directory first; an absolute one is used as-is.
  Matching is `fnmatch`-based — the pattern is compared against the whole filename
  string, so `*` also spans `/` separators: an absolute `dir/*.py` pattern therefore
  matches `dir/sub/mod.py` as well as `dir/mod.py`.

## Helpers and redirection

- `virtual_file(name, contents)` — register `contents` in `linecache` under a fresh
  key of the form `"<name#N>"` and return that key.
- `redirect(fn, transform)` — rewrite `fn`'s code in place so calling `fn` runs
  `transform(saved)`, where `saved` is the original `fn`; `fn` keeps its identity
  and every reference observes the change.
- `redirect_code(code, transform)` — the same, addressed by a code object; if
  `code` is not used by exactly one live function, raise an error whose message
  contains `"requires exactly one function"`.
