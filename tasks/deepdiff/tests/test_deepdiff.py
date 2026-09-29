"""
End-to-end tests for deepdiff. Each passing workflow chains diff → hash → search →
extract → serialize → delta → verify in multi-step pipelines.
"""
import datetime
import unittest
from collections import OrderedDict
from decimal import Decimal

from deepdiff import DeepDiff, DeepHash, DeepSearch, Delta, extract, grep, parse_path


# =============================================================================
# MEGA WORKFLOW 1: Full comparison + hash + search + path + serialization
# =============================================================================

class TestFullComparisonPipeline(unittest.TestCase):
    def test_end_to_end_comparison(self):
        """Complete pipeline: diff all types → verify paths → extract old/new →
        hash consistency → search+extract → serialize → affected paths."""
        import json

        # --- Dict changes ---
        t1 = {"a": 1, "b": {"c": 2, "d": {"e": 3}}, "f": 4}
        t2 = {"a": 9, "b": {"c": 5, "d": {"e": 7}}, "g": 10}
        diff = DeepDiff(t1, t2)
        self.assertIn("root['a']", diff["values_changed"])
        self.assertIn("root['b']['d']['e']", diff["values_changed"])
        self.assertIn("root['g']", diff["dictionary_item_added"])
        self.assertIn("root['f']", diff["dictionary_item_removed"])
        for path, change in diff["values_changed"].items():
            self.assertEqual(extract(t1, path), change["old_value"])
            self.assertEqual(extract(t2, path), change["new_value"])
        diff2 = DeepDiff({"x": 1}, {"x": 1, "y": 2}, verbose_level=2)
        self.assertIsInstance(diff2["dictionary_item_added"], dict)
        self.assertEqual(diff2["dictionary_item_added"]["root['y']"], 2)

        # --- List, set, tuple, type changes ---
        self.assertEqual(DeepDiff([1, 2], [1, 2, 3])["iterable_item_added"]["root[2]"], 3)
        self.assertEqual(DeepDiff([1, 2, 3], [1, 2])["iterable_item_removed"]["root[2]"], 3)
        self.assertIn("root[1][1]", DeepDiff([[1, 2], [3, 4]], [[1, 2], [3, 5]])["values_changed"])
        diff_s = DeepDiff({1, 2, 3}, {2, 3, 4})
        self.assertIn("root[4]", diff_s["set_item_added"])
        self.assertIn("root[1]", diff_s["set_item_removed"])
        diff_t = DeepDiff({"a": 1}, {"a": "1"})
        self.assertEqual(diff_t["type_changes"]["root['a']"]["old_type"], int)
        self.assertEqual(diff_t["type_changes"]["root['a']"]["new_type"], str)
        self.assertEqual(DeepDiff((1, 2, 3), (1, 2, 4))["values_changed"]["root[2]"]["old_value"], 3)

        # --- Options ---
        self.assertEqual(DeepDiff([1, 2, 3], [3, 1, 2], ignore_order=True), {})
        self.assertIn(3, DeepDiff([1, 2], [2, 1, 3], ignore_order=True)["iterable_item_added"].values())
        self.assertEqual(DeepDiff([{"a": 1}], [{"a": 1}], ignore_order=True), {})
        self.assertEqual(DeepDiff({"a": 1}, {"a": 1.0}, ignore_numeric_type_changes=True), {})
        self.assertEqual(DeepDiff({"a": "hi"}, {"a": b"hi"}, ignore_string_type_changes=True), {})
        self.assertIn("type_changes", DeepDiff({"f": True}, {"f": 1}))
        self.assertIn("type_changes", DeepDiff({"v": False}, {"v": 0}))
        self.assertEqual(DeepDiff({"a": 1.001}, {"a": 1.002}, significant_digits=2), {})
        self.assertEqual(DeepDiff({"a": 1.0}, {"a": 1.0001}, math_epsilon=0.001), {})
        self.assertIn("values_changed", DeepDiff({"v": float("nan")}, {"v": float("nan")}))
        self.assertEqual(DeepDiff({"v": float("nan")}, {"v": float("nan")}, ignore_nan_inequality=True), {})
        self.assertEqual(DeepDiff({"a": 1, "b": 2}, {"a": 1, "b": 3}, exclude_paths=["root['b']"]), {})
        self.assertEqual(DeepDiff({"a": 1, "b": "x"}, {"a": 1, "b": "y"}, exclude_types=[str]), {})
        self.assertEqual(len(DeepDiff({"a": 1, "b": 2, "c": 3}, {"a": 1, "b": 99, "c": 99},
                                      include_paths=["root['b']"])["values_changed"]), 1)
        diff_r = DeepDiff({"name": "A", "age": 30, "name_full": "B"},
                          {"name": "X", "age": 31, "name_full": "Y"},
                          exclude_regex_paths=[r"root\['name"])
        self.assertIn("root['age']", diff_r["values_changed"])
        self.assertNotIn("root['name']", diff_r.get("values_changed", {}))
        class Obj:
            def __init__(self, x, y): self.x, self.y = x, y
        obj_diff = DeepDiff(Obj(1, 2), Obj(1, 3))
        self.assertIn("root.y", obj_diff["values_changed"])
        self.assertEqual(obj_diff["values_changed"]["root.y"]["old_value"], 2)
        self.assertEqual(obj_diff["values_changed"]["root.y"]["new_value"], 3)
        class O2: pass
        a, b = O2(), O2(); a.x = 1; b.x = 1; b.y = 2
        self.assertIn("root.y", DeepDiff(a, b)["attribute_added"])
        class O3:
            def __init__(self): self.x = 1; self.__custom__ = "a"
        c, d = O3(), O3(); d.__custom__ = "b"
        self.assertEqual(DeepDiff(c, d), {})
        self.assertIn("values_changed", DeepDiff(c, d, ignore_private_variables=False))
        self.assertEqual(DeepDiff({"a": "Hello"}, {"a": "hello"}, ignore_string_case=True), {})
        self.assertIn("diff", DeepDiff({"t": "a\nb\nc"}, {"t": "a\nx\nc"})["values_changed"]["root['t']"])
        self.assertEqual(DeepDiff({"d": datetime.datetime(2024, 1, 1, 12, 30, 45)},
                                  {"d": datetime.datetime(2024, 1, 1, 12, 30, 59)},
                                  truncate_datetime="minute"), {})
        change_d = DeepDiff({"p": Decimal("10.50")}, {"p": Decimal("10.75")})["values_changed"]["root['p']"]
        self.assertEqual(change_d["old_value"], Decimal("10.50"))

        # --- Hash consistency ---
        h1_obj = {"x": [1, 2], "y": True}
        h2_obj = {"x": [1, 2], "y": True}
        self.assertEqual(DeepHash(h1_obj)[h1_obj], DeepHash(h2_obj)[h2_obj])
        self.assertEqual(DeepDiff(h1_obj, h2_obj), {})
        self.assertNotEqual(DeepHash({"a": 1})[{"a": 1}], DeepHash({"a": 2})[{"a": 2}])
        io1, io2 = [1, 2, 3], [3, 2, 1]
        self.assertEqual(DeepHash(io1, ignore_iterable_order=True)[io1],
                         DeepHash(io2, ignore_iterable_order=True)[io2])
        sha1_hash = DeepHash({"a": 1}, hasher=DeepHash.sha1hex)[{"a": 1}]
        self.assertIsInstance(sha1_hash, str)
        self.assertEqual(len(sha1_hash), 40)
        inner = [1, 2, 3]
        self.assertEqual(len(DeepHash({"data": inner})[inner]), 64)
        inner2 = {"x": 42}
        self.assertEqual(DeepHash({"w": inner2})[inner2], DeepHash(inner2)[inner2])
        raw = DeepHash({"a": 1}, apply_hash=False)[{"a": 1}]
        self.assertNotEqual(len(raw), 64)
        self.assertEqual(DeepHash({"v": 1.001}, significant_digits=2)[{"v": 1.001}],
                         DeepHash({"v": 1.002}, significant_digits=2)[{"v": 1.002}])
        self.assertEqual(DeepHash({"a": 1, "b": 2}, exclude_paths=["root['b']"])[{"a": 1, "b": 2}],
                         DeepHash({"a": 1, "b": 999}, exclude_paths=["root['b']"])[{"a": 1, "b": 999}])
        self.assertEqual(DeepHash({"a": 1, "b": "hi"}, exclude_types=[str])[{"a": 1, "b": "hi"}],
                         DeepHash({"a": 1, "b": "bye"}, exclude_types=[str])[{"a": 1, "b": "bye"}])
        self.assertEqual(DeepHash({"s": "Hello"}, ignore_string_case=True)[{"s": "Hello"}],
                         DeepHash({"s": "hello"}, ignore_string_case=True)[{"s": "hello"}])

        # --- Search → extract ---
        obj = {"a": 1, "b": {"c": 2, "d": "target"}}
        result = DeepSearch(obj, "target")
        self.assertIn("root['b']['d']", result["matched_values"])
        for p in (result["matched_values"].keys() if isinstance(result["matched_values"], dict)
                  else result["matched_values"]):
            self.assertEqual(extract(obj, p), "target")
        self.assertIn("root['b']['target_key']",
                      DeepSearch({"a": 1, "b": {"target_key": 2}}, "target_key")["matched_paths"])
        self.assertIn("root[1][1][1]",
                      DeepSearch([1, [2, [3, "needle"]]], "needle")["matched_values"])
        self.assertEqual(len(DeepSearch({"a": 1}, "missing").get("matched_values", set())), 0)
        v2 = DeepSearch({"a": "hello world"}, "hello", verbose_level=2)
        self.assertEqual(v2["matched_values"]["root['a']"], "hello world")
        self.assertIn("matched_values", {"b": "find_me"} | grep("find_me"))
        r = DeepSearch({"email": "user@example.com"}, r"\w+@\w+\.\w+", use_regexp=True)
        self.assertIn("root['email']", r["matched_values"])
        self.assertNotIn("root['a']", DeepSearch({"a": "hello world", "b": "hello"},
                                                  "hello", match_string=True).get("matched_values", {}))
        self.assertIn("root['b']", DeepSearch({"a": "hello world", "b": "hello"},
                                               "hello", match_string=True).get("matched_values", {}))
        cs = DeepSearch({"a": "Hello", "b": "hello"}, "Hello", case_sensitive=True).get("matched_values", {})
        self.assertIn("root['a']", cs)
        self.assertNotIn("root['b']", cs)
        ex = DeepSearch({"a": "target", "b": {"c": "target"}}, "target",
                        exclude_paths=["root['b']"]).get("matched_values", {})
        self.assertIn("root['a']", ex)
        self.assertNotIn("root['b']['c']", ex)

        # --- Path utilities ---
        self.assertEqual(parse_path("root['a'][0]['b']"), ["a", 0, "b"])
        pr = parse_path("root['a'][0]", include_actions=True)
        self.assertEqual(pr[0], {"element": "a", "action": "GET"})
        attrs = parse_path("root.x.y", include_actions=True)
        self.assertEqual(attrs[0]["action"], "GETATTR")
        self.assertEqual(extract({"a": {"b": {"c": 42}}}, "root['a']['b']['c']"), 42)
        self.assertEqual(extract([10, [20, 30]], "root[1][0]"), 20)
        class C:
            def __init__(self): self.value = 42
        self.assertEqual(extract({"w": C()}, "root['w'].value"), 42)

        # --- group_by + ignore_type_in_groups ---
        self.assertEqual(DeepDiff([{"k": "x", "v": 1}, {"k": "y", "v": 2}],
                                  [{"k": "y", "v": 2}, {"k": "x", "v": 1}], group_by="k"), {})
        self.assertEqual(DeepDiff({"a": 1}, OrderedDict([("a", 1)]),
                                  ignore_type_in_groups=[(dict, OrderedDict)]), {})

        # --- Serialization + properties ---
        diff3 = DeepDiff({"a": 1}, {"a": 2})
        self.assertIn("values_changed", json.loads(diff3.to_json()))
        d = diff3.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("values_changed", d)
        pretty = diff3.pretty()
        self.assertIn("root['a']", pretty)
        diff4 = DeepDiff({"a": {"x": 1}, "b": 2}, {"a": {"x": 2}, "b": 2})
        self.assertIn("root['a']['x']", diff4.affected_paths)
        self.assertIn("a", diff4.affected_root_keys)
        self.assertNotIn("b", diff4.affected_root_keys)


