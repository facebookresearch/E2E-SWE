# Build a Java source-code generation library (JavaPoet)

## Overview

JavaPoet is a library for **generating Java source code programmatically**. Instead of building
strings by hand, you assemble an in-memory model of a Java file from small immutable objects and ask
the library to render it as correctly-formatted, correctly-imported `.java` source — the kind of tool
an annotation processor or code generator uses to emit boilerplate. This document is
**self-contained**; you should not need prior familiarity with the library (package
`com.squareup.javapoet`).

### A first example

A `HelloWorld` class with a `main` method:

```java
MethodSpec main = MethodSpec.methodBuilder("main")
    .addModifiers(Modifier.PUBLIC, Modifier.STATIC)
    .addParameter(ArrayTypeName.of(ClassName.get("java.lang", "String")), "args")
    .addStatement("$T.out.println($S)", ClassName.get("java.lang", "System"), "Hello, JavaPoet!")
    .build();
TypeSpec helloWorld = TypeSpec.classBuilder("HelloWorld")
    .addModifiers(Modifier.PUBLIC, Modifier.FINAL)
    .addMethod(main)
    .build();
JavaFile file = JavaFile.builder("com.example.helloworld", helloWorld).build();
```

`file.toString()` produces:

```java
package com.example.helloworld;

import java.lang.String;
import java.lang.System;

public final class HelloWorld {
  public static void main(String[] args) {
    System.out.println("Hello, JavaPoet!");
  }
}
```

Notice how `JavaFile` collected the imports and the body used simple names, the `$T`/`$S`
placeholders filled in the type and the quoted string, and a method with no explicit return type
renders `void`.

### The building blocks

The model is small and composes bottom-up:

- **`TypeName`** and its subtypes name a Java *type*: `TypeName.INT` (primitive), `ClassName`
  (class/interface), `ParameterizedTypeName` (generic), `ArrayTypeName`, `WildcardTypeName`,
  `TypeVariableName`.
- The immutable **`*Spec`** builders describe *declarations* and **nest**: a **`TypeSpec`** (class,
  interface, enum, or annotation type) holds **`FieldSpec`**s and **`MethodSpec`**s; a `MethodSpec`
  holds **`ParameterSpec`**s and a body; **`AnnotationSpec`** is an annotation applied to a spec.
  Each is built with a fluent `Builder` finished by `build()`.
- **`CodeBlock`** is a fragment of code — a method body, a field initializer — written with
  `$`-placeholders instead of concatenation: `$T` a type, `$S` a string literal, `$L` a literal,
  `$N` a name. E.g. `CodeBlock.of("$T name = $S", ClassName.get("java.lang", "String"), "Lee")`
  renders `java.lang.String name = "Lee"`.
- **`JavaFile`** wraps one top-level `TypeSpec` into a compilation unit: it prints the `package` line,
  **collects and sorts imports** so referenced types render by their simple names, and emits the type.

A couple more specs rendered on their own via `toString()`:

```java
MethodSpec.methodBuilder("add").addModifiers(Modifier.PUBLIC).returns(TypeName.INT)
    .addParameter(TypeName.INT, "a").addParameter(TypeName.INT, "b")
    .addStatement("return a + b").build()
//  ->  public int add(int a, int b) {
//        return a + b;
//      }

FieldSpec.builder(TypeName.INT, "count", Modifier.PRIVATE, Modifier.FINAL).initializer("$L", 0).build()
//  ->  private final int count = 0;
```

**One rule runs throughout:** a spec printed **on its own** via `toString()` uses
**fully-qualified** type names (e.g. `java.util.List<java.lang.String>`); the **same** spec placed
inside a `JavaFile` is printed with **imports collected + simple names** (as in HelloWorld above). The
sections below give each construct's exact rendering contract — not a line-by-line blueprint; the
formatting rules are the observable behavior your output must match, and how you implement them is up
to you.

## Project layout and build

