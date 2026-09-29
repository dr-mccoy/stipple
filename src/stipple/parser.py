from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass

from .model import (
    Alignment,
    Diagram,
    DiagramError,
    Edge,
    Endpoint,
    Location,
    Node,
    Placement,
    Port,
)

_TOKEN = re.compile(
    r"(?P<space>[^\S\n]+)|(?P<comment>\#[^\n]*)|(?P<newline>\n|;)"
    r"|(?P<arrow>->|--)|(?P<number>-?(?:\d+(?:\.\d+)?|\.\d+))"
    r'|(?P<string>"(?:[^"\\\n]|\\[^\n])*")'
    r"|(?P<word>[A-Za-z_][A-Za-z_0-9]*(?:-[A-Za-z_0-9]+)*)"
    r"|(?P<punct>[{}\[\]=,.()])"
)
SIDES = {"north", "south", "east", "west"}
KINDS = {"box", "text", "junction", "resistor", "capacitor"}
MAX_SOURCE_CHARACTERS = 1_000_000


@dataclass(frozen=True)
class Token:
    kind: str
    value: str
    location: Location


def lex(source: str, filename: str) -> list[Token]:
    if len(source) > MAX_SOURCE_CHARACTERS:
        raise DiagramError("source exceeds the one million character limit")
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    lines = source.split("\n")
    tokens = []
    offset, line, column = 0, 1, 1
    while offset < len(source):
        loc = Location(filename, line, column, lines[line - 1])
        match = _TOKEN.match(source, offset)
        if not match:
            raise DiagramError(f"unexpected character {source[offset]!r}", loc)
        value = match.group()
        kind = match.lastgroup
        if kind not in {"space", "comment"}:
            tokens.append(Token(kind, value, loc))
        offset = match.end()
        if value == "\n":
            line, column = line + 1, 1
        else:
            column += len(value)
    tokens.append(Token("eof", "", Location(filename, line, column, lines[line - 1])))
    return tokens