# =============================================================================
# MEGA WORKFLOW 2: Full Delta pipeline (non-addition operations)
# =============================================================================

class TestFullDeltaPipeline(unittest.TestCase):
    def test_end_to_end_delta(self):
        """Complete Delta pipeline: value/remove/list/type/set → bidirectional →
        serialization → root tuple/frozenset → nested tuple/frozenset → ignore_order."""
        self.assertEqual({"a": 1, "b": 2} + Delta(DeepDiff({"a": 1, "b": 2}, {"a": 1, "b": 3})),
                         {"a": 1, "b": 3})
        self.assertEqual({"a": 1, "b": 2} + Delta(DeepDiff({"a": 1, "b": 2}, {"a": 1})), {"a": 1})
        self.assertEqual([1, 2] + Delta(DeepDiff([1, 2], [1, 2, 3])), [1, 2, 3])
        self.assertEqual([1, 2, 3] + Delta(DeepDiff([1, 2, 3], [1, 2])), [1, 2])
        self.assertEqual({"a": 1} + Delta(DeepDiff({"a": 1}, {"a": "1"})), {"a": "1"})
        self.assertEqual({1, 2, 3} + Delta(DeepDiff({1, 2, 3}, {2, 3, 4})), {2, 3, 4})
        t1, t2 = [1, 2, 3], [1, 4, 3, 5]
        delta = Delta(DeepDiff(t1, t2), bidirectional=True)
        self.assertEqual(t1 + delta, t2)
        self.assertEqual(t2 - delta, t1)
        a, b = {"a": 1, "b": [1, 2]}, {"a": 2, "b": [1, 3]}
        self.assertEqual(a + Delta(DeepDiff(a, b)), b)
        self.assertIsInstance(Delta(DeepDiff({"a": 1}, {"a": 2})).to_dict(), dict)
        delta_f = Delta(DeepDiff({"a": 1, "b": 2}, {"a": 1, "b": 3}))
        flat_dict = delta_f.to_flat_dicts()[0]
        self.assertEqual(flat_dict["path"], ["b"])
        self.assertEqual(flat_dict["value"], 3)
        self.assertEqual(flat_dict["action"], "values_changed")
        flat_row = delta_f.to_flat_rows()[0]
        self.assertEqual(flat_row.path, ["b"])
        self.assertEqual(flat_row.value, 3)
        self.assertEqual(flat_row.action, "values_changed")
        r1 = (1, 2, 3) + Delta(DeepDiff((1, 2, 3), (1, 2, 4)))
        self.assertEqual(r1, (1, 2, 4))
        self.assertIsInstance(r1, tuple)
        r2 = frozenset([1, 2, 3]) + Delta(DeepDiff(frozenset([1, 2, 3]), frozenset([2, 3, 4])))
        self.assertEqual(r2, frozenset([2, 3, 4]))
        self.assertIsInstance(r2, frozenset)
        nt1, nt2 = {"d": (1, 2, 3)}, {"d": (1, 5, 3)}
        nr1 = nt1 + Delta(DeepDiff(nt1, nt2))
        self.assertEqual(nr1, nt2)
        self.assertIsInstance(nr1["d"], tuple)
        nt3 = {"items": ({"a": 1}, {"b": 2})}
        nt4 = {"items": ({"a": 1}, {"b": 9})}
        nr2 = nt3 + Delta(DeepDiff(nt3, nt4))
        self.assertEqual(nr2, nt4)
        self.assertIsInstance(nr2["items"], tuple)
        ft1, ft2 = {"tags": frozenset([1, 2, 3])}, {"tags": frozenset([2, 3, 4])}
        fr1 = ft1 + Delta(DeepDiff(ft1, ft2))
        self.assertEqual(fr1, ft2)
        self.assertIsInstance(fr1["tags"], frozenset)
        lt1 = {"data": [{"vals": (1, 2)}, {"vals": (3, 4)}]}
        lt2 = {"data": [{"vals": (1, 2)}, {"vals": (3, 99)}]}
        lr1 = lt1 + Delta(DeepDiff(lt1, lt2))
        self.assertEqual(lr1["data"][1]["vals"], (3, 99))
        self.assertIsInstance(lr1["data"][1]["vals"], tuple)
        self.assertEqual(set([1, 2, 3] + Delta(DeepDiff([1, 2, 3], [3, 2, 1, 4],
                                                         ignore_order=True, report_repetition=True))),
                         {1, 2, 3, 4})


