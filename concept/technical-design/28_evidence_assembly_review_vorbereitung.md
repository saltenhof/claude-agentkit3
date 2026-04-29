---
concept_id: FK-28
title: Evidence Assembly und Review-Vorbereitung
module: evidence-assembly
domain: verify-system
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: evidence-assembly
  - scope: bundle-manifest
  - scope: authority-classes
defers_to:
  - target: FK-27
    scope: verify-phase
    reason: Evidence Assembly dient der Vorbereitung fuer Verify Schicht 2 (FK-27)
  - target: FK-34
    scope: llm-evaluations
    reason: LLM-basierte Reviews in der Verify-Phase in FK-34 beschrieben
  - target: FK-12
    scope: git-operations
    reason: GitOperations ist Single-Repo by design (FK-12)
  - target: FK-13
    scope: vectordb
    reason: Story Knowledge Base und VektorDB-Abgleich in FK-13
  - target: FK-46
    scope: import-resolution
    reason: Stufe 2 (Import-Auflösung, Confidence-Labels) liegt in FK-46
  - target: FK-47
    scope: request-dsl
    reason: Request-DSL und Preflight-Turn liegen in FK-47
  - target: FK-43
    scope: agentkit-cli
    reason: CLI-Subparser-Wiring liegt in FK-43
  - target: FK-30
    scope: review-templates
    reason: Review-Template-Sentinel und hook.py-Regex liegen in FK-30
  - target: FK-67
    scope: artefakt-envelope
    reason: Bundle-Manifest und Evidenz-Container folgen dem Envelope-Schema und der Producer-Registry (FK-67)
supersedes: []
superseded_by:
tags: [evidence-assembly, authority-classes, review-preparation, bundles]
formal_scope: prose-only
---

# 28 — Evidence Assembly und Review-Vorbereitung

## 28.1 Zweck

Die Evidence Assembly ist der deterministische Vorbereitungsschritt
für alle LLM-basierten Reviews in der Verify-Phase (Schicht 2,
FK-34). Sie ersetzt die bisher vom Worker selbst kuratierte
`merge_paths`-Liste durch einen maschinell assemblierten,
klassifizierten und auditierbaren Evidenz-Körper.

Das Kernproblem: Worker-Agenten entscheiden heute eigenständig,
welche Dateien ein Reviewer sieht. Das erzeugt zwei systematische
Risiken:

1. **Selektive Evidenz**: Der Worker kann — bewusst oder unbewusst —
   Dateien weglassen, die Schwächen seiner Implementierung aufdecken
   würden.
2. **Kontextlücken**: Der Worker kennt den Informationsbedarf des
   Reviewers nicht im Voraus. Fehlende Nachbardateien, Schemas oder
   Konfigurationen führen zu oberflächlichen Reviews.

Die Evidence Assembly löst beide Probleme durch drei Mechanismen:

- **Deterministischer Assembler** (Stufe 1+2): Sammelt Evidenz
  regelbasiert aus Git-Diff, Imports und normativen Quellen —
  unabhängig vom Worker.
- **Worker-Hints** (Stufe 3): Der Worker darf Dateien vorschlagen,
  diese werden aber als niedrigste Autoritätsklasse markiert.
- **Preflight-Turn** (Request-DSL): Der Reviewer kann vor dem
  eigentlichen Review strukturiert fehlende Informationen anfordern.

Dieses Kapitel beschreibt die Package-Struktur, den Evidence Assembler,
die Autoritätsklassen, die CLI-Registrierung und die Integration in
den bestehenden Review-Flow. **Stufe 2 (Import-Auflösung) ist in FK-46
ausgelagert; Request-DSL und Preflight-Turn liegen in FK-47.**

## 28.2 Package-Struktur (`agentkit/evidence/`)

Komplett neues Package für Evidence Assembly, Import Resolution
und Request-DSL. Keine neuen externen Abhängigkeiten — alle Module
nutzen ausschließlich Python-stdlib (`re`, `pathlib`, `json`,
`subprocess`, `enum`, `dataclasses`) und `pydantic` (bestehende
Dependency).

```
agentkit/evidence/
├── __init__.py
├── assembler.py          # Evidence Assembler (Stufe 1 + 3)
├── import_resolver.py    # Sprachspezifische Import-Extraktion (Stufe 2, FK-46)
├── authority.py          # Autoritätsklassen + BundleEntry-Modell
├── request_resolver.py   # DSL-Request-Auflösung (7 Typen, FK-47)
├── request_types.py      # Pydantic-Modelle für Request-DSL (FK-47)
└── bundle_manifest.py    # BundleManifest (Zusammenfassung des assemblierten Bundles)
```

| Modul | Verantwortung | Abhängigkeiten |
|-------|---------------|----------------|
| `assembler.py` | Orchestriert die 3-Stufen-Assembly | `authority.py`, `import_resolver.py`, `bundle_manifest.py`, `core/git.py` |
| `import_resolver.py` | Regex-basierte Import-Extraktion (Python, TS, Java) — siehe FK-46 | Nur stdlib (`re`, `pathlib`, `json`) |
| `authority.py` | `AuthorityClass` (IntEnum), `BundleEntry` (Dataclass) | `import_resolver.py` (für `ConfidenceLabel`) |
| `request_types.py` | Pydantic-Modelle: `RequestType`, `ReviewerRequest`, `RequestResult` — siehe FK-47 | `pydantic` |
| `request_resolver.py` | Deterministische Auflösung der 7 Request-Typen — siehe FK-47 | `request_types.py`, `core/git.py` |
| `bundle_manifest.py` | `BundleManifest` mit Prompt-Header-Rendering | `authority.py` |

## 28.3 Evidence Assembler

### 28.3.1 3-Stufen-Architektur

Der Evidence Assembler arbeitet in drei sequentiellen Stufen mit
aufsteigender Unsicherheit:

```mermaid
flowchart TD
    START["EvidenceAssembler.assemble()"] --> S1["Stufe 1: Deterministischer Kern"]
    S1 --> S2["Stufe 2: Import-Extraktion"]
    S2 --> S3["Stufe 3: Worker-Hints"]
    S3 --> DEDUP["Deduplizierung"]
    DEDUP --> LIMIT["Größenlimit (350 KB)"]
    LIMIT --> MANIFEST["BundleManifest erzeugen"]
    MANIFEST --> RESULT["AssemblyResult"]

    S1 -.- N1["Git-Diff, Nachbarn,<br/>Story/Concept/Guardrails<br/>Authority: PRIMARY_*"]
    S2 -.- N2["Python/TS/Java Imports<br/>Authority: SECONDARY_CONTEXT"]
    S3 -.- N3["handover.json, worker-manifest.json<br/>Authority: WORKER_ASSERTION"]
```

| Stufe | Quelle | Autoritätsklasse | Unsicherheit |
|-------|--------|-----------------|--------------|
| 1 — Deterministischer Kern | Git-Diff, Nachbardateien, Story-Spec, Concepts, Guardrails, YAML/JSON-Configs | `PRIMARY_IMPLEMENTATION` / `PRIMARY_NORMATIVE` | Keine — alles deterministisch aus Git und Filesystem |
| 2 — Import-Extraktion | Regex-basierte Import-Auflösung für Python, TypeScript, Java (FK-46) | `SECONDARY_CONTEXT` | Gering — Regex kann False Positives erzeugen, Confidence Labels quantifizieren das |
| 3 — Worker-Hints | `handover.json` und `worker-manifest.json` | `WORKER_ASSERTION` | Hoch — Worker-Claims sind ungeprüft, niedrigste Beweiskraft |

> **[Entscheidung 2026-04-08]** Element 15 — Multi-Repo Worktree Logic ist Produktionsanforderung. `worktree_paths` (Dict: repo-id → Pfad) + `primary_repo_id` im Spawn-Vertrag. Runtime-Anforderung fuer Multi-Repo-Zielprojekte.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 15.

### 28.3.2 Multi-Repo-Contract (`RepoContext`) (FK-28-001)

AgentKit unterstützt Multi-Repo-Stories (mehrere Repositories in
einem Arbeitspaket). Der Evidence Assembler operiert daher nicht
auf einer einzelnen `repo_root: Path`, sondern auf einem Repo-Set.

```python
# agentkit/evidence/assembler.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentkit.core.git import GitOperations


@dataclass(frozen=True)
class RepoContext:
    """Kontext für ein einzelnes Repo im Assembly-Prozess.

    Args:
        repo_id: Eindeutige Kennung (z.B. "app", "docs", "frontend").
        repo_path: Worktree-Pfad oder Repository-Root.
        git: Bereits instanziierte GitOperations (single-repo per design).
        git_base_branch: Branch gegen den der Diff berechnet wird.
        role: Semantische Rolle ("app" | "docs" | "frontend" | "infra").
        affected: Ob dieses Repo von der Story betroffen ist (aus StoryContext bzw. dessen `context.json`-Export).
    """
    repo_id: str
    repo_path: Path
    git: GitOperations
    git_base_branch: str
    role: str
    affected: bool
```

**Design-Begründung:**

1. `GitOperations` ist absichtlich Single-Repo (FK-12). Ein
   `_git()`-Call ist auf ein Repo gescoped. Multi-Repo-Koordination
   gehört in die Orchestrierungsschicht — nicht in `git.py`.

2. Der Assembler iteriert über das Repo-Set:
   - Stufe 1: `_collect_changed_files()` läuft **pro Repo** und
     aggregiert die Ergebnisse.
   - Stufe 2: `ImportResolver` wird **pro Repo** instanziiert
     (jeweils mit dessen `repo_path`).
   - Stufe 3: Worker-Hints aus `handover.json` referenzieren Pfade,
     die gegen das Repo-Set aufgelöst werden.

3. **Priorisierung bei Multi-Repo:**
   - Primary-Repo-Dateien haben höhere Priorität als
     Secondary-Repo-Dateien bei gleicher `AuthorityClass`.
   - Repos mit `affected=false` werden nur für Import-Auflösung
     herangezogen, nicht für Diff-Collection.

4. **Single-Repo-Kompatibilität:** Stories ohne `worktree_paths`
im `StoryContext` bzw. dessen `context.json`-Export erzeugen ein Repo-Set mit einem einzigen
   Eintrag. Der Assembler behandelt beides uniform.

### 28.3.3 Stufe 1: Deterministischer Kern

Stufe 1 sammelt alle Evidenz, die ohne Heuristik aus dem
Dateisystem und Git ableitbar ist.

**Datenquellen pro Repo:**

| Kategorie | Methode | Authority | Beschreibung |
|-----------|---------|-----------|--------------|
| Geänderte Dateien | `_collect_changed_files()` | `PRIMARY_IMPLEMENTATION` | `git diff --name-only {base} HEAD` |
| Modul-Nachbarn | `_collect_module_neighbors()` | `SECONDARY_CONTEXT` | `__init__.py`, `schemas.py`, `protocols.py`, `config.py`, `types.py` im selben und übergeordneten Verzeichnis |
| Normative Quellen | `_collect_normative_sources()` | `PRIMARY_NORMATIVE` | Story-Spec, Concept-Docs, Guardrails aus `StoryContext` / `.story-pipeline.yaml` |
| YAML/JSON-Configs | `_collect_yaml_json_configs()` | `SECONDARY_CONTEXT` | Konfigurationsdateien im selben Modul wie geänderte Dateien |

**Diff-Basis-Ermittlung (D4, FK-28-002):**

Die Diff-Basis wird nicht hart an `"main"` festgetackert, sondern
aus dem Story-Kontext ermittelt:

