"""
End-to-end tests for pycparser — C99 parser in pure Python.
Each test chains: parse C → verify AST → generate C → re-parse → verify round-trip.
"""

import io
import sys


def _parse(code, filename='<test>'):
    from pycparser import CParser
    return CParser().parse(code, filename=filename)


def _parse_and_generate(code):
    from pycparser.c_generator import CGenerator
    return CGenerator().visit(_parse(code))


def _roundtrip_verify(code):
    generated = _parse_and_generate(code)
    return generated, _parse(generated)


# =============================================================================
# MEGA WORKFLOW 1: Lexer → Parse → Declarations → Expressions → Roundtrip
# =============================================================================

class TestFullParsingPipeline:
    def test_lex_parse_generate_roundtrip(self):
        """Full pipeline: lex tokens → parse declarations + expressions +
        statements → verify AST structure → generate C → re-parse → verify
        structure preserved. Covers keywords, operators, literals, types,
        pointers, arrays, qualifiers, storage, multi-declarators, precedence,
        ternary, cast, unary, struct ref, array ref, assignment ops."""
        from pycparser import c_ast
        from pycparser.c_lexer import CLexer, Token
        from pycparser.c_generator import CGenerator

        # --- Lexer: keywords, operators, numeric/string literals ---
        lexer = CLexer(
            error_func=lambda msg, line, col: None,
            on_lbrace_func=lambda: None,
            on_rbrace_func=lambda: None,
            type_lookup_func=lambda name: False,
        )
        lexer.input('int void return if while for x y z')
        tokens = []
        while True:
            tok = lexer.token()
            if tok is None:
                break
            tokens.append(tok)
        types = [t.type for t in tokens]
        assert types[:6] == ['INT', 'VOID', 'RETURN', 'IF', 'WHILE', 'FOR']
        assert types[6:] == ['ID', 'ID', 'ID']
        assert tokens[0].lineno == 1 and tokens[0].column >= 1

        lexer2 = CLexer(
            error_func=lambda msg, line, col: None,
            on_lbrace_func=lambda: None,
            on_rbrace_func=lambda: None,
            type_lookup_func=lambda name: False,
        )
        lexer2.input('+ - * / % && || == != -> ++ -- ... 42 0xFF 0b1010 3.14')
        op_types = []
        while True:
            tok = lexer2.token()
            if tok is None:
                break
            op_types.append(tok.type)
        for expected in ['PLUS', 'MINUS', 'TIMES', 'DIVIDE', 'MOD',
                         'LAND', 'LOR', 'EQ', 'NE', 'ARROW', 'PLUSPLUS', 'ELLIPSIS',
                         'INT_CONST_DEC', 'INT_CONST_HEX', 'INT_CONST_BIN']:
            assert expected in op_types

        lexer3 = CLexer(
            error_func=lambda msg, line, col: None,
            on_lbrace_func=lambda: None,
            on_rbrace_func=lambda: None,
            type_lookup_func=lambda name: False,
        )
        lexer3.input('"hello" \'x\' L"wide" L\'w\'')
        str_types = []
        while True:
            tok = lexer3.token()
            if tok is None:
                break
            str_types.append(tok.type)
        assert 'STRING_LITERAL' in str_types
        assert 'CHAR_CONST' in str_types
        assert 'WSTRING_LITERAL' in str_types
        assert 'WCHAR_CONST' in str_types

        # --- Declarations: basic types, pointers, arrays, qualifiers ---
        code_decls = 'int x; int *p; char **pp; int arr[10]; const int cx; static int sx;'
        ast = _parse(code_decls)
        assert ast.ext[0].name == 'x'
        assert isinstance(ast.ext[0].type, c_ast.TypeDecl)
        assert 'int' in ast.ext[0].type.type.names
        assert isinstance(ast.ext[1].type, c_ast.PtrDecl)
        assert isinstance(ast.ext[2].type.type, c_ast.PtrDecl)
        assert isinstance(ast.ext[3].type, c_ast.ArrayDecl)
        assert ast.ext[3].type.dim.value == '10'
        assert 'const' in ast.ext[4].quals
        assert 'static' in ast.ext[5].storage
        _roundtrip_verify(code_decls)

        # Multi declarators
        ast2 = _parse('int a, *b, c[10];')
        assert len(ast2.ext) == 3
        assert isinstance(ast2.ext[1].type, c_ast.PtrDecl)
        assert isinstance(ast2.ext[2].type, c_ast.ArrayDecl)

        # Function declarations
        ast3 = _parse('int foo(int a, float b);')
        assert isinstance(ast3.ext[0].type, c_ast.FuncDecl)
        assert len(ast3.ext[0].type.args.params) == 2
        _roundtrip_verify('int foo(int a, float b);')

        # --- More declarations: compound literals, _Atomic, scalar brace init,
        #     nested struct init, signal-style complex declaration ---
        code_cl = '''
        struct point { int x; int y; };
        void f() {
            struct point p = (struct point){.x = 10, .y = 20};
        }
        '''
        ast_cl = _parse(code_cl)
        assert isinstance(ast_cl.ext[1].body.block_items[0].init, c_ast.CompoundLiteral)
        _roundtrip_verify(code_cl)

        ast_at = _parse('_Atomic int x;')
        assert ast_at.ext[0].name == 'x'
        _roundtrip_verify('_Atomic int x;')
        _roundtrip_verify('int _Atomic *p;')

        ast_sc = _parse('int x = {0};')
        assert ast_sc.ext[0].name == 'x'
        assert isinstance(ast_sc.ext[0].init, c_ast.InitList)
        _roundtrip_verify('int x = {0};')

        code_nsi = '''
        struct inner { int x; int y; };
        struct outer { struct inner a; int b; };
        struct outer o = { { 1, 2 }, 3 };
        '''
        assert isinstance(_parse(code_nsi).ext[2].init, c_ast.InitList)
        _roundtrip_verify(code_nsi)

        ast_sig = _parse('void (*signal(int sig, void (*handler)(int)))(int);')
        assert ast_sig.ext[0].name == 'signal'
        _roundtrip_verify('void (*signal(int sig, void (*handler)(int)))(int);')

        # --- Expressions: precedence, ternary, cast, unary, struct/array ref ---
        ast4 = _parse('int x = a + b * c;')
        init = ast4.ext[0].init
        assert init.op == '+' and init.right.op == '*'
        ast5 = _parse('int x = a || b && c;')
        assert ast5.ext[0].init.op == '||' and ast5.ext[0].init.right.op == '&&'
        ast6 = _parse('int x = a ? b : c;')
        assert isinstance(ast6.ext[0].init, c_ast.TernaryOp)

        code_expr = '''
        void f() {
            float y = (float)x;
            int a = sizeof(int);
            int *p = &x;
            int v = *p;
            int d = s.x;
            int e = p->y;
            int g = arr[5];
            x += 5; y *= 2; z >>= 1;
        }
        '''
        ast7 = _parse(code_expr)
        items = ast7.ext[0].body.block_items
        assert isinstance(items[0].init, c_ast.Cast)
        assert items[1].init.op == 'sizeof'
        assert items[2].init.op == '&'
        assert items[3].init.op == '*'
        assert isinstance(items[4].init, c_ast.StructRef) and items[4].init.type == '.'
        assert isinstance(items[5].init, c_ast.StructRef) and items[5].init.type == '->'
        assert isinstance(items[6].init, c_ast.ArrayRef)
        assert items[7].op == '+=' and items[8].op == '*=' and items[9].op == '>>='
        _roundtrip_verify(code_expr)


