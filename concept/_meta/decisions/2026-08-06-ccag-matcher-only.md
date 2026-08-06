---
concept_id: META-DEC-2026-08-06-CCAG-MATCHER-ONLY
title: Concept-Decision-Record — CCAG-Matcher ohne Permission-Autoritaet
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to:
  - FK-42
  - FK-55
supersedes:
  - META-DEC-2026-07-14-CCAG-CENTRAL-OWNER
superseded_by:
tags: [meta, decision-record, ccag, hooks, matcher, AG3-226]
formal_scope: prose-only
---

# Concept-Decision-Record — CCAG-Matcher ohne Permission-Autoritaet

Datum: 2026-08-06. Record gemaess META-CONCEPT-CONSISTENCY P3 und W4 fuer
AG3-226, Auslegung A.

## 1. Anlass

CCAG trug neben dem weiterhin benoetigten Hook-Identifier und Tool-Matcher ein
vollstaendiges Verfahren fuer persistente menschliche Freigaben: Regeldateien,
Requests, Leases, API-Routen, CLI-Kommandos, Projektionen und State-Backend-
Tabellen. Die Product-Entscheidung fuer AG3-226 hebt diese Autoritaet auf. Der
Matcher muss nach FK-91 §91.4 fuer beide Harness-Einstiege bestehen bleiben.

## 2. Entscheidung

`ccag_gatekeeper` bleibt als registrierter, zustandsloser Hook mit dem Matcher
`Bash|Write|Edit|Read|Grep|Glob|Agent` bestehen. Er erteilt und verweigert keine
Freigabe, erzeugt keine Regeln und materialisiert keinen Request oder Lease.
Claude Code und Codex fuehren denselben autoritaetslosen Backend-Endpunkt aus.
Die Aussage ueber fehlende State-Schreibwirkung bezieht sich dabei exakt auf
Permission- und `PhaseState`-State. Der gemeinsame Hook-Dispatcher zaehlt den
Aufruf weiterhin ueber `_record_guard_invocation()` als FK-61-KPI. Dieser
generische Control-Plane-Schreibvorgang ist eine eigene Beobachtungsaufgabe und
wird bewusst nicht fuer CCAG ausgenommen; eine Ausnahme wuerde den KPI
verfaelschen, ohne das abgeschaffte Permission-Verfahren weiterzutragen.

Harte Guards und Principal Capabilities entscheiden weiterhin vor diesem
Endpunkt. Eine im `story_execution`-Modus unbekannte Operation wird unmittelbar
durch das Principal-Capability-Modell blockiert; daraus entsteht kein spaeter
entscheidbarer Fall. In anderen Modi darf der Harness innerhalb seiner eigenen
Grenzen handeln. Wo frueher ausschliesslich eine CCAG-Regel blockiert haette,
blockiert CCAG nicht mehr. Dies ist die ausdruecklich gewollte Wirkung der
Auslegung A und kein Fehler-Bypass einer fortbestehenden Autoritaet.

Upgrades entfernen die drei obsoleten Dateien
`.agentkit/ccag/rules/global.yaml`, `subagents.yaml` und `approved.yaml`
unbedingt, auch bei menschlich bearbeitetem Inhalt. Ihr Erhalt waere eine
irrefuehrende Governance-Leiche; andere Dateien und die Hook-Registrierung
bleiben unberuehrt. Derselbe produktive Upgrade-Pfad entfernt aus einer
bestehenden `project.yaml` exakt den obsoleten Zweig `pipeline.permissions`,
einschliesslich seines einzigen definierten Blatts `request_ttl_s`, auch ohne
Versionssprung. Vor der Mutation entsteht die vorgeschriebene `.bak`. Andere,
auch schemafremde Geschwisterschluessel bleiben unangetastet; die Migration ist
kein generischer Unknown-Key-Filter.
Die `.bak` liegt als einzelner rollierender Vor-Migrationsstand unter
`.agentkit/config/project.yaml.bak`. AgentKit behaelt sie nach erfolgreicher
Migration fuer das manuelle Nachziehen erkannter Nutzeranpassungen; die naechste
Migration ersetzt sie atomar, und nach Verifikation beziehungsweise Nachziehen
entfernt sie der Projektverantwortliche.
Vor Regeldatei-Cleanup und Config-Mutation wird die projektlokale Pfadidentitaet
ueber die zentrale Filesystem-Boundary bewiesen. Ein Symlink oder eine Junction
im Pfad blockiert fail-closed, damit weder Loeschung noch Backup/Rewrite aus dem
Zielprojekt entkommen kann.

Bereits initialisierte SQLite- und PostgreSQL-Backends behalten die physischen
Tabellen `ccag_permission_requests` und `ccag_permission_leases`. Der Product
Owner hat am 2026-08-06 bewusst die nicht-destruktive Variante entschieden:
kein `DROP`, keine Schema-Migration und kein Reset. Beide Tabellen sind tot,
werden von keinem Code gelesen oder geschrieben und koennen nicht erneut
befuellt werden. Ihre physische Altbestandsverantwortung liegt beim
`state_backend`. Neue Backends legen sie nicht mehr an; die kanonischen
Frischschemas enthalten beide Tabellen nicht.