```python
def _resolve_base(self, repo_ctx: RepoContext) -> str:
    """Ermittelt die korrekte Diff-Basis aus dem Story-Kontext.

    Auflösungsreihenfolge:
1. StoryContext / `context.json`-Export → `base_branch` (explizite Überschreibung)
    2. RepoContext.git_base_branch (aus Pipeline-Config)
    3. Idealerweise git merge-base für Rebase-Sicherheit
    """
    explicit = self._context_json.get("base_branch")
    if explicit:
        return explicit
    return repo_ctx.git_base_branch
```

**Nachbardateien-Heuristik:**

Für jede geänderte Datei werden strukturelle Nachbarn im selben
und im übergeordneten Verzeichnis gesammelt:

```python
NEIGHBOR_PATTERNS: tuple[str, ...] = (
    "__init__.py",
    "schemas.py",
    "protocols.py",
    "config.py",
    "types.py",
    "models.py",
    "constants.py",
)

def _collect_module_neighbors(
    self,
    changed_files: list[Path],
    repo_path: Path,
) -> list[Path]:
    """Sammelt strukturelle Nachbarn geänderter Dateien."""
    neighbors: set[Path] = set()
    seen_dirs: set[Path] = set()
    for changed in changed_files:
        for directory in (changed.parent, changed.parent.parent):
            if directory in seen_dirs or not directory.is_relative_to(repo_path):
                continue
            seen_dirs.add(directory)
            for pattern in NEIGHBOR_PATTERNS:
                candidate = directory / pattern
                if candidate.exists() and candidate not in changed_files:
                    neighbors.add(candidate)
    return sorted(neighbors)
```

### 28.3.4 Stufe 2: Sprachspezifische Import-Extraktion

Stufe 2 delegiert an den `ImportResolver` (siehe **FK-46** für die
sprachspezifischen Patterns, Confidence-Labels und das
Klassen-Design). Pro Repo wird eine Instanz erzeugt, die alle
Imports der geänderten Dateien auflöst.

```python
def _stage2_imports(self) -> list[BundleEntry]:
    """Delegiert an ImportResolver für Python/TS/Java."""
    entries: list[BundleEntry] = []
    for repo_id, repo_ctx in self._repos.items():
        if not repo_ctx.affected:
            continue
        resolver = ImportResolver(
            repos={rid: rc.repo_path for rid, rc in self._repos.items()},
        )
        for changed_file in self._changed_files_by_repo.get(repo_id, []):
            resolved = resolver.resolve(changed_file)
            for imp in resolved:
                if imp.target_file not in self._seen_paths:
                    self._seen_paths.add(imp.target_file)
                    content = imp.target_file.read_text(encoding="utf-8", errors="replace")
                    entries.append(BundleEntry(
                        repo_id=repo_id,
                        path=imp.target_file.relative_to(repo_ctx.repo_path),
                        authority=AuthorityClass.SECONDARY_CONTEXT,
                        confidence=imp.confidence,
                        reason=f"Import aus {imp.source_file.name}: {imp.import_statement}",
                        size=len(content.encode("utf-8")),
                        content=content,
                    ))
    return entries
```

### 28.3.5 Stufe 3: Worker-Hints

Stufe 3 liest `handover.json` und `worker-manifest.json` und
extrahiert vom Worker vorgeschlagene Dateien. Diese erhalten die
niedrigste Autoritätsklasse `WORKER_ASSERTION`.

```python
def _stage3_worker_hints(self) -> list[BundleEntry]:
    """Liest handover.json + worker-manifest.json, markiert als WORKER_ASSERTION."""
    ...

def _check_self_reference(self, hint_path: Path) -> bool:
    """Warnt wenn Worker Dateien vorschlägt, die er selbst geändert hat.

    Self-Referencing ist ein Warnsignal: der Worker versucht
    möglicherweise, den Reviewer mit seinen eigenen Änderungen
    als 'Kontext' zu lenken.
    """
    ...
```

**Worker-Hint-Regeln:**

1. Hints sind rein **additiv** — sie können keine Stufe-1/2-Dateien
   entfernen oder herabstufen.
2. Dateien, die bereits im Bundle sind (aus Stufe 1 oder 2), werden
   nicht dupliziert — das Hint wird ignoriert.
3. Dateien, die der Worker selbst geändert hat, erzeugen ein
   WARNING (Self-Reference-Check).

> **[Entscheidung 2026-04-08]** Element 28 — Section-aware Bundle-Packing ist Pflicht. FK-34-121 normativ. Die Priorisierung und das Bundle-Packing muessen section-aware erfolgen.
> Siehe `stories/entscheidung-v2-ballast-bewertung.md`, Element 28.

### 28.3.6 Bundle-Größenlimit und Priorisierung (FK-28-003)

Das Bundle hat ein hartes Limit von **350 KB** (unkomprimiert).
Bei Überschreitung wird nach Autoritätsklasse und innerhalb einer
Klasse nach Confidence priorisiert.

```python
BUNDLE_SIZE_LIMIT = 350 * 1024  # 350 KB unkomprimiert

def _enforce_size_limit(
    self,
    entries: list[BundleEntry],
) -> tuple[list[BundleEntry], bool]:
    """Kürzt bei >350KB nach Priorität:

    Reihenfolge (höchste Priorität zuerst):
    1. PRIMARY_NORMATIVE
    2. PRIMARY_IMPLEMENTATION
    3. SECONDARY_CONTEXT
    4. WORKER_ASSERTION

    Innerhalb einer Klasse:
    - Geänderte Dateien > direkte Imports > Heuristik-Treffer
    - Primary-Repo > Secondary-Repo (bei Multi-Repo)
    """
    sorted_entries = sorted(entries, key=lambda e: e.sort_key)
    included: list[BundleEntry] = []
    total_size = 0
    truncated = False
    for entry in sorted_entries:
        if total_size + entry.size <= BUNDLE_SIZE_LIMIT:
            included.append(entry)
            total_size += entry.size
        else:
            truncated = True
            self._warnings.append(
                f"Bundle truncated: {entry.path} ({entry.authority.name}) "
                f"excluded ({entry.size} bytes)"
            )
    return included, truncated
```

