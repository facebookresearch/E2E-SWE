# KlongPy: Python Implementation of the Klong Array Language

Build `klongpy`, a Python package implementing the Klong array language. Klong is a member of the APL family -- a right-to-left evaluated array language where operations are vectorized over NumPy arrays.

## Dependencies and Environment

The environment is **offline** -- there is no network access. All dependencies are **already installed**; do **not** attempt to install anything (no `pip install`, no network fetches).

Runtime dependencies (pre-installed and available to `import`):

- `numpy` (>=2.0) -- the array backend; all vectorized operations are built on NumPy arrays.
- `colorama` (>=0.4) -- used by the CLI for terminal output.

The project is installed offline by a `setup.sh` that runs `pip install -e . --no-build-isolation` against these pre-installed dependencies (the build backend, `setuptools`, is also already present). Your package must be installable this way -- declare your dependencies and build configuration so an editable install works without fetching anything from the network.

## Core API

### KlongInterpreter

```python
from klongpy import KlongInterpreter

klong = KlongInterpreter()

# Evaluate expression, return result
result = klong("1+2")           # 3
result = klong("a::[1 2 3]")   # array([1, 2, 3])
result = klong("+/a")           # 6

# Python interop via __getitem__ / __setitem__
klong['x'] = 42
val = klong['x']               # 42
del klong['x']
# klong['x'] now raises KeyError -- see note below

# exec() returns list of all sub-results
results = klong.exec("a::10;b::20;a+b")  # [10, 20, 30]

# Python callables set via __setitem__ are callable from Klong
klong['pyfn'] = lambda x: x * 10
klong("pyfn(5)")  # 50
```

The Python `__getitem__` accessor (`klong[name]`) follows Python-mapping semantics: it **raises `KeyError`** for a name that is not defined or has been deleted. This is distinct from evaluating an undefined variable *inside* Klong (e.g. `klong("name")`), which instead returns a symbol with that name (see Data Types below).

### Top-level Exports

```python
from klongpy import KlongInterpreter, KlongException
```

## Language Specification

### Evaluation Order

Klong evaluates **right to left**, with no operator precedence:

```
5+3*2  ->  11    (3*2 first, then +5)
2*3+4  ->  14    (3+4 first, then *2)
```

### Data Types

- **Integers**: `0`, `42`, `-7`
- **Floats**: `1.5`, `3.14`, `1e5`
- **Strings**: `"hello"` (doubled quotes inside: `"say ""hi"""`)
- **Characters**: `0cx` is character 'x'. Characters are a `str` subclass. Accessing a single element of a string yields a **character** (a `str`-subclass value), not a plain 1-character Python `str`: indexing a string by a scalar (`"xyz"@1` -> the character `y`) and taking First of a string (`*"xyz"` -> the character `x`) both return a character. This matters for downstream operators that key on the character type — e.g. the List monad `,`'s single-character special case fires on such a value, so `,("xyz"@1)` -> `"y"` (a one-character string), and `.p`/`.d`/`$` render it as the bare character.
- **Symbols**: `:foo`, `:bar` (a `str` subclass whose `str()` returns the name without the colon, e.g. `str(:foo)` -> `"foo"`)
- **Arrays**: `[1 2 3]`, `[[1 2] [3 4]]`
- **Dictionaries**: `:{[key1 val1] [key2 val2]}` (keys and values can be any type including symbols). A Klong dictionary returned to Python is an instance of the built-in `dict` (or a `dict` subclass) and supports standard Python mapping access: `isinstance(d, dict)` is true, `d[key]` returns the value for an existing key, `key in d` reports membership, and `len(d)` is the entry count. The keys present are exactly the Klong keys (those added at creation and via `,` add-pair, minus those removed via `_` drop-key). A dictionary is a **reference (mutable) value**: an in-place `,` add-pair mutates the underlying dict object itself, so the change is visible through every binding that references that same dictionary — including a function-local variable that a nested function (e.g. the lambda under an Each) has captured as a free variable.
- **Undefined variables**: accessing an undefined variable returns a symbol with that name
- **Functions**: `{x+1}` (monad), `{x+y}` (dyad), `{x+y+z}` (triad)
- **Undefined**: sentinel with `str()` returning `":undefined"`. Result of division by zero, missing dict keys, etc.

### Evaluated Arrays

`[;expr1;expr2;...]` evaluates each expression at construction time.

### Variables and Assignment

```
name::value          Define/assign (dyadic ::), returns the value
```

Variables are looked up through a scope chain. Assignment to an existing variable updates it in its original scope.

### Comments

