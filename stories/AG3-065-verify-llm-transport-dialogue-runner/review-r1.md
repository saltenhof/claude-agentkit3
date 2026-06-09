OVERALL: CHANGES-REQUESTED

**1) Konzept-Vollstaendigkeit: FAIL**

- ERROR: FK-11 §11.2.3-Fehlerprotokoll ist unvollständig bzw. widersprochen. FK sagt: `send -> Timeout | Release versuchen. Neuer Slot. Retry (max 1)` und `Jeder Fehler | Release im finally-Block` (`concept/technical-design/11_llm_provider_browser_pools_prompt_execution.md:189`, `:192`). Story reduziert das auf `Timeout -> fail-closed` (`story.md:32`, `:48`) und testet keinen Release-on-error.  
  Fix: Scope/AC um `release in finally`, Timeout-Retry mit neuem Slot und harte Max-1-Grenze erweitern oder bewusst als Konzeptabweichung mit Owner dokumentieren.

- ERROR: FK-11 §11.4.6 fordert Telemetrie plus QA-Artefakt. Story fordert nur Prompt-/Antwort-Persistenz via `prompt_audit` (`story.md:33`, `:49`), lässt aber `llm_call` mit `pool`, `role`, `retry`, `check_count`, `status` aus (`concept/.../11...md:441-460`).  
  Fix: AC für Telemetrie-Event und QA-Artefaktfelder ergänzen.

- ERROR: FK-11 §11.4.4 Stufe 1 ist falsch wiedergegeben. FK-Stufe 1 ist Prompt-Template mit expliziter JSON-Antwortvorgabe (`concept/.../11...md:316-335`); Story macht daraus `JSON-Block extrahieren + json.loads` (`story.md:30`).  
  Fix: Prompt-Template-Vertrag/G golden tests als eigene Pflicht aufnehmen; Extraktion erst als Stufe 2 beschreiben.

- WARNING: Index scoped AG3-065 auf `FK-11 §11.2-§11.6` (`var/concept-gap-analysis/_STORY_INDEX.md:56`), Story nimmt §11.3 und §11.6.2/§11.6.3 nur teilweise bzw. gar nicht auf. §11.3.3 fordert Runtime-Auflösung + `llm_call` (`concept/.../11...md:228-236`), §11.6.2 Slot-Budget 1 sequentiell (`:564-569`), §11.6.3 Queue-Warten (`:571-575`).  
  Fix: Entweder Story-Quellkonzepte präzise auf die tatsächlich zu erfüllenden Unteranker begrenzen oder die fehlenden Anforderungen als Scope/AC aufnehmen.

**2) AC-Schaerfe: FAIL**

- ERROR: AC3 ist technisch nicht eindeutig: `Nicht-JSON -> Regex-Fallback liefert Verdict` (`story.md:46`). FK beschreibt Regex-Fallback auf `status`, `reason`, `description` in Freitext (`concept/.../11...md:345-350`), nicht ein Role-Verdict. Bestehender Code validiert `list[CheckResult]` (`structured_evaluator.py:368-371`).  
  Fix: Testfälle mit konkretem Freitextformat, CheckResult-Erzeugung, `check_id`-Zuordnung und Vollständigkeitsvalidierung definieren.

- ERROR: Fail-closed ist als Observable unklar. Aktueller Code wirft bei Parsefehler `StructuredEvaluatorError` (`src/agentkit/verify_system/llm_evaluator/structured_evaluator.py:357-372`); FK spricht von `Alle Checks = FAIL` (`concept/.../11...md:303`, `:358`, `:368`); Story sagt nur `fail-closed FAIL` (`story.md:30`, `:50`).  
  Fix: Festlegen, ob `evaluate()` ein FAIL-Result liefert oder eine Exception propagiert, und welche Ebene daraus Layer-2-Blocking macht.

- WARNING: AC8 nennt `vier Konzept-Gates`, aber keine vier konkreten Befehle (`story.md:51`). Lokale Regeln nennen explizit `scripts/ci/check_concept_frontmatter.py` und `scripts/ci/compile_formal_specs.py`; Jenkins/Sonar sind separate Remote-Gates.  
  Fix: Exakte Befehlsliste mit Remote-Gate-Script aufnehmen.

**3) Klarheit/Eindeutigkeit: FAIL**