**Vollständige Klasse `EvidenceAssembler`:**

```python
# agentkit/evidence/assembler.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentkit.evidence.authority import AuthorityClass, BundleEntry
from agentkit.evidence.bundle_manifest import BundleManifest
from agentkit.evidence.import_resolver import ImportResolver


BUNDLE_SIZE_LIMIT = 350 * 1024  # 350 KB unkomprimiert


@dataclass(frozen=True)
class AssemblyResult:
    """Ergebnis der Evidence-Assembly."""
    entries: list[BundleEntry]
    manifest: BundleManifest
    total_size: int
    truncated: bool
    warnings: list[str]


class EvidenceAssembler:
    """Assembliert Review-Bundles aus deterministischen Quellen + Worker-Hints.

    Drei Stufen:
      1. Deterministischer Kern (Git-Diff + Nachbardateien + Story/Concept/Guardrails)
      2. Sprachspezifische Import-Extraktion (delegiert an ImportResolver, FK-46)
      3. Worker-Hinweise aus handover.json/worker-manifest.json (nur additiv)

    Args:
        repos: Repo-Set mit RepoContext pro Repository.
        primary_repo_id: ID des primären Repos (höhere Priorität).
        story_dir: Verzeichnis der Story-Artefakte.
context_json: Geladener `context.json`-Export eines `StoryContext`.
        pipeline_config: Geladene .story-pipeline.yaml.
    """

    def __init__(
        self,
        repos: dict[str, RepoContext],
        primary_repo_id: str,
        story_dir: Path,
        context_json: dict,
        pipeline_config: dict,
    ) -> None: ...

    def assemble(self) -> AssemblyResult:
        """Hauptmethode: Führt alle 3 Stufen aus und liefert das Bundle."""
        entries: list[BundleEntry] = []
        entries += self._stage1_deterministic()
        entries += self._stage2_imports()
        entries += self._stage3_worker_hints()
        entries = self._deduplicate(entries)
        entries, truncated = self._enforce_size_limit(entries)
        manifest = BundleManifest.from_entries(
            entries=entries,
            truncated=truncated,
            warnings=self._warnings,
        )
        return AssemblyResult(
            entries=entries,
            manifest=manifest,
            total_size=sum(e.size for e in entries),
            truncated=truncated,
            warnings=self._warnings,
        )

    # --- Stufe 1: Deterministischer Kern ---

    def _stage1_deterministic(self) -> list[BundleEntry]:
        """Git-Diff → geänderte Dateien + Nachbarn + Story/Concept/Guardrails."""
        ...

    def _collect_changed_files(self, repo_ctx: RepoContext) -> list[Path]:
        """Git diff --name-only gegen base branch, pro Repo."""
        ...

    def _collect_module_neighbors(
        self, changed_files: list[Path], repo_path: Path,
    ) -> list[Path]:
        """Strukturelle Nachbarn im selben und übergeordneten Verzeichnis."""
        ...

    def _collect_normative_sources(self) -> list[Path]:
"""Story-Spec, Concept-Docs, Guardrails aus StoryContext/context-export/pipeline-config."""
        ...

    def _collect_yaml_json_configs(
        self, changed_files: list[Path], repo_path: Path,
    ) -> list[Path]:
        """YAML/JSON-Configs im selben Modul wie geänderte Dateien."""
        ...

    # --- Stufe 2: Import-Extraktion ---

    def _stage2_imports(self) -> list[BundleEntry]:
        """Delegiert an ImportResolver für Python/TS/Java, pro Repo (FK-46)."""
        ...

    # --- Stufe 3: Worker-Hints ---

    def _stage3_worker_hints(self) -> list[BundleEntry]:
        """Liest handover.json + worker-manifest.json, markiert als WORKER_ASSERTION."""
        ...

    def _check_self_reference(self, hint_path: Path) -> bool:
        """Warnt wenn Worker Dateien vorschlägt, die er selbst geändert hat."""
        ...

    # --- Bundle-Management ---

    def _deduplicate(self, entries: list[BundleEntry]) -> list[BundleEntry]:
        """Entfernt Duplikate. Bei gleicher Datei gewinnt die höhere Authority."""
        ...

    def _enforce_size_limit(
        self, entries: list[BundleEntry],
    ) -> tuple[list[BundleEntry], bool]:
        """Kürzt bei >350KB nach Priorität."""
        ...
```

**Benötigte Git-Erweiterungen** (`agentkit/core/git.py`):

`GitOperations` hat aktuell keine `diff()`-Methode. Für den
Assembler werden drei neue Methoden benötigt, die den bestehenden
`_git()`-Mechanismus nutzen:

```python
# Erweiterung in agentkit/core/git.py

def diff_name_only(self, base: str = "main") -> list[str]:
    """Gibt Liste geänderter Dateien zurück (relativ zum Repo-Root)."""
    result = self._git("diff", "--name-only", base, "HEAD")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]

def diff_stat(self, base: str = "main") -> str:
    """Gibt diff --stat zurück (Zusammenfassung der Änderungen)."""
    result = self._git("diff", "--stat", base, "HEAD")
    return result.stdout

def diff_full(self, base: str = "main", paths: list[str] | None = None) -> str:
    """Gibt vollständigen Diff zurück, optional auf bestimmte Pfade beschränkt."""
    cmd = ["diff", base, "HEAD"]
    if paths:
        cmd += ["--"] + paths
    result = self._git(*cmd)
    return result.stdout
```

**Hinweis:** `checks_impact.py` (FK-33) nutzt bereits
`git diff --name-only` via subprocess-Direktaufruf. Nach
Implementierung der neuen Methoden wird `checks_impact.py` auf
`GitOperations.diff_name_only()` umgestellt.

