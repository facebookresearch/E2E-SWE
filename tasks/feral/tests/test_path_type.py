"""Path built-in type tests.

`.path()` on a Str produces a Path (§7.3 Path row); Path exposes a bundled
filesystem-path API (`isAbsolute`/`isRelative`, `parent`/`file`/`fileName`/
`fileExt`/`hasFile`/`hasFileExt`, `hasRoot`, `empty`, and the `/` join
operator) documented in §7.3.
"""

from _helpers import run_feral


def test_path_type_methods_split_join_and_predicates():
    """The Path type documented in §7.3 covers three families of operations
    used together to inspect and compose filesystem paths:
      1. Segment splitters: `.parent()` (parent directory Path), `.file()`
         (leaf-name Path INCLUDING extension), `.fileName()` (leaf-name Path
         WITHOUT extension), `.fileExt()` (extension Path including the dot).
         Each returns a Path; `.str()` on a Path yields its textual form.
      2. Predicates: `.isAbsolute()` / `.isRelative()` (Bool), `.hasFile()`,
         `.hasFileExt()`, `.hasRoot()`, `.empty()`.
      3. Join operator `p / other`: returns a NEW Path with `other` (Str or
         Path) appended -- the original Path is unchanged.
    Together these are the minimum surface a caller needs to decompose,
    classify, and reassemble a path -- so we cover them in one workflow test
    rather than fragmenting across every getter.
    """
    src = """
let io = import('std/io');

# 1. Split a mixed relative path into its components.
let p = 'foo/bar/baz.txt'.path();
io.println(p.file().str());              # 'baz.txt'  (leaf with extension)
io.println(p.fileName().str());          # 'baz'      (leaf without extension)
io.println(p.fileExt().str());           # '.txt'     (extension w/ leading dot)
io.println(p.parent().str());            # 'foo/bar'  (parent directory)

# 2. Predicate cluster on the same relative path.
io.println(p.isAbsolute());              # false
io.println(p.isRelative());              # true
io.println(p.empty());                   # false
io.println(p.hasFile());                 # true
io.println(p.hasFileExt());              # true
io.println(p.hasRoot());                 # false

# 3. Join operator `/` builds a new Path; original is unchanged.
let base = 'foo'.path();
let joined = base / 'bar.log';
io.println(joined.file().str());         # 'bar.log'
io.println(joined.parent().str());       # 'foo'
io.println(base.str());                  # 'foo'  (unchanged: `/` is pure)

# 4. Absolute paths flip the relative/absolute predicates.
let abs = '/tmp/x.dat'.path();
io.println(abs.isAbsolute());            # true
io.println(abs.isRelative());            # false
io.println(abs.hasRoot());               # true

# 5. Empty path.
let e = ''.path();
io.println(e.empty());                   # true
"""
    r = run_feral(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout == (
        "baz.txt\n"
        "baz\n"
        ".txt\n"
        "foo/bar\n"
        "false\n"
        "true\n"
        "false\n"
        "true\n"
        "true\n"
        "false\n"
        "bar.log\n"
        "foo\n"
        "foo\n"
        "true\n"
        "false\n"
        "true\n"
        "true\n"
    )