# =============================================================================
# MEGA WORKFLOW 2: Statements + Control Flow → Roundtrip
# =============================================================================

class TestStatementsPipeline:
    def test_full_control_flow_and_roundtrip(self):
        """Function with if/else, for, while, do-while, switch, goto/label,
        function calls — verify AST types and roundtrip."""
        from pycparser import c_ast

        code = '''
        int compute(int x) {
            int result = 0;
            if (x > 0) { result = x; } else { result = -x; }
            for (int i = 0; i < x; i++) { result += i; }
            while (result > 100) { result--; }
            do { result++; } while (result < 0);
            switch (result) {
                case 0: break;
                case 1: break;
                default: break;
            }
            goto end;
            end: return result;
        }
        '''
        ast = _parse(code)
        func = ast.ext[0]
        assert isinstance(func, c_ast.FuncDef) and func.decl.name == 'compute'
        items = func.body.block_items
        assert isinstance(items[1], c_ast.If)
        assert items[1].iftrue is not None and items[1].iffalse is not None
        assert isinstance(items[2], c_ast.For)
        assert items[2].init is not None and items[2].cond is not None and items[2].next is not None
        assert isinstance(items[3], c_ast.While)
        assert isinstance(items[4], c_ast.DoWhile)
        assert isinstance(items[5], c_ast.Switch)
        assert isinstance(items[6], c_ast.Goto) and items[6].name == 'end'
        assert isinstance(items[7], c_ast.Label) and items[7].name == 'end'

        generated, ast2 = _roundtrip_verify(code)
        assert ast2.ext[0].decl.name == 'compute'
        # The re-parsed body has exactly 8 top-level statements (decl, if, for,
        # while, do-while, switch, goto, labeled return) — pin it, not a lower bound.
        assert len(ast2.ext[0].body.block_items) == 8

        # Function call in expression
        code2 = 'void f() { printf("hello %d", x); }'
        ast3 = _parse(code2)
        call = ast3.ext[0].body.block_items[0]
        assert isinstance(call, c_ast.FuncCall)
        assert call.name.name == 'printf'
        assert isinstance(call.args, c_ast.ExprList)


# =============================================================================
# MEGA WORKFLOW 3: Generator + Visitor + Rewriting + Serialization
# =============================================================================

class TestGeneratorVisitorPipeline:
    def test_generator_visitor_rewrite_serialize(self):
        """Generator roundtrip + reduce_parentheses + NodeVisitor collection +
        parent tracking + AST rewriting + function call finding +
        show() options + children/coord/iteration."""
        from pycparser import c_ast
        from pycparser.c_ast import NodeVisitor
        from pycparser.c_generator import CGenerator
        from pycparser.c_parser import Coord

        # --- Generator roundtrip ---
        code = 'int add(int a, int b) { return a + b; }'
        generated, ast2 = _roundtrip_verify(code)
        assert ast2.ext[0].decl.name == 'add'
        assert len(ast2.ext[0].decl.type.args.params) == 2
        assert any(isinstance(item, c_ast.Return) for item in ast2.ext[0].body.block_items)

        # --- Indentation ---
        # The inner statement sits one compound-block level deeper than the enclosing `if`
        # (function body -> if body), so the generator must place `y = 1;` on its own line indented
        # strictly further from the margin than the `if (x)` line. (We check the real nesting depth
        # rather than the exact indent width, which is generator formatting the spec leaves open.)
        gen_if = _parse_and_generate('void f() { if (x) { y = 1; } }')
        def _indent(prefix):
            line = next(l for l in gen_if.split('\n') if l.strip().startswith(prefix))
            return len(line) - len(line.lstrip())
        assert _indent('y = 1;') > _indent('if')

        # --- reduce_parentheses ---
        # Chained same-precedence ops carry redundant parens that reduce_parentheses must strip:
        # default emits the fully-parenthesized form, reduce_parentheses=True drops all of them.
        ast_p = _parse('int x = a + b + c + d;')
        out_normal = CGenerator().visit(ast_p)
        out_reduced = CGenerator(reduce_parentheses=True).visit(ast_p)
        assert out_normal.strip() == 'int x = ((a + b) + c) + d;'
        assert out_reduced.strip() == 'int x = a + b + c + d;'
        assert out_reduced.count('(') < out_normal.count('(')
        _parse(out_normal)
        _parse(out_reduced)

        # --- NodeVisitor: collect functions + count ops ---
        code2 = '''
        int foo() { return 1 + 2; }
        void bar() { return; }
        int main() { return foo() + 3 * 4; }
        '''
        ast3 = _parse(code2)

        class Analyzer(NodeVisitor):
            def __init__(self):
                self.func_names = []
                self.op_count = 0
            def visit_FuncDef(self, node):
                self.func_names.append(node.decl.name)
                self.generic_visit(node)
            def visit_BinaryOp(self, node):
                self.op_count += 1
                self.generic_visit(node)

        a = Analyzer()
        a.visit(ast3)
        assert a.func_names == ['foo', 'bar', 'main']
        assert a.op_count == 3

        # --- generic_visit traverses all ---
        class Counter(NodeVisitor):
            def __init__(self):
                self.count = 0
            def generic_visit(self, node):
                self.count += 1
                for _, child in node.children():
                    self.visit(child)
        c = Counter()
        c.visit(ast3)
        # generic_visit fires once per node, so this proves the traversal reaches every node.
        # Empty () parameter lists and the argument-less foo() call contribute no parameter/arg
        # child nodes (FuncDecl.args / FuncCall.args are None), so the snippet has exactly 31 nodes
        # — an over-generated empty ParamList/ExprList would push the total above it.
        assert c.count == 31

        # --- Parent tracking ---
        code3 = '''
        int f() {
            if (1) { if (2) { return 42; } }
            return 0;
        }
        '''
        ast4 = _parse(code3)

        class StackTracker(NodeVisitor):
            def __init__(self):
                self.stack = []
                self.return_ancestors = None
            def generic_visit(self, node):
                self.stack.append(node)
                if isinstance(node, c_ast.Return) and node.expr is not None:
                    if hasattr(node.expr, 'value') and node.expr.value == '42':
                        self.return_ancestors = list(self.stack)
                for c in node:
                    self.visit(c)
                self.stack.pop()

        st = StackTracker()
        st.visit(ast4)
        assert st.return_ancestors is not None
        ancestor_types = [type(n).__name__ for n in st.return_ancestors]
        assert ancestor_types[0] == 'FileAST'
        assert ancestor_types.count('If') == 2
        assert ancestor_types[-1] == 'Return'

        # --- AST rewriting: add _hidden param ---
        code4 = '''
        int foo(int a) { return a; }
        void bar(float x, float y) { return; }
        int baz() { return 0; }
        '''
        ast5 = _parse(code4)

        class AddParam(NodeVisitor):
            def visit_FuncDecl(self, node):
                hidden = c_ast.Decl(
                    name='_hidden', quals=[], align=[], storage=[], funcspec=[],
                    type=c_ast.TypeDecl(declname='_hidden', quals=[], align=None,
                                        type=c_ast.IdentifierType(names=['int'])),
                    init=None, bitsize=None)
                if node.args is None:
                    node.args = c_ast.ParamList(params=[hidden])
                else:
                    node.args.params.append(hidden)

        AddParam().visit(ast5)
        gen5 = CGenerator().visit(ast5)
        ast5b = _parse(gen5)
        for ext in ast5b.ext:
            if isinstance(ext, c_ast.FuncDef):
                param_names = [p.name for p in ext.decl.type.args.params]
                assert '_hidden' in param_names

        # --- Rename ID references ---
        ast6 = _parse('void f() { int x = 1; int y = x + 2; int z = x + y; }')
        class Renamer(NodeVisitor):
            def visit_ID(self, node):
                if node.name not in ('f',):
                    node.name = 'v_' + node.name
        Renamer().visit(ast6)
        gen6 = CGenerator().visit(ast6)
        assert 'v_x' in gen6 and 'v_y' in gen6

        # --- Find function calls ---
        code5 = '''
        void f() {
            int *a = (int *)malloc(sizeof(int) * 10);
            int *b = (int *)malloc(100);
            free(a);
            int *c = (int *)malloc(sizeof(int));
            free(b);
        }
        '''
        ast7 = _parse(code5)
        class CallFinder(NodeVisitor):
            def __init__(self, name):
                self.name = name
                self.calls = []
            def visit_FuncCall(self, node):
                if isinstance(node.name, c_ast.ID) and node.name.name == self.name:
                    self.calls.append(node)
                self.generic_visit(node)
        mf = CallFinder('malloc'); mf.visit(ast7)
        assert len(mf.calls) == 3
        ff = CallFinder('free'); ff.visit(ast7)
        assert len(ff.calls) == 2

        # --- show() options ---
        ast8 = _parse('int x = 42;', filename='demo.c')
        buf1 = io.StringIO(); ast8.show(buf=buf1)
        assert 'FileAST' in buf1.getvalue() and 'Decl' in buf1.getvalue()
        buf2 = io.StringIO(); ast8.show(buf=buf2, attrnames=True)
        assert 'x' in buf2.getvalue()
        buf3 = io.StringIO(); ast8.show(buf=buf3, showcoord=True)
        assert 'demo.c' in buf3.getvalue()
        buf4 = io.StringIO(); ast8.show(buf=buf4, nodenames=True)
        assert 'ext[0]' in buf4.getvalue()

        # --- children + coord + iteration ---
        ast9 = _parse('int x = a + b;\nfloat y;', filename='test.c')
        child_names = [name for name, _ in ast9.ext[0].children()]
        assert 'type' in child_names and 'init' in child_names
        assert ast9.ext[0].coord.file == 'test.c' and ast9.ext[0].coord.line == 1
        assert ast9.ext[1].coord.line == 2
        assert 'test.c' in str(Coord('test.c', 10, 5))
        children = list(ast9)
        assert len(children) == 2


