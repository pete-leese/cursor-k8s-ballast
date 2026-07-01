"""Service dependency graph behind blast-radius reasoning.

The seam: ``TopologySource`` has a single method, ``dependents()``. The prototype
implements it by reading the declared ``topology.yaml``; in production a service
mesh / Consul MCP implementation would derive the same graph from the live mesh
without touching anything that consumes it. Declared graph for the prototype,
live source in production.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import yaml


class TopologySource(ABC):
    @abstractmethod
    def dependents(self, service: str) -> list[str]:
        """Return every service that depends on ``service``, directly or
        transitively — i.e. who would be affected if ``service`` were rolled
        back. This is the blast radius."""

    @abstractmethod
    def services(self) -> list[str]:
        """All known services."""


class DeclaredTopologySource(TopologySource):
    """Reads a declared dependency graph from a YAML file shaped like
    ``{services: {name: {depends_on: [...]}}}``."""

    def __init__(self, path: str | Path) -> None:
        data = yaml.safe_load(Path(path).read_text()) or {}
        self._services: dict[str, dict] = data.get("services", {})

    def services(self) -> list[str]:
        return sorted(self._services)

    def _direct_dependents(self, service: str) -> list[str]:
        return [
            name
            for name, meta in self._services.items()
            if service in (meta or {}).get("depends_on", [])
        ]

    def dependents(self, service: str) -> list[str]:
        # Breadth-first transitive closure over the reverse-dependency edges.
        seen: set[str] = set()
        stack = [service]
        while stack:
            current = stack.pop()
            for dependent in self._direct_dependents(current):
                if dependent not in seen:
                    seen.add(dependent)
                    stack.append(dependent)
        return sorted(seen)
