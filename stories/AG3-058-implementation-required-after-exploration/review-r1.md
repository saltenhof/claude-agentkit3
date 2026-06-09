OVERALL CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: WEAK**

WARNING: FK-24 §24.9 wird in der Story zu hart wiedergegeben. Die Story behauptet `exploration-summary.md` als direktes FK-Pflichtartefakt ([story.md](T:/codebase/claude-agentkit3/stories/AG3-058-implementation-required-after-exploration/story.md:10)), FK-24 erlaubt aber `exploration-summary.md` **oder** einen definierten Abschnitt in `protocol.md` ([24_story_type_mode_terminalitaet.md](T:/codebase/claude-agentkit3/concept/technical-design/24_story_type_mode_terminalitaet.md:520)). Fix: klarstellen, dass AG3-058 bewusst die strengere Index-Entscheidung `exploration-summary.md` wählt ([\_STORY_INDEX.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/_STORY_INDEX.md:44)), nicht dass FK-24 nur diese Datei erlaubt.

**2) AC-Schaerfe: WEAK**

ERROR: AC2/Scope definieren „Code-/Datei-Aenderungen“ nicht eindeutig als Trust-A/B-Systemevidence. Bestehender Verify-Code verbietet Blocking-Entscheidungen auf Worker-Selbstreport ([system_evidence.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/structural/system_evidence.py:3)); `worker-manifest.json` darf also nicht als Nachweis fuer echte Aenderungen reichen. Fix: AC2 explizit auf `ChangeEvidence`/System-Diff bzw. echte Git-/Dateisystem-Evidence festlegen; Manifest nur als Pflichtartefakt/Schema-Nachweis zaehlen.

ERROR: Sub-Agent-Hinweis behauptet, `worker-manifest.json`/`protocol.md` aus bestehenden `core_types`-Artefakt-Konstanten zu ziehen ([story.md](T:/codebase/claude-agentkit3/stories/AG3-058-implementation-required-after-exploration/story.md:73)). Aktuell liegen diese Strings privat in Verify/Implementation (`_PROTOCOL_FILE`, `_WORKER_MANIFEST_FILE`) ([artifact_checks.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/structural/checks/artifact_checks.py:33)); `core_types` exportiert nur andere QA-Namen ([__init__.py](T:/codebase/claude-agentkit3/src/agentkit/core_types/__init__.py:29)). Fix: entweder Scope um „Konstanten nach `core_types` konsolidieren/exportieren“ erweitern oder den Hinweis auf bestehende Konstanten entfernen.

**3) Klarheit/Eindeutigkeit: WEAK**

WARNING: Der Status-/Owner-Pfad fuer `IMPLEMENTATION_REQUIRED_AFTER_EXPLORATION` bleibt implementierungsentscheidend, aber AG3-058 hat keine Abhaengigkeit auf AG3-059, obwohl AG3-059 PhaseStateCore/`escalation_reason` als Schema-Owner behandelt ([AG3-059 story.md](T:/codebase/claude-agentkit3/stories/AG3-059-phase-state-core-fieldset-ownership/story.md:5)) und den Zusatzwert explizit an AG3-058 auslagert ([AG3-059 story.md](T:/codebase/claude-agentkit3/stories/AG3-059-phase-state-core-fieldset-ownership/story.md:40). Fix: `depends_on: AG3-059` setzen oder im Scope eindeutig sagen, dass AG3-058 nur den Wert/Code entscheidet und AG3-059 den PhaseStateCore-Transport nachzieht.

**4) Kontext-Sinnhaftigkeit: FAIL**

ERROR: Ist-Zustand-Claim „Folge-Zustands-Flags … existieren nicht (Grep ohne Treffer)“ ist in dieser Form falsch, weil `story_done` als Codeanker existiert (`_transition_story_done`) ([closure/phase.py](T:/codebase/claude-agentkit3/src/agentkit/closure/phase.py:331), [closure/phase.py](T:/codebase/claude-agentkit3/src/agentkit/closure/phase.py:1082)). Als Zustandsfeld fehlt es zwar in `StoryContext`/Payload ([models.py](T:/codebase/claude-agentkit3/src/agentkit/story_context_manager/models.py:310)), aber der Grep-Claim ist nicht wahr. Fix: umformulieren: `implementation_required`/`closure_allowed` fehlen komplett; `story_done` existiert nur als Closure-Helper-Name, nicht als persistiertes Folge-Zustandsfeld.

NIT: Die belegten positiven Anker sind sonst real: FK-24 §24.5.2/§24.7.1/§24.8.2/§24.9/§24.12/§24.14 existieren, Closure-Sequenz ist in [closure/phase.py](T:/codebase/claude-agentkit3/src/agentkit/closure/phase.py:16) belegt, `closure/gates.py` enthaelt nur den Finding-Resolution-Gate ([gates.py](T:/codebase/claude-agentkit3/src/agentkit/closure/gates.py:58)), und die genannten Tests fehlen aktuell.

**Must-Fix**

1. Falschen `story_done`/„Grep ohne Treffer“-Ist-Claim korrigieren.
2. `core_types`-Konstanten-Behauptung fuer `worker-manifest.json`/`protocol.md` korrigieren oder als Konsolidierungs-Scope aufnehmen.
3. FK-24 §24.9 sauber als „FK erlaubt Alternative; AG3-058 waehlt `exploration-summary.md` wegen Index“ formulieren.
4. AG3-059-Abhaengigkeit/Owner-Reihenfolge fuer PhaseStateCore und `escalation_reason` explizit klaeren.
5. AC2 auf unabhängige System-Evidence fuer echte Code-/Datei-Aenderungen schaerfen.
