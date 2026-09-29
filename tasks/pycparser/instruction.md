# pycparser — C99 Parser in Pure Python

Implement `pycparser`, a complete C99 parser in pure Python. The library tokenizes C source code, parses it into an Abstract Syntax Tree (AST) with ~50 node types, and can regenerate C code from the AST. No external dependencies.

## Dependencies

None — `pycparser` is pure Python and uses only the standard library (no third-party runtime dependencies).

The environment is **offline**: there is no network access, and you must not install anything. The project is built and installed for you by a `setup.sh` that runs fully offline (an editable install via the pre-baked `setuptools`/`wheel` build backend). Implement the package against the standard library only.

## Package Structure

```python
from pycparser import CParser, c_ast
from pycparser.c_ast import NodeVisitor
from pycparser.c_generator import CGenerator
from pycparser.c_lexer import CLexer, Token
from pycparser.c_parser import Coord, ParseError
```

Top-level convenience: `pycparser.CParser` is re-exported from `pycparser.c_parser.CParser`.

## 1. CParser — Main Entry Point

```python
parser = CParser()
ast = parser.parse(text, filename='<unknown>')  # returns c_ast.FileAST
```

Parses C99 source code (as a string) and returns an AST. The `filename` parameter is used for error messages and `Coord` objects. Raises `ParseError` on syntax errors.

The parser implements a recursive-descent parser for the full C99/C11 grammar including: variable/function declarations (including K&R old-style parameter declarations), type specifiers/qualifiers (including multi-word like `unsigned long long int`, `_Atomic`), pointer/array/function declarators, typedef names (with scope tracking — typedef names can be reused as variables in inner scopes), struct/union/enum (including bitfields, flexible array members, anonymous struct/union members), compound literals, designated initializers, expressions with operator precedence (including comma operator), all statement types (if/else, for, while, do-while, switch/case/default, goto/label, return, break, continue), `_Pragma`, `_Alignas`, `_Noreturn`, `_Atomic` (as specifier and qualifier), `_Static_assert`, variable-length arrays (VLA), array parameter qualifiers (`const int a[const n]`), `#line` directives (update file/line in `Coord`), and more.

**Empty external declaration**: a lone `;` at file scope is an empty declaration — it is accepted rather than raising `ParseError`.

**Typedef/identifier disambiguation**: The parser maintains a scope stack to track typedef names. When the lexer encounters an identifier, it queries the parser to determine if it's a typedef name (tokenized as `TYPEID`) or a regular identifier (`ID`).

**Identifier characters**: identifiers follow the C rule (`[A-Za-z_][A-Za-z0-9_]*`) but additionally allow the `$` character (as some compilers do) in **any** position, including as the first character — i.e. `$` joins both the leading and the body character class, so identifiers match `[A-Za-z_$][A-Za-z0-9_$]*`. Thus both `a$b` and `$x` are single valid identifiers.

**Coord** tracks source locations with `file`, `line`, and optional `column` attributes. Its `str()` form is `'file:line'`, with `':column'` appended only when `column` is set (i.e. `'file:line[:column]'`).

## 2. AST Nodes

All nodes inherit from `c_ast.Node`:
- `coord`: Source location (`Coord` or None)
- `children()`: Returns `tuple` of `(name, child_node)` pairs. Sequence children use indexed names: `"ext[0]"`, `"stmts[1]"`
- `attr_names`: Class-level tuple of leaf attribute names (not child nodes)
- `show(buf=sys.stdout, offset=0, attrnames=False, nodenames=False, showcoord=False)`: Pretty-prints the AST. `attrnames=True` includes leaf attribute values; `nodenames=True` includes child names like `"ext[0]"`; `showcoord=True` includes `file:line` info. Output is indented to reflect tree depth.
- Nodes are iterable — `iter(node)` yields child nodes directly
- Nodes are **mutable** — attributes can be set after construction (e.g., `node.name = 'new_name'`). This enables AST rewriting: parse C, modify nodes, generate modified C.
- Nodes can be **constructed programmatically** and passed to `CGenerator` to produce C code without parsing. This enables building ASTs from scratch.
- ASTs can be **serialized to JSON** by walking `children()` and `attr_names` — each node becomes a dict with `_nodetype` (class name), leaf attributes, child nodes as nested dicts, and `coord` as a string.

**Node types** (each has `__slots__` and a constructor exposing all attributes as named parameters in the documented order — so they may be passed positionally or by keyword — with `coord` as a keyword-only parameter):

Declarations: `FileAST`, `Decl`, `TypeDecl`, `IdentifierType`, `PtrDecl`, `ArrayDecl`, `FuncDecl`, `FuncDef`, `Typedef`, `Struct`, `Union`, `Enum`, `Enumerator`, `EnumeratorList`, `ParamList`, `EllipsisParam`, `DeclList`, `Typename`

