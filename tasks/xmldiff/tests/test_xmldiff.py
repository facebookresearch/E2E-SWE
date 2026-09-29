"""Integration tests for a from-scratch xmldiff implementation.

These tests assert the exact, deterministic edit-script output of the tree-diff
engine (the bespoke FMES matcher + differ), the DiffFormatter text grammar, the
three formatters, the patch round-trip, the xpath conventions, and the two CLIs.

Each test is a distinct function (no parametrization) so pytest-json-ctrf reports
one entry per assertion area.
"""
import io
import subprocess


from lxml import etree

from xmldiff import main, formatting
from xmldiff.patch import Patcher, DiffParser
from xmldiff.actions import (
    DeleteNode,
    InsertNode,
    RenameNode,
    MoveNode,
    UpdateTextIn,
    UpdateTextAfter,
    UpdateAttrib,
    DeleteAttrib,
    InsertAttrib,
    RenameAttrib,
    InsertComment,
    InsertNamespace,
    DeleteNamespace,
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def diff(left, right, **opts):
    return main.diff_texts(left, right, diff_options=opts or None)


def diff_str(left, right, **opts):
    return main.diff_texts(
        left, right, diff_options=opts or None, formatter=formatting.DiffFormatter()
    )


def canon(xml):
    return etree.tostring(etree.fromstring(xml))


# --------------------------------------------------------------------------- #
# 1. Edit-script vocabulary & exact output (the FMES core)
# --------------------------------------------------------------------------- #
def test_text_update_editscript():
    L = "<document><p>Text</p><p>More</p></document>"
    R = "<document><p>Tokst</p><p>More</p></document>"
    assert diff(L, R) == [
        UpdateTextIn(node="/document/p[1]", text="Tokst", oldtext="Text")
    ]


def test_tail_update_editscript():
    L = "<doc><a/>tail1<b/></doc>"
    R = "<doc><a/>tail2<b/></doc>"
    assert diff(L, R) == [
        UpdateTextAfter(node="/doc/a[1]", text="tail2", oldtext="tail1")
    ]


def test_insert_node_editscript():
    L = "<document><p>x</p></document>"
    R = "<document><p>x</p><p>y</p></document>"
    assert diff(L, R) == [
        InsertNode(target="/document[1]", tag="p", position=1),
        UpdateTextIn(node="/document/p[2]", text="y", oldtext=None),
    ]


def test_delete_node_editscript():
    # A leaf present on the left but gone on the right is removed, and nothing
    # else happens. Under the §2 node representation these empty leaves reduce to
    # their bare tags, so <b/> is not similar enough to any right-hand node to be
    # paired while <a/> and <c/> match their namesakes: the whole script is one
    # DeleteNode at the §4 xpath of <b/>.
    L = "<document><a/><b/><c/></document>"
    R = "<document><a/><c/></document>"
    es = diff(L, R)
    assert es == [DeleteNode(node="/document/b[1]")]
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


def test_rename_node_editscript():
    L = "<document><p>Hello there how are you</p></document>"
    R = "<document><h1>Hello there how are you</h1></document>"
    assert diff(L, R) == [RenameNode(node="/document/p[1]", tag="h1")]


def test_move_node_editscript():
    # First: a subtree relocated under a different parent must round-trip. Whether
    # an explicit MoveNode appears here depends on how the near-identical empty
    # <b>/<d> parents are paired: their self-similarity is an exact tie, and
    # cross-matching them (each a legitimate RenameNode) leaves <c> under its
    # renamed parent with no move. The spec does not break that tie, so -- like the
    # suite's other tie-sensitive move tests (test_deep_cross_level_move,
    # test_sibling_reorder_alignment) -- assert only the observable round-trip the
    # spec DOES pin (§3) for this input, not that a MoveNode is emitted.
    L = "<a><b><c/></b><d/></a>"
    R = "<a><b/><d><c/></d></a>"
    es = diff(L, R)
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)
    # On a tie-free input the exact MoveNode is pinned. Rotating three siblings
    # whose tags and texts are pairwise disjoint admits only one matching (each
    # leaf pairs with its namesake) and only one longest common subsequence
    # ([b, c]), so the minimum realignment (§2) is the single move of <a>, whose
    # `target` is the new parent's xpath and whose `position` is its child index
    # there.
    assert diff(
        "<r><a>1111</a><b>2222</b><c>3333</c></r>",
        "<r><b>2222</b><c>3333</c><a>1111</a></r>",
    ) == [MoveNode(node="/r/a[1]", target="/r[1]", position=2)]