# =============================================================================
# FAILING TESTS (keep separate — each exercises a distinct hard grammar area)
# =============================================================================

class TestComplexDeclarators:
    def test_function_pointer_and_complex_declarators(self):
        """Function pointers, array of pointers, pointer to array — roundtrip."""
        from pycparser import c_ast

        ast = _parse('int (*fp)(int, int);')
        assert ast.ext[0].name == 'fp'
        assert isinstance(ast.ext[0].type, c_ast.PtrDecl)
        assert isinstance(ast.ext[0].type.type, c_ast.FuncDecl)
        ast2 = _parse('int *arr[5];')
        assert isinstance(ast2.ext[0].type, c_ast.ArrayDecl)
        assert isinstance(ast2.ext[0].type.type, c_ast.PtrDecl)
        ast3 = _parse('int (*pa)[10];')
        assert isinstance(ast3.ext[0].type, c_ast.PtrDecl)
        assert isinstance(ast3.ext[0].type.type, c_ast.ArrayDecl)
        code = 'int *(*fp)(int, float);'
        generated, ast4 = _roundtrip_verify(code)
        assert ast4.ext[0].name == 'fp'
        assert isinstance(ast4.ext[0].type, c_ast.PtrDecl)
        assert isinstance(ast4.ext[0].type.type, c_ast.FuncDecl)
        assert len(ast4.ext[0].type.type.args.params) == 2


class TestTypedefScope:
    def test_typedef_struct_enum_union(self):
        """Typedef + usage, struct, enum, union — requires scope tracking."""
        from pycparser import c_ast

        code = '''
        typedef int myint;
        myint x;
        struct point { int x; int y; };
        enum color { RED, GREEN, BLUE };
        union value { int i; float f; char *s; };
        '''
        ast = _parse(code)
        assert isinstance(ast.ext[0], c_ast.Typedef) and ast.ext[0].name == 'myint'
        assert isinstance(ast.ext[1], c_ast.Decl) and ast.ext[1].name == 'x'
        assert isinstance(ast.ext[2].type, c_ast.Struct) and len(ast.ext[2].type.decls) == 2
        assert len(ast.ext[3].type.values.enumerators) == 3
        assert isinstance(ast.ext[4].type, c_ast.Union) and len(ast.ext[4].type.decls) == 3
        gen, ast2 = _roundtrip_verify('struct point { int x; int y; };')
        assert ast2.ext[0].type.name == 'point'
        field_names = [d.name for d in ast2.ext[0].type.decls]
        assert 'x' in field_names and 'y' in field_names


class TestStructRoundtrip:
    def test_roundtrip_struct_fields(self):
        """Struct field *types* (pointer, sized array, multi-word) must survive generate → re-parse,
        not just the field names."""
        from pycparser import c_ast

        code = 'struct rec { char *name; double scores[4]; unsigned int flags; };'
        generated, ast2 = _roundtrip_verify(code)
        struct = ast2.ext[0].type
        assert isinstance(struct, c_ast.Struct) and struct.name == 'rec'
        assert [d.name for d in struct.decls] == ['name', 'scores', 'flags']
        # char *name — pointer to char
        assert isinstance(struct.decls[0].type, c_ast.PtrDecl)
        assert struct.decls[0].type.type.type.names == ['char']
        # double scores[4] — sized array of double
        assert isinstance(struct.decls[1].type, c_ast.ArrayDecl)
        assert struct.decls[1].type.dim.value == '4'
        assert struct.decls[1].type.type.type.names == ['double']
        # unsigned int flags — multi-word type specifier
        assert struct.decls[2].type.type.names == ['unsigned', 'int']


class TestPreprocessedCode:
    def test_parse_preprocessed_program(self):
        """Simulated cpp + fake_libc_include: typedefs + struct + functions → roundtrip."""
        from pycparser import c_ast
        from pycparser.c_ast import NodeVisitor
        from pycparser.c_generator import CGenerator

        code = '''
        typedef unsigned long size_t;
        typedef struct _IO_FILE FILE;

        extern int fprintf(FILE *stream, const char *fmt, ...);
        extern void *malloc(size_t size);
        extern void free(void *ptr);

        struct buffer {
            char *data;
            size_t len;
            size_t cap;
        };

        struct buffer *buffer_new(size_t initial_cap) {
            struct buffer *buf = (struct buffer *)malloc(sizeof(struct buffer));
            buf->data = (char *)malloc(initial_cap);
            buf->len = 0;
            buf->cap = initial_cap;
            return buf;
        }

        void buffer_free(struct buffer *buf) {
            if (buf != (void *)0) {
                free(buf->data);
                free(buf);
            }
        }

        int main() {
            struct buffer *b = buffer_new(1024);
            fprintf(stdout, "len=%lu\\n", b->len);
            buffer_free(b);
            return 0;
        }
        '''
        ast = _parse(code)

        class TC(NodeVisitor):
            def __init__(self): self.typedefs = []
            def visit_Typedef(self, node): self.typedefs.append(node.name)
        tc = TC(); tc.visit(ast)
        assert 'size_t' in tc.typedefs and 'FILE' in tc.typedefs

        class FC(NodeVisitor):
            def __init__(self): self.defined = []
            def visit_FuncDef(self, node): self.defined.append(node.decl.name)
        fc = FC(); fc.visit(ast)
        assert set(fc.defined) == {'buffer_new', 'buffer_free', 'main'}

        found_struct = False
        for ext in ast.ext:
            if isinstance(ext, c_ast.Decl) and isinstance(ext.type, c_ast.Struct):
                if ext.type.name == 'buffer':
                    found_struct = True
                    assert set(d.name for d in ext.type.decls) == {'data', 'len', 'cap'}
        assert found_struct

        generated = CGenerator().visit(ast)
        ast2 = _parse(generated)
        fc2 = FC(); fc2.visit(ast2)
        assert set(fc2.defined) == set(fc.defined)