# =============================================================================
# MEGA WORKFLOW 3: Full large data pipeline
# =============================================================================

class TestFullLargeDataPipeline(unittest.TestCase):
    def test_end_to_end_large_data(self):
        """Large-scale: 500-key diffs, 10K dicts, 1000-element sets, deep nesting,
        200-item ignore_order, large hash, large search."""
        import random
        t1 = {f"key_{i}": i for i in range(500)}
        t2 = dict(t1)
        for i in range(0, 500, 10):
            t2[f"key_{i}"] = i + 1000
        diff = DeepDiff(t1, t2)
        self.assertEqual(len(diff["values_changed"]), 50)
        self.assertEqual(diff["values_changed"]["root['key_0']"]["new_value"], 1000)
        big1 = {f"k_{i}": i for i in range(10000)}
        big2 = dict(big1)
        for i in range(0, 10000, 10):
            big2[f"k_{i}"] = i + 100000
        self.assertEqual(len(DeepDiff(big1, big2)["values_changed"]), 1000)
        diff_s = DeepDiff(set(range(1000)), set(range(100, 1100)))
        self.assertEqual(len(diff_s["set_item_added"]), 100)
        self.assertEqual(len(diff_s["set_item_removed"]), 100)
        def nest(val, depth):
            return val if depth == 0 else {"level": nest(val, depth - 1)}
        diff_n = DeepDiff(nest(1, 20), nest(2, 20))
        self.assertEqual(list(diff_n["values_changed"].keys())[0].count("['level']"), 20)
        obj = {"a": 1}
        for i in range(15):
            obj = {f"l{i}": obj}
        path = "root" + "".join(f"['l{i}']" for i in range(14, -1, -1)) + "['a']"
        self.assertEqual(extract(obj, path), 1)
        self.assertEqual(DeepDiff(list(range(200)), list(reversed(range(200))), ignore_order=True), {})
        t2_l = list(range(200)) + list(range(1000, 1010))
        random.Random(42).shuffle(t2_l)
        self.assertEqual(set(DeepDiff(list(range(200)), t2_l, ignore_order=True)
                             ["iterable_item_added"].values()), set(range(1000, 1010)))
        t1_10k = list(range(10000))
        t2_10k = list(t1_10k)
        random.Random(99).shuffle(t2_10k)
        self.assertEqual(DeepDiff(t1_10k, t2_10k, ignore_order=True), {})
        h1 = {f"k_{i}": list(range(i, i + 5)) for i in range(1000)}
        h2 = {f"k_{i}": list(range(i, i + 5)) for i in range(1000)}
        self.assertEqual(DeepHash(h1)[h1], DeepHash(h2)[h2])
        hbig1 = {f"k_{i}": i * 1.1 for i in range(10000)}
        hbig2 = {f"k_{i}": i * 1.1 for i in range(10000)}
        self.assertEqual(DeepHash(hbig1)[hbig1], DeepHash(hbig2)[hbig2])
        rows = {f"row_{i}": {"name": f"user_{i}", "score": i} for i in range(10000)}
        rows["row_7777"]["name"] = "THE_TARGET"
        result = DeepSearch(rows, "THE_TARGET")
        matched = result["matched_values"]
        paths = list(matched.keys()) if isinstance(matched, dict) else list(matched)
        self.assertEqual(extract(rows, paths[0]), "THE_TARGET")
        text1 = "\n".join(f"line {i}: original_{i}" for i in range(500))
        text2_lines = [f"line {i}: original_{i}" for i in range(500)]
        text2_lines[250] = "line 250: CHANGED"
        text2 = "\n".join(text2_lines)
        change = DeepDiff({"c": text1}, {"c": text2})["values_changed"]["root['c']"]
        self.assertIn("diff", change)
        self.assertIn("CHANGED", change["diff"])
        obj2 = {f"k_{i}": f"val_{i % 5}" for i in range(100)}
        self.assertEqual(len(DeepSearch(obj2, "val_0")["matched_values"]), 20)
        self.assertEqual(len(DeepDiff(set(range(10000)), set(range(500, 10500)))["set_item_added"]), 500)
        # Large nested dicts (500-row tabular + realistic JSON)
        rows1 = [{"id": i, "name": f"user_{i}", "profile": {"score": i * 10, "level": i % 5},
                  "tags": [f"tag_{j}" for j in range(i % 3 + 1)]} for i in range(500)]
        rows2 = [dict(r) for r in rows1]
        for r in rows2:
            r["profile"] = dict(r["profile"])
            r["tags"] = list(r["tags"])
        for i in range(0, 500, 10):
            rows2[i]["profile"]["score"] = 99999
            rows2[i]["name"] = f"modified_{i}"
        self.assertEqual(len(DeepDiff(rows1, rows2)["values_changed"]), 100)
        import copy
        company1 = {"company": {"departments": [
            {"name": f"dept_{i}", "employees": [
                {"id": j, "info": {"salary": 50000 + j * 100}} for j in range(i*10, i*10+10)]}
            for i in range(20)], "metadata": {"version": 1}}}
        company2 = copy.deepcopy(company1)
        company2["company"]["departments"][5]["employees"][3]["info"]["salary"] = 999999
        company2["company"]["departments"][15]["name"] = "RENAMED"
        company2["company"]["metadata"]["version"] = 2
        self.assertEqual(len(DeepDiff(company1, company2)["values_changed"]), 3)


