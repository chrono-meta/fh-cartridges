"""miniyaml.py — stdlib reader for a YAML subset (block/flow mappings and sequences, quoted and plain scalars,
| and > block scalars, comments). Anchors, aliases, tags, merge keys and several documents are refused, never
guessed. Duplicate keys are refused. Vendored unchanged from cart-ghaudit/scripts/gha_audit.py (same repository)."""
import re

class YamlError(ValueError):
    pass


class YamlUnsupported(Exception):
    pass


_INT = re.compile(r"^[-+]?(0|[1-9][0-9_]*|0[0-7_]+|0x[0-9a-fA-F_]+|0b[01_]+)$")
_FLOAT = re.compile(r"^[-+]?([0-9][0-9_]*)?\.[0-9_]*([eE][-+][0-9]+)?$|^[-+]?\.(inf|Inf|INF)$|^\.(nan|NaN|NAN)$")
_SEXA = re.compile(r"^[-+]?[1-9][0-9_]*(:[0-5]?[0-9])+$")
_NULL = {"", "~", "null", "Null", "NULL"}
_ESC = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
        "e": "\x1b", " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ", "P": " "}
_HEXLEN = {"x": 2, "u": 4, "U": 8}


def _plain(s):
    """Resolve a plain scalar: null, int, float, else the text. Booleans and timestamps stay text (rules compare
    text; ON / YES are names)."""
    if s in _NULL:
        return None
    if _SEXA.match(s):
        sign, t = (-1, s[1:]) if s[0] == "-" else (1, s.lstrip("+"))
        v = 0
        for part in t.replace("_", "").split(":"):
            v = v * 60 + int(part)
        return sign * v
    if _INT.match(s):
        t = s.replace("_", "")
        try:
            return int(t, 8) if re.match(r"^[-+]?0[0-7]+$", t) else int(t, 0)
        except ValueError:
            return s
    if _FLOAT.match(s) and re.search(r"[0-9]|inf|Inf|INF|nan|NaN|NAN", s):
        t = s.replace("_", "").lower()
        if t.lstrip("+-") in (".inf", ".nan"):
            return float(t.replace(".", ""))
        try:
            return float(t)
        except ValueError:
            return s
    return s


