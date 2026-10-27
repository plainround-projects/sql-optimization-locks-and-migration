"""How busy the machine was while something was measured, so a reader can discount the milliseconds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HostLoad:
    """The 1-minute load average and the CPU count at the start of a measurement."""

    load_average: float
    cpus: int

    @property
    def loaded(self) -> bool:
        """True when more than half a runnable task per CPU was waiting: timings are inflated."""
        return self.load_average > self.cpus / 2

    def note(self) -> str:
        """One sentence for the results file."""
        if self.loaded:
            return (
                f"Measured on a loaded machine (load average {self.load_average:.1f} on {self.cpus} CPUs); rerun "
                "`make run` on a quiet machine for clean figures. The ratios survive load better than the milliseconds."
            )
        return f"Measured at load average {self.load_average:.1f} on {self.cpus} CPUs."