- Source language: **Java** (source/target 8 or later).
- All your library code must live as `.java` files under `/app/src/` in the package
  **`com.squareup.javapoet`**. Provide `/app/setup.sh` that compiles every source into `/app/out`,
  roughly:

  ```bash
  mkdir -p /app/out
  find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
  ```

  The grader then compiles a hidden Java test suite against `/app/out` and runs it.
- The environment is **offline**: no dependency may be downloaded. JavaPoet has **no external runtime
  dependencies** — it uses only the JDK (`javax.lang.model.element.Modifier` for modifiers, and the
  reflection/`java.lang.model` types referenced by the `get(...)` factories). Do not add a
  Gradle/Maven build.
- **Your entire `/app/src` must compile.** There is no partial credit for a capability whose harness
  fails to compile against your classes: a missing or wrongly-typed public method fails every test
  in that group. Keep the **exact package, type names, and public signatures** given below, because
  the tests import and call them.
- Keep no `main` method and no test files under `/app/src`.

## Global rendering contract

Individual specs render through `toString()`; a whole file renders through `JavaFile`. These rules
are **observable output contracts** the tests assert on exact strings.

1. **Indentation** is two spaces per level.
2. **Standalone qualification.** A spec rendered on its own via `toString()` (a `FieldSpec`,
   `MethodSpec`, `TypeSpec`, `AnnotationSpec`, `CodeBlock`, or any `TypeName`) prints every referenced
   type by its **fully-qualified canonical name** — e.g. `java.lang.String`, `java.util.List`. Import
   collection and simple-name emission happen **only** inside a `JavaFile` (see *JavaFile & imports*).
3. **Trailing newline.** `toString()` of a `FieldSpec`, `MethodSpec`, `TypeSpec`, and of a
   `CodeBlock` produced by `addStatement`/control-flow ends with a single `\n`. A `TypeName`, a
   `ParameterSpec`, an `AnnotationSpec`, and a bare `CodeBlock.of(...)` do **not** add a trailing
   newline.
4. **Modifier order** follows the JLS canonical order: `public`/`protected`/`private`, `abstract`,
   `default`, `static`, `final`, … (e.g. `private final`, `public static`, `static final`).
5. **Blank lines between members.** Consecutive members of a type body (fields, methods, nested
   types, initializer blocks) are separated by exactly one blank line; there is no blank line right
   after the opening `{` or right before the closing `}`.
6. **Line wrapping at column 100.** A method/constructor declaration is kept within 100 columns.
   If its single-line form fits, emit it as one line. Otherwise lay it out **greedily, left to
   right**, breaking only at fixed **wrap points** and putting each break on a **continuation line
   indented 4 spaces beyond the declaration's own indentation**. All continuation lines of one
   declaration share that same 4-space-deeper indent (they do not nest progressively deeper). The
   wrap points are: right after the opening `(` (before the first parameter, or — for an empty
   parameter list — before the closing `)`), before each later parameter, before the `throws`
   keyword, and before each exception. Starting from the declaration head
   (`[modifiers] [<type-vars>] returnType name(`), keep appending the next token while it still fits
   within 100 columns; when it would exceed 100, break at its wrap point onto a fresh continuation
   line and keep filling from there.
   - Every parameter's fit check includes the trailing punctuation that follows it on the same line
     — the `,` before the next parameter, or the closing `) {` (or the `)` before a `throws` clause)
     after the last/only parameter. So the **first parameter** stays on the declaration line only
     when the head *plus* that parameter *plus* that trailing punctuation is within 100 columns;
     otherwise the declaration line ends right after `(` and the first parameter begins on a 4-space
     continuation line. For a method with **no parameters** whose head still exceeds 100 columns,
     the closing `)` itself moves to the continuation line — rendered as `name(` then a newline
     then `    ) {`.
   - In the **`throws` clause** the `throws` keyword and each exception are **independent** wrap
     tokens filled by the same greedy rule. After `)`, ` throws` is appended to the current line
     when it fits; it moves onto its own 4-space continuation line only when ` throws` alone does
     not fit after `)`.
   - The parameter list and the throws list wrap independently. Field declarations and
     class/interface headers are not auto-wrapped.