class TestParseErrors:
    def test_parse_errors(self):
        """Invalid C constructs raise ParseError."""
        from pycparser.c_parser import ParseError
        from pycparser import CParser
        import pytest
        parser = CParser()
        with pytest.raises(ParseError):
            parser.parse('int int int;')
        with pytest.raises(ParseError):
            parser.parse('int x\nint y;')
        with pytest.raises(ParseError):
            parser.parse('void f() { int x = 1;')


class TestNestedStructTypedef:
    def test_nested_struct_and_complex_typedef(self):
        """Nested struct and function pointer typedef — parse and roundtrip."""
        from pycparser import c_ast

        code = '''
        struct outer {
            struct inner { int x; } field;
            int y;
        };
        '''
        ast = _parse(code)
        assert isinstance(ast.ext[0].type, c_ast.Struct) and ast.ext[0].type.name == 'outer'
        _roundtrip_verify(code)

        code2 = 'typedef int (*callback_t)(void *, int);'
        ast2 = _parse(code2)
        assert isinstance(ast2.ext[0], c_ast.Typedef) and ast2.ext[0].name == 'callback_t'
        _roundtrip_verify(code2)


# =============================================================================
# MEGA WORKFLOW 4: Complex cases + large program
# =============================================================================

# =============================================================================
# Hard C grammar features (each is a genuine, distinct grammar challenge)
# =============================================================================

class TestBitfields:
    def test_bitfield_struct_roundtrip(self):
        """Parse struct with bitfield members, verify bitsize in AST, roundtrip."""
        from pycparser import c_ast
        code = '''
        struct flags {
            unsigned int readable : 1;
            unsigned int writable : 1;
            unsigned int executable : 1;
            unsigned int reserved : 5;
        };
        '''
        ast = _parse(code)
        struct = ast.ext[0].type
        assert isinstance(struct, c_ast.Struct)
        for decl in struct.decls:
            assert decl.bitsize is not None
        assert struct.decls[0].bitsize.value == '1'
        assert struct.decls[3].bitsize.value == '5'
        _roundtrip_verify(code)


class TestCommaOperator:
    def test_comma_operator_roundtrip(self):
        """Parse comma operator in expression, verify ExprList, roundtrip."""
        from pycparser import c_ast
        code = 'void f() { int x = (1, 2, 3); }'
        ast = _parse(code)
        # Comma operator produces an ExprList of the three constants
        init = ast.ext[0].body.block_items[0].init
        assert isinstance(init, c_ast.ExprList)
        assert [e.value for e in init.exprs] == ['1', '2', '3']
        _roundtrip_verify(code)


class TestMultiDimArray:
    def test_multi_dimensional_array_roundtrip(self):
        """Parse multi-dimensional array, verify nested ArrayDecl, roundtrip."""
        from pycparser import c_ast
        code = 'int matrix[3][4][5];'
        ast = _parse(code)
        decl = ast.ext[0]
        assert isinstance(decl.type, c_ast.ArrayDecl)
        assert isinstance(decl.type.type, c_ast.ArrayDecl)
        assert isinstance(decl.type.type.type, c_ast.ArrayDecl)
        _roundtrip_verify(code)


class TestFuncPtrParam:
    def test_function_pointer_as_parameter(self):
        """Parse function taking a function pointer parameter, verify and roundtrip."""
        from pycparser import c_ast
        code = 'void sort(int *arr, int n, int (*cmp)(int, int));'
        ast = _parse(code)
        params = ast.ext[0].type.args.params
        assert len(params) == 3
        # Third param should be a function pointer
        cmp_param = params[2]
        assert cmp_param.name == 'cmp'
        assert isinstance(cmp_param.type, c_ast.PtrDecl)
        assert isinstance(cmp_param.type.type, c_ast.FuncDecl)
        _roundtrip_verify(code)


class TestNestedDesignatedInit:
    def test_nested_designated_initializer(self):
        """Parse nested designated initializer: { .a = { .b = 1 } }, roundtrip."""
        from pycparser import c_ast
        code = '''
        struct inner { int val; };
        struct outer { struct inner field; int x; };
        struct outer o = { .field = { .val = 42 }, .x = 10 };
        '''
        ast = _parse(code)
        init = ast.ext[2].init
        assert isinstance(init, c_ast.InitList)
        # Should have NamedInitializers
        for expr in init.exprs:
            assert isinstance(expr, c_ast.NamedInitializer)
        _roundtrip_verify(code)


class TestFlexibleArrayMember:
    def test_flexible_array_member(self):
        """Parse struct with flexible array member (no size), roundtrip."""
        from pycparser import c_ast
        code = '''
        struct packet {
            int len;
            char data[];
        };
        '''
        ast = _parse(code)
        struct = ast.ext[0].type
        assert isinstance(struct, c_ast.Struct)
        last_field = struct.decls[-1]
        assert last_field.name == 'data'
        assert isinstance(last_field.type, c_ast.ArrayDecl)
        assert last_field.type.dim is None
        _roundtrip_verify(code)


class TestComplexSizeof:
    def test_sizeof_on_complex_type(self):
        """Parse sizeof with complex type argument, verify UnaryOp and the
        type expression inside sizeof. Anonymous struct inside sizeof must
        produce a Struct node with 2 fields."""
        from pycparser import c_ast
        code = '''
        void f() {
            int a = sizeof(int);
            int b = sizeof(int *);
            int c = sizeof(struct { int x; int y; });
            int d = sizeof(_Atomic(int));
        }
        '''
        ast = _parse(code)
        items = ast.ext[0].body.block_items
        assert items[0].init.op == 'sizeof'
        assert items[1].init.op == 'sizeof'
        assert items[2].init.op == 'sizeof'
        assert items[3].init.op == 'sizeof'
        # sizeof(int *) — the expr should be a Typename with PtrDecl
        sizeof_ptr = items[1].init
        assert isinstance(sizeof_ptr.expr, c_ast.Typename)
        assert isinstance(sizeof_ptr.expr.type, c_ast.PtrDecl)
        # sizeof(struct { int x; int y; }) — anonymous struct with 2 fields
        sizeof_struct = items[2].init
        assert isinstance(sizeof_struct.expr, c_ast.Typename)
        struct_type = sizeof_struct.expr.type.type
        assert isinstance(struct_type, c_ast.Struct)
        assert len(struct_type.decls) == 2
        field_names = [d.name for d in struct_type.decls]
        assert 'x' in field_names and 'y' in field_names
        # sizeof(_Atomic(int)) — the _Atomic(...) specifier inside an abstract type-name, a
        # different grammar path from a declaration's declaration-specifiers.
        assert isinstance(items[3].init.expr, c_ast.Typename)
        _roundtrip_verify(code)


