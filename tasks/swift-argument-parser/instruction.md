# ArgumentParser — a declarative command-line argument parser for Swift

Implement a Swift library that lets a developer describe a command-line interface **declaratively**
— by decorating the stored properties of a `struct` with property wrappers — and then parses an
argument array into a fully-populated, type-checked instance of that struct, producing precise
error messages and formatted help text when the input is wrong or help is requested.

Deliver a Swift package whose library product is a single module named **`ArgumentParser`**. All
types and members described below must be `public` and importable via `import ArgumentParser`. The
package must build offline (no network, no external dependencies) with the installed Swift 6
toolchain. Only the standard library and `Foundation` are available.

Everything in this document is part of the public contract. Where exact output text is shown
(help screens, error messages, completion scripts), reproduce it exactly, including spacing.

---

## 1. Core model

A user declares a type conforming to one of:

- **`ParsableArguments`** — a bundle of parsed values with no behavior of its own.
- **`ParsableCommand`** — a runnable command; refines `ParsableArguments` and adds an optional
  `static var configuration: CommandConfiguration` and a `mutating func run() throws` (a default
  empty `run()` is provided).

```swift
struct Repeat: ParsableCommand {
  @Flag(help: "Include a counter with each repetition.") var includeCounter = false
  @Option(name: .shortAndLong, help: "How many times to repeat 'phrase'.") var count: Int? = nil
  @Argument(help: "The phrase to repeat.") var phrase: String
  mutating func run() throws { /* ... */ }
}
```

Stored properties are declared with the property wrappers `@Argument`, `@Option`, `@Flag`, and
`@OptionGroup`. The parser uses the property names, their types, and the wrapper configuration to
drive parsing. Conformers are `Decodable`; a conforming type with only wrapped properties gets its
conformance synthesized, and parsing populates each property through a custom decoding process (you
choose the mechanism — the observable contract is what matters).

### Parsing entry points

On any `ParsableArguments` type `T`:

- `static func parse(_ arguments: [String]? = nil) throws -> T` — parse an explicit argument array
  (when `nil`, use the process arguments) and return a populated instance, or throw on failure or
  when help is requested. **Successful parsing also runs the instance's `validate()` (see §7).**
- `static func message(for error: Error) -> String` — a brief, user-facing message for an error.
- `static func helpMessage(includeHidden: Bool = false, columns: Int? = nil) -> String` — the
  rendered help screen (see §10).
- `static func exitCode(for error: Error) -> ExitCode` — the exit code an error maps to (see §8).
- `static func completionScript(for shell: CompletionShell) -> String` — a shell completion
  script (see §12).

On `ParsableCommand` type `T`:

- `static func parseAsRoot(_ arguments: [String]? = nil) throws -> ParsableCommand` — parse,
  resolving the command tree (§9), and return the selected leaf command instance (which may be a
  subcommand type, not `T`). A help request throws an error that `message(for:)` renders as help.

---

## 2. `@Option`

An option takes a named value: `--count 5`, `--count=5`, or (short) `-c 5`.

- `@Option var count: Int` — required; parsing fails if absent.
- `@Option var count: Int?` — optional; `nil` when absent.
- `@Option var count: Int = 10` — defaulted; `10` when absent.
- `@Option var files: [String]` — repeatable; see §5 for strategies.

Value types must be `ExpressibleByArgument` (§4) unless a `transform:` closure is supplied (§7).
Configuration parameters (all optional): `name:` (§3), `parsing:` (§5), `help:` (§10),
`transform:` (§7).

Accepted value syntaxes for an option with long name `--name` and short name `-n`:

| Syntax | Notes |
|---|---|
| `--name value` | value is the next element |
| `--name=value` | joined with `=` |
| `-n value` | short, space-separated |
| `-nvalue` | short, **joined** — only when the short name allows it (§3) |

---

## 3. Names — `NameSpecification`