def test_identical_documents_yield_empty_script():
    L = "<doc><p>same</p><p>here</p></doc>"
    assert diff(L, L) == []


# --------------------------------------------------------------------------- #
# 2. Attribute diffing (canonical sorted order, rename detection)
# --------------------------------------------------------------------------- #
def test_attribute_insert_and_delete_order():
    # 'a' unchanged, 'b' removed, 'c' added -> insert before delete.
    L = '<node a="1" b="2"/>'
    R = '<node a="1" c="3"/>'
    assert diff(L, R) == [
        InsertAttrib(node="/node[1]", name="c", value="3"),
        DeleteAttrib(node="/node[1]", name="b"),
    ]


def test_attribute_rename_detection():
    # same value under a new name -> a single RenameAttrib, not delete+insert.
    L = '<node a="1"/>'
    R = '<node b="1"/>'
    assert diff(L, R) == [
        RenameAttrib(node="/node[1]", oldname="a", newname="b")
    ]


def test_attribute_update_value():
    L = '<n a="1" timestamp="t1">text</n>'
    R = '<n a="2" timestamp="t2">text</n>'
    assert diff(L, R) == [
        UpdateAttrib(node="/n[1]", name="a", value="2"),
        UpdateAttrib(node="/n[1]", name="timestamp", value="t2"),
    ]


def test_ignored_attrs_excluded():
    L = '<n a="1" timestamp="t1">text</n>'
    R = '<n a="2" timestamp="t2">text</n>'
    assert diff(L, R, ignored_attrs=["timestamp"]) == [
        UpdateAttrib(node="/n[1]", name="a", value="2")
    ]


# --------------------------------------------------------------------------- #
# 3. Namespaces, comments, unique attributes
# --------------------------------------------------------------------------- #
def test_namespace_insert():
    L = "<doc><p>text</p></doc>"
    R = '<doc xmlns:x="http://x"><p>text</p></doc>'
    assert diff(L, R) == [InsertNamespace(prefix="x", uri="http://x")]


def test_namespace_delete_is_first():
    # The namespace-changed element is re-created as a new node (delete + insert), not
    # renamed. Which child index the new <p> takes while the doomed <x:p> is still in the
    # parent is a placement detail the spec does not pin -- inserting before or after the
    # sibling the script deletes later both leave <p> as the only child -- so assert the
    # insert itself plus the text update that populates it (whose §4 xpath is /doc/p[1]
    # either way), not the index.
    L = '<doc xmlns:x="http://x"><x:p>hi</x:p></doc>'
    R = "<doc><p>hi</p></doc>"
    es = diff(L, R)
    assert es[0] == DeleteNamespace(prefix="x")
    assert DeleteNode(node="/doc/x:p[1]") in es
    assert any(
        isinstance(a, InsertNode) and a.target == "/doc[1]" and a.tag == "p" for a in es
    )
    assert UpdateTextIn(node="/doc/p[1]", text="hi", oldtext=None) in es


def test_comment_insert():
    L = "<doc><p>a</p></doc>"
    R = "<doc><!-- hello --><p>a</p></doc>"
    assert diff(L, R) == [
        InsertComment(target="/doc[1]", position=0, text=" hello ")
    ]


def test_comment_changed_is_text_update():
    L = "<doc><!-- old comment text here --><p>a</p></doc>"
    R = "<doc><!-- new comment text here --><p>a</p></doc>"
    assert diff(L, R) == [
        UpdateTextIn(
            node="/doc/comment()[1]",
            text=" new comment text here ",
            oldtext=" old comment text here ",
        )
    ]


def test_xmlid_unique_attr_matching():
    # Nodes are matched by xml:id regardless of order/content: the reordered
    # siblings must be realigned (at least one MoveNode) and the node whose text
    # changed must be updated bbbb -> bzbb. Which sibling is reported as the moved
    # one (and its xpath/position) is not pinned by the spec, so assert the
    # observable invariants plus a successful round-trip instead.
    L = '<doc><n xml:id="a1">aaaa</n><n xml:id="a2">bbbb</n></doc>'
    R = '<doc><n xml:id="a2">bzbb</n><n xml:id="a1">aaaa</n></doc>'
    es = diff(L, R)
    assert any(isinstance(a, MoveNode) for a in es)
    assert any(
        isinstance(a, UpdateTextIn) and a.text == "bzbb" and a.oldtext == "bbbb"
        for a in es
    )
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


