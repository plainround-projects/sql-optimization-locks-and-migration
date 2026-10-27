"""What the plan-flip experiment reads from a plan: the planner's estimate, the node types, the time."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from .errors import PlanParseError

_NODE = re.compile(r"^\s*(?:->\s*)?(Seq Scan|Index Scan Backward|Index Scan|Bitmap Heap Scan|Sort)\b", re.MULTILINE)
_ESTIMATE = re.compile(r"\(cost=[^)]*rows=(\d+)")
_EXECUTION = re.compile(r"Execution Time: ([\d.]+) ms")


@dataclass(frozen=True, slots=True)
class FlipPlan:
    """The estimate on the deepest node, the node types in plan order, and the execution time."""

    estimate: int
    nodes: tuple[str, ...]
    milliseconds: float

    @property
    def scans_everything(self) -> bool:
        return "Seq Scan" in self.nodes

    @property
    def walks_the_index(self) -> bool:
        return "Index Scan Backward" in self.nodes


def parse_flip_plan(lines: Sequence[str]) -> FlipPlan:
    """Read a plan from `EXPLAIN (ANALYZE, BUFFERS)` text."""
    text = "\n".join(lines)
    estimates, execution = _ESTIMATE.findall(text), _EXECUTION.search(text)
    if not estimates or execution is None:
        raise PlanParseError("the plan has no row estimate or no Execution Time: was it produced with ANALYZE?")
    return FlipPlan(int(estimates[-1]), tuple(dict.fromkeys(_NODE.findall(text))), float(execution.group(1)))
