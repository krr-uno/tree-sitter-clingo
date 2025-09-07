#!/usr/bin/env python3
# Python 3.9+
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Union, Tuple
import argparse
import ctypes
import importlib
import os
import sys
from pathlib import Path

from tree_sitter import Language, Parser

# -----------------------------------------------------------------------------
# AST (lean subset modeled after https://potassco.org/clingo-preview/python-api/clingo/ast.html)
# -----------------------------------------------------------------------------

@dataclass
class Location:
    start_row: int
    start_col: int
    end_row: int
    end_col: int

@dataclass
class Relation:
    op: str  # one of ">", "<", ">=", "<=", "=", "!="

# Terms
@dataclass
class TermNumber:
    value: int
    location: Location

@dataclass
class TermString:
    value: str
    location: Location

@dataclass
class TermIdentifier:
    name: str
    location: Location

@dataclass
class TermFunction:
    name: str
    arguments: List[List["Term"]]  # pool/tuple-of-tuples (as per grammar "pool/tuple")
    location: Location

@dataclass
class TermTuple:
    items: List[List["Term"]]  # like function pool without name
    location: Location

@dataclass
class TermUnaryOperation:
    op: str  # "-" or "~"
    rhs: "Term"
    location: Location

@dataclass
class TermBinaryOperation:
    op: str  # "+", "-", "*", "/", "\\", "**", "&", "?", "^", ".."
    left: "Term"
    right: "Term"
    location: Location

@dataclass
class TermAbsolute:
    pool: List["Term"]  # abs can be |t1; t2; ...|
    location: Location

Term = Union[
    TermNumber, TermString, TermIdentifier,
    TermFunction, TermTuple, TermUnaryOperation,
    TermBinaryOperation, TermAbsolute
]

# Atoms & Literals
@dataclass
class SymbolicAtom:
    name: str
    pool: Optional[List[List[Term]]]
    location: Location

@dataclass
class AtomComparison:
    left: Term
    relations: List[Tuple[Relation, Term]]  # chained: a < b <= c ...
    location: Location

@dataclass
class AtomBoolean:
    value: bool
    location: Location

SimpleAtom = Union[SymbolicAtom, AtomComparison, AtomBoolean]

@dataclass
class Sign:
    # clingo has Sign.NoSign / Single / Double; we encode literally
    count_not: int  # 0, 1, or 2

@dataclass
class Literal:
    sign: Sign
    atom: SimpleAtom
    location: Location

@dataclass
class ConditionalLiteral:
    literal: Literal
    condition: List[Literal]  # ":" literal_tuple
    location: Location

HeadElement = Union[
    Literal,                       # HeadSimpleLiteral
    ConditionalLiteral,            # used in disjunction
]

@dataclass
class HeadDisjunction:
    elements: List[HeadElement]
    location: Location

Head = Union[Literal, HeadDisjunction]

@dataclass
class Body:
    # mix of simple/aggregate/theory not fully covered here; we support simple/cond literals
    items: List[Literal | ConditionalLiteral]
    location: Location

# Statements
@dataclass
class StatementRule:
    head: Head
    body: Optional[Body]
    location: Location

@dataclass
class StatementIntegrityConstraint:
    body: Body
    location: Location

Statement = Union[StatementRule, StatementIntegrityConstraint]

# -----------------------------------------------------------------------------
# Utility: load Tree-Sitter language
# -----------------------------------------------------------------------------

def load_ts_language(module: Optional[str], so_path: Optional[Path]) -> Language:
    """
    Load the clingo language for Tree-Sitter 0.23.x either from
    - a Python module that exposes language() (returning capsule/pointer) or
    - a compiled shared library exporting tree_sitter_clingo().
    """
    if module:
        m = importlib.import_module(module)  # e.g., tree_sitter_clingo
        lang_capsule = m.language()
        # Wrap capsule/pointer into Language if needed
        return lang_capsule if isinstance(lang_capsule, Language) else Language(lang_capsule)
    if so_path:
        if not so_path.exists():
            raise FileNotFoundError(f"Shared lib not found: {so_path}")
        lib = ctypes.CDLL(str(so_path))
        try:
            lib.tree_sitter_clingo.restype = ctypes.c_void_p
            capsule = lib.tree_sitter_clingo()
        except AttributeError:
            raise RuntimeError(f"{so_path} does not export tree_sitter_clingo")
        if not capsule:
            raise RuntimeError("tree_sitter_clingo() returned NULL")
        return Language(capsule)
    raise SystemExit("Provide --module tree_sitter_clingo OR --so ./parser.(so|dylib|dll)")