# --------------------------------------------------------------------------- #
# 4. Richer multi-action diffs (matcher must pick the right partners)
# --------------------------------------------------------------------------- #
def test_rich_mixed_editscript():
    # A multi-change diff must rename <h> -> <title>, delete <foot>, and insert a
    # new <p>three</p>, plus realign the reordered <p>s. The exact global ordering
    # of move/rename/insert/update/delete across different nodes is not pinned by
    # the spec, so assert the key actions are present and the script round-trips.
    L = "<doc><h>Header</h><p>one</p><p>two</p><foot>Footer</foot></doc>"
    R = "<doc><title>Header</title><p>two</p><p>one</p><p>three</p></doc>"
    es = diff(L, R, ratio_mode="accurate")
    assert any(isinstance(a, RenameNode) and a.tag == "title" for a in es)
    assert any(isinstance(a, DeleteNode) and "foot" in a.node for a in es)
    assert any(isinstance(a, InsertNode) for a in es)
    assert any(isinstance(a, UpdateTextIn) and a.text == "three" for a in es)
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


def test_sibling_reorder_alignment():
    # Reordering [a,b,c,d] -> [c,a,d,b] is realigned with the minimum set of
    # MoveNode actions (two moves), but which two of the equal-length common
    # subsequences the algorithm keeps stable is a tie the spec does not break.
    # Assert exactly two moves and a successful round-trip, not the specific pair.
    L = "<r><a>1111</a><b>2222</b><c>3333</c><d>4444</d></r>"
    R = "<r><c>3333</c><a>1111</a><d>4444</d><b>2222</b></r>"
    es = diff(L, R, ratio_mode="accurate")
    assert sum(1 for a in es if isinstance(a, MoveNode)) == 2
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


def test_deep_cross_level_move():
    # Whether the matcher pairs differently-tagged elements across the 0.5
    # threshold on the strength of a shared child depends on the exact similarity
    # formula, which the spec only describes qualitatively. Pin the observable
    # outcome via a round-trip rather than the exact move/rename script.
    L = "<root><sec><p>alpha beta</p></sec><sec2/></root>"
    R = "<root><sec/><sec2><p>alpha beta</p></sec2></root>"
    es = diff(L, R, ratio_mode="accurate")
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


def test_best_match_produces_valid_roundtrip():
    L = "<r><item>apple banana cherry</item><item>dog elephant frog</item></r>"
    R = ("<r><item>dog elephant frog grape</item>"
         "<item>apple banana cherry kiwi</item></r>")
    es = diff(L, R, ratio_mode="accurate", best_match=True)
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


# --------------------------------------------------------------------------- #
# 5. Similarity-driven matching (observable behaviour)
# --------------------------------------------------------------------------- #
def test_similar_node_is_updated_not_replaced():
    # Two children share most of their text -> matched -> a text update, not a
    # delete + insert. This pins the F=0.5 similarity threshold behaviour.
    L = "<doc><p>The quick brown fox jumps over</p></doc>"
    R = "<doc><p>The quick brown fox leaps over</p></doc>"
    assert diff(L, R, ratio_mode="accurate") == [
        UpdateTextIn(
            node="/doc/p[1]",
            text="The quick brown fox leaps over",
            oldtext="The quick brown fox jumps over",
        )
    ]


def test_dissimilar_node_is_replaced_not_updated():
    # Below the similarity threshold the nodes don't match: the old one is
    # deleted and a new one inserted (no UpdateTextIn). The two texts share no
    # characters and are the same length, so the pair scores well below F=0.5
    # under any reasonable node representation (not just at the boundary).
    L = "<doc><p>aaaaaaaaaaaa</p></doc>"
    R = "<doc><p>zzzzzzzzzzzz</p></doc>"
    es = diff(L, R, ratio_mode="accurate")
    kinds = {type(a).__name__ for a in es}
    assert "InsertNode" in kinds
    assert "DeleteNode" in kinds
    # The old <p> was not kept-and-updated in place: no action rewrites its
    # existing text ('aaaaaaaaaaaa') into the new value.
    assert not any(
        isinstance(a, UpdateTextIn) and a.oldtext == "aaaaaaaaaaaa" for a in es
    )


