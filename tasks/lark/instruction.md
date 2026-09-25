# lark

Build `lark`, a parser generator for Python that supports LALR(1) and Earley parsing algorithms. It compiles EBNF grammars into parsers, produces parse trees, and provides a Transformer pattern for tree-to-value conversion. Grammars are defined as strings using lark's EBNF syntax.

## Dependencies

- No runtime dependencies. `lark` is a pure-Python implementation.
- The environment is **offline**: there is no network access, and everything needed is already
  installed. Do **not** install anything. The project is installed for you by a `setup.sh` that
  runs offline (an editable install backed by a pre-baked build backend); just implement the
  package so that an editable install of it imports as `lark`.

## Package Structure

Importable as `lark`. Key exports:
- `lark.Lark` — main parser generator class
- `lark.Tree` — parse tree node
- `lark.Token` — terminal token (inherits from str)
- `lark.Transformer` — tree transformation via method dispatch
- `lark.Visitor` — tree traversal
- `lark.Discard` — sentinel value to discard nodes in Transformer
- `lark.v_args` — decorator to control how arguments are passed to Transformer methods
- `lark.exceptions` — `GrammarError`, `UnexpectedToken`, `UnexpectedCharacters`, `UnexpectedEOF`, `LarkError`
- `lark.indenter.Indenter` — postlex for Python-style indentation handling
- `lark.reconstruct.Reconstructor` — convert parse tree back to source text

## Lark

`Lark(grammar, parser='earley', start='start', **options)` — compile an EBNF grammar string into a parser.

- `parser` — `'lalr'` (fast, deterministic) or `'earley'` (general, handles ambiguity)
- `start` — name of the start rule (default `'start'`)
- `ambiguity` — `'explicit'` wraps ambiguous parses in `_ambig` nodes (Earley only). Each distinct
  ambiguity point in the parse becomes a single `_ambig` `Tree` node whose children are the
  alternative subtrees for that point (one child per distinct derivation); sub-derivations that are
  unambiguous are left unwrapped.
- `postlex` — a `PostLex` instance to post-process the token stream (e.g., `Indenter`)
- `maybe_placeholders` — when `False`, disables placeholder insertion for optional rules (required for `Reconstructor`)

`parser.parse(text, on_error=None)` → `Tree` — parse input text and return a parse tree. The optional `on_error` callback (LALR only) receives an `UnexpectedToken` exception and returns `True` to attempt recovery.

`parser.parse_interactive(text)` → `InteractiveParser` — begin step-by-step LALR parsing.

`parser.save(f)` / `Lark.load(f)` — serialize/deserialize a compiled parser to/from a file object (pickle format).

## Grammar Syntax

Grammars use EBNF notation:
- **Rules** (lowercase): `rule_name: pattern` — produce Tree nodes
- **Terminals** (UPPERCASE): `TERMINAL: /regex/` or `TERMINAL: "literal"` — produce Token leaves
- **Alternatives**: `rule: option_a | option_b`
- **Repetition**: `item*` (zero or more), `item+` (one or more), `item?` (optional)
- **Grouping**: `(a b | c d)` — group expressions
- **Optional group**: `[a b | c d]` — same as `(a b | c d)?`
- **Inline rules**: `?rule: ...` — transparent rule, inlines single-child matches (node is replaced by its child). Inlining applies **only** to alternatives without an alias.
- **Aliases**: `rule: pattern -> alias_name` — the matched alternative always produces a Tree node named `alias_name`. An alias overrides `?` inlining: an aliased alternative yields its named node even when it matched a single child (so its Transformer method is dispatched). For example, `?factor: NUMBER -> number` yields a one-child `number` Tree, not the bare `NUMBER` Token.
- **Ignore**: `%ignore /pattern/` — skip matching content (e.g., whitespace)
- **Import**: `%import common.NUMBER`, `%import common.ESCAPED_STRING`, `%import common.WS` — import built-in terminal definitions
- **Declare**: `%declare TERMINAL` — declare a terminal that will be provided externally (e.g., by a postlex like `Indenter`)

String literals in rules are auto-converted to anonymous terminals.

**Tree children filtering.** Lark treats some terminals as punctuation and omits them from a Tree's children by default: anonymous terminals created from inline string literals (e.g. `"="`, `"+"`, keywords like `"set"`) and terminals whose name begins with an underscore (e.g. `_NL`). Only named rules, named terminals, and anonymous regex terminals appear as children. So `item: NAME "=" VALUE` yields a node with two children (`NAME`, `VALUE`) — the `"="` literal is dropped.

