"""Comprehensive test suite for pySMT library.

Tests cover formula construction, type system, simplification, rewritings,
oracles, walkers, serialization/parsing, and cross-feature integration.

Restructured to minimize easy/isolated tests and focus on complex, goal-oriented
workflows that exercise real pySMT capabilities end-to-end.
"""
import unittest
from fractions import Fraction
from io import StringIO

import pysmt.operators as op


class TestSubstitutionWorkflow(unittest.TestCase):
    """Consolidated substitution test: basic, simplify, quantifier scoping, DAG."""

    def test_substitution_workflow(self):
        """End-to-end substitution workflow covering basic substitution with
        simplification, quantifier-aware scoping, and DAG preservation.

        Steps:
        1. substitute(And(x,y), {x: TRUE()}) -> verify is_and with TRUE and y
        2. simplify that result -> verify equals y
        3. Substitute in ForAll([yi], Equals(xi, yi)) with {xi: Int(5)} ->
           verify yi NOT substituted, xi gone from free vars
        4. Build Or(shared, Not(shared)), substitute in shared -> verify
           DAG sharing preserved (same object via hash-consing)
        """
        from pysmt.shortcuts import (reset_env, Symbol, And, Or, Not, ForAll,
                                      Equals, Int, TRUE, substitute, simplify,
                                      get_free_variables)
        from pysmt.typing import BOOL, INT
        reset_env()

        # Step 1 & 2: Basic substitution + simplification
        x = Symbol("x", BOOL)
        y = Symbol("y", BOOL)
        result = substitute(And(x, y), {x: TRUE()})
        self.assertTrue(result.is_and())
        args = set(result.args())
        self.assertIn(TRUE(), args)
        self.assertIn(y, args)
        self.assertEqual(simplify(result), y)

        # Step 3: Quantifier scoping
        xi = Symbol("xi", INT)
        yi = Symbol("yi", INT)
        f = ForAll([yi], Equals(xi, yi))
        qresult = substitute(f, {xi: Int(5)})
        fv = get_free_variables(qresult)
        self.assertNotIn(xi, fv)
        self.assertNotIn(yi, fv)
        self.assertTrue(qresult.is_forall())

        # Step 4: DAG preservation
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        z = Symbol("z", BOOL)
        shared = And(a, b)
        f2 = Or(shared, Not(shared))
        dag_result = substitute(f2, {a: z})
        and_in_or = None
        and_in_not = None
        for arg in dag_result.args():
            if arg.is_and():
                and_in_or = arg
            if arg.is_not():
                and_in_not = arg.arg(0)
        self.assertIsNotNone(and_in_or)
        self.assertIsNotNone(and_in_not)
        self.assertIs(and_in_or, and_in_not)


class TestRewritingPipeline(unittest.TestCase):
    """Consolidated rewriting test: NNF, CNF with Tseitin, and Prenex in one flow."""

    def test_rewriting_pipeline(self):
        """End-to-end rewriting pipeline on a formula family with Implies, Iff,
        ForAll, Exists.

        Steps:
        1. NNF: verify Not(And(a,b)) -> Or(Not(a), Not(b)) (De Morgan)
        2. NNF: verify Not(Implies(a,b)) -> And(a, Not(b))
        3. NNF quantifiers: Not(ForAll) -> Exists, Not(Exists) -> ForAll
        4. CNF: Or(And(a,b), c) -> conjunction of disjunctions
        5. CNF Tseitin: verify fresh variables introduced (more vars than original)
        6. Prenex: And(ForAll([x], ...), Exists([y], ...)) -> quantifier at front
        """
        from pysmt.shortcuts import (reset_env, Symbol, And, Or, Not, Implies,
                                      ForAll, Exists, Function, GE, LE, Int,
                                      get_free_variables)
        from pysmt.typing import BOOL, INT, FunctionType
        from pysmt.rewritings import NNFizer, CNFizer, PrenexNormalizer
        reset_env()

        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        c = Symbol("c", BOOL)

        nnf = NNFizer()

        # Step 1: De Morgan -- assert the full concrete result, not just node shape
        r1 = nnf.convert(Not(And(a, b)))
        self.assertEqual(r1, Or(Not(a), Not(b)))

        # Step 2: Implies negation -- assert the full concrete result
        r2 = nnf.convert(Not(Implies(a, b)))
        self.assertEqual(r2, And(a, Not(b)))

        # Step 3: Quantifier duals -- assert the full negated result, not just the
        # node kind. NNF of Not(ForAll(x, P(x))) is Exists(x, Not(P(x))) and NNF of
        # Not(Exists(x, P(x))) is ForAll(x, Not(P(x))); the body must be negated. A
        # buggy NNFizer that flipped the quantifier but forgot to push Not into the
        # body would still satisfy an is_exists()/is_forall() shape check.
        x = Symbol("x", INT)
        P = Symbol("P", FunctionType(BOOL, [INT]))
        r3 = nnf.convert(Not(ForAll([x], Function(P, [x]))))
        self.assertEqual(r3, Exists([x], Not(Function(P, [x]))))
        r4 = nnf.convert(Not(Exists([x], Function(P, [x]))))
        self.assertEqual(r4, ForAll([x], Not(Function(P, [x]))))

        # Step 4 & 5: CNF with Tseitin
        cnfizer = CNFizer()
        f_or_and = Or(And(a, b), c)
        cnf_result = cnfizer.convert_as_formula(f_or_and)
        if cnf_result.is_and():
            for clause in cnf_result.args():
                if clause.is_or():
                    pass  # valid clause
                else:
                    self.assertTrue(clause.is_symbol() or clause.is_not()
                                    or clause.is_true() or clause.is_false())
        original_vars = get_free_variables(f_or_and)
        cnf_vars = get_free_variables(cnf_result)
        self.assertGreater(len(cnf_vars), len(original_vars))

        # Step 6: Prenex normalization -- assert the concrete prenex form up to
        # alpha-equivalence of the bound variables. Both quantifiers must be hoisted to
        # the front as a ForAll wrapping an Exists (or the Exists/ForAll swap -- either
        # nesting order is valid) and the matrix must conjoin both bodies relative to
        # whatever bound symbols the normalizer chose: the universally-bound variable
        # carries the >= 0 bound and the existentially-bound variable the <= 10 bound.
        # The spec scopes alpha-renaming to capture-avoidance and does not pin the bound-
        # variable NAMES, so eager renaming to fresh symbols is a faithful PNF strategy;
        # we therefore compare relative to the chosen symbols, not to the literal x/y. A
        # normalizer that hoisted only one quantifier, swapped which variable each
        # quantifier binds, or corrupted the matrix is still caught.
        y = Symbol("y", INT)
        f_prenex = And(ForAll([x], GE(x, Int(0))), Exists([y], LE(y, Int(10))))
        pnf = PrenexNormalizer()
        prenex_result = pnf.normalize(f_prenex)
        outer, inner = prenex_result, prenex_result.arg(0)
        self.assertTrue(
            (outer.is_forall() and inner.is_exists())
            or (outer.is_exists() and inner.is_forall())
        )
        (forall_node, exists_node) = (
            (outer, inner) if outer.is_forall() else (inner, outer)
        )
        self.assertEqual(len(forall_node.quantifier_vars()), 1)
        self.assertEqual(len(exists_node.quantifier_vars()), 1)
        uv = forall_node.quantifier_vars()[0]
        ev = exists_node.quantifier_vars()[0]
        expected_matrix = And(GE(uv, Int(0)), LE(ev, Int(10)))
        self.assertEqual(inner.arg(0), expected_matrix)


