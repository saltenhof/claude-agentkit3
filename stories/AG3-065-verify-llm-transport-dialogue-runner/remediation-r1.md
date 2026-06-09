# AG3-065 — Remediation R1 (Antwort auf review-r1.md)

**Story:** AG3-065 — Verify-LLM-Transport + DialogueRunner + Timeouts
**Review:** `review-r1.md` (OVERALL: CHANGES-REQUESTED)
**Ergebnis:** `story.md` neu geschrieben; `status.yaml` geprüft (korrekt, keine Änderung nötig); nur `story.md` und diese `remediation-r1.md` geschrieben.

**Scope-Leitplanke:** Schnitt aus `var/concept-gap-analysis/_STORY_INDEX.md:56` — `FK § = FK-11 §11.2-§11.6`, `depends_on = AG3-043, AG3-075`, Scope = konkreter LLM-Pool-Adapter / dreistufige Verarbeitung / DialogueRunner / Timeouts / vollständiges Logging. **Konsument laut Index = AG3-079** (`:80`), **nicht** AG3-062. Es wurde **kein** Scope hinzugefügt, der über diesen Schnitt hinausgeht; mehrere Befunde wurden bewusst durch *Verengung* statt Erweiterung gelöst.

---

## Must-Fix ERRORs

### ERROR 1 — FK-11 §11.2.3 Fehlerprotokoll unvollständig (release-finally, neuer Slot, max-1-Timeout-Retry)
**Befund:** Story reduzierte „Timeout → fail-closed" und testete kein Release-on-error.
**Resolution:** Eigener Scope-Punkt 2.1.3 „Acquire/Send/Release-Fehlerprotokoll" aufgenommen: Release im `finally` bei jedem Ausgang; Send-Timeout → genau **1** Retry mit **neuem** Slot; `lease_expired` → neuer Acquire (unter dieselbe Max-1-Grenze); danach fail-closed. Eigene Quell-Konzept-Zeile ergänzt (`FK-11 §11.2.3`). AC3 deckt das mit drei Teil-Tests ab (release-count, Slot-Retry mit zwei `acquire`-Calls, harte ≤2-Sends-Obergrenze). Diese Transport-Retry-Stufe ist explizit **getrennt** vom Schema-Retry markiert.

### ERROR 2 — §11.4.6 Telemetrie + QA-Artefakt fehlte (`llm_call` mit pool/role/retry/check_count/status)
**Befund:** Story forderte nur Prompt-/Antwort-Persistenz, ließ das `llm_call`-Telemetrie-Event aus.
**Resolution:** §11.4.6 als **zwei** Pflichten modelliert: (a) QA-Artefakt mit vollständigem Prompt + roher Antwort (an `prompt_audit.py` angedockt); (b) `llm_call`-Event mit Payload `{pool, role, retry, check_count, status}`. Scope-Punkt 2.1.8 + AC9 (beide Teil-Tests). Out-of-Scope-Note: breiter EventType-Katalog = AG3-081; AG3-065 emittiert nur, ergänzt den EventType minimal falls nötig.

### ERROR 3 — §11.4.4 Stufe 1 falsch wiedergegeben (Prompt-Template-Vertrag, nicht JSON-Extraktion)
**Befund:** Story machte aus Stufe 1 „JSON-Block extrahieren + json.loads"; FK-Stufe 1 ist das Prompt-Template mit expliziter JSON-Antwort-Vorgabe.
**Resolution:** Stufen korrekt neu zugeordnet: Stufe 1 = **Prompt-Template-Vertrag** (JSON-Antwort-Vorgabe im Template), Stufe 2 = JSON-Block-Extraktion + Deserialisierung, Stufe 3 = Regex-Fallback. Stufe-1-Template-Vertrag als eigene Pflicht mit Contract-/Golden-Test (Scope 2.1.4 + **AC5**). Anker präzisiert auf die FK-Überschriften (siehe WARNING 4).

