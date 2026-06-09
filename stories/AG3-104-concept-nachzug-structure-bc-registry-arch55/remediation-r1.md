# AG3-104 — Remediation R1 (nach giftiger Codex-Review `review-r1.md`)

Doc-only/Concept-Alignment. Jede Aufloesung gleicht **Prosa an die Code-Realitaet** an
und routet reine Code-Fixes namentlich an die owning Code-Story bzw. (wo kein
Backlog-Owner existiert) an eine benannte PO-Eskalation. **Keine** Produktionscode-,
Test- oder Konzept-Datei wurde in dieser Remediation veraendert; geaendert wurde
ausschliesslich `stories/AG3-104-*/story.md` (+ dieser Report). Die eigentliche
FK-/PROJECT_STRUCTURE-Prosa-Aenderung ist Scope der Story-Execution nach Freigabe;
die Story beschreibt sie jetzt praezise und self-consistent.

## Finding -> Resolution

### Konzept-Vollstaendigkeit (ERROR)

**F1 — BC-Registry nicht scharf: PROJECT_STRUCTURE „16" vs. `bounded-contexts.yaml` kennt `harness-integration`.**
Belegt: `PROJECT_STRUCTURE.md:89` („16 BCs"), Baum `:93`–`:204` (BC 1–16) und Tabelle `:274`–`:289` fuehren `harness-integration` nicht; `bounded-contexts.yaml:245-265` kennt den BC samt `owns`-Liste.
Resolution: Scope 3 + AC2 verlangen jetzt **drei** konsistente Nachzuege in PROJECT_STRUCTURE.md — Zaehlung `:89` (16 -> 17), Baum-Aufzaehlung und Verantwortungstabelle. „Zaehlung, Baum und Verantwortungstabelle konsistent" ist woertlich AC2.

**F2 — ARCH-55 unvollstaendig gespiegelt (nur `pattern.py`).**
Verifiziert: zusaetzliche deutsche Werte real vorhanden — `check_proposal.py:56-58` (`FalsePositiveRisk` niedrig/mittel/hoch) und SQLite-CHECK-Constraints `sqlite_store.py:800-805` (`promotion_rule`/`risk_level`).
Resolution: §1 ARCH-55-Block + Scope 6 + AC4 erweitert auf **alle vier** Werte (pattern.py PromotionRule/PatternRiskLevel, check_proposal.py FalsePositiveRisk, sqlite_store.py CHECKs). Alle gehoeren zu AG3-078 (Schema-Owner `fc_patterns`/`fc_check_proposals`) — ein Code-Owner, vollstaendiger Spiegel, keine unbegruendete Ausnahme.

**F3 — FK-76-Port-Surface faelschlich „optional".**
Verifiziert: FK-76 §76.8 (`76_agent_harness_integration.md:306-308`) benennt die oeffentliche Surface verbindlich; nur die **physische Paketverschiebung** ist „kosmetisch" (§76.3, `:151-155`).
Resolution: §1 + Scope 3 trennen jetzt sauber: Paketverschiebung = optionale Code-Folge (kosmetisch); Port-Surface = **verbindliche, geownete Code-Soll-Surface** mit benanntem Owner-BC `harness-integration`. Kein „optionaler Sammelhinweis" mehr.

### AC-Schaerfe (ERROR)

**F4 — Spiegelung an AG3-078/070/068 nicht verifizierbar („gespiegelt (Vermerk)").**
Resolution: Out-of-Scope §2.2 benennt pro Befund das **konkrete Zielartefakt**: Spiegel an AG3-078 = Vermerk in **diesem** `remediation-r1.md` (CP5); offene Code-Bedarfe ohne Backlog = nummerierte **PO-Eskalation** (CP1–CP3); AG3-068-`slugify` = **Cross-Story-Voraussetzung CP4**. Es wird ausdruecklich **keine** fremde Story-Datei editiert.

**F5 — AC5 „kein offener Owner-Konflikt" trotz „PO/Backlog"/„Code-Folge-Story".**
Resolution: AC5 fordert nun, dass **jeder** owner-lose Code-Bedarf als nummerierte PO-Eskalation (CP1–CP3) bzw. Cross-Story-Voraussetzung (CP4–CP5) ausgewiesen ist; WorktreeManager hat ausserdem jetzt den **bestehenden** Soll-Owner `story_context_manager` (siehe F7). Damit verbleibt kein diffuser „PO/Backlog"-Platzhalter.

**F6 — Gate-AC zu unkonkret.**
Resolution: AC7 nennt die konkreten Doc-only-Gates `scripts/ci/check_concept_frontmatter.py`, `scripts/ci/compile_formal_specs.py`, `scripts/ci/check_remote_gates.ps1` (alle drei im Repo verifiziert) plus die Diff-Regel `git diff -- src tests` = leer.

### Klarheit (ERROR)

**F7 — Scope-Kollision: Z. 5 „keine concept/PROJECT_STRUCTURE-Aenderung" widerspricht Scope/AC.**
Resolution: Header-Zeile umformuliert auf **„Doc-only: NUR `concept/`- und `PROJECT_STRUCTURE.md`-Prosa wird geaendert. Kein `src/`-/`tests/`-Diff."** Damit ist die DoD nicht mehr durch das eigene Scope-Verbot blockiert; Code/Test bleiben verboten.

**F8 — Sub-Agent-Hinweis „PROJECT_STRUCTURE/FK-Dateien nicht anfassen" blockiert die DoD.**
Resolution: §6 umgestellt — Sub-Agent **darf/soll** FK-07/73/76/92 + PROJECT_STRUCTURE-Prosa anpassen; verboten bleiben nur `src/`/`tests/` und fremde Story-Dateien.

### Kontext-Sinnhaftigkeit (ERROR)

**F9 — WorktreeManager faelschlich „kein Owner im Index".**
Verifiziert: `bc-cut-decisions.md:275-283` modelliert WorktreeManager als shared component mit `owner_group_id: architecture-conformance.group.story_context_manager` (`:278`).
Resolution: §1 + Scope 2 + AC1 verorten den Drift jetzt gegen den **bestehenden** Owner `story_context_manager` (story-lifecycle). Owner-per-value erfuellt; die Konsolidierung ist ein Code-Drift gegen ein geownetes Soll (PO-Eskalation CP1), nicht owner-los.

**F10 — Unklar, wie `harness_integration` registriert wird (gezaehlt/synchronisiert/nur Baum).**
Resolution: Scope 3 entscheidet explizit: **alle drei** — Zaehlung anheben, Baum ergaenzen, Tabelle ergaenzen; BC-Name `harness-integration` aus `bounded-contexts.yaml:245` uebernehmen, realer Ort `governance/harness_adapters/` benannt.

**F11 — offene Code-Bedarfe nicht owner-/artefaktgenau gespiegelt.**
Resolution: §2.2 fuehrt CP1–CP5 mit je benanntem Owner-BC und Eskalations-/Zielartefakt.

## Anker-Korrekturen (file:line gegen Code-Realitaet)

- **Falsch:** „nur `StoryContextPort` existiert (`verify_system/system.py`)". **Real:** Symbol `StoryContextPort` existiert **nicht**; reales Pendant `StoryContextQueryPort` (`src/agentkit/verify_system/system.py:122` `_NullStoryContextPort`, `:149`; `src/agentkit/exploration/ports.py:10`). Korrigiert in §1/Scope 1/AC1.
- **Praezisiert:** reale Protocol-Ports `exploration/ports.py:36/57/82/111/152`, `closure/runtime_ports.py:100/198/222/244/271`.
- **Praezisiert:** Port-Zaehlung von „32" auf „35 ueber §7.4.1–§7.4.6" korrigiert (gezaehlt: 15+6+8+2+1+3); FK-07-Anker `07_komponentenarchitektur_und_architekturkonformanz.md:83/87/91`.
- **Praezisiert:** dim9_drift-Anker `19-32` (statt `22-32`), Quote deckt `:25-30`.
- **Bestaetigt korrekt:** `pattern.py:50-60`, `entities.py:14-55`, `bc-cut-decisions.md:275/278`, `bounded-contexts.yaml:245`, FK-73 `:101/107`, FK-92 `:90/95`.

## Genuine Cross-Story-Voraussetzungen / PO-Eskalationen

- **CP1 (PO-Eskalation):** WorktreeManager-Konsolidierung — Code, Owner-BC `story-lifecycle`/`story_context_manager` (`bc-cut-decisions.md:278`); **kein** Backlog-Eintrag.
- **CP2 (PO-Eskalation):** `harness_integration`-Paketverschiebung + Port-Surface (§76.8) — Code, Owner-BC `harness-integration` (`bounded-contexts.yaml:245`); **kein** Backlog-Eintrag.
- **CP3 (PO-Eskalation):** SonarQube-Baseline-Hash-`configuration`-Feld der Project-Entitaet — Code, Owner-BC `project-management`; **kein** Backlog-Eintrag (project-management-GAP-Analyse §4 fuehrt es nicht; AG3-070 = `project-config`, nicht project-management — liefert es nicht).
- **CP4 (Cross-Story):** `slugify` (FK-92 §92.4) — Code-Home Story-Creation-BC; **nicht** im AG3-068-Scope enumeriert -> AG3-068-Scope erweitern oder dedizierte Verzeichnis-Konventions-Story.
- **CP5 (Cross-Story):** Deutsche `failure-corpus`-Enum-/CHECK-Werte (pattern.py:50-60, check_proposal.py:56-58, sqlite_store.py:800-805) -> **AG3-078** (Schema-Owner). Vollstaendiger ARCH-55-Spiegel, kein Wert ausgelassen.

## Verifikationsstatus

- Geaenderte Dateien dieser Remediation: `stories/AG3-104-*/story.md`, `stories/AG3-104-*/remediation-r1.md`. **Sonst nichts.**
- `status.yaml` unveraendert: `type: concept`, `size: M`, `depends_on: [AG3-102]`, `status: draft`, `phase: review_pending` sind weiterhin korrekt; kein Feld war fachlich falsch.
- AG3-104 bleibt strikt doc-only; AG3-057-Template-Struktur (§1 Kontext, §2 Scope 2.1/2.2, §3 AK, §4 DoD, §5 Guardrails, §6 Sub-Agent-Hinweise) ist erhalten.
