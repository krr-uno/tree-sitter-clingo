import tree_sitter_clingo as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())

parser = Parser(PY_LANGUAGE)

source = bytes("""\
p(1).
q(X) :- p(X), not r(X).
""", "utf-8")

tree = parser.parse(source)
    

def print_tree(node, source: bytes, indent: int = 0):
    """
    Recursively print a Tree-sitter node and its children with spans and snippets.

    Parameters
    ----------
    node : tree_sitter.Node
        The current node to print.
    source : bytes
        The original source code as bytes (so we can show snippets).
    indent : int
        Current indentation level (used internally in recursion).
    """
    start, end = node.start_point, node.end_point
    snippet = source[node.start_byte:node.end_byte].decode("utf-8", "replace").strip()
    # Clean up whitespace and truncate long snippets
    snippet = " ".join(snippet.split())
    if len(snippet) > 60:
        snippet = snippet[:57] + "..."

    print("  " * indent + f"{node.type} [{start[0]}:{start[1]}-{end[0]}:{end[1]}] :: {snippet}")
    for child in node.children:
        print_tree(child, source, indent + 1)


print_tree(tree.root_node, source)