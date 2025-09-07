import unittest
from clingo.core import Library
from clingo.ast import parse_string
from clingo_to_ast import load_ts_language, parse_to_clingo_ast

class TestParser(unittest.TestCase):

    def assertParserOutput(self, program: str):
        lang = load_ts_language("tree_sitter_clingo", None)
        lib = Library()
        ast = parse_to_clingo_ast(lib, bytes(program, encoding="utf-8"), lang)
        expected_ast = []
        parse_string(lib, program, expected_ast.append)
        expected_ast = expected_ast[1:]
        # self.assertEqual(list(map(str, ast)), list(map(str, expected_ast)))
        for node1, node2 in zip(ast, expected_ast):
            self.assertEqual(str(node1), str(node2))
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

    # def test_empty_program(self):
    #     program = ""
    #     self.assertParserOutput(program)
        
if __name__ == "__main__":
    unittest.main()