from __future__ import annotations

from collections import defaultdict, deque
from itertools import combinations

from .model import Box, Diagram, DiagramError, Drawing, Location, Node
from .routing import route_all
from .style import CLASSIC
from .text import measure


def dimensions(node: Node, font_size: float) -> tuple[float, float]:
    text = measure(node.label, font_size, node.location)
    if node.kind == "junction":
        width, height = 6.0, 6.0
    elif node.kind == "text":
        width, height = max(text.width, 1), text.height
    elif node.kind in {"resistor", "capacitor"}:
        if node.orientation == "down":
            width, height = text.width + 32, max(80, text.height + 20)
        else:
            width, height = max(80, text.width + 8), text.height + 38
    else:
        width, height = max(72, text.width + 32), max(44, text.height + 28)
    if (
        node.width is not None
        and node.width < width - 1e-6
        or node.height is not None
        and node.height < height - 1e-6
    ):
        raise DiagramError(
            f"{node.id!r} needs at least {width:.1f} × {height:.1f} units for its label",
            node.location,
        )
    return node.width or width, node.height or height


def automatic(diagram: Diagram, sizes: dict[str, tuple[float, float]]) -> dict[str, Box]:
    order = {name: i for i, name in enumerate(diagram.nodes)}
    # Fully positioned drawings may contain cycles; no automatic ranks are needed.
    absolute = {p.node for p in diagram.placements if p.relation == "at"}
    if len(absolute) == len(diagram.nodes):
        return {name: Box(0, 0, *size) for name, size in sizes.items()}
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming = dict.fromkeys(diagram.nodes, 0)
    ranks = dict.fromkeys(diagram.nodes, 0)
    for edge in diagram.edges:
        a, b = edge.start.node, edge.end.node
        if edge.layout and b not in outgoing[a]:
            outgoing[a].add(b)
            incoming[b] += 1
    queue = deque(name for name in diagram.nodes if incoming[name] == 0)
    visited = 0
    while queue:
        a = queue.popleft()
        visited += 1
        for b in sorted(outgoing[a], key=order.__getitem__):
            ranks[b] = max(ranks[b], ranks[a] + 1)
            incoming[b] -= 1
            if incoming[b] == 0:
                queue.append(b)
    if visited != len(diagram.nodes):
        name = next(name for name, count in incoming.items() if count)
        raise DiagramError(
            "automatic layout contains a cycle; set [layout=false] on a return "
            "connection, or place every node at explicit coordinates",
            diagram.nodes[name].location,
        )
    layers: dict[int, list[str]] = defaultdict(list)
    for name in diagram.nodes:
        layers[ranks[name]].append(name)
    vertical = diagram.direction == "down"
    depth_axis, cross_axis = (1, 0) if vertical else (0, 1)
    layer_widths = {
        rank: sum(sizes[n][cross_axis] for n in names) + diagram.gap * (len(names) - 1)
        for rank, names in layers.items()
    }
    total_width = max(layer_widths.values())
    boxes = {}
    depth = 0.0
    for rank, names in sorted(layers.items()):
        cross = (total_width - layer_widths[rank]) / 2
        layer_depth = max(sizes[n][depth_axis] for n in names)
        for name in names:
            w, h = sizes[name]
            x, y = (cross, depth) if vertical else (depth, cross)
            boxes[name] = Box(x, y, w, h)
            cross += sizes[name][cross_axis] + diagram.gap
        depth += layer_depth + diagram.gap
    return boxes