# --------------------------------------------------------------------------- #
# 7. DiffFormatter text grammar + DiffParser inverse
# --------------------------------------------------------------------------- #
def test_diffformatter_single_lines():
    # Each rendered line uses the DiffFormatter grammar: the hyphen-joined action
    # name, bare xpaths, JSON-quoted text, bare integer positions. The update-text
    # and delete inputs give a single unambiguous action, so their exact rendered
    # line is derivable.
    assert (
        diff_str("<document><p>Text</p></document>", "<document><p>Tokst</p></document>")
        == '[update-text, /document/p[1], "Tokst", "Text"]'
    )
    assert (
        diff_str(
            "<document><para>keep this paragraph</para><gone>remove this node</gone></document>",
            "<document><para>keep this paragraph</para></document>",
        )
        == "[delete, /document/gone[1]]"
    )
    # A leaf with distinctive text relocates between two same-named parents. Which
    # left node pairs with which right node when both same-tag parents are equally
    # self-similar and a shared child migrates is decided by the similarity
    # computation, which the spec describes only qualitatively; a faithful reading
    # can legitimately keep the same-tag pairs (the <item> emitted as its own move)
    # or cross-match the parents (a rename/update/move cascade in which the <item>
    # rides under its cross-matched parent, with no item MoveNode). The spec does
    # not break this tie, so -- like the suite's other move tests
    # (test_move_node_editscript, test_deep_cross_level_move) -- assert only the
    # observable contract the spec DOES pin: the DiffFormatter->DiffParser round-trip
    # reproduces the right tree, rather than pinning which node carries the move.
    Lc = ("<catalog><electronics>phones and laptops galore</electronics>"
          "<groceries>fruits and vegetables fresh<item>the special product</item></groceries></catalog>")
    Rc = ("<catalog><electronics>phones and laptops galore<item>the special product</item></electronics>"
          "<groceries>fruits and vegetables fresh</groceries></catalog>")
    text = diff_str(Lc, Rc)
    parsed = list(DiffParser().parse(text))
    patched = Patcher().patch(parsed, etree.fromstring(Lc))
    assert etree.tostring(patched) == canon(Rc)


def test_diffformatter_attribute_lines():
    assert (
        diff_str('<node a="1" b="2"/>', '<node a="1" c="3"/>')
        == '[insert-attribute, /node[1], c, "3"]\n[delete-attribute, /node[1], b]'
    )
    assert (
        diff_str('<node a="1"/>', '<node b="1"/>')
        == "[rename-attribute, /node[1], a, b]"
    )
    assert (
        diff_str("<doc><a/>tail1<b/></doc>", "<doc><a/>tail2<b/></doc>")
        == '[update-text-after, /doc/a[1], "tail2", "tail1"]'
    )


def test_diffformatter_insert_renders_null_oldtext():
    out = diff_str("<document><p>x</p></document>",
                   "<document><p>x</p><p>y</p></document>")
    assert out == (
        "[insert, /document[1], p, 1]\n"
        '[update-text, /document/p[2], "y", null]'
    )


