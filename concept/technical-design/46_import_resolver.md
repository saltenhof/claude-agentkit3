---
concept_id: FK-46
title: Import-Resolver für Evidence Assembly
module: import-resolver
domain: verify-system
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: import-resolution
  - scope: confidence-labels
defers_to:
  - target: FK-28
    scope: evidence-assembly
    reason: Stufe-2-Eingliederung liegt in FK-28 §28.3
  - target: FK-10
    scope: worktree-topology
    reason: Physische Worktree-Leseflaechen liegen ausschliesslich am Project Edge
supersedes: []
superseded_by:
tags: [evidence-assembly, import-resolution, authority-classes, review-preparation]
formal_scope: prose-only
---

# 46 — Import-Resolver für Evidence Assembly

## 46.1 Zweck

Der Import-Resolver ist der deterministische Backend-Kern fuer
Stufe 2 der Evidence Assembly (FK-28 §28.3). Seit AG3-156 liest er
keine Ziel-Worktrees. Eingangsmenge ist ein vom Project Edge
gemeldeter, inhaltlich gebundener Snapshot aus
`VerifyEvidenceFile(repo_id, path, content, size, sha256)`.

Die Regex-, Alias-, Barrel- und Java-Konsolidierung bleibt im
Backend. Der Edge sammelt Dateien, entscheidet aber weder
Confidence noch D3. `ImportResolver.from_collected_files(files)`
akzeptiert keine physischen Repo-Pfade.

## 46.2 Python-Resolver

Python-Imports werden aus dem gemeldeten Quellinhalt per Regex
extrahiert. Ein Modul `a.b` erzeugt die Snapshot-Kandidaten
`a/b.py` und `a/b/__init__.py`. Zuerst wird innerhalb der
`source_repo_id` gesucht, danach ueber weitere gemeldete Repos.
Relative Imports werden anhand der fuehrenden Punkte gegen das
Package-Verzeichnis der gemeldeten Quelldatei normalisiert; auch
dabei erfolgt ausschliesslich ein Snapshot-Lookup.
Gibt es nach dieser Repo-Bindung keinen eindeutigen Kandidaten,
bleibt der Import dynamisch/unaufgeloest; es erfolgt kein
Dateisystem-Fallback.

## 46.3 TypeScript-Resolver (inkl. JS/JSX/TSX)

Unterstuetzt werden statische Imports, Side-Effect-Imports,
Re-Exports und `require(...)`. Kandidaten entstehen nur aus dem
Snapshot. `tsconfig.json`/`jsconfig.json`, `baseUrl`, `paths` und
Barrel-Dateien werden aus demselben Snapshot geparst. Dynamische
`import(...)`-Ausdruecke erhalten `UNRESOLVED_DYNAMIC`; das Backend
scannt dafuer keinen Worktree nach.

## 46.4 Java-Resolver (inkl. Spring-Heuristiken)

Package-Index, explizite Imports, Same-Package-Referenzen und
Spring-Scan-Heuristiken werden ausschliesslich aus gemeldeten
`.java`-Inhalten aufgebaut. Ein `rglob` oder `read_text` ueber
Ziel-Repositories ist im Backend verboten. Nicht im Snapshot
enthaltene Typen bleiben unaufgeloest.

## 46.5 Confidence Labels (FK-28-004)

| Label | Prioritaet | Bedeutung |
|-------|-----------:|-----------|
| `RESOLVED_IMPORT` | 5 | expliziter, eindeutig snapshot-gebundener Import |
| `RESOLVED_ALIAS` | 4 | eindeutig ueber gemeldete Alias-Konfiguration |
| `BARREL_CONTEXT` | 3 | eindeutig ueber eine gemeldete Barrel-Datei |
| `SAME_PACKAGE_HEURISTIC` | 2 | Java-Typ im gleichen gemeldeten Package |
| `SPRING_SCAN_HEURISTIC` | 1 | gemeldeter Spring-Scan-Kontext |
| `UNRESOLVED_DYNAMIC` | 0 | nicht eindeutig oder dynamisch |

```python
from __future__ import annotations

class ImportResolver:
    def __init__(self, files: Iterable[VerifyEvidenceFile]) -> None: ...

    @classmethod
    def from_collected_files(
        cls, files: Iterable[VerifyEvidenceFile],
    ) -> ImportResolver: ...

    def resolve(
        self, repo_id: str, source_file: Path,
    ) -> list[ResolvedImport]: ...
```

Ein `ResolvedImport` bindet `source_repo_id`, relativen
`source_file`, optional `target_repo_id` und relativen
`target_file`, Original-Import und Confidence. Stage 2 uebernimmt
nur Ziele, deren Inhalt/Groesse noch exakt zum gemeldeten Snapshot
passt; ein Binding-Mismatch ist ERROR, ein fehlendes Edge-File ein
benannter `EDGE_EVIDENCE_UNAVAILABLE`-Befund.
