# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Rules for values written to deployment.yaml or a blueprint copy."""

import json
import re

from .errors import ToolError

# deployment_name must be a valid GCP label value (gcluster checks this too).
NAME_RE = re.compile(r"^[a-z][-_a-z0-9]{0,62}$")
ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")  # var names
MODULE_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")  # as in templates, e.g. lustre-gcp
ZONE_RE = re.compile(r"^[a-z]+-[a-z]+[0-9]+-[a-z]$")
VAR_REF_RE = re.compile(r"^\$\(vars\.([a-z0-9_]+)\)$")
VAR_REF_ANY_RE = re.compile(r"\$\(vars\.([a-z0-9_]+)\)")
# A module output, e.g. $(private_service_access.cidr_range).
MODULE_REF_ANY_RE = re.compile(r"\$\(([a-z][a-z0-9_-]*)\.([a-z0-9_]+)\)")
SCALAR_TYPES = ("string", "number", "bool")
# Expression syntax, remote sources and multi-line values could smuggle
# behaviour into the blueprint rather than set a value.
_FORBIDDEN_IN_STRINGS = ("$(", "((", "git::", "http://", "https://", "\n")
_MAX_STRING = 256


def check_value(name, declared, value, refs=()):
    """refs: var names that string values may reference as $(vars.<name>),
    e.g. `$(vars.deployment_name)-scratch`. Any other expression is rejected."""
    if declared == "bool":
        ok = isinstance(value, bool)
    elif declared == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif declared in ("string", "expression"):  # an expression default can be replaced by a literal
        ok = isinstance(value, str) and len(value) <= _MAX_STRING
    elif declared == "list":
        ok = isinstance(value, list) and all(
            isinstance(v, (str, int, float, bool)) for v in value
        )
    else:
        raise ToolError(f"{name!r} has type {declared!r}; not overridable")
    if not ok:
        raise ToolError(f"{name!r} must be a {declared}")
    for s in value if isinstance(value, list) else [value]:
        if not isinstance(s, str):
            continue
        for ref in VAR_REF_ANY_RE.findall(s):
            if ref not in refs:
                raise ToolError(f"{name!r} references unknown or disallowed variable {ref!r}")
        if any(t in VAR_REF_ANY_RE.sub("", s) for t in _FORBIDDEN_IN_STRINGS):
            raise ToolError(f"{name!r} contains a forbidden sequence")


