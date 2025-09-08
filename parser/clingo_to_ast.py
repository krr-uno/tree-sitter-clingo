#!/usr/bin/env python3
"""
Build a clingo 6 AST from a Clingo source string using Tree-Sitter 0.23.6.

- Loads the clingo Tree-Sitter grammar (either from a Python module exposing
  `language()` or a compiled shared library exporting `tree_sitter_clingo()`).
- Parses a string to a CST (Tree-Sitter tree).
- Converts the CST to real clingo 6 `clingo.ast` nodes, including #sum/#count/#min/#max body aggregates.

Requires:
  pip install tree_sitter==0.23.6 clingo
"""
from __future__ import annotations

from typing import List, Optional
import argparse
import ctypes
import importlib
from pathlib import Path

from tree_sitter import Language, Parser

# clingo 6 core & ast
from clingo.core import Location, Position, Library
from clingo import ast
from clingo.symbol import Number, String as SymString, Infimum, Supremum

# --------------------------- language loader (TS 0.23.6) ----------------------

def load_ts_language(module: Optional[str], so_path: Optional[Path]) -> Language:
    if module:
        m = importlib.import_module(module)  # e.g., tree_sitter_clingo
        cap = m.language()
        return cap if isinstance(cap, Language) else Language(cap)
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

def ts_loc(lib: Library, node) -> Location:
    # Tree-Sitter is 0-based; clingo positions are 1-based
    sr, sc = node.start_point
    er, ec = node.end_point
    return Location(
        Position(lib, FILENAME, sr + 1, sc + 1),
        Position(lib, FILENAME, er + 1, ec + 1),
    )

def text(src: bytes, node) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")

def named(node):
    return [c for c in node.children if c.is_named]

def field(node, name: str):
    return node.child_by_field_name(name)

# ----------------------------- operator mappings ------------------------------

BINOP = {
    "+":  ast.BinaryOperator.Plus,
    "-":  ast.BinaryOperator.Minus,
    "*":  ast.BinaryOperator.Multiplication,
    "/":  ast.BinaryOperator.Division,
    "\\": ast.BinaryOperator.Modulo,
    "**": ast.BinaryOperator.Power,
    "&":  ast.BinaryOperator.And,
    "^":  ast.BinaryOperator.Xor,
    "|":  ast.BinaryOperator.Or,
    "?":  ast.BinaryOperator.Or,  # some grammars tokenise bitwise OR as '?'
}

REL = {
    "=":  ast.Relation.Equal,
    "!=": ast.Relation.NotEqual,
    "<":  ast.Relation.Less,
    "<=": ast.Relation.LessEqual,
    ">":  ast.Relation.Greater,
    ">=": ast.Relation.GreaterEqual,
}

AGGFN = {
    "#sum":  ast.AggregateFunction.Sum,
    "#sum+": ast.AggregateFunction.Sump,
    "#min":  ast.AggregateFunction.Min,
    "#max":  ast.AggregateFunction.Max,
    "#count": ast.AggregateFunction.Count,
}

def sign_from(node_opt) -> ast.Sign:
    if node_opt is None:
        return ast.Sign.NoSign
    if node_opt.type == "default_negation":
        return ast.Sign.Single
    if node_opt.type == "sign":
        n = sum(1 for ch in named(node_opt) if ch.type == "default_negation")
        return ast.Sign.Double if n >= 2 else (ast.Sign.Single if n == 1 else ast.Sign.NoSign)
    return ast.Sign.NoSign

# ------------------------------ term conversion -------------------------------