# -----------------------------------------------------------------------------
# CST helpers
# -----------------------------------------------------------------------------

def loc(node) -> Location:
    s = node.start_point
    e = node.end_point
    return Location(s[0], s[1], e[0], e[1])

def text(src: bytes, node) -> str:
    return src[node.start_byte:node.end_byte].decode("utf-8", "replace")

def children(node):
    return list(node.children)

def field(node, name: str):
    # Tree-Sitter python binding exposes named_children + field_names via node.child_by_field_name
    return node.child_by_field_name(name)

def named(node):
    return [c for c in node.children if c.is_named]

# -----------------------------------------------------------------------------
# Converters: CST -> AST
# (Each converter assumes the node type matches; dispatch from higher-level.)
# -----------------------------------------------------------------------------

# --- Terms ---

def convert_term(src: bytes, node) -> Term:
    t = node.type
    if t == "number":
        # handle hex/oct/bin as integers
        raw = text(src, node)
        if raw.startswith(("0x", "0X")):
            val = int(raw, 16)
        elif raw.startswith(("0o", "0O")):
            val = int(raw, 8)
        elif raw.startswith(("0b", "0B")):
            val = int(raw, 2)
        else:
            val = int(raw)
        return TermNumber(val, loc(node))
    if t == "string":
        s = text(src, node)
        # naive unescape: strip quotes
        if len(s) >= 2 and s[0] == s[-1] == '"':
            s = s[1:-1]
        return TermString(s, loc(node))
    if t in ("identifier", "negative_identifier"):
        return TermIdentifier(text(src, node).strip(), loc(node))
    if t == "function":
        nm = field(node, "name")
        pool = field(node, "arguments")  # "pool" node or None
        args = convert_pool(src, pool) if pool else None
        return TermFunction(
            name=text(src, nm).strip(),
            arguments=args or [],
            location=loc(node),
        )
    if t == "tuple":
        return TermTuple(
            items=convert_pool(src, node),  # tuple shares the "pool-like" shape
            location=loc(node),
        )
    if t == "unary":
        op = field(node, "op")
        rhs = field(node, "rhs")
        return TermUnaryOperation(text(src, op), convert_term(src, rhs), loc(node))
    if t == "binary":
        lhs = field(node, "lhs")
        rhs = field(node, "rhs")
        op = field(node, "op")
        return TermBinaryOperation(text(src, op), convert_term(src, lhs), convert_term(src, rhs), loc(node))
    if t == "abs":
        # | term (; term)* |
        # Represent as TermAbsolute over the flattened group (first "term" of each part)
        items = []
        # first child is "|" then a sequence of terms and ";" then final "|"
        for ch in named(node):
            if ch.type == "term":
                items.append(convert_term(src, ch))
        return TermAbsolute(items, loc(node))

    # generic fallback: if node *is* a term wrapper, dive into first named
    for ch in named(node):
        if ch.type in ("infimum", "supremum", "anonymous", "variable"):
            # you can extend to support them if needed
            return TermIdentifier(text(src, ch), loc(ch))
        if ch.type in ("function", "tuple", "binary", "unary", "abs", "number", "string",
                       "identifier", "negative_identifier"):
            return convert_term(src, ch)
    raise ValueError(f"Unhandled term node: {t}")

def convert_pool(src: bytes, pool_node) -> List[List[Term]]:
    """
    Grammar shape:
      pool      : '(' terms (';' terms)* ')'
      terms     : term (',' term)*
    We represent it as a list of lists (rows separated by ';').
    """
    if pool_node is None:
        return []
    rows: List[List[Term]] = []
    cur: List[Term] = []
    for ch in named(pool_node):
        if ch.type == "terms":
            # this "terms" can repeat; on each, start a new row
            if cur:
                rows.append(cur)
                cur = []
            # collect items inside 'terms'
            for tch in named(ch):
                if tch.type == "term":
                    cur.append(convert_term(src, tch))
        # ignore terminals ')' '{' etc.; the aliases make "terms" appear multiple times
    if cur:
        rows.append(cur)
    return rows

