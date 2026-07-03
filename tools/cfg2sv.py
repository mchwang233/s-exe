#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cfg2sv.py - Convert .cfg files into SystemVerilog (UVM ssv_object) classes
            and generate the cfg package + all.cmd.

.cfg syntax (INI-ish + C-block hybrid):
------------------------------------------------------------
# Lines starting with '#' or '//' are comments.
# (No in-line comment support; put comments on their own line.)

<type> :: <NAME> = <value>          # field declaration. supported types:
                                    #   int / int unsigned / bit / byte / shortint
                                    #   / longint / real / string
                                    #   / bit [N:0] / bit [N:M] / logic [...]
                                    # The boundary is '::' (NOT ':'):
                                    # it does not collide with the ':' inside
                                    # bit/logic vector dimensions like 'bit[7:0]',
                                    # and whitespace around '::' is optional.

<class_name> <inst_name> {          # sub-object instantiation. The block body
                                    # may only contain field overrides.
    <type> :: <NAME> = <value>      # override field; if absent, the sub-object
                                    # uses its own .cfg default.
    ...
}

class_name {                        # top-level class declaration. Each .cfg file
                                    # may declare at most ONE top-level class.
    ...
}
------------------------------------------------------------

@ include syntax (allowed only OUTSIDE any class block):
    @<path>            Load the .cfg file at <path> as a standalone cfg.
                       Its top-level class is registered in the global
                       registry; this .cfg's fields are NOT auto-merged
                       (independent-cfg semantics). Nested @ is allowed;
                       circular includes raise an error.

    Path resolution:
        - '/' prefix → absolute path
        - otherwise  → relative to the directory of the CURRENT .cfg file
        - ${VAR} and $VAR are both expanded via os.path.expandvars;
          if a '$' remains in the expanded path, the env var is undefined
          and an error is raised.
        - After expansion the path is .resolve()'d (absolute).

Each .cfg file defines a class whose name is the top-level class block
(or the file name by default). Cross-file class references are legal:
the parser scans all .cfg files to build the type registry first.

Usage:
    python3 tools/cfg2sv.py [--cfg-dir cfg] [--root top.cfg]
                             [--root-class ssv_root_cfg]

Outputs:
    cfg/<class_name>.sv            one per cfg class (sits next to its .cfg)
    cfg/ssv_cfg_pkg.sv             packages all cfg classes
    cfg/all.cmd                    default cfg dump (one ssv_cfg: line per
                                   field hierarchy path, used as the glob
                                   expansion candidate set on the Python side)
"""
import argparse
import dataclasses
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ----------------------------- Data structures -----------------------------

@dataclasses.dataclass
class FieldDecl:
    ftype: str   # full type, e.g. "int unsigned" / "bit [7:0]" / "logic [3:0]"
    name: str
    value: str   # raw literal text (preserved verbatim, not parsed; written
                 # straight into the generated SV).

@dataclasses.dataclass
class SubObjDecl:
    class_name: str
    inst_name: str
    overrides: List[FieldDecl] = dataclasses.field(default_factory=list)

@dataclasses.dataclass
class ClassDecl:
    name: str
    fields: List[FieldDecl] = dataclasses.field(default_factory=list)
    sub_objects: List[SubObjDecl] = dataclasses.field(default_factory=list)
    source_file: str = ""

# ----------------------------- Parser -----------------------------

# Default values for simple types (used when a field omits the '= value' part).
_SIMPLE_TYPE_DEFAULT = {
    "int": "0",
    "int unsigned": "0",
    "uint": "0",
    "bit": "1'b0",
    "logic": "1'b0",
    "byte": "0",
    "shortint": "0",
    "longint": "0",
    "real": "0.0",
    "string": "\"\"",
}


# ----------------------------- array/queue type helpers -----------------------------

def _is_dynamic_array(ftype: str) -> bool:
    return "[]" in ftype

def _is_queue(ftype: str) -> bool:
    return "[$]" in ftype

def _is_array(ftype: str) -> bool:
    return _is_dynamic_array(ftype) or _is_queue(ftype)

def _array_dim(ftype: str) -> str:
    if _is_queue(ftype):
        return "[$]"
    if _is_dynamic_array(ftype):
        return "[]"
    return ""

def _array_elem_type(ftype: str) -> str:
    dim = _array_dim(ftype)
    if not dim:
        return ftype
    return ftype.replace(dim, "", 1).strip()

def _array_or_scalar_default(ftype: str) -> str:
    if _is_array(ftype):
        return "'{}"
    base = ftype.split(' ')[0]
    return _SIMPLE_TYPE_DEFAULT.get(base, "0")

def _strip_inline_comment(line: str) -> str:
    """Strip '#' / '//' comments outside of string literals.

    Handles both whole-line comments (returns "") and inline trailing
    comments (truncates at the comment marker, then rstrip). '#' and '//'
    inside "..." string literals are preserved as data.

    Examples:
        "# whole line"                            -> ""
        "  // whole line   "                      -> ""
        "int :: A = 5; # trailing comment"        -> "int :: A = 5;"
        'string :: A = "hello #world";'          -> 'string :: A = "hello #world";'
        'string :: A = "// not a comment";'       -> 'string :: A = "// not a comment";'
    """
    in_s = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_s:
            # Inside a string literal: only an unescaped '"' exits the
            # literal. Don't treat '#' / '//' inside the literal as comments.
            if ch == '"' and (i == 0 or line[i-1] != '\\'):
                in_s = False
            i += 1
            continue
        if ch == '"':
            in_s = True
            i += 1
            continue
        if ch == '#':
            return line[:i].rstrip()
        if ch == '/' and i + 1 < len(line) and line[i+1] == '/':
            return line[:i].rstrip()
        i += 1
    return line

def _split_top_type(full_type: str) -> str:
    """Normalize type spelling (collapse multiple whitespace)."""
    return re.sub(r'\s+', ' ', full_type.strip())

def _clean_value(s: str) -> str:
    """Strip trailing ',' or ';' and surrounding whitespace."""
    s = s.strip()
    # Repeatedly strip trailing ',' or ';'.
    while s and s[-1] in (',', ';'):
        s = s[:-1].rstrip()
    return s

def _resolve_include_path(token: str, base: Path) -> Path:
    """Resolve the path after '@':
    1) Expand env vars ($VAR and ${VAR}).
    2) '/' prefix -> absolute; otherwise -> relative to base.parent.
    3) .resolve() to absolute.
    Undefined env vars raise SyntaxError.
    """
    expanded = os.path.expandvars(token)
    if '$' in expanded:
        undefined = re.findall(r'\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?', expanded)
        raise SyntaxError(
            f"@ include: env var undefined in path: {token!r}"
            f" (expanded still contains '$'; candidates: {undefined})")
    p = Path(expanded)
    if not p.is_absolute():
        p = (base.parent / p).resolve()
    else:
        p = p.resolve()
    return p


def _cfg_line_iter(path: Path, _active: Set[Path]):
    """Yield two kinds of tokens:
      ('line', raw_text, source_path, line_idx_in_source)
      ('include', include_token, source_path, line_idx_in_source)
    Raises SyntaxError on circular include.

    @ lines are NOT inlined (we don't yield the included file's lines).
    Instead we yield an 'include' event so parse_cfg itself recursively
    calls parse_cfg to handle the included file's top-level class, and
    accumulates all included top-level classes via a shared _acc_includes
    list.
    """
    abs_path = path.resolve()
    if abs_path in _active:
        raise SyntaxError(f"{path}: circular @ include: {abs_path}")
    _active.add(abs_path)
    try:
        # Use utf-8-sig so a leading BOM (Excel / some Windows editors) is
        # stripped automatically. Without this, the BOM gets glued onto the
        # first token of the first line, breaking class-block detection and
        # surfacing as a cryptic IndexError.
        text = path.read_text(encoding='utf-8-sig')
        line_idx = 0
        for raw in text.split('\n'):
            line_idx += 1
            stripped = raw.strip()
            if stripped.startswith('@'):
                # @ include: yield an event for parse_cfg to handle.
                if not stripped or stripped == '@':
                    raise SyntaxError(f"{path}:{line_idx}: @ include: path missing")
                first_token = stripped.split()[0]
                inc_token = first_token[1:]  # drop the leading '@'
                if not inc_token:
                    raise SyntaxError(f"{path}:{line_idx}: @ include: path missing")
                yield ('include', inc_token, path, line_idx)
                continue
            yield ('line', raw, path, line_idx)
    finally:
        _active.discard(abs_path)


def parse_cfg(path: Path, *, require_top_class: bool = True,
              _active: Optional[Set[Path]] = None,
              _acc_includes: Optional[List[ClassDecl]] = None
              ) -> Tuple[Optional[ClassDecl], List[ClassDecl]]:
    """Parse one .cfg file, recursively handling @ includes.

    Returns: (main_decl, included_decls)
        main_decl:       this file's top-level class (must be non-None when
                         require_top_class=True)
        included_decls:  flat list of every top-level class reached via @
                         include across the whole include chain (order =
                         first occurrence)

    @ include rules:
        - Only allowed OUTSIDE any class block (i.e. at top level).
        - Path: absolute, or relative to the current .cfg's parent dir;
          supports ${VAR} and $VAR env var expansion.
        - Circular includes raise (detected via the cross-recursion _active
          set).
        - Same file re-included: blocked by the _active set during recursion.
          A top-level call to parse_cfg on the same file again is treated as
          "independent class re-registration" (the caller / registry dedups
          via source_file).
    """
    if _active is None:
        _active = set()
    if _acc_includes is None:
        _acc_includes = []

    # Always resolve the path so source_file is a uniform absolute path.
    # (Paths passed in from @ include are already resolved; paths from
    # cfg_dir.glob() may not be.)
    path = path.resolve()

    # Cycle detection is owned by _cfg_line_iter (parse_cfg does not
    # pre-add abs_path to _active, otherwise the first entry would be
    # blocked by itself).

    decl: Optional[ClassDecl] = None
    stack: List[Tuple[str, object]] = []  # nested block tracking (class / subobj)

    for tok in _cfg_line_iter(path, _active):
        kind = tok[0]

        if kind == 'include':
            # Include directive: resolve the path, recurse into parse_cfg, and
            # accumulate the included file's top-level class into
            # _acc_includes (independent-cfg semantics; no field merging).
            _, inc_token, src_path, line_idx = tok
            if stack:
                raise SyntaxError(
                    f"{src_path}:{line_idx}: @ include is only allowed outside"
                    f" any class block (top level)")
            inc_path = _resolve_include_path(inc_token, src_path)
            if not inc_path.exists():
                raise SyntaxError(
                    f"{src_path}:{line_idx}: @ include: file not found: {inc_path}")
            # Recurse: pass the SAME _acc_includes list so every class along
            # the include chain ends up there.
            inc_decl, _nested = parse_cfg(
                inc_path, require_top_class=True,
                _active=_active, _acc_includes=_acc_includes)
            if inc_decl is not None:
                _acc_includes.append(inc_decl)
            # _nested was already accumulated into _acc_includes above
            # (shared list reference).
            continue

        # kind == 'line'
        _, raw, src_path, line_idx = tok

        # Strip inline '#' / '//' comments (outside string literals) BEFORE
        # tokenizing, so trailing comments like 'int :: A = 5; # note' don't
        # leak into the value field. The whole-line comment check below is
        # preserved so blank-after-strip lines are skipped cleanly.
        raw = _strip_inline_comment(raw)
        stripped = raw.strip()
        if not stripped or stripped.startswith('#') or stripped.startswith('//'):
            continue

        # @ lines were dispatched as 'include' events in the iterator and
        # will never reach here.
        assert not stripped.startswith('@'), "internal: @ line not handled by iterator"

        # In-line comment removal (outside string literals): find the first
        # '#' or '//' outside quotes and truncate.
        # Simplified: only treat '//' after leading whitespace as a comment
        # opener; '#' same. (Users typically wrap '#' in string literals.)

        # Tokenize { and } boundaries. First, merge strings into single token
        # segments to protect special characters inside strings.
        tokens: List[str] = []
        cur = []
        j = 0
        instr = False
        # Use a regex-like approach: match string literals, {, }, whitespace,
        # and 'everything else'. Simplified: just character-by-character scan.
        buf = raw
        k = 0
        cur_token: List[str] = []
        in_s = False
        segment_buf: List[str] = []
        segments: List[Tuple[str, str]] = []  # (kind, text); kind: ws / punct / string / other
        while k < len(buf):
            ch = buf[k]
            if in_s:
                segment_buf.append(ch)
                if ch == '"' and (k == 0 or buf[k-1] != '\\'):
                    segments.append(('string', "".join(segment_buf)))
                    segment_buf = []
                    in_s = False
                k += 1
                continue
            if ch == '"':
                if segment_buf:
                    segments.append(('other', "".join(segment_buf)))
                    segment_buf = []
                in_s = True
                segment_buf.append(ch)
                k += 1
                continue
            # '::' is a 2-char punct that marks the type/name boundary for
            # a field. We use '::' (not ':') so it does not collide with the
            # single ':' inside bit/logic vector dimensions like 'bit[7:0]',
            # and we don't have to require whitespace around it.
            if ch == ':' and k + 1 < len(buf) and buf[k+1] == ':':
                if segment_buf:
                    segments.append(('other', "".join(segment_buf)))
                    segment_buf = []
                segments.append(('punct', '::'))
                k += 2
                continue
            # Punct set: characters that mark positions which never collide
            # with other syntax:
            #   { }    block boundaries
            #   ; ,    value tail (e.g. '{1, 2, 3}'), statement terminator
            # Single ':' is NOT a punct (it belongs to vector dimensions);
            # the field boundary is detected via '::' above.
            # '=' is also not a punct (current value syntax does not use '='
            # as a literal value).
            if ch in '{};,':
                if segment_buf:
                    segments.append(('other', "".join(segment_buf)))
                    segment_buf = []
                segments.append(('punct', ch))
                k += 1
                continue
            if ch.isspace():
                if segment_buf:
                    segments.append(('other', "".join(segment_buf)))
                    segment_buf = []
                # Coalesce runs of whitespace.
                if segments and segments[-1][0] == 'ws':
                    segments[-1] = ('ws', segments[-1][1] + ch)
                else:
                    segments.append(('ws', ch))
                k += 1
                continue
            segment_buf.append(ch)
            k += 1
        if segment_buf:
            segments.append(('other', "".join(segment_buf)))
            segment_buf = []

        # Merge segments into line_tokens: skip ws; treat string/other as a
        # single token each; punct tokens stand alone.
        line_tokens: List[str] = []
        for kind, t in segments:
            if kind == 'ws':
                continue
            if kind == 'punct':
                line_tokens.append(t)
            else:
                if t:
                    line_tokens.append(t)

        if not line_tokens:
            continue

        # The first token is one of:
        #   "class_name {"               syntax 1: top-level class
        #   "class_name inst_name {"     syntax 2: sub-object instantiation
        #   "class_name { <fields> }"    syntax 1b: one-line top-level class
        #   "class_name inst_name { <overrides> }"  syntax 2b: one-line sub-obj
        #   "<type> :: <NAME> [= <val>]" syntax 3: field line
        #   "}"                          syntax 4: end of current block
        #
        # Top-level '{' starts a new block. Two shapes:
        #   (a) Multi-line block: line ends with '{'; body on subsequent lines.
        #   (b) One-line block: line contains both '{' and '}'; body on the
        #       same line, terminated by ';'. We split body_tokens on ';' to
        #       recover individual field declarations.
        has_open  = '{' in line_tokens
        has_close = '}' in line_tokens
        is_multiline_block = line_tokens[-1] == '{'
        is_oneline_block = False
        if has_open and has_close and not is_multiline_block:
            # Only treat as a one-line block when pre_tokens (before '{') look
            # like a class/subobj declaration: 1 or 2 tokens, no '::'.
            # Otherwise the line is a field whose value happens to contain
            # '{...}' (e.g. 'int :: A = '{1, 2, 3};') and must fall through
            # to field-line processing.
            open_pos = line_tokens.index('{')
            if open_pos in (1, 2) and '::' not in line_tokens[:open_pos]:
                is_oneline_block = True

        if is_multiline_block or is_oneline_block:
            # Extract pre-tokens (the class/subobj declaration).
            open_pos = line_tokens.index('{')
            if is_oneline_block:
                # Find the LAST '}' on the line as the closing brace (one-line
                # blocks have no nesting).
                close_pos = len(line_tokens) - 1 - line_tokens[::-1].index('}')
                pre_tokens   = line_tokens[:open_pos]
                body_tokens  = line_tokens[open_pos+1:close_pos]
                post_tokens  = line_tokens[close_pos+1:]
            else:
                brace_pos    = open_pos
                pre_tokens   = line_tokens[:brace_pos]
                body_tokens  = None
                post_tokens  = []

            if len(pre_tokens) == 1:
                # Top-level class declaration.
                block_name = pre_tokens[0]
                if stack and isinstance(stack[-1][1], ClassDecl):
                    # stack top is ClassDecl -- we're inside a class and
                    # trying to open another class block. Not allowed.
                    raise SyntaxError(
                        f"{src_path}:{line_idx}: nested class definition is not"
                        f" allowed; use '<class_name> <inst_name> {{'")
                if decl is not None:
                    raise SyntaxError(f"{src_path}:{line_idx}: multiple top-level class blocks")
                decl = ClassDecl(name=block_name, source_file=str(path))
                stack.append(("class", decl))
            elif len(pre_tokens) == 2 and stack and isinstance(stack[-1][1], ClassDecl):
                # Sub-object instantiation: <class_name> <inst_name> { ... }
                parent: ClassDecl = stack[-1][1]
                sub = SubObjDecl(class_name=pre_tokens[0], inst_name=pre_tokens[1])
                parent.sub_objects.append(sub)
                stack.append(("subobj", sub))
            else:
                raise SyntaxError(f"{src_path}:{line_idx}: invalid block start: {' '.join(pre_tokens)}")

            # For one-line blocks, process the inline body as field lines
            # and close the block on the same line.
            if is_oneline_block:
                if post_tokens:
                    raise SyntaxError(
                        f"{src_path}:{line_idx}: extra tokens after closing"
                        f" '}}': {' '.join(post_tokens)}")
                # Split the flat body_tokens list on ';' to recover
                # individual field declarations. (The tokenizer already
                # isolated ';' as its own punct token.)
                chunks: List[List[str]] = []
                cur: List[str] = []
                for t in body_tokens:
                    if t == ';':
                        if cur:
                            chunks.append(cur)
                        cur = []
                    else:
                        cur.append(t)
                if cur:
                    chunks.append(cur)
                for field_tokens in chunks:
                    if not field_tokens:
                        continue
                    if '::' not in field_tokens:
                        raise SyntaxError(
                            f"{src_path}:{line_idx}: inline block body"
                            f" missing '::': {' '.join(field_tokens)}")
                    colon_pos = field_tokens.index('::')
                    type_tokens = field_tokens[:colon_pos]
                    rest_tokens = field_tokens[colon_pos+1:]
                    if not type_tokens or not rest_tokens:
                        raise SyntaxError(f"{src_path}:{line_idx}: field syntax error")
                    ftype = _split_top_type(" ".join(type_tokens))
                    name = rest_tokens[0]
                    value_tokens = rest_tokens[1:]
                    if value_tokens and value_tokens[0] == '=':
                        value_tokens = value_tokens[1:]
                    value = _clean_value(" ".join(value_tokens))
                    if not value:
                        value = _array_or_scalar_default(ftype)
                    field = FieldDecl(ftype=ftype, name=name, value=value)
                    if not stack:
                        raise SyntaxError(
                            f"{src_path}:{line_idx}: field outside any block"
                            f" (one-line block body)")
                    top_kind, top_obj = stack[-1]
                    if top_kind == "class" and isinstance(top_obj, ClassDecl):
                        top_obj.fields.append(field)
                    elif top_kind == "subobj" and isinstance(top_obj, SubObjDecl):
                        top_obj.overrides.append(field)
                    else:
                        raise SyntaxError(
                            f"{src_path}:{line_idx}: field outside any block")
                # Close the one-line block immediately.
                if not stack:
                    raise SyntaxError(
                        f"{src_path}:{line_idx}: unmatched '}}' (close > open)")
                stack.pop()
            continue

        if line_tokens == ['}']:
            if not stack:
                raise SyntaxError(f"{src_path}:{line_idx}: unmatched '}}'")
            stack.pop()
            continue

        # Otherwise, this should be a field line: <type> :: <NAME> [= <value>]
        # Inside a SubObjDecl, only field overrides are allowed.
        # Inside a ClassDecl, field declarations + sub-object instantiations
        # (already handled above) are allowed.
        if not stack:
            raise SyntaxError(
                f"{src_path}:{line_idx}: field declaration outside any class"
                f" block (wrap in '<class_name> {{ ... }}' or use"
                f" '@./other.cfg' to pull in a class)")
        top_kind, top_obj = stack[-1]
        if top_kind == "class" and isinstance(top_obj, ClassDecl) and '::' in line_tokens:
            colon_pos = line_tokens.index('::')
            type_tokens = line_tokens[:colon_pos]
            rest_tokens = line_tokens[colon_pos+1:]
            if not type_tokens or not rest_tokens:
                raise SyntaxError(f"{src_path}:{line_idx}: field syntax error")
            ftype = _split_top_type(" ".join(type_tokens))
            name = rest_tokens[0]
            # The rest is the value (joined with a single space).
            value_tokens = rest_tokens[1:]
            # Strip a leading '=' from the value side.
            if value_tokens and value_tokens[0] == '=':
                value_tokens = value_tokens[1:]
            value = _clean_value(" ".join(value_tokens))
            if not value:
                # No '= value': fall back to the type default
                # (array -> '{}', scalar -> _SIMPLE_TYPE_DEFAULT).
                value = _array_or_scalar_default(ftype)
            field = FieldDecl(ftype=ftype, name=name, value=value)
            top_obj.fields.append(field)
            continue

        if top_kind == "subobj" and isinstance(top_obj, SubObjDecl) and '::' in line_tokens:
            # Field override inside a sub-object block.
            colon_pos = line_tokens.index('::')
            type_tokens = line_tokens[:colon_pos]
            rest_tokens = line_tokens[colon_pos+1:]
            ftype = _split_top_type(" ".join(type_tokens))
            name = rest_tokens[0]
            value_tokens = rest_tokens[1:]
            if value_tokens and value_tokens[0] == '=':
                value_tokens = value_tokens[1:]
            value = _clean_value(" ".join(value_tokens))
            if not value:
                value = _array_or_scalar_default(ftype)
            top_obj.overrides.append(FieldDecl(ftype=ftype, name=name, value=value))
            continue

        # Fallback: a line that is neither a field nor a block start. This
        # usually means a missing '::' or stray syntax.
        raise SyntaxError(f"{src_path}:{line_idx}: unrecognized statement: {raw.strip()}")

    if stack:
        raise SyntaxError(f"{path}: file not closed (unmatched braces)")
    if require_top_class and decl is None:
        raise SyntaxError(f"{path}: no top-level class declaration found")
    return decl, _acc_includes


# ----------------------------- Registry & cross-file resolution -----------------------------

class CfgRegistry:
    def __init__(self):
        self.classes: Dict[str, ClassDecl] = {}

    def load_dir(self, cfg_dir: Path):
        # Scan every .cfg in cfg_dir to build the name registry.
        # Each .cfg may pull in external .cfg files via @ include; those
        # included files' top-level classes are also registered (returned via
        # parse_cfg's includes list).
        for p in sorted(cfg_dir.glob("*.cfg")):
            c, includes = parse_cfg(p)
            all_classes = ([c] if c is not None else []) + includes
            for cls in all_classes:
                if cls.name in self.classes:
                    existing_src = self.classes[cls.name].source_file
                    new_src = cls.source_file
                    if Path(existing_src).resolve() == Path(new_src).resolve():
                        # Same source file (e.g. load_dir picked it up AND
                        # another file @-included it) -- treat as the same
                        # class and skip.
                        continue
                    raise RuntimeError(
                        f"class name conflict {cls.name}: {new_src}"
                        f" vs {existing_src}")
                self.classes[cls.name] = cls

    def get(self, name: str) -> ClassDecl:
        if name not in self.classes:
            raise KeyError(f"unknown class {name} (not found in cfg/)")
        return self.classes[name]


# ----------------------------- Code generation -----------------------------

# Scalar types that can be marked `rand`. Vector fields are NOT marked
# `rand` here (the SV side is left to handle that).
_SCALAR_RANDABLE = {"int", "int unsigned", "uint", "bit", "logic", "byte", "shortint", "longint"}

def _is_packed_type(elem: str) -> bool:
    """Returns True if the type string contains a [N:M] / [N:0] dimension,
    i.e. is a packed vector like 'bit [7:0]'.

    Packed vector field assignments MUST go through ssv_ato_packed to avoid
    ssv_atoi silently truncating to 32 bits.

    NOTE: UVM 1.2 has no uvm_field_*_hext macro. Packed vectors therefore
    also go through array_int / queue_int / uvm_field_int -- this only
    affects UVM's do_pack / do_compare / do_print infrastructure; the
    bit-level values stored in simulation are unaffected.
    """
    return '[' in elem

# uvm_field_* macro mapping: base type -> macro. UVM 1.2 has no _hext series,
# so packed vectors also go through _int.
def _uvm_field_macro(ftype: str, name: str) -> str:
    # Array / queue -> array_int / queue_int / array_string / queue_string.
    if _is_array(ftype):
        elem = _array_elem_type(ftype)
        elem_base = elem.split(' ')[0]
        is_q = _is_queue(ftype)
        if elem_base == "string":
            kw = "queue_string" if is_q else "array_string"
        elif elem_base == "real":
            kw = "queue_real" if is_q else "array_real"
        else:
            # Packed vector elements / plain int elements both use _int
            # (UVM 1.2 has no _hext macro).
            kw = "queue_int" if is_q else "array_int"
        return f"`uvm_field_{kw}({name}, UVM_DEFAULT)"
    base = ftype.split(' ')[0]
    if base == "string":
        return f"`uvm_field_string({name}, UVM_DEFAULT)"
    if base in ("real",):
        return f"`uvm_field_real({name}, UVM_DEFAULT)"
    # Packed vector / plain int scalar both use uvm_field_int.
    return f"`uvm_field_int({name}, UVM_DEFAULT)"


def _is_subobj_scalar_kind(field: FieldDecl) -> bool:
    """Return True for scalar types that can take a `rand` qualifier.
    We don't add `rand` to vector fields."""
    base = field.ftype.split(' ')[0]
    return base in _SCALAR_RANDABLE


def _field_assignment_stmt(f: FieldDecl) -> str:
    """Emit the type-aware '<field> = <expr>;' statement for an override
    string."""
    base = f.ftype.split(' ')[0]
    if base == "string":
        return f"{f.name} = ssv_object::ssv_unquote(value);"
    if base == "real":
        return f"{f.name} = value.atoreal();"
    if _is_packed_type(f.ftype):
        # Packed vector scalar -- ssv_ato_packed returns a 256-bit value;
        # SV truncates to the field width on assignment, so hex / bin
        # literals are preserved.
        return f"{f.name} = ssv_object::ssv_ato_packed(value);"
    # int / uint / bit / logic / byte / shortint / longint: type-aware helper.
    return f"{f.name} = ssv_object::ssv_atoi(value);"


def _queue_push_stmt(f: FieldDecl) -> str:
    """Emit '<field>.push_back(<expr>);' for a queue field."""
    elem = _array_elem_type(f.ftype)
    elem_base = elem.split(' ')[0]
    if elem_base == "string":
        return f"{f.name}.push_back(ssv_object::ssv_unquote(value));"
    if elem_base == "real":
        return f"{f.name}.push_back(value.atoreal());"
    if _is_packed_type(elem):
        return f"{f.name}.push_back(ssv_object::ssv_ato_packed(value));"
    return f"{f.name}.push_back(ssv_object::ssv_atoi(value));"