def convert_term(lib: Library, src: bytes, node) -> ast.Term:
    t = node.type
    loc = ts_loc(lib, node)

    if t == "number":
        raw = text(src, node)
        if   raw.startswith(("0x","0X")): val = int(raw, 16)
        elif raw.startswith(("0o","0O")): val = int(raw, 8)
        elif raw.startswith(("0b","0B")): val = int(raw, 2)
        else:                              val = int(raw)
        return ast.TermSymbolic(lib, location=loc, symbol=Number(lib, val))

    if t == "string":
        s = text(src, node)
        if len(s) >= 2 and s[0] == s[-1] == '"':
            s = s[1:-1]
        return ast.TermSymbolic(lib, location=loc, symbol=SymString(lib, s))

    if t == "infimum":
        return ast.TermSymbolic(lib, location=loc, symbol=Infimum(lib))
    if t == "supremum":
        return ast.TermSymbolic(lib, location=loc, symbol=Supremum(lib))

    if t in ("anonymous", "variable"):
        name = "_" if t == "anonymous" else text(src, node)
        return ast.TermVariable(lib, location=loc, name=name, anonymous=(t == "anonymous"))

    # Bare identifier -> nullary function symbol
    if t in ("identifier", "negative_identifier"):
        return ast.TermFunction(lib, location=loc, name=text(src, node), pool=[], external=False)

    if t == "function":
        nm = field(node, "name")
        pool = field(node, "arguments")
        arg_tuples = convert_arg_pool(lib, src, pool) if pool is not None else []
        return ast.TermFunction(lib, location=loc, name=text(src, nm), pool=arg_tuples, external=False)

    if t == "external_function":
        nm = field(node, "name")
        pool = field(node, "arguments")
        arg_tuples = convert_arg_pool(lib, src, pool) if pool is not None else []
        return ast.TermFunction(lib, location=loc, name=text(src, nm), pool=arg_tuples, external=True)

    if t == "unary":
        op_txt = text(src, field(node, "op"))
        rhs = convert_term(lib, src, field(node, "rhs"))
        uop = ast.UnaryOperator.Minus if op_txt == "-" \
              else ast.UnaryOperator.Negation if op_txt == "~" \
              else ast.UnaryOperator.Minus
        return ast.TermUnaryOperation(lib, location=loc, operator_type=uop, argument=rhs)

    if t == "abs":
        inner = next((convert_term(lib, src, ch) for ch in named(node) if ch.type == "term"), None)
        return ast.TermAbsolute(lib, location=loc, pool=[inner] if inner is not None else [])

    if t == "binary":
        lhs = convert_term(lib, src, field(node, "lhs"))
        rhs = convert_term(lib, src, field(node, "rhs"))
        op_txt = text(src, field(node, "op"))
        if op_txt == "..":
            raise NotImplementedError("interval terms (‘..’) not implemented")
        op_ty = BINOP.get(op_txt)
        if op_ty is None:
            raise ValueError(f"Unknown binary operator: {op_txt!r}")
        return ast.TermBinaryOperation(lib, location=loc, operator_type=op_ty, left=lhs, right=rhs)

    if t == "pool":
        # Generic tuple/pool term like (a,b) or (a;b)
        groups = collect_pool_groups(lib, src, node)  # List[List[ast.Term]]
        if len(groups) <= 1:
            args = groups[0] if groups else []
            return ast.TermTuple(lib, location=loc, pool=args)
        tuples = [ast.ArgumentTuple(lib, arguments=args) for args in groups]
        return ast.TermTuple(lib, location=loc, pool=tuples)

    # wrapper/alias nodes: descend
    for ch in named(node):
        if ch.type in {
            "number","string","infimum","supremum","anonymous","variable",
            "identifier","negative_identifier","function","external_function",
            "unary","abs","binary","pool"
        }:
            return convert_term(lib, src, ch)

    raise ValueError(f"Unhandled term node: {t}")

def collect_pool_groups(lib: Library, src: bytes, pool_node) -> List[List[ast.Term]]:
    groups: List[List[ast.Term]] = []
    for ch in named(pool_node):
        if ch.type in ("terms", "terms_par", "terms_sem", "terms_trail_par", "terms_trail"):
            cur = [convert_term(lib, src, tch) for tch in named(ch) if tch.type == "term"]
            if cur:
                groups.append(cur)
        elif ch.type == "pool_binary":
            tms = [convert_term(lib, src, tch) for tch in named(ch) if tch.type == "term"]
            for i in range(0, len(tms), 2):
                groups.append(tms[i:i+2])
    return groups

def convert_arg_pool(lib: Library, src: bytes, pool_node) -> List[ast.ArgumentTuple]:
    """Function/external-function arguments: return list of ArgumentTuple (no location parameter in clingo 6)."""
    if pool_node is None:
        return []
    groups = collect_pool_groups(lib, src, pool_node)
    out: List[ast.ArgumentTuple] = []
    for args in groups if groups else [[]]:
        out.append(ast.ArgumentTuple(lib, arguments=args))
    return out