## 28.4 Import-Resolver

> Stufe 2 (Sprachspezifische Import-Extraktion mit Python-,
> TypeScript- und Java-Patterns, Confidence-Labels und Vollständigkeit
> des `ImportResolver`-Klassen-Designs) ist normativ in **FK-46
> (Import-Resolver für Evidence Assembly)** beschrieben.

## 28.5 Autoritätsklassen und BundleEntry

### 28.5.1 AuthorityClass (4 Stufen) (FK-28-005)

Jede Datei im Review-Bundle erhält eine Autoritätsklasse, die
ihre Beweiskraft im Review-Prozess bestimmt:

```python
class AuthorityClass(IntEnum):
    """Autoritätsklassen, geordnet nach Priorität (höher = wichtiger).

    Die numerische Ordnung wird für die Priorisierung bei
    Bundle-Größen-Überschreitung verwendet.
    """
    WORKER_ASSERTION = 0     # Vom Worker vorgeschlagene Dateien (niedrigste Beweiskraft)
    SECONDARY_CONTEXT = 1    # Nachbardateien, Import-Ziele
    PRIMARY_IMPLEMENTATION = 2  # Geänderte Dateien (Prüfgegenstand)
    PRIMARY_NORMATIVE = 3    # Autoritative Quellen: Story-Spec, Concepts, Guardrails
```

**Semantik der Klassen:**

| Klasse | Herkunft | Beweiskraft | Review-Rolle |
|--------|----------|-------------|-------------|
| `PRIMARY_NORMATIVE` | Story-Spec, Concept-Docs, Guardrails, Architektur-Referenzen | Höchste | Die autoritativen Referenzen, gegen die geprüft wird |
| `PRIMARY_IMPLEMENTATION` | Geänderte Dateien aus Git-Diff | Hoch | Der Prüfgegenstand selbst |
| `SECONDARY_CONTEXT` | Nachbardateien, Import-Ziele, Configs | Mittel | Kontext für Verifikation (nicht-autoritativ) |
| `WORKER_ASSERTION` | Worker-Hints aus handover.json | Niedrigste | Ungeprüfte Worker-Claims — mit Vorsicht behandeln |

### 28.5.2 BundleEntry-Datenmodell (FK-28-006)

```python
# agentkit/evidence/authority.py
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from agentkit.evidence.import_resolver import ConfidenceLabel


@dataclass(frozen=True)
class BundleEntry:
    """Ein Eintrag im Review-Bundle mit Autoritätsklassifikation.

    Multi-Repo-fähig: repo_id identifiziert das Quell-Repository.

    Attributes:
        repo_id: Quell-Repository-ID.
        path: Dateipfad relativ zum jeweiligen Repo-Root.
        authority: Autoritätsklasse (bestimmt Beweiskraft und Priorität).
        confidence: Confidence-Label aus Import-Resolution (None für Stufe 1+3).
        reason: Menschenlesbare Begründung, warum diese Datei im Bundle ist.
        size: Dateigröße in Bytes.
        content: Dateiinhalt (geladen).
    """
    repo_id: str
    path: Path
    authority: AuthorityClass
    confidence: ConfidenceLabel | None
    reason: str
    size: int
    content: str

    @property
    def sort_key(self) -> tuple[int, int]:
        """Für Priorisierung: (authority descending, confidence descending).

        Nutzt eine explizite Ranking-Tabelle statt hash() für
        deterministische und semantisch korrekte Sortierung.
        """
        conf_rank = (
            CONFIDENCE_PRIORITY.get(self.confidence, 0)
            if self.confidence else 0
        )
        return (-self.authority.value, -conf_rank)
```

### 28.5.3 BundleManifest (FK-28-007)

Das `BundleManifest` ist die Zusammenfassung des assemblierten
Bundles. Es wird als JSON-Artefakt geschrieben und als Header
in den Review-Prompt eingefügt.

```python
# agentkit/evidence/bundle_manifest.py
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from agentkit.evidence.authority import AuthorityClass, BundleEntry


@dataclass(frozen=True)
class BundleManifest:
    """Zusammenfassung des assemblierten Bundles.

    Wird als Header in den Review-Prompt eingefügt und
    als JSON-Artefakt geschrieben.

    Attributes:
        entries: Alle BundleEntry-Objekte.
        total_size: Gesamtgröße in Bytes.
        truncated: Ob das Bundle gekürzt wurde.
        warnings: Warnungen während der Assembly.
        evidence_epoch: ISO 8601 Timestamp der Assembly (D2).
        manifest_hash: SHA-256 über sortierte Dateipfade + Größen (D2).
    """
    entries: list[BundleEntry]
    total_size: int
    truncated: bool
    warnings: list[str]
    evidence_epoch: str
    manifest_hash: str

    @staticmethod
    def from_entries(
        entries: list[BundleEntry],
        truncated: bool,
        warnings: list[str],
    ) -> BundleManifest:
        """Factory-Methode: Berechnet evidence_epoch und manifest_hash."""
        epoch = datetime.now(timezone.utc).isoformat()
        hash_input = "|".join(
            f"{e.repo_id}:{e.path}:{e.size}"
            for e in sorted(entries, key=lambda e: (e.repo_id, str(e.path)))
        )
        manifest_hash = hashlib.sha256(hash_input.encode()).hexdigest()
        return BundleManifest(
            entries=entries,
            total_size=sum(e.size for e in entries),
            truncated=truncated,
            warnings=warnings,
            evidence_epoch=epoch,
            manifest_hash=manifest_hash,
        )

    @property
    def file_paths(self) -> list[Path]:
        """Alle Dateipfade im Bundle — für merge_paths-Nutzung."""
        return [entry.path for entry in self.entries]

    def render_prompt_header(self) -> str:
        """Erzeugt den strukturierten Bundle-Header für den Review-Prompt.

        Format:
        ## Bundle-Inhalt
        ### PRIMARY_NORMATIVE (autoritative Quellen — höchste Beweiskraft)
        - datei.md (Grund)
        ...
        """
        sections: dict[AuthorityClass, list[str]] = {}
        for entry in self.entries:
            sections.setdefault(entry.authority, []).append(
                f"- {entry.path.name} ({entry.reason})"
            )
        lines = ["## Bundle-Inhalt\n"]
        labels = {
            AuthorityClass.PRIMARY_NORMATIVE:
                "PRIMARY_NORMATIVE (autoritative Quellen — höchste Beweiskraft)",
            AuthorityClass.PRIMARY_IMPLEMENTATION:
                "PRIMARY_IMPLEMENTATION (geänderte Dateien — Prüfgegenstand)",
            AuthorityClass.SECONDARY_CONTEXT:
                "SECONDARY_CONTEXT (Nachbarquellen — für Verifikation)",
            AuthorityClass.WORKER_ASSERTION:
                "WORKER_ASSERTION (Worker-Claims — niedrigste Beweiskraft)",
        }
        for auth_class in sorted(labels.keys(), key=lambda x: -x.value):
            if auth_class in sections:
                lines.append(f"### {labels[auth_class]}")
                lines.extend(sections[auth_class])
                lines.append("")
        lines.append(f"Evidence-Epoch: {self.evidence_epoch}")
        lines.append(f"Manifest-Hash: {self.manifest_hash[:16]}...")
        return "\n".join(lines)
```