`:" this is a comment"` -- ignored during evaluation.

### Functions

Functions use braces. Parameters are always `x`, `y`, `z`:

```
{x+1}               monad (1 arg)
{x+y}               dyad (2 args)
{x+y+z}             triad (3 args)
{42}                 nilad (0 args)
```

Local variables: `{[a;b]; a::1; b::2; a+b}`

Application: `f(arg)`, `f(arg1;arg2)`, `f()` (niladic)

Applying a function to **more** arguments than its arity is tolerated (it does not raise): the first arguments (up to the arity) bind positionally to `x`, `y`, `z` and any extra arguments are ignored. In particular, a function of lower arity applied under an adverb that supplies one element per position — e.g. a nilad under Each — simply does not read the supplied element(s), so `{...nilad body...}'list` evaluates the body once per element of `list`.

### Anonymous Recursion

`.f` inside a function body refers to the currently executing function:

```
{:[x<2;x;.f(x-1)+.f(x-2)]}(10)  ->  55   (fibonacci)
```

### Conditionals

```
:[cond;then;else]
:[cond1;then1:|cond2;then2;else]    chained else-if
```

False: `0`, `[]`, `""`. Everything else is true.

### Projections (Partial Application)

Omitting arguments creates projections:

```
{x-y}(1;)@2       ->  -1    (x=1 fixed, apply y=2)
{x-y}(;2)@3       ->  1     (y=2 fixed, apply x=3)
{x-y*z}(1;2;)@4   ->  -7    (x=1,y=2 fixed, apply z=4)
```

A projection may leave **more than one** slot open. When `N` slots are open the projection is `N`-adic, and applying it with an `N`-element list fills the open slots **positionally**, left to right (first open slot <- first element, etc.):

```
{x-y*z}(2;;)@[3 4]   ->  -10   (y=3, z=4; x=2 fixed)
{x-y*z}(;5;)@[3 4]   ->  -17   (x=3, z=4; y=5 fixed)
```

Under a **dyadic** adverb (each-2, each-left, each-right), a two-hole projection binds the left operand element to its first open slot and the right operand element to its second open slot:

```
[7 8]{x,y,z}(;9;)'[1 2]  ->  [[7 9 1] [8 9 2]]
```

### Modules

`.module(:name)` starts a module scope. `.module(0)` closes it. Variables defined inside the module are captured by functions defined there and remain accessible through those functions even after the module closes. While a module scope is open, `name::value` binds the name in that module's own scope, shadowing any same-named variable in an enclosing scope rather than updating it; after `.module(0)`, a top-level assignment to that name targets the enclosing variable and leaves the module's binding unchanged.

### Newlines

Outside of function bodies, lists, conditionals, and dicts, newlines act as semicolons (statement separators). Inside those constructs, newlines are whitespace.

## Monadic Operators (Unary, prefix)

| Op | Name | Description |
|----|------|-------------|
| `@a` | Atom | 1 if atom (number, empty list/string, symbol, function, dict), 0 if non-empty list/string |
| `#a` | Size | Length of list/string, abs of number, ord of char, dict entry count |
| `!a` | Enumerate | `!n` -> `[0 1 ... n-1]` |
| `-a` | Negate | `0-a` (atomic) |
| `+a` | Transpose | Matrix transpose |
| `*a` | First | First element. `*[]`->`[]`, `*""`->`""`, `*42`->`42` |
| `%a` | Reciprocal | `1/a`. `%0` -> `:undefined` (atomic) |
| `~a` | Not | 1 for 0/[]/""   0 otherwise (atomic) |
| `,a` | List | Wrap in single-element list. Special case: wrapping a single character yields a one-character **string** (since characters are a `str` subclass), e.g. `,0cq` -> `"q"`, not a list |
| `$a` | Format | Convert to its **display**-form string (atomic) -- the same external representation Klong would print: a string is unquoted (`$"abc"` -> `"abc"`) and a **character is the bare character** (`$0cz` -> `"z"`, **not** the `0c<c>` readable form). The one exception is a symbol, which is formatted **with** its leading colon, e.g. `$:bar` -> `":bar"` (and numbers as-is, e.g. `$42` -> `"42"`, `$2.5` -> `"2.5"`) |
| `_a` | Floor | Floor toward negative infinity (atomic) |
| `?a` | Unique | Unique elements preserving order |
| `<a` | Grade-Up | Indices that sort ascending (stable: equal elements keep their original relative order) |
| `>a` | Grade-Down | Indices that sort descending. Tie-break: equal elements are returned in **reverse** of their original order, e.g. `>"banana"` -> `[4 2 0 5 3 1]` (the two `n`s at indices 2,4 appear as 4 then 2) |
| `=a` | Group | Group indices by equal elements |
| `\|a` | Reverse | Reverse list/string |
| `^a` | Shape | Dimension vector of `a`: `0` for an atom, otherwise a rank-1 integer array of axis sizes (see below) |
| `&a` | Expand/Where | Replicate indices by count, or find true positions |
| `:#a` | Char | Code point to character (atomic) |
| `:_a` | Undefined | 1 if undefined, else 0 |

