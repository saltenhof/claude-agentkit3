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
    reason: Stufe-2-Eingliederung in den Evidence Assembler liegt in FK-28 §28.3
  - target: FK-12
    scope: git-operations
    reason: GitOperations und Multi-Repo-Kontext in FK-12
supersedes: []
superseded_by:
tags: [evidence-assembly, import-resolution, authority-classes, review-preparation]
formal_scope: prose-only
---

# 46 — Import-Resolver für Evidence Assembly

## 46.1 Zweck

Der Import-Resolver ist das zentrale Modul für **Stufe 2** der
Evidence Assembly (FK-28 §28.3). Er arbeitet ausschließlich mit
Regex und Dateisystem-Operationen — kein AST-Framework, keine
externen Abhängigkeiten. Eingangsmenge sind die geänderten Dateien
aus dem Git-Diff (Stufe 1); Ausgangsmenge sind aufgelöste
Nachbar-Dateien mit Confidence-Label, die als
`SECONDARY_CONTEXT` in den BundleEntry-Strom des Assemblers
einfließen (FK-28 §28.5).

## 46.2 Python-Resolver

**Regex-Pattern:**

```python
PY_IMPORT = re.compile(
    r'^(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))',
    re.MULTILINE,
)
```

**Auflösungsstrategie:**

1. Extrahiere alle `from X import Y` und `import X` Statements.
2. Konvertiere Dotted-Path zu Dateipfad relativ zum Repo-Root
   (z.B. `agentkit.core.git` → `agentkit/core/git.py`).
3. Prüfe: Existiert die Zieldatei?
   - Ja → `RESOLVED_IMPORT`
   - Nein, aber Package-`__init__.py` existiert → `RESOLVED_IMPORT`
     (auf das Package)
   - Nein → Verwerfen (wahrscheinlich stdlib oder Third-Party)

```python
def _resolve_python(self, source: Path) -> list[ResolvedImport]:
    """from X import Y / import X → Dateipfade.

    Sucht zuerst im Source-Repo, dann cross-repo.
    Stdlib- und Third-Party-Imports werden verworfen
    (keine Datei im Repo-Set → kein Treffer).
    """
    content = source.read_text(encoding="utf-8", errors="replace")
    results: list[ResolvedImport] = []
    for match in PY_IMPORT.finditer(content):
        module_path = match.group(1) or match.group(2)
        if not module_path:
            continue
        # Dotted-Path → Dateipfad
        parts = module_path.split(".")
        for repo_id, repo_path in self._repos.items():
            # Versuch 1: als Modul-Datei
            candidate = repo_path / Path(*parts).with_suffix(".py")
            if candidate.exists():
                results.append(ResolvedImport(
                    source_file=source,
                    target_file=candidate,
                    import_statement=match.group(0),
                    confidence=ConfidenceLabel.RESOLVED_IMPORT,
                ))
                break
            # Versuch 2: als Package (__init__.py)
            candidate_pkg = repo_path / Path(*parts) / "__init__.py"
            if candidate_pkg.exists():
                results.append(ResolvedImport(
                    source_file=source,
                    target_file=candidate_pkg,
                    import_statement=match.group(0),
                    confidence=ConfidenceLabel.RESOLVED_IMPORT,
                ))
                break
    return results
```

## 46.3 TypeScript-Resolver (inkl. JS/JSX/TSX)

**6 Pattern-Klassen:**

```python
# Static Import: import { X } from 'path' / import X from 'path'
TS_STATIC_IMPORT = re.compile(
    r'''import\s+(?:type\s+)?'''
    r'''(?:\{[^}]*\}|[\w*]+(?:\s*,\s*\{[^}]*\})?)\s+from\s+['"]([^'"]+)['"]''',
    re.MULTILINE,
)

# Side-Effect Import: import 'path'
TS_SIDE_EFFECT = re.compile(
    r'''import\s+['"]([^'"]+)['"]''',
    re.MULTILINE,
)

# Re-Export: export * from 'path' / export { X } from 'path'
TS_REEXPORT = re.compile(
    r'''export\s+(?:\*|\{[^}]*\})\s+from\s+['"]([^'"]+)['"]''',
    re.MULTILINE,
)

# CommonJS Require: require('path') / import X = require('path')
TS_REQUIRE = re.compile(
    r'''(?:import\s+\w+\s*=\s*)?require\s*\(\s*['"]([^'"]+)['"]\s*\)''',
    re.MULTILINE,
)

# Dynamic Import: import('path')
TS_DYNAMIC = re.compile(
    r'''import\s*\(\s*['"]([^'"]+)['"]\s*\)''',
    re.MULTILINE,
)
```