def test_diffparser_roundtrips_formatter():
    L = ('<doc id="1"><title>Old Title</title>'
         "<body><p>First para</p><p>Second</p></body></doc>")
    R = ('<doc id="2"><heading>New Title</heading>'
         "<body><p>First para</p><p>Second</p><p>Third</p></body></doc>")
    text = diff_str(L, R)
    parsed = list(DiffParser().parse(text))
    # The root attribute update is present (parser does not restore oldtext); its
    # absolute position in the script is not pinned by the spec, so assert
    # membership like the other two actions rather than index 0.
    assert UpdateAttrib(node="/doc[1]", name="id", value="2") in parsed
    assert RenameNode(node="/doc/title[1]", tag="heading") in parsed
    assert InsertNode(target="/doc/body[1]", tag="p", position=2) in parsed
    # The parsed script must apply back to L to reproduce R (oldtext is not needed
    # to patch), confirming the formatter->parser round-trip is faithful.
    patched = Patcher().patch(parsed, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


# --------------------------------------------------------------------------- #
# 8. Patching & round-trip
# --------------------------------------------------------------------------- #
def test_patch_tree_roundtrip():
    L = "<document><p>Text</p><p>More</p></document>"
    R = "<document><p>Tokst</p><p>More</p></document>"
    es = diff(L, R)
    patched = Patcher().patch(es, etree.fromstring(L))
    assert etree.tostring(patched) == canon(R)


def test_patch_does_not_mutate_input():
    L = "<doc><p>a</p></doc>"
    R = "<doc><p>b</p></doc>"
    tree = etree.fromstring(L)
    before = etree.tostring(tree)
    Patcher().patch(diff(L, R), tree)
    assert etree.tostring(tree) == before


def test_patch_file_stream_roundtrip():
    # main.patch_file is the file/stream analogue of patch_text: the diff and the
    # XML both arrive as open streams (not strings). Exercise it on a multi-action
    # diff (an attribute insert plus a text update) so it covers a distinct surface
    # from the in-memory tree patch above.
    L = '<doc><item a="1">old</item></doc>'
    R = '<doc><item a="1" b="2">new</item></doc>'
    text = diff_str(L, R)
    out = main.patch_file(io.StringIO(text), io.StringIO(L))
    assert canon(out) == canon(R)


def test_patch_text_comment_roundtrip():
    # main.patch_text on a comment-centric diff: a changed comment (UpdateTextIn on
    # the comment node) plus an inserted comment. This drives patch_text over the
    # comment actions specifically -- a surface the formatter->parser round-trip and
    # the other patch tests don't reach (they cover attribute/rename/insert and
    # node text only, never comment insert/update through patch_text).
    L = "<doc><!-- old comment --><p>keep</p></doc>"
    R = "<doc><!-- new comment --><p>keep</p><!-- trailing --></doc>"
    text = diff_str(L, R)
    assert canon(main.patch_text(text, L)) == canon(R)


# --------------------------------------------------------------------------- #
# 9. Other formatters
# --------------------------------------------------------------------------- #
def test_xml_formatter_inline_annotation():
    out = main.diff_texts(
        "<doc><p>old text here</p></doc>",
        "<doc><p>new text here</p></doc>",
        formatter=formatting.XMLFormatter(),
    )
    assert 'xmlns:diff="http://namespaces.shoobx.com/diff"' in out
    assert "<diff:delete>old</diff:delete>" in out
    assert "<diff:insert>new</diff:insert>" in out
    assert "text here" in out


def test_old_formatter_output():
    out = main.diff_texts(
        "<doc><p>Text</p></doc>",
        "<doc><p>Tokst</p></doc>",
        formatter=formatting.XmlDiffFormatter(),
    )
    assert out == '[update, /doc/p[1]/text()[1], "Tokst"]'


# --------------------------------------------------------------------------- #
# 10. Command-line tools
# --------------------------------------------------------------------------- #
def test_cli_xmldiff_default(tmp_path):
    l = tmp_path / "l.xml"
    r = tmp_path / "r.xml"
    l.write_text("<doc><p>Text</p></doc>")
    r.write_text("<doc><p>Tokst</p></doc>")
    out = subprocess.run(
        ["xmldiff", str(l), str(r)], capture_output=True, text=True
    )
    assert out.returncode == 0
    assert out.stdout.strip() == '[update-text, /doc/p[1], "Tokst", "Text"]'


def test_cli_xmldiff_old_formatter(tmp_path):
    l = tmp_path / "l.xml"
    r = tmp_path / "r.xml"
    l.write_text("<doc><p>Text</p></doc>")
    r.write_text("<doc><p>Tokst</p></doc>")
    out = subprocess.run(
        ["xmldiff", str(l), str(r), "-f", "old"], capture_output=True, text=True
    )
    assert out.stdout.strip() == '[update, /doc/p[1]/text()[1], "Tokst"]'


def test_cli_xmldiff_check_exit_codes(tmp_path):
    l = tmp_path / "l.xml"
    r = tmp_path / "r.xml"
    l.write_text("<doc><p>Text</p></doc>")
    r.write_text("<doc><p>Tokst</p></doc>")
    same = subprocess.run(
        ["xmldiff", str(l), str(l), "--check"], capture_output=True, text=True
    )
    differ = subprocess.run(
        ["xmldiff", str(l), str(r), "--check"], capture_output=True, text=True
    )
    assert same.returncode == 0
    assert differ.returncode == 1


def test_cli_xmlpatch_roundtrip(tmp_path):
    l = tmp_path / "l.xml"
    p = tmp_path / "patch.diff"
    l.write_text("<doc><p>Text</p></doc>")
    p.write_text(diff_str("<doc><p>Text</p></doc>", "<doc><p>Tokst</p></doc>"))
    out = subprocess.run(
        ["xmlpatch", str(p), str(l)], capture_output=True, text=True
    )
    assert canon(out.stdout) == canon("<doc><p>Tokst</p></doc>")
