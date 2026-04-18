---
title: Formal Spec Syntax Contract
status: active
doc_kind: core
authority_over:
  - scope: formal-spec-syntax
---

# Formal Spec Syntax Contract

## 1. Ziel

Dieses Dokument legt die verbindliche Dateisyntax fuer
`concept/formal-spec/` fest.

Die Syntax muss:

- mit dem Guardrail `concept/` = Markdown-only kompatibel bleiben
- fuer Menschen lesbar sein
- fuer den Compiler deterministisch parsebar sein
- Prosa und normative Semantik sauber trennen

## 2. Grundform jeder Datei

Jede Datei unter `concept/formal-spec/` besteht aus genau drei Ebenen:

1. YAML-Frontmatter
2. menschenlesbare Einleitung/Erlaeuterung in normalem Markdown
3. genau eine kanonische, maschinenlesbare Spezifikationszone

## 3. Frontmatter-Pflichtfelder

Jede Formal-Spec-Datei muss mindestens diese Felder im Frontmatter
tragen:

- `id`
- `title`
- `status`
- `doc_kind`
- `context`
- `spec_kind`
- `version`

Optional zulaessig:

- `depends_on`
- `prose_refs`
- `formal_refs`
- `tags`

## 4. Kanonische Spezifikationszone

Die normative Semantik einer Datei darf nur innerhalb einer explizit
markierten Spezifikationszone stehen.

Verbindliches Format:

```md
<!-- FORMAL-SPEC:BEGIN -->
```yaml
...
```
<!-- FORMAL-SPEC:END -->
```

Regeln:

1. Pro Datei ist genau **eine** solche Zone zulaessig.
2. Der Compiler liest nur den Inhalt zwischen
   `FORMAL-SPEC:BEGIN/END`.
3. YAML ausserhalb dieser Zone ist nicht normativ.
4. Freie Prosa ausserhalb dieser Zone ist erlaubt, aber nicht Teil der
   maschinenpruefbaren Semantik.

## 5. Kanonische YAML-Struktur

Der YAML-Inhalt innerhalb der Spezifikationszone beginnt immer mit:

- `object`
- `schema_version`
- `kind`
- `context`

Danach folgen die fuer den jeweiligen `kind` zulaessigen Felder.

## 6. Verbotene Formen

Nicht zulaessig sind:

- normative Listen nur im Fliesstext
- mehrere konkurrierende YAML-Zonen in einer Datei
- relevante Normdaten nur in Tabellen
- normative Semantik nur in Mermaid-Diagrammen
- Referenzziele, die nur ueber Dateinamen statt ueber IDs auffindbar
  sind

## 7. Kommentarstatus von Prosa

Freie Erlaeuterung ausserhalb der Spezifikationszone ist ausdruecklich
erlaubt und erwuenscht, aber hat Kommentarstatus.

Wenn Prosa normatives Verhalten beschreibt, muss sie dieses Verhalten
ueber Formal-IDs referenzieren. Die Prosa wird dadurch auditierbar,
ohne selbst die kanonische Liste erneut zu definieren.

## 8. Kontext-README

Jeder fachliche Kontextordner unter `concept/formal-spec/` enthaelt
zusaetzlich ein `README.md`.

Dieses README ist nicht die kanonische Spezifikation, sondern erklaert:

- Zweck des Kontexts
- enthaltene Dateien
- Abgrenzung zu anderen Kontexten
- relevante Prosa-Konzepte

## 9. Granularitaet

Die Dateigranularitaet ist bewusst mittelfein:

- nicht alles in eine Sammeldatei
- aber auch nicht von Beginn an eine Datei pro Zustand oder Event

Der Normalfall pro Kontext ist:

- `state-machine.md`
- `commands.md`
- `events.md`
- `invariants.md`
- `scenarios.md`
- optional `entities.md`

## 10. Parser-Vertrag

Der Compiler darf fuer die erste Version nur diese Dinge als normativ
lesen:

- Frontmatter
- die eine kanonische Spezifikationszone

Alles andere gilt als nicht normativer Kommentar.