**Auflösungsstrategie:**

```python
def _resolve_typescript(self, source: Path) -> list[ResolvedImport]:
    """6 Pattern-Klassen für TS/JS/TSX/JSX."""
    content = source.read_text(encoding="utf-8", errors="replace")
    results: list[ResolvedImport] = []

    patterns = [
        (TS_STATIC_IMPORT, ConfidenceLabel.RESOLVED_IMPORT),
        (TS_SIDE_EFFECT, ConfidenceLabel.RESOLVED_IMPORT),
        (TS_REEXPORT, ConfidenceLabel.RESOLVED_IMPORT),
        (TS_REQUIRE, ConfidenceLabel.RESOLVED_IMPORT),
        (TS_DYNAMIC, ConfidenceLabel.UNRESOLVED_DYNAMIC),
    ]
    for pattern, default_confidence in patterns:
        for match in pattern.finditer(content):
            specifier = match.group(1)
            resolved = self._resolve_ts_specifier(specifier, source)
            if resolved:
                confidence = default_confidence
                # Alias-Auflösung hat eigenes Label
                if self._is_alias(specifier, source):
                    confidence = ConfidenceLabel.RESOLVED_ALIAS
                results.append(ResolvedImport(
                    source_file=source,
                    target_file=resolved,
                    import_statement=match.group(0),
                    confidence=confidence,
                ))
    return results
```

**Specifier-Auflösung:**

```python
def _resolve_ts_specifier(self, specifier: str, source: Path) -> Path | None:
    """Alias-Auflösung → Kandidatenliste → erste existierende Datei.

    Auflösungsreihenfolge:
    1. Prüfe ob relativer Pfad (./ oder ../)
    2. Prüfe tsconfig/jsconfig paths (Alias-Match)
    3. Kandidaten: .ts, .tsx, .js, .jsx, .d.ts, /index.ts, /index.tsx
    4. Prüfe ob Barrel (index.ts) → eine Ebene tief folgen
    """
    ...

def _load_tsconfig(self, source: Path) -> dict | None:
    """Nächstes tsconfig.json/jsconfig.json aufwärts suchen, cached."""
    ...

def _resolve_barrel(
    self, barrel_file: Path, named_import: str | None,
) -> list[ResolvedImport]:
    """export * from / export {...} from → eine Ebene tief."""
    ...
```

**Barrel-Auflösung:** Wenn ein Specifier auf eine `index.ts`
(Barrel) zeigt, wird das Barrel **eine Ebene tief** gefolgt, um
die eigentlichen Quelldateien zu finden. Re-Exports in der Barrel
erhalten `ConfidenceLabel.BARREL_CONTEXT`.

## 46.4 Java-Resolver (inkl. Spring-Heuristiken)

**Regex-Patterns:**

```python
# Standard-Import
JAVA_IMPORT = re.compile(
    r'^import\s+(?:static\s+)?([\w.]+(?:\.\*)?)\s*;',
    re.MULTILINE,
)

# Package-Deklaration
JAVA_PACKAGE = re.compile(
    r'^package\s+([\w.]+)\s*;',
    re.MULTILINE,
)

# Spring-Annotations mit Scan-Konfiguration
SPRING_SCAN = re.compile(
    r'@(?:SpringBootApplication|ComponentScan|Import|EntityScan|EnableJpaRepositories)'
    r'\s*\(([^)]*)\)',
    re.MULTILINE | re.DOTALL,
)
```