# --------------------------- atoms & (simple) literals -------------------------

def term_for_symbolic_atom(lib: Library, src: bytes, node) -> ast.Term:
    nm = field(node, "name")
    pool = field(node, "pool")
    args = convert_arg_pool(lib, src, pool) if pool is not None else []
    return ast.TermFunction(lib, location=ts_loc(lib, node), name=text(src, nm), pool=args, external=False)

def convert_comparison_literal(lib: Library, src: bytes, node, sign: ast.Sign, loc: Location) -> ast.LiteralComparison:
    kids = named(node)
    left = convert_term(lib, src, kids[0])
    rights: List[ast.RightGuard] = []
    i = 1
    while i + 1 < len(kids):
        rel = text(src, kids[i])
        rhs = convert_term(lib, src, kids[i+1])
        op = REL.get(rel)
        if op is None:
            raise ValueError(f"Unknown comparison op: {rel!r}")
        rights.append(ast.RightGuard(lib, relation=op, term=rhs))
        i += 2
    return ast.LiteralComparison(lib, location=loc, sign=sign, left=left, right=rights)

def convert_simple_literal(lib: Library, src: bytes, node, sign: ast.Sign, loc: Location):
    t = node.type
    if t == "symbolic_atom":
        atom = term_for_symbolic_atom(lib, src, node)
        return ast.LiteralSymbolic(lib, location=loc, sign=sign, atom=atom)
    if t == "comparison":
        return convert_comparison_literal(lib, src, node, sign, loc)
    if t == "boolean_constant":
        val = text(src, node) == "#true"
        return ast.LiteralBoolean(lib, location=loc, sign=sign, value=val)
    # wrappers
    for ch in named(node):
        if ch.type in ("symbolic_atom","comparison","boolean_constant"):
            return convert_simple_literal(lib, src, ch, sign, loc)
    raise ValueError(f"Unhandled simple atom: {t}")

def convert_literal(lib: Library, src: bytes, node):
    kids = named(node)
    si_node = kids[0] if kids and kids[0].type in ("sign","default_negation") else None
    atom_node = kids[1] if si_node is not None else (kids[0] if kids else None)
    if atom_node is None:
        raise ValueError("literal without atom")
    sign = sign_from(si_node)
    return convert_simple_literal(lib, src, atom_node, sign, ts_loc(lib, node))

# ------------------------------- aggregates (NEW) ------------------------------

def _parse_lower_guard(lib: Library, src: bytes, lower_node) -> Optional[ast.LeftGuard]:
    # node-types: lower has children: relation, term (both required)
    if lower_node is None:
        return None
    tnode = next((c for c in named(lower_node) if c.type == "term"), None)
    rnode = next((c for c in named(lower_node) if c.type == "relation"), None)
    if tnode is None or rnode is None:
        return None
    rel = REL[text(src, rnode)]
    term = convert_term(lib, src, tnode)
    return ast.LeftGuard(lib, relation=rel, term=term)

def _parse_upper_guard(lib: Library, src: bytes, upper_node) -> Optional[ast.RightGuard]:
    # node-types: upper has children: relation, term (both required)
    if upper_node is None:
        return None
    rnode = next((c for c in named(upper_node) if c.type == "relation"), None)
    tnode = next((c for c in named(upper_node) if c.type == "term"), None)
    if tnode is None or rnode is None:
        return None
    rel = REL[text(src, rnode)]
    term = convert_term(lib, src, tnode)
    return ast.RightGuard(lib, relation=rel, term=term)

def _parse_condition_literals_from_element(lib: Library, src: bytes, el_node) -> List[ast.Literal]:
    """Collect condition literals (as clingo.ast.Literal) from a body_aggregate_element.
    node-types marks ':' and literal_tuple as field 'condition'. We just need the literal_tuple."""
    tup = next((c for c in named(el_node) if c.type == "literal_tuple"), None)
    if tup is None:
        return []
    lits: List[ast.Literal] = []
    for lit in named(tup):
        if lit.type == "literal":
            lits.append(convert_literal(lib, src, lit))
    return lits