- ERROR: Story verlangt gleichzeitig `LlmClient`-Port behalten und `merge_paths`/`file_paths` durchreichen. Der Port hat nur `complete(self, *, role: str, prompt: str)` (`llm_client.py:55`); Story sagt Port bewusst schmal halten (`story.md:24`, `:66`) und Datei-Handling durchreichen (`story.md:29`). Das ist nicht implementierbar.  
  Fix: Entweder Port sauber um optionale `merge_paths`/`file_paths` erweitern und alle Caller/Tests nennen, oder Datei-Handling aus AG3-065 entfernen und an eine Story mit Port-Änderung geben.

- ERROR: `produktive Default-Wahl` kollidiert mit `llm_roles` als AG3-070-Out-of-Scope. Story konsumiert `llm_roles` (`story.md:29`, `:38`), aber `status.yaml` hängt nicht von AG3-070 ab (`status.yaml:8-10`).  
  Fix: AG3-070 als Dependency setzen oder Routing so schneiden, dass AG3-065 ohne AG3-070 produktiv testbar bleibt.

- WARNING: AG3-062 wird als Konsument genannt (`story.md:24`, `:40`, `:70`), aber der Index führt AG3-062 vor AG3-065 und ohne AG3-065-Dependency (`_STORY_INDEX.md:53`).  
  Fix: Abhängigkeit/Ordering korrigieren oder AG3-062 aus den Konsumenten streichen.

**4) Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Bestehender `HubClientProtocol.send` und `HubClient.send` haben keine `merge_paths`/`file_paths` Parameter (`src/agentkit/multi_llm_hub/client.py:99-107`, `:168-176`). Story sagt aber, auf den vorhandenen HubClient adaptieren und Datei-Handling durchreichen (`story.md:29`, `:67`).  
  Fix: Explizit den HubClientProtocol-/Client-Contract ändern und testen, oder nicht behaupten, dass der vorhandene Client das kann.

- ERROR: Routing-Owner ist unsauber. FK-75 sagt, fachliches Modell-/Phasenrouting gehört nach `prompt_runtime`, nicht in den Hub-Adapter (`concept/technical-design/75_multi_llm_hub.md:49-57`). Story platziert Rollen-zu-Pool-Routing im Verify-Transport (`story.md:29`) ohne Resolver-/Owner-Grenze.  
  Fix: Einen klaren Owner nennen, z.B. injizierter RoleResolver/top-surface aus `prompt_runtime`/Config, und verhindern, dass Verify-System eine zweite Routing-Wahrheit liest.

- WARNING: FK-11 enthält zwei Überschriften `### 11.4.4` (`concept/.../11...md:310`, `:360`). Story referenziert pauschal `FK-11 §11.4.4/§11.4` (`story.md:8`, `:30`), was als Anker mehrdeutig ist.  
  Fix: In der Story die Abschnittstitel mitnennen oder Konzeptanker bereinigen.

- PASS-Teilbefund: Die belegten Ist-Zustandsclaims sind überwiegend korrekt: `FailClosedLlmClient` ist Port/Fallback (`llm_client.py:41-112`), `StructuredEvaluator` parst strikt `json.loads` ohne Retry (`structured_evaluator.py:329-372`), Ergebnis speichert nur Hashes (`structured_evaluator.py:247-269`), Hub-Default ist `timeout=30.0` (`multi_llm_hub/client.py:59`, `:119`), `DialogueRunner|DialogueTurn|DialogueResult` hat in `.py` keine Treffer.

**Must-Fix ERROR List**

1. Timeout-/Fehlerprotokoll aus FK-11 §11.2.3 vollständig aufnehmen: release-finally, neuer Slot, max 1 Timeout-Retry.
2. §11.4.6-Telemetrie und QA-Artefakt-Logging als AC ergänzen.
3. Dreistufige Antwortverarbeitung korrekt modellieren: Prompt-Template-Vertrag, JSON-Block-Extraktion, Schema-Deserialisierung, Regex-Fallback.
4. `LlmClient`/HubClient-Datei-Handling-Konflikt auflösen.
5. `llm_roles`/AG3-070 Dependency oder Routing-Schnitt sauber festlegen.
6. Fail-closed-Observable festlegen: Exception vs. FAIL-Result.
7. Regex-Fallback-AC mit konkretem CheckResult-Verhalten schärfen.
8. Routing-Owner gegen FK-75/prompt_runtime klären.