class TestOracleAnalysis(unittest.TestCase):
    """Consolidated oracle test: free vars, atoms, formula size, is_qf, get_logic."""

    def test_oracle_analysis(self):
        """Build ForAll([x], And(Equals(x, y), LT(a, b))) with mixed free/bound vars.

        Steps:
        1. get_free_variables -> verify {y, a, b} (x is bound)
        2. get_atoms on the body -> verify atomic predicates (Equals, LT)
        3. get_formula_size -> verify node count
        4. is_quantifier -> verify True (has ForAll)
        5. get_logic on a Plus formula -> verify QF_LIA (not IDL)
        6. get_logic on BV formula -> verify QF_BV
        """
        from pysmt.shortcuts import (reset_env, Symbol, And, ForAll, Equals, LT,
                                      Plus, Int, BV, BVAdd, get_free_variables,
                                      get_atoms, get_formula_size)
        from pysmt.typing import INT, BOOL, BVType
        from pysmt.oracles import get_logic
        reset_env()

        x = Symbol("x", INT)
        y = Symbol("y", INT)
        a = Symbol("a", INT)
        b = Symbol("b", INT)

        body = And(Equals(x, y), LT(a, b))
        f = ForAll([x], body)

        # Step 1: Free variables
        fv = get_free_variables(f)
        self.assertIn(y, fv)
        self.assertIn(a, fv)
        self.assertIn(b, fv)
        self.assertNotIn(x, fv)

        # Step 2: Atoms of the body -- assert the exact atom set, not just the count
        atoms = get_atoms(body)
        self.assertEqual(atoms, {Equals(x, y), LT(a, b)})

        # Step 3: Formula size of body: And + Equals + x + y + LT + a + b = 7
        self.assertEqual(get_formula_size(body), 7)

        # Step 4: Quantifier detection
        self.assertTrue(f.is_quantifier())
        self.assertTrue(f.is_forall())

        # Step 5: Theory detection - Plus forces LIA (not IDL)
        f_lia = Equals(Plus(x, y), Int(0))
        logic_lia = get_logic(f_lia)
        self.assertEqual(str(logic_lia), "QF_LIA")

        # Step 6: BV theory
        bvx = Symbol("bvx", BVType(8))
        bvy = Symbol("bvy", BVType(8))
        logic_bv = get_logic(Equals(BVAdd(bvx, bvy), BV(0, 8)))
        self.assertEqual(str(logic_bv), "QF_BV")


class TestWalkerPatterns(unittest.TestCase):
    """Consolidated walker test: custom DagWalker, memoization, IdentityDagWalker, TreeWalker."""

    def test_walker_patterns(self):
        """End-to-end walker pattern test.

        Steps:
        1. Custom DagWalker with @handles counting nodes -> walk formula -> verify count
        2. Verify memoization: shared subformula visited once (DAG has fewer visits than tree)
        3. IdentityDagWalker round-trip -> verify equality
        4. TreeWalker with generator yield -> verify traversal visits all nodes
        """
        from pysmt.shortcuts import reset_env, Symbol, And, Or, Not
        from pysmt.typing import BOOL
        from pysmt.walkers import DagWalker, IdentityDagWalker, TreeWalker, handles
        reset_env()

        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)

        # Step 1: Custom node counter
        class NodeCounter(DagWalker):
            @handles(op.ALL_TYPES)
            def walk_all_nodes(self, formula, args, **kwargs):
                return 1 + sum(args)

        counter = NodeCounter()
        self.assertEqual(counter.walk(And(a, b)), 3)

        # Step 2: Memoization verification
        class VisitCounter(DagWalker):
            def __init__(self):
                DagWalker.__init__(self)
                self.visit_count = 0

            @handles(op.ALL_TYPES)
            def walk_count(self, formula, args, **kwargs):
                self.visit_count += 1
                return formula

        shared = And(a, b)
        f_dag = Or(shared, Not(shared))
        vcounter = VisitCounter()
        vcounter.walk(f_dag)
        # DAG nodes: Or, And(a,b), Not(And(a,b)), a, b = 5
        self.assertEqual(vcounter.visit_count, 5)

        # Step 3: IdentityDagWalker round-trip
        f_complex = Or(And(a, Not(b)), a)
        idw = IdentityDagWalker()
        self.assertEqual(idw.walk(f_complex), f_complex)

        # Step 4: TreeWalker traversal
        class ChildYielder(TreeWalker):
            def __init__(self):
                TreeWalker.__init__(self)
                self.visited = []

            @handles(op.ALL_TYPES)
            def walk_all(self, formula):
                self.visited.append(formula)
                for child in formula.args():
                    yield child

        f_tree = And(a, b)
        w = ChildYielder()
        w.walk(f_tree)
        self.assertEqual(len(w.visited), 3)