class TestArrayOfFuncPtrsTypedef:
    def test_typedef_array_of_function_pointers(self):
        """typedef void (*handler_t[3])(int); — verify the full declarator chain:
        Typedef > ArrayDecl > PtrDecl > FuncDecl."""
        from pycparser import c_ast
        code = 'typedef void (*handler_table[3])(int);'
        ast = _parse(code)
        td = ast.ext[0]
        assert isinstance(td, c_ast.Typedef)
        assert td.name == 'handler_table'
        # Verify declarator nesting: ArrayDecl > PtrDecl > FuncDecl
        arr = td.type
        assert isinstance(arr, c_ast.ArrayDecl)
        assert arr.dim.value == '3'
        ptr = arr.type
        assert isinstance(ptr, c_ast.PtrDecl)
        func = ptr.type
        assert isinstance(func, c_ast.FuncDecl)
        assert len(func.args.params) == 1
        _roundtrip_verify(code)


class TestComplexTypeSpecifiers:
    def test_complex_type_specifier_combinations(self):
        """Parse complex type specifier combinations and verify roundtrip.
        unsigned long long int, signed char, const volatile — order matters."""
        from pycparser import c_ast
        code = '''
        unsigned long long int x;
        const volatile int *p;
        static const char *msg;
        extern unsigned short y;
        '''
        ast = _parse(code)
        assert len(ast.ext) == 4
        generated, ast2 = _roundtrip_verify(code)
        assert len(ast2.ext) == 4
        # Multi-word specifier ORDER must survive the roundtrip exactly:
        # unsigned long long int -> ['unsigned', 'long', 'long', 'int'] (not reordered or dropped).
        first_type = ast2.ext[0].type.type
        assert isinstance(first_type, c_ast.IdentifierType)
        assert first_type.names == ['unsigned', 'long', 'long', 'int']
        # const volatile int *p — qualifiers preserved on the pointee.
        assert isinstance(ast2.ext[1].type, c_ast.PtrDecl)
        assert ast2.ext[1].type.type.quals == ['const', 'volatile']
        assert ast2.ext[1].type.type.type.names == ['int']
        # static const char *msg — storage class + pointer-to-char preserved.
        assert ast2.ext[2].storage == ['static']
        assert ast2.ext[2].type.type.type.names == ['char']
        # extern unsigned short y — storage class + multi-word base type preserved.
        assert ast2.ext[3].storage == ['extern']
        assert ast2.ext[3].type.type.names == ['unsigned', 'short']


class TestPragmaAndAlignas:
    def test_pragma_and_alignas(self):
        """Parse _Pragma and _Alignas — C11 features listed in the AST node types."""
        from pycparser import c_ast
        code_pragma = '_Pragma("pack(push, 1)");'
        ast = _parse(code_pragma)
        assert isinstance(ast.ext[0], c_ast.Pragma)
        # The _Pragma operator form carries the parenthesized string literal as its payload
        # (a Constant), so the pragma text must actually be captured, not just recognized.
        assert isinstance(ast.ext[0].string, c_ast.Constant)
        assert ast.ext[0].string.value == '"pack(push, 1)"'

        code_alignas = '_Alignas(16) int aligned_var;'
        ast2 = _parse(code_alignas)
        decl = ast2.ext[0]
        assert decl.name == 'aligned_var'
        # The _Alignas(16) specifier must be captured as an Alignas node with alignment 16,
        # not silently dropped while the declarator name still parses.
        assert decl.align and isinstance(decl.align[0], c_ast.Alignas)
        assert decl.align[0].alignment.value == '16'
        gen_alignas, _ = _roundtrip_verify(code_alignas)
        assert '_Alignas(16)' in gen_alignas


class TestASTJsonSerialization:
    def test_ast_to_json_serialization(self):
        """Serialize AST to JSON dict using children(), attr_names, and coord.
        Follows pycparser's official serialization format:
        - _nodetype: class name
        - leaf attributes from attr_names
        - child nodes as nested dicts
        - coord as 'filename:line[:column]' string
        Verify the JSON captures the full AST structure."""
        from pycparser import c_ast
        from pycparser.c_generator import CGenerator
        import json

        code = '''
        int factorial(int n) {
            if (n <= 1) { return 1; }
            return n * factorial(n - 1);
        }
        '''
        ast = _parse(code, filename='test.c')

        # Serialize using children() and attr_names
        def ast_to_dict(node):
            d = {'_nodetype': type(node).__name__}
            for attr in node.attr_names:
                d[attr] = getattr(node, attr)
            if node.coord:
                d['coord'] = str(node.coord)
            else:
                d['coord'] = None
            for name, child in node.children():
                d[name] = ast_to_dict(child)
            return d

        serialized = ast_to_dict(ast)
        assert serialized['_nodetype'] == 'FileAST'

        # Round-trip through JSON
        json_str = json.dumps(serialized, default=str)
        parsed_back = json.loads(json_str)
        assert parsed_back['_nodetype'] == 'FileAST'

        # Verify structure: find FuncDef for 'factorial'
        found_func = False
        def find_in_dict(d):
            nonlocal found_func
            if isinstance(d, dict):
                if d.get('_nodetype') == 'FuncDef':
                    found_func = True
                for v in d.values():
                    find_in_dict(v)
            elif isinstance(d, list):
                for item in d:
                    find_in_dict(item)
        find_in_dict(parsed_back)
        assert found_func

        # Verify coord appears in serialized form
        assert 'test.c' in json_str

        # Count node types in serialized AST
        node_types = []
        def collect_types(d):
            if isinstance(d, dict) and '_nodetype' in d:
                node_types.append(d['_nodetype'])
                for v in d.values():
                    collect_types(v)
            elif isinstance(d, list):
                for item in d:
                    collect_types(item)
        collect_types(parsed_back)
        assert 'FuncDef' in node_types
        assert 'If' in node_types
        assert 'Return' in node_types
        assert 'BinaryOp' in node_types
        assert 'FuncCall' in node_types

        # Leaf attributes must round-trip through JSON, not just node types: the
        # if-condition `n <= 1` serializes to a BinaryOp carrying op == '<='.
        binop_ops = []
        def collect_binop_ops(d):
            if isinstance(d, dict):
                if d.get('_nodetype') == 'BinaryOp':
                    binop_ops.append(d.get('op'))
                for v in d.values():
                    collect_binop_ops(v)
            elif isinstance(d, list):
                for item in d:
                    collect_binop_ops(item)
        collect_binop_ops(parsed_back)
        assert '<=' in binop_ops


class TestEnumExpressionValues:
    def test_enum_with_expression_values(self):
        """Enum with expression-valued constants, verify and roundtrip."""
        from pycparser import c_ast
        code = 'enum flags { READ = 1, WRITE = 2, EXEC = 4, ALL = 7 };'
        ast = _parse(code)
        enum = ast.ext[0].type
        assert isinstance(enum, c_ast.Enum)
        assert len(enum.values.enumerators) == 4
        # Verify the concrete enumerator values: each value is a Constant whose .value is the literal text
        for e in enum.values.enumerators:
            assert isinstance(e.value, c_ast.Constant)
        assert [e.name for e in enum.values.enumerators] == ['READ', 'WRITE', 'EXEC', 'ALL']
        assert [e.value.value for e in enum.values.enumerators] == ['1', '2', '4', '7']
        _roundtrip_verify(code)


