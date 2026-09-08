"""Attacks package.
Provides a tiny data‑driven framework for executing memory‑poisoning attacks.
All attack configuration is expressed in YAML files; the runtime loads the
configuration, checks its trigger predicate, optionally injects delay messages,
and then mutates the in‑memory state via the existing tool registry.
"""

__all__ = ["base", "run_attack"]