class TestSmtLibRoundTripAllTheories(unittest.TestCase):
    """Consolidated SMT-LIB round-trip: Bool + Arith + BV + quantifiers + let-bindings."""

    def test_smtlib_round_trip_all_theories(self):
        """Build formulas spanning multiple theories, serialize to SMT-LIB,
        parse back, verify equality. Also test let-binding parsing.

        Steps:
        1. Boolean: And(Or(a,b), Not(c)) round-trip
        2. Arithmetic: Plus(x, Times(Int(2), y)) round-trip
        3. BV: BVAdd round-trip, verify bvadd in serialization
        4. Quantifiers: ForAll([x], GE(x, Int(0))) round-trip
        5. Let-bindings: parse (let ((y (+ x 1))) (= y 5)) -> verify result
        """
        from pysmt.shortcuts import (reset_env, Symbol, And, Or, Not, Plus, Times,
                                      Int, Equals, BV, BVAdd, ForAll, GE, to_smtlib)
        from pysmt.typing import BOOL, INT, BVType
        from pysmt.smtlib.parser import SmtLibParser
        import pysmt.smtlib.script as script_mod
        reset_env()

        parser = SmtLibParser()

        def round_trip(formula):
            scr = script_mod.smtlibscript_from_formula(formula)
            buf = StringIO()
            scr.serialize(buf)
            s = parser.get_script(StringIO(buf.getvalue()))
            return s.get_strict_formula()

        # Step 1: Boolean
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        c = Symbol("c", BOOL)
        f_bool = And(Or(a, b), Not(c))
        self.assertEqual(round_trip(f_bool), f_bool)

        # Step 2: Arithmetic
        x = Symbol("x", INT)
        y = Symbol("y", INT)
        f_arith = Equals(Plus(x, Times(Int(2), y)), Int(0))
        self.assertEqual(round_trip(f_arith), f_arith)

        # Step 3: BV
        bv_x = Symbol("bv_x", BVType(8))
        bv_y = Symbol("bv_y", BVType(8))
        f_bv = Equals(BVAdd(bv_x, bv_y), BV(0, 8))
        smtlib_str = to_smtlib(f_bv, daggify=False)
        self.assertIn("bvadd", smtlib_str)
        self.assertEqual(round_trip(f_bv), f_bv)

        # Step 4: Quantifiers
        xq = Symbol("xq", INT)
        f_quant = ForAll([xq], GE(xq, Int(0)))
        self.assertEqual(round_trip(f_quant), f_quant)

        # Step 5: Let-bindings
        let_str = (
            "(set-logic QF_LIA)\n"
            "(declare-fun x () Int)\n"
            "(assert (let ((y (+ x 1))) (= y 5)))\n"
            "(check-sat)\n"
        )
        s = parser.get_script(StringIO(let_str))
        asserted = s.get_strict_formula()
        expected = Equals(Plus(x, Int(1)), Int(5))
        self.assertEqual(asserted, expected)


class TestSmtLibScriptWorkflow(unittest.TestCase):
    """Tests multi-assertion SmtLibScript assembly, get_strict_formula, and round-trip."""

    def test_smtlib_script_workflow(self):
        """Assemble a script with MULTIPLE assert commands and verify that
        get_strict_formula returns the conjunction of all assertions (not just a
        single one), then round-trip the script through the parser and verify the
        conjunction is preserved.

        Steps:
        1. Build a script: set-logic, declare-fun for a/b/c, two asserts (Or(a,b)
           and Not(c)), check-sat.
        2. get_strict_formula -> assert it equals And(Or(a,b), Not(c)) exactly.
        3. get_last_formula -> same conjunction (assertion stack with no push/pop).
        4. Serialize, parse back, and assert the re-parsed strict formula still
           equals And(Or(a,b), Not(c)).
        """
        from pysmt.shortcuts import reset_env, Symbol, And, Or, Not
        from pysmt.typing import BOOL
        from pysmt.smtlib.script import SmtLibScript, SmtLibCommand
        import pysmt.smtlib.commands as smtcmd
        from pysmt.smtlib.parser import SmtLibParser
        reset_env()
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        c = Symbol("c", BOOL)

        # Step 1: assemble a multi-assertion script
        scr = SmtLibScript()
        scr.add(name=smtcmd.SET_LOGIC, args=["QF_BOOL"])
        for sym in (a, b, c):
            scr.add(name=smtcmd.DECLARE_FUN, args=[sym])
        scr.add_command(SmtLibCommand(name=smtcmd.ASSERT, args=[Or(a, b)]))
        scr.add_command(SmtLibCommand(name=smtcmd.ASSERT, args=[Not(c)]))
        scr.add_command(SmtLibCommand(name=smtcmd.CHECK_SAT, args=[]))

        conjunction = And(Or(a, b), Not(c))

        # Step 2 & 3: both formula extractors conjoin the two assertions
        self.assertEqual(scr.get_strict_formula(), conjunction)
        self.assertEqual(scr.get_last_formula(), conjunction)

        # Step 4: serialize -> parse back -> conjunction preserved
        buf = StringIO()
        scr.serialize(buf)
        parser = SmtLibParser()
        reparsed = parser.get_script(StringIO(buf.getvalue()))
        self.assertEqual(reparsed.get_strict_formula(), conjunction)


class TestHRRoundTripBasic(unittest.TestCase):
    """Consolidated HR round-trip: boolean, arithmetic, ITE, and complex shared subexpressions."""

    def test_hr_round_trip_basic(self):
        """Build formulas of several types, serialize to HR format, parse back,
        verify equality through the Pratt parser.

        Steps:
        1. Boolean: And(a, Or(b, c)) round-trip
        2. Arithmetic: Plus(x, Times(Int(2), y)) round-trip
        3. ITE: Ite(a, And(b,c), Or(d,e)) round-trip with ? and : operators
        4. Complex shared: Or(And(shared,c), And(shared,d)) round-trip
        """
        from pysmt.shortcuts import (reset_env, Symbol, And, Or, Not, Plus, Times,
                                      Int, Ite, serialize)
        from pysmt.typing import BOOL, INT
        from pysmt.parsing import HRParser
        reset_env()
        parser = HRParser()

        # Step 1: Boolean
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        c = Symbol("c", BOOL)
        f_bool = And(a, Or(b, c))
        hr = serialize(f_bool)
        self.assertEqual(parser.parse(hr), f_bool)

        # Step 2: Arithmetic
        x = Symbol("x", INT)
        y = Symbol("y", INT)
        f_arith = Plus(x, Times(Int(2), y))
        hr = serialize(f_arith)
        self.assertEqual(parser.parse(hr), f_arith)

        # Step 3: ITE
        d = Symbol("d", BOOL)
        e = Symbol("e", BOOL)
        f_ite = Ite(a, And(b, c), Or(d, e))
        hr = serialize(f_ite)
        self.assertIn("?", hr)
        self.assertIn(":", hr)
        self.assertEqual(parser.parse(hr), f_ite)

        # Step 4: Complex shared subexpressions
        shared = And(a, b)
        f_shared = Or(And(shared, c), And(shared, d))
        hr = serialize(f_shared)
        self.assertEqual(parser.parse(hr), f_shared)