## `TypeName` and its subtypes

`TypeName` is the root of the type model; `ClassName`, `ParameterizedTypeName`, `ArrayTypeName`,
`WildcardTypeName`, and `TypeVariableName` are all **subtypes of `TypeName`** (so `TypeName` must be
non-final/extensible). All are immutable and print via `toString()` as their canonical form.

**Primitive & core constants** on `TypeName`: `VOID`, `BOOLEAN`, `BYTE`, `SHORT`, `INT`, `LONG`,
`CHAR`, `FLOAT`, `DOUBLE` (each `toString()` is its keyword, e.g. `TypeName.INT` → `int`), and
`OBJECT`. Methods: `box()` returns the boxed reference type (`TypeName.INT.box()` →
`java.lang.Integer`); `unbox()` returns the primitive of a boxed type
(`ClassName.get("java.lang","Integer").unbox()` → `int`); `isBoxedPrimitive()` returns whether the
type is a boxed primitive.

**Type-use annotations** — `annotated(AnnotationSpec... annotations)` returns a copy of the type
carrying type-use annotations, and they participate in `toString()`. A type-use annotation renders
immediately **before the type's final simple name**, after any package/enclosing qualifier — e.g.
`java.lang. @com.example.Nullable String` (note the space after the qualifier and the space
separating multiple annotations: `java.lang. @A @B String`). As a type argument it renders inside
the `<...>` the same way. The distinction on arrays is meaningful: annotating the **component type**
renders `@Nullable String[]`, whereas annotating the **`ArrayTypeName` itself** renders after the
component, before the brackets — `String @Nullable []`.

### `ClassName` — a declared class or interface

- `ClassName.OBJECT` (equals `ClassName.get("java.lang","Object")`).
- `ClassName.get(Class<?>)`; `ClassName.get(String packageName, String simpleName, String... simpleNames)`
  (trailing names are nested classes); `ClassName.bestGuess(String)` parses a dotted string, treating
  segments that start lowercase as the package and the rest as (possibly nested) simple names.
- `nestedClass(String)` → the named nested class; `peerClass(String)` → a class with the same
  enclosing scope but a different final simple name; `simpleName()` → the last simple name;
  `canonicalName()` → dotted fully-qualified name (nested separated by `.`); `reflectionName()` →
  binary name (nested separated by `$`).
- `toString()` equals `canonicalName()`.

### `ParameterizedTypeName`

- `ParameterizedTypeName.get(ClassName rawType, TypeName... typeArguments)` → `Raw<A, B>` (type
  arguments separated by `, `). Arguments may themselves be parameterized, wildcards, or type
  variables.
- `nestedClass(String)` on a `ParameterizedTypeName` renders `Outer<A, B>.Inner`.

### `ArrayTypeName`

- `ArrayTypeName.of(TypeName componentType)` → `Component[]`; nesting yields `String[][]`; the
  component may be parameterized (`java.util.List<java.lang.String>[]`).

### `WildcardTypeName`

- `WildcardTypeName.subtypeOf(TypeName)` → `? extends Bound`, except `subtypeOf(OBJECT)` renders as
  bare `?`. `WildcardTypeName.supertypeOf(TypeName)` → `? super Bound`. Used as a type argument it
  renders inside the `<...>`.

### `TypeVariableName`

- `TypeVariableName.get(String name)` → the name (`T`). `TypeVariableName.get(String name, TypeName... bounds)`
  carries bounds that render **only at a declaration site** (see `MethodSpec`/`TypeSpec`), not in the
  variable's own `toString()`, which is just the name.

## `CodeBlock` and format placeholders