def check_input_value(label, info, value, refs=()):
    """Type plus the form-checkable rules gcluster explain reports. Values
    that reference vars are only checked by gcluster, after expansion."""
    check_value(label, info["type"], value, refs)
    if isinstance(value, str) and VAR_REF_ANY_RE.search(value):
        return
    c = constraints(info)
    allowed = c.get("allowed_values")
    if allowed and value is not None:
        fold = str.lower if c.get("case_insensitive") else str
        if fold(str(value)) not in {fold(str(v)) for v in allowed}:
            raise ToolError(f"{label} must be one of {allowed}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        low, high = c.get("min"), c.get("max")
        if low is not None and (value <= low if c.get("min_exclusive") else value < low):
            raise ToolError(f"{label} must be {'more than' if c.get('min_exclusive') else 'at least'} {low}")
        if high is not None and (value >= high if c.get("max_exclusive") else value > high):
            raise ToolError(f"{label} must be {'less than' if c.get('max_exclusive') else 'at most'} {high}")
    if isinstance(value, str) and c.get("pattern") and not re.search(c["pattern"], value):
        raise ToolError(f"{label} must match {c['pattern']}")


def constraints(info):
    """The limits `gcluster explain` reports for a module input (its
    `constraints`: allowed_values with case_insensitive, min / max with
    min_exclusive / max_exclusive, pattern), or {}. Every value Terraform
    and gcluster accept meets them; other rules are messages in
    `validations`, checked by gcluster expand."""
    return info.get("constraints") or {}


def default_value(var):
    """Declared default (explain's JSON string) as a Python value, or None."""
    try:
        return json.loads(var["default"])
    except (KeyError, ValueError):
        return None


_SHAPES = {"list": list, "set": list, "tuple": list, "object": dict, "map": dict}


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


_TYPE_TOKEN_RE = re.compile(r"\s*([a-z_][a-z0-9_]*|[(){}\[\],=])")


def structured_type(info):
    """The parsed type of a module input whose value is a list, set, map or
    object (explain's `type`), or None for scalars and `any`."""
    t = parse_type(info["type"]) if info.get("type") else ("any",)
    return t if t[0] not in ("string", "number", "bool", "any") else None


def parse_type(expr):
    """A Terraform type constraint as `gcluster explain` reports it (an
    input's `type`), as nested tuples: ("string",), ("list", t), ("map", t),
    ("set", t), ("tuple", [t...]), ("object", {name: (t, optional)}),
    ("any",). A bare list, set or map has elements of any type; a bare
    object (no attributes listed) is any."""
    tokens = _TYPE_TOKEN_RE.findall(expr)
    pos = 0

    def take(expected=None):
        nonlocal pos
        tok = tokens[pos] if pos < len(tokens) else None
        if tok is None or (expected and tok != expected):
            raise ValueError(f"bad type expression {expr!r}")
        pos += 1
        return tok

    def parse():
        name = take()
        if name in ("string", "number", "bool", "any"):
            return (name,)
        if tokens[pos:pos + 1] != ["("]:  # bare: elements (or attributes) of any type
            if name in ("list", "set", "map"):
                return (name, ("any",))
            if name == "object":
                return ("any",)
        take("(")
        if name in ("list", "set", "map"):
            t = (name, parse())
        elif name == "tuple":
            take("[")
            elems = [parse()]
            while tokens[pos] == ",":
                take(",")
                elems.append(parse())
            take("]")
            t = ("tuple", elems)
        elif name == "object":
            take("{")
            attrs = {}
            while tokens[pos] != "}":
                attr = take()
                take("=")
                optional = tokens[pos] == "optional"
                if optional:
                    take("optional")
                    take("(")
                attrs[attr] = (parse(), optional)
                if optional:
                    take(")")
                if tokens[pos] == ",":
                    take(",")
            take("}")
            t = ("object", attrs)
        else:
            raise ValueError(f"unknown type {name!r} in {expr!r}")
        take(")")
        return t

    return parse()


def check_type(label, t, value):
    """value against a parsed type: the shape, unknown object attributes and
    missing required ones. Strings with $(...) references are left to
    gcluster (their value is not known here); null is allowed anywhere."""
    kind = t[0]
    if value is None or kind == "any" or (isinstance(value, str) and "$(" in value):
        return
    if kind == "string":
        ok = isinstance(value, (str, int, float, bool))  # Terraform converts primitives
    elif kind == "number":
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif kind == "bool":
        ok = isinstance(value, bool)
    elif kind in ("list", "set", "tuple"):
        ok = isinstance(value, list) and (kind != "tuple" or len(value) == len(t[1]))
    else:
        ok = isinstance(value, dict)
    if not ok:
        raise ToolError(f"{label} must be a {kind}, not {type(value).__name__}")
    if kind in ("list", "set"):
        for i, v in enumerate(value):
            check_type(f"{label}[{i}]", t[1], v)
    elif kind == "tuple":
        for i, (et, v) in enumerate(zip(t[1], value)):
            check_type(f"{label}[{i}]", et, v)
    elif kind == "map":
        for k, v in value.items():
            check_type(f"{label}.{k}", t[1], v)
    elif kind == "object":
        attrs = t[1]
        unknown = sorted(set(value) - set(attrs))
        if unknown:
            raise ToolError(f"{label} has unknown attribute(s) {unknown}; allowed: {sorted(attrs)}")
        missing = sorted(a for a, (_, optional) in attrs.items() if not optional and a not in value)
        if missing:
            raise ToolError(f"{label} is missing required attribute(s) {missing}")
        for a, v in value.items():
            check_type(f"{label}.{a}", attrs[a][0], v)


# The gcluster expressions values may use beyond plain references: these
# functions, over references to the blueprint's own module outputs and
# declared vars only (as the examples combine startup scripts and lists).
EXPRESSION_FUNCTIONS = ("concat", "flatten", "merge")
_EXPR_RE = re.compile(r"^\$\((.*)\)$")  # one line only
_EXPR_TOKEN_RE = re.compile(r"[ \t]+|[\[\](),]|(?P<fn>[a-z]+)\(|(?P<ref>[a-z][a-z0-9_-]*)\.(?P<attr>[a-z0-9_]+)")


def whole_reference(value, refs=(), modules=()):
    """True when value is exactly one reference or allowed expression:
    $(vars.<declared>), $(<module>.<output>), or concat/flatten/merge over
    such references (lists and nesting allowed). Raises ToolError naming
    what is not allowed; False when value is not of that form at all."""
    m = _EXPR_RE.match(value) if isinstance(value, str) else None
    if not m:
        return False
    body, pos, seen = m.group(1), 0, set()
    while pos < len(body):
        t = _EXPR_TOKEN_RE.match(body, pos)
        if not t:
            raise ToolError(f"{value[:60]!r}: only {', '.join(EXPRESSION_FUNCTIONS)} over references to this "
                            "blueprint's modules and vars are allowed in expressions")
        if t.group("fn") and t.group("fn") not in EXPRESSION_FUNCTIONS:
            raise ToolError(f"{value[:60]!r}: function {t.group('fn')!r} is not allowed; use "
                            f"{', '.join(EXPRESSION_FUNCTIONS)}")
        if t.group("ref"):
            ref, attr = t.group("ref"), t.group("attr")
            if ref == "vars" and attr not in refs:
                raise ToolError(f"{value[:60]!r} references unknown or disallowed variable {attr!r}")
            if ref != "vars" and ref not in modules:
                raise ToolError(f"{value[:60]!r} references {ref!r}, which is not a module of this blueprint")
            if (ref, attr) in seen:  # gcluster cannot expand a repeated reference in one expression
                raise ToolError(f"{value[:60]!r} references {ref}.{attr} twice")
            seen.add((ref, attr))
        pos = t.end()
    return True


def check_module_value(label, info, value, refs=(), modules=()):
    """A value for a module input of any type: the declared shape, the rules
    gcluster explain reports, and no expressions, URLs or multi-line text
    in any string except references to the given vars ($(vars.<ref>)) and
    to outputs of the given modules ($(<module>.<output>); gcluster expand
    checks the output exists and its type). A whole value may also be one of
    the allowed expressions (see whole_reference). "dynamic" accepts any
    shape."""
    if whole_reference(value, refs, modules):
        return  # its type is only known once gcluster expands it
    if info["type"] in SCALAR_TYPES and not (isinstance(value, str) and MODULE_REF_ANY_RE.search(value)):
        check_input_value(label, info, value, refs)
        return
    shape = _SHAPES.get(info["type"].split("(")[0])
    if shape and not isinstance(value, shape):
        raise ToolError(f"{label} must be a {info['type']}")
    for s in _strings(value):
        if whole_reference(s, refs, modules):
            continue
        for ref in VAR_REF_ANY_RE.findall(s):
            if ref not in refs:
                raise ToolError(f"{label} references unknown or disallowed variable {ref!r}")
        for mod, _ in MODULE_REF_ANY_RE.findall(VAR_REF_ANY_RE.sub("", s)):
            if mod not in modules:
                raise ToolError(f"{label} references {mod!r}, which is not a module of this blueprint")
        rest = MODULE_REF_ANY_RE.sub("", VAR_REF_ANY_RE.sub("", s))
        if len(s) > _MAX_STRING or any(t in rest for t in _FORBIDDEN_IN_STRINGS):
            raise ToolError(f"{label}: {s[:40]!r} is too long or contains an expression, URL or line break")
    t = structured_type(info)
    if t:
        check_type(label, t, value)