def _array_elem_setter_expr(f: FieldDecl) -> str:
    """Emit the right-hand-side expression (no LHS) for the
    'FIELD[idx] = <expr>;' form."""
    elem = _array_elem_type(f.ftype)
    elem_base = elem.split(' ')[0]
    if elem_base == "string":
        return "ssv_object::ssv_unquote(value)"
    if elem_base == "real":
        return "value.atoreal()"
    if _is_packed_type(elem):
        # Packed vector element -- ssv_ato_packed returns 256 bits and SV
        # truncates to the field width on assignment, so hex / bin literals
        # are preserved.
        return "ssv_object::ssv_ato_packed(value)"
    return "ssv_object::ssv_atoi(value)"


def gen_class_sv(c: ClassDecl, reg: CfgRegistry) -> str:
    """Generate the .sv source for one class."""
    lines: List[str] = []
    lines.append("// =============================================================================")
    lines.append(f"// Auto-generated from {os.path.basename(c.source_file)} -- DO NOT EDIT")
    lines.append(f"// Generated by tools/cfg2sv.py")
    lines.append("// =============================================================================")
    lines.append("")
    lines.append(f"class {c.name} extends ssv_object;")
    lines.append("")

    # Field declarations.
    for f in c.fields:
        if _is_array(f.ftype):
            # Array / queue: postfix dimension. We don't add `rand`
            # (mandatory for string; avoided for the others to keep things
            # simple).
            elem = _array_elem_type(f.ftype)
            dim = _array_dim(f.ftype)
            if f.value:
                lines.append(f"  {elem} {f.name} {dim} = {f.value};")
            else:
                lines.append(f"  {elem} {f.name} {dim};")
        else:
            decl = f.ftype
            rand_kw = "rand " if _is_subobj_scalar_kind(f) else ""
            if f.value:
                lines.append(f"  {rand_kw}{decl} {f.name} = {f.value};")
            else:
                lines.append(f"  {rand_kw}{decl} {f.name};")

    # Sub-object handle declarations.
    for s in c.sub_objects:
        lines.append(f"  {s.class_name} {s.inst_name};")

    if c.fields or c.sub_objects:
        lines.append("")

    # uvm_object_utils.
    lines.append("  `uvm_object_utils_begin(" + c.name + ")")
    for f in c.fields:
        lines.append("    " + _uvm_field_macro(f.ftype, f.name))
    for s in c.sub_objects:
        lines.append(f"    `uvm_field_object({s.inst_name}, UVM_DEFAULT)")
    lines.append("  `uvm_object_utils_end")
    lines.append("")

    # new(): create sub-objects and apply per-instance field overrides.
    lines.append(f"  function new(string name = \"{c.name}\");")
    lines.append("    super.new(name);")
    for s in c.sub_objects:
        try:
            reg.get(s.class_name)
        except KeyError:
            lines.append(f"    // WARNING: sub-object class {s.class_name} is not registered;"
                         f" construction may fail")
        lines.append(f"    {s.inst_name} = {s.class_name}::type_id::create(\"{s.inst_name}\");")
        for ov in s.overrides:
            lines.append(f"    {s.inst_name}.{ov.name} = {ov.value};")
    lines.append("  endfunction")
    lines.append("")

    # apply_field: turn an override string into a type-aware assignment.
    has_dyn_arr = any(_is_dynamic_array(f.ftype) for f in c.fields)
    if c.fields:
        lines.append("  function bit apply_field(string field_name, string value);")
        lines.append("    bit applied = 0;")
        lines.append("    case (field_name)")
        for f in c.fields:
            if _is_queue(f.ftype):
                # Queue: each occurrence in a .cmd pushes back once.
                lines.append(f"      \"{f.name}\": begin {_queue_push_stmt(f)} applied = 1; end")
            elif _is_dynamic_array(f.ftype):
                # Dynamic array: full-array replacement is NOT done via
                # apply_field; users should use FIELD.size / FIELD[N] in
                # .cmd. Fall through to apply_array_field below.
                pass
            else:
                lines.append(f"      \"{f.name}\": begin {_field_assignment_stmt(f)} applied = 1; end")
        lines.append("      default: ;")
        lines.append("    endcase")
        # Dynamic-array FIELD.size / FIELD[N] go through apply_array_field
        # (for field names that include a '.' or '[').
        if has_dyn_arr:
            lines.append("    if (!applied) applied = apply_array_field(field_name, value);")
        lines.append("    return applied;")
        lines.append("  endfunction")
    else:
        lines.append("  function bit apply_field(string field_name, string value);")
        lines.append("    return 0;")
        lines.append("  endfunction")

    lines.append("")

    # apply_array_field: handle 'FIELD.size' (resize) and 'FIELD[N]'
    # (write the Nth element, auto-grow if needed).
    if has_dyn_arr:
        lines.append("  // apply_array_field: handle the 'FIELD.size' (resize) and")
        lines.append("  // 'FIELD[N]' (write the Nth element, auto-grow) modifier forms")
        lines.append("  // for dynamic-array field names.")
        lines.append("  function bit apply_array_field(string field_name, string value);")
        lines.append("    bit applied = 0;")
        lines.append("    string base;")
        lines.append("    int    idx;")
        lines.append("")
        lines.append("    // 'FIELD[N]' form: write element by index.")
        lines.append("    if (ssv_object::ssv_match_array_idx(field_name, base, idx)) begin")
        lines.append("      case (base)")
        for f in c.fields:
            if not _is_dynamic_array(f.ftype):
                continue
            setter = _array_elem_setter_expr(f)
            lines.append(f"        \"{f.name}\": begin")
            lines.append(f"          if ({f.name}.size <= idx) {f.name} = new[idx+1];")
            lines.append(f"          {f.name}[idx] = {setter};")
            lines.append("          applied = 1;")
            lines.append("        end")
        lines.append("        default: ;")
        lines.append("      endcase")
        lines.append("    end")
        lines.append("    if (applied) return applied;")
        lines.append("")
        lines.append("    // 'FIELD.size' form: resize (old elements are discarded).")
        lines.append("    if (ssv_object::ssv_match_field_size(field_name, base)) begin")
        lines.append("      case (base)")
        for f in c.fields:
            if not _is_dynamic_array(f.ftype):
                continue
            lines.append(f"        \"{f.name}\": begin {f.name} = new[ssv_object::ssv_atoi(value)]; applied = 1; end")
        lines.append("        default: ;")
        lines.append("      endcase")
        lines.append("    end")
        lines.append("    return applied;")
        lines.append("  endfunction")
        lines.append("")

    # find_sub: return a sub-object handle by instance name.
    if c.sub_objects:
        lines.append("  function ssv_object find_sub(string inst_name);")
        lines.append("    case (inst_name)")
        for s in c.sub_objects:
            lines.append(f"      \"{s.inst_name}\": return {s.inst_name};")
        lines.append("      default: return null;")
        lines.append("    endcase")
        lines.append("  endfunction")
    else:
        lines.append("  function ssv_object find_sub(string inst_name);")
        lines.append("    return null;")
        lines.append("  endfunction")

    lines.append("")
    lines.append("endclass")
    lines.append("")
    return "\n".join(lines)


