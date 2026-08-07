"""AgentKit wire contract package -- the ``/v1`` vocabulary of both machines.

AK3 runs on two machines: **Project Edge** on the developer machine and the
**core** on a central host (FK-10). The ``/v1`` HTTP interface is the only bridge
between them. This package holds the vocabulary that both sides of that bridge
need, so neither has to import the other to name a request or a response.

**This is not a shared-code dump.** Membership is decided by the frozen
classification in
``concept/formal-spec/architecture-conformance/entities.md``:
``distribution_symbol_boundaries`` names, per source module, exactly which
symbols move here and which stay. A symbol that is not listed there does not
belong here, however convenient it would be.

Rules this package keeps, enforced by
``tests/contract/wire/test_wire_package_purity.py``:

* **I/O-free.** No filesystem, network, database, subprocess or environment
  access; no ``pathlib``, no ``os``, no ``open``.
* **Leaf.** No import from ``agentkit`` -- neither edge nor core. The dependency
  arrow points at this package and never out of it.
* **pydantic and the standard library only.** No other third party.
* **Vocabulary, not behaviour.** Models, enums, constants and their validators.
  A function that *does* something belongs to the side that owns the doing.

Each module here corresponds to one ``wire_target_modules`` entry of the frozen
classification and carries the symbols that entry assigns to it.

AG3-239 created the package with the symbols the ``governance-and-guards``
bounded context needs. The remaining symbols follow in the other bounded-context
stories; each moves exactly once, to the place the classification already names.
There is deliberately no third distribution yet -- the wheel split is AG3-209.
"""

from __future__ import annotations

__all__: list[str] = []
