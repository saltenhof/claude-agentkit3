---
concept_id: FK-42
title: CCAG Gatekeeper-Hook und Matcher-Katalog
module: ccag-tools
domain: governance-and-guards
status: active
doc_kind: core
parent_concept_id:
authority_over:
  - scope: ccag-tools
defers_to:
  - target: FK-30
    scope: hook-infrastructure
    reason: FK-30 owns registration ordering and harness materialization
  - target: FK-55
    scope: principal-capability-model
    reason: FK-55 owns capability grants and denials
  - target: FK-31
    scope: subagent-spawn-integrity
    reason: FK-31 owns the dedicated prompt-integrity guard for Agent calls
supersedes: []
superseded_by:
tags: [ccag, hooks, tools]
formal_refs:
  - formal.principal-capabilities.invariants
  - formal.principal-capabilities.scenarios
  - formal.operating-modes.invariants
prose_anchor_policy: strict
glossary:
  exported_terms:
    - id: ccag-gatekeeper
      definition: >
        Permanently registered PreToolUse hook identifier and matcher catalog
        Bash|Write|Edit|Read|Grep|Glob|Agent. The hook itself reads and writes
        no permission policy or PhaseState and grants or denies no operation.
        The shared dispatcher still records the generic FK-61 invocation KPI.
        Principal capabilities and dedicated guards decide first.
      see_also:
        - term: guard-system
          domain: governance-and-guards
  internal_terms: []
---

# 42 — CCAG Gatekeeper-Hook und Matcher-Katalog

<!-- PROSE-FORMAL: formal.principal-capabilities.invariants, formal.principal-capabilities.scenarios, formal.operating-modes.invariants -->

## 42.1 Zweck

CCAG bleibt als **registrierter Hook-Identifier und Matcher-Katalog** bestehen.
Der Matcher lautet unveraendert:

```text
Bash|Write|Edit|Read|Grep|Glob|Agent
```

Diese Registrierung macht die Harness-Kante und insbesondere die Einordnung des
`Agent`-Werkzeugs sichtbar. Sie ist keine Autoritaetsquelle.

## 42.2 Keine Permission-Autoritaet

**F-42-001 — Matcher ohne Entscheidungsautoritaet:** Der
`ccag_gatekeeper` erteilt keine Freigabe, blockiert nicht anhand von
Permission-Regeln und erzeugt keine Ausnahme. Sein produktives Ergebnis nach
den vorgeordneten Durchsetzungsstellen ist ein benanntes `ALLOW`, das nur den
erfolgreichen Durchlauf dieses registrierten Hook-Endpunkts bezeichnet.

**F-42-002 — Kein Permission-Request-Verfahren:** Es gibt weder Anlage,
Genehmigung, Ablehnung, Lease, Ablauf noch TTL-Eskalation eines
Permission-Requests. Es existieren dafuer keine Route, kein Kommando, kein
Ereignis und keine Persistenz.

## 42.3 Reihenfolge und verbleibende Autoritaet

**F-42-004 — Autoritaet vor Katalog-Endpunkt:** Die Principal-Capability-Schicht
aus FK-55 und die dedizierten Guard-Hooks aus FK-30/FK-31 laufen vor dem
`ccag_gatekeeper`. Ein dort entstandener Block ist final; der CCAG-Endpunkt wird
danach nicht aufgerufen.

**F-42-005 — Story-Ausfuehrung bleibt fail-closed:** Ein unbekannter oder nicht
entscheidbarer Vorgang im `story_execution`-Modus wird unmittelbar durch die
Principal-Capability-Schicht blockiert. Daraus entsteht kein spaeter genehmigbarer
Vorgang.

**F-42-006 — Gewollte Wirkung von Auslegung (A):** Hat die
Principal-Capability-Schicht einen Vorgang erlaubt oder im echten
`ai_augmented`-Modus an den Harness delegiert, fuegt CCAG keine weitere
Permission-Regel-Blockade hinzu. Ein Vorgang, den ausschliesslich eine fruehere
CCAG-Regel blockiert haette, wird daher durch CCAG nicht mehr blockiert. Das ist
der beabsichtigte Wegfall der CCAG-Autoritaet, kein stiller Fail-open einer noch
geltenden Regel.