# --- Simple atoms & literals ---

def convert_symbolic_atom(src: bytes, node) -> SymbolicAtom:
    nm = field(node, "name")
    pool = field(node, "pool")
    return SymbolicAtom(
        name=text(src, nm).strip(),
        pool=convert_pool(src, pool) if pool else None,
        location=loc(node),
    )

def convert_comparison(src: bytes, node) -> AtomComparison:
    # comparison: term relation term (relation term)*
    kids = named(node)
    assert kids and kids[0].type == "term"
    left = convert_term(src, kids[0])
    rest: List[Tuple[Relation, Term]] = []
    i = 1
    while i + 1 < len(kids):
        rel = kids[i]; rhs = kids[i+1]
        rest.append((Relation(text(src, rel)), convert_term(src, rhs)))
        i += 2
    return AtomComparison(left=left, relations=rest, location=loc(node))

def convert_boolean(src: bytes, node) -> AtomBoolean:
    val = text(src, node) == "#true"
    return AtomBoolean(val, loc(node))

def convert_simple_atom(src: bytes, node) -> SimpleAtom:
    t = node.type
    if t == "symbolic_atom":
        return convert_symbolic_atom(src, node)
    if t == "comparison":
        return convert_comparison(src, node)
    if t == "boolean_constant":
        return convert_boolean(src, node)
    # fallback: single child might be the actual type
    for ch in named(node):
        if ch.type in ("symbolic_atom", "comparison", "boolean_constant"):
            return convert_simple_atom(src, ch)
    raise ValueError(f"Unhandled simple atom node: {t}")

def convert_sign(src: bytes, node_opt) -> Sign:
    """
    Grammar:
      sign : 'not' ['not']
    """
    if node_opt is None:
        return Sign(0)
    # node is 'sign' or direct 'default_negation'
    if node_opt.type == "default_negation":
        return Sign(1)
    if node_opt.type == "sign":
        # count occurrences of 'default_negation' under it
        c = sum(1 for ch in named(node_opt) if ch.type == "default_negation")
        return Sign(c)
    # defensive
    return Sign(0)

def convert_literal(src: bytes, node) -> Literal:
    # literal: [sign] _simple_atom
    kids = named(node)
    si = None
    atom_node = None
    if kids and kids[0].type in ("sign", "default_negation"):
        si = kids[0]
        atom_node = kids[1] if len(kids) > 1 else None
    else:
        atom_node = kids[0] if kids else None
    return Literal(
        sign=convert_sign(src, si),
        atom=convert_simple_atom(src, atom_node),
        location=loc(node),
    )

def convert_conditional_literal(src: bytes, node) -> ConditionalLiteral:
    # conditional_literal: literal ':' literal_tuple
    kids = named(node)
    assert kids and kids[0].type == "literal"
    base = convert_literal(src, kids[0])
    cond: List[Literal] = []
    # find the condition tuple (":" literal, ("," literal)*)
    for ch in kids[1:]:
        if ch.type in ("literal", "literal_tuple"):
            if ch.type == "literal":
                cond.append(convert_literal(src, ch))
            else:
                for g in named(ch):
                    if g.type == "literal":
                        cond.append(convert_literal(src, g))
    return ConditionalLiteral(base, cond, loc(node))

# --- Head & Body ---

def convert_head(src: bytes, node) -> Head:
    t = node.type
    if t == "head":
        # head : literal | disjunction | set_aggregate | head_aggregate | theory_atom
        # We support literal and disjunction here; others can be added analogously.
        for ch in named(node):
            if ch.type == "literal":
                return convert_literal(src, ch)
            if ch.type == "disjunction":
                return convert_disjunction(src, ch)
        # Fallback: just try literal
        for ch in named(node):
            if ch.type == "conditional_literal":
                # single conditional treated as disjunction with one element
                return HeadDisjunction([convert_conditional_literal(src, ch)], loc(node))
        raise ValueError("Unsupported head form (aggregate/theory not yet mapped).")
    if t == "disjunction":
        return convert_disjunction(src, node)
    if t == "literal":
        return convert_literal(src, node)
    raise ValueError(f"Unhandled head node: {t}")