`CodeBlock` is immutable, created via `CodeBlock.of(String format, Object... args)` or
`CodeBlock.builder()`. Builder methods: `add(String format, Object... args)`,
`addNamed(String format, Map<String,?> args)`, `addStatement(String format, Object... args)`,
`beginControlFlow(String, Object...)`, `nextControlFlow(String, Object...)`, `endControlFlow()`,
`indent()`, `unindent()`, `build()`. `CodeBlock.join(Iterable<CodeBlock>, String separator)` joins
blocks with a separator.

Format placeholders:

- `$L` — a **literal**, emitted via `String.valueOf` with no quoting (numbers, booleans, another
  `CodeBlock`, a `TypeSpec`, an `AnnotationSpec`, …).
- `$S` — a **string literal**: the argument is wrapped in double quotes and escaped (`"` → `\"`,
  `\t`, `\b`, `\r`, `\f`, and backslash). A `null` argument emits the unquoted word `null`. An
  embedded newline splits the literal into one double-quoted piece per line, keeping each newline as
  a trailing `\n` inside its piece and joining the pieces with `\n` + two extra indent levels +
  `+ ` — e.g. `"line1\n"` newline `····+ "line2"`.
- `$T` — a `TypeName` (canonical form standalone; import-aware inside a `JavaFile`).
- `$N` — a **name**: the simple name of a spec (`FieldSpec`/`MethodSpec`/`ParameterSpec`/`TypeSpec`)
  or a raw string, emitted verbatim.
- `$$` — a literal dollar sign.
- **Positional** args: `$1L`, `$2L`, … reuse the Nth argument (1-based).
- **Named** args (via `addNamed`): `$name:L`, `$name:S`, etc., keyed into the supplied map.

`addStatement` appends a `;` and a newline. Control flow renders
`if (x > 0) {` … `} else {` … `}` with the body indented one level; `beginControlFlow` opens `<fmt> {`
and increases indent, `nextControlFlow` closes then re-opens (`} else {`), `endControlFlow` emits `}`.

## Specs

All specs are immutable, built through a fluent nested `Builder`; `build()` returns the spec. Common
builder methods across `FieldSpec`, `ParameterSpec`, `MethodSpec`, `TypeSpec`: `addModifiers(Modifier...)`,
`addAnnotation(ClassName)`/`addAnnotation(AnnotationSpec)`, `addJavadoc(String format, Object... args)`.
Annotations render on their own line(s) above the declaration; a `FieldSpec`/`MethodSpec` annotation
goes on the preceding line, a `ParameterSpec` annotation stays inline before the type.

### `FieldSpec`

`FieldSpec.builder(TypeName type, String name, Modifier... modifiers)`; `initializer(String format,
Object... args)`. `toString()` → `[annotations] [modifiers] Type name [= initializer];` + `\n`
(e.g. `private int count = 0;`). Javadoc renders as a `/** ... */` block above; a single trailing
newline in the javadoc text is absorbed (it does not add a blank line before the closing `*/`).

### `ParameterSpec`

`ParameterSpec.builder(TypeName type, String name, Modifier... modifiers)`. `toString()` →
`[annotations] [modifiers] Type name` (no newline). An annotation renders inline:
`@java.lang.Deprecated java.lang.String name`.

### `MethodSpec`

Factories `MethodSpec.methodBuilder(String name)` and `MethodSpec.constructorBuilder()`. Builder:
`returns(TypeName)`, `addParameter(TypeName type, String name, Modifier... modifiers)` /
`addParameter(ParameterSpec)`, `addException(TypeName)`, `addTypeVariable(TypeVariableName)`,
`varargs()`, `addStatement(...)`, `beginControlFlow`/`nextControlFlow`/`endControlFlow`,
`addCode(...)`, `addAnnotation(...)`.

Rendering:

- `[modifiers] [<TypeVars>] returnType name(params)[ throws E1, E2] { body }` + `\n`. A method with
  no explicit `returns` renders `void`.
