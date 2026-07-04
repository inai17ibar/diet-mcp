from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Meal:
    id: str
    date: str  # "YYYY-MM-DD"
    time: str  # "HH:MM"
    description: str
    calories: float
    tags: list[str] = field(default_factory=list)
    protein_g: float | None = None
    fat_g: float | None = None
    carbs_g: float | None = None