class TestHRParseBVAndQuantifiers(unittest.TestCase):
    """HR round-trip for BV and quantifiers -- tests Pratt parser with typed symbols."""

    def test_hr_parse_bv_and_quantifiers(self):
        """Serialize BV operations and quantified formulas to HR format,
        parse back through the Pratt parser, verify equality.

        Steps:
        1. BV: BVAdd(bv_x, bv_y) round-trip through HR
        2. Quantifiers: ForAll([x], Implies(GE(x,0), GE(x,0))) round-trip
        """
        from pysmt.shortcuts import (reset_env, Symbol, BVAdd, ForAll, Implies,
                                      GE, Int, serialize)
        from pysmt.typing import INT, BVType
        from pysmt.parsing import HRParser
        reset_env()
        parser = HRParser()

        # Step 1: BV round-trip
        bv_x = Symbol("bv_x", BVType(8))
        bv_y = Symbol("bv_y", BVType(8))
        f_bv = BVAdd(bv_x, bv_y)
        hr = serialize(f_bv)
        self.assertEqual(parser.parse(hr), f_bv)

        # Step 2: Quantifier round-trip
        x = Symbol("x", INT)
        f_quant = ForAll([x], Implies(GE(x, Int(0)), GE(x, Int(0))))
        hr = serialize(f_quant)
        self.assertIn("forall", hr)
        self.assertEqual(parser.parse(hr), f_quant)


class TestStringAndArrayWorkflow(unittest.TestCase):
    """Consolidated string and array theory test."""

    def test_string_and_array_workflow(self):
        """Full string and array workflow in one test.

        Steps:
        1. String: construct constants, verify type propagation, then simplify
           constant expressions to their concrete folded values -- length, concat,
           contains (-> TRUE/FALSE), and indexOf (-> first index, or -1 if absent).
        2. Array: construct ArrayType, create an array constant, Store/Select, verify
           type propagation, then assert read-over-write: Select at the stored index
           folds to the stored value and Select at any other index folds to the
           array's default.
        """
        from pysmt.shortcuts import (reset_env, Symbol, String, StrLength, StrConcat,
                                      StrContains, StrIndexOf, Array, Select, Store,
                                      Int, Real, TRUE, FALSE, simplify)
        from pysmt.typing import STRING, BOOL, INT, REAL, ArrayType
        reset_env()

        # String operations
        s1 = String("hello")
        self.assertEqual(s1.get_type(), STRING)
        self.assertEqual(StrLength(s1).get_type(), INT)
        s2 = String("world")
        concat = StrConcat(s1, s2)
        self.assertEqual(concat.get_type(), STRING)
        # StrContains/StrIndexOf over string constants must fold to the concrete
        # result, not merely produce a node of the right type. A wrong-but-right-
        # shaped implementation (returning the wrong boolean/index) would pass a
        # get_type() check; pinning the computed value catches it.
        contains = StrContains(s1, String("ell"))
        self.assertEqual(contains.get_type(), BOOL)
        self.assertEqual(simplify(contains), TRUE())
        # "ell" not contained in "world" -> FALSE
        self.assertEqual(simplify(StrContains(s2, String("ell"))), FALSE())
        idx = StrIndexOf(s1, String("ll"), Int(0))
        self.assertEqual(idx.get_type(), INT)
        # first index of "ll" in "hello" starting at 0 is 2
        self.assertEqual(simplify(idx), Int(2))
        # absent substring -> -1
        self.assertEqual(simplify(StrIndexOf(s1, String("zz"), Int(0))), Int(-1))
        self.assertEqual(simplify(StrLength(String("abc"))), Int(3))
        self.assertEqual(simplify(StrConcat(String("ab"), String("cd"))),
                         String("abcd"))

        # Array operations
        arr_t = ArrayType(INT, REAL)
        self.assertTrue(arr_t.is_array_type())
        arr = Array(INT, Real(0))
        self.assertEqual(arr.get_type(), arr_t)
        self.assertTrue(arr.is_array_value())
        stored = Store(arr, Int(1), Real(Fraction(3, 2)))
        self.assertEqual(stored.get_type(), ArrayType(INT, REAL))
        selected = Select(stored, Int(1))
        self.assertEqual(selected.get_type(), REAL)
        # Read-over-write: select at the stored index returns the stored value,
        # select at any other index returns the array's default. Asserting only
        # the element type would pass even if Store/Select violated this axiom
        # (e.g. wrote to the wrong index or returned the default instead).
        self.assertEqual(simplify(selected), Real(Fraction(3, 2)))
        default_read = Select(stored, Int(0))
        self.assertEqual(simplify(default_read), Real(0))
        arr_sym = Symbol("arr", ArrayType(INT, REAL))
        sel = Select(arr_sym, Int(0))
        self.assertEqual(sel.get_type(), REAL)
        st = Store(arr_sym, Int(0), Real(1))
        self.assertEqual(st.get_type(), ArrayType(INT, REAL))