Shape (`^a`) always returns `0` for an atom and otherwise a **rank-1 integer array** of axis sizes -- never a bare scalar. A length-`N` vector or string has shape `[N]` (a one-element array, not the number `N`), and higher-rank arrays yield one entry per axis (outermost first).

## Dyadic Operators (Binary, infix)

| Op | Name | Description |
|----|------|-------------|
| `a+b` | Plus | Addition (atomic) |
| `a-b` | Minus | Subtraction (atomic) |
| `a*b` | Times | Multiplication (atomic) |
| `a%b` | Divide | Division, always float. `x%0` -> `:undefined` (atomic) |
| `a^b` | Power | Exponentiation. Integer result when possible (atomic) |
| `a!b` | Remainder | Truncated division remainder (atomic) |
| `a\|b` | Max/Or | Maximum (atomic) |
| `a&b` | Min/And | Minimum (atomic) |
| `a<b` | Less | 1 if a<b, else 0 (atomic) |
| `a>b` | More | 1 if a>b, else 0 (atomic) |
| `a=b` | Equal | 1 if a=b, else 0 (atomic, element-wise) |
| `a~b` | Match | Deep equality |
| `a,b` | Join | Concatenate lists/strings, create pairs; `dict,key,val` adds pair in-place |
| `a#b` | Take | Take `a` elements: positive from the front, negative from the end. When `\|a\|` exceeds the length, the source is conceptually repeated (tiled) and then the leading `a` (or trailing `\|a\|` for negative `a`) elements are taken, so `4#[1 2]` -> `[1 2 1 2]`, `(-4)#[1 2 3]` -> `[3 1 2 3]`, and `5#"ab"` -> `"ababa"` (a string source yields a string). `0#b` yields an empty list/string |
| `a_b` | Drop | Drop elements; or remove dict key |
| `a@b` | At/Apply | Index into list/string; apply function. Indexing a list by an array of indices gathers the selected elements into a list (`[10 20 30 40]@[1 3]` -> `[20 40]`), but indexing a **string** by an array of indices returns a **string** (the selected characters concatenated), not an array of characters, e.g. `"world"@[1 3]` -> `"ol"` |
| `a?b` | Find | Find all positions of b in list/string (returns list); dict lookup returns value or `:undefined`. When both `a` and `b` are **strings**, `b` is treated as a substring: return the start index of every left-to-right occurrence of `b` within `a`, scanning one position at a time so overlapping occurrences are counted (e.g. `"mississippi"?"ss"` -> `[2 5]`, `"banana"?"a"` -> `[1 3 5]`). A single-character or single-element `b` thus still returns element positions |
| `a$b` | Format2 | `n$s`: pad string to width n (positive=left-align, negative=right-align); `w.d$n`: format float with width w and d decimal places. **Atomic -- broadcasts element-wise over arrays** (like `:$`), and a numeric `b` is first converted to its display string and then width-padded, so `[2 3]$[7 8]` -> `["7 " "8  "]` (each element padded to its own width) |
| `a::b` | Define | Assign b to variable a |
| `a:%b` | Integer-Divide | Truncated integer division (atomic) |
| `a:=b` | Amend | `array:=value,indices` replaces the element at each index with `value`; works on strings too; string amend beyond length grows the string. When the replacement `value` is a string longer than one character, the **entire** value is written into the target string starting at each amend index (overwriting and growing as needed), e.g. `"......":="ab",[0 3]` -> `"ab.ab."` and `"xy":="pq",2` -> `"xypq"` |
| `a:-b` | Amend-in-Depth | `array:-value,path` replaces element at nested path |
| `a:@b` | Index-in-Depth | Index into multi-dim array |
| `a:^b` | Reshape | Reshape array `b` to the shape given by `a` (a scalar rank or a rank-1 vector of axis sizes), filling row-major from `b`'s elements; if the shape needs more elements than `b` has, `b` is tiled (cycled), and if fewer, the excess is dropped (e.g. `3:^7` -> `[7 7 7]`). `0` is identity (returns `b` unchanged). A `-1` in the shape means **half the source size**: each `-1` axis is set to `source_element_count` floor-divided by 2, independently of the other axes (it is NOT numpy-style inference from the other axes). This is the same rule whether `a` is a bare scalar or `-1` appears as one axis of a multi-element shape vector, e.g. `[2 -1]:^!10` -> `[[0 1 2 3 4] [5 6 7 8 9]]` (a 2x5 array, since `-1` = 10/2 = 5); a `-1` axis still resolves to half the source even when that makes the total exceed the source and tiling kicks in |
| `a:+b` | Rotate | Rotate list/string `b` by `a` positions. Positive `a` rotates toward the end, so the last `a` elements wrap to the front (`2:+[1 2 3]` -> `[2 3 1]`); negative `a` rotates toward the front (`(-2):+[1 2 3]` -> `[3 1 2]`) |
| `a:#b` | Split | Split list/string `b` into segments. Integer `a`=`n`: split into `ceil(#b/n)` nearly-equal contiguous segments (numpy `array_split` semantics, e.g. `2:#"abcde"` -> `["ab" "cd" "e"]`); if `n>=#b`, returns `[b]`. List `a`: consecutive segment sizes, cycling through `a` when it runs out |
| `a:_b` | Cut | Cut list before given positions |
| `a:$b` | Form | Convert string to type matching a (atomic -- broadcasts over arrays) |
| `a:>b` | Autograd | Gradient via numeric differentiation |

