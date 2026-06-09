# AG3-065 — Remediation R3 (Antwort auf review-r3.md)

**Story:** AG3-065 — Verify-LLM-Transport + DialogueRunner + Timeouts
**Review:** `review-r3.md` (OVERALL: CHANGES-REQUESTED; 3 verbleibende Must-Fix-ERRORs; 4 Round-2-Must-Fix bestätigt RESOLVED außer Queued-Acquire)
**Ergebnis:** `story.md` editiert; `status.yaml` geprüft (korrekt, keine Änderung); nur `story.md` und diese `remediation-r3.md` geschrieben.
**Scope-Leitplanke:** Index-Schnitt `var/concept-gap-analysis/_STORY_INDEX.md:56` — `FK § = FK-11 §11.2-§11.6`, `depends_on = AG3-043, AG3-075`, Konsument = AG3-079 (`:80`). Kein Scope über diesen Schnitt hinaus hinzugefügt. AG3-057-Template-Struktur beibehalten. ARCH-55 (Englisch) für alle neuen Identifier eingehalten.

---

## Verbleibende Must-Fix-ERRORs (review-r3)

### ERROR 1 — Queued-Acquire hat keine implementierbare Hub-Oberfläche
**Befund (review-r3):** `HubClientProtocol.acquire` gibt heute `HubSessionLease` zurück; `HubClient.acquire` parst die Antwort direkt als Lease. Ein `queued`-Zustand ist nach diesem Pfad nicht unterscheidbar. Story-Zeile 43 sagte nur „minimal nötige Erkennung im Verify-Adapter", ohne die Protokolländerung zu definieren. Fix-Vorgabe: getypte `AcquireResult`/`QueuedAcquire`-Union, dedizierte queued-Exception oder andere explizite `HubClient.acquire`-Vertragserweiterung, **mit Tests auf HubClient- und HubLlmClient-Ebene**.

**Realer Code verifiziert:** `HubClient.acquire` (`multi_llm_hub/client.py:149-166`) parst direkt über `_lease_payload` (`:299-308`), der `raw_lease["session_id"]`/`["token"]` indexiert; `HubClientProtocol.acquire` (`:98`) deklariert Rückgabe `HubSessionLease`. Eine `queued`-Antwort ohne Slot zerfällt heute als `KeyError` → `_request` (`:224-235`) → `MultiLlmHubError`/`HubUnavailableError` und ist nicht als Queue-Zustand erkennbar. `multi_llm_hub/errors.py:8-17` definiert `MultiLlmHubError` als Basis (mit `HubUnavailableError`/`HubSessionNotFoundError`).