class TestBitVectorOperations(unittest.TestCase):
    """Tests for bitvector constant folding across arithmetic, bitwise, shift, and comparison."""

    def test_bv_constant_folding_pipeline(self):
        """Pipeline of BV constant folding: arithmetic (Add, Mul), bitwise (And, Or,
        Xor), shift (LShl, LShr), rotate (Rol), and comparison (ULT, ULE) all in
        one sequential flow on 8-bit vectors."""
        from pysmt.shortcuts import (reset_env, BV, BVAdd, BVMul, BVAnd, BVOr,
                                      BVXor, BVLShl, BVLShr, BVRol, BVULT,
                                      BVULE, TRUE, FALSE, simplify)
        reset_env()
        # Arithmetic
        self.assertEqual(simplify(BVAdd(BV(3, 8), BV(5, 8))), BV(8, 8))
        self.assertEqual(simplify(BVMul(BV(3, 8), BV(4, 8))), BV(12, 8))
        # Bitwise
        self.assertEqual(simplify(BVAnd(BV(0xF0, 8), BV(0x0F, 8))), BV(0, 8))
        self.assertEqual(simplify(BVOr(BV(0xF0, 8), BV(0x0F, 8))), BV(0xFF, 8))
        self.assertEqual(simplify(BVXor(BV(0xAA, 8), BV(0x55, 8))), BV(0xFF, 8))
        # Shift
        self.assertEqual(simplify(BVLShl(BV(1, 8), BV(3, 8))), BV(8, 8))
        self.assertEqual(simplify(BVLShr(BV(128, 8), BV(1, 8))), BV(64, 8))
        # Rotate: Rol(0x81, 1) on 8 bits = 0x03
        self.assertEqual(simplify(BVRol(BV(0x81, 8), 1)), BV(0x03, 8))
        # Comparison
        self.assertEqual(simplify(BVULT(BV(3, 8), BV(5, 8))), TRUE())
        self.assertEqual(simplify(BVULE(BV(5, 8), BV(3, 8))), FALSE())

    def test_bv_extract_concat_signed(self):
        """Pipeline of BV extract, concat, and signed operations (SDiv, SRem, Neg)
        in one sequential flow."""
        from pysmt.shortcuts import (reset_env, BV, BVExtract, BVConcat,
                                      BVSDiv, BVSRem, BVNeg, SBV, simplify)
        reset_env()
        # Extract and Concat
        self.assertEqual(simplify(BVExtract(BV(0xFF, 8), 0, 3)), BV(0xF, 4))
        self.assertEqual(simplify(BVConcat(BV(0xF, 4), BV(0x0, 4))), BV(0xF0, 8))
        # Signed division: 10 / 3 = 3
        self.assertEqual(simplify(BVSDiv(BV(10, 8), BV(3, 8))), BV(3, 8))
        # Signed remainder: -5 % 3 = -2 (result sign matches dividend)
        neg5 = SBV(-5, 8)
        result = simplify(BVSRem(neg5, BV(3, 8)))
        self.assertEqual(result.bv_signed_value(), -2)
        # BVNeg: negation of 5 is -5 (i.e., 251 unsigned in 8-bit)
        self.assertEqual(simplify(BVNeg(BV(5, 8))), SBV(-5, 8))


class TestCrossFeatureIntegration(unittest.TestCase):
    """Tests combining multiple features end-to-end."""

    def test_theory_detection_mixed(self):
        """Verify get_logic returns correct logic for mixed theory combinations:
        BV+UF formula, LIA+Arrays formula, and LIRA formula."""
        from pysmt.shortcuts import (reset_env, Symbol, BV, BVAdd, Function,
                                      Equals, Select, Int, Real, GE, And, Plus)
        from pysmt.typing import INT, REAL, BOOL, BVType, FunctionType, ArrayType
        from pysmt.oracles import get_logic
        reset_env()
        bvx = Symbol("bvx", BVType(8))
        P = Symbol("P", FunctionType(BOOL, [BVType(8)]))
        f_bvuf = Function(P, [BVAdd(bvx, BV(1, 8))])
        self.assertEqual(str(get_logic(f_bvuf)), "QF_UFBV")
        arr = Symbol("arr", ArrayType(INT, INT))
        x = Symbol("x", INT)
        f_lia_arr = Equals(Select(arr, x), Int(0))
        self.assertEqual(str(get_logic(f_lia_arr)), "QF_ALIA")
        y = Symbol("y", INT)
        xr = Symbol("xr", REAL)
        f_lira = And(Equals(Plus(x, y), Int(0)), GE(xr, Real(0)))
        self.assertEqual(str(get_logic(f_lira)), "QF_LIRA")

    def test_theory_detection_difference_vs_linear(self):
        """Verify the distinction between difference logic (QF_IDL) and linear
        arithmetic (QF_LIA). Minus(x, y) = 5 is difference logic; Plus(x, y) = 5
        is linear (not difference)."""
        from pysmt.shortcuts import reset_env, Symbol, Minus, Plus, Equals, Int
        from pysmt.typing import INT
        from pysmt.oracles import get_logic
        reset_env()
        x = Symbol("x", INT)
        y = Symbol("y", INT)
        f_diff = Equals(Minus(x, y), Int(5))
        logic_diff = get_logic(f_diff)
        self.assertEqual(str(logic_diff), "QF_IDL")
        f_linear = Equals(Plus(x, y), Int(5))
        logic_linear = get_logic(f_linear)
        self.assertEqual(str(logic_linear), "QF_LIA")

    def test_cnf_clause_set_form(self):
        """Exercise the CNFizer.convert clause-set API (frozenset of frozenset of
        literals) and prove the And-of-Or rebuilt from it is a faithful CNF.

        Unlike the other CNF tests (which only call convert_as_formula), this checks
        the lower-level convert form:
        1. convert(Or(And(a,Not(b)),c)) returns a frozenset of frozensets, and every
           element is a literal (a symbol or the negation of a symbol).
        2. The And(Or(clause)...) rebuilt from that clause set is equisatisfiable with
           the original f -- for every assignment to f's own variables, f is satisfied
           iff some assignment to the introduced Tseitin variables satisfies the CNF.
           (Tseitin is equisatisfiable, not canonical: the fresh aux variables are an
           internal detail the spec leaves open, so we check the logical contract --
           SAT-preservation over the original variables -- not structural identity
           against a second, independently-introduced convert_as_formula pass.)
        """
        from pysmt.shortcuts import (reset_env, Symbol, And, Or, Not, TRUE, FALSE,
                                     simplify, substitute, get_free_variables)
        from pysmt.typing import BOOL
        from pysmt.rewritings import CNFizer
        reset_env()
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        c = Symbol("c", BOOL)
        f = Or(And(a, Not(b)), c)
        cnf = CNFizer()

        # Step 1: clause-set form is a frozenset of frozensets of literals
        clauses = cnf.convert(f)
        self.assertIsInstance(clauses, frozenset)
        self.assertGreater(len(clauses), 0)

        def is_literal(node):
            return node.is_symbol() or (node.is_not() and node.arg(0).is_symbol())

        for clause in clauses:
            self.assertIsInstance(clause, frozenset)
            for lit in clause:
                self.assertTrue(is_literal(lit), "Non-literal in clause: %s" % lit)

        # Step 2: the rebuilt And-of-Or is equisatisfiable with f. Project the fresh
        # Tseitin variables out: f holds iff some assignment to them satisfies the CNF.
        reconstructed = And([Or(list(clause)) for clause in clauses])
        orig_vars = sorted(get_free_variables(f), key=lambda v: v.symbol_name())
        aux_vars = sorted(get_free_variables(reconstructed) - get_free_variables(f),
                          key=lambda v: v.symbol_name())
        for bits in range(2 ** len(orig_vars)):
            subs = {v: (TRUE() if (bits >> i) & 1 else FALSE())
                    for i, v in enumerate(orig_vars)}
            orig_sat = simplify(substitute(f, subs)) == TRUE()
            cnf_sat = False
            for aux_bits in range(2 ** len(aux_vars)):
                aux_subs = dict(subs)
                for j, av in enumerate(aux_vars):
                    aux_subs[av] = TRUE() if (aux_bits >> j) & 1 else FALSE()
                if simplify(substitute(reconstructed, aux_subs)) == TRUE():
                    cnf_sat = True
                    break
            self.assertEqual(orig_sat, cnf_sat,
                             "CNF not equisatisfiable with f at assignment %s" % subs)


