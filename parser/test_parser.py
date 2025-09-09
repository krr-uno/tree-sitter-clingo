import unittest
from clingo.core import Library
from clingo.ast import parse_string
from clingo_to_ast import load_ts_language, parse_to_clingo_ast



class TestParser(unittest.TestCase):

    def assertEqualAST(self, ast1, ast2):
        self.assertIsInstance(ast1, AST)
        self.assertEqual(str(ast1), str(ast2))
        self.assertEqual(type(ast1), type(ast2))
        self.assertEqual(str(ast1), str(ast2))
        if ast1 != ast2:
            print(f"Node mismatch:\n  {ast1}\n  {ast2}")
            pprint(ast1)
            pprint(ast2)
        self.assertEqual(ast1, ast2)

    def assertParserOutput(self, program: str, expected_program: str | None = None):
        lang = load_ts_language("tree_sitter_clingo", None)
        lib = Library()
        ast = parse_to_clingo_ast(lib, bytes(program, encoding="utf-8"), lang)
        expected_ast = []
        if expected_program is None:
            expected_program = program
        parse_string(lib, expected_program, expected_ast.append)
        expected_ast = expected_ast[1:]
        # self.assertEqual(list(map(str, ast)), list(map(str, expected_ast)))
        for node1, node2 in zip(ast, expected_ast):
            self.assertEqual(str(node1), str(node2))
            self.assertEqual(type(node1), type(node2))
            if node1 != node2:
                print(f"Node mismatch:\n  {node1}\n  {node2}")
                pprint(node1)
                pprint(node2)
            self.assertEqual(node1, node2)

    def test_simple_fact(self):
        program = """
        p(1).
        """
        self.assertParserOutput(program)

    def test_simple_program(self):
        program = """
        p(1).
        q(X) :- p(X), not r(X).
        """
        self.assertParserOutput(program)

    def test_aggregate(self):
        program = """
        p(1).
        q(X) :- X = #sum{ Y : p(Y) }.
        """
        self.assertParserOutput(program)

    # ===== corpus: body.txt =====

    def test_corpus_body_symbolic_literals(self):
        program = ":- p(X), not p(X), not not p(X), -p(X), not -p(X), not not -p(X)."
        self.assertParserOutput(program)

    # def test_corpus_body_comparisons(self):
    #     program = ":- X < Y < Z, -p(X) < X < Y."
    #     self.assertParserOutput(program)

    # def test_corpus_body_conditional_literals(self):
    #     program = ":- a, not b: p, c; p(X):; not not X < Y < Z: p(X)."
    #     self.assertParserOutput(program)

    # def test_corpus_body_set_aggregates(self):
    #     self.skipTest('set-aggregates not yet implemented')
    #     program = ":- not 1 { a; a: ; a: b; a: b, c } <= 3."
    #     self.assertParserOutput(program)

    # def test_corpus_body_aggregates(self):
    #     program = ":- not 1 #count { :; :a; a; a: ; a: b, c; a, b } <= 3."
    #     self.assertParserOutput(program)

    # # ===== corpus: head.txt =====

    # def test_corpus_head_symbolic_literal(self):
    #     program = "not p."
    #     self.assertParserOutput(program)

    # def test_corpus_head_comparison(self):
    #     program = "X < Y < Z."
    #     self.assertParserOutput(program)

    # def test_corpus_head_boolean(self):
    #     program = "#true; #false."
    #     self.assertParserOutput(program)

    # def test_corpus_head_disjunction(self):
    #     program = "p; p: q, c; d: ; |X| < 10."
    #     self.assertParserOutput(program)

    # def test_corpus_head_set_aggregate(self):
    #     self.skipTest('head set-aggregate not yet implemented')
    #     program = "1 <= { a; a: b, c } <= 2."
    #     self.assertParserOutput(program)

    # def test_corpus_head_aggregate(self):
    #     self.skipTest('head aggregate not yet implemented')
    #     program = "1 <= #count { :a; 1:a:b,c; 1:a: } <= 2."
    #     self.assertParserOutput(program)

    # def test_corpus_head_theory(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p."
    #     self.assertParserOutput(program)

    # # ===== corpus: terms.txt =====

    # def test_corpus_terms_numbers(self):
    #     program = "p(0,9,0xf,0b1,0o7)."
    #     self.assertParserOutput(program)

    # def test_corpus_terms_constants(self):
    #     program = 'p("abc", #inf, #sup).'
    #     self.assertParserOutput(program)

    # def test_corpus_terms_variables(self):
    #     program = "p(X,_,__'Xa')."
    #     self.assertParserOutput(program)

    # def test_corpus_terms_unary(self):
    #     program = "p(-1,~1,|1;2|)."
    #     self.assertParserOutput(program)

    # def test_corpus_terms_binary(self):
    #     program = "p(1-2,1*2,1**2,1/2,1\\2)."
    #     self.assertParserOutput(program)

    # def test_corpus_terms_precedence(self):
    #     program = "p(1+2*3-4)."
    #     self.assertParserOutput(program, 'p((1+2)*(3-4)).')

    # def test_corpus_terms_function1(self):
    #     program = "p(f())."
    #     self.assertParserOutput(program, 'p(f).')

    # def test_corpus_terms_function2(self):
    #     program = "p(g)."
    #     self.assertParserOutput(program)

    # def test_corpus_terms_function(self):
    #     program = "p(f(),g,h(;1;1,2),@g)."
    #     self.assertParserOutput(program, 'p(f,g,h(1;1,2),@g()).')

    # def test_corpus_terms_tuple(self):
    #     self.skipTest('tuple terms not yet implemented')
    #     program = "p((),(;a;a,;;a,b;a,b,))."
    #     self.assertParserOutput(program)

    # # ===== corpus: statements.txt =====

    # def test_corpus_statements_comments(self):
    #     program = "% foo\n%* \n * bar\n *%\n"
    #     self.assertParserOutput(program)

    # def test_corpus_statements_rules(self):
    #     program = "head.\nhead :-  body."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_constraints(self):
    #     program = ":- body.\n:- ."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_weak_constraint(self):
    #     self.skipTest('weak constraints not yet implemented')
    #     program = ":~ a, b. [1@2,1,2,3]\n:~ . [0]"
    #     self.assertParserOutput(program)

    # def test_corpus_statements_minimize(self):
    #     self.skipTest('minimize not yet implemented')
    #     program = "#minimize{ 1@3: a; 1: b; 2,3: b,c  }."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_maximize(self):
    #     self.skipTest('maximize not yet implemented')
    #     program = "#maximize{ }."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_show(self):
    #     self.skipTest('show directives not yet implemented')
    #     program = "#show.\n#show a/2.\n#show -a/2.\n#show a/2+1.\n#show -p(X) : q(), c(X).\n#show a."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_defined(self):
    #     self.skipTest('defined directives not yet implemented')
    #     program = "#defined a/2.\n#defined -a/2."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_project(self):
    #     self.skipTest('project directives not yet implemented')
    #     program = "#project a/2.\n#project -a/2.\n#project a.\n#project a : .\n#project a : b."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_const(self):
    #     self.skipTest('const directives not yet implemented')
    #     program = "#const x = 1.\n#const x = f((), |x|).\n#const x = 1. [default]\n#const x = 2. [override]"
    #     self.assertParserOutput(program)

    # def test_corpus_statements_script(self):
    #     self.skipTest('script blocks not yet implemented')
    #     program = "#script (python)\n\n\ndef main(ctl):\n  ctl.ground()\n\n#end."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_include(self):
    #     self.skipTest('include directives not yet implemented')
    #     program = "#include \"a\".\n#include <b>."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_program(self):
    #     self.skipTest('program directives not yet implemented')
    #     program = "#program base.\n#program base().\n#program acid(a, b)."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_external(self):
    #     self.skipTest('external directives not yet implemented')
    #     program = "#external a.\n#external -a.\n#external a : b.\n#external a(X) : p(B). [X]"
    #     self.assertParserOutput(program)

    # def test_corpus_statements_edge(self):
    #     self.skipTest('edge directives not yet implemented')
    #     program = "#edge (a,b).\n#edge (a,b; b, c).\n#edge (a,b; b, c) : q."
    #     self.assertParserOutput(program)

    # def test_corpus_statements_heuristic(self):
    #     self.skipTest('heuristic directives not yet implemented')
    #     program = "#heuristic a(). [true,blub]\n#heuristic a(). [true@10,blub]\n#heuristic a(X) : q(X). [true@X,blub]"
    #     self.assertParserOutput(program)

    # # ===== corpus: theory.txt =====

    # def test_corpus_theory_guard(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p <= 5."
    #     self.assertParserOutput(program)

    # def test_corpus_theory_elements(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p { : ; 1; 1,2; 1:a,b; 1,2:a }."
    #     self.assertParserOutput(program)

    # def test_corpus_theory_tuple(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p { (); (,); (1); (1,); (1,2); (1,2,) }."
    #     self.assertParserOutput(program)

    # def test_corpus_theory_list(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p { []; [1]; [1,2] }."
    #     self.assertParserOutput(program)

    # def test_corpus_theory_set(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p { {}; {1}; {1,2} }."
    #     self.assertParserOutput(program)

    # def test_corpus_theory_function(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p { f, f(), f(1), f(1,2) }."
    #     self.assertParserOutput(program)

    # def test_corpus_theory_terms(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p { 1, #sup, #inf, \"str\", X, _ }."
    #     self.assertParserOutput(program)

    # def test_corpus_theory_unparsed(self):
    #     self.skipTest('theory atoms not yet implemented')
    #     program = "&p { - 1, -1 * f(2), - + 1 * 2 ** 3 }."
    #     self.assertParserOutput(program)

if __name__ == "__main__":
    unittest.main()