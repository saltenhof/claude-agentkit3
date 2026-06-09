OVERALL CHANGES-REQUESTED

**Konzept-Vollstaendigkeit: FAIL**

- ERROR: AG3-062 fordert bei invalider Preflight-Antwort fail-closed Parse-Fehler, FK-47 normiert aber `requests=[] + WARNING` und Review laeuft weiter. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:33), [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:50), [47_request_dsl_und_preflight_turn.md](T:/codebase/claude-agentkit3/concept/technical-design/47_request_dsl_und_preflight_turn.md:138), [47_request_dsl_und_preflight_turn.md](T:/codebase/claude-agentkit3/concept/technical-design/47_request_dsl_und_preflight_turn.md:330). Fix: entweder Story auf FK-Verhalten `WARNING + continue` korrigieren oder vorher FK-47 explizit aendern.
- ERROR: Transport-Schnitt ist konzeptionell widerspruechlich. FK-47 sagt direkter MCP-Pool-Call, nicht `LlmEvaluator`/`StructuredEvaluator`; AG3-065 sagt zugleich, AG3-062 ist kein garantierter Konsument und AG3-065 liefert kein `merge_paths`/file handling. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:33), [47_request_dsl_und_preflight_turn.md](T:/codebase/claude-agentkit3/concept/technical-design/47_request_dsl_und_preflight_turn.md:275), [AG3-065 story.md](T:/codebase/claude-agentkit3/stories/AG3-065-verify-llm-transport-dialogue-runner/story.md:80), [AG3-065 story.md](T:/codebase/claude-agentkit3/stories/AG3-065-verify-llm-transport-dialogue-runner/story.md:82). Fix: AG3-062 muss den Preflight-Send-Port eindeutig schneiden: direkter Hub/MCP-Port mit Dateiuebergabe, oder harte Dependency auf eine Story, die genau diesen Port liefert.

**AC-Schaerfe: FAIL**

- ERROR: AC7/Guardrail machen den falschen Invalid-JSON-Pfad testpflichtig. Das wuerde eine FK-47-Inkompatibilitaet in Tests zementieren. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:50), [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:58), [28_evidence_assembly_review_vorbereitung.md](T:/codebase/claude-agentkit3/concept/technical-design/28_evidence_assembly_review_vorbereitung.md:985). Fix: AC auf valides JSON, invalides JSON -> leere Liste + WARNING + kein Silent Drop der Warnung umstellen.
- WARNING: AC5 fordert `> 8 Requests fail-closed`; FK-47-Beispiel kappt per `raw_requests[:MAX_REQUESTS]`. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:48), [47_request_dsl_und_preflight_turn.md](T:/codebase/claude-agentkit3/concept/technical-design/47_request_dsl_und_preflight_turn.md:147). Fix: klaeren, ob Ueberlauf hart fehlschlaegt oder deterministisch auf 8 begrenzt und als WARNING gespiegelt wird.

**Klarheit: WEAK**

- WARNING: Modulpfad bleibt in AG3-062 implizit. FK-28/FK-46 nennen `agentkit/evidence/`, realer AK3-Schnitt ist `agentkit/verify_system/evidence/`; AG3-061 erklaert diese Abweichung, AG3-062 nicht. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:29), [46_import_resolver.md](T:/codebase/claude-agentkit3/concept/technical-design/46_import_resolver.md:329), [AG3-061 story.md](T:/codebase/claude-agentkit3/stories/AG3-061-evidence-assembly-core/story.md:69). Fix: In Scope explizit `src/agentkit/verify_system/evidence/{import_resolver.py,request_types.py,request_resolver.py}` nennen.
- WARNING: Template-Scope nennt nur Datei unter `resources/`, aber vorhandene Prompt-Bundles sind manifest-registriert. Evidence: [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:35), [manifest.json](T:/codebase/claude-agentkit3/src/agentkit/resources/internal/prompts/manifest.json:4). Fix: AC fuer Registrierung im Prompt-Manifest mit Hash aufnehmen.

**Kontext-Sinnhaftigkeit: FAIL**

- ERROR: `status.yaml` haengt nur von AG3-061 ab, obwohl die Story AG3-065-Transport als Nutzpfad nennt; AG3-065 ist selbst draft und nicht als Dependency gesetzt. Evidence: [status.yaml](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/status.yaml:8), [AG3-065 status.yaml](T:/codebase/claude-agentkit3/stories/AG3-065-verify-llm-transport-dialogue-runner/status.yaml:4), [story.md](T:/codebase/claude-agentkit3/stories/AG3-062-import-resolver-request-dsl-preflight/story.md:68). Fix: entweder AG3-065-Abhaengigkeit setzen und Port-Kontrakt passend erweitern, oder AG3-062 ohne AG3-065 formulieren.
- PASS: Ist-Zustand-Anker sind groesstenteils real: FK-46/FK-47 fehlen laut Gap-Audit, `verify_system/evidence/__init__.py` ist leer, `PreflightSentinel` und `PREFLIGHT_*` existieren, Setup-Preflight ist ein anderes Konzept. Evidence: [gap-fk-46-56.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/gap-fk-46-56.md:14), [gap-fk-46-56.md](T:/codebase/claude-agentkit3/var/concept-gap-analysis/gap-fk-46-56.md:39), [__init__.py](T:/codebase/claude-agentkit3/src/agentkit/verify_system/evidence/__init__.py:1), [preflight_sentinel.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/contract/preflight_sentinel.py:50), [events.py](T:/codebase/claude-agentkit3/src/agentkit/telemetry/events.py:61), [preflight.py](T:/codebase/claude-agentkit3/src/agentkit/governance/setup_preflight_gate/preflight.py:1).

**Must-Fix**

1. FK-47 Parse-/Fehlertoleranz-Konflikt bereinigen.
2. Preflight-Transport-Port und Dependency zu AG3-065 eindeutig schneiden.
3. AG3-062-Modulpfade auf `src/agentkit/verify_system/evidence/` festlegen.
4. Prompt-Template inklusive Manifest-Registrierung als AC aufnehmen.
5. `MAX_REQUESTS`-Overflow-Verhalten mit FK-47 vereinheitlichen.