## Adverbs (Higher-Order Modifiers)

| Adverb | Name | Form | Description |
|--------|------|------|-------------|
| `f'a` | Each | monadic | Apply f to each element |
| `a f'b` | Each-2 | dyadic | Apply f pairwise |
| `f:'a` | Each-Pair | monadic | Apply f to each consecutive pair, earlier element to x and later element to y: `f(a1;a2), f(a2;a3), ...` (e.g. `-:'[2 5 9]` -> `[-3 -4]`). For an atom or single-element list, return `a` unchanged |
| `a f:\b` | Each-Left | dyadic | `f(a;b1), f(a;b2), ...` |
| `a f:/b` | Each-Right | dyadic | `f(b1;a), f(b2;a), ...` |
| `f/a` | Over | monadic | Fold/reduce. With no neutral, folding over an empty list returns the empty list (and an empty string for a string argument), e.g. `,/[]` -> `[]` |
| `a f/b` | Over-Neutral | dyadic | Fold with neutral element |
| `f\a` | Scan | monadic | Running fold (accumulate) |
| `f:~a` | Converge | monadic | Find fixpoint |
| `a f:~b` | While | dyadic | f(b) while a(b) is true |
| `a f:*b` | Iterate | dyadic | Apply f to b, a times |
| `f\~a` | Scan-Converge | monadic | Like Converge (`f:~a`) but collects intermediates: it starts with the seed and appends each successive value `f(x)`; iteration stops as soon as applying `f` leaves the value unchanged (`f(x)~x`), and the converged fixpoint value appears **exactly once** (the repeated value that triggers convergence is not appended), so the last element equals the corresponding `f:~a` result. E.g. `{_x%3}\~81` -> `[81 27 9 3 1 0]` (0 is the fixpoint since `_0%3` is 0, and it appears only once) |
| `a f\~b` | Scan-While | dyadic | Like `a f:~b` but collects intermediates: it keeps each value for which the predicate `a` holds and **stops before** the first value at which `a` fails (the seed is included, the failing value is not). E.g. `{x<20}{x+3}\~1` -> `[1 4 7 10 13 16 19]` (22 is excluded) |
| `a f\*b` | Scan-Iterate | dyadic | Iterate collecting intermediates |
| `f@'a` | Each-Index | monadic | Apply f to [index;element] pairs |

Adverbs can be chained: `+/'` is Plus-Over-Each.

When Each is applied to a dictionary, it iterates over `[key, value]` pairs. Each such pair is a **heterogeneous, type-preserving array**: its elements keep their original Python types and are **not** coerced to a common type. So iterating a dictionary with a string key and an integer value yields the pair with the string key *and* the integer value intact — e.g. `{x}':{["k" 7]}` yields the pair `["k" 7]` where the value `7` is still the integer `7` (not the string `"7"`). More generally, any Klong array holding mixed-type elements preserves each element's type rather than unifying them.

## System Functions