def constraints(diagram: Diagram, boxes: dict[str, Box]) -> dict[str, Box]:
    # Each axis is a graph of equations: position(a) = position(b) + delta.
    neighbors: list[dict[str, list[tuple[str, float, Location]]]] = [
        defaultdict(list),
        defaultdict(list),
    ]
    anchors: list[list[tuple[str, float, Location]]] = [[], []]
    targets: list[set[str]] = [set(), set()]
    for p in diagram.placements:
        a = boxes[p.node]
        if p.relation == "at":
            for axis in (0, 1):
                anchors[axis].append((p.node, p.values[axis], p.location))
            continue
        assert p.reference is not None
        b = boxes[p.reference]
        gap = p.values[0] if p.values else diagram.gap
        dx, dy = (b.width - a.width) / 2, (b.height - a.height) / 2
        if p.relation == "below":
            dy = b.height + gap
        elif p.relation == "above":
            dy = -a.height - gap
        elif p.relation == "right":
            dx = b.width + gap
        elif p.relation == "left":
            dx = -a.width - gap
        for axis, delta in enumerate((dx, dy)):
            neighbors[axis][p.reference].append((p.node, delta, p.location))
            neighbors[axis][p.node].append((p.reference, -delta, p.location))
            targets[axis].add(p.node)
    for alignment in diagram.alignments:
        anchor = alignment.anchor
        axis = 0 if anchor in {"left", "right", "center-x"} else 1
        factor = 1 if anchor in {"right", "bottom"} else 0.5 if "center" in anchor else 0
        reference = alignment.nodes[0]
        for name in alignment.nodes[1:]:
            a, b = boxes[name], boxes[reference]
            delta = factor * ((b.width - a.width) if axis == 0 else (b.height - a.height))
            neighbors[axis][reference].append((name, delta, alignment.location))
            neighbors[axis][name].append((reference, -delta, alignment.location))
            targets[axis].add(name)
    values = []
    for axis in (0, 1):
        fixed: dict[str, tuple[float, Location]] = {}
        for name, value, loc in anchors[axis]:
            if name in fixed and abs(fixed[name][0] - value) > 1e-6:
                raise DiagramError(f"conflicting coordinates for {name!r}", loc)
            fixed[name] = (value, loc)
        solved = {}
        for first in diagram.nodes:
            if first in solved:
                continue
            offsets = {first: 0.0}
            queue = deque([first])
            while queue:
                name = queue.popleft()
                for other, delta, loc in neighbors[axis][name]:
                    expected = offsets[name] + delta
                    if other in offsets:
                        if abs(offsets[other] - expected) > 1e-6:
                            raise DiagramError(
                                "conflicting placement or alignment constraints", loc
                            )
                    else:
                        offsets[other] = expected
                        queue.append(other)
            root = next((n for n in offsets if n in fixed), None)
            if root is None:
                root = next((n for n in offsets if n not in targets[axis]), first)
                base = (boxes[root].x if axis == 0 else boxes[root].y) - offsets[root]
            else:
                base = fixed[root][0] - offsets[root]
            for name, offset in offsets.items():
                value = base + offset
                if name in fixed and abs(value - fixed[name][0]) > 1e-6:
                    raise DiagramError(f"conflicting placement for {name!r}", fixed[name][1])
                solved[name] = value
        values.append(solved)
    return {
        name: Box(values[0][name], values[1][name], box.width, box.height)
        for name, box in boxes.items()
    }


def layout(diagram: Diagram) -> Drawing:
    sizes = {name: dimensions(node, diagram.font_size) for name, node in diagram.nodes.items()}
    boxes = constraints(diagram, automatic(diagram, sizes))
    for name, other in combinations(boxes, 2):
        if boxes[name].overlaps(boxes[other]):
            raise DiagramError(
                f"nodes {name!r} and {other!r} overlap", diagram.nodes[other].location
            )
    edges = route_all(diagram, boxes)
    extents = [
        Box(
            b.x,
            b.y,
            b.width + (CLASSIC.shadow_x if diagram.nodes[n].shadow else 0),
            b.height + (CLASSIC.shadow_y if diagram.nodes[n].shadow else 0),
        )
        for n, b in boxes.items()
    ]
    for edge in edges:
        if edge.label_box:
            extents.append(edge.label_box)
        extents.extend(Box(p.x - 4, p.y - 4, 8, 8) for p in edge.points)
    left = min(b.x for b in extents) - 24
    top = min(b.y for b in extents) - 24
    right = max(b.right for b in extents) + 24
    bottom = max(b.bottom for b in extents) + 24
    return Drawing(diagram, boxes, tuple(edges), Box(left, top, right - left, bottom - top))