class TestComplexCastCall:
    def test_cast_to_function_pointer_and_call(self):
        """Parse function pointer cast followed by call: ((void(*)(int))ptr)(42);
        Verify the FuncCall wraps a Cast wrapping a function pointer type."""
        from pycparser import c_ast
        code = 'void f() { ((void (*)(int))ptr)(42); }'
        ast = _parse(code)
        stmt = ast.ext[0].body.block_items[0]
        # Should be FuncCall whose name is a Cast
        assert isinstance(stmt, c_ast.FuncCall)
        assert isinstance(stmt.name, c_ast.Cast)
        # The cast target should be ID 'ptr'
        assert isinstance(stmt.name.expr, c_ast.ID)
        assert stmt.name.expr.name == 'ptr'
        # The argument should be Constant 42
        assert isinstance(stmt.args, c_ast.ExprList)
        assert isinstance(stmt.args.exprs[0], c_ast.Constant)
        assert stmt.args.exprs[0].value == '42'
        _roundtrip_verify(code)


class TestReturnStructLiteral:
    def test_return_compound_literal(self):
        """Parse function returning a compound literal. Verify the Return
        contains a CompoundLiteral with NamedInitializers."""
        from pycparser import c_ast
        code = '''
        struct point { int x; int y; };
        struct point make_point(int x, int y) {
            return (struct point){ .x = x, .y = y };
        }
        '''
        ast = _parse(code)
        func = ast.ext[1]
        assert isinstance(func, c_ast.FuncDef)
        ret = func.body.block_items[0]
        assert isinstance(ret, c_ast.Return)
        assert isinstance(ret.expr, c_ast.CompoundLiteral)
        assert isinstance(ret.expr.init, c_ast.InitList)
        for expr in ret.expr.init.exprs:
            assert isinstance(expr, c_ast.NamedInitializer)
        _roundtrip_verify(code)


class TestBuildASTFromScratch:
    def test_construct_ast_and_generate_c(self):
        """Build an AST programmatically from scratch (no parsing), then
        generate C code and verify it parses back correctly."""
        from pycparser import c_ast
        from pycparser.c_generator import CGenerator

        # Build: int add(int a, int b) { return a + b; }
        func_decl = c_ast.FuncDecl(
            args=c_ast.ParamList(params=[
                c_ast.Decl(name='a', quals=[], align=[], storage=[], funcspec=[],
                           type=c_ast.TypeDecl(declname='a', quals=[], align=None,
                                               type=c_ast.IdentifierType(names=['int'])),
                           init=None, bitsize=None),
                c_ast.Decl(name='b', quals=[], align=[], storage=[], funcspec=[],
                           type=c_ast.TypeDecl(declname='b', quals=[], align=None,
                                               type=c_ast.IdentifierType(names=['int'])),
                           init=None, bitsize=None),
            ]),
            type=c_ast.TypeDecl(declname='add', quals=[], align=None,
                                type=c_ast.IdentifierType(names=['int']))
        )
        func_def = c_ast.FuncDef(
            decl=c_ast.Decl(name='add', quals=[], align=[], storage=[], funcspec=[],
                            type=func_decl, init=None, bitsize=None),
            param_decls=None,
            body=c_ast.Compound(block_items=[
                c_ast.Return(expr=c_ast.BinaryOp(
                    op='+',
                    left=c_ast.ID(name='a'),
                    right=c_ast.ID(name='b')
                ))
            ])
        )
        file_ast = c_ast.FileAST(ext=[func_def])

        # Generate C code from hand-built AST. The AST renders deterministically;
        # the single binary op needs no parentheses under the default generator.
        gen = CGenerator()
        generated = gen.visit(file_ast)
        assert 'int add' in generated
        assert 'return a + b;' in generated

        # Re-parse the generated code and pin the body: the Return wraps a
        # BinaryOp '+' over IDs 'a' and 'b' (not just "some Return exists").
        ast2 = _parse(generated)
        func = ast2.ext[0]
        assert isinstance(func, c_ast.FuncDef)
        assert func.decl.name == 'add'
        assert len(func.decl.type.args.params) == 2
        ret = func.body.block_items[0]
        assert isinstance(ret, c_ast.Return)
        assert isinstance(ret.expr, c_ast.BinaryOp)
        assert ret.expr.op == '+'
        assert ret.expr.left.name == 'a'
        assert ret.expr.right.name == 'b'


class TestKRStyleFunction:
    def test_kr_style_function_roundtrip(self):
        """K&R (old-style) function definition with parameter types declared
        separately. Verify param_decls contains the K&R parameter declarations."""
        from pycparser import c_ast
        code = '''
        int main(argc, argv)
        int argc;
        char** argv;
        {
            return 0;
        }
        '''
        ast = _parse(code)
        func = ast.ext[0]
        assert isinstance(func, c_ast.FuncDef)
        assert func.decl.name == 'main'
        # K&R functions have param_decls (separate from the declarator params)
        assert func.param_decls is not None
        assert len(func.param_decls) == 2
        param_names = [p.name for p in func.param_decls]
        assert 'argc' in param_names
        assert 'argv' in param_names
        _roundtrip_verify(code)


class TestInnerScopeTypedef:
    def test_typedef_reused_as_variable(self):
        """A typedef name can be reused as a variable name in an inner scope.
        The parser must track scopes to resolve the ambiguity correctly."""
        from pycparser import c_ast
        code = '''
        typedef int mytype;
        void f() {
            int mytype;
            mytype = 5;
        }
        mytype g;
        '''
        ast = _parse(code)
        assert isinstance(ast.ext[0], c_ast.Typedef)
        assert ast.ext[0].name == 'mytype'
        func = ast.ext[1]
        assert isinstance(func, c_ast.FuncDef)
        # After the function, mytype should still be a typedef
        assert isinstance(ast.ext[2], c_ast.Decl)
        assert ast.ext[2].name == 'g'
        _roundtrip_verify(code)


class TestLineDirective:
    def test_line_directive_updates_coords(self):
        """#line directives update the file and line in subsequent AST coords."""
        from pycparser import c_ast
        code = '''
        int a;
        #line 100 "header.h"
        int b;
        #line 200 "other.h"
        int c;
        '''
        ast = _parse(code, filename='main.c')
        # First decl: main.c, line 2
        assert ast.ext[0].coord.file == 'main.c'
        assert ast.ext[0].coord.line == 2
        # After #line 100 "header.h"
        assert ast.ext[1].coord.file == 'header.h'
        assert ast.ext[1].coord.line == 100
        # After #line 200 "other.h"
        assert ast.ext[2].coord.file == 'other.h'
        assert ast.ext[2].coord.line == 200