| Function | Description |
|----------|-------------|
| `.p(x)` | Print with newline, returns display string |
| `.d(x)` | Display without newline, returns display string |
| `.w(x)` | Write readable representation |
| `.l(x)` | Load and execute .kg file |
| `.E(x)` | Evaluate string as Klong code |
| `.py(x)` | Import a Python module into the context, binding **all** of its public top-level names as **bare, directly-callable** names (e.g. after `.py("math")`, `sqrt(4)` calls `math.sqrt` -> `2.0`) |
| `.pyf(x;y)` | Import only the selected names `y` from module `x` as bare callables (e.g. `.pyf("os.path";"exists")` then `exists("/")`) |
| `.bkf(x)` | Import the named functions from the array backend (NumPy) and bind each as a bare, directly-callable name (like `.pyf`). `x` is a list of function-name strings, e.g. after `.bkf(["exp"])`, `exp(1.0)` calls `numpy.exp`, and after `.bkf(["sqrt"])`, `sqrt([4 9 16])` -> `[2 3 4]` element-wise |
| `.pc()` | Seconds since interpreter start |
| `.rn()` | Random float in [0,1) |
| `.ic(x)` / `.oc(x)` / `.ac(x)` | Open file for reading/writing/appending |
| `.cc(x)` | Close channel |
| `.fc(x)` / `.tc(x)` | Select `x` as the input/output channel (0 restores the default `.cin`/`.cout`); **returns the channel that was previously active**, so `.cc(.tc(0))` restores the default output channel and closes the one it replaced |
| `.r()` / `.rl()` | Read data object / read line from input |
| `.rs(x)` | Parse string into Klong object |
| `.x(x)` | Exit interpreter (raises SystemExit) |
| `.module(x)` | Start/stop module scope |

A function value displays (via `.d`/`.p`) as a colon-prefixed arity tag matching its parameter count: `:nilad` (0 args), `:monad` (1 arg), `:dyad` (2 args), `:triad` (3 args). For example, `.d({x+y})` -> `":dyad"`.

Arrays and dictionaries render in Klong source notation: an array as its space-separated elements inside square brackets (e.g. `.d([1 2])` -> `"[1 2]"`), and a dictionary as `:{[key val] ...}` (e.g. `.d(:{[3 4]})` -> `":{[3 4]}"`). `.d`/`.p` produce the *display* form (strings appear unquoted, characters bare, and a **symbol appears as its bare name without the leading colon**, e.g. `.d(:bar)` -> `"bar"`), while `.w` writes the *readable* form (strings wrapped in quotes with inner quotes doubled, characters as `0c<c>`, symbols **with** their colon as `:name`); both render arrays/dicts with the same bracket notation, recursing on their elements. Note the display form of a symbol thus differs from `$` (Format), which keeps the colon (`$:bar` -> `":bar"`).

`.E(x)` evaluates its string as top-level Klong code in the **global** scope, so assignments made through it (e.g. `created::...`) define or mutate global variables even when `.E` is called from inside a function body. For example, `maker::{.E("created::" , $x)}; maker(42)` leaves `created` visible at top level (`created` -> `42`).

File I/O works through the channel stack: `.oc`/`.ic` open a file for output/input, `.tc`/`.fc` push it as the active output/input channel (returning the previously-active channel), `.w`/`.r` write/read data objects, and `.cc(.tc(0))` / `.cc(.fc(0))` restore the default and close the file. A full write-then-read roundtrip looks like:

```
.tc(.oc("/tmp/f"))      open file for output and make it active
.w([1 2 3])             write a readable data object to it
.cc(.tc(0))             restore default output channel and close the file
.fc(.ic("/tmp/f"))      open the same file for input and make it active
x::.r()                 read the data object back  ->  [1 2 3]
.cc(.fc(0))             restore default input channel and close the file
```

### System Variables

- `.f` -- the currently executing function (for anonymous recursion)

## Backend

The interpreter uses a NumPy backend by default. `klong.backend.name` returns `'numpy'`.

## CLI Entry Point

Invocable as `python -m klongpy.cli`:

```bash
python -m klongpy.cli -e "1+2"    # Evaluate expression, print result
python -m klongpy.cli file.kg     # Run file
```

## Numeric Differentiation (Autograd)

The `:>` operator computes gradients via numeric differentiation:

```
{x^2}:>3.0       ->  ~6.0
{+/x^2}:>[1 2 3] ->  [2 4 6]
```

Multi-parameter mode: when the right operand of `:>` is a bracketed list of bare variable names (e.g. `loss:>[w b]`), the names are taken as **gradient targets** rather than evaluated to their values — i.e. `[w b]` is treated as the list of *symbols* `w` and `b`, not the array of their current numeric values. The left operand is then a niladic loss function that reads those variables as free (in-scope) variables. The result is a list holding one partial derivative per listed variable, in the same order.