class MiniYaml:
    """Stdlib reader for the YAML that GitHub Actions workflows use: block mappings and sequences, flow [ ] { },
    plain / single- / double-quoted scalars, literal | and folded > block scalars, comments. Anything outside that
    (anchors, aliases, tags, merge keys, complex keys, directives, several documents) is refused as
    UNSUPPORTED-YAML rather than guessed. Duplicate keys are refused."""

    def __init__(self, text):
        if text.startswith("﻿"):
            text = text[1:]
        self.lines = text.split("\n")
        if self.lines and self.lines[-1] == "":
            self.lines.pop()  # the file's final line break ends the last line; it is not one more (empty) line
        self.i = 0

    # ---- helpers ------------------------------------------------------------------------------------------------
    def err(self, msg):
        raise YamlError("line %d: %s" % (self.i + 1, msg))

    @staticmethod
    def indent(line):
        n = len(line) - len(line.lstrip(" "))
        if line[n:n + 1] == "\t" and line.strip():
            raise YamlError("tab in indentation")
        return n

    def skip_blank(self):
        while self.i < len(self.lines):
            s = self.lines[self.i].strip()
            if s and not s.startswith("#"):
                return True
            self.i += 1
        return False

    @staticmethod
    def strip_comment(s):
        """Drop a trailing ` # comment` outside quotes (s has no leading space). A quote opens a quoted scalar only at
        the start of the value, or inside a flow collection after [ { , or : — a quote inside a plain scalar is text."""
        q, k = None, 0
        while k < len(s):
            c = s[k]
            if q == "'":
                if c == "'":
                    if s[k + 1:k + 2] == "'":
                        k += 2
                        continue
                    q = None
            elif q == '"':
                if c == "\\":
                    k += 2
                    continue
                if c == '"':
                    q = None
            elif c in "'\"" and _opens_quote(s, k):
                q = c
            elif c == "#" and (k == 0 or s[k - 1] in " \t"):
                return s[:k].rstrip()
            k += 1
        return s.rstrip()

    def check_supported(self, s):
        if s[:1] in ("&", "*", "!") or s.startswith("<<") or s.startswith("? ") or s == "?" or s[:1] in ("%", "@", "`"):
            raise YamlUnsupported("line %d: anchors, aliases, tags, merge keys, complex keys and reserved indicators "
                                  "are outside what this script reads: %r" % (self.i + 1, s[:40]))

    # ---- document -----------------------------------------------------------------------------------------------
    def document(self):
        if not self.skip_blank():
            return None
        first = self.lines[self.i].strip()
        if first.startswith("%"):
            raise YamlUnsupported("line %d: YAML directives are outside what this script reads" % (self.i + 1))
        if first == "---" or first.startswith("--- "):
            rest = self.strip_comment(first[3:].strip())
            if rest:
                raise YamlUnsupported("line %d: content on the `---` line is outside what this script reads" % (self.i + 1))
            self.i += 1
            if not self.skip_blank():
                return None
        if self.indent(self.lines[self.i]) != 0:
            self.err("document does not start at column 0")
        v = self.node(0)
        if self.skip_blank():
            s = self.lines[self.i].strip()
            if s == "---" or s.startswith("--- ") or s == "...":
                raise YamlUnsupported("line %d: more than one document (or `...`) — one workflow per file" % (self.i + 1))
            self.err("unexpected content (bad indentation?)")
        return v

    def node(self, n):
        """A block node whose first line (self.i) is at indent n."""
        line = self.lines[self.i]
        s = line.strip()
        self.check_supported(s)
        if s == "-" or s.startswith("- "):
            return self.seq(n)
        if self.key_split(s) is not None:
            return self.mapping(n)
        # a bare scalar or flow collection as the whole node
        v = self.inline_value(self.strip_comment(s), n - 1)
        return v

    # ---- block sequence -----------------------------------------------------------------------------------------
    def seq(self, n):
        out = []
        while self.skip_blank():
            line = self.lines[self.i]
            ind = self.indent(line)
            if ind < n:
                break
            if ind > n:
                self.err("bad indentation in a sequence")
            s = line.strip()
            if not (s == "-" or s.startswith("- ")):
                break
            rest = s[1:].lstrip(" ")
            if not rest or rest.startswith("#"):
                self.i += 1
                if self.skip_blank() and self.indent(self.lines[self.i]) > n:
                    out.append(self.node(self.indent(self.lines[self.i])))
                else:
                    out.append(None)
                continue
            col = len(line) - len(rest)
            self.lines[self.i] = " " * col + rest  # the item reads as a node starting at its own column
            out.append(self.node(col))
        return out

    # ---- block mapping ------------------------------------------------------------------------------------------
    def key_split(self, s):
        """(key, rest) if s starts a mapping entry, else None."""
        if s[:1] in "\"'":
            q = s[0]
            k = 1
            while k < len(s):
                if s[k] == "\\" and q == '"':
                    k += 2
                    continue
                if s[k] == q:
                    if q == "'" and s[k + 1:k + 2] == "'":
                        k += 2
                        continue
                    break
                k += 1
            if k >= len(s):
                return None
            after = s[k + 1:].lstrip(" ")
            if after == ":" or after.startswith(": ") or after.startswith(":\t"):
                return (self.quoted(s[:k + 1]), after[1:].strip())
            return None
        if s[0] in "[{#|>&*!" or s.startswith("- ") or s == "-":
            return None
        m = re.search(r":(\s|$)", s)
        if not m:
            return None
        head = s[:m.start()]
        if " #" in head or "\t#" in head:
            return None
        key = head.rstrip()
        self.check_supported(key)
        return (_plain(key), s[m.end():].strip())

    def mapping(self, n):
        out = {}
        while self.skip_blank():
            line = self.lines[self.i]
            ind = self.indent(line)
            if ind < n:
                break
            if ind > n:
                self.err("bad indentation in a mapping")
            s = line.strip()
            if s == "-" or s.startswith("- ") or (ind == 0 and (s in ("---", "...") or s.startswith("--- "))):
                break
            self.check_supported(s)
            kv = self.key_split(s)
            if kv is None:
                self.err("expected `key: value`")
            key, rest = kv
            try:
                hash(key)
            except TypeError:
                self.err("unhashable key")
            if key in out:
                self.err("duplicate key %r" % (key,))
            rest = self.strip_comment(rest)
            if rest:
                self.check_supported(rest)
            if not rest:
                self.i += 1
                if self.skip_blank():
                    nxt = self.lines[self.i]
                    ni = self.indent(nxt)
                    ns = nxt.strip()
                    if ni > n or (ni == n and (ns == "-" or ns.startswith("- "))):
                        out[key] = self.node(ni)
                        continue
                out[key] = None
                continue
            if rest[0] in "|>":
                out[key] = self.block_scalar(rest, n)
                continue
            out[key] = self.inline_value(rest, n)
        return out

    # ---- values on a line ---------------------------------------------------------------------------------------
    def inline_value(self, rest, n):
        """Value text starting on line self.i; may continue on following lines more indented than n."""
        if rest[:1] in "[{":
            text = rest
            while not self.balanced(text):
                self.i += 1
                if self.i >= len(self.lines):
                    self.err("unclosed flow collection")
                text += "\n" + self.lines[self.i]
            self.i += 1
            f = _Flow(text, self.i)
            v = f.value()
            f.ws()
            if f.k != len(f.t):
                self.err("text after a flow collection")
            return v
        if rest[:1] in "\"'":
            text = rest
            while not self.quote_closed(text):
                self.i += 1
                if self.i >= len(self.lines):
                    self.err("unclosed quoted scalar")
                text += "\n" + self.lines[self.i].strip()
            self.i += 1
            end = self.quote_end(text)
            tail = self.strip_comment(text[end + 1:].strip())
            if tail:
                self.err("text after a quoted scalar")
            return self.quoted(text[:end + 1])
        # plain scalar, possibly multi-line: a single break folds to a space, k blank lines become k newlines
        if re.search(r":(\s|$)", rest):
            self.err("mapping values are not allowed here")
        text, single = rest, True
        commented = self.strip_comment(self.lines[self.i].strip()) != self.lines[self.i].strip()
        self.i += 1
        while not commented and self.i < len(self.lines):
            j, blanks = self.i, 0
            while j < len(self.lines) and not self.lines[j].strip():
                j, blanks = j + 1, blanks + 1
            if j >= len(self.lines):
                break
            ln = self.lines[j]
            s = ln.strip()
            if self.indent(ln) <= n or s.startswith("#") or (ln[:3] in ("---", "...") and ln[3:4] in ("", " ", "\t")):
                break
            c = self.strip_comment(s)
            if re.search(r":(\s|$)", c) or c.startswith("- "):
                self.i = j
                self.err("mapping values are not allowed here")
            text += ("\n" * blanks) if blanks else " "
            text += c
            single = False
            self.i = j + 1
            if c != s:
                break
        return _plain(text) if single else text

    @staticmethod
    def quote_end(text):
        q, k = text[0], 1
        while k < len(text):
            if text[k] == "\\" and q == '"':
                k += 2
                continue
            if text[k] == q:
                if q == "'" and text[k + 1:k + 2] == "'":
                    k += 2
                    continue
                return k
            k += 1
        return -1

    def quote_closed(self, text):
        return self.quote_end(text) >= 0

    @staticmethod
    def balanced(text):
        depth, q, k = 0, None, 0
        while k < len(text):
            c = text[k]
            if q == "'":
                if c == "'":
                    if text[k + 1:k + 2] == "'":
                        k += 2
                        continue
                    q = None
            elif q == '"':
                if c == "\\":
                    k += 2
                    continue
                if c == '"':
                    q = None
            elif c in "'\"" and _opens_quote(text, k):
                q = c
            elif c == "#" and (k == 0 or text[k - 1] in " \t\n"):
                while k < len(text) and text[k] != "\n":
                    k += 1
                continue
            elif c in "[{":
                depth += 1
            elif c in "]}":
                depth -= 1
                if depth == 0:
                    return True
            k += 1
        return False

    def quoted(self, tok):
        q, body = tok[0], tok[1:-1]
        if q == "'":
            return _fold_lines(body).replace("''", "'")
        out, k = [], 0
        body = _fold_lines(body, escape=True)
        while k < len(body):
            c = body[k]
            if c != "\\":
                out.append(c)
                k += 1
                continue
            e = body[k + 1:k + 2]
            if e in _ESC:
                out.append(_ESC[e])
                k += 2
            elif e in _HEXLEN:
                h = body[k + 2:k + 2 + _HEXLEN[e]]
                if len(h) != _HEXLEN[e] or not re.match(r"^[0-9a-fA-F]+$", h):
                    raise YamlError("bad escape \\%s" % e)
                out.append(chr(int(h, 16)))
                k += 2 + _HEXLEN[e]
            elif e == "\n":
                k += 2
                while k < len(body) and body[k] in " \t":
                    k += 1
            else:
                raise YamlError("unknown escape \\%s in a double-quoted scalar" % e)
        return "".join(out)

    def block_scalar(self, header, n):
        h = self.strip_comment(header)
        m = re.match(r"^([|>])([-+]?)([1-9]?)([-+]?)$", h)
        if not m or (m.group(2) and m.group(4)):
            self.err("bad block scalar header %r" % header)
        style, chomp, explicit = m.group(1), m.group(2) or m.group(4), m.group(3)
        self.i += 1
        raw = []
        while self.i < len(self.lines):
            ln = self.lines[self.i]
            if ln.strip() and self.indent(ln) <= n:
                break
            raw.append(ln)
            self.i += 1
        # content indent
        if explicit:
            ci = n + int(explicit) if n >= 0 else int(explicit)
        else:
            ci = None
            for ln in raw:
                if ln.strip():
                    ci = len(ln) - len(ln.lstrip(" "))
                    break
            if ci is None:
                ci = n + 1
        for ln in raw:
            if ln.strip():
                break
            if len(ln) > ci:
                raise YamlError("leading empty line of a block scalar is more indented than its content")
        body = []
        for ln in raw:
            if ln.strip():
                if len(ln) - len(ln.lstrip(" ")) < ci:
                    raise YamlError("block scalar line less indented than its first line")
                body.append(ln[ci:])
            else:
                body.append(ln[ci:] if len(ln) > ci else "")
        # trailing blank lines
        k = len(body)
        while k > 0 and body[k - 1] == "":
            k -= 1
        content, trail = body[:k], len(body) - k
        if style == "|":
            text = "\n".join(content)
        else:
            text, prev, blanks = "", None, 0
            for ln in content:
                if ln == "":
                    blanks += 1
                    continue
                if prev is None:
                    text = "\n" * blanks + ln
                elif not prev.startswith((" ", "\t")) and not ln.startswith((" ", "\t")):
                    text += ("\n" * blanks if blanks else " ") + ln
                else:
                    text += "\n" + "\n" * blanks + ln
                prev, blanks = ln, 0
        if not content:
            return "" if chomp != "+" else "\n" * trail
        if chomp == "-":
            return text
        if chomp == "+":
            return text + "\n" + "\n" * trail
        return text + "\n"