# ===== Tree View =====

class TestTreeView(unittest.TestCase):
    def test_tree_view_levels(self):
        # In view="tree" every report category yields DiffLevel objects exposing the identical
        # .t1 / .t2 / .path() accessor interface. Build one diff spanning multiple categories
        # (values_changed, type_changes, dictionary_item_added, iterable_item_added) plus an
        # object diff for the attribute case, and assert the level interface once per category.
        diff = DeepDiff({"a": 1, "lst": [1, 2]}, {"a": "1", "lst": [1, 2, 3], "b": 9}, view="tree")
        for level in diff["type_changes"]:
            self.assertEqual(level.t1, 1)
            self.assertEqual(level.t2, "1")
            self.assertEqual(level.path(), "root['a']")
        added = list(diff["dictionary_item_added"])
        self.assertEqual(added[0].path(), "root['b']")
        self.assertEqual(added[0].t2, 9)
        self.assertEqual(list(diff["iterable_item_added"])[0].t2, 3)

        class Obj:
            def __init__(self, x): self.x = x
        for level in DeepDiff(Obj(1), Obj(2), view="tree")["values_changed"]:
            self.assertEqual(level.t1, 1)
            self.assertEqual(level.t2, 2)
            self.assertIn("x", level.path())

    def test_tree_paths_match_text(self):
        t1, t2 = {"a": 1, "b": [10, 20]}, {"a": 2, "b": [10, 30]}
        self.assertEqual(set(DeepDiff(t1, t2, view="text")["values_changed"].keys()),
                         {l.path() for l in DeepDiff(t1, t2, view="tree")["values_changed"]})