**4 Import-Formen:**

| Form | Beispiel | Auflösung |
|------|---------|-----------|
| Expliziter Import | `import com.acme.Foo;` | `com/acme/Foo.java` (Maven/Gradle-Konvention) |
| Star-Import | `import com.acme.*;` | Alle `.java`-Dateien im Package |
| Static Import | `import static com.acme.Foo.BAR;` | `com/acme/Foo.java` |
| Same-Package-Referenz | `extends BaseService` | Package-Index-Lookup |

**Package-Index:**

Der Java-Resolver baut einmal pro Assembly einen repoweiten
Package-Index auf (gecached):

```python
def _build_java_package_index(self) -> dict[str, list[Path]]:
    """Repoweiter package → Dateien-Index. Einmal pro Assembly gecached.

    Scannt alle .java-Dateien, extrahiert das package-Statement,
    und baut einen Index auf: package_name → [datei1.java, datei2.java]
    """
    index: dict[str, list[Path]] = {}
    for repo_path in self._repos.values():
        for java_file in repo_path.rglob("*.java"):
            content = java_file.read_text(encoding="utf-8", errors="replace")
            match = JAVA_PACKAGE.search(content)
            if match:
                package = match.group(1)
                index.setdefault(package, []).append(java_file)
    return index
```

**Spring-Heuristiken:**

```python
def _resolve_spring_annotations(self, source: Path) -> list[ResolvedImport]:
    """Erkennt @SpringBootApplication, @ComponentScan, @Import,
    @EntityScan, @EnableJpaRepositories.

    Auflösung:
    - Ohne scanBasePackages: Base-Package der annotierten Klasse
    - Mit scanBasePackages: Die angegebenen Packages
    - Alle Dateien in den Scan-Packages → SPRING_SCAN_HEURISTIC
    """
    ...
```

**Same-Package-Heuristik:**

```python
def _resolve_same_package(
    self, source: Path, package: str,
) -> list[ResolvedImport]:
    """Typnamen in extends/implements/Felder gegen Package-Index matchen.

    Erkennt Referenzen auf Klassen im selben Package, die ohne
    expliziten Import nutzbar sind (Java-Spezifikation).
    Confidence: SAME_PACKAGE_HEURISTIC.
    """
    ...
```

## 46.5 Confidence Labels (FK-28-004)

Jeder aufgelöste Import erhält ein Confidence Label, das die
Zuverlässigkeit der Auflösung quantifiziert:

```python
class ConfidenceLabel(StrEnum):
    """Zuverlässigkeit der Auflösung — bestimmt die Priorisierung
    bei Bundle-Größen-Überschreitung."""
    RESOLVED_IMPORT = "RESOLVED_IMPORT"             # Direkter Import, Datei existiert
    RESOLVED_ALIAS = "RESOLVED_ALIAS"               # Über tsconfig-Alias aufgelöst
    BARREL_CONTEXT = "BARREL_CONTEXT"                # Über Barrel/Index-Datei aufgelöst
    SAME_PACKAGE_HEURISTIC = "SAME_PACKAGE_HEURISTIC"  # Java Same-Package-Referenz
    SPRING_SCAN_HEURISTIC = "SPRING_SCAN_HEURISTIC"    # Spring Component Scan
    UNRESOLVED_DYNAMIC = "UNRESOLVED_DYNAMIC"          # Dynamic Import — nicht auflösbar
```

**Priorisierungstabelle:**

| Label | Priorität | Beschreibung |
|-------|-----------|--------------|
| `RESOLVED_IMPORT` | 5 (höchste) | Expliziter Import, Zieldatei existiert |
| `RESOLVED_ALIAS` | 4 | Über Alias aufgelöst (tsconfig paths) |
| `BARREL_CONTEXT` | 3 | Über Barrel/Index eine Ebene tief gefolgt |
| `SAME_PACKAGE_HEURISTIC` | 2 | Java-Referenz im selben Package |
| `SPRING_SCAN_HEURISTIC` | 1 | Spring Component Scan (breiteste Heuristik) |
| `UNRESOLVED_DYNAMIC` | 0 (niedrigste) | Dynamic Import — wird gesammelt, aber niedrig priorisiert |