- An `abstract` (or `native`) method renders with `;` in place of the `{ body }`.
- Body statements are indented one level; each `addStatement` line ends with `;`.
- **Type variable bounds** render at the declaration: a single bound renders inline as
  `<T extends Bound>` (multiple bounds joined by ` & `).
- **Varargs**: after `varargs()`, the final parameter's array type renders with `...` instead of
  `[]` (`java.lang.String... names`).
- **Constructors**: `constructorBuilder()` has no name; because a standalone `toString()` has no
  enclosing type, the constructor name renders as the placeholder **`Constructor`**
  (e.g. `public Constructor(int x) { ... }`).
- The `default` modifier (for interface default methods) renders `default` in canonical position.

### `TypeSpec`

Factories: `classBuilder(String)`, `interfaceBuilder(String)`, `enumBuilder(String)`,
`annotationBuilder(String)`, `anonymousClassBuilder(String constructorArgsFormat, Object... args)`.
Builder: `addModifiers(Modifier...)`, `addField(FieldSpec)` / `addField(TypeName, String, Modifier...)`,
`addMethod(MethodSpec)`, `addType(TypeSpec)`, `superclass(TypeName)`, `addSuperinterface(TypeName)`,
`addTypeVariable(TypeVariableName)`, `addEnumConstant(String)` /
`addEnumConstant(String name, TypeSpec anonymousBody)`, `addStaticBlock(CodeBlock)`,
`addInitializerBlock(CodeBlock)`, `addAnnotation(...)`.

Rendering:

- `[modifiers] class|interface|enum|@interface Name[<TypeVars>][ extends Super][ implements I1, I2] {`
  … members … `}` + `\n`. Members are emitted in the order **fields, then static/instance
  initializer blocks, then methods** (with exactly one blank line between members). A
  `class`/`interface` with no members still renders an empty `{\n}\n` body.
- **Interfaces**: `@interface` is the annotation-type keyword; a plain interface uses `interface`.
  Inside an `interface` or `@interface`, modifiers that are **implicit** for its members are elided:
  a member method drops `public`/`abstract` (e.g. `double area();`, not
  `public abstract double area();`).
- **Enums**: constants render one per line separated by a blank line, the last without a trailing
  comma, e.g. `RED,` blank `GREEN,` blank `BLUE`. A constant with an anonymous body
  (`addEnumConstant(name, TypeSpec.anonymousClassBuilder("")...)`) renders `NAME {` … body … `}`.
  When the enum also declares members (fields/methods/constructors), the constant list is terminated
  with a `;` on the last constant's line (e.g. `EARTH(5.97);`), followed by a blank line and then the
  members.
- **Anonymous classes** used as a `$L` argument render `new Super() { ... }` (with `addSuperinterface`
  choosing the supertype), suitable as a field initializer. The first argument to
  `anonymousClassBuilder` is a `CodeBlock` format for the **parenthesized constructor/superclass
  argument list** rendered after the supertype (or the enum-constant name), *not* generic type
  arguments.
- **Nested types** render indented in the body; `addStaticBlock` renders a `static { ... }` block and
  `addInitializerBlock` an instance `{ ... }` block (static block before instance block when both are
  present).

### `AnnotationSpec`

`AnnotationSpec.builder(ClassName type)`; `addMember(String name, String format, Object... args)`.
Rendering (`toString()`, no trailing newline):

- No members → `@Type`.
- A **single** member named `value` renders the value only: `@Type("unchecked")`. Any other single
  member renders `name = value`: `@Type(millis = 1000)`.
- Multiple **distinct** members render `@Type(a = 1, b = 2)` (comma-space separated, inline).
- **Repeating the same member name** collects the values into an array: two `addMember("value", ...)`
  calls render `@Type({"unchecked", "rawtypes"})`.