**Terminal priority.** When two terminals can match the same text, a string-literal terminal takes precedence over an overlapping regex terminal. So with both `"if"` and `NAME: /[a-zA-Z_]\w*/` defined, the input `if` lexes as the `"if"` literal, not as `NAME` — reserved keywords win over a general identifier terminal. (Explicit `TERMINAL.<int>: ...` priorities and longer matches also influence lexing order.)

**Contextual lexing (LALR).** The `'lalr'` parser lexes *contextually*: at each position the lexer only considers the terminals that are grammatically valid in the parser's current state. So when two or more terminals match the same text at the **same length** with the **same priority** and none is a string literal — and the priority rules above therefore leave the choice open — the LALR parser produces whichever of those terminals is accepted at that position by the grammar. For example, with `item: NAME "=" VALUE`, `NAME: /[a-zA-Z_]+/`, and `VALUE: /[a-zA-Z0-9_]+/`, the input `name=Alice` lexes `name` as `NAME` (only `NAME` is valid at the start of `item`) and the equal-length-overlapping `Alice` after `=` as `VALUE` (the position where `VALUE` is expected), even though both terminals match `Alice`. The same holds when two terminals are defined identically (e.g. `NAME: /[a-zA-Z_]+/` and `KEY: /[a-zA-Z_]+/` used in different rule positions): the parser context selects the one valid at each position. Because of this, the `'lalr'` and `'earley'` backends produce the same parse tree for such grammars.

**Optionals and placeholders.** A trailing `?` on a single terminal or rule (e.g. `name: FIRST LAST?`) simply omits the item when it doesn't match — no placeholder child is added (so an absent `LAST?` leaves one child). The bracket form `[ ... ]` instead inserts a `None` placeholder when it doesn't match while `maybe_placeholders=True` (the default); set `maybe_placeholders=False` to make `[ ... ]` behave exactly like `( ... )?` with no placeholder.

## Tree

`Tree(data, children)` — parse tree node.
- `data` — rule name (str)
- `children` — list of child Trees and Tokens
- `pretty()` → str — indented string representation
- `find_data(name)` → iterator of subtrees with matching data
- `find_pred(predicate)` → iterator of subtrees matching predicate
- `iter_subtrees()` → iterator of all subtrees (bottom-up)
- Supports equality comparison and hashing

## Token

Inherits from `str`. Has `.type` attribute (terminal name) and `.value` (the matched text, same as str value). Carries position info: `.line`, `.column`, `.end_line`, `.end_column` (1-indexed).

## Transformer

Subclass `Transformer` and define methods matching rule names. Each method receives the children list and returns a transformed value. The tree is processed bottom-up.

```python
class MyTransformer(Transformer):
    def rule_name(self, children):
        return processed_value
```

`transformer.transform(tree)` — apply the transformation.

Return `Discard` from a method to remove that node from its parent's children.

## v_args

`@v_args(inline=True)` — class or method decorator. When applied, transformer methods receive children as individual positional arguments instead of a single list.

## Visitor

Like Transformer but for side effects — visits nodes without replacing them. Call `visitor.visit(tree)`.

## Indenter

`lark.indenter.Indenter` — abstract `PostLex` subclass that injects `INDENT`/`DEDENT` tokens based on indentation level changes. Subclass it and define these attributes:
- `NL_type` — terminal type for newlines
- `INDENT_type`, `DEDENT_type` — token types to inject
- `OPEN_PAREN_types`, `CLOSE_PAREN_types` — paren tokens (indentation ignored inside parens)
- `tab_len` — spaces per tab

The grammar must use `%declare` for the INDENT and DEDENT terminal types. Pass the Indenter instance as `postlex` to `Lark`.

## InteractiveParser

Returned by `parser.parse_interactive(text)`. Allows stepping through LALR parsing token-by-token.
- `iter_parse()` → iterator of tokens fed to the parser
- `feed_eof(last_token=None)` → feed end-of-input and return the parse tree
- `copy()` → create an independent copy of the parser state
- `choices()` → dict of currently accepted token types

## Reconstructor

`lark.reconstruct.Reconstructor(parser)` — given a Lark parser instance (created with `maybe_placeholders=False`), reconstructs source text from a parse tree.

`reconstructor.reconstruct(tree)` → str

## Error Handling

- `GrammarError` — invalid grammar syntax
- `UnexpectedToken` — parser received a token it didn't expect. Has `.token`, `.expected`, `.line`, `.column` attributes.
- `UnexpectedCharacters` — lexer encountered characters matching no terminal. Has `.line`, `.column`.
- `UnexpectedEOF` — input ended before parsing completed

All inherit from `LarkError`.

## setup.sh

```bash
pip install -e . --no-build-isolation
```