class TestDeepASTComparison:
    def test_deep_ast_comparison_roundtrip(self):
        """Parse → generate → re-parse → deep-compare ASTs using attr_names
        and children(). More rigorous than just checking re-parseability.
        Combines typedef scope, bitfields, function pointers, and an
        _Atomic(int) struct member so a single deep comparison catches the
        full generate/re-parse fidelity contract for all of them."""
        from pycparser import c_ast
        from pycparser.c_generator import CGenerator

        def compare_asts(ast1, ast2):
            if type(ast1) is not type(ast2):
                return False
            if isinstance(ast1, (list, tuple)):
                if len(ast1) != len(ast2):
                    return False
                return all(compare_asts(a, b) for a, b in zip(ast1, ast2))
            if isinstance(ast1, c_ast.Node):
                for attr in ast1.attr_names:
                    if not compare_asts(getattr(ast1, attr), getattr(ast2, attr)):
                        return False
                c1, c2 = ast1.children(), ast2.children()
                if len(c1) != len(c2):
                    return False
                return all(compare_asts(a, b) for a, b in zip(c1, c2))
            return ast1 == ast2

        code = '''
        typedef int (*compare_fn)(const void *, const void *);

        struct config {
            unsigned long flags : 8;
            unsigned long mode : 4;
            _Atomic(int) ref_count;
            const char *name;
            compare_fn cmp;
        };

        static inline struct config *config_create(const char *name,
                                                    compare_fn cmp) {
            struct config *c = (struct config *)malloc(sizeof(struct config));
            c->name = name;
            c->cmp = cmp;
            c->flags = 0;
            c->mode = 1;
            c->ref_count = 1;
            return c;
        }

        void config_apply(struct config *c, const void *a, const void *b) {
            if (c->cmp != (compare_fn)0) {
                int result = c->cmp(a, b);
                if (result > 0)
                    c->flags |= 1;
            }
        }
        '''
        ast1 = _parse(code)
        generated = CGenerator().visit(ast1)
        ast2 = _parse(generated)
        assert compare_asts(ast1, ast2), \
            f"ASTs differ after roundtrip:\nOriginal:\n{code}\nGenerated:\n{generated}"
        # The _Atomic specifier on the struct member must survive into generated C
        # (a dropped specifier would be invisible to the structural deep-compare alone).
        assert '_Atomic' in generated
        # It must also land on the member's declared type, not only on the member Decl:
        # a qualifier recorded in one place only would still deep-compare equal after the
        # roundtrip, so the placement needs its own check.
        ref_count = next(d for d in ast2.ext[1].type.decls if d.name == 'ref_count')
        assert '_Atomic' in ref_count.type.quals


class TestAnonymousStructUnion:
    def test_anonymous_struct_member(self):
        """Parse struct with anonymous struct/union member (C11)."""
        from pycparser import c_ast
        code = '''
        struct container {
            struct { int x; int y; };
            int z;
        };
        '''
        ast = _parse(code)
        struct = ast.ext[0].type
        assert isinstance(struct, c_ast.Struct)
        assert struct.name == 'container'
        # The anonymous struct member is a nameless Decl whose type is the inner Struct;
        # its fields and the following named member must both be present.
        anon = struct.decls[0]
        assert isinstance(anon, c_ast.Decl) and anon.name is None
        assert isinstance(anon.type, c_ast.Struct)
        assert {d.name for d in anon.type.decls} == {'x', 'y'}
        assert struct.decls[1].name == 'z'
        _roundtrip_verify(code)


class TestAdvancedGrammarCombinations:
    def test_vla_noreturn_array_qualifiers(self):
        """Combine VLA, _Noreturn, and array parameter qualifiers in one program.
        Parse → verify AST → roundtrip."""
        from pycparser import c_ast
        code = '''
        _Noreturn void die(const char *msg);

        int sum(int n, const int arr[const n]) {
            int total = 0;
            for (int i = 0; i < n; i++) {
                total += arr[i];
            }
            return total;
        }

        void make_matrix(int rows, int cols) {
            int matrix[rows][cols];
            for (int i = 0; i < rows; i++)
                for (int j = 0; j < cols; j++)
                    matrix[i][j] = i * cols + j;
        }
        '''
        ast = _parse(code)
        # _Noreturn should be in funcspec
        assert '_Noreturn' in ast.ext[0].funcspec
        # sum has 2 params, second is array with qualifiers
        sum_func = ast.ext[1]
        assert isinstance(sum_func, c_ast.FuncDef)
        assert sum_func.decl.name == 'sum'
        # make_matrix uses VLA (matrix[rows][cols])
        make_func = ast.ext[2]
        assert isinstance(make_func, c_ast.FuncDef)
        _roundtrip_verify(code)

    def test_comma_operator_in_statements(self):
        """Comma operator used as statement (not just in expressions) combined
        with typedef-as-parameter ambiguity and empty struct."""
        from pycparser import c_ast
        code = '''
        struct empty {};

        typedef int T;

        void swap(T *a, T *b) {
            T tmp;
            if (a != b)
                tmp = *a, *a = *b, *b = tmp;
        }

        void multi_update(int *x, int *y) {
            *x += 1, *y -= 1;
            (*x)++, (*y)--;
        }
        '''
        ast = _parse(code)
        # Empty struct
        empty = ast.ext[0].type
        assert isinstance(empty, c_ast.Struct)
        assert empty.name == 'empty'
        # Typedef
        assert isinstance(ast.ext[1], c_ast.Typedef)
        # swap uses comma operator as statement
        swap = ast.ext[2]
        assert isinstance(swap, c_ast.FuncDef)
        assert swap.decl.name == 'swap'
        _roundtrip_verify(code)

    def test_dollar_identifier_and_deeply_nested_sizeof(self):
        """Two distinct grammar features in one program: '$' is a legal identifier
        character (a pycparser extension), and sizeof(...) nests to arbitrary depth.
        (The _Atomic specifier/qualifier forms are covered by
        test_atomic_specifier_and_qualifier_forms, so they are not re-tested here.)"""
        from pycparser import c_ast
        # '$' inside identifiers must survive parse + name extraction + roundtrip.
        ast_d = _parse('int a$b; int $x;')
        assert ast_d.ext[0].name == 'a$b'
        assert ast_d.ext[1].name == '$x'
        gen_d, ast_d2 = _roundtrip_verify('int a$b; int $x;')
        assert 'a$b' in gen_d and '$x' in gen_d
        assert [d.name for d in ast_d2.ext] == ['a$b', '$x']

        # sizeof recursion: 20 nested sizeof(...) must parse to depth 20 and roundtrip.
        inner = 'int'
        for _ in range(20):
            inner = f'sizeof({inner})'
        code = f'void f() {{ int x = {inner}; }}'
        ast = _parse(code)
        node = ast.ext[0].body.block_items[0].init
        depth = 0
        while isinstance(node, c_ast.UnaryOp) and node.op == 'sizeof':
            depth += 1
            node = node.expr
        assert depth == 20
        _roundtrip_verify(code)


class TestTypedefParamAmbiguity:
    def test_typedef_name_as_parameter(self):
        """Typedef name reused as parameter name — parser must resolve 'size'
        as type in return/parameter type position, then as variable name in
        parameter name position. Verify AST and roundtrip."""
        from pycparser import c_ast
        code = '''
        typedef int size;
        size get_size(size size) {
            return size + 1;
        }
        size x;
        '''
        ast = _parse(code)
        # Typedef
        assert isinstance(ast.ext[0], c_ast.Typedef)
        assert ast.ext[0].name == 'size'
        # Function: return type uses typedef, param also named 'size'
        func = ast.ext[1]
        assert isinstance(func, c_ast.FuncDef)
        assert func.decl.name == 'get_size'
        params = func.decl.type.args.params
        assert len(params) == 1
        assert params[0].name == 'size'
        # After function scope, 'size' is still a typedef
        assert isinstance(ast.ext[2], c_ast.Decl)
        assert ast.ext[2].name == 'x'
        _roundtrip_verify(code)


class TestForwardVsFullStruct:
    def test_forward_empty_and_full_struct(self):
        """Forward declaration (decls=None), empty body (decls=[]),
        and full definition (decls=[...]) are distinct. Verify each
        and roundtrip."""
        from pycparser import c_ast
        code = '''
        struct forward;
        struct empty {};
        struct full { int x; int y; };
        void f(struct forward *fwd, struct full val) {
            val.x = 1;
        }
        '''
        ast = _parse(code)
        # Forward: decls is None
        fwd_struct = ast.ext[0].type
        assert isinstance(fwd_struct, c_ast.Struct)
        assert fwd_struct.name == 'forward'
        assert fwd_struct.decls is None
        # Empty: decls is empty list
        empty_struct = ast.ext[1].type
        assert isinstance(empty_struct, c_ast.Struct)
        assert empty_struct.name == 'empty'
        assert empty_struct.decls is not None
        assert len(empty_struct.decls) == 0
        # Full: decls has 2 fields
        full_struct = ast.ext[2].type
        assert isinstance(full_struct, c_ast.Struct)
        assert full_struct.name == 'full'
        assert len(full_struct.decls) == 2
        # Function uses both
        func = ast.ext[3]
        assert isinstance(func, c_ast.FuncDef)
        _roundtrip_verify(code)