Statements: `Compound`, `If`, `For`, `While`, `DoWhile`, `Switch`, `Case`, `Default`, `Return`, `Break`, `Continue`, `Goto`, `Label`, `EmptyStatement`

Expressions: `BinaryOp`, `UnaryOp`, `TernaryOp`, `Assignment`, `Cast`, `FuncCall`, `ExprList`, `Constant`, `ID`, `ArrayRef`, `StructRef`, `InitList`, `NamedInitializer`, `CompoundLiteral`

Other: `StaticAssert`, `Pragma`, `Alignas`

**Per-node attributes.** Each node's constructor accepts the attributes below as named parameters in the order listed, so a node may be constructed by passing them positionally **or** by keyword (the parameter names equal the attribute names); e.g. `c_ast.IdentifierType(names=['int'])` and `c_ast.Decl(name='x', quals=[], align=[], storage=[], funcspec=[], type=..., init=None, bitsize=None)` are both valid, as is the equivalent positional form. `coord` is a keyword-only parameter. Names marked `*` are child nodes (or `None`); names marked `**` are sequences of child nodes (a Python `list`); unmarked names are leaf attributes (returned by `children()` for the starred ones, and listed in `attr_names` for the unmarked ones).

| Node | Attributes (in order) |
| --- | --- |
| `FileAST` | `ext**` |
| `Decl` | `name`, `quals`, `align`, `storage`, `funcspec`, `type*`, `init*`, `bitsize*` |
| `TypeDecl` | `declname`, `quals`, `align`, `type*` |
| `IdentifierType` | `names` |
| `PtrDecl` | `quals`, `type*` |
| `ArrayDecl` | `type*`, `dim*`, `dim_quals` |
| `FuncDecl` | `args*`, `type*` |
| `FuncDef` | `decl*`, `param_decls**`, `body*` |
| `Typedef` | `name`, `quals`, `storage`, `type*` |
| `Struct` / `Union` | `name`, `decls**` |
| `Enum` | `name`, `values*` |
| `Enumerator` | `name`, `value*` |
| `EnumeratorList` | `enumerators**` |
| `ParamList` | `params**` |
| `EllipsisParam` | (none) |
| `DeclList` | `decls**` |
| `Typename` | `name`, `quals`, `align`, `type*` |
| `Compound` | `block_items**` |
| `If` | `cond*`, `iftrue*`, `iffalse*` |
| `For` | `init*`, `cond*`, `next*`, `stmt*` |
| `While` / `DoWhile` | `cond*`, `stmt*` |
| `Switch` | `cond*`, `stmt*` |
| `Case` | `expr*`, `stmts**` |
| `Default` | `stmts**` |
| `Return` | `expr*` |
| `Break` / `Continue` / `EmptyStatement` | (none) |
| `Goto` | `name` |
| `Label` | `name`, `stmt*` |
| `BinaryOp` | `op`, `left*`, `right*` |
| `UnaryOp` | `op`, `expr*` |
| `TernaryOp` | `cond*`, `iftrue*`, `iffalse*` |
| `Assignment` | `op`, `lvalue*`, `rvalue*` |
| `Cast` | `to_type*`, `expr*` |
| `FuncCall` | `name*`, `args*` |
| `ExprList` / `InitList` | `exprs**` |
| `Constant` | `type`, `value` |
| `ID` | `name` |
| `ArrayRef` | `name*`, `subscript*` |
| `StructRef` | `name*`, `type`, `field*` |
| `NamedInitializer` | `name**`, `expr*` |
| `CompoundLiteral` | `type*`, `init*` |
| `StaticAssert` | `cond*`, `message*` |
| `Pragma` | `string` |
| `Alignas` | `alignment*` |