# ===== E2E Delta with additions =====

class TestE2EDeltaAdditions(unittest.TestCase):
    def test_diff_apply_rediff(self):
        t1 = {"users": [{"name": "Alice"}], "version": 1}
        t2 = {"users": [{"name": "Alice"}], "version": 2, "new_field": True}
        self.assertEqual(DeepDiff(t1 + Delta(DeepDiff(t1, t2)), t2), {})

    def test_serialize_apply_rediff(self):
        t1 = {"config": {"debug": False}, "items": [1, 2]}
        t2 = {"config": {"debug": True, "verbose": True}, "items": [1, 2, 3]}
        self.assertEqual(DeepDiff(t1 + Delta(Delta(DeepDiff(t1, t2)).dumps()), t2), {})

    def test_lifecycle_with_options(self):
        t1 = {"name": "Alice", "score": 95.11, "tags": ["a", "b"],
              "meta": {"ts": 1000, "debug": False}}
        t2 = {"name": "Alice", "score": 95.14, "tags": ["b", "a"],
              "meta": {"ts": 2000, "debug": True, "env": "prod"}}
        diff_lenient = DeepDiff(t1, t2, significant_digits=1, ignore_order=True)
        self.assertNotIn("root['score']", diff_lenient.get("values_changed", {}))
        result = t1 + Delta(DeepDiff(t1, t2))
        self.assertEqual(result["meta"]["env"], "prod")

    def test_deeply_nested_mixed(self):
        t1 = {"users": [{"name": "Alice", "scores": (90, 85)},
                         {"name": "Bob", "scores": (70, 75)}],
              "config": {"debug": False, "tags": {"prod", "v1"}}}
        t2 = {"users": [{"name": "Alice", "scores": (90, 95)},
                         {"name": "Charlie", "scores": (70, 75)}],
              "config": {"debug": True, "tags": {"prod", "v2"}, "version": 2}}
        result = t1 + Delta(DeepDiff(t1, t2))
        self.assertEqual(result["users"][0]["scores"], (90, 95))
        self.assertIsInstance(result["users"][0]["scores"], tuple)
        self.assertEqual(result["config"]["version"], 2)
        self.assertIn("v2", result["config"]["tags"])