### 28.5.4 Evidence-Epoch (D2) (FK-28-008)

Jedes assemblierte Bundle erhält eine eingefrorene
Evidenz-Identität, bestehend aus:

| Feld | Typ | Zweck |
|------|-----|-------|
| `evidence_epoch` | `str` (ISO 8601) | Zeitpunkt der Assembly — Audit-Bindung |
| `manifest_hash` | `str` (SHA-256) | Deterministische Prüfsumme über Inhalt — Integritätsnachweis |

Diese Werte werden in das Manifest-Artefakt geschrieben und in
Preflight-Response, Review-Response und Divergenz-Telemetrie
(FK-14) referenziert. So ist nachvollziehbar, auf welcher
Evidenzbasis jeder Reviewer gearbeitet hat.

**Hash-Berechnung:**

```python
hash_input = "|".join(
    f"{e.repo_id}:{e.path}:{e.size}"
    for e in sorted(entries, key=lambda e: (e.repo_id, str(e.path)))
)
manifest_hash = hashlib.sha256(hash_input.encode()).hexdigest()
```

Der Hash ist deterministisch: gleiche Dateien in gleicher
Zusammensetzung erzeugen denselben Hash, unabhängig von der
Reihenfolge der Assembly-Stufen.

## 28.6 Request-DSL und Preflight-Turn

> Die 7 Request-Typen, der `RequestResolver` (Multi-Repo), die
> Mehrdeutigkeitsregel D3, die Preflight-Turn-Architektur und das
> Prompt-Template `review-preflight.md` sind normativ in **FK-47
> (Request-DSL und Preflight-Turn)** beschrieben.

## 28.7 CLI-Surface

### 28.7.1 `agentkit evidence assemble` (FK-28-014)

Worker-Templates referenzieren `agentkit evidence assemble` als
CLI-Command. AgentKit CLI nutzt manuelles argparse-Subparser-Wiring
(FK-43). Der neue Command wird als Subparser registriert.

**Command-Signatur:**

```
agentkit evidence assemble \
  --story-id ODIN-042 \
  --story-dir ./stories/ODIN-042 \
  --output-dir ./stories/ODIN-042/qa \
  [--config .story-pipeline.yaml]
```

**Parameter:**

| Parameter | Pflicht | Beschreibung |
|-----------|---------|--------------|
| `--story-id` | Ja | Story-ID für Telemetrie und Artefakt-Benennung |
| `--story-dir` | Ja | Verzeichnis der Story-Artefakt-Exporte (enthaelt optional `context.json`) |
| `--output-dir` | Ja | Zielverzeichnis für `bundle_manifest.json` und assemblierte Dateien |
| `--config` | Nein | Pfad zur `.story-pipeline.yaml` (Default: `.story-pipeline.yaml` im Repo-Root) |

**Handler-Logik:**

```python
# In agentkit/cli.py — Neuer Subparser

def _register_evidence_commands(subparsers) -> None:
    """Registriert den 'evidence' Subparser mit Sub-Subcommand 'assemble'."""
    evidence_parser = subparsers.add_parser("evidence", help="Evidence Assembly Commands")
    evidence_sub = evidence_parser.add_subparsers(dest="evidence_command")

    assemble_parser = evidence_sub.add_parser(
        "assemble",
        help="Assembliert das Review-Bundle aus deterministischen Quellen",
    )
    assemble_parser.add_argument("--story-id", required=True)
    assemble_parser.add_argument("--story-dir", required=True, type=Path)
    assemble_parser.add_argument("--output-dir", required=True, type=Path)
    assemble_parser.add_argument("--config", type=Path, default=None)
    assemble_parser.set_defaults(func=_handle_evidence_assemble)


def _handle_evidence_assemble(args) -> int:
    """Handler für 'agentkit evidence assemble'.

1. Lädt `context.json`-Export aus `--story-dir` oder nutzt direkt `StoryContext`
2. Baut RepoContext-Set aus `repos[]` + `worktree_paths`
    3. Instanziiert EvidenceAssembler mit Multi-Repo-API
    4. Ruft assemble() auf
    5. Schreibt bundle_manifest.json in --output-dir
    6. Gibt Exit-Code 0 bei Erfolg, 1 bei Fehler zurück
    """
    ...
```

**Begründung für CLI-Variante (statt reiner Python-API):**

1. Konsistent mit bestehenden Commands (`structural`, `policy`,
   `verify`) — einheitliche Nutzungsschnittstelle.