class TestDifficultFlavors(unittest.TestCase):
    """Tests for edge cases, overflow, exponential avoidance, and walker completeness."""

    def test_bv_overflow_wrapping(self):
        """BVAdd(BV(200,8), BV(100,8)) wraps around modulo 256. simplify gives BV(44,8)."""
        from pysmt.shortcuts import reset_env, BV, BVAdd, simplify
        reset_env()
        result = simplify(BVAdd(BV(200, 8), BV(100, 8)))
        self.assertEqual(result, BV(44, 8))

    def test_deep_nested_simplification(self):
        """Deeply nested And/Or with TRUE/FALSE constants fully simplifies."""
        from pysmt.shortcuts import reset_env, Symbol, And, Or, TRUE, FALSE, simplify
        from pysmt.typing import BOOL
        reset_env()
        a = Symbol("a", BOOL)
        f = And(TRUE(), Or(FALSE(), And(a, TRUE())))
        result = simplify(f)
        self.assertEqual(result, a)

    def test_cnf_exponential_avoidance(self):
        """Large formula via CNFizer yields polynomial-size result (not exponential)."""
        from pysmt.shortcuts import reset_env, Symbol, And, Or, get_formula_size
        from pysmt.typing import BOOL
        from pysmt.rewritings import CNFizer
        reset_env()
        syms = []
        n = 10
        for i in range(n):
            syms.append((Symbol("a%d" % i, BOOL), Symbol("b%d" % i, BOOL)))
        big_or = Or([And(a, b) for a, b in syms])
        cnf = CNFizer()
        result = cnf.convert_as_formula(big_or)
        size = get_formula_size(result)
        self.assertLess(size, 500)

    def test_hash_consing_under_rewriting(self):
        """After NNF rewriting, structurally identical subformulas share the same
        hash-consed node (DAG identity), asserted unconditionally.

        Not(Or(And(a,b), And(a,b))) NNFizes to And(X, X) where X = Or(Not(a),Not(b))
        for both branches. Because the FormulaManager hash-conses, the two children
        must be the *same object*, so assertIs holds without any shape guard.
        """
        from pysmt.shortcuts import reset_env, Symbol, And, Or, Not
        from pysmt.typing import BOOL
        from pysmt.rewritings import NNFizer
        reset_env()
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        shared = And(a, b)
        f = Or(shared, shared)
        nnf = NNFizer()
        result = nnf.convert(Not(f))
        self.assertTrue(result.is_and())
        args = result.args()
        self.assertEqual(len(args), 2)
        self.assertIs(args[0], args[1])

    def test_walker_grouped_dispatch_with_fallback(self):
        """Custom DagWalker that registers @handles on SPECIFIC operator groups plus a
        fallback handler, verifying grouped dispatch routes each node-type group to its
        own walk_* method.

        Unlike test_walker_patterns (one @handles(op.ALL_TYPES) catch-all), this exercises
        a distinct contract: a dedicated handler bound to op.BV_OPERATORS, a second bound to
        op.RELATIONS, and a third fallback bound to every remaining node type. Because the
        metaclass installs walk_<opname> per node type in each group, a node lands in the
        handler for its group -- so a routing defect (e.g. collapsing every node into one
        handler) is detected by the per-group tallies, which the ALL_TYPES catch-all cannot.
        """
        from collections import Counter

        from pysmt.shortcuts import reset_env, Symbol, BVAdd, BVAnd, BVULT
        from pysmt.typing import BVType
        from pysmt.walkers import DagWalker, handles
        reset_env()

        class GroupRouter(DagWalker):
            @handles(op.BV_OPERATORS)
            def walk_bv_op(self, formula, args, **kwargs):
                counts = Counter()
                for a in args:
                    counts.update(a)
                counts["bvop"] += 1
                return counts

            @handles(op.RELATIONS)
            def walk_relation(self, formula, args, **kwargs):
                counts = Counter()
                for a in args:
                    counts.update(a)
                counts["rel"] += 1
                return counts

            @handles(set(op.ALL_TYPES) - op.BV_OPERATORS - op.RELATIONS)
            def walk_other(self, formula, args, **kwargs):
                counts = Counter()
                for a in args:
                    counts.update(a)
                counts["other"] += 1
                return counts

        x = Symbol("x", BVType(8))
        y = Symbol("y", BVType(8))
        f = BVULT(BVAnd(BVAdd(x, y), x), y)
        counts = GroupRouter().walk(f)
        # BV_OPERATORS nodes: BVAdd, BVAnd -> 2; RELATIONS node: BVULT -> 1;
        # remaining (the BV symbols) route to the fallback handler.
        self.assertEqual(counts["bvop"], 2)
        self.assertEqual(counts["rel"], 1)
        self.assertGreaterEqual(counts["other"], 1)