**Leaf-value conventions** (the strings/values these leaf attributes hold):
- `BinaryOp.op` / `Assignment.op`: the operator as a string, e.g. `'+'`, `'*'`, `'||'`, `'&&'`, `'=='`, `'>>'` for binary ops and `'='`, `'+='`, `'*='`, `'>>='` for assignments.
- `UnaryOp.op`: the unary operator as a string, e.g. `'&'` (address-of), `'*'` (dereference), `'-'`, `'!'`, `'p++'`/`'p--'` (postfix), and `'sizeof'` for `sizeof`.
- `StructRef.type`: `'.'` for `a.b` and `'->'` for `a->b`.
- `Constant.value`: the literal's source text as a string (e.g. `'42'`, `'3.14'`), and `Constant.type` its kind: integer literals are `'int'` (with `'unsigned'`/`'long'` suffix words appended when present, e.g. `'unsigned int'`, `'long int'`), floating literals `'double'` (or `'float'`/`'long double'` for an `f`/`F` or `l`/`L` suffix), string literals `'string'`, and character literals `'char'`.
- `ArrayDecl.dim`: the size expression node, or `None` for an unsized / flexible array member (`char data[];`).
- `FuncDecl.args`: the `ParamList` child for a function declarator's parameters, or `None` when the parameter list is empty (`()` — no parameter-type-list); `(void)` instead yields a `ParamList` with a single `void` `Typename`. Likewise `FuncCall.args` is `None` for a call with no arguments (`foo()`) and an `ExprList` of the arguments otherwise. (So empty parens add no child node to the tree.)
- `Struct.decls` / `Union.decls`: `None` for a forward declaration (`struct S;`), `[]` (empty list) for an empty body (`struct S {};`), and a list of member `Decl`s for a full definition. A member `Decl` carries its bit-field width in `bitsize` (a `Constant` or `None`).
- **Where a type node attaches on a `Decl` / `Typedef` (the `TypeDecl`-interposition rule).** A `TypeDecl` sits between a declaration and its base type **only when the declaration introduces a declared name** (`TypeDecl.declname`). So a named or builtin-type declaration (`int x;`, or a struct-typed variable `struct S s;`, or a `typedef`) wraps the base type in a `TypeDecl`: `int x;` → `Decl.type` is a `TypeDecl(declname='x')` whose `.type` is an `IdentifierType`; `struct S s;` → `Decl.type` is a `TypeDecl(declname='s')` whose `.type` is the `Struct`; `typedef struct rec {...} rec_t;` → `Typedef.type` is a `TypeDecl(declname='rec_t')` whose `.type` is the `Struct`. In contrast, a declaration that introduces a struct/union/enum type **without** a declared name — the standalone forms `struct S {...};`, `union U {...};`, `enum E {...};`, the forward `struct S;`, and the empty `struct S {};`, as well as a nameless anonymous struct/union member inside a struct body — produces a `Decl` with `name is None` whose `type` **is** the `Struct` / `Union` / `Enum` node **directly**, with no `TypeDecl` in between (`ast.ext[i].type` is the `Struct`/`Union`/`Enum`). The usual `TypeDecl` still sits at the bottom of the declarator chain inside pointer/array/function declarators and in abstract / `Typename` declarators (e.g. the type in `sizeof(struct {...})`).
- `Decl.quals` / `.storage` / `.funcspec`: lists of strings, e.g. `quals` contains `'const'`/`'volatile'`, `storage` contains `'static'`/`'extern'`, `funcspec` contains `'inline'`/`'_Noreturn'`.
- The comma operator (e.g. `(1, 2, 3)`) is represented as a `c_ast.ExprList` whose `exprs**` are the comma-separated sub-expressions in source order — not as a `BinaryOp` with `op=','`.
- `Pragma.string`: for the `_Pragma("...")` operator form, this holds a `Constant` node (a string literal) whose `value` is the parenthesized payload as source text **including the surrounding quotes** (e.g. `_Pragma("pack(push, 1)")` gives a `Constant` with `value == '"pack(push, 1)"'`). For the `#pragma ...` directive form it holds the directive text as a plain string. (`string` is listed in `attr_names`, but its value for the operator form is a `Constant`.)
- `Decl.align` / `Typename.align` / `TypeDecl.align`: a list of `Alignas` nodes (not a plain leaf value). An `_Alignas(N)` specifier on a declaration is captured as an `Alignas` node — whose `alignment*` child is the alignment expression (e.g. a `Constant`) — appended to the declaration's `align` list, and the generator re-emits it as `_Alignas(N)`. A declaration with no alignment specifier has an empty `align` list.
- `IdentifierType.names` and the `quals` / `storage` / `funcspec` lists preserve their words in **source order**, so a multi-word specifier such as `unsigned long long int` becomes `names == ['unsigned', 'long', 'long', 'int']`, and `_Atomic` (whether written as the `_Atomic(...)` specifier or as a trailing `_Atomic` qualifier) appears as `'_Atomic'` in the relevant `quals` list.
- Where qualifiers attach on a simple (non-pointer) declaration: leading declaration-level qualifiers/specifiers — an ordinary `const`/`volatile`, and the `_Atomic` contributed by the `_Atomic(...)` specifier form (e.g. `const _Atomic(int) x;`) — are recorded in `Decl.quals`. **In addition**, every type qualifier on such a declaration — whether written before the base type (a leading `const`/`volatile`, a leading bare `_Atomic int`, or the `_Atomic(...)` specifier) or after it (a trailing `int const`, or the trailing `_Atomic` in `int _Atomic flag;`) — is **also** recorded on the declared type's (`TypeDecl`) `quals`. So `_Atomic` on a simple declaration appears in `TypeDecl.quals` regardless of the position it was written in, which is what lets a generate → re-parse roundtrip preserve it: the generator may re-emit an `_Atomic` qualifier before the base type (`_Atomic int flag;`), and because a leading bare `_Atomic` still lands on `TypeDecl.quals`, the qualifier survives the roundtrip there. (For a pointer declaration, a qualifier on the pointed-to `_Atomic(int *)` lives on the `PtrDecl.quals`.)
- For a **pointer or array** declaration, leading ordinary type qualifiers written before the base type (the `const volatile` in `const volatile int *p;`, or in `const volatile int a[3];`) qualify the pointed-to / element type: they are recorded on the innermost (pointed-to / element) `TypeDecl.quals` — `PtrDecl.type.quals` for a pointer, `ArrayDecl.type.quals` for an array — not on the `PtrDecl` / `ArrayDecl` itself. (`Decl.quals` carries leading qualifiers for the simple non-pointer case above.)

