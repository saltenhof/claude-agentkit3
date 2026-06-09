# AG3-062 — Remediation R1 (Antwort auf review-r1.md)

**Scope der Remediation:** ausschliesslich `story.md` neu gefasst. `status.yaml` blieb unveraendert (Begruendung siehe Finding 6). Keine Produktionscode-/Test-/Konzept-Aenderung. AG3-057-Template-Struktur (Abschnitte 1–6) beibehalten.

**Leitkorrektur (vom Auftraggeber vorgegeben):** FK-47 normiert eine invalide Preflight-Antwort als `requests=[] + WARNING` mit Weiterlauf des Reviews — **kein** fail-closed Parse-Fehler. Die Story trug an mehreren Stellen das falsche fail-closed-Verhalten und haette diese FK-47-Inkompatibilitaet sogar in Tests zementiert. Die Story ist jetzt durchgaengig auf das FK-normierte Verhalten ausgerichtet.

---

## Must-Fix-Findings (ERROR)

### Finding 1 — FK-47 Parse-/Fehlertoleranz-Konflikt (Konzept-Vollstaendigkeit: FAIL)
**Befund:** Story (alt §2.1.5/§2.1.8, AC7, Guardrail §5) forderte „fail-closed Parse-Fehler" bei schema-invalider Preflight-Antwort; FK-47 §47.3 (`47_request_dsl_und_preflight_turn.md:138-149`) und §47.5 (`:330`) normieren `requests=[] + WARNING`, Review laeuft weiter.
**Resolution:** Story auf das FK-Verhalten korrigiert (kein vorheriger FK-47-Aenderungsbedarf — die FK-Norm ist autoritativ und korrekt):
- §2.1.4 `parse_preflight_response` jetzt exakt nach FK-47 §47.3 dokumentiert: Parse-Fehler (`JSONDecodeError`/`KeyError`/`TypeError`/`ValueError`) → leere Liste + WARNING, kein Abbruch.
- §2.1.5 Preflight-Turn-Fehlertoleranz exakt nach FK-47 §47.5 (`:328-335`): Parse-Fehler/alle-UNRESOLVED/Timeout → Review laeuft mit Original-Bundle weiter.
- §5 Guardrail-Referenzen trennt jetzt explizit „FAIL CLOSED (wo FK es vorsieht)" von den FK-normierten Toleranz-Pfaden (WARNING statt ERROR).

### Finding 2 — Transport-Schnitt widerspruechlich (Konzept-Vollstaendigkeit: FAIL)
**Befund:** FK-47 §47.5 (`:275-281`) verlangt direkten MCP-Pool-Call (nicht `LlmEvaluator`/`StructuredEvaluator`); AG3-065 (`AG3-065 story.md:80`/`:82`) sagt zugleich, AG3-062 ist kein garantierter Konsument und AG3-065 liefert kein `merge_paths`/Datei-Handling. Die alte Story haengte den Send unklar an „AG3-065 bzw. dessen Port" und ersatzweise an den datei-freien `LlmClient`-Port.
**Resolution:** Eindeutiger Schnitt: AG3-062 definiert einen **eigenen, schmalen, datei-faehigen** Preflight-Send-Port (`send(*, prompt, merge_paths)`, neu §2.1.6) + `FailClosedPreflightReviewSender`-Default (Muster `FailClosedLlmClient` `llm_client.py:77-112`). Der datei-freie Layer-2-`LlmClient`-Port (`llm_client.py:55`) bleibt unveraendert und wird **nicht** missbraucht. Der konkrete MCP-Pool-Adapter ist Out of Scope (§2.2). Begruendung in §1 „Transport-Abgrenzung zu AG3-065" mit Belegen. AC10 verprobt den fail-closed Port + die Unveraendertheit des Layer-2-Ports.

### Finding 3 — AC7/Guardrail machen den falschen Invalid-JSON-Pfad testpflichtig (AC-Schaerfe: FAIL)
**Befund:** AC7 (alt) und Guardrail forderten den fail-closed-Invalid-JSON-Test und haetten die FK-47-Inkompatibilitaet zementiert.
**Resolution:** AC7 neu gefasst — drei Faelle: gueltige Antwort → aufgeloeste Requests + `extended_paths`; schema-invalide Antwort → leere Liste + WARNING + Weiterlauf mit Original-Bundle (Test belegt alle drei: leere Liste, Weiterlauf, emittierter WARNING; **kein** Silent Drop); alle-UNRESOLVED → Weiterlauf. §2.1.9 Negativ-/Grenzpfade entsprechend umgestellt.

### Finding 7 — `status.yaml`/Dependency-Sinnhaftigkeit (Kontext-Sinnhaftigkeit: FAIL)
**Befund:** `status.yaml` haengt nur an AG3-061, obwohl die alte Story AG3-065-Transport als Nutzpfad nannte; AG3-065 ist selbst `draft` und nicht als Dependency gesetzt.
**Resolution (Variante B des Reviews: AG3-062 ohne AG3-065 formulieren):** Die Story ist jetzt **transport-unabhaengig** geschnitten (eigener Preflight-Send-Port + fail-closed Default). Damit ist `depends_on: [AG3-061]` in `status.yaml` **genau richtig** und deckt sich mit dem Index-Schnitt (`_STORY_INDEX.md:53`, `depends_on: AG3-061`) und mit AG3-065s eigenem Cut (`AG3-065 story.md:82`: AG3-062 kein garantierter Konsument). **`status.yaml` wurde daher NICHT geaendert** — kein Feld war fachlich falsch; eine AG3-065-Dependency waere im Gegenteil eine erfundene, vom Index abweichende Abhaengigkeit auf eine Faehigkeit (datei-faehiger Send), die AG3-065 laut Scope nicht liefert.