**Resolution:** Explizite, **additive** Vertragserweiterung gewählt (Variante „dedizierte queued-Exception" aus der Fix-Vorgabe, weil sie den `HubSessionLease`-Rückgabetyp und damit den AG3-079-Port stabil hält — kein Union-Bruch):
- Scope 2.1.3 „Benötigte Hub-Surface-Erweiterung (verbindliche Designentscheidung)" neu: `HubClient.acquire` wirft bei `status == "queued"` (ohne gewährten Slot) eine **getypte** `HubAcquireQueuedError` (neue Subklasse von `MultiLlmHubError` in `multi_llm_hub/errors.py`) **bevor** `_lease_payload` greift; optionales `estimated_wait_seconds`. Rückgabetyp `HubSessionLease` von `acquire`/`HubClientProtocol.acquire` (`:98`) **unverändert** → AG3-079-Port + bestehende Aufrufer stabil. Der `HubLlmClient` fängt die Ausnahme und treibt die `MAX_ACQUIRE_RETRIES = 5`-Re-Acquire-Schleife (gleicher Owner), re-raised nach Erschöpfung als `LlmClientError`.
- §1 Ist-Zustand „Queued-Acquire heute" präzisiert: Parse-Zerfall-Pfad (`KeyError`) belegt; Anker `_lease_payload :299-308`, `_request :224-235` ergänzt.
- AC3 aufgeteilt in **Hub-Ebene** (d: `HubAcquireQueuedError` statt Parse-Zerfall, Test gegen Fake-`JsonTransport`) **und HubLlmClient-Ebene** (e: Re-Acquire-Erfolg innerhalb 5, gleicher Owner; f: Erschöpfung → `LlmClientError`, Call-Count = 5). Damit Tests auf **beiden** geforderten Ebenen.
- Sub-Agent-Hinweis + ARCH-55-Identifier-Liste (`HubAcquireQueuedError`, `status: "queued"`, `estimated_wait_seconds`) nachgezogen.

### ERROR 2 — Login-Fehler-Handling widerspricht FK-11
**Befund (review-r3):** FK-11 §11.2.3 Zeile 191 (+ FK-34 §286): `send`-Login-Fehler = Mensch muss einloggen, Pipeline pausiert. Story-Zeile 47 mappte `Login-Fehler` auf generisches `LlmClientError` fail-closed. Fix-Vorgabe: distinkten Login-Required-Ausgang modellieren, der Pipeline-Pause mit Operator-Hinweis auslöst — oder explizite Konzept-Supersession dokumentieren.

**Realer Code verifiziert:** Der Pause-Mechanismus läuft über `PauseReason` (`core_types/pause_reason.py:46-60`) — eine **geschlossene** StrEnum mit **genau drei** Werten (`AWAITING_DESIGN_REVIEW`/`AWAITING_DESIGN_CHALLENGE`/`GOVERNANCE_INCIDENT`), Owner FK-39 §39.2.2 + AG3-021 (`completed`); der Wire-Key `pause_reason` ist Eigentum von **AG3-059** (`_STORY_INDEX.md:45`). Ein neuer Pause-Wert „login required" + Phase-Runner-Pause-Verdrahtung liegt damit **außerhalb** des AG3-065-Transport-Schnitts.

**Resolution (in-story modellieren + Pause-Verdrahtung an Owner routen):**
- Scope 2.1.3 neuer Unterpunkt „Login-Fehler — distinkter Ausgang": AG3-065 liefert eine **getypte** `LoginRequiredError` als **Subklasse von `LlmClientError`** (in `verify_system/llm_evaluator/llm_client.py`) mit `operator_hint` (betroffener Pool, „login required"). Weil Subklasse, bleiben bestehende `LlmClientError`-Catches (Layer-2-Integration) **rückwärtskompatibel** blockierend (kein PASS/Skip) — der distinkte Typ trägt aber die Pause-Information. Generisches fail-closed, das den FK-11-Pause-Ausgang verschluckt, wird damit aufgelöst.
- §1 neuer Beleg „Login-Fehler/Pause heute": geschlossene `PauseReason`-Enum + Owner FK-39/AG3-021/AG3-059 belegt; begründet, warum der neue Pause-Wert out-of-cut ist.
- §2.2 neue Out-of-Scope-Zeile mit **Owner AG3-059**: Pipeline-Pause-Verdrahtung (neuer `PauseReason`-Member + Phase-Runner-Pause) explizit dorthin geroutet; AG3-065 liefert nur den abgreifbaren Transport-Ausgang.
- Quell-Konzept-Zeile (§ oben) um FK-11 §11.2.3 Zeile 191 ergänzt; AC10 um (b) Login-Fehler erweitert (distinkter Typ abgreifbar **und** Rückwärtskompatibilität bestehender Catches); FAIL-CLOSED-Guardrail + Sub-Agent-Hinweis + ARCH-55-Liste (`LoginRequiredError`, `operator_hint`) nachgezogen.

### ERROR 3 — DialogueRunner-Transcript-Logging fehlt
**Befund (review-r3):** FK-11 §11.5.2 verlangt „separates Logging" und vollständiges Transcript-Logging inkl. Prompt + Response pro Turn. Story-Zeile 53 + AC7 verlangten nur ein In-Memory-`DialogueResult`-Transcript. Fix-Vorgabe: Transcript-Logging in Scope + AC aufnehmen (inkl. Persistenzziel und Tests) oder explizit einem Owner zuweisen.

**Konzept verifiziert:** FK-11 §11.5.2 Zeile 494 („separates Logging") + Zeile 532 (Vergleichstabelle: DialogueRunner-Logging = „Vollständiger Transcript (Prompt + Response pro Turn)"). Persistenz-Maschinerie existiert: `verify_system/prompt_audit.py` (`materialize_qa_prompt_audit`) über `ArtifactManager` (analog zum StructuredEvaluator-Logging in Scope 2.1.8a).

**Resolution (in-story, im Cut):**
- Scope 2.1.5 neuer Unterpunkt „Persistiertes Transcript-Logging": vollständiges Transcript (jeder Turn `role`/`content`/`ts`, also Prompt **und** Antwort pro Turn) **zusätzlich** zum In-Memory-`DialogueResult` über die bestehende `prompt_audit`/`ArtifactManager`-Maschinerie persistiert (kein paralleler Kanal, kein loses JSON); fehlender `ArtifactManager` → sauberer `skipped`-Status (wie `prompt_audit`).
- Quell-Konzept-Zeile um §11.5.2 Zeile 490-545 / 494 / 532 ergänzt.
- AC7 erweitert: persistiertes Logging-Artefakt enthält **alle** Turns (agentkit- und llm-Turns) mit vollständigem `content`; fehlender `ArtifactManager` → `skipped` (Test).
- Sub-Agent-Hinweis nachgezogen (Andocken an `prompt_audit`, kein paralleler Kanal).

