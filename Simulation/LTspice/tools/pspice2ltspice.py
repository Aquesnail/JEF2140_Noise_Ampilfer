#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pspice2ltspice.py -- convert a TI / PSpice op-amp macro-model (.LIB) into a
netlist LTspice runs without complaint.

Typical use (TI "Green-Williams-Lis" models such as OPA161x, OPA1612-Q1,
OPA192, OPA1656, ...):

    python pspice2ltspice.py OPA161x.LIB -o OPA161x_LTspice.lib

What it rewrites
----------------
  G.. n+ n- VALUE={expr}          ->  B.. n+ n- I=expr      (PSpice VCCS -> LTspice B)
  E.. n+ n- VALUE={expr}          ->  B.. n+ n- V=expr      (PSpice VCVS -> LTspice B)
  G.. n+ n- TABLE {(x)} = (..)    ->  B.. n+ n- I=table(x, x1,y1, x2,y2, ...)
  .MODEL m VSWITCH(VON= VOFF= RON= ROFF=)
                                  ->  .MODEL m SW(VT=(VON+VOFF)/2 VH=VON-VOFF RON= ROFF=)
  .MODEL m RES (T_ABS=-273.15)    ->  dropped  (LTspice resistors take no model)
  R.. n1 n2 m value               ->  R.. n1 n2 value
  KF={PWR(FLW,0.5)/1E11}          ->  numeric KF (LTspice .model takes no {expr});
                                      the enclosing .SUBCKT PARAMS defaults are
                                      substituted before evaluating
  I../V.. n+ n- DC value          ->  I../V.. n+ n- value   (DC keyword dropped)
  trailing "+ ..." cards          ->  joined onto one line
  PARAMS: (empty)                 ->  removed

Everything else (topology, node names, values, subcircuit structure) is kept
verbatim, so the result can be diffed against the original file.