def convert_body_aggregate(lib: Library, src: bytes, node, sign: ast.Sign) -> ast.BodyAggregate:
    # body_aggregate has direct children: [lower] aggregate_function [body_aggregate_elements] [upper]
    loc = ts_loc(lib, node)
    lower = next((c for c in named(node) if c.type == "lower"), None)
    upper = next((c for c in named(node) if c.type == "upper"), None)
    fn_tok = next((c for c in named(node) if c.type == "aggregate_function"), None)
    if fn_tok is None:
        raise ValueError("malformed body_aggregate: missing aggregate_function")
    fun = AGGFN[text(src, fn_tok)]

    elements: List[ast.BodyAggregateElement] = []
    elems_parent = next((c for c in named(node) if c.type == "body_aggregate_elements"), None)
    if elems_parent is not None:
        for el in named(elems_parent):
            if el.type != "body_aggregate_element":
                continue
            el_loc = ts_loc(lib, el)
            # tuple terms
            terms_node = next((c for c in named(el) if c.type == "terms"), None)
            if terms_node is not None:
                terms = [convert_term(lib, src, t) for t in named(terms_node) if t.type == "term"]
            else:
                terms = []
            tup = terms  # BodyAggregateElement expects Iterable[Term]
            cond = _parse_condition_literals_from_element(lib, src, el)
            elements.append(ast.BodyAggregateElement(lib, location=el_loc, tuple=tup, condition=cond))

    left  = _parse_lower_guard(lib, src, lower)
    right = _parse_upper_guard(lib, src, upper)
    return ast.BodyAggregate(lib, location=loc, sign=sign, left=left, function=fun, elements=elements, right=right)

# ------------------------------ conditional literals --------------------------

def convert_conditional_literal_body(lib: Library, src: bytes, node):
    """BodyConditionalLiteral: literal : condition."""
    loc = ts_loc(lib, node)
    lits = [ch for ch in named(node) if ch.type == "literal"]
    base = convert_literal(lib, src, lits[0])
    cond: List[ast.BodySimpleLiteral] = []
    for ch in lits[1:]:
        cond.append(ast.BodySimpleLiteral(lib, literal=convert_literal(lib, src, ch)))
    for ch in named(node):
        if ch.type == "literal_tuple":
            for g in named(ch):
                if g.type == "literal":
                    cond.append(ast.BodySimpleLiteral(lib, literal=convert_literal(lib, src, g)))
    return ast.BodyConditionalLiteral(lib, location=loc, literal=base, condition=cond)

# ------------------------------ head / body / stmts ---------------------------

def convert_head(lib: Library, src: bytes, node):
    for ch in named(node):
        if ch.type == "literal":
            return ast.HeadSimpleLiteral(lib, literal=convert_literal(lib, src, ch))
        if ch.type == "disjunction":
            return convert_disjunction_head(lib, src, ch)
    if node.type == "literal":
        return ast.HeadSimpleLiteral(lib, literal=convert_literal(lib, src, node))
    if node.type == "disjunction":
        return convert_disjunction_head(lib, src, node)
    return ast.HeadDisjunction(lib, location=ts_loc(lib, node), elements=[])

def convert_disjunction_head(lib: Library, src: bytes, node):
    loc = ts_loc(lib, node)
    elems = []
    for ch in named(node):
        if ch.type in ("conditional_literal","conditional_literal_n","conditional_literal_0"):
            # head-conditional literal form
            hl = convert_conditional_literal_body(lib, src, ch)  # reuse body version to build literal/condition
            elems.append(ast.HeadConditionalLiteral(lib, location=hl.location, literal=hl.literal, condition=[
                ast.HeadSimpleLiteral(lib, literal=b.literal) for b in hl.condition
            ]))
        elif ch.type == "literal":
            elems.append(ast.HeadSimpleLiteral(lib, literal=convert_literal(lib, src, ch)))
    return ast.HeadDisjunction(lib, location=loc, elements=elems)