---

## Round-2-Must-Fix-Status (review-r3 bestätigt)
- Per-Operation-Timeouts: **RESOLVED** (unverändert übernommen).
- AG3-070 / `llm_roles`: **RESOLVED** (unverändert übernommen).
- Remote-Gate-Befehl: **RESOLVED** (unverändert übernommen).
- Queued-Acquire: war NOT GENUINELY RESOLVED → jetzt mit getypter `HubAcquireQueuedError`-Hub-Surface + Tests auf beiden Ebenen behoben (ERROR 1).

## Per-Dimension-FAILs (review-r3) — Auflösung
- **Konzept-Vollständigkeit (war FAIL):** FK-11 §11.2.3-Login-Pause (Zeile 191) und §11.5.2-Transcript-Logging (Zeile 494/532) jetzt korrekt eingezogen (ERROR 2+3).
- **AC-Schärfe (war FAIL):** AC3 definiert nun die geforderte Hub-Acquire-Surface (`HubAcquireQueuedError`) mit Tests auf HubClient- **und** HubLlmClient-Ebene (ERROR 1); AC7 trägt die FK-11-Transcript-Logging-Pflicht (ERROR 3); AC10b trägt den distinkten Login-Ausgang (ERROR 2).
- **Klarheit/Eindeutigkeit (war WEAK):** „minimal nötige Erkennung im Verify-Adapter" ersetzt durch eine konkrete, additive, getypte Protokollerweiterung gegen das reale `acquire → HubSessionLease`-Parsing.
- **Kontext-Sinnhaftigkeit (war FAIL):** Queued-Acquire-Design jetzt am realen `_lease_payload`-Parsing (`client.py:164-166`/`:299-308`) ausgerichtet; Login-Pause am realen geschlossenen `PauseReason`-Enum (`pause_reason.py:46-60`) verankert und korrekt an AG3-059 geroutet.

---

## Code-Anker (gegen den realen Code verifiziert / präzisiert)

| Thema | Verifiziert |
|---|---|
| Queued-Acquire-Parse-Zerfall | `HubClient.acquire` `client.py:149-166`; `_lease_payload` `:299-308` (indexiert `session_id`/`token`); `HubClientProtocol.acquire -> HubSessionLease` `:98`; `_request` `:224-235` |
| Hub-Error-Basis | `multi_llm_hub/errors.py:8-17` — `MultiLlmHubError` (Basis), `HubUnavailableError`/`HubSessionNotFoundError` (Geschwister von `HubAcquireQueuedError`) |
| Login-Pause-Owner | `PauseReason` geschlossene 3-Wert-StrEnum `core_types/pause_reason.py:46-60`; Owner FK-39 §39.2.2 / AG3-021 (`completed`); `pause_reason`-Wire-Key = AG3-059 (`_STORY_INDEX.md:45`) |
| LlmClient-Port/Error | `LlmClient`-Port `llm_client.py:42-74`; `LlmClientError` `:29-38` (Basis für neue `LoginRequiredError`); `FailClosedLlmClient` `:77-112` |
| Transcript-Logging-Quelle | FK-11 §11.5.2 Konzept-Datei Zeile 494 („separates Logging"), Zeile 532 (Tabelle „Vollständiger Transcript: Prompt + Response pro Turn") |
| Logging-Persistenz | `verify_system/prompt_audit.py` (`materialize_qa_prompt_audit`) über `ArtifactManager`; `skipped`-Status-Muster `:58-71` |
| FK-11 Login-Quelle | Konzept-Datei Zeile 191 (`send → Login-Fehler (500)` → „Mensch muss einloggen. Pipeline pausiert mit Hinweis.") |

---

## status.yaml
Geprüft, **keine Änderung**: `depends_on: [AG3-043, AG3-075]` stimmt exakt mit dem Index-Schnitt (`_STORY_INDEX.md:56`). Die neuen Owner-Routings (AG3-059 für die Pause-Verdrahtung; AG3-070 für den produktiven Resolver) sind **fachliche Nachfolger/Owner**, kein Build-Blocker für die hier gelieferten Transport-Artefakte — daher kein Index-überschreibendes Dependency-Feld. `status: draft` / `phase: review_pending` sind template-konform (AG3-057) korrekt.

## Geschriebene Dateien (nur diese)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/story.md` (editiert)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/remediation-r3.md` (dieser Report)
- `status.yaml`: **nicht** geändert (geprüft, korrekt).

**Keine** Produktionscode-, Test- oder `concept/`-Datei wurde angefasst.
