from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from . import __version__
from .layout import layout
from .model import DiagramError
from .parser import MAX_SOURCE_CHARACTERS, parse
from .svg import render_svg


def write_atomic(path: Path, content: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as stream:
            temporary = stream.name
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def read_source(filename: str) -> str:
    if filename != "-":
        with Path(filename).open(encoding="utf-8", newline="") as stream:
            return stream.read(MAX_SOURCE_CHARACTERS + 1)
    # UTF-8 uses a max of four bytes per character; reject oversized inputs
    data = sys.stdin.buffer.read(4 * MAX_SOURCE_CHARACTERS + 1)
    if len(data) > 4 * MAX_SOURCE_CHARACTERS:
        raise DiagramError("source exceeds the one million character limit")
    return data.decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="stipple", description="Compile technical diagrams to SVG."
    )
    parser.add_argument("input", help="diagram source, or - for standard input")
    parser.add_argument("-o", "--output", help="output file; defaults to standard output")
    parser.add_argument("--check", action="store_true", help="validate and lay out without writing")
    parser.add_argument(
        "--format",
        choices=("svg", "json"),
        default="svg",
        help="SVG or resolved geometry for inspection",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="write SVG to -o and print its Markdown image reference",
    )
    parser.add_argument("--id-prefix", help="unique SVG identifier prefix for inline embedding")
    parser.add_argument("--version", action="version", version=f"stipple {__version__}")
    args = parser.parse_args(argv)
    if args.markdown and (not args.output or args.format != "svg" or args.check):
        parser.error("--markdown requires -o, SVG output, and no --check")
    try:
        diagram = parse(read_source(args.input), filename=args.input)
        drawing = layout(diagram)
        if args.check:
            return 0
        if args.format == "svg":
            content = render_svg(drawing, id_prefix=args.id_prefix)
        else:
            geometry = {
                "bounds": asdict(drawing.bounds),
                "nodes": {name: asdict(box) for name, box in drawing.boxes.items()},
                "connections": [
                    {
                        "from": asdict(e.edge.start),
                        "to": asdict(e.edge.end),
                        "points": [asdict(p) for p in e.points],
                        "label": asdict(e.label_box) if e.label_box else None,
                    }
                    for e in drawing.edges
                ],
            }
            content = json.dumps(geometry, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            if args.input != "-" and Path(args.output).resolve() == Path(args.input).resolve():
                raise DiagramError("output must not replace the source file")
            write_atomic(Path(args.output), content)
        else:
            sys.stdout.buffer.write(content.encode("utf-8"))
        if args.markdown:
            title = diagram.title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")
            title = " ".join(title.split())
            reference = f"![{title}](<{quote(Path(args.output).as_posix(), safe='/.-_~:')}>)\n"
            sys.stdout.buffer.write(reference.encode("utf-8"))
        return 0
    except (DiagramError, OSError, UnicodeError) as error:
        sys.stderr.buffer.write((str(error) + "\n").encode("utf-8", errors="backslashreplace"))
        return 1
