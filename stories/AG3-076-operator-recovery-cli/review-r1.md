OVERALL: **CHANGES-REQUESTED**

**1) Konzept-Vollstaendigkeit: FAIL**

- **ERROR**: FK-04 §4.2 wird nicht vollstaendig abgedeckt. FK-04 nennt `agentkit backend health` als Monitoring-Befehl (`concept/technical-design/04_betrieb_monitoring_audit_runbooks.md:56`), die Story zitiert ihn selbst als Quell-Konzept (`story.md:8`), schiebt ihn aber Out of Scope (`story.md:50`). Fix: entweder `backend health` in AG3-076 aufnehmen oder die Quell-Konzept-Zitierung enger fassen und einen konkreten Owner/Folgestory-Eintrag mit Pflichtcharakter anlegen.
- **ERROR**: FK-04 §4.4.2 verlangt, dass Review-Reports “bei jedem `agentkit status` oder explizitem Review-Aufruf” erscheinen (`concept/.../04_betrieb_monitoring_audit_runbooks.md:136-143`). Die Story fordert nur `weekly-review` (`story.md:39`, AC `story.md:63`) und lässt `status` ohne Review-Report-Pflicht (`story.md:36`, `story.md:60`). Fix: AC fuer `status` erweitern: Status rendert den Weekly-Review-Block oder dokumentiert eindeutig, warum diese FK-Anforderung verlagert wird.
- **WARNING**: FK-10 §10.6.2 beschreibt Cleanup von “Worktree, Branch, Locks, Artefakte” (`concept/.../10_runtime_deployment_speicher.md:355-356`). Story reduziert das praktisch auf stale Lock / Worktree (`story.md:35`, AC `story.md:59`). Fix: Cleanup-Scope explizit fuer Branch und Artefakte definieren oder bewusst mit Owner ausschliessen.

**2) AC-Schaerfe: FAIL**

- **ERROR**: AC 2 verlangt Delegation an “bestehende Service-Pfade” (`story.md:56`), aber die Service-Pfade sind fuer mehrere Befehle nicht konkret benannt. Besonders `reset-escalation`, `override-integrity`, `status`, `query-state` und `query-telemetry` bleiben auf “Surface/Read-Modell” Niveau. Fix: pro Befehl genaues Modul, Klasse/Funktion, Eingabe, Rueckgabe und Fehlervertrag nennen.
- **ERROR**: `reset-escalation` ist widerspruechlich testbar. Scope sagt: wenn kein Service existiert, nur melden (`story.md:34`, `story.md:83`); AC 4 verlangt aber funktional, dass aus ESCALATED wieder ein fortsetzbarer Run wird (`story.md:58`). Fix: entweder Service als Voraussetzung konkretisieren und `depends_on` auf abgeschlossene Story setzen, oder AC auf “fehlender Service-Anker erzeugt non-zero + expliziten Befund” aendern.
- **WARNING**: `query-state --story {story_id} [--locks]` (`story.md:37`) kollidiert mit FK-04 `agentkit query-state --locks` ohne Story (`concept/.../04_betrieb_monitoring_audit_runbooks.md:58`). Fix: globalen Lock-Query-Fall separat akzeptieren oder absichtlich ausschliessen.

**3) Klarheit/Eindeutigkeit: FAIL**

- **ERROR**: Story behauptet “die Services existieren bereits” (`story.md:22`), nennt aber gleichzeitig fehlende Service-Anker als moeglichen Befund (`story.md:83`). Das ist kein klarer Auftrag. Fix: Ist-Zustand hart trennen: “existiert”, “Dependency noch draft”, “fehlt und muss gemeldet werden”.
- **ERROR**: `cleanup` wird an `closure/merge_sequence._resume_merge_only` geankert (`story.md:35`), aber dieser Code ist ein Merge-Resume innerhalb des Pre-Merge/Merge-Blocks, nicht PID/TTL-Stale-Lock-Cleanup (`src/agentkit/closure/merge_sequence.py:435-460`). Fix: echten Lock-/PID-/TTL-Service angeben oder Cleanup als Service-Luecke markieren.
- **WARNING**: “Operator darf CLI nutzen, Agent nicht” aus FK-45 (`concept/.../45_phase_runner_cli.md:349-352`) steht in den Quellen (`story.md:7`), aber kein AC prueft, dass Agent-/Control-Plane-Pfade die CLI nicht verwenden. Fix: Architektur-/Import-/capability-Test oder zumindest explizites Nichtziel mit bestehendem Guard nennen.

**4) Kontext-Sinnhaftigkeit: FAIL**

- **ERROR**: Falscher Code-Anker: Story nennt `pipeline_engine/engine.py` mit `_check_preconditions` (`story.md:23`), aber `findstr /s /n /c:"_check_preconditions" src\agentkit\*.py` findet keinen Treffer. Fix: falschen Anchor entfernen und den realen Transition-/Precondition-Owner nennen.
- **ERROR**: AG3-071/072/073 werden als existierende Reset/Split/Exit-Services dargestellt (`story.md:25`), sind aber laut Status noch `draft` / `review_pending` (`stories/AG3-071-story-reset-service/status.yaml:4-5`, analog AG3-072/073). In `src/agentkit` existieren keine `StoryResetService`/`StorySplitService` Treffer. Fix: AG3-076 blockieren, bis Dependencies abgeschlossen sind, oder Story als explizit nachgelagert formulieren.
- **ERROR**: `override-integrity` delegiert angeblich an einen bestehenden Override-Pfad (`story.md:40`), aber die Suche zeigt nur generische `OverrideRecord`-/Engine-Overrides und keinen Integrity-Override-Service; Integrity-Treffer sind Gate-/Merge-Fehler, kein autorisierter CLI-Override-Pfad. Fix: konkreten Owner-Service schaffen/voraussetzen oder AC auf fehlenden Anchor fail-closed aendern.
- **PASS**: CLI-Ist-Zustand ist korrekt belegt: `cli/main.py` registriert `install`, `uninstall`, `run-story`, `doctor`, `serve-control-plane` (`src/agentkit/cli/main.py:38-160`), und `run-story` ist ein Print-Stub (`src/agentkit/cli/main.py:325-345`). `serve-control-plane` als Adaptermuster existiert (`src/agentkit/cli/main.py:369-382`).

**Must-Fix ERROR List**

1. FK-04-Abdeckung klaeren: `backend health` und `status` mit Weekly-Review-Report entweder aufnehmen oder mit verbindlichem Owner auslagern.
2. Alle “bestehenden Service-Pfade” pro CLI-Befehl konkret benennen; keine abstrakten “Surface”-Formulierungen.
3. `reset-escalation`-Widerspruch beheben: funktionaler AC nur mit existierendem Service, sonst fail-closed Befund-AC.
4. Falschen `_check_preconditions`-Anchor entfernen.
5. AG3-071/072/073 nicht als existierende Services behaupten, solange sie draft sind und keine Klassen im Code existieren.
6. `cleanup` nicht an `_resume_merge_only` als stale-lock/PID/TTL-Service verkaufen.
7. `override-integrity` nur fordern, wenn ein echter autorisierter Integrity-Override-Service existiert oder als explizite Service-Luecke behandelt wird.