def gen_cfg_pkg(reg: CfgRegistry, cfg_dir: Path) -> Path:
    """Generate ssv_cfg_pkg.sv into the root cfg's directory, `include'ing
    every cfg class.

    Include path:
        - Class inside the cfg tree: relative-to-cfg_dir path (so the cfg
          tree can be copied wholesale into another project).
        - Class outside the cfg tree (pulled in via @<abs>/xxx.cfg):
          absolute path (works but is not portable).
    """
    pkg_path = cfg_dir / "ssv_cfg_pkg.sv"
    cfg_dir = cfg_dir.resolve()

    def _inc_path(cls: ClassDecl) -> str:
        """sv `include path: relative to cfg_dir if inside, absolute otherwise."""
        sv = Path(cls.source_file).with_suffix(".sv")
        try:
            return str(sv.relative_to(cfg_dir)).replace('\\', '/')
        except ValueError:
            return str(sv.resolve()).replace('\\', '/')

    lines: List[str] = []
    lines.append("// =============================================================================")
    lines.append("// Auto-generated cfg package -- DO NOT EDIT")
    lines.append("// Generated by tools/cfg2sv.py")
    lines.append("// =============================================================================")
    lines.append("")
    lines.append("`ifndef SSV_CFG_PKG_SV")
    lines.append("`define SSV_CFG_PKG_SV")
    lines.append("")
    lines.append("package ssv_cfg_pkg;")
    lines.append("")
    lines.append("  // cfg classes extend ssv_pkg::ssv_object")
    lines.append("  `include \"uvm_macros.svh\"")
    lines.append("  import uvm_pkg::*;")
    lines.append("  import ssv_pkg::*;")
    lines.append("")
    lines.append("  // One .sv per cfg class, sitting next to its .cfg source (so the")
    lines.append("  // .cfg + .sv pair can be copied together).")
    # Dependency-friendly order: dependents first, then "root" last.
    sorted_classes = sorted(reg.classes.values(), key=lambda c: (1 if "root" in c.name else 0, c.name))
    for cls in sorted_classes:
        lines.append(f"  `include \"{_inc_path(cls)}\"")
    lines.append("")
    lines.append("endpackage")
    lines.append("")
    lines.append("`endif // SSV_CFG_PKG_SV")
    pkg_path.write_text("\n".join(lines), encoding='utf-8')
    return pkg_path