class TestScopeGapCoverage(unittest.TestCase):
    """Tests covering scope gaps: BVSMod, FreshSymbol, normalize, DAG printing,
    type errors, and complex BV pipelines."""

    def test_bvsmod_expansion(self):
        """BVSMod expands to a complex ITE expression that, when simplified on
        constants, yields the correct signed modulo result per SMT-LIB semantics."""
        from pysmt.shortcuts import reset_env, BV, SBV, simplify, get_env
        reset_env()
        mgr = get_env().formula_manager
        # Both positive: 7 smod 3 = 1
        r1 = simplify(mgr.BVSMod(BV(7, 8), BV(3, 8)))
        self.assertTrue(r1.is_bv_constant())
        self.assertEqual(r1.constant_value(), 1)
        # Negative dividend: -7 smod 3 = 2 (result sign matches divisor)
        r2 = simplify(mgr.BVSMod(SBV(-7, 8), BV(3, 8)))
        self.assertTrue(r2.is_bv_constant())
        self.assertEqual(r2.bv_signed_value(), 2)
        # Negative divisor: 7 smod -3 = -2 (result sign matches divisor)
        r3 = simplify(mgr.BVSMod(BV(7, 8), SBV(-3, 8)))
        self.assertTrue(r3.is_bv_constant())
        self.assertEqual(r3.bv_signed_value(), -2)
        # Both negative: -7 smod -3 = -1 (result sign matches divisor)
        r4 = simplify(mgr.BVSMod(SBV(-7, 8), SBV(-3, 8)))
        self.assertTrue(r4.is_bv_constant())
        self.assertEqual(r4.bv_signed_value(), -1)

    def test_fresh_symbol_and_normalize(self):
        """FreshSymbol generates unique names across calls. normalize() moves a
        formula from one FormulaManager into another, preserving structure but
        creating distinct FNode objects."""
        from pysmt.shortcuts import reset_env, Symbol, FreshSymbol, Equals, get_env
        from pysmt.typing import INT
        import pysmt.environment as penv
        reset_env()
        fs1 = FreshSymbol(INT)
        fs2 = FreshSymbol(INT)
        fs3 = FreshSymbol(INT)
        names = {fs1.symbol_name(), fs2.symbol_name(), fs3.symbol_name()}
        self.assertEqual(len(names), 3, "FreshSymbol must generate unique names")
        x = Symbol("x", INT)
        y = Symbol("y", INT)
        f = Equals(x, y)
        env1 = penv.get_env()
        self.assertIn(f, env1.formula_manager)
        penv.push_env()
        try:
            env2 = penv.get_env()
            self.assertIsNot(env1, env2)
            f_norm = env2.formula_manager.normalize(f)
            self.assertIn(f_norm, env2.formula_manager)
            self.assertIsNot(f, f_norm)
            self.assertTrue(f_norm.is_equals())
            norm_names = {a.symbol_name() for a in f_norm.args()}
            self.assertEqual(norm_names, {"x", "y"})
        finally:
            penv.pop_env()

    def test_smtlib_dag_printer(self):
        """SmtDagPrinter (daggify=True) emits let-bindings for shared subexpressions.
        Parse the output back and verify structural equality with the original."""
        from pysmt.shortcuts import (reset_env, Symbol, And, Or, to_smtlib)
        from pysmt.typing import BOOL
        from pysmt.smtlib.parser import SmtLibParser
        import pysmt.smtlib.script as script_mod
        reset_env()
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        c = Symbol("c", BOOL)
        d = Symbol("d", BOOL)
        shared = And(a, b)
        f = And(Or(shared, c), Or(shared, d))
        dag_str = to_smtlib(f, daggify=True)
        self.assertIn("let", dag_str)
        scr = script_mod.smtlibscript_from_formula(f)
        buf = StringIO()
        scr.serialize(buf, daggify=True)
        parser = SmtLibParser()
        s = parser.get_script(StringIO(buf.getvalue()))
        parsed = s.get_strict_formula()
        self.assertEqual(parsed, f)

    def test_type_error_handling(self):
        """Type mismatches raise PysmtTypeError: And(INT, BOOL), Plus(BOOL, BOOL),
        BVAdd with mismatched widths."""
        from pysmt.shortcuts import reset_env, Symbol, And, Plus, BV, BVAdd
        from pysmt.typing import INT, BOOL, BVType
        from pysmt.exceptions import PysmtTypeError
        reset_env()
        with self.assertRaises(PysmtTypeError):
            And(Symbol("ti_x", INT), Symbol("ti_y", BOOL))
        with self.assertRaises(PysmtTypeError):
            Plus(Symbol("ti_p", BOOL), Symbol("ti_q", BOOL))
        with self.assertRaises(PysmtTypeError):
            BVAdd(BV(1, 8), BV(2, 16))

    def test_complex_bv_simplification_pipeline(self):
        """Build a complex BV expression mixing BVAdd, BVSub, BVAnd, BVOr,
        BVExtract, BVConcat on constants and symbols. Substitute symbols with
        constants, simplify, serialize to SMT-LIB, parse back, verify equality."""
        from pysmt.shortcuts import (reset_env, Symbol, BV, BVAdd, BVSub, BVAnd,
                                      BVOr, BVExtract, BVConcat, simplify,
                                      substitute, to_smtlib, Equals)
        from pysmt.typing import BVType
        from pysmt.smtlib.parser import SmtLibParser
        import pysmt.smtlib.script as script_mod
        reset_env()
        x = Symbol("x", BVType(8))
        y = Symbol("y", BVType(8))
        expr = BVAnd(
            BVOr(BVAdd(x, BV(3, 8)), BV(0x0F, 8)),
            BVSub(BVConcat(BVExtract(y, 0, 3), BVExtract(y, 4, 7)), BV(1, 8))
        )
        self.assertEqual(expr.get_type(), BVType(8))
        expr2 = substitute(expr, {x: BV(0xAA, 8)})
        expr3 = simplify(expr2)
        expr4 = substitute(expr3, {y: BV(0x55, 8)})
        expr5 = simplify(expr4)
        # Fully constant after both substitutions: assert the computed value, not
        # just the shape. BVOr(BVAdd(0xAA,3),0x0F)=0xAF;
        # BVSub(BVConcat(Extract(0x55,0,3)=0x5, Extract(0x55,4,7)=0x5)=0x55, 1)=0x54;
        # BVAnd(0xAF, 0x54) = 0x04.
        self.assertEqual(expr5, BV(4, 8))
        f_eq = Equals(expr, BV(0, 8))
        scr = script_mod.smtlibscript_from_formula(f_eq)
        buf = StringIO()
        scr.serialize(buf)
        parser = SmtLibParser()
        s = parser.get_script(StringIO(buf.getvalue()))
        parsed = s.get_strict_formula()
        self.assertEqual(parsed, f_eq)