Der Impact-Sweep hat ausserhalb des Entscheidungsumfangs eine vorbestehende
Freeze-Luecke sichtbar gemacht: Ein aktiver `conflict_freeze` wird beim
`Agent`-Spawn nur als `CapabilityHull.freeze_verdict=deny` transportiert.
`prompt_integrity` wertet den Hull nicht aus, ein anderweitig gueltiger Spawn
geht durch. Das galt bereits vor AG3-226: Am Basisstand `8eefd4f4` pruefte die
alte CCAG-Runtime nur, ob ein Hull vorhanden war, nicht dessen
`freeze_verdict`. Ferner existiert produktiv kein Aufrufer der von FK-91 dem
GuardSystem bzw. der Eskalationslogik zugewiesenen
`ConflictFreezeOverlay.freeze()`-Aktivierung. Beides wird nicht in dieser Story
behoben, sondern als gemeinsamer Schnitt fuer eine Folgestory festgehalten.

## 3. Alternativen

- Eine read-only oder mit `410` endende Kompatibilitaetsroute wurde verworfen,
  weil sie das abgeschaffte Verfahren als erreichbare Oberflaeche fortsetzt.
- Das Behalten alter Regeln als inaktive Customization wurde verworfen, weil
  dies eine nicht mehr erreichbare Autoritaet suggeriert.
- Das Entfernen des Matchers wurde verworfen, weil FK-91 §91.4 seine
  Registrierung fuer beide Harnesses verlangt.
- Ein Ersatz-Freigabeverfahren wurde verworfen; die Entscheidung hebt die
  Autoritaet auf und fuehrt keine neue ein.

## 4. Impact-Sweep (P3/W4)

Der Sweep zaehlte aktive Markdown-Normen in `concept/domain-design`,
`concept/technical-design`, `concept/formal-spec` und
`concept/_meta/bc-cut-decisions.md` auf. Gesucht wurde nach CCAG- und
Permission-Request-Begriffen, Request-/Lease-Typen, Routen und Kommandos,
State-/Projektionsnamen, FK-18/FK-90 sowie den drei Regeldateien. Historische Decision
Records wurden nicht umgeschrieben; der bisher aktive Central-Owner-Record wird
durch diesen Record explizit superseded. Betroffen sind insbesondere DK-09,
DK-12, FK-01/02/03/04/07/10/15/24/27/30/31/35/42/51/55/56/71/90/91/92/93,
der BC-Cut und die formalen Principal-Capability-, Operating-Mode-, Frontend-,
Guard- und Architekturvertraege.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| DK-09 / DK-12 | geaendert | CCAG ist Matcher-Metadaten, keine Berechtigungsquelle. |
| FK-42 | ersetzt | Matcher und Registrierung bleiben; Regeln, Requests und Autoritaet entfallen. |
| FK-55 / formale Principal Capabilities | geaendert | Unbekannte Story-Operationen blockieren direkt; Request-/Lease-Zustaende entfallen. |
| FK-30 / FK-91 / Operating Modes | geaendert | Beide Hook-Einstiege behalten den Matcher ohne Entscheidungswirkung. |
| FK-10 / FK-18 / FK-90 / State-Backend | geaendert | Request-/Lease-Owner, Records und Projektionen entfallen. Alte Backends behalten die zwei toten Tabellen unter `state_backend`-Ownership; neue Backends legen sie nicht an. |
| FK-03 / FK-51 / FK-92 / Zielprojekte | geaendert | Regeldateien werden nicht mehr installiert und bei Upgrade entfernt. |
| Bestehende `project.yaml` | geaendert | Upgrade entfernt gezielt `pipeline.permissions`, bewahrt fremde Geschwister und schreibt zuvor `.bak`. |
| FK-04 / FK-35 | geaendert | Runbook und Integrity-Sicht behandeln nur externe Host-Interferenz. |
| FK-15 / FK-27 / FK-31 / FK-71 | geaendert | Dedizierte Guards sind alleinige benannte Schutzstellen. |
| Control-Plane- und CLI-Katalog | entfernt | Keine Request-/Lease-Route und kein Freigabekommando bleibt erreichbar. |
| Alter Central-Owner-Record | superseded | Der Owner existiert nicht mehr, weil die gesamte State-Familie entfaellt. |
| FK-61 Guard-KPI | unveraendert | Der generische Aufrufzaehler bleibt bewusst auch fuer `ccag_gatekeeper`; er ist weder Permission- noch PhaseState-State. |
| Conflict-Freeze / Agent-Spawn | Befund, Folgestory | Vorbestehender fehlender Producer/Consumer; ausserhalb des AG3-226-Scopes. |

## 6. P4-Formalisierungspruefung

Ja. Entities, Commands, Events, State-Machine, Invariants und Scenarios des
Principal-Capability-Vertrags wurden um Request-/Lease-Verfahren bereinigt.
Operating-Mode-, Frontend-, Guard- und Architekturformalia bilden die
verbleibende Matcher-Grenze und die direkten Blockaden ab.