2. Nutzbar in Worker-Prompts UND manuell/debugging.
3. Testbar über Integrationstests mit subprocess.

## 28.8 Integration in den Review-Flow

### 28.8.1 Ablauf: Assembly → Preflight → Resolution → Review (FK-28-015)

Der vollständige Review-Flow mit Evidence Assembly:

```mermaid
flowchart TD
    START["Story in Verify-Phase"] --> L1["Schicht 1: Deterministische Checks<br/>(FK-33)"]
    L1 -->|PASS| ASSEMBLE["EvidenceAssembler.assemble()"]
    L1 -->|FAIL| FAIL_L1["→ Feedback + Remediation"]

    ASSEMBLE --> MANIFEST["BundleManifest erstellt<br/>evidence_epoch + manifest_hash"]

    MANIFEST --> PREFLIGHT["Preflight-Turn<br/>(MCP Pool Send) — FK-47"]
    PREFLIGHT --> PARSE["parse_preflight_response() — FK-47"]

    PARSE -->|Requests vorhanden| RESOLVE["RequestResolver.resolve_all() — FK-47"]
    PARSE -->|Keine Requests| REVIEW

    RESOLVE --> EXTEND["merge_paths erweitern<br/>+ BUNDLE_HEADER aktualisieren"]
    EXTEND --> REVIEW

    REVIEW["Review-Turn<br/>(MCP Pool Send mit erweitertem Bundle)"]
    REVIEW --> L2["Schicht 2: LLM-Bewertungen<br/>(FK-34)"]
    L2 -->|PASS| L3["Schicht 3: Adversarial<br/>(FK-34)"]
    L2 -->|FAIL| FAIL_L2["→ Feedback + Remediation"]
    L3 --> L4["Schicht 4: Policy-Engine<br/>(FK-33)"]
```

**Zeitliche Einordnung:**

Die Evidence Assembly läuft **nach** Schicht 1 (deterministische
Checks) und **vor** Schicht 2 (LLM-Bewertungen). Sie ist selbst
ein deterministischer Schritt — kein LLM beteiligt. Der
Preflight-Turn (FK-47) ist der erste LLM-Kontakt im Review-Flow.

### 28.8.2 Worker-Template-Aenderungen (FK-28-016)

`worker-implementation.md` und `worker-bugfix.md` erhalten in
der DoD-Review-Sektion eine Anweisung, den Evidence Assembler
(`agentkit evidence assemble`) statt eigener `merge_paths`-Kuration
zu verwenden. Der Assembler:

1. Ermittelt geänderte Dateien aus Git-Diff
2. Sammelt normative Quellen (Story-Spec, Concepts, Guardrails)
3. Löst Imports auf und fügt Nachbar-Dateien hinzu (FK-46)
4. Integriert Worker-Hinweise aus handover.json (additiv)
5. Klassifiziert alles nach Autoritätsklasse
6. Kürzt bei >350 KB nach Priorität

### 28.8.3 Bestehende Review-Template-Erweiterungen (FK-28-017)

Alle Review-Templates in `userstory/prompts/sparring/` erhalten
den `{{BUNDLE_MANIFEST_HEADER}}`-Platzhalter, der vom Evidence
Assembler befüllt wird. Das ersetzt die bisherige unstrukturierte
Einleitung.

**Betroffene Templates:**

| Template | Aenderung |
|----------|----------|
| `review-consolidated.md` | `{{BUNDLE_MANIFEST_HEADER}}` einfügen |
| `review-spec-compliance.md` | `{{BUNDLE_MANIFEST_HEADER}}` einfügen |
| `review-implementation.md` | `{{BUNDLE_MANIFEST_HEADER}}` einfügen |
| `review-test-sparring.md` | `{{BUNDLE_MANIFEST_HEADER}}` einfügen |
| `review-synthesis.md` | `{{BUNDLE_MANIFEST_HEADER}}` einfügen |

**Prompt-Header nach Preflight erweitern (D5, FK-28-018):**

Nach dem Preflight-Turn (FK-47) und der Request-Auflösung wird der
Prompt-Header für den eigentlichen Review um einen neuen
Abschnitt erweitert:

```markdown
### Nachgereichte Reviewer-Requests

Die folgenden Dateien wurden auf deine Preflight-Anfrage nachgeliefert:

| Request | Status | Datei |
|---------|--------|-------|
| NEED_FILE: utils/helpers.py | RESOLVED | utils/helpers.py (SECONDARY_CONTEXT) |
| NEED_SCHEMA: ConfigModel | RESOLVED | core/config.py (SECONDARY_CONTEXT) |
| NEED_CALLSITE: process_event | UNRESOLVED (nicht auflösbar) | — |
```

Aufgelöste Dateien erhalten die Autoritätsklasse
`SECONDARY_CONTEXT`. Es wird keine neue Autoritätsklasse
eingeführt. UNRESOLVED-Requests werden dem Reviewer explizit
als "nicht auflösbar" mitgeteilt.

## 28.9 Test-Strategie (FK-28-019)

| Modul | Testart | Schwerpunkt | Fixture |
|-------|---------|-------------|---------|
| `import_resolver.py` (FK-46) | Unit-Tests mit echten Dateistrukturen | Regex-Patterns für alle 3 Sprachen, Alias-Auflösung, Barrel-Folgen, Spring-Heuristiken | `tmp_path`-Fixtures mit Dateistrukturen pro Sprache |
| `assembler.py` | Integrationstests mit Git-Repo-Fixture | Stufe 1 Vollständigkeit, 350 KB Limit, Priorisierung, Worker-Hint-Warnung, **Multi-Repo-Fixture** | `@pytest.mark.requires_git`, echtes Git-Repo mit Commits |
| `authority.py` | Unit-Tests | Sortierung (explizite CONFIDENCE_PRIORITY-Tabelle), `BundleEntry.sort_key` | Keine externen Fixtures |
| `bundle_manifest.py` | Unit-Tests | `file_paths`-Property, `render_prompt_header()`, `evidence_epoch`/`manifest_hash`-Berechnung | Keine externen Fixtures |
| `request_resolver.py` (FK-47) | Unit + Integration | Alle 7 Request-Typen, Timeout-Handling, UNRESOLVED-Verhalten, Mehrdeutigkeitsregel (D3) | `tmp_path`, `@pytest.mark.requires_git` |
| `request_resolver.py` (`parse_preflight_response`, FK-47) | Unit-Tests | Valides JSON, invalides JSON → leere Liste + WARNING, Randfälle (leerer String, None, kein `requests`-Key) | Keine externen Fixtures |
| `git.py` (Erweiterung) | Unit-Tests | `diff_name_only`, `diff_stat`, `diff_full` | `@pytest.mark.requires_git` |