### ERROR 4 — `LlmClient`/HubClient-Datei-Handling-Konflikt (`merge_paths`/`file_paths`)
**Befund:** Story wollte Port schmal halten **und** Datei-Handling durchreichen — nicht implementierbar; weder Port (`complete(*, role, prompt)`, `llm_client.py:55`) noch `HubClient.send` (`client.py:168-204`) tragen Datei-Parameter.
**Resolution:** Datei-Handling **vollständig aus AG3-065 entfernt** und an den Owner **AG3-061** (EvidenceAssembler/`merge_paths`, FK-28) geroutet — der Index-Schnitt nennt für AG3-065 ohnehin kein Datei-Handling. Story reicht ausschließlich `prompt: str` durch; Port und `HubClient.send` werden **nicht** erweitert. Explizit in §1 Konfliktcheck, §2.2 Out-of-Scope und §6 dokumentiert.

### ERROR 5 — `llm_roles`/AG3-070-Dependency vs. „produktive Default-Wahl"
**Befund:** Story konsumierte `llm_roles`, aber `status.yaml` hing nicht von AG3-070 ab.
**Resolution:** Gelöst durch **Routing-Schnitt statt Dependency** (in Übereinstimmung mit dem Index, der `depends_on = AG3-043, AG3-075` festschreibt — AG3-070 ist dort **nicht** gelistet). AG3-065 definiert/konsumiert einen **injizierten `RolePoolResolver`-Port**; die produktive Implementierung (`llm_roles`-Parsing) ist AG3-070 (Out-of-Scope). Fehlt der Resolver → fail-closed (`FailClosedLlmClient`). Damit ist AG3-065 ohne AG3-070 produktiv und negativ testbar (AC2). `status.yaml` bleibt korrekt (kein AG3-070-Eintrag) — kein Widerspruch mehr.

### ERROR 6 — Fail-closed-Observable unklar (Exception vs. FAIL-Result)
**Befund:** Unklar, ob `evaluate()` ein FAIL-Result liefert oder eine Exception propagiert.
**Resolution:** Eindeutig festgelegt (Scope 2.1.6 + AC6): `evaluate()` **propagiert weiterhin die Exception** (`StructuredEvaluatorError`/`LlmClientError`, wie heute `structured_evaluator.py:319-323`/`:329-334`); das **Layer-2-Blocking** entsteht in der Layer-2-Integration, die die Exception fängt. **Kein** neuer „FAIL-Result"-Pfad (FIX THE MODEL: ein Fehlerkanal). AC6 testet beide Ebenen.

### ERROR 7 — Regex-Fallback-AC ohne konkretes CheckResult-Verhalten
**Befund:** „Regex-Fallback liefert Verdict" war mehrdeutig (Role-Verdict vs. `list[CheckResult]`); realer Code validiert `list[CheckResult]`.
**Resolution:** AC4 + Scope 2.1.4 Stufe 3 präzisiert: Regex-Fallback extrahiert `status`/`reason`/`description` aus Freitext (FK-11, Konzept-Zeile 345-350), baut `CheckResult`-Objekte mit korrekter **`check_id`-Zuordnung** und durchläuft die **bestehende** `_validate_completeness` (`structured_evaluator.py:402-446`) als unveränderte Schema-/Vollständigkeitswahrheit. Vier Tests inkl. Call-Count.

### ERROR 8 — Routing-Owner gegen FK-75/prompt_runtime
**Befund:** Story platzierte Rollen→Pool-Routing im Verify-Transport; FK-75 §75.3 sagt, fachliches Routing gehört nach `prompt_runtime`.
**Resolution:** Routing aus dem Verify-Transport **herausgeschnitten**: injizierter `RolePoolResolver`-Port (Owner = `prompt_runtime`/Config, FK-75 §75.3); der Adapter liest **keine** Config und baut **keine** zweite Routing-Wahrheit. Explizit in BC-Zeile, §1 Konfliktcheck, Scope 2.1.2, AC2, Guardrail-Referenzen und §6.

---

## WARNINGs

### WARNING 1 — Index-Scope §11.2-§11.6 nur teilweise abgedeckt (§11.3.3, §11.6.2, §11.6.3)
**Resolution (im Scope behandelt + präzise begrenzt):** §11.2.3 (Fehlerprotokoll) und §11.4.6 (Telemetrie+Artefakt) jetzt voll aufgenommen (ERROR 1/2). §11.3.3 „Runtime-Auflösung + `llm_call`": Auflösung über injizierten Resolver (AC2) + `llm_call`-Event (AC9) — die in §11.3.3 genannte `llm_roles`-Lese-Logik selbst ist bewusst AG3-070 (Routing-Owner, FK-75). §11.6.2 (Slot-Budget 1 sequentiell) ist durch das strikte acquire→send→release-Protokoll je Aufruf strukturell erfüllt; §11.6.3 (Queue-Warten bei `queued`) ist Pool-intern (FK-75-Hub) und ausdrücklich Hub-Server-Sache (§2.2 „Hub-Server/Pool-Implementierung = FK-75"). Die Quell-Konzept-Anker wurden auf die tatsächlich erfüllten Unteranker (§11.2.1/§11.2.3/§11.4.4/§11.4.6/§11.5.2/§11.6.1) präzisiert.