```python
CONFIDENCE_PRIORITY: dict[ConfidenceLabel, int] = {
    ConfidenceLabel.RESOLVED_IMPORT: 5,
    ConfidenceLabel.RESOLVED_ALIAS: 4,
    ConfidenceLabel.BARREL_CONTEXT: 3,
    ConfidenceLabel.SAME_PACKAGE_HEURISTIC: 2,
    ConfidenceLabel.SPRING_SCAN_HEURISTIC: 1,
    ConfidenceLabel.UNRESOLVED_DYNAMIC: 0,
}
```

**Vollständiges Klassen-Design:**

```python
# agentkit/evidence/import_resolver.py
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class ConfidenceLabel(StrEnum):
    """Zuverlässigkeit der Auflösung."""
    RESOLVED_IMPORT = "RESOLVED_IMPORT"
    RESOLVED_ALIAS = "RESOLVED_ALIAS"
    BARREL_CONTEXT = "BARREL_CONTEXT"
    SAME_PACKAGE_HEURISTIC = "SAME_PACKAGE_HEURISTIC"
    SPRING_SCAN_HEURISTIC = "SPRING_SCAN_HEURISTIC"
    UNRESOLVED_DYNAMIC = "UNRESOLVED_DYNAMIC"


@dataclass(frozen=True)
class ResolvedImport:
    """Ein aufgelöster Import mit Confidence-Label."""
    source_file: Path       # Datei die den Import enthält
    target_file: Path       # Aufgelöste Zieldatei
    import_statement: str   # Originaler Import-String
    confidence: ConfidenceLabel


class ImportResolver:
    """Sprachspezifische Import-Extraktion.

    Erkennt die Sprache anhand der Dateiendung und delegiert
    an den passenden Resolver. Multi-Repo: sucht zuerst im
    Source-Repo, dann cross-repo.

    Args:
        repos: Mapping repo_id → repo_path.
            Import-Auflösung braucht nur Dateisystem-Zugriff,
            kein Git, kein Branch, keine Rolle.
    """

    LANGUAGE_MAP: dict[str, str] = {
        ".py": "_resolve_python",
        ".ts": "_resolve_typescript",
        ".tsx": "_resolve_typescript",
        ".js": "_resolve_typescript",
        ".jsx": "_resolve_typescript",
        ".java": "_resolve_java",
    }

    def __init__(self, repos: dict[str, Path]) -> None:
        self._repos = repos
        self._tsconfig_cache: dict[Path, dict] = {}
        self._java_package_index: dict[str, list[Path]] | None = None

    def resolve(self, source_file: Path) -> list[ResolvedImport]:
        """Löst alle Imports einer Datei auf."""
        suffix = source_file.suffix
        handler_name = self.LANGUAGE_MAP.get(suffix)
        if handler_name is None:
            return []
        handler = getattr(self, handler_name)
        return handler(source_file)

    # --- Python ---
    def _resolve_python(self, source: Path) -> list[ResolvedImport]: ...

    # --- TypeScript (+ JS/JSX/TSX) ---
    def _resolve_typescript(self, source: Path) -> list[ResolvedImport]: ...
    def _load_tsconfig(self, source: Path) -> dict | None: ...
    def _resolve_ts_specifier(self, specifier: str, source: Path) -> Path | None: ...
    def _resolve_barrel(
        self, barrel_file: Path, named_import: str | None,
    ) -> list[ResolvedImport]: ...

    # --- Java ---
    def _resolve_java(self, source: Path) -> list[ResolvedImport]: ...
    def _build_java_package_index(self) -> dict[str, list[Path]]: ...
    def _resolve_java_import(self, import_stmt: str) -> Path | None: ...
    def _resolve_same_package(
        self, source: Path, package: str,
    ) -> list[ResolvedImport]: ...
    def _resolve_spring_annotations(self, source: Path) -> list[ResolvedImport]: ...
```
