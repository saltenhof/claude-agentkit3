OVERALL: CHANGES-REQUESTED  (Pilot-Review, Codex job-c659db5f)

1. Konzept-Vollstaendigkeit: FAIL
- ERROR: Bugfix-Red-Green ist aus dem Scope gefallen. Index ordnet es AG3-064 zu (_STORY_INDEX.md:159); FK-33:390-398 listet bugfix.reproducer_manifest/red_evidence/green_evidence/suite_evidence/red_green_consistency. Story schiebt Check-Body weg (story.md:43), keine AC. Fix: in Scope/AC aufnehmen oder Cut formal aendern.
- ERROR: Trust-Class-Validierung fehlt. FK-33:501-505 verlangt: keine Stage mit trust_class "C" als blocking:true. Story fordert nur das Feld, keinen Reject-Pfad. Fix: AC/Test fuer Trust-C + blocking=true fail-closed.
- ERROR: §33.2.3 Stage-ID = artifact_kind/Dateiname nicht abgedeckt (FK-33:194-219). Code nutzt doc_fidelity.json/decision.json (qa_artifact_names.py:36,60-66). Fix: Migration/Kompatibilitaetsregel spezifizieren.
- WARNING: concept/research zu grob. FK-33:940-959 nennt concept.structure/completeness/sparring/vectordb, research.structure/sources/assessment. Story nur concept_feedback/research_quality. Fix: Stage<->Subcheck exakt definieren oder Owner-Story.

2. AC-Schaerfe: FAIL
- ERROR: AC2 testet nur "korrekten layer" (story.md:48); FK-33:147-158 fordert kind/blocking/trust_class/producer/execution_policy/override_policy. Fix: Tabelle erwarteter Werte + Tests aller Felder.
- ERROR: AC5 nur _LAYER_NAME_TO_NUMBER (story.md:51); Code hat weitere Layer-Wahrheiten _SYSTEM_LAYER_NAME_TO_NUMBER und _KIND_TO_LAYER_NUMBER (system.py:1504-1524). Fix: alle Mapping-Quellen adressieren.
- ERROR: AC7 kein pruefbares PolicyWarning-Contract. decide() nimmt nur LayerResult (policy_engine/engine.py:190-198); VerifyDecision hat kein Warning-Feld (100-107). Fix: Warning-Modell/Input-Port/Projection-Feld + Tests (missing/sufficient/partial/malformed).
- WARNING: AC1 "blocking ohne Severity zu brechen" unklar. Fix: Invariante festlegen (default_blocking = severity==BLOCKING; effective_blocking nach Override).

3. Klarheit/Eindeutigkeit: FAIL
- ERROR: id vs stage_id ungeklaert (FK-33:149 'id'; stage_registry/stages.py:82 'stage_id'). Fix: Migrationspfad/Alias.
- ERROR: doc_fidelity_impl kollidiert mit doc_fidelity (qa_artifact_names.py:36,50,76,89; engine.py:387). Fix: kanonische Stage-ID oder Legacy-Alias-Regel.
- ERROR: Falscher TrustClass-Anker. Story sagt policy_engine/trust.py (story.md:23,31,69); real verify_system/protocols.py:173-186; policy_engine/trust.py:12 importiert nur. Fix: Anker korrigieren.
- WARNING: Producer-IDs ambig (FK-33:164-176 qa-*; Code qa_artifact_names.py:79-91 verify-system.layer-*). Fix: bestehende Producer-SSOT wiederverwenden oder Konzeptmigration.

4. Kontext-Sinnhaftigkeit: FAIL
- ERROR: 'policy' als blocking Stage bricht Ablauf. VerifySystem ueberspringt QALayerKind.POLICY (system.py:596-598), ruft decide() danach (650). Blocking-Stage 'policy' layer4 -> _missing_stage_findings sieht traversierte Stage ohne LayerResult (engine.py:328-349; system.py:1518-1524). Fix: 'policy' vor Missing-Stage-Pruefung ausnehmen oder als nachgelagertes Decision-Artefakt.
- ERROR: Missing-Stage-Pruefung ist layer-basiert (engine.py:394-401). 'structural'-Result maskiert fehlende 'sonarqube_gate' (beide layer1). Fix: gegen Stage-ID/ArtifactRecord/Producer pruefen.
- ERROR: "Registry ersetzt Engine-Layer-Tabelle" unvollstaendig — neben _LAYER_NAME_TO_NUMBER (engine.py:382-391) auch system.py:1504-1524. Fix: alle Layer-Wahrheiten inventarisieren.
- WARNING: Config-Owner fuer policy.stage_overrides unspezifiziert. ProjectConfig verbietet extra fields (config/models.py:433); PipelineConfig hat kein policy-Feld (372-381). Fix: Pydantic-Modelle/YAML-Pfad/Loader-Tests in Story.

Must-Fix ERRORs:
1. Bugfix-Red-Green-Scope klaeren/in AC oder Cut korrigieren.
2. Trust-C/blocking fail-closed Validierung.
3. artifact_kind/Dateiname-Migration §33.2.3.
4. AC fuer ALLE Stage-Felder, nicht nur Layer.
5. PolicyWarning-Contract + Input-Pfad.
6. id/stage_id, doc_fidelity_impl/doc_fidelity, Producer-SSOT entscheiden.
7. 'policy'-Stage Self-missing + layer-basierte Missing-Stage-Pruefung beheben.
8. Alle Layer-Mapping-SSOTs adressieren, nicht nur _LAYER_NAME_TO_NUMBER.
