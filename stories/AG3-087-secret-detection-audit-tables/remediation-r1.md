# AG3-087 — Remediation Report (Review R1)

**Review:** `review-r1.md` (OVERALL: CHANGES-REQUESTED, hostile Codex review)
**Scope-Quelle:** `var/concept-gap-analysis/_STORY_INDEX.md` Zeile AG3-087 (Welle 5, governance-and-guards). Es wurde **kein** Scope ueber den Index-Schnitt hinaus aufgenommen.
**Geaenderte Dateien:** `story.md` (Vollumschrift, Template-Struktur AG3-057 erhalten). `status.yaml` unveraendert (kein falsches Feld, siehe unten). Dieser Report.

---

## Must-Fix ERRORs

### ERROR 1 — Pre-Commit-Hook + identische Patterns (Konzept-Vollstaendigkeit)
**Befund:** FK-15 §15.5.2 verlangt zweistufige Secret-Detection (Stufe 1 Pre-Commit-Hook, Stufe 2 Structural-Check) mit **identischen** Patterns. Die Story scopte nur `composition_root`/Structural-Check; der reale Hook `.githooks/pre-commit` macht nur Concept-Validation.
**Resolution:** In Scope (§2.1.1) eine **gemeinsame, typisierte Pattern-Quelle** im `guard_system`-BC aufgenommen, die **beide** Stufen speist (kein zweites Set). Stufe 1 = Secret-Scan im realen Hook `.githooks/pre-commit` (global aktiv, unabhaengig vom pfadbasierten Concept-Dispatching), Pattern-Logik in `src/agentkit/` (ARCH-55), Hook ruft sie nur auf. Stufe 2 = `security.secrets` (Patterns vervollstaendigt) + neue `security.secrets_content`-Stage. Neues AC1 verlangt beide Stufen + Single-Pattern-Source-Test; AC3 die Patterngruppen. Tests (§2.1.8) decken beide Stufen ab. Belegte Ist-Zustand-Zeile auf `.githooks/pre-commit:19-31` korrigiert; FK-Prosa-Pfad-Drift (`tools/hooks/pre-commit`) als Doc-only an **AG3-102** geroutet (§2.2), Implementierung gegen realen Pfad.

### ERROR 2 — Custom-Field-Entitaeten unvollstaendig + Owner falsch
**Befund:** Story nannte nur `provider_sync_status`/`conflict_detected`/`is_writable_by_agentkit`; FK-17 §17.3.4/5 verlangt den vollen Feldsatz. Owner war faelschlich `governance`+`state_backend`; FK-17/FK-18 setzen `story_context_manager`.
**Resolution:** §2.1.4 listet jetzt den **vollstaendigen** FK-17-Feldsatz fuer Definition **und** Value (alle vom Reviewer genannten Felder: `display_name`/`field_type`/`provider`/`provider_field_ref`/`is_required`/`allowed_values` bzw. `value`/`value_status`/`source`/`last_synced_at`/`last_written_by`/`last_sync_attempt_at` neben Sync/Conflict). Owner im BC-Header und §2.1.4 auf `story_context_manager` korrigiert; `state_backend` explizit nur als Persistenzadapter. AC5 verlangt Roundtrip fuer Definition **und** Value + Single-Writer-Schranke. Anker auf FK-18 §18.3.1 (Catalog-Family) / §18.6e.1 (Pflichtspalten) praezisiert (vorher pauschal „§18.4").

### ERROR 3 — Servicepfad-Attestierung nach §55.3a/§55.9/§55.10.3 (AC5-Schaerfe)
**Befund:** Altes AC5 sagte „Hook-Kontext"/„echter Servicepfad" — nicht testbar und zu eng; FK-55 §55.9 nennt Service-API **und** Operator-CLI, §55.3a vier Attestierungsquellen.
**Resolution:** „Hook-Kontext only" entfernt. §2.1.5 + neues AC6 definieren die vier §55.3a-Attestierungsquellen explizit, nennen konkrete §55.9-Positiv-Pfade einzeln (mind. `agentkit run-phase closure` als `pipeline_deterministic`, `agentkit reset-story` als `admin_service`/`human_cli`), behalten den Bash-Spoofing-Negativtest (§55.10.7) und verorten die Pruefung an FK-55 §55.10.3 Step 8. Quell-Konzepte um §55.3a/§55.9/§55.10.3/§55.10.4/§55.10.7 ergaenzt (adressiert auch WARNING „Quell-Konzepte unvollstaendig"). Vorhandenes Attestierungsmuster `principals.py:51-67` als Anker referenziert.

### ERROR 4 — Freeze-Nachweis nur Negativfall (Konzept-Vollstaendigkeit)
**Befund:** Story/AC deckten nur „fehlt -> blockiert"; FK-55 §55.10.8 fordert Audit-Nachweis fuer Aktivierungszeit, geblockten Principal, offiziellen Aufloesungspfad.
**Resolution:** §2.1.6 spezifiziert einen **kanonischen, persistenten** Proof-Record (Owner `guard_system`) mit den drei §55.10.8-Pflichtinhalten `activated_at`/`blocked_principal`/`resolution_service_path`, Erzeugung beim Freeze/bei Aufloesung, Persistenz im State-Backend. AC7 verlangt **positiven** Erzeugungs-/Persistenz-Roundtrip-Test **plus** den bestehenden Negativtest (Freeze ohne Nachweis -> nicht closure-faehig).

