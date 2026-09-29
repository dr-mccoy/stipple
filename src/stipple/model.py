from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Location:
    filename: str
    line: int
    column: int
    text: str


class DiagramError(ValueError):
    def __init__(self, message: str, location: Location | None = None):
        self.message = message
        self.location = location
        super().__init__(message)

    def __str__(self) -> str:
        if self.location is None:
            return self.message
        loc = self.location
        return (
            f"{loc.filename}:{loc.line}:{loc.column}: {self.message}\n"
            f"  {loc.text}\n  {' ' * (loc.column - 1)}^"
        )


@dataclass(frozen=True)
class Endpoint:
    node: str
    port: str | None = None


@dataclass(frozen=True)
class Port:
    side: str
    fraction: float = 0.5


@dataclass
class Node:
    id: str
    kind: str
    label: str
    location: Location
    width: float | None = None
    height: float | None = None
    shadow: bool = True
    orientation: str = "right"
    ports: dict[str, Port] = field(default_factory=dict)


@dataclass
class Edge:
    start: Endpoint
    end: Endpoint
    location: Location
    arrow: bool = True
    label: str = ""
    via: str | None = None
    offset: float = 32
    layout: bool = True


@dataclass(frozen=True)
class Placement:
    node: str
    relation: str
    reference: str | None
    values: tuple[float, ...]
    location: Location


@dataclass(frozen=True)
class Alignment:
    nodes: tuple[str, ...]
    anchor: str
    location: Location


@dataclass
class Diagram:
    title: str = "Diagram"
    description: str = ""
    direction: str = "down"
    gap: float = 52
    font_size: float = 15
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)
    alignments: list[Alignment] = field(default_factory=list)


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def expand(self, amount: float) -> Box:
        return Box(
            self.x - amount, self.y - amount, self.width + 2 * amount, self.height + 2 * amount
        )

    def overlaps(self, other: Box) -> bool:
        return (
            self.x < other.right - 1e-6
            and self.right > other.x + 1e-6
            and self.y < other.bottom - 1e-6
            and self.bottom > other.y + 1e-6
        )


@dataclass(frozen=True)
class RoutedEdge:
    edge: Edge
    points: tuple[Point, ...]
    label_box: Box | None = None


@dataclass(frozen=True)
class Drawing:
    diagram: Diagram
    boxes: dict[str, Box]
    edges: tuple[RoutedEdge, ...]
    bounds: Box