# ----------------------------- all.cmd generation -----------------------------

def flatten_defaults(reg: CfgRegistry, root_name: str,
                     overrides_for: Dict[str, Dict[str, FieldDecl]] = None
                     ) -> List[Tuple[str, str]]:
    """
    Flatten the whole tree into (hierarchy, value) pairs.
    Hierarchy looks like "root.sub_a.FIELD".
    overrides_for: {class_name: {field_name: FieldDecl}} -- explicit overrides
    from the top-level cfg replace the class's own defaults.
    """
    overrides_for = overrides_for or {}

    def visit(c: ClassDecl, inst_path: str, out: List[Tuple[str, str]]):
        # Fields.
        for f in c.fields:
            value = f.value
            # If a class is overridden at an instantiation point, use the
            # override value instead. The algorithm walks top-down: start
            # with the class's own defaults, then substitute overrides as
            # they are encountered.
            hier = f"{inst_path}.{f.name}" if inst_path else f.name
            out.append((hier, value))
        for s in c.sub_objects:
            child_path = f"{inst_path}.{s.inst_name}" if inst_path else s.inst_name
            child_cls = reg.get(s.class_name)
            # Effective overrides for this instance come from the
            # sub-object block in the parent .cfg.
            ov_map = {ov.name: ov for ov in s.overrides}
            # Recurse into the sub-object to get its (hier, default_value)
            # list, then substitute any local overrides.
            sub_list: List[Tuple[str, str]] = []
            visit(child_cls, child_path, sub_list)
            for hier, val in sub_list:
                leaf = hier.split('.')[-1]
                if leaf in ov_map:
                    val = ov_map[leaf].value
                out.append((hier, val))

    root = reg.get(root_name)
    out: List[Tuple[str, str]] = []
    visit(root, root_name, out)
    return out