def convert_body_literal(lib: Library, src: bytes, node):
    """
    body_literal := [sign] ( set_aggregate | body_aggregate | theory_atom | _simple_atom )
    Also handle the alias cases used in separators.
    """
    t = node.type
    if t == "conditional_literal":
        return convert_conditional_literal_body(lib, src, node)

    # unwrap alias containers
    if t == "_body_literal":
        sub = next((c for c in named(node) if c.type in ("body_literal","conditional_literal")), None)
        return convert_body_literal(lib, src, sub) if sub is not None else None

    if t == "body_literal":
        kids = named(node)
        si = kids[0] if kids and kids[0].type == "sign" else None
        payload = next((c for c in kids if c.type in (
            "set_aggregate","body_aggregate","theory_atom","symbolic_atom","comparison","boolean_constant"
        )), None)
        if payload is None:
            return None
        # aggregates
        if payload.type == "body_aggregate":
            return convert_body_aggregate(lib, src, payload, sign_from(si))
        # (set_aggregate and theory_atom not implemented here)
        if payload.type in ("symbolic_atom","comparison","boolean_constant"):
            lit = convert_simple_literal(lib, src, payload, sign_from(si), ts_loc(lib, node))
            return ast.BodySimpleLiteral(lib, literal=lit)
        return None

    # Fallbacks when parser gave us simple literal nodes directly (rare)
    if t == "literal":
        return ast.BodySimpleLiteral(lib, literal=convert_literal(lib, src, node))
    if t == "conditional_literal":
        return convert_conditional_literal_body(lib, src, node)

    return None

def convert_body(lib: Library, src: bytes, node) -> List:
    items: List = []
    for ch in named(node):
        if ch.type in ("body_literal", "_body_literal", "conditional_literal", "literal"):
            conv = convert_body_literal(lib, src, ch)
            if conv is not None:
                items.append(conv)
    return items

def convert_statement(lib: Library, src: bytes, node):
    t = node.type
    loc = ts_loc(lib, node)
    if t == "rule":
        head = None
        body: List = []
        for ch in named(node):
            if ch.type == "head":
                head = convert_head(lib, src, ch)
            elif ch.type == "body":
                body = convert_body(lib, src, ch)
        if head is None:
            head = ast.HeadDisjunction(lib, location=loc, elements=[])
        return ast.StatementRule(lib, location=loc, head=head, body=body)
    if t == "integrity_constraint":
        body = []
        for ch in named(node):
            if ch.type == "body":
                body = convert_body(lib, src, ch)
        head = ast.HeadDisjunction(lib, location=loc, elements=[])
        return ast.StatementRule(lib, location=loc, head=head, body=body)
    return None

# ---------------------------------- driver ------------------------------------

def parse_to_clingo_ast(lib: Library, src: bytes, lang: Language):
    parser = Parser(lang)  # TS 0.23.6
    tree = parser.parse(src)
    root = tree.root_node

    out = []
    for st in named(root):
        if st.type == "statement":
            for ch in named(st):
                stmt = convert_statement(lib, src, ch)
                if stmt is not None:
                    out.append(stmt)
        elif st.type in ("rule", "integrity_constraint"):
            stmt = convert_statement(lib, src, st)
            if stmt is not None:
                out.append(stmt)
    return out

def main():
    ap = argparse.ArgumentParser(description="Parse Clingo (clingo 6) with Tree-Sitter and build clingo.ast nodes.")
    srcg = ap.add_mutually_exclusive_group(required=True)
    srcg.add_argument("--text", type=str, help="Inline program text.")
    srcg.add_argument("--file", type=Path, help="Path to .lp file.")
    ap.add_argument("--module", type=str, default=None, help="Python module exposing language() (e.g., tree_sitter_clingo).")
    ap.add_argument("--so", type=Path, default=None, help="Path to compiled parser shared lib exporting tree_sitter_clingo().")
    args = ap.parse_args()

    lang = load_ts_language(args.module, args.so)
    src_bytes = args.text.encode() if args.text is not None else args.file.read_bytes()

    lib = Library()
    ast_list = parse_to_clingo_ast(lib, src_bytes, lang)
    for i, stm in enumerate(ast_list, 1):
        print(f"% ---- statement {i} ----")
        print(stm)

if __name__ == "__main__":
    main()