### WARNING 2 — AC8 „vier Konzept-Gates" ohne konkrete Befehle
**Resolution:** AC11 listet die vier Gates exakt: `check_concept_frontmatter.py`, `compile_formal_specs.py`, `check_concept_code_contracts.py`, `check_architecture_conformance.py` (alle unter `scripts/ci/`), plus expliziter Hinweis, dass Jenkins/Sonar separate Remote-Gates sind.

### WARNING 3 — AG3-062 als Konsument, aber Index führt AG3-062 ohne AG3-065-Dependency
**Resolution:** AG3-062 aus den Konsumenten **gestrichen**; als Konsument bleibt nur **AG3-079** (Index `:80`). AG3-062 wird in §2.2 mit der Ordering-Notiz geführt (vor AG3-065, `depends_on: AG3-061`, kein garantierter Konsument). BC-Zeile und §6 entsprechend bereinigt.

### WARNING 4 — FK-11 hat zwei `### 11.4.4`-Überschriften (mehrdeutiger Anker)
**Resolution:** Beide Anker mit Titel + Konzept-Datei-Zeilennummer disambiguiert: `FK-11 §11.4.4 "Dreistufige Antwort-Verarbeitung"` (Zeile 310) und `FK-11 §11.4.4 "Regeln (aus FK)"` (Zeile 360). Pauschales „§11.4.4/§11.4" entfernt.

---

## Korrektur falscher Code-Anker (alle gegen den realen Code verifiziert)

| Alt (story.md R0) | Neu (verifiziert) |
|---|---|
| `llm_client.py` „nur Port + FailClosed" (ohne Zeilen) | Port `llm_client.py:42-74`, `complete` Signatur `:55`, `FailClosedLlmClient` `:77-112` |
| `structured_evaluator.py:299-372` (strikt json.loads, kein Retry) | `evaluate` `:299-350`, `_parse_response` `:352-372`, strikt `json.loads` `:358`, Raise `:359-361`/`:371-372` |
| `StructuredEvaluatorResult` „nur Hashes" (ohne Zeilen) | `:247-269` |
| `multi_llm_hub/client.py:59` (timeout 30) | bestätigt `:59` **und** `:119` (HubClient-Default) |
| `multi_llm_hub/client.py:92-216` | präzisiert `:92-235`; `send` ohne Datei-Parameter: Protocol `:99-107`, Impl `:168-204` |
| `prompt_audit*.py` (vage) | konkret `verify_system/prompt_audit.py`, `materialize_qa_prompt_audit` (Zeile 28) |
| `_validate_completeness` (nicht referenziert) | `structured_evaluator.py:402-446` (bleibt Schema-Wahrheit für Stufe 2/3) |

PASS-Teilbefund des Reviews (Ist-Zustandsclaims überwiegend korrekt) wurde durch direkte Code-Lektüre bestätigt; die wenigen ungenauen Zeilenangaben sind oben korrigiert.

---

## status.yaml
Geprüft, **keine Änderung**: `depends_on: [AG3-043, AG3-075]` stimmt exakt mit dem Index-Schnitt (`_STORY_INDEX.md:56`) überein. ERROR 5 wurde bewusst durch den injizierten Resolver-Schnitt (nicht durch eine AG3-070-Dependency) gelöst, damit Story und Index konsistent bleiben. `status: draft` / `phase: review_pending` sind korrekt (Template-konform).

## Geschriebene Dateien (nur diese)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/story.md` (neu geschrieben)
- `stories/AG3-065-verify-llm-transport-dialogue-runner/remediation-r1.md` (dieser Report)
- `status.yaml`: **nicht** geändert (geprüft, korrekt).

**Keine** Produktionscode-, Test- oder `concept/`-Datei wurde angefasst.