def gen_all_cmd(reg: CfgRegistry, root_name: str, path: Path):
    pairs = flatten_defaults(reg, root_name)
    lines: List[str] = ["# Auto-generated default cfg dump. Each line: ssv_cfg: <hierarchy> = <value>",
                        "# Generated by tools/cfg2sv.py",
                        ""]
    for hier, val in pairs:
        lines.append(f"ssv_cfg: {hier} = {val}")
    path.write_text("\n".join(lines) + "\n", encoding='utf-8')


# ----------------------------- Main entry -----------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cfg-dir", default="cfg",
                    help="Directory of .cfg files (the generated .sv,"
                         " ssv_cfg_pkg.sv, and all.cmd are also placed under"
                         " this tree).")
    ap.add_argument("--root", default="top.cfg",
                    help="Root .cfg filename (relative to --cfg-dir).")
    ap.add_argument("--root-class", default=None,
                    help="Root class name (default: taken from the root"
                         " .cfg's class declaration).")
    ap.add_argument("--all-cmd", default=None,
                    help="Path to write the default cfg dump. Default:"
                         " <root cfg dir>/all.cmd (alongside the root .cfg"
                         " to keep .cfg/.sv/all.cmd together). Leave empty"
                         " for default.")
    ap.add_argument("--file", default=None,
                    help="Convert only this single .cfg (relative to"
                         " --cfg-dir); do NOT regenerate ssv_cfg_pkg.sv or"
                         " all.cmd. Useful for incremental edits or"
                         " debugging a single cfg class.")
    args = ap.parse_args()

    proj_root = Path(__file__).resolve().parent.parent
    cfg_dir = (proj_root / args.cfg_dir).resolve()

    print(f"[cfg2sv] scanning {cfg_dir}")
    reg = CfgRegistry()
    reg.load_dir(cfg_dir)
    print(f"[cfg2sv] loaded classes: {sorted(reg.classes.keys())}")

    def _class_sv_path(cls: ClassDecl) -> Path:
        """Path of the .sv corresponding to a cfg class: same directory as
        its .cfg source, with the .sv extension and the class name as the
        base name."""
        return Path(cls.source_file).with_suffix(".sv")

    # === --file single-file mode: generate only the .sv for that one cfg.
    if args.file:
        cfg_path = cfg_dir / args.file
        if not cfg_path.is_file():
            print(f"[cfg2sv] --file: {cfg_path} not found or not a file", file=sys.stderr)
            sys.exit(1)
        target, target_includes = parse_cfg(cfg_path)
        if target is not None and target.name not in reg.classes:
            reg.classes[target.name] = target
        for cls in target_includes:
            if cls.name not in reg.classes:
                reg.classes[cls.name] = cls
        sv_path = _class_sv_path(target)
        sv_path.write_text(gen_class_sv(target, reg), encoding='utf-8')
        print(f"[cfg2sv] wrote {sv_path}")
        print(f"[cfg2sv] --file mode: ssv_cfg_pkg.sv and all.cmd were NOT"
              f" regenerated. Run cfg2sv.py without --file to integrate.")
        return

    # === Full mode.
    # Parse the root cfg (including its @ includes).
    root_path = cfg_dir / args.root
    if not root_path.exists():
        print(f"[cfg2sv] root cfg {root_path} not found", file=sys.stderr)
        sys.exit(1)
    root_decl, root_includes = parse_cfg(root_path)
    root_name = args.root_class or root_decl.name

    # The root may have pulled in extra classes via @; register them too
    # (load_dir already dedups via source_file when the same file is both
    # glob-picked and @-included).
    for cls in root_includes:
        if cls.name in reg.classes:
            existing_src = reg.classes[cls.name].source_file
            if Path(existing_src).resolve() == Path(cls.source_file).resolve():
                continue
            raise RuntimeError(
                f"class name conflict {cls.name}: {cls.source_file}"
                f" vs {existing_src}")
        reg.classes[cls.name] = cls

    # Generate one .sv per class into the same directory as its .cfg
    # (.cfg + .sv pair is self-contained and can be copied wholesale).
    for cls in reg.classes.values():
        sv_path = _class_sv_path(cls)
        sv_path.parent.mkdir(parents=True, exist_ok=True)
        sv_path.write_text(gen_class_sv(cls, reg), encoding='utf-8')
        print(f"[cfg2sv] wrote {sv_path}")

    # Generate the cfg package next to the root cfg (so the whole tree
    # stays self-contained for copy-out).
    pkg = gen_cfg_pkg(reg, root_path.parent)
    print(f"[cfg2sv] wrote {pkg}")

    # Generate all.cmd next to the root cfg by default.
    if args.all_cmd:
        all_cmd = (proj_root / args.all_cmd).resolve()
    else:
        all_cmd = root_path.parent / "all.cmd"
    gen_all_cmd(reg, root_name, all_cmd)
    print(f"[cfg2sv] wrote {all_cmd}")

    print("[cfg2sv] done.")


if __name__ == "__main__":
    main()
