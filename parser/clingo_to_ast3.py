#!/usr/bin/env python3
"""
Build a clingo.ast AST from a Clingo source string using Tree-Sitter (0.23.x).

- Loads the clingo Tree-Sitter grammar (either from a Python module exposing
  `language()` or a compiled shared library exporting `tree_sitter_clingo()`).
- Parses a string to a CST (Tree-Sitter tree).
- Converts the CST to *real* `clingo.ast` nodes (Rule, Literal, Function, ...).

Tested with:
  - tree_sitter==0.23.6
  - clingo>=5.5
  - tree-sitter-clingo grammar

Covers rules, disjunctions, symbolic atoms, comparisons, booleans,
variables, numbers/strings, unary/binary ops, intervals, function/external
function calls, default negation, and conditional literals.

(Theory/aggregates can be added in the same style; left out to stay concise.)
"""
from __future__ import annotations

from typing import List, Optional
import argparse
import ctypes
import importlib
from pathlib import Path

from tree_sitter import Language, Parser
from clingo.symbol import Number, String as SymString, Function as SymFunction, Infimum, Supremum

from clingo import ast  # clingo.ast

# --------------------------- language loader (TS 0.23.x) ----------------------

def load_ts_language(module: Optional[str], so_path: Optional[Path]) -> Language:
    if module:
        m = importlib.import_module(module)  # e.g., tree_sitter_clingo
        lang_capsule = m.language()
        return lang_capsule if isinstance(lang_capsule, Language) else Language(lang_capsule)
    if so_path:
        lib = ctypes.CDLL(str(so_path))
        if not hasattr(lib, "tree_sitter_clingo"):
            raise RuntimeError(f"{so_path} does not export tree_sitter_clingo")
        lib.tree_sitter_clingo.restype = ctypes.c_void_p
        ptr = lib.tree_sitter_clingo()
        if not ptr:
            raise RuntimeError("tree_sitter_clingo() returned NULL")
        return Language(ptr)
    raise SystemExit("Provide --module tree_sitter_clingo OR --so ./parser.(so|dylib|dll)")

# ---------------------------------- helpers -----------------------------------

FILENAME = "<ts>"

def ts_loc_to_ast_loc(node) -> ast.Location:
    # Tree-Sitter is 0-based; clingo.ast.Position is 1-based
    sr, sc = node.start_point
    er, ec = node.end_point
    b = ast.Position(FILENAME, sr + 1, sc + 1)
    e = ast.Position(FILENAME, er + 1, ec + 1)
    return ast.Location(b, e)

def text(src: bytes, node) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")

def named(node):
    return [c for c in node.children if c.is_named]

def field(node, name: str):
    return node.child_by_field_name(name)

# ----------------------------- operator mappings ------------------------------

_BINOP = {
    "+": ast.BinaryOperator.Plus,
    "-": ast.BinaryOperator.Minus,
    "*": ast.BinaryOperator.Multiplication,
    "/": ast.BinaryOperator.Division,
    "\\": ast.BinaryOperator.Modulo,
    "**": ast.BinaryOperator.Power,
    "&": ast.BinaryOperator.And,
    "^": ast.BinaryOperator.Xor,
    "?": ast.BinaryOperator.Or,   # grammar uses '?' token for bitwise or
}

_CMP = {
    "=": ast.Relation.Equal,
    "!=": ast.Relation.NotEqual,
    "<": ast.Relation.Less,
    "<=": ast.Relation.LessEqual,
    ">": ast.Relation.Greater,
    ">=": ast.Relation.GreaterEqual,
}

def _sign_from(node_opt) -> ast.Sign:
    if node_opt is None:
        return ast.Sign.NoSign
    if node_opt.type == "default_negation":
        return ast.Sign.Negation
    if node_opt.type == "sign":
        cnt = sum(1 for ch in named(node_opt) if ch.type == "default_negation")
        return ast.Sign.DoubleNegation if cnt >= 2 else (ast.Sign.Negation if cnt == 1 else ast.Sign.NoSign)
    return ast.Sign.NoSign

