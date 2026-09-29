from __future__ import annotations

import heapq
from itertools import count, pairwise

from .model import Box, Diagram, DiagramError, Edge, Endpoint, Point, Port, RoutedEdge
from .style import CLASSIC
from .text import measure

VECTORS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}


def obstacle(diagram: Diagram, name: str, box: Box) -> Box:
    shadow = diagram.nodes[name].shadow
    return Box(
        box.x,
        box.y,
        box.width + (CLASSIC.shadow_x if shadow else 0),
        box.height + (CLASSIC.shadow_y if shadow else 0),
    ).expand(CLASSIC.clearance)


def segment_hits(a: Point, b: Point, box: Box) -> bool:
    """Test the open interior; travelling along an obstacle boundary is allowed."""
    epsilon = 1e-6
    if abs(a.y - b.y) < epsilon:
        return (
            box.y + epsilon < a.y < box.bottom - epsilon
            and max(a.x, b.x) > box.x + epsilon
            and min(a.x, b.x) < box.right - epsilon
        )
    if abs(a.x - b.x) < epsilon:
        return (
            box.x + epsilon < a.x < box.right - epsilon
            and max(a.y, b.y) > box.y + epsilon
            and min(a.y, b.y) < box.bottom - epsilon
        )
    raise ValueError("router received a non-orthogonal segment")


def simplify(points: list[Point]) -> tuple[Point, ...]:
    result: list[Point] = []
    for point in points:
        if result and point == result[-1]:
            continue
        while len(result) >= 2:
            a, b = result[-2:]
            same_x = a.x == b.x == point.x and (b.y - a.y) * (point.y - b.y) >= 0
            same_y = a.y == b.y == point.y and (b.x - a.x) * (point.x - b.x) >= 0
            if same_x or same_y:
                result.pop()
            else:
                break
        result.append(point)
    return tuple(result)


def shortest_path(start: Point, end: Point, obstacles: list[Box], edge: Edge) -> list[Point]:
    if start == end:
        return [start]
    xs = sorted({start.x, end.x, *(v for b in obstacles for v in (b.x, b.right))})
    ys = sorted({start.y, end.y, *(v for b in obstacles for v in (b.y, b.bottom))})
    initial = (xs.index(start.x), ys.index(start.y), 0)
    goal = (xs.index(end.x), ys.index(end.y))
    serial = count()
    queue = [(0.0, next(serial), 0.0, initial)]
    costs = {initial: 0.0}
    previous = {}
    visibility = {}
    while queue:
        _, _, cost, current = heapq.heappop(queue)
        if cost > costs[current]:
            continue
        x, y, direction = current
        if (x, y) == goal:
            path = [Point(xs[x], ys[y])]
            while current in previous:
                current = previous[current]
                path.append(Point(xs[current[0]], ys[current[1]]))
            return list(reversed(path))
        if len(costs) > 100_000:
            raise DiagramError(
                "routing search is too large; simplify or split the drawing", edge.location
            )
        a = Point(xs[x], ys[y])
        for nx, ny, nd in ((x + 1, y, 1), (x - 1, y, 1), (x, y + 1, 2), (x, y - 1, 2)):
            if not 0 <= nx < len(xs) or not 0 <= ny < len(ys):
                continue
            b = Point(xs[nx], ys[ny])
            key = (min(x, nx), min(y, ny), max(x, nx), max(y, ny))
            if key not in visibility:
                visibility[key] = not any(segment_hits(a, b, box) for box in obstacles)
            if not visibility[key]:
                continue
            distance = abs(a.x - b.x) + abs(a.y - b.y)
            candidate_cost = cost + distance + (14 if direction and nd != direction else 0)
            candidate = (nx, ny, nd)
            if candidate_cost >= costs.get(candidate, float("inf")):
                continue
            costs[candidate] = candidate_cost
            previous[candidate] = (x, y, direction)
            heuristic = abs(b.x - end.x) + abs(b.y - end.y)
            heapq.heappush(
                queue, (candidate_cost + heuristic, next(serial), candidate_cost, candidate)
            )
    raise DiagramError(
        "no clear route between connection ports; increase spacing or choose another port",
        edge.location,
    )