Exit status: 0 on success, 1 if a construct was found that the script could not
translate (details go to stderr and, with --report, a report file).
"""

import argparse
import math
import os
import re
import sys

# ---------------------------------------------------------------------------
# SPICE number handling
# ---------------------------------------------------------------------------

_SCALES = (
    ("MEG", 1e6), ("MIL", 25.4e-6), ("T", 1e12), ("G", 1e9), ("K", 1e3),
    ("M", 1e-3), ("U", 1e-6), ("N", 1e-9), ("P", 1e-12), ("F", 1e-15),
)

_NUM_RE = re.compile(r"^([+-]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][+-]?\d+)?)([A-Za-z]*)$")


def spice_num(tok):
    """Parse a SPICE value such as 10MV, 22.044F, 1E-3, 1551E4 into a float.

    Returns None when the token is not numeric."""
    m = _NUM_RE.match(tok.strip())
    if not m:
        return None
    val = float(m.group(1).replace("D", "E").replace("d", "e"))
    suffix = m.group(2).upper()
    if suffix:
        for tag, mul in _SCALES:
            if suffix.startswith(tag):
                val *= mul
                break
        # any other letters (V, A, Hz, ...) are meaningless suffixes: ignored
    return val


def fmt(val):
    """Format a float for a SPICE card, keeping enough digits."""
    if val == int(val) and abs(val) < 1e15:
        return "%d" % int(val)
    return "%.12g" % val


# ---------------------------------------------------------------------------
# Expression handling
# ---------------------------------------------------------------------------

_EXPR_FUNCS = {
    "abs": abs, "sqrt": math.sqrt, "exp": math.exp, "log": math.log,
    "ln": math.log, "log10": math.log10, "sin": math.sin, "cos": math.cos,
    "tan": math.tan, "min": min, "max": max, "int": int, "floor": math.floor,
    "ceil": math.ceil, "pow": pow, "pwrs": lambda a, b: math.copysign(abs(a) ** b, a),
    "pwr": lambda a, b: math.copysign(abs(a) ** b, a),
    "pi": math.pi,
}


def eval_expr(expr, params):
    """Evaluate a PSpice {..} expression with the enclosing subckt parameters.

    Raises ValueError when the expression uses anything we cannot resolve."""
    src = expr
    src = re.sub(r"\bPWR\b", "pwr", src, flags=re.I)
    src = re.sub(r"\bPWRS\b", "pwrs", src, flags=re.I)
    src = src.replace("^", "**")
    env = dict(_EXPR_FUNCS)
    env.update(params)
    try:
        return float(eval(src, {"__builtins__": {}}, env))  # noqa: S307 - restricted env
    except Exception as exc:  # noqa: BLE001
        raise ValueError("cannot evaluate {%s}: %s" % (express(expr), exc))


def express(s):
    return s.strip()


def brace_value(rest):
    """Return the {..} payload at the end of `rest`, or None."""
    rest = rest.strip()
    m = re.search(r"\{([^{}]*)\}\s*$", rest, re.S)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Card splitting
# ---------------------------------------------------------------------------

def split_cards(text):
    """Yield (lineno, card) with '+' continuation lines joined and inline
    comments removed (brace aware)."""
    raw = text.splitlines()
    cards = []
    cur = None
    start = 0
    in_brace = 0
    for idx, line in enumerate(raw, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if in_brace == 0 and stripped.startswith("*"):
            continue  # full-line comment
        cont = in_brace > 0 or stripped.startswith("+")
        body = stripped[1:] if stripped.startswith("+") else stripped
        body = strip_comment(body, in_brace)
        # keep brace-depth across the physical line
        in_brace = brace_depth_after(body, in_brace)
        if cont and cards:
            cards[-1] = (cards[-1][0], cards[-1][1].rstrip() + " " + body.strip())
        else:
            start = idx
            cards.append((start, body.strip()))
            if in_brace == 0:
                pass
    return cards


def strip_comment(body, in_brace):
    if in_brace:
        return body
    out = []
    depth = 0
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            break
        out.append(ch)
    return "".join(out)


def brace_depth_after(body, depth):
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
    return depth


# ---------------------------------------------------------------------------
# Converter
# ---------------------------------------------------------------------------

class Converter:
    def __init__(self):
        self.out = []
        self.notes = []      # what changed (one line per change)
        self.warnings = []
        self.res_models = set()
        self.params_stack = [{}]   # subckt parameter defaults

    # -- helpers ---------------------------------------------------------
    def params(self):
        merged = {}
        for d in self.params_stack:
            merged.update(d)
        return merged

    @staticmethod
    def fields(card):
        """Split a card into the leading tokens and remember nothing else."""
        return card.split()

    def head(self, card, count):
        """Return (tokens[:count], remainder) using whitespace boundaries."""
        toks = card.split(None, count)
        if len(toks) < count:
            return toks, ""
        return toks[:count], toks[count] if count < len(toks) else ""

    # -- card handlers ---------------------------------------------------
    def convert(self, card):
        first = card[0].upper()
        if first == ".":
            return self.directive(card)
        if first in ("R", "C", "L", "E", "G", "F", "H", "I", "V", "S", "D",
                     "Q", "M", "J", "X", "B", "K", "T", "W", "Z"):
            handler = getattr(self, "dev_" + first, None)
            return handler(card) if handler else card
        self.warnings.append("unknown card kept verbatim: %s" % card.strip())
        return card

    # -- dots ------------------------------------------------------------
    def directive(self, card):
        low = card.lower()
        if low.startswith(".subckt"):
            return self.do_subckt(card)
        if low.startswith(".ends"):
            if len(self.params_stack) > 1:
                self.params_stack.pop()
            return card
        if re.match(r"^\s*\.model\b", low):
            return self.do_model(card)
        if re.match(r"^\s*\.(lib|include)\b", low):
            self.warnings.append(
                "the file contains a .lib/.include card; LTspice resolves it "
                "relative to the schematic, check the path: %s" % card)
            return card
        return card

    def do_subckt(self, card):
        # .SUBCKT name p1 p2 ... [PARAMS: A=1 B=2]  -- the defaults are kept
        # (LTspice wants a parameter declared if an X card passes it) but the
        # list is normalised so comma separators cannot confuse LTspice.
        params = {}
        head = card
        m = re.search(r"\bPARAMS?\s*:\s*(.*)$", card, re.I | re.S)
        if m:
            declared = []
            for key, val in re.findall(r"([A-Za-z_]\w*)\s*=\s*([^\s,]+)", m.group(1)):
                n = spice_num(val)
                params[key.upper()] = n if n is not None else val
                declared.append("%s=%s" % (key, val))
            head = card[:m.start()].rstrip()
            if declared:
                head = head + " PARAMS: " + " ".join(declared)
        self.params_stack.append(params)
        return head

    def do_model(self, card):
        m = re.match(r"^\s*\.model\s+(\S+)\s+([A-Za-z_]\w*)\s*(.*)$", card, re.I | re.S)
        if not m:
            self.warnings.append("unparsed .model card: %s" % card)
            return card
        name, typ, rest = m.group(1), m.group(2), m.group(3)
        up = typ.upper()

        if up in ("VSWITCH", "SW"):
            return self.model_switch(name, rest)

        if up in ("RES", "R", "RESISTOR"):
            # LTspice does accept a semiconductor-resistor model, including
            # T_ABS.  TI uses .model R_NOISELESS RES(T_ABS=-273.15) to put its
            # model resistors at 0 K (no thermal noise); KEEPING it is what
            # makes an .noise analysis of the converted model correct.
            self.res_models.add(name.upper())
            self.notes.append(".model %s RES(...) kept (LTspice honours T_ABS)" % name)
            return ".model %s RES(%s)" % (name, rest.strip().strip("()")) if rest.strip() \
                else ".model %s RES" % name

        # substitute {expr} inside model parameters with numbers
        def repl(mm):
            body = mm.group(1).strip()
            if spice_num(body) is not None:
                return mm.group(0)
            try:
                return fmt(eval_expr(body, self.params()))
            except ValueError as exc:
                self.warnings.append("%s; leaving %s in .model %s for LTspice"
                                     % (exc, mm.group(0), name))
                return mm.group(0)

        rest = re.sub(r"\{([^{}]*)\}", repl, rest)
        return ".model %s %s(%s)" % (name, up, rest.strip().strip("()"))

    def model_switch(self, name, rest):
        vals = {}
        for key, val in re.findall(r"([A-Za-z_]\w*)\s*=\s*([^\s,()]+)", rest):
            n = spice_num(val)
            vals[key.upper()] = n if n is not None else val
        von = vals.get("VON", 0.0)
        voff = vals.get("VOFF", 0.0)
        ron = vals.get("RON", 1.0)
        roff = vals.get("ROFF", 1e12)
        vt = (von + voff) / 2.0
        vh = abs(von - voff)
        if vh <= 0:
            vh = 1e-6
            self.warnings.append(
                "%s: VON == VOFF, hysteresis set to 1uV to keep the solver smooth" % name)
        self.notes.append(
            ".model %s VSWITCH(VON=%s VOFF=%s) -> SW(VT=%s VH=%s RON=%s ROFF=%s)"
            % (name, fmt(von), fmt(voff), fmt(vt), fmt(vh), fmt(ron), fmt(roff)))
        return ".model %s SW(VT=%s VH=%s RON=%s ROFF=%s)" % (
            name, fmt(vt), fmt(vh), fmt(ron), fmt(roff))

    # -- devices ---------------------------------------------------------
    def dev_R(self, card):
        # Rname n1 n2 [model] value -- LTspice accepts the same form, and the
        # model reference carries the T_ABS =-273.15 (noiseless) trick, so the
        # card is kept verbatim.
        return card

    def dev_V(self, card):
        return self.drop_dc(card)

    dev_I = dev_V

    def drop_dc(self, card):
        toks = card.split()
        if len(toks) >= 5 and toks[3].upper() == "DC":
            self.notes.append("%s: 'DC' keyword dropped" % toks[0])
            return " ".join(toks[:3] + toks[4:])
        return card

    def _two_nodes(self, card):
        toks = card.split(None, 3)
        if len(toks) < 4:
            return None
        return toks[0], toks[1], toks[2], toks[3]

    def dev_E(self, card):
        return self.controlled(card, "V")

    def dev_G(self, card):
        return self.controlled(card, "I")

    def brace_params(self, expr, params):
        """Wrap subcircuit parameters in {} inside a behavioural expression.

        LTspice wants parameters braced inside B-source expressions, and a bare
        name such as DC or G is otherwise ambiguous."""
        if not params:
            return expr
        out = expr
        for name in sorted(params, key=len, reverse=True):
            pat = r"(?<![A-Za-z0-9_{}%~])" + re.escape(name) + r"(?![A-Za-z0-9_])(?!\s*\()"
            out = re.sub(pat, "{%s}" % name, out, flags=re.I)
        return out

    def controlled(self, card, kind):
        parts = self._two_nodes(card)
        if parts is None:
            return card
        name, n1, n2, rest = parts
        bname = "B" + name[1:]
        params = self.params()

        # TABLE {x} = (x1,y1) (x2,y2) ...
        m = re.match(r"TABLE\s*\{?\s*(.*?)\s*\}?\s*=\s*(.*)$", rest, re.I | re.S)
        if m:
            expr = m.group(1).strip()
            if expr.startswith("(") and expr.endswith(")"):
                expr = expr[1:-1].strip()
            expr = self.brace_params(expr, params)
            pairs = re.findall(r"\(([^()]*)\)", m.group(2))
            pts = []
            for pair in pairs:
                bits = [p.strip() for p in pair.split(",")]
                if len(bits) != 2:
                    self.warnings.append("%s: bad table row %r" % (name, pair))
                    continue
                pts.append("%s,%s" % (bits[0], bits[1]))
            self.notes.append("%s TABLE -> %s I=table(...) with %d points"
                              % (name, bname, len(pts)))
            if not pts:
                self.warnings.append("%s: empty TABLE, kept verbatim" % name)
                return card
            return "%s %s %s %s=table(%s,%s)" % (bname, n1, n2, kind, expr, ",".join(pts))

        # VALUE = {expr}
        m = re.match(r"VALUE\s*=\s*\{(.*)\}\s*$", rest, re.I | re.S)
        if m:
            expr = self.brace_params(m.group(1).strip(), params)
            self.notes.append("%s VALUE={..} -> %s %s=.." % (name, bname, kind))
            return "%s %s %s %s=%s" % (bname, n1, n2, kind, expr)

        # linear controlled source, keep
        return card

    def dev_B(self, card):
        return card

    def dev_X(self, card):
        # drop a dangling "PARAMS:" with no parameters
        out = re.sub(r"\s+PARAMS?\s*:\s*$", "", card, flags=re.I)
        if out != card:
            self.notes.append("%s: empty PARAMS: removed" % card.split()[0])
        return out

    def dev_S(self, card):
        return card

    def dev_H(self, card):
        return card

    def dev_D(self, card):
        return card

    def dev_F(self, card):
        return card

    # -- driver ----------------------------------------------------------
    def run(self, text):
        for _, card in split_cards(text):
            new = self.convert(card)
            if new:
                self.out.append(new.strip())
        return "\n".join(self.out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

HEADER = """\
* ===========================================================================
* {name}
* LTspice version, converted from the TI PSpice macro-model
*   source : {src}
*   tool   : pspice2ltspice.py
* Changes are listed in the companion README; the electrical intent is
* unchanged.  Use it with
*   .lib {libname}
* and an X-instance:
*   {usage}
* ===========================================================================
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", help="PSpice .LIB file to convert")
    ap.add_argument("-o", "--output", help="output .lib (default: <input>_LTspice.lib)")
    ap.add_argument("--top", help="subcircuit to name in the usage hint")
    ap.add_argument("--report", help="write a conversion report to this file")
    args = ap.parse_args(argv)

    with open(args.input, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()

    conv = Converter()
    body = conv.run(text)

    out = args.output
    if not out:
        root, _ = os.path.splitext(args.input)
        out = root + "_LTspice.lib"

    heads = [c for c in conv.out if c.lower().startswith(".subckt")]
    top = args.top or (heads[0].split()[1] if heads else "*")
    pins = []
    if heads:
        for tok in heads[0].split()[2:]:
            if tok.upper().startswith("PARAM"):
                break
            pins.append(tok)
    usage = "X1 %s%s%s" % (" ".join(pins), " " if pins else "", top)
    header = HEADER.format(name=os.path.basename(out),
                           src=os.path.basename(args.input),
                           libname=os.path.basename(out), usage=usage)

    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header + body)

    report = []
    report.append("source : %s" % os.path.abspath(args.input))
    report.append("output : %s" % os.path.abspath(out))
    report.append("cards  : %d" % len(conv.out))
    report.append("subckts: %s" % ", ".join(c.split()[1] for c in heads))
    report.append("")
    report.append("--- changes ---")
    report.extend("  " + n for n in conv.notes)
    report.append("")
    report.append("--- warnings ---")
    report.extend("  " + w for w in conv.warnings)
    txt = "\n".join(report) + "\n"
    print(txt)
    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)

    return 1 if conv.warnings else 0


if __name__ == "__main__":
    sys.exit(main())