By default an option/flag's **long** name is its property name converted from `camelCase` to
`kebab-case` (`filePath` → `--file-path`). Provide `name:` to override. A `NameSpecification` is
composed of one or more elements:

- `.long` — the kebab-cased long name (default).
- `.short` — a single-dash name from the property's first letter (`verbose` → `-v`).
- `.shortAndLong` — both `.short` and `.long`.
- `.customShort(_ char: Character, allowingJoined: Bool = false)` — a specific short name. When
  `allowingJoined` is `true`, the `-<char><value>` joined form is accepted for options.
- `.customLong(_ name: String, withSingleDash: Bool = false)` — a specific long name; with
  `withSingleDash: true` it is written with a single dash (e.g. `-title`) instead of `--`.

A name is only reachable in the exact form declared: a single-dash long name is not matched by
`--`, and an overridden long name replaces (does not add to) the inferred one. Combine elements
with an array literal, e.g. `name: [.customShort("n"), .long]`.

---

## 4. Values — `ExpressibleByArgument`

A type parseable from a single command-line token conforms to `ExpressibleByArgument` by providing
`init?(argument: String)` (returning `nil` for an unparseable token). `String`, `Int`, `Double`,
`Bool`, and other standard types conform out of the box. A `RawRepresentable` type whose raw value
is `ExpressibleByArgument` (e.g. a `String`- or `Int`-backed `enum`) gets a default
implementation, so `enum Format: String, ExpressibleByArgument { case text, json, csv }` parses
`--format json` into `.json`. An invalid value yields a specific error listing the valid values
(§11).

---

## 5. Parsing strategies

### `@Option` arrays — `ArrayParsingStrategy` (via `parsing:`)

- `.singleValue` (default) — one value per option occurrence; repeats accumulate. Values are
  distinguished from options, so `--read foo --name Foo` binds `foo` to `read`.
  `--read foo --read bar` → `["foo", "bar"]` (also with `=`).
- `.upToNextOption` — consume consecutive values until the next dash-prefixed token.
  `--files foo bar --verbose` → `files == ["foo", "bar"]`, and `--verbose` still parses.
- `.remaining` — capture **all** following inputs unparsed (pass-through).
  `--passthrough --foo 1 --bar 2 -xvf` → `["--foo", "1", "--bar", "2", "-xvf"]`.

### `@Argument` (positional) arrays — via `parsing:`

- `.remaining` (default) — capture all positional inputs; inputs after the `--` terminator are
  positional too.
- `.allUnrecognized` — after normal parsing, capture every input not matched by a known
  flag/option or a preceding positional (suppresses "unexpected argument"). Given `@Flag verbose`,
  `@Argument name`, `@Argument(parsing: .allUnrecognized) other`: `--verbose Negin one two` →
  `name == "Negin"`, `other == ["one", "two"]`; `Asa --verbose --other -zzz` → `name == "Asa"`,
  `other == ["--other", "-zzz"]`.
- `.postTerminator` — capture only the inputs that follow `--`; a stray positional before `--` is
  still an unexpected-argument error.

### `@Option` single value — `SingleValueParsingStrategy`

`.next` (default) takes the next non-option element as the value.

The `--` terminator forces everything after it to be treated as positional input, even
option-looking tokens.

### Negative numbers as values

A dash-prefixed token that represents a negative number (for example `-1`) and matches no declared
option or flag name is treated as a **value**, not rejected as an unknown option. Such a token
fills a positional `@Argument` and is likewise accepted as the value of an option that expects one.
A dash-prefixed token that is not a number and matches no declaration is still an unknown-option
error (§11).

---

## 6. `@Flag`

A flag is a valueless switch. Behaviors by property type:

- **`Bool`** — `false` by default; present → `true`. `@Flag var verbose = false`.
- **`Bool?`** — `nil` when neither the flag nor its inverse appears.
- **`Int`** — counts occurrences: none → `0`, `-vvv` and `-v -v -v` → `3`.
- **`EnumerableFlag` enum** — each case becomes its own flag name (§6.3).