class TestHarderIntegration(unittest.TestCase):
    """Harder integration tests covering walker inheritance, quantified
    substitution, and CNF conversion of implication/iff formulas."""

    def test_walker_inheritance_and_override(self):
        """Create a DagWalker subclass with @handles for ALL_TYPES that computes
        depth. Then create a sub-subclass that overrides the AND handler using
        Walker.super() to call the parent. Verify both levels work correctly."""
        from pysmt.shortcuts import reset_env, Symbol, And, Or, Not
        from pysmt.typing import BOOL
        from pysmt.walkers import DagWalker, handles
        from pysmt.walkers.generic import Walker
        reset_env()

        class DepthCounter(DagWalker):
            """Counts the depth of a formula DAG."""
            @handles(op.ALL_TYPES)
            def walk_all(self, formula, args, **kwargs):
                if args:
                    return 1 + max(args)
                return 1

        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        f = And(a, Or(b, Not(a)))
        counter = DepthCounter()
        depth = counter.walk(f)
        self.assertEqual(depth, 4)

        class DoubleAndDepth(DepthCounter):
            """Doubles the depth contribution of AND nodes via Walker.super."""
            @handles(op.AND)
            def walk_and(self, formula, args, **kwargs):
                parent_result = DepthCounter.super(self, formula, args=args, **kwargs)
                return parent_result * 2

        counter2 = DoubleAndDepth()
        depth2 = counter2.walk(f)
        self.assertEqual(depth2, 8)

    def test_substitution_in_complex_quantified_formula(self):
        """Substitution must recurse through NESTED quantifiers, reaching the
        deepest body, while leaving both bound variables untouched.

        Build ForAll([x], Exists([y], And(Equals(x,y), Equals(y,z)))) and
        substitute {z: Int(5)}. The free z (which lives two quantifier levels
        deep) must be replaced, the bound x and y must be left alone, and the
        nested ForAll/Exists structure must be rebuilt intact. Unlike the
        single-quantifier scoping check in test_substitution_workflow, this pins
        the full concrete result so a substituter that stopped at the outer
        quantifier or dropped the inner Exists is caught.
        """
        from pysmt.shortcuts import (reset_env, Symbol, ForAll, Exists, And,
                                      Equals, Int, substitute, get_free_variables)
        from pysmt.typing import INT
        reset_env()
        x = Symbol("x", INT)
        y = Symbol("y", INT)
        z = Symbol("z", INT)
        f = ForAll([x], Exists([y], And(Equals(x, y), Equals(y, z))))
        fv_before = get_free_variables(f)
        self.assertEqual(fv_before, {z})
        result = substitute(f, {z: Int(5)})
        self.assertEqual(len(get_free_variables(result)), 0)
        # Full concrete result: substitution descended through both quantifier
        # levels (z -> 5 in the innermost conjunct) and preserved the nested
        # ForAll(Exists(...)) shape and the untouched x = y conjunct.
        expected = ForAll([x], Exists([y], And(Equals(x, y), Equals(y, Int(5)))))
        self.assertEqual(result, expected)

    def test_cnf_with_implications_and_iff(self):
        """Build a formula using Implies and Iff (not just And/Or). Convert to
        CNF via Tseitin. Verify the result is in CNF form (conjunction of
        disjunctions/literals). Verify satisfiability is preserved by checking
        that the same variable assignments satisfy both original and CNF."""
        from pysmt.shortcuts import (reset_env, Symbol, And, Implies, Iff,
                                      TRUE, FALSE, substitute, simplify,
                                      get_free_variables)
        from pysmt.typing import BOOL
        from pysmt.rewritings import CNFizer
        reset_env()
        a = Symbol("a", BOOL)
        b = Symbol("b", BOOL)
        c = Symbol("c", BOOL)
        f = And(Implies(a, b), Iff(b, c))
        cnf = CNFizer()
        cnf_f = cnf.convert_as_formula(f)
        def is_literal(node):
            return (node.is_symbol() or node.is_true() or node.is_false()
                    or (node.is_not() and node.arg(0).is_symbol()))
        if cnf_f.is_and():
            for clause in cnf_f.args():
                if clause.is_or():
                    for lit in clause.args():
                        self.assertTrue(is_literal(lit),
                                        "Non-literal in CNF clause: %s" % lit)
                else:
                    self.assertTrue(is_literal(clause),
                                    "Non-literal CNF clause: %s" % clause)
        cnf_aux_vars = get_free_variables(cnf_f) - get_free_variables(f)
        for av in [TRUE(), FALSE()]:
            for bv in [TRUE(), FALSE()]:
                for cv in [TRUE(), FALSE()]:
                    subs = {a: av, b: bv, c: cv}
                    orig_val = simplify(substitute(f, subs))
                    if orig_val == TRUE():
                        found_sat = False
                        aux_list = sorted(cnf_aux_vars, key=lambda v: v.symbol_name())
                        for bits in range(2 ** len(aux_list)):
                            aux_subs = dict(subs)
                            for j, aux_v in enumerate(aux_list):
                                aux_subs[aux_v] = TRUE() if (bits >> j) & 1 else FALSE()
                            cnf_val = simplify(substitute(cnf_f, aux_subs))
                            if cnf_val == TRUE():
                                found_sat = True
                                break
                        self.assertTrue(found_sat,
                                        "CNF not satisfiable for assignment %s" % subs)


if __name__ == "__main__":
    unittest.main()