def convert_disjunction(src: bytes, node) -> HeadDisjunction:
    # disjunction is a sequence mixing literal and conditional_literal separated by '|', ';', ','
    elems: List[HeadElement] = []
    for ch in named(node):
        if ch.type == "literal":
            elems.append(convert_literal(src, ch))
        elif ch.type == "conditional_literal":
            elems.append(convert_conditional_literal(src, ch))
    return HeadDisjunction(elems, loc(node))

def convert_body(src: bytes, node) -> Body:
    """
    body: ( ...body_literal... ) "."
    For now we collect simple and conditional literals; aggregates/theory can be added later.
    """
    items: List[Literal | ConditionalLiteral] = []
    for ch in named(node):
        if ch.type == "body_literal":
            # body_literal -> [sign] (set_aggregate | body_aggregate | theory_atom | _simple_atom)
            # If it resolved to simple literal, it will be a 'literal' child under an alias'ed path.
            # Here we pattern-match by diving for 'literal' or 'conditional_literal'.
            lit = None
            for g in named(ch):
                if g.type == "literal":
                    lit = convert_literal(src, g)
                    items.append(lit)
                elif g.type == "conditional_literal":
                    items.append(convert_conditional_literal(src, g))
        elif ch.type == "conditional_literal":
            items.append(convert_conditional_literal(src, ch))
        elif ch.type == "literal":
            items.append(convert_literal(src, ch))
    return Body(items, loc(node))

# --- Statements ---

def convert_statement(src: bytes, node) -> Optional[Statement]:
    t = node.type
    if t == "rule":
        # rule : head "."  |  head ":-" body
        kids = named(node)
        # Find "head" and maybe "body"
        hd = None
        bd = None
        for ch in kids:
            if ch.type == "head":
                hd = convert_head(src, ch)
            elif ch.type == "body":
                bd = convert_body(src, ch)
        return StatementRule(hd, bd, loc(node))
    if t == "integrity_constraint":
        # ":-" body
        bd = next((ch for ch in named(node) if ch.type == "body"), None)
        if bd is None:
            raise ValueError("Integrity constraint without body?")
        return StatementIntegrityConstraint(convert_body(src, bd), loc(node))

    # not building others yet (weak_constraint, show, etc.) — easy to add later
    return None

# -----------------------------------------------------------------------------
# Parse + build AST
# -----------------------------------------------------------------------------

def parse_to_ast(src: bytes, lang: Language) -> List[Statement]:
    parser = Parser(lang)  # TS 0.23.x: pass language in constructor
    tree = parser.parse(src)
    root = tree.root_node
    # grammar’s root is `source_file` containing many `statement`s
    out: List[Statement] = []
    for st in named(root):
        if st.type == "statement":
            # drill down: the first named child is the concrete statement kind
            for ch in named(st):
                stmt = convert_statement(src, ch)
                if stmt is not None:
                    out.append(stmt)
    return out

# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Parse Clingo with Tree-Sitter and build a clingo-like AST.")
    srcg = ap.add_mutually_exclusive_group(required=True)
    srcg.add_argument("--text", type=str, help="Inline program text.")
    srcg.add_argument("--file", type=Path, help="Path to .lp file.")
    ap.add_argument("--module", type=str, default=None,
                    help="Python module exposing language() (e.g., tree_sitter_clingo).")
    ap.add_argument("--so", type=Path, default=None,
                    help="Path to compiled parser shared lib exporting tree_sitter_clingo().")
    args = ap.parse_args()

    lang = load_ts_language(args.module, args.so)
    src_bytes = args.text.encode() if args.text is not None else args.file.read_bytes()

    ast = parse_to_ast(src_bytes, lang)

    # Pretty print result (quick demo)
    from pprint import pprint
    pprint(ast, width=100, compact=False)

if __name__ == "__main__":
    main()
