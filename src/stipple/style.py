from dataclasses import dataclass


@dataclass(frozen=True)
class Style:
    ink: str = "#202020"
    paper: str = "#ffffff"
    stroke: float = 1.15
    shadow_x: float = 10
    shadow_y: float = 14
    dot_pitch: float = 5
    dot_radius: float = 0.7
    clearance: float = 6


CLASSIC = Style()