**Multi-Repo-Test-Fixture:**

Für Integrationstests des Assemblers wird eine Fixture benötigt,
die mehrere Git-Repos mit Commits, Branches und Dateien aufbaut:

```python
@pytest.fixture
def multi_repo_fixture(tmp_path: Path) -> dict[str, RepoContext]:
    """Erstellt zwei Git-Repos (primary + secondary) mit Commits.

    primary/
      ├── src/main.py  (geändert)
      ├── src/utils.py (Nachbar)
      └── config.yaml
    secondary/
      ├── lib/shared.py
      └── lib/types.py
    """
    ...
```

**Coverage-Erwartung:** Alle neuen Module >= 85%
(`fail_under = 85` in `pyproject.toml`).

## 28.10 Design-Entscheidungen

### 28.10.1 D2: Evidence-Epoch als Audit-Bindung (FK-28-020)

**Entscheidung:** Jedes assemblierte Bundle erhält eine eingefrorene
Evidenz-Identität (`evidence_epoch` + `manifest_hash`).

**Begründung:**

- Nachvollziehbarkeit: Review-Ergebnisse sind an eine konkrete
  Evidenzbasis gebunden. Wenn sich das Bundle zwischen Preflight
  und Review ändert (z.B. durch parallele Commits), ist das
  erkennbar.
- Audit-Compliance: Die Verify-Phase muss nachweisen können, auf
  welcher Basis ein PASS/FAIL entstanden ist.
- Divergenz-Analyse: Wenn zwei Reviewer auf demselben
  `manifest_hash` unterschiedliche Ergebnisse liefern, ist die
  Divergenz inhaltlich (nicht evidenzbasiert).

**Alternative verworfen:** Kein Evidence-Epoch — Review-Ergebnisse
wären nicht an eine Evidenzbasis gebunden, Divergenz-Ursachen
wären nicht unterscheidbar.

### 28.10.2 D3: Resolver-Mehrdeutigkeitsregel (FK-28-021)

**Entscheidung:** Bei mehreren Treffern für einen Request wird
`UNRESOLVED` mit Kandidatenliste zurückgegeben. Der Resolver wählt
bei Mehrdeutigkeit NICHT eigenständig aus. Detail in FK-47 §47.4.

**Begründung:**

- Determinismus: Eine Heuristik ("nimm den ersten Treffer") würde
  von der Datei-Reihenfolge abhängen, die zwischen Systemen
  variieren kann.
- Transparenz: Der Reviewer sieht die Kandidaten und kann selbst
  entscheiden, welche Datei relevant ist.
- Sicherheit: Falsches Heuristik-Picking könnte den Reviewer in
  die Irre führen.

**Alternative verworfen:** "Nearest-File"-Heuristik (nächste Datei
zum geänderten Code gewinnt) — nicht sprachübergreifend definierbar,
potentiell irreführend.

### 28.10.3 D4: Diff-Basis aus Story-Kontext (FK-28-022)

**Entscheidung:** Die Diff-Basis wird nicht hart an `"main"`
festgetackert, sondern aus dem Story-Kontext ermittelt:
1. `StoryContext` / `context.json`-Export → `base_branch` (explizite Überschreibung)
2. `RepoContext.git_base_branch` (aus Pipeline-Config)
3. `git merge-base` für Rebase-Sicherheit

**Begründung:**

- Release-Branches: Stories gegen `release/v2.x` müssen den Diff
  gegen den Release-Branch berechnen, nicht gegen `main`.
- Rebase-Sicherheit: `git merge-base` liefert die korrekte
  Verzweigungsbasis auch nach Rebases.
- Konfigurierbarkeit: Verschiedene Repos im selben Arbeitspaket
  können unterschiedliche Base-Branches haben.

**Alternative verworfen:** Hardcoded `"main"` — funktioniert nicht
für Release-Branches und Multi-Branch-Workflows.

### 28.10.4 D5: Prompt-Header nach Preflight erweitern (FK-28-023)

**Entscheidung:** Nach dem Preflight-Turn (FK-47) wird der
Review-Prompt um einen Abschnitt "Nachgereichte Reviewer-Requests"
erweitert. Aufgelöste Dateien erhalten `SECONDARY_CONTEXT` — keine
neue Autoritätsklasse.

**Begründung:**

- Transparenz: Der Reviewer sieht explizit, welche seiner Requests
  aufgelöst wurden und welche nicht.
- Keine Authority-Inflation: Eine fünfte Autoritätsklasse
  (z.B. `REVIEWER_REQUESTED`) würde die Priorisierungslogik
  verkomplizieren ohne semantischen Mehrwert.
- UNRESOLVED-Sichtbarkeit: Der Reviewer muss wissen, dass
  bestimmte Informationen nicht verfügbar sind — damit er seine
  Bewertung entsprechend einschränkt.

**Alternative verworfen:** Eigene Autoritätsklasse
`REVIEWER_REQUESTED` — würde die 4-Stufen-Hierarchie durchbrechen
und die Priorisierung in `_enforce_size_limit()` verkomplizieren.
