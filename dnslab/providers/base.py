"""Provider ABC: the uniform lifecycle contract across tiers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..model import Instance, Profile, ServerSpec, Target


class Provider(ABC):
    name: str

    @abstractmethod
    def start(self, spec: ServerSpec, profile: Profile, instance_name: str,
              *, wait: bool = True, timeout: float = 60, **overrides) -> Instance: ...

    @abstractmethod
    def stop(self, instance: Instance) -> None: ...

    @abstractmethod
    def discover(self) -> list[Instance]:
        """Find instances this provider previously started (kernel-restart safe)."""

    @abstractmethod
    def target(self, instance: Instance) -> Target: ...

    def logs(self, instance: Instance, tail: int = 100) -> str:
        return ""

    def nuke(self) -> list[str]:
        """Tear down everything this provider ever started; returns what it removed."""
        removed = []
        for inst in self.discover():
            self.stop(inst)
            removed.append(inst.name)
        return removed