# --------------------------------- terms --------------------------------------

def convert_term(src: bytes, node) -> ast.AST:
    t = node.type

    if t == "number":
        raw = text(src, node)
        if raw.startswith(("0x", "0X")):
            val = int(raw, 16)
        elif raw.startswith(("0o", "0O")):
            val = int(raw, 8)
        elif raw.startswith(("0b", "0B")):
            val = int(raw, 2)
        else:
            val = int(raw)
        return ast.SymbolicTerm(ts_loc_to_ast_loc(node), Number(val))

    if t == "string":
        s = text(src, node)
        if len(s) >= 2 and s[0] == s[-1] == '"':
            s = s[1:-1]
        return ast.SymbolicTerm(ts_loc_to_ast_loc(node), SymString(s))

    if t in ("infimum", "supremum"):
        sym = Infimum if t == "infimum" else Supremum
        return ast.SymbolicTerm(ts_loc_to_ast_loc(node), sym)

    if t in ("anonymous", "variable"):
        name = "_" if t == "anonymous" else text(src, node)
        return ast.Variable(ts_loc_to_ast_loc(node), name)

    if t in ("identifier", "negative_identifier"):
        return ast.Function(ts_loc_to_ast_loc(node), text(src, node), [], False)

    if t == "function":
        nm = field(node, "name")
        pool = field(node, "arguments")  # "pool" node
        args = convert_pool(src, pool) if pool is not None else []
        return ast.Function(ts_loc_to_ast_loc(node), text(src, nm), args, False)

    if t == "external_function":
        nm = field(node, "name")
        pool = field(node, "arguments")
        args = convert_pool(src, pool) if pool is not None else []
        return ast.Function(ts_loc_to_ast_loc(node), text(src, nm), args, True)

    if t == "unary":
        op = field(node, "op")
        rhs = field(node, "rhs")
        op_txt = text(src, op)
        if op_txt == "-":
            op_ty = ast.UnaryOperator.Minus
        elif op_txt == "~":
            op_ty = ast.UnaryOperator.Negation
        else:
            op_ty = ast.UnaryOperator.Minus
        return ast.UnaryOperation(ts_loc_to_ast_loc(node), op_ty, convert_term(src, rhs))

    if t == "abs":
        inner = next((convert_term(src, ch) for ch in named(node) if ch.type == "term"), None)
        inner = inner or convert_term(src, named(node)[0])
        return ast.UnaryOperation(ts_loc_to_ast_loc(node), ast.UnaryOperator.Absolute, inner)

    if t == "binary":
        lhs = convert_term(src, field(node, "lhs"))
        rhs = convert_term(src, field(node, "rhs"))
        op_txt = text(src, field(node, "op"))
        if op_txt == "..":
            return ast.Interval(ts_loc_to_ast_loc(node), lhs, rhs)
        op_ty = _BINOP.get(op_txt)
        if op_ty is None:
            raise ValueError(f"Unknown binary operator: {op_txt!r}")
        return ast.BinaryOperation(ts_loc_to_ast_loc(node), op_ty, lhs, rhs)

    if t == "pool":
        groups = _collect_pool_groups(src, node)
        terms = [tm for grp in groups for tm in grp]
        return ast.Pool(ts_loc_to_ast_loc(node), terms)

    # wrapper/alias nodes: descend
    for ch in named(node):
        if ch.type in {
            "number","string","infimum","supremum","anonymous","variable",
            "identifier","negative_identifier","function","external_function",
            "unary","abs","binary","pool"
        }:
            return convert_term(src, ch)

    raise ValueError(f"Unhandled term node: {t}")