# ===== Delta dict additions =====

class TestDeltaDictAdditions(unittest.TestCase):
    def test_add_typed_values(self):
        # Re-adding a dict item is one contract: the added value is stored verbatim regardless of
        # its Python type, count, or nesting depth. Add one value of each representative type
        # (scalar, list, nested dict, tuple, set, None, bool, Decimal) at one nested level in one
        # structure and round-trip it, asserting the immutables/bool keep their type.
        t1 = {"a": 1, "o": {"i": {"keep": 0}}}
        t2 = {"a": 1, "o": {"i": {"keep": 0, "scalar": 2, "lst": [1, 2, 3],
                                  "nested": {"x": {"y": 42}}, "tup": (10, 20),
                                  "st": {"x", "y"}, "none": None, "flag": True,
                                  "dec": Decimal("9.99")}}}
        result = t1 + Delta(DeepDiff(t1, t2))
        self.assertEqual(result, t2)
        inner = result["o"]["i"]
        self.assertIsInstance(inner["tup"], tuple)
        self.assertIsInstance(inner["st"], set)
        self.assertIsInstance(inner["flag"], bool)
        self.assertIsInstance(inner["dec"], Decimal)

    def test_apply_object_attribute_delta(self):
        # Distinct Delta branch: applying attribute changes to a custom object via root.attr paths
        # (a changed attribute value + a newly added attribute), not covered by the dict/list/set
        # round-trip tests above.
        class Obj:
            def __init__(self, x, y):
                self.x, self.y = x, y
            def __eq__(self, other):
                return isinstance(other, Obj) and self.__dict__ == other.__dict__
        t2 = Obj(10, 2)
        t2.z = 99
        result = Obj(1, 2) + Delta(DeepDiff(Obj(1, 2), t2))
        self.assertEqual(result, t2)
        self.assertEqual(result.z, 99)

    def test_bidirectional_round_trip(self):
        # One bidirectional delta spanning every inversion the reverse apply has to undo: a dict key
        # added only in t2 (reverse must delete it), a dict key present only in t1 (reverse must
        # re-insert it with its original value), a changed value, and set members added/removed.
        t1 = {"a": 1, "gone": 5, "tags": {"a", "b", "c"}}
        t2 = {"a": 2, "tags": {"b", "c", "d"}, "y": {"n": True}}
        delta = Delta(DeepDiff(t1, t2), bidirectional=True)
        self.assertEqual(t1 + delta, t2)
        self.assertEqual(t2 - delta, t1)

    def test_10k_dict_delta(self):
        t1 = {f"k_{i}": i for i in range(10000)}
        t2 = dict(t1)
        for i in range(0, 10000, 10):
            t2[f"k_{i}"] = i + 100000
        self.assertEqual(t1 + Delta(DeepDiff(t1, t2)), t2)


# ===== Advanced features =====

class TestIterableCompareFunc(unittest.TestCase):
    def test_compare_func_match(self):
        # iterable_compare_func pairs reordered list items by the bool the callback returns under
        # ignore_order. A composite key (name AND type) subsumes the single-key case — both take the
        # identical code path that invokes the callback and reads its bool — so one test covers it.
        from deepdiff.helper import CannotCompare
        def cmp(x, y):
            try: return x['name'] == y['name'] and x['type'] == y['type']
            except: raise CannotCompare()
        # threshold_to_diff_deeper=0 ("0 always diffs deeper") keeps this test on the callback-pairing
        # contract instead of the default threshold's collapse boundary, whose input measure the spec
        # only pins at its endpoints.
        diff = DeepDiff([{"name": "a", "type": "x", "val": 1}, {"name": "b", "type": "y", "val": 2}],
                        [{"name": "b", "type": "y", "val": 20}, {"name": "a", "type": "x", "val": 1}],
                        ignore_order=True, iterable_compare_func=cmp, threshold_to_diff_deeper=0)
        change = [v for p, v in diff["values_changed"].items() if "val" in p][0]
        self.assertEqual(change["new_value"], 20)

    def test_cannot_compare_fallback(self):
        from deepdiff.helper import CannotCompare
        self.assertEqual(DeepDiff([1, 2, 3], [3, 2, 1], ignore_order=True,
                                  iterable_compare_func=lambda x, y: (_ for _ in ()).throw(CannotCompare())), {})

    def test_compare_func_delta(self):
        from deepdiff.helper import CannotCompare
        def cmp(x, y):
            try: return x['key'] == y['key']
            except: raise CannotCompare()
        t1 = [{"key": "a", "val": 1}, {"key": "b", "val": 2}]
        t2 = [{"key": "b", "val": 20}, {"key": "a", "val": 1}]
        result = t1 + Delta(DeepDiff(t1, t2, ignore_order=True, iterable_compare_func=cmp, report_repetition=True))
        self.assertEqual(next(i["val"] for i in result if i["key"] == "b"), 20)


class TestIgnoreOrderFunc(unittest.TestCase):
    def test_selective(self):
        diff = DeepDiff({"ordered": [1, 2, 3], "unordered": [1, 2, 3]},
                        {"ordered": [3, 2, 1], "unordered": [3, 2, 1]},
                        ignore_order_func=lambda level: "unordered" in str(level))
        changed = diff["values_changed"]
        self.assertTrue(any(p.startswith("root['ordered']") for p in changed))
        self.assertFalse(any("unordered" in p for p in changed))


class TestAdvancedParams(unittest.TestCase):
    def test_max_passes(self):
        """A capped max_passes costs granularity on the deepest reordered iterables while still
        reporting the genuine top-level changes.

        The single allowed pass goes to the top-level operand comparison, so the top-level value
        change (val5 -> CHANGE) is still reported, but the five-level-deep reordered k3 lists can no
        longer be resolved — so the capped diff must differ from the unbounded one. An
        implementation that accepts max_passes and then ignores it makes the two equal and fails.
        cutoff_intersection_for_pairs=1 and threshold_to_diff_deeper=0 force the engine to keep
        diffing deeper.
        """
        t1 = [{"k3": [[[[[1, 2, 4, 5]]]]], "k4": [7, 8]}, {"k5": "val5", "k6": "val6"}]
        t2 = [{"k5": "CHANGE", "k6": "val6"}, {"k3": [[[[[1, 3, 5, 4]]]]], "k4": [7, 8]}]
        kw = dict(ignore_order=True, cutoff_intersection_for_pairs=1, threshold_to_diff_deeper=0)
        diff_limited = DeepDiff(t1, t2, max_passes=1, **kw)
        diff_full = DeepDiff(t1, t2, **kw)
        self.assertNotEqual(diff_limited, {})
        self.assertNotEqual(diff_limited, diff_full)
        changed = diff_limited["values_changed"]
        # Assert the spec-determined top-level change (val5 -> CHANGE) is reported, without pinning
        # which side's index the matched item uses: under ignore_order the {k5,k6} dict moves from
        # index 1 in t1 to index 0 in t2, and which side's index the reported path carries is an
        # internal engine detail the spec does not fix, so accept either root[0]['k5'] or root[1]['k5'].
        k5_changes = [c for p, c in changed.items() if p.endswith("['k5']")]
        self.assertEqual(len(k5_changes), 1)
        self.assertEqual(k5_changes[0], {"old_value": "val5", "new_value": "CHANGE"})

    def test_max_diffs(self):
        """max_diffs=1 stops after 1 item-to-item diff, producing a strictly less granular result."""
        def reported_changes(diff):
            return sum(len(diff.get(k, {})) for k in
                       ("iterable_item_added", "iterable_item_removed", "values_changed"))
        diff_limited = DeepDiff(list(range(20)), list(range(20, 40)),
                                ignore_order=True, max_diffs=1)
        diff_full = DeepDiff(list(range(20)), list(range(20, 40)),
                             ignore_order=True)
        # Limited still detects a difference but reports strictly fewer changes than the full diff.
        # A no-op max_diffs (parameter ignored) would make limited == full and fail this.
        self.assertNotEqual(diff_limited, {})
        self.assertLess(reported_changes(diff_limited), reported_changes(diff_full))

    def test_cache_size(self):
        t1 = [{"id": i, "data": list(range(10))} for i in range(50)]
        t2 = [{"id": i, "data": list(range(10))} for i in range(50)]
        t2[25]["id"] = 999
        diff = DeepDiff(t1, t2, ignore_order=True, cache_size=500)
        changed = diff["values_changed"]
        self.assertEqual(len(changed), 1)
        ((path, change),) = changed.items()
        self.assertEqual(path, "root[25]['id']")
        self.assertEqual(change["old_value"], 25)
        self.assertEqual(change["new_value"], 999)

    def test_number_format_notation_e(self):
        # Under "e" notation, significant_digits counts scientific-notation digits: 1234567 vs
        # 1234568 collapse (both 1.23e+06) while the default "f" notation still reports them as
        # changed. Genuinely different magnitudes (100 vs 200) still differ under "e".
        self.assertIn("values_changed", DeepDiff({"v": 1234567}, {"v": 1234568}, significant_digits=2))
        self.assertEqual(DeepDiff({"v": 1234567}, {"v": 1234568},
                                  significant_digits=2, number_format_notation="e"), {})
        self.assertIn("values_changed", DeepDiff({"v": 100}, {"v": 200},
                                                 significant_digits=2, number_format_notation="e"))


class TestCustomOperators(unittest.TestCase):
    def test_skip_by_type(self):
        from deepdiff.operator import BaseOperator
        class Skip(BaseOperator):
            def give_up_diffing(self, level, diff_instance): return True
        diff = DeepDiff({"a": 1.0, "b": "hi"}, {"a": 2.0, "b": "bye"},
                        custom_operators=[Skip(types=[float])])
        self.assertIn("root['b']", diff.get("values_changed", {}))
        self.assertNotIn("root['a']", diff.get("values_changed", {}))

    def test_skip_by_regex_path(self):
        from deepdiff.operator import BaseOperator
        class Skip(BaseOperator):
            def give_up_diffing(self, level, diff_instance): return True
        diff = DeepDiff({"name": "Alice", "created_at": 1000, "updated_at": 2000},
                        {"name": "Bob", "created_at": 9999, "updated_at": 8888},
                        custom_operators=[Skip(regex_paths=[r"_at"])])
        self.assertIn("root['name']", diff.get("values_changed", {}))
        self.assertNotIn("root['created_at']", diff.get("values_changed", {}))


class TestGroupBy(unittest.TestCase):
    def test_group_by_key(self):
        gb_diff = DeepDiff([{"id": 1, "val": "a"}, {"id": 2, "val": "b"}],
                           [{"id": 2, "val": "x"}, {"id": 1, "val": "a"}], group_by="id")
        gb_changes = {p: v for p, v in gb_diff["values_changed"].items() if "val" in p}
        self.assertGreater(len(gb_changes), 0)
        change = list(gb_changes.values())[0]
        self.assertEqual(change["old_value"], "b")
        self.assertEqual(change["new_value"], "x")



class TestIgnoreTypeInGroups(unittest.TestCase):
    def test_ignore_type_in_groups(self):
        # Both spec-named groups: a scalar pair only has to suppress the type_changes report, while
        # a container pair additionally has to compare the two differently-typed containers
        # item-by-item, so neither subsumes the other.
        self.assertEqual(DeepDiff({"a": 1}, {"a": 1.0}, ignore_type_in_groups=[(int, float)]), {})
        self.assertEqual(DeepDiff({"d": [1, 2]}, {"d": (1, 2)}, ignore_type_in_groups=[(list, tuple)]), {})



class TestDeepDistance(unittest.TestCase):
    def test_deep_distance(self):
        diff = DeepDiff({"a": 1}, {"a": 2}, get_deep_distance=True)
        self.assertIsInstance(diff["deep_distance"], float)
        self.assertGreater(diff["deep_distance"], 0)
        self.assertEqual(DeepDiff({"a": 1}, {"a": 1}, get_deep_distance=True).get("deep_distance", 0), 0)
        t1 = {"a": 1, "b": 2, "c": 3, "d": 4}
        d_sm = DeepDiff(t1, {"a": 1, "b": 2, "c": 3, "d": 5}, get_deep_distance=True).get("deep_distance", 0)
        d_lg = DeepDiff(t1, {"a": 10, "b": 20, "c": 30, "d": 40}, get_deep_distance=True).get("deep_distance", 0)
        self.assertGreater(d_lg, d_sm)
        dist = DeepDiff({"x": [1]}, {"y": "z"}, get_deep_distance=True)["deep_distance"]
        self.assertGreaterEqual(dist, 0)
        self.assertLessEqual(dist, 1)


class TestCallbacks(unittest.TestCase):
    def test_exclude_obj_callback(self):
        # exclude_obj_callback drops objects for which the callback returns True. Cover both kinds of
        # excluded value: a leaf scalar, and a container — excluding a container excludes it from
        # comparison, so none of its contents may be reported either, while its sibling is still diffed.
        diff = DeepDiff({"a": 1, "b": -5, "c": 3}, {"a": 1, "b": -99, "c": 4},
                        exclude_obj_callback=lambda obj, path: isinstance(obj, (int, float)) and obj < 0)
        self.assertNotIn("root['b']", diff.get("values_changed", {}))
        self.assertIn("root['c']", diff["values_changed"])
        nested = DeepDiff({"small": [1, 2], "big": [1, 2, 3, 4, 5]},
                          {"small": [1, 3], "big": [9, 9, 9, 9, 9]},
                          exclude_obj_callback=lambda obj, path: isinstance(obj, list) and len(obj) > 3)
        changed = nested.get("values_changed", {})
        self.assertTrue(any(p.startswith("root['small']") for p in changed))
        self.assertFalse(any(p.startswith("root['big']") for p in changed))

    def test_include_obj_callback(self):
        diff = DeepDiff({"name": "Alice", "age": 30}, {"name": "Bob", "age": 31},
                        include_obj_callback=lambda obj, path: isinstance(obj, str))
        self.assertIn("root['name']", diff.get("values_changed", {}))
        self.assertNotIn("root['age']", diff.get("values_changed", {}))

    def test_number_to_string_func(self):
        """number_to_string_func with significant_digits uses custom formatting."""
        diff = DeepDiff({"val": 1.2}, {"val": 1.8},
                        significant_digits=0,
                        number_to_string_func=lambda n, *a, **kw: str(int(n)))
        self.assertEqual(diff, {})


if __name__ == "__main__":
    unittest.main()