- Class literals and nested annotations are passed via `$T.class` and `$L` respectively
  (`@Type(type = java.lang.String.class)`, `@Outer(inner = @Inner("x"))`).

### `JavaFile` & imports

`JavaFile.builder(String packageName, TypeSpec typeSpec)`; builder methods `skipJavaLangImports(boolean)`,
`addStaticImport(ClassName className, String... names)`, `addFileComment(String format, Object... args)`,
`indent(String)`. `toString()` renders a full compilation unit and enables import collection.

- Layout: optional `// file comment` line(s) (immediately followed by the next section — **no**
  blank line after the comment); then `package <pkg>;` and a blank line — **both the package line
  and that blank line are omitted for the empty package**, so a default-package file begins directly
  with its imports (or, if none, the type); then the import block and a blank line; then the type.
  The import block lists **static imports first** (`import static pkg.Type.member;`), then a blank
  line, then **regular imports**, each group sorted lexicographically, one per line. The blank line
  between the static-import and regular-import groups appears **only when both groups are
  non-empty** (a file with static imports but no regular imports has a single blank line before the
  type, not two); the one blank line separating the whole import block from the type is always
  present.
- **Import collection.** Every referenced `ClassName` is imported and rendered by simple name,
  including `java.lang` types (`import java.lang.String;`) — **unless** `skipJavaLangImports(true)`,
  which drops `java.lang.*` imports while still rendering them by simple name. Types in the file's own
  package are **not** imported and render by simple name.
- **Nested types.** A reference to a nested `ClassName` (e.g. `ClassName.get("java.util","Map","Entry")`)
  imports the **top-level enclosing** class and renders the use site with the enclosing simple name
  prefix — `import java.util.Map;` and `Map.Entry` at the use site.
- **Collisions.** When two different classes share a simple name, the **first one encountered** wins
  the import and renders by simple name; every other colliding class renders by its **fully-qualified
  name** at the use site (no import). A class in the **file's own package** always wins its simple
  name (it needs no import), forcing any other same-simple-name class to be fully-qualified. Example:
  with `java.util.Date` added before `java.sql.Date`, the file imports `java.util.Date` and renders
  the other as `java.sql.Date`. Collisions are keyed on the **top-level simple name that is actually
  imported**, not a nested type's leaf `simpleName()`: a nested-type reference reserves its
  top-level enclosing class's simple name (`Map.Entry` reserves `Map`, see *Nested types* above), so
  it collides only with another class whose imported top-level simple name is also that name.
- **Static-import collapse.** A member registered via `addStaticImport(className, names...)` emits
  `import static <pkg>.<Type>.<member>;` in the static-import group, and every occurrence of that
  member written as `$T.member` (with `$T` the declaring class) is emitted by its **bare member
  name** — the declaring class is dropped and is **not** added to the regular imports. Example: with
  `addStaticImport(Collections, "emptyList")`, a body of `$T.emptyList()` (Collections) renders
  `return emptyList();` and the file imports only `import static java.util.Collections.emptyList;`
  (no `import java.util.Collections;`).
- **Custom indent** (`indent("    ")`) replaces the two-space unit throughout the file.

## `NameAllocator`

`new NameAllocator()`; `String newName(String suggestion)` and `String newName(String suggestion,
Object tag)` return a unique, legal Java identifier; `String get(Object tag)` looks up the name
allocated for a tag; static `String toJavaIdentifier(String)` normalises a string to a legal
identifier.

- `newName` returns the suggestion unchanged when it is free and legal.
- **Collisions** get a `_` appended until unique: allocating `foo` twice yields `foo` then `foo_`.
- A suggestion that is a **Java keyword** (e.g. `public`) is suffixed with `_` → `public_`.
- `toJavaIdentifier` replaces each character that is not a legal identifier part with `_`
  (`a-b c` → `a_b_c`), and prefixes `_` when the first character is not a legal identifier start
  (`1st` → `_1st`).
