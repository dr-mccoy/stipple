from .model import DiagramError

__all__ = ["DiagramError", "__version__", "compile_svg"]

__version__ = "0.1.0"


def compile_svg(source: str, *, filename: str = "<input>", id_prefix: str | None = None) -> str:
    """Compile source to SVG, using filename only for diagnostics.

    Use a unique id_prefix for each copy embedded inline in one HTML document.
    """
    from .layout import layout
    from .parser import parse
    from .svg import render_svg

    return render_svg(layout(parse(source, filename=filename)), id_prefix=id_prefix)