def terminal(
    diagram: Diagram, boxes: dict[str, Box], endpoint: Endpoint, default: str
) -> tuple[Point, Point]:
    node, box = diagram.nodes[endpoint.node], boxes[endpoint.node]
    port = node.ports.get(endpoint.port or "", Port(endpoint.port or default))
    side, fraction = port.side, port.fraction
    if side in {"north", "south"}:
        point = Point(box.x + box.width * fraction, box.y if side == "north" else box.bottom)
    else:
        point = Point(box.x if side == "west" else box.right, box.y + box.height * fraction)
    if node.kind == "junction":
        point = box.center
    elif node.kind == "text":
        dx, dy = VECTORS[side]
        point = Point(point.x + dx * 4, point.y + dy * 4)
    elif node.kind in {"resistor", "capacitor"}:
        if node.orientation == "down" and side in {"north", "south"}:
            point = Point(box.x + 9, point.y)
        elif node.orientation == "right" and side in {"east", "west"}:
            point = Point(point.x, box.bottom - 10)
        else:
            raise DiagramError("connection must use the component's terminal sides", node.location)
    clearance = obstacle(diagram, endpoint.node, box)
    if side == "north":
        escape = Point(point.x, clearance.y)
    elif side == "south":
        escape = Point(point.x, clearance.bottom)
    elif side == "east":
        escape = Point(clearance.right, point.y)
    else:
        escape = Point(clearance.x, point.y)
    return point, escape


def route(diagram: Diagram, boxes: dict[str, Box], edge: Edge) -> RoutedEdge:
    a, b = boxes[edge.start.node].center, boxes[edge.end.node].center
    if abs(b.x - a.x) > abs(b.y - a.y):
        start_side, end_side = ("east", "west") if b.x >= a.x else ("west", "east")
    else:
        start_side, end_side = ("south", "north") if b.y >= a.y else ("north", "south")
    if edge.start.node == edge.end.node and not (edge.start.port and edge.end.port):
        raise DiagramError("self-connections need two explicit ports", edge.location)
    start, start_escape = terminal(diagram, boxes, edge.start, start_side)
    end, end_escape = terminal(diagram, boxes, edge.end, end_side)
    if start == end:
        raise DiagramError("connection terminals coincide; choose different ports", edge.location)
    obstacles = [obstacle(diagram, name, box) for name, box in boxes.items()]
    for name, box in boxes.items():
        if name != edge.start.node and segment_hits(start, start_escape, box):
            raise DiagramError("the source port is blocked by another node", edge.location)
        if name != edge.end.node and segment_hits(end, end_escape, box):
            raise DiagramError("the destination port is blocked by another node", edge.location)
    waypoints = [start_escape]
    if edge.via in {"left", "right"}:
        x = (
            min(b.x for b in obstacles) - edge.offset
            if edge.via == "left"
            else max(b.right for b in obstacles) + edge.offset
        )
        waypoints.extend((Point(x, start_escape.y), Point(x, end_escape.y)))
    elif edge.via in {"top", "bottom"}:
        y = (
            min(b.y for b in obstacles) - edge.offset
            if edge.via == "top"
            else max(b.bottom for b in obstacles) + edge.offset
        )
        waypoints.extend((Point(start_escape.x, y), Point(end_escape.x, y)))
    waypoints.append(end_escape)
    points = [start]
    for a, b in pairwise(waypoints):
        points.extend(shortest_path(a, b, obstacles, edge))
    points.append(end)
    return RoutedEdge(edge, simplify(points))


def label_box(
    diagram: Diagram, routed: RoutedEdge, forbidden: list[Box], segments: list[tuple[Point, Point]]
) -> Box:
    text = measure(routed.edge.label, diagram.font_size, routed.edge.location)
    width, height = text.width + 12, text.height + 8
    for a, b in sorted(
        pairwise(routed.points),
        key=lambda p: -abs(p[0].x - p[1].x) - abs(p[0].y - p[1].y),
    ):
        for fraction in (0.5, 0.25, 0.75):
            x, y = a.x + (b.x - a.x) * fraction, a.y + (b.y - a.y) * fraction
            candidates = (
                (
                    Box(x - width / 2, y - height - 4, width, height),
                    Box(x - width / 2, y + 4, width, height),
                )
                if a.y == b.y
                else (
                    Box(x + 5, y - height / 2, width, height),
                    Box(x - width - 5, y - height / 2, width, height),
                )
            )
            for box in candidates:
                if any(box.overlaps(other) for other in forbidden):
                    continue
                if any(segment_hits(p, q, box) for p, q in segments):
                    continue
                return box
    raise DiagramError(
        "connection label has no clear space; increase the gap or route offset",
        routed.edge.location,
    )


def route_all(diagram: Diagram, boxes: dict[str, Box]) -> list[RoutedEdge]:
    paths = [route(diagram, boxes, edge) for edge in diagram.edges]
    segments = [segment for path in paths for segment in pairwise(path.points)]
    forbidden = [obstacle(diagram, name, box) for name, box in boxes.items()]
    for i, path in enumerate(paths):
        if path.edge.label:
            box = label_box(diagram, path, forbidden, segments)
            forbidden.append(box)
            paths[i] = RoutedEdge(path.edge, path.points, box)
    return paths