## 42.4 Sub-Agent-Spawn

**F-42-007 — Matcher bleibt fuer `Agent`:** `Agent` bleibt Teil des Matchers.
Die Registrierung erteilt dem Spawn keine Capability. FK-55 erkennt den
kontrollplanartigen, pfadlosen Vorgang, damit er nicht als unbekanntes
Dateisystemwerkzeug vorzeitig abgefangen wird. Die eigentliche fail-closed
Spawn-Autoritaet ist der dauerhaft registrierte `prompt_integrity`-Hook aus
FK-31. Er prueft Governance-Escape, Spawn-Schema und Template-/Skill-Bindung.
Diese Autoritaet ersetzt nicht das Conflict-Freeze aus FK-55 §55.8: Ein aktiver
Freeze muss den Spawn vor dem Matcher blockieren. Ein nur in einem ungenutzten
Wert transportiertes Freeze-Signal erfuellt diese Pflicht nicht.

## 42.5 Harness-Vertrag

**F-42-008 — Claude Code:** Der Installer materialisiert den
`ccag_gatekeeper` als letzten `PreToolUse`-Hook mit dem zentral gerenderten,
absoluten `agentkit-hook-claude`-Wrapper.

**F-42-009 — Codex:** Der interpretergebundene Codex-Adapter dispatcht denselben
registrierten Hook-Identifier. Beide Harness-Einstiege erreichen denselben
zustandslosen Runner-Endpunkt.

**F-42-010 — Keine Permission-/PhaseState-Seiteneffekte:** Der CCAG-Endpunkt
darf weder einen Project-Edge-Mutationsclient noch ein State-Backend-Repository
konstruieren und darf keine Datei im Zielprojekt schreiben. Seine Eingabe
beeinflusst nur das benannte Durchlaufergebnis. Der umgebende gemeinsame
Hook-Dispatcher zeichnet den Aufruf weiterhin ueber
`_record_guard_invocation()` als FK-61-KPI auf. Dieser generische Zaehler ist
kein Permission- oder `PhaseState`-Schreibpfad und wird fuer CCAG bewusst nicht
durch einen Sonderfall verfaelscht.

## 42.6 Abgrenzung

- FK-30 besitzt Hook-Reihenfolge, Registrierung und Adaptervertrag.
- FK-31 besitzt die Prompt-Integrity-Durchsetzung der Agent-Kante.
- FK-55 besitzt Principal-, Operations-, Pfadklassen- und Freeze-Autoritaet.
- FK-91 katalogisiert Matcher, Routen und Ereignisse. Fuer CCAG verbleibt dort
  nur der Matcher; ein Permission-Request-API-Vertrag existiert nicht.

## 42.7 Bereinigung bestehender Zielprojekte

**F-42-003 — Keine persistente Regelbasis:** AK3 installiert, liest,
aktualisiert oder schuetzt keine menschlich genehmigten CCAG-Regeldateien.
Frueher materialisierte `global.yaml`, `subagents.yaml` und `approved.yaml`
werden beim Upgrade entfernt, weil kein produktiver Reader und keine Autoritaet
mehr existieren. Die Entfernung gilt auch fuer menschlich ergaenzte Inhalte;
eine scheinbar wirksame Rest-Policy waere fachlich falsch. Andere Dateien im
Verzeichnis bleiben unberuehrt. Derselbe produktive Upgrade-Pfad entfernt aus
`project.yaml` exakt `pipeline.permissions` samt dem frueher definierten
`request_ttl_s`, auch wenn kein Versionssprung ansteht. Vor der Mutation wird
eine `.bak` geschrieben. Andere, auch unbekannte Geschwisterschluessel bleiben
unveraendert; dies ist keine generische Bereinigung schemafremder Felder.