def _collect_pool_groups(src: bytes, pool_node) -> List[List[ast.AST]]:
    groups: List[List[ast.AST]] = []
    for ch in named(pool_node):
        if ch.type in ("terms", "terms_par", "terms_sem", "terms_trail_par", "terms_trail"):
            cur = [convert_term(src, tch) for tch in named(ch) if tch.type == "term"]
            if cur: groups.append(cur)
        elif ch.type == "pool_binary":
            tms = [convert_term(src, tch) for tch in named(ch) if tch.type == "term"]
            for i in range(0, len(tms), 2):
                groups.append(tms[i:i+2])
    return groups

def convert_pool(src: bytes, pool_node) -> List[ast.AST]:
    if pool_node is None:
        return []
    groups = _collect_pool_groups(src, pool_node)
    if not groups:
        return []
    if len(groups) == 1:
        return groups[0]
    out: List[ast.AST] = []
    for grp in groups:
        loc = ast.Location(grp[0].location.begin, grp[-1].location.end) if grp else ts_loc_to_ast_loc(pool_node)  # type: ignore[attr-defined]
        out.append(ast.Pool(loc, grp))
    return out

# ------------------------------ atoms / literals ------------------------------

def convert_symbolic_atom(src: bytes, node) -> ast.AST:
    nm_node = field(node, "name")
    pool = field(node, "pool")
    args = convert_pool(src, pool) if pool is not None else []
    fun = ast.Function(ts_loc_to_ast_loc(node), text(src, nm_node), args, False)
    return ast.SymbolicAtom(fun)

def convert_comparison(src: bytes, node) -> ast.AST:
    kids = [ch for ch in named(node)]
    base = convert_term(src, kids[0])
    guards: List[ast.AST] = []
    i = 1
    while i + 1 < len(kids):
        rel = text(src, kids[i])
        rhs = convert_term(src, kids[i+1])
        op = _CMP.get(rel)
        if op is None:
            raise ValueError(f"Unknown comparison op: {rel!r}")
        guards.append(ast.Guard(op, rhs))
        i += 2
    return ast.Comparison(base, guards)

def convert_boolean(src: bytes, node) -> ast.AST:
    return ast.BooleanConstant(1 if text(src, node) == "#true" else 0)

def convert_simple_atom(src: bytes, node) -> ast.AST:
    t = node.type
    if t == "symbolic_atom":
        return convert_symbolic_atom(src, node)
    if t == "comparison":
        return convert_comparison(src, node)
    if t == "boolean_constant":
        return convert_boolean(src, node)
    for ch in named(node):
        if ch.type in ("symbolic_atom", "comparison", "boolean_constant"):
            return convert_simple_atom(src, ch)
    raise ValueError(f"Unhandled simple atom: {t}")

def convert_literal(src: bytes, node) -> ast.AST:
    kids = named(node)
    si = kids[0] if kids and kids[0].type in ("sign","default_negation") else None
    atom_node = kids[1] if si is not None else (kids[0] if kids else None)
    if atom_node is None:
        raise ValueError("literal without atom")
    sign = _sign_from(si)
    atom = convert_simple_atom(src, atom_node)
    return ast.Literal(ts_loc_to_ast_loc(node), sign, atom)

def convert_conditional_literal(src: bytes, node) -> ast.AST:
    kids = named(node)
    base_lit = convert_literal(src, next(ch for ch in kids if ch.type == "literal"))
    cond: List[ast.AST] = []
    for ch in kids[1:]:
        if ch.type == "literal":
            cond.append(convert_literal(src, ch))
        elif ch.type == "literal_tuple":
            for g in named(ch):
                if g.type == "literal":
                    cond.append(convert_literal(src, g))
    return ast.ConditionalLiteral(ts_loc_to_ast_loc(node), base_lit, cond)

# ------------------------------ head / body / stmts ---------------------------