class Parser:
    def __init__(self, source: str, filename: str):
        self.tokens = lex(source, filename)
        self.index = 0
        self.diagram = Diagram()

    @property
    def token(self) -> Token:
        return self.tokens[self.index]

    def pop(self) -> Token:
        token = self.token
        if token.kind != "eof":
            self.index += 1
        return token

    def accept(self, value: str) -> bool:
        if self.token.value == value:
            self.pop()
            return True
        return False

    def expect(self, value: str) -> Token:
        if self.token.value != value:
            self.fail(f"expected {value!r}, found {self.token.value or 'end of input'!r}")
        return self.pop()

    def fail(self, message: str, token: Token | None = None):
        raise DiagramError(message, (token or self.token).location)

    def word(self) -> str:
        if self.token.kind != "word":
            self.fail("expected an identifier")
        return self.pop().value

    def number(self) -> float:
        token = self.token
        if token.kind != "number":
            self.fail("expected a number")
        number = float(self.pop().value)
        if not -100_000 <= number <= 100_000:
            self.fail("number must be finite and between -100000 and 100000", token)
        return number

    def string(self) -> str:
        token = self.token
        if token.kind != "string":
            self.fail("expected a quoted string")
        try:
            value = unicodedata.normalize("NFC", json.loads(self.pop().value))
        except ValueError:
            self.fail("invalid string escape; use JSON string escapes", token)
        if len(value) > 8000 or any(
            (ord(c) < 32 and c != "\n") or 0xD800 <= ord(c) <= 0xDFFF or ord(c) in {0xFFFE, 0xFFFF}
            for c in value
        ):
            self.fail("text must be valid XML text of at most 8000 characters", token)
        return value

    def breaks(self):
        while self.token.kind == "newline":
            self.pop()

    def endpoint(self) -> Endpoint:
        node = self.word()
        port = self.word() if self.accept(".") else None
        return Endpoint(node, port)

    def attributes(self, allowed: dict[str, type]) -> dict:
        attrs = {}
        if not self.accept("["):
            return attrs
        self.breaks()
        while not self.accept("]"):
            token = self.token
            name = self.word()
            if name not in allowed:
                self.fail(f"unknown attribute {name!r}; choose from {', '.join(allowed)}", token)
            if name in attrs:
                self.fail(f"duplicate attribute {name!r}", token)
            self.expect("=")
            kind = allowed[name]
            if kind is float:
                value = self.number()
                if value <= 0:
                    self.fail(f"{name} must be greater than zero", token)
            elif kind is bool:
                boolean = self.word()
                if boolean not in {"true", "false"}:
                    self.fail(f"{name} must be true or false", token)
                value = boolean == "true"
            else:
                value = self.string() if self.token.kind == "string" else self.word()
            attrs[name] = value
            self.breaks()
            if self.accept("]"):
                break
            self.expect(",")
            self.breaks()
        return attrs

    def parse(self) -> Diagram:
        self.breaks()
        self.expect("diagram")
        if self.token.kind == "string":
            self.diagram.title = self.string()
        self.expect("{")
        self.breaks()
        settings = set()
        while not self.accept("}"):
            start = self.token
            keyword = self.word()
            if keyword in {"direction", "gap", "font-size", "description", "style"}:
                if keyword in settings:
                    self.fail(f"duplicate setting {keyword!r}", start)
                settings.add(keyword)
                if keyword == "direction":
                    self.diagram.direction = self.word()
                    if self.diagram.direction not in {"down", "right"}:
                        self.fail("direction must be down or right", start)
                elif keyword in {"gap", "font-size"}:
                    value = self.number()
                    minimum = 28 if keyword == "gap" else 6
                    maximum = 1000 if keyword == "gap" else 96
                    if not minimum <= value <= maximum:
                        self.fail(f"{keyword} must be between {minimum} and {maximum}", start)
                    setattr(self.diagram, keyword.replace("-", "_"), value)
                elif keyword == "description":
                    self.diagram.description = self.string()
                elif self.word() != "classic":
                    self.fail("the available style is classic", start)
            elif keyword == "place":
                node = self.word()
                relation = self.word()
                if relation == "at":
                    self.expect("(")
                    x = self.number()
                    self.expect(",")
                    y = self.number()
                    self.expect(")")
                    placement = Placement(node, relation, None, (x, y), start.location)
                elif relation in {"below", "above", "left", "right"}:
                    reference = self.word()
                    gap = self.number() if self.accept("gap") else None
                    if gap is not None and gap < 0:
                        self.fail("placement gap cannot be negative", start)
                    placement = Placement(
                        node, relation, reference, () if gap is None else (gap,), start.location
                    )
                else:
                    self.fail("expected at, below, above, left, or right", start)
                self.diagram.placements.append(placement)
            elif keyword == "align":
                anchor = self.word()
                if anchor not in {"left", "right", "top", "bottom", "center-x", "center-y"}:
                    self.fail("unknown alignment anchor", start)
                names = [self.word(), self.word()]
                while self.token.kind == "word":
                    names.append(self.word())
                self.diagram.alignments.append(Alignment(tuple(names), anchor, start.location))
            elif keyword == "port":
                endpoint = self.endpoint()
                if endpoint.port is None or endpoint.port in SIDES:
                    self.fail("use a named port such as decoder.input", start)
                side = self.word()
                fraction = self.number() if self.token.kind == "number" else 0.5
                if side not in SIDES or not 0 <= fraction <= 1:
                    self.fail("port needs a side and a fraction from 0 to 1", start)
                node = self.diagram.nodes.get(endpoint.node)
                if node is None:
                    self.fail("declare the node before its ports", start)
                if node.kind != "box":
                    self.fail("only boxes support named ports", start)
                if endpoint.port in node.ports:
                    self.fail(f"duplicate port {endpoint.port!r}", start)
                node.ports[endpoint.port] = Port(side, fraction)
            elif self.accept("="):
                if keyword in self.diagram.nodes:
                    self.fail(f"duplicate node {keyword!r}", start)
                kind = self.word()
                if kind not in KINDS:
                    self.fail(
                        f"unknown shape {kind!r}; choose from {', '.join(sorted(KINDS))}", start
                    )
                label = self.string() if kind != "junction" else ""
                attrs = self.attributes(
                    {
                        "width": float,
                        "height": float,
                        "shadow": bool,
                        "orientation": str,
                    }
                )
                if "orientation" in attrs and (
                    kind not in {"resistor", "capacitor"}
                    or attrs["orientation"] not in {"right", "down"}
                ):
                    self.fail("orientation applies to components and must be right or down", start)
                if kind != "box" and attrs.get("shadow", False):
                    self.fail("only boxes support shadows", start)
                attrs.setdefault("shadow", kind == "box")
                self.diagram.nodes[keyword] = Node(keyword, kind, label, start.location, **attrs)
            else:
                self.index -= 1
                a = self.endpoint()
                connections = []
                while self.token.kind == "arrow":
                    arrow = self.pop().value == "->"
                    b = self.endpoint()
                    connections.append((a, b, arrow))
                    a = b
                if not connections:
                    self.fail("expected a node declaration or a connection", start)
                attrs = self.attributes({"label": str, "via": str, "offset": float, "layout": bool})
                if "via" in attrs and attrs["via"] not in {"left", "right", "top", "bottom"}:
                    self.fail("via must be left, right, top, or bottom", start)
                if "offset" in attrs and "via" not in attrs:
                    self.fail("offset requires a via routing lane", start)
                self.diagram.edges.extend(
                    Edge(a, b, start.location, arrow=arrow, **attrs) for a, b, arrow in connections
                )
            if self.token.value != "}" and self.token.kind != "newline":
                self.fail("expected a newline or semicolon between statements")
            self.breaks()
        self.breaks()
        if self.token.kind != "eof":
            self.fail("unexpected content after diagram")
        self.validate()
        return self.diagram

    def validate(self):
        diagram = self.diagram
        if not diagram.nodes:
            self.fail("diagram needs at least one node")
        if len(diagram.nodes) > 256 or len(diagram.edges) > 1024:
            self.fail("diagram exceeds the limit of 256 nodes or 1024 connections")
        for edge in diagram.edges:
            for endpoint in (edge.start, edge.end):
                self.require_node(endpoint.node, edge.location)
                if (
                    endpoint.port
                    and endpoint.port not in SIDES | diagram.nodes[endpoint.node].ports.keys()
                ):
                    raise DiagramError(
                        f"unknown port {endpoint.node}.{endpoint.port}", edge.location
                    )
        for placement in diagram.placements:
            self.require_node(placement.node, placement.location)
            if placement.reference:
                self.require_node(placement.reference, placement.location)
        for alignment in diagram.alignments:
            for name in alignment.nodes:
                self.require_node(name, alignment.location)

    def require_node(self, name: str, location: Location):
        if name not in self.diagram.nodes:
            raise DiagramError(f"unknown node {name!r}", location)


def parse(source: str, *, filename: str = "<input>") -> Diagram:
    return Parser(source, filename).parse()