def _opens_quote(s, k):
    if k == 0:
        return True
    if s[:1] not in "[{":
        return False
    j = k - 1
    while j >= 0 and s[j] in " \t\n":
        j -= 1
    return j >= 0 and s[j] in "[{,:"


def _fold_lines(body, escape=False):
    """Line folding inside a multi-line quoted scalar: a single line break becomes a space, n breaks become n-1."""
    if "\n" not in body:
        return body
    lines = body.split("\n")
    out = lines[0].rstrip(" \t") if not (escape and lines[0].endswith("\\")) else lines[0]
    blanks = 0
    for idx, ln in enumerate(lines[1:], 1):
        s = ln.strip(" \t")
        if not s and idx < len(lines) - 1:
            blanks += 1
            continue
        if escape and out.endswith("\\") and not out.endswith("\\\\"):
            out = out + "\n" + s
        else:
            out += ("\n" * blanks) if blanks else " "
            out += s
        blanks = 0
    return out


class _Flow:
    def __init__(self, text, line):
        self.t, self.k, self.line = text, 0, line

    def err(self, msg):
        raise YamlError("line %d: %s" % (self.line, msg))

    def ws(self):
        while self.k < len(self.t):
            c = self.t[self.k]
            if c in " \t\n":
                self.k += 1
            elif c == "#" and (self.k == 0 or self.t[self.k - 1] in " \t\n"):
                while self.k < len(self.t) and self.t[self.k] != "\n":
                    self.k += 1
            else:
                break

    def value(self):
        self.ws()
        c = self.t[self.k:self.k + 1]
        if c == "[":
            return self.seq()
        if c == "{":
            return self.mapping()
        if c in ("'", '"'):
            end = MiniYaml.quote_end(self.t[self.k:])
            if end < 0:
                self.err("unclosed quote in a flow collection")
            tok = self.t[self.k:self.k + end + 1]
            self.k += end + 1
            return _quoted(tok)
        if c in ("&", "*", "!", "?", "%", "@", "`") or self.t.startswith("<<", self.k):
            raise YamlUnsupported("line %d: anchors, aliases, tags, merge keys or complex keys inside a flow collection "
                                  "are outside what this script reads" % self.line)
        a = self.k
        while self.k < len(self.t):
            ch = self.t[self.k]
            if ch in ",[]{}":
                break
            if ch == ":" and (self.k + 1 >= len(self.t) or self.t[self.k + 1] in " ,[]{}"):
                break
            if ch == "#" and self.t[self.k - 1:self.k] in (" ", "\t", "\n"):
                break
            self.k += 1
        tok = self.t[a:self.k].strip(" \n")
        if not tok:
            self.err("empty entry in a flow collection")
        if "\t" in tok:
            self.err("tab inside a plain scalar in a flow collection")
        return _plain(_fold_lines(tok))

    def seq(self):
        self.k += 1
        out = []
        while True:
            self.ws()
            if self.t[self.k:self.k + 1] == "]":
                self.k += 1
                return out
            v = self.value()
            self.ws()
            if self.t[self.k:self.k + 1] == ":":
                self.err("single-pair mappings inside [ ] are outside what this script reads")
            out.append(v)
            self.ws()
            c = self.t[self.k:self.k + 1]
            if c == ",":
                self.k += 1
            elif c != "]":
                self.err("expected , or ] in a flow sequence")

    def mapping(self):
        self.k += 1
        out = {}
        while True:
            self.ws()
            if self.t[self.k:self.k + 1] == "}":
                self.k += 1
                return out
            key = self.value()
            self.ws()
            if self.t[self.k:self.k + 1] == ":":
                self.k += 1
                self.ws()
                val = None if self.t[self.k:self.k + 1] in (",", "}") else self.value()
            else:
                val = None
            try:
                hash(key)
            except TypeError:
                self.err("unhashable key")
            if key in out:
                self.err("duplicate key %r" % (key,))
            out[key] = val
            self.ws()
            c = self.t[self.k:self.k + 1]
            if c == ",":
                self.k += 1
            elif c != "}":
                self.err("expected , or } in a flow mapping")


def _quoted(tok):
    return MiniYaml.quoted(MiniYaml.__new__(MiniYaml), tok)


def load_yaml(text):
    return MiniYaml(text).document()