def convert_head(src: bytes, node) -> ast.AST:
    for ch in named(node):
        if ch.type == "literal":
            return convert_literal(src, ch)
        if ch.type == "disjunction":
            return convert_disjunction(src, ch)
    if node.type == "disjunction":
        return convert_disjunction(src, node)
    if node.type == "literal":
        return convert_literal(src, node)
    return ast.Disjunction(ts_loc_to_ast_loc(node), [])

def convert_disjunction(src: bytes, node) -> ast.AST:
    elems: List[ast.AST] = []
    for ch in named(node):
        if ch.type in ("conditional_literal", "conditional_literal_n", "conditional_literal_0"):
            elems.append(convert_conditional_literal(src, ch))
        elif ch.type == "literal":
            elems.append(ast.ConditionalLiteral(ts_loc_to_ast_loc(ch), convert_literal(src, ch), []))
    return ast.Disjunction(ts_loc_to_ast_loc(node), elems)

def convert_body_literal(src: bytes, node) -> Optional[ast.AST]:
    for ch in named(node):
        if ch.type == "literal":
            return convert_literal(src, ch)
        if ch.type == "conditional_literal":
            return convert_conditional_literal(src, ch)
    return None  # aggregates/theory atoms omitted here

def convert_body(src: bytes, node) -> List[ast.AST]:
    items: List[ast.AST] = []
    for ch in named(node):
        if ch.type in ("body_literal", "_body_literal"):
            lit = convert_body_literal(src, ch)
            if lit is not None:
                items.append(lit)
        elif ch.type in ("literal", "conditional_literal"):
            items.append(convert_literal(src, ch) if ch.type == "literal" else convert_conditional_literal(src, ch))
    return items

def convert_statement(src: bytes, node) -> Optional[ast.AST]:
    t = node.type
    if t == "rule":
        hd = None
        bd: List[ast.AST] = []
        for ch in named(node):
            if ch.type == "head":
                hd = convert_head(src, ch)
            elif ch.type == "body":
                bd = convert_body(src, ch)
        if hd is None:
            hd = ast.Disjunction(ts_loc_to_ast_loc(node), [])
        return ast.Rule(ts_loc_to_ast_loc(node), hd, bd)
    if t == "integrity_constraint":
        bd = []
        for ch in named(node):
            if ch.type == "body":
                bd = convert_body(src, ch)
        hd = ast.Disjunction(ts_loc_to_ast_loc(node), [])
        return ast.Rule(ts_loc_to_ast_loc(node), hd, bd)
    return None  # other statements not implemented for brevity

# ---------------------------------- driver ------------------------------------

def parse_to_clingo_ast(src: bytes, lang: Language) -> List[ast.AST]:
    parser = Parser(lang)  # TS 0.23.x: pass Language in ctor
    tree = parser.parse(src)
    root = tree.root_node  # source_file
    out: List[ast.AST] = []
    for st in named(root):
        if st.type == "statement":
            for ch in named(st):
                stmt = convert_statement(src, ch)
                if stmt is not None:
                    out.append(stmt)
    return out

def main():
    ap = argparse.ArgumentParser(description="Parse Clingo with Tree-Sitter and build clingo.ast nodes.")
    srcg = ap.add_mutually_exclusive_group(required=True)
    srcg.add_argument("--text", type=str, help="Inline program text.")
    srcg.add_argument("--file", type=Path, help="Path to .lp file.")
    ap.add_argument("--module", type=str, default=None, help="Python module exposing language() (e.g., tree_sitter_clingo).")
    ap.add_argument("--so", type=Path, default=None, help="Path to compiled parser shared lib exporting tree_sitter_clingo().")
    args = ap.parse_args()

    lang = load_ts_language(args.module, args.so)
    src_bytes = args.text.encode() if args.text is not None else args.file.read_bytes()

    ast_list = parse_to_clingo_ast(src_bytes, lang)

    # Pretty-print: clingo.ast nodes stringify to their gringo representation
    for i, stm in enumerate(ast_list, 1):
        print(f"% ---- statement {i} ----")
        print(str(stm))

if __name__ == "__main__":
    main()