---

## WARNINGs

### Finding 4 — AC5 `MAX_REQUESTS`-Overflow vs. FK-47 (AC-Schaerfe: WARNING)
**Befund:** AC5 (alt) forderte „> 8 Requests fail-closed"; FK-47 kappt deterministisch via `raw_requests[:MAX_REQUESTS]` (`:147`)/`requests[:MAX_REQUESTS]` (`:179`).
**Resolution:** §2.1.4b + AC5 vereinheitlicht: Ueberlauf → deterministische Kappung auf die ersten 8 + WARNING (kein fail-closed Abbruch). Der WARNING wird real emittiert und ist dem Auftraggeber zu spiegeln (CLAUDE.md SEVERITY-SEMANTIK). FK-konform.

### Finding 5 — Modulpfad implizit (Klarheit: WEAK/WARNING)
**Befund:** FK-28/46 nennen `agentkit/evidence/`, realer AK3-Schnitt ist `agentkit/verify_system/evidence/`; AG3-061 erklaert die Abweichung, AG3-062 nicht.
**Resolution:** §1 Abschnitt „Modulpfad (FK-§ vs. AK3-BC-Schnitt, belegt)" ergaenzt; §2.1-Preambel und AC1 nennen explizit `src/agentkit/verify_system/evidence/{import_resolver.py, request_types.py, request_resolver.py}` (+ Preflight-Turn/Port). Belegt mit `46_import_resolver.md:329`, `47_..._turn.md:55`/`:119` und `AG3-061 story.md:69`.

### Finding 6 — Template-Scope ohne Manifest-Registrierung (Klarheit: WARNING)
**Befund:** Template-Scope nannte nur die Datei unter `resources/`; vorhandene Prompt-Bundles sind manifest-registriert (`manifest.json:4`).
**Resolution:** §2.1.8 + neues AC9: Pflicht-Registrierung im Prompt-Manifest `src/agentkit/resources/internal/prompts/manifest.json` mit `relpath` + `sha256` und hochgezogener `bundle_version`; Contract-Test gegen den Hash, am bestehenden Eintrags-Muster (`:4-45`) ausgerichtet.

---

## Code-Anker-Korrekturen (file:line gegen realen Code verifiziert)
- `telemetry/contract/preflight_sentinel.py` Klasse `PreflightSentinel` → real `:50` (Konstanten ab `:41`). Aufgenommen.
- `telemetry/events.py` `PREFLIGHT_REQUEST/RESPONSE/COMPLIANT` → real `:61-63`. Aufgenommen.
- `verify_system/evidence/__init__.py` Leerstub (1 Zeile) → bestaetigt. Aufgenommen.
- `verify_system/llm_evaluator/llm_client.py`: `LlmClient.complete(*, role, prompt) -> str` `:55`, `FailClosedLlmClient` `:77-112` → bestaetigt. Aufgenommen.
- `governance/setup_preflight_gate/preflight.py` (Setup-Preflight, anderes Konzept) → Pfad praezisiert (vorher generisch `governance/setup_preflight_gate/*`).
- FK-Anker: `46_import_resolver.md:329` (Modul-Kommentar `agentkit/evidence/import_resolver.py`), `47_..._turn.md:138-149` (`parse_preflight_response`), `:147`/`:179` (Kappung), `:275-281` (direkter MCP-Pool-Call), `:311-326` (Ablaufschema), `:328-335` (Fehlertoleranz), `:394` (Sentinel) → verifiziert und eingebettet.
- ConfidenceLabel-Quelle praezisiert: FK-46 **§46.5** (`:287`/`:293-302`) statt vager §46.3.

---

## PASS-Finding (unveraendert bestaetigt)
Die Ist-Zustands-Anker waren bereits real (Review PASS): FK-46/47 laut Gap-Audit fehlend, `verify_system/evidence/__init__.py` leer, `PreflightSentinel`/`PREFLIGHT_*` vorhanden, Setup-Preflight ein anderes Konzept. Diese Anker wurden in der Neufassung beibehalten und nur um exakte file:line ergaenzt.

---

## Genuine Cross-Story-Voraussetzungen / -Hinweise
1. **AG3-061 (harte Vorbedingung, unveraendert):** liefert EvidenceAssembler/`BundleManifest`/`AuthorityClass`/`RepoContext`/`merge_paths` + den erweiterbaren Stufe-2-Eingang. AG3-062 konsumiert/erweitert nur, baut den Assembler nicht um. `status.yaml depends_on: [AG3-061]` bleibt korrekt.
2. **AG3-065 ist KEINE Voraussetzung von AG3-062** (bewusste Cut-Entscheidung, vom Index gedeckt): AG3-062 ist transport-unabhaengig geschnitten (eigener datei-faehiger Preflight-Send-Port + fail-closed Default). Ein **konkreter** produktiver MCP-Pool-/Hub-Adapter hinter diesem Port ist Out of Scope und muss von einer Transport-Story (AG3-065 oder einer dedizierten Transport-Story) geliefert/injiziert werden, **bevor** der Preflight-Send produktiv laeuft — bis dahin fail-closed. Das ist ein **fachlicher Nachfolger fuer die produktive Aktivierung**, kein Build-Blocker fuer die hier gelieferten Port-/Turn-/Resolver-Artefakte. Diese Aktivierungs-Voraussetzung ist dem Auftraggeber zur Priorisierung zu spiegeln (WARNING-Charakter, aufschiebend).

Keine weitere Story wird in Anspruch genommen, etwas zu liefern, das ihr Scope nicht deckt. Insbesondere wird AG3-065 **nicht** als Lieferant der datei-faehigen Send-Oberflaeche behauptet (das schliesst AG3-065s Scope aus).