class TestArrayDeclQualifiers:
    def test_array_param_with_qualifiers(self):
        """Array parameter with const and static qualifiers in function
        declaration. This is valid C99 — the array size and qualifiers
        appear inside the brackets. Verify parsing and roundtrip."""
        from pycparser import c_ast
        code = '''
        void process(int n, const int data[const n]) {
            int total = 0;
            for (int i = 0; i < n; i++)
                total += data[i];
        }
        int lookup(const int table[static 256], int key) {
            return table[key];
        }
        '''
        ast = _parse(code)
        # process: 2 params, second is array with VLA dim
        proc = ast.ext[0]
        assert isinstance(proc, c_ast.FuncDef)
        assert proc.decl.name == 'process'
        params = proc.decl.type.args.params
        assert len(params) == 2
        assert isinstance(params[1].type, c_ast.ArrayDecl)
        # lookup: array param with 'static' qualifier
        lookup = ast.ext[1]
        assert isinstance(lookup, c_ast.FuncDef)
        assert lookup.decl.name == 'lookup'
        lookup_params = lookup.decl.type.args.params
        assert isinstance(lookup_params[0].type, c_ast.ArrayDecl)
        _roundtrip_verify(code)


class TestAtomicSpecifierVsQualifier:
    def test_atomic_specifier_and_qualifier_forms(self):
        """_Atomic as specifier (_Atomic(int)) vs qualifier (int _Atomic)
        produce different AST structures. Both must parse, generate valid C,
        and roundtrip correctly."""
        from pycparser import c_ast
        from pycparser.c_generator import CGenerator
        code = '''
        _Atomic(int) counter;
        int _Atomic flag;
        _Atomic(int *) atomic_intptr;
        const _Atomic(int) readonly_counter;
        int * _Atomic atomic_ptr;
        '''
        ast = _parse(code)
        assert ast.ext[0].name == 'counter'
        assert ast.ext[1].name == 'flag'
        assert ast.ext[2].name == 'atomic_intptr'
        assert ast.ext[3].name == 'readonly_counter'
        assert ast.ext[4].name == 'atomic_ptr'
        # The _Atomic-ness itself must be captured, not silently dropped: the qualifier
        # form (int _Atomic flag) carries '_Atomic' in the declared type's quals.
        assert '_Atomic' in ast.ext[1].type.quals
        # const _Atomic(int) combines an ordinary qualifier with _Atomic.
        assert 'const' in ast.ext[3].quals and '_Atomic' in ast.ext[3].quals
        # A qualifier written AFTER the '*' qualifies the pointer itself, so it lands on the
        # PtrDecl (not on the pointed-to type, where a leading qualifier would go).
        assert isinstance(ast.ext[4].type, c_ast.PtrDecl)
        assert '_Atomic' in ast.ext[4].type.quals
        # Generate and verify re-parseable
        gen = CGenerator()
        generated = gen.visit(ast)
        ast2 = _parse(generated)
        assert len(ast2.ext) == 5
        # All 5 declarations should survive roundtrip with correct names
        names = [d.name for d in ast2.ext]
        assert names == ['counter', 'flag', 'atomic_intptr', 'readonly_counter', 'atomic_ptr']
        # _Atomic must appear in the regenerated C (a dropped specifier/qualifier is caught here)
        # and survive the roundtrip on the qualifier-form declaration.
        assert '_Atomic' in generated
        assert '_Atomic' in ast2.ext[1].type.quals


class TestNestedFuncDeclaration:
    def test_function_declaration_inside_function(self):
        """Declare a function inside another function's body, then call it.
        The inner declaration is a Decl with FuncDecl, not a FuncDef."""
        from pycparser import c_ast
        code = '''
        void outer() {
            int inner(int x);
            int result = inner(42);
        }
        '''
        ast = _parse(code)
        func = ast.ext[0]
        assert isinstance(func, c_ast.FuncDef)
        assert func.decl.name == 'outer'
        items = func.body.block_items
        # First item: nested function declaration
        inner_decl = items[0]
        assert isinstance(inner_decl, c_ast.Decl)
        assert inner_decl.name == 'inner'
        assert isinstance(inner_decl.type, c_ast.FuncDecl)
        # Second item: call to inner
        result_decl = items[1]
        assert isinstance(result_decl.init, c_ast.FuncCall)
        _roundtrip_verify(code)


class TestComplexAndLargeScale:
    def test_complex_cases_and_large_program(self):
        """Initializer lists, designated initializers, variadic functions,
        static_assert, complex cast expressions, and a realistic multi-function
        program — all with roundtrip verification."""
        from pycparser import c_ast
        from pycparser.c_ast import NodeVisitor

        # Initializer list
        ast = _parse('int arr[] = {1, 2, 3, 4, 5};')
        assert isinstance(ast.ext[0].init, c_ast.InitList) and len(ast.ext[0].init.exprs) == 5
        _roundtrip_verify('int arr[] = {1, 2, 3, 4, 5};')

        # Designated initializer
        ast2 = _parse('struct point p = { .x = 10, .y = 20 };')
        for expr in ast2.ext[0].init.exprs:
            assert isinstance(expr, c_ast.NamedInitializer)
        _roundtrip_verify('struct point p = { .x = 10, .y = 20 };')

        # Variadic function
        ast3 = _parse('void printf(const char *fmt, ...);')
        assert isinstance(ast3.ext[0].type.args.params[-1], c_ast.EllipsisParam)

        # Static assert
        ast4 = _parse('_Static_assert(sizeof(int) == 4, "int must be 4 bytes");')
        assert isinstance(ast4.ext[0], c_ast.StaticAssert)

        # Complex expression roundtrip
        code_cx = 'void f() { x = ((struct node *)ptr)->next; }'
        gen_cx, _ = _roundtrip_verify(code_cx)
        assert 'struct node' in gen_cx and '->' in gen_cx

        # --- Large realistic program ---
        code_large = '''
        typedef struct node {
            int data;
            struct node *next;
        } node_t;

        node_t *create_node(int val) {
            node_t *n = (node_t *)malloc(sizeof(node_t));
            n->data = val;
            n->next = (node_t *)0;
            return n;
        }

        int sum_list(node_t *head) {
            int total = 0;
            while (head != (node_t *)0) {
                total += head->data;
                head = head->next;
            }
            return total;
        }

        int main() {
            node_t *list = create_node(1);
            list->next = create_node(2);
            list->next->next = create_node(3);
            int s = sum_list(list);
            return 0;
        }
        '''
        ast5 = _parse(code_large)
        class FC(NodeVisitor):
            def __init__(self): self.names = []
            def visit_FuncDef(self, node): self.names.append(node.decl.name)
        fc = FC(); fc.visit(ast5)
        assert set(fc.names) == {'create_node', 'sum_list', 'main'}

        generated, ast6 = _roundtrip_verify(code_large)
        fc2 = FC(); fc2.visit(ast6)
        assert set(fc2.names) == set(fc.names)