### 6.1 Inversions — `FlagInversion` (via `inversion:`)

- `.prefixedNo` — adds a `--no-<name>` inverse: `--extattr` sets `true`, `--no-extattr` sets
  `false`.
- `.prefixedEnableDisable` — names become `--enable-<name>` / `--disable-<name>`.

By default a repeated/conflicting flag uses **last-wins** semantics
(`--no-extattr --extattr` → `true`).

### 6.2 Exclusivity — `FlagExclusivity` (via `exclusivity:`)

- `.exclusive` — a conflict between a flag and its inverse is an error instead of last-wins.

A Bool-inversion flag defaults to last-wins (§6.1) and takes `exclusivity: .exclusive` to opt in to
erroring on a conflict; an `EnumerableFlag` enum instead defaults to exclusive (§6.3).

### 6.3 `EnumerableFlag`

An `enum` conforming to `EnumerableFlag` exposes each case as a flag. `@Flag var output: Output`
requires exactly one of the case flags; with a default (`= .list`) it is optional. Override the
name derivation with `static func name(for value: Self) -> NameSpecification`. An `EnumerableFlag`
is **exclusive by default**: selecting two of its case flags is a conflict error (§11) even when
`exclusivity: .exclusive` is not specified.

---

## 7. Transforms, validation, and custom values

- **`transform:`** — `@Option(transform: (String) throws -> Value)` converts the raw string into
  the property's type; throwing (e.g. `ValidationError`) rejects the input.
- **`validate()`** — a `ParsableArguments`/`ParsableCommand` type may implement
  `func validate() throws`, run automatically after a successful parse; throwing turns a
  syntactically valid parse into a failure.
- **`ValidationError(_ message: String)`** — an error carrying a custom message; maps to the
  validation exit code.
- **`CleanExit`** — a non-error termination; `CleanExit.message(_:)` creates one. Maps to success.

---

## 8. Exit codes — `ExitCode`

`ExitCode` is an `Error` wrapping an `Int32` code:

- `ExitCode.success` (`rawValue == 0`), `ExitCode.failure`, `ExitCode.validationFailure`.
- `init(_ code: Int32)` and `init(rawValue: Int32)`; a `rawValue` property; `var isSuccess: Bool`
  (true iff the code is the success code).

`exitCode(for:)` maps: a `ValidationError` → `.validationFailure`; an `ExitCode` → itself; a
`CleanExit` → `.success`; other errors → `.failure`.

---

## 9. `@OptionGroup` and commands

### `@OptionGroup`

`@OptionGroup var options: Shared` embeds another `ParsableArguments` type's properties into the
enclosing type, so they parse as if declared inline. Used to share common options and to compose
subcommands.

### `CommandConfiguration`

`ParsableCommand` types provide `static let configuration = CommandConfiguration(...)`:

- `commandName: String?` — the name on the command line (default: the type name, lowercased).
- `abstract: String` — one-line description for help.
- `subcommands: [ParsableCommand.Type]` — child commands, forming a tree.
- `defaultSubcommand: ParsableCommand.Type?` — chosen when no subcommand token is present.
- `aliases: [String]` — alternative names that resolve to this command.

`parseAsRoot` walks the tree: `math add 1 2 3` selects the `add` subcommand and returns its
instance; an alias resolves to the same command; a `defaultSubcommand` is used when no child name
is given (`math 1 2` → the default child, receiving `1 2`); nested trees resolve the full path and
return the leaf. An unknown subcommand name is an error.

---

## 10. Help generation

`helpMessage(includeHidden:columns:)` renders a help screen. For

```swift
struct A: ParsableArguments {
  @Option(help: "Your name") var name: String
  @Option(help: "Your title") var title: String?
}
```

`A.helpMessage(includeHidden: false, columns: 80)` returns exactly the following. The returned
string ends with a single trailing newline (the final `-h, --help` entry line is followed by
exactly one `\n`), with no trailing blank line:

```
USAGE: a --name <name> [--title <title>]

OPTIONS:
  --name <name>           Your name
  --title <title>         Your title
  -h, --help              Show help information.
```

Format rules shown above:

- `USAGE:` line lists the command name then each argument. Required options/arguments appear bare
  (`--name <name>`, `<phrase>`); optional ones are bracketed (`[--title <title>]`). An option's
  value placeholder is `<name>` (the long name) unless a custom `valueName` is given.
- Sections `ARGUMENTS:` (positional) and `OPTIONS:` (options/flags), each present only if it has
  visible entries. Entries are indented two spaces; the help text starts at a fixed column (the
  label is padded to width 24, i.e. the description begins 24 characters after the two-space
  indent), or wraps to the next line indented to that column when the label is too long.
- A built-in `-h, --help              Show help information.` entry is always appended to
  `OPTIONS:`.
- A defaulted option with no help text shows `(default: <value>)`; with help text the help is
  shown. Example option lines: `  --two <two>             (default: 42)` and
  `  --three <three>         The third option`.
- An `ArgumentHelp(_ abstract:, discussion:)` renders the abstract on the entry line and the
  discussion as an indented paragraph on the following line(s), indented six spaces beyond the
  entry indent:
  ```
    --name <name>           Your name.
          Your name is used to greet you and say hello.
  ```
- `ArgumentHelp.hidden` (or `help: .hidden`) omits the entry unless `includeHidden` is true.
- Subcommands appear in a `SUBCOMMANDS:` section.

---

## 11. Error messages

`message(for:)` returns the brief text below (no `Error:` prefix). Reproduce exactly.

For `struct Bar { @Option var name: String; @Option(name: [.short, .long]) var format: String }`:

| Input | `message(for:)` |
|---|---|
| `[]` | `Missing expected argument '--name <name>'` |
| `--name a` | `Missing expected argument '--format <format>'` |
| `--name a --format b --verbose` | `Unknown option '--verbose'` |
| `--name a --format` | `Missing value for '--format <format>'` |
| `--name a --format f b` | `Unexpected argument 'b'` |
| `--name a --format f b baz` | `2 unexpected arguments: 'b', 'baz'` |

**Missing** required arguments, **unknown** options, **missing value** for an option, and one or
more **unexpected** arguments each have the forms above. A positional's placeholder in these
messages is kebab-cased (e.g. a `firstNumber` positional appears as `<first-number>`).

**Invalid enumerable value.** For a value that is not a valid case, list the valid values. With a
few cases, inline with Oxford-style "or":

```
The value 'png' is invalid for '--format <format>'. Please provide one of 'text', 'json' or 'csv'.
```

With many cases, a bulleted list (each `  - <case>` on its own line):

```
The value 'loki' is invalid for '--name <name>'. Please provide one of the following:
  - bruce
  - clint
  - hulk
  - natasha
  - steve
  - thor
  - tony
```

**"Did you mean".** An unknown option close (by edit distance) to a known one appends a
suggestion, matching the offending token's dash style; a distant token gets none:

```
Unknown option '--nme'. Did you mean '--name'?
Unknown option '-ttle'. Did you mean '-title'?
Unknown option '--not-similar'
```

**Mutually-exclusive flag conflict.** When an exclusive flag or its inverse is set twice, name
both the offending flag and the one that already set the value:

```
Value to be set with flag '-s' had already been set with flag '--list'
Value to be set with flag '--bool' had already been set with flag '--no-bool'
```

---

## 12. Completion scripts

`completionScript(for:)` takes a `CompletionShell` (with cases including `.bash`, `.zsh`, `.fish`)
and returns a shell script that registers completion for the command and enumerates its named
arguments (options and flags) and subcommands. Requirements the generated scripts must satisfy:

- **bash**: registers via a line of the form `complete -o filenames -F <function> <command-name>`,
  and the script references the command name, each option's and flag's long name, and each
  subcommand name.
- **zsh**: begins with a `#compdef <command-name>` directive, and references each option's and
  flag's long name and each subcommand name.