## 3. NodeVisitor

```python
class NodeVisitor:
    def visit(self, node)         # dispatches to visit_<ClassName>, else generic_visit
    def generic_visit(self, node)  # visits all children recursively
```

Define `visit_XXX(self, node)` methods to handle specific node types. When a `visit_XXX` method exists, `generic_visit` is NOT called automatically — to also visit children, call `self.generic_visit(node)` explicitly.

## 4. CLexer — C Tokenizer

`CLexer(error_func, on_lbrace_func, on_rbrace_func, type_lookup_func)` — call `lexer.input(text)` then `lexer.token()` repeatedly (returns `Token` or `None` at end). `Token` has `type`, `value`, `lineno`, `column`.

Token types include: C keywords (`INT`, `VOID`, `RETURN`, `IF`, `WHILE`, `FOR`, `STRUCT`, `ENUM`, `TYPEDEF`, `SWITCH`, `CASE`, `DEFAULT`, `SIZEOF`, `STATIC`, `EXTERN`, `CONST`, `VOLATILE`, etc.), operators (`PLUS`, `MINUS`, `TIMES`, `DIVIDE`, `MOD`, `LAND`, `LOR`, `EQ`, `NE`, `LE`, `GE`, `LSHIFT`, `RSHIFT`, `ARROW`, `PLUSPLUS`, `MINUSMINUS`, `ELLIPSIS`, assignment ops), literals (`INT_CONST_DEC`, `INT_CONST_HEX`, `INT_CONST_OCT`, `INT_CONST_BIN`, `FLOAT_CONST`, `HEX_FLOAT_CONST`, `STRING_LITERAL`, `CHAR_CONST`, `WSTRING_LITERAL`, `WCHAR_CONST`), and identifiers (`ID`, `TYPEID`).

`type_lookup_func(name) -> bool`: Called for each identifier. If True, token type is `TYPEID` instead of `ID`. This enables the parser to resolve the typedef/identifier ambiguity.

## 5. CGenerator — C Code Generation

```python
gen = CGenerator(reduce_parentheses=False)
code = gen.visit(ast)  # returns C code as string
```

Regenerates C source code from an AST using the visitor pattern. `visit(node)` dispatches to `visit_<ClassName>` methods, each returning a string. Output uses conventional C formatting: operators and `=` are spaced with single spaces and declarations terminate with `;` (e.g. `int x = ...;`).

**Parenthesization.** By default (`reduce_parentheses=False`) the generator wraps every binary sub-expression in explicit parentheses, so a chained `p * q * r` is emitted fully parenthesized as `(p * q) * r` (the assignment right-hand side itself is not wrapped — only the binary operands are). Passing `reduce_parentheses=True` omits the parentheses that are redundant given operator precedence/associativity, so the same expression renders as `p * q * r`.

**Round-trip fidelity.** Whichever parenthesization mode is in effect, the emitted text must be valid C that re-parses to the same AST; where the parenthesization policy above would leave a sub-expression ambiguous, the generator parenthesizes it so the meaning is preserved.

## 6. ParseError

```python
from pycparser.c_parser import ParseError
```

Raised on C syntax errors. Message format: `"{file}:{line}: {description}"`.

Syntax errors that raise `ParseError` include not only structural mistakes (a missing `;`, an unclosed `{`, a stray token) but also an **invalid combination of type specifiers** — a declaration whose specifier set is not a legal C type. In particular a duplicated/repeated base type (or otherwise conflicting base specifiers) is rejected with `ParseError`. (Only legal multi-word specifiers like `unsigned long long int` accumulate into `IdentifierType.names`; an illegal specifier combination does not.)