### ERROR 5 — Bounded Context fuer Custom Fields falsch/unklar (Klarheit)
**Befund:** Story ordnete alles `governance`+`state_backend` zu; FK-17/FK-18 Owner ist `story_context_manager` fuer Custom Fields, `guard_system` fuer GuardDecision.
**Resolution:** BC-Header in einen klaren mehrteiligen Owner-Schnitt umgeschrieben: `guard_system` (GuardDecision, Secret-Detection, Servicepfad, Freeze-Nachweis, Rueckkanal), `story_context_manager` (Custom Fields), `state_backend` nur Persistenzadapter. Owner pro Teilwert auch in den Scope-Punkten 3/4 benannt.

### ERROR 6 — Resultierender Scope passt nicht zum echten System (Kontext-Sinnhaftigkeit)
**Befund:** Ohne Hook-Stufe wuerde AG3-087 nach Umsetzung weiterhin FK-15 verletzen; echter Hook `.githooks/pre-commit` wurde nicht angefasst.
**Resolution:** Identisch zu ERROR 1 geloest — Hook-Pfad realistisch (`.githooks/pre-commit`) benannt und in Scope/AC/Tests aufgenommen. Damit erfuellt der resultierende Scope FK-15 §15.5.2 vollstaendig.

---

## WARNINGs

### WARNING A — AC7 „Begruendung" zu lax (FK-55 verlangt „kurze, strukturierte Begruendung")
**Resolution (gefixt in der Story):** §2.1.7 + neues AC8 geben ein **getyptes Allow-Schema** mit Feldern, Typen und Laengen-/Strukturgrenzen an; `reason` ist explizit „kurze, **strukturierte** Begruendung mit Laengen-/Strukturgrenze". Default-deny aller anderen Felder; verworfene Inhalts-Felder enumeriert (rohe Diffs, `context.json`/`are_bundle.json`-Zitate, vollstaendige Inhaltsartefakte, freie Prompt-/Bundle-Listen).

### WARNING B — Quell-Konzepte unvollstaendig fuer eigenen Scope
**Resolution (gefixt in der Story):** Quell-Konzepte-Liste um §55.3a, §55.9, §55.10.3 (Step 8), §55.10.4, §55.10.7 ergaenzt; FK-15-Anker auf §15.5.2 (zweistufig) praezisiert; FK-17/FK-18-Anker mit Ownern und §18.3.1/§18.3.3/§18.6e.1/§18.6e.3 geschaerft.

### WARNING C — Verifizierte Claims/Anchors (kein Handlungsbedarf)
Der Reviewer bestaetigte alle Ist-Zustand-Anker als korrekt. Eigene Nachpruefung:
- `composition_root.py:773` (`_SECRET_EXTENSIONS`) / `:805-806` (`secret_files`) — korrekt.
- `verify_system/structural/checker.py:459` (`_check_security_secrets`) — korrekt (Story nannte vorher nur den Pfad ohne Funktionsname; jetzt praezisiert).
- `matrix.py:26` („later"-Marker) / `enforcement.py:49-52` (deliberately rudimentary) — korrekt; Code-internes „Step 6" == FK-55 §55.10.3 step 8 in der Story aufgeloest.
- `principals.py:51-67` (`_ATTEST_FLAG`/`_PRIVILEGED`) — als positiver Attestierungs-Anker ergaenzt.
- `.githooks/pre-commit:19-31` (nur Concept-Validation) — verifiziert; Glob bestaetigt: einziger realer Hook ist `.githooks/pre-commit`.
- 0-Treffer-Claims (`guard_decisions`/`GuardDecision`, `story_custom_field*`/`StoryCustomField`, `security.secrets_content`, `is_official_service_path`, `freeze|conflict_freeze` in `integrity_gate/`) — uebernommen.
Keine falschen Ist-Zustand-Zeilen; keine Anker-Korrektur am Code noetig (nur Praezisierung von Funktionsnamen).

---

## status.yaml
Geprueft: `story_id`/`title`/`type`/`size`/`depends_on` (AG3-032, AG3-034) stimmen mit `_STORY_INDEX.md` ueberein; `phase: review_pending` ist konsistent zum Review-Stand. **Kein Feld falsch -> unveraendert gelassen.**

## Scope-Disziplin
Alle Fixes bleiben im Index-Schnitt von AG3-087 (Secret-Detection + Audit-Tabellen + Servicepfad/Freeze-Nachweis + Rueckkanal). Keine Scope-Ausweitung: angrenzende Themen (Permission-Lease/Request/Timeouts, CCAG, scope.json-Writer, Tabellen-Renames, Bugfix-Checks, KPI-Entitaet, Hook-Pfad-Doc-Drift, Branch-Guard-Owner) sind in §2.2 explizit an ihre Owner-Stories (AG3-086, AG3-064, AG3-083, AG3-102, AG3-104) geroutet, nicht hier implementiert.

## Beruehrte Dateien
- `stories/AG3-087-secret-detection-audit-tables/story.md` — neu geschrieben.
- `stories/AG3-087-secret-detection-audit-tables/remediation-r1.md` — dieser Report.
- `status.yaml` — geprueft, unveraendert.
Keine Produktionscode-, Test- oder `concept/`-Dateien beruehrt.
