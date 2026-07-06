# GAP-Analyse-Schema fuer Bounded Contexts

> **Single Source of Truth fuer das Format der Datei `<bc-id>-gap-analyse.md`.**
> Jeder Sub-Agent, der eine BC-spezifische GAP-Analyse schreibt, **muss
> dieses Schema strikt einhalten**. Abweichungen sind nicht erlaubt — der
> Stories-Root soll ein konsistentes, vergleichbares Bild ueber alle BCs
> liefern.

## 1. Vorgabe

- **Ablageort:** `stories/<bc-id>-gap-analyse.md` (Root des Stories-
  Verzeichnisses, **nicht** in einem AG3-Unterordner)
- **Dateiname:** exakt `<bc-id>` aus
  `concept/technical-design/_meta/domain-registry.yaml` plus
  `-gap-analyse.md` (Beispiel:
  `verify-system-gap-analyse.md`)
- **Sprache:** Deutsch
- **Encoding:** UTF-8, LF
- **Kein Emoji**, keine kreativen Section-Headings ausser den vorgegebenen.

## 2. Pflichtstruktur

Die Markdown enthaelt **genau** die nachfolgenden Abschnitte in dieser
Reihenfolge. Abschnitts-Ueberschriften wortgleich uebernehmen.

````markdown
# <BC-ID> — GAP-Analyse

> Generiert von einem dedizierten Sonnet-Sub-Agent (Stand <YYYY-MM-DD>).

## Header

| Feld | Wert |
|---|---|
| BC-ID | `<bc-id>` |
| Display-Name | `<aus domain-registry.yaml>` |
| Analyse-Datum | `<YYYY-MM-DD>` |
| Konzept-Quellen (autoritativ) | `<FK-XX, FK-YY, DK-ZZ, formal.<ctx>.<...>>` |
| Codebase-Hauptpfade | `<src/agentkit/<paket1>/, src/agentkit/<paket2>/>` |

## 1. Executive Summary

<2–4 Saetze Gesamtbild des BC-Stands. Konkret: Wie weit ist die
Implementation gegenueber dem Konzept? Welche Hauptluecken pragen das
Bild?>

| Kategorie | Anzahl |
|---|---|
| A — Nicht umgesetzt | N |
| B — Teilweise umgesetzt | M |
| C — Drift / Fehler | K |

## 2. Konzept-Soll (Kurzfassung)

<Stichpunkte der konzeptionellen Anforderungen, jede mit autoritativer
Doc-Referenz. Ein Punkt pro Soll-Anforderung. Keine Paraphrase ohne
Doc-Quelle. Reihenfolge nach inhaltlicher Wichtigkeit (nicht nach
Kapitelreihenfolge).>

- **<Anforderung>** — `<doc>.md §<kap>`
- **<Anforderung>** — `<doc>.md §<kap>`

## 3. Code-Stand (Ist-Bild)

<Stichpunkte: vorhandene Pakete, Module, Klassen, wesentliche Funktionen
die diesen BC abdecken. Pfade vollstaendig (von repo-root). Bei Code-
Stellen: `:<Klasse>` oder `:<Klasse>.<methode>` anfuegen, falls relevant.>

- `src/agentkit/<paket>/<modul>.py:<Klasse>` — <was leistet das>
- `src/agentkit/<paket>/<modul>.py:<Klasse>.<methode>` — <was leistet das>

## 4. GAP-Analyse

> **Wichtig:** Jede Zeile in einer der drei Tabellen muss mindestens
> eine konkrete Doc-Referenz tragen. Code-Referenzen sind in den
> Tabellen B und C Pflicht, in Tabelle A optional (weil dort gerade
> kein Code existiert).

### 4.1 A — Nicht umgesetzt

| # | Thema | Konzept-Referenz | Anmerkung |
|---|---|---|---|
| A1 | <kurze Sache> | `<doc>.md §<kap>` | <Begruendung; ggf. Story-ID falls bereits geplant> |
| A2 | ... | ... | ... |

### 4.2 B — Teilweise umgesetzt

| # | Thema | Code-Referenz | Konzept-Referenz | Was fehlt |
|---|---|---|---|---|
| B1 | <Thema> | `src/agentkit/.../modul.py:Klasse.methode` | `<doc>.md §<kap>` | <konkret welche Teilanforderung nicht erfuellt ist> |

### 4.3 C — Drift / Fehler

> Hier landen Implementierungen, die etwas tun, aber nicht das, was im
> Konzept steht, **oder** offensichtlich fehlerhaft sind (Bug,
> Verletzung einer Invariante, falsche Trust-Boundary, etc.).

| # | Thema | Code-Referenz | Konzept-Referenz | Drift / Fehler |
|---|---|---|---|---|
| C1 | <Thema> | `src/agentkit/.../...` | `<doc>.md §<kap>` | <was weicht ab; warum problematisch> |

## 5. Ableitungen / Empfehlungen

> **Keine Stories anlegen.** Diese Sektion ist eine priorisierte
> Stichpunkt-Liste fuer den nachgelagerten Backlog-Schnitt durch den
> User. Pro Eintrag: Was sollte als naechstes adressiert werden und
> warum (Risiko, Bloecker fuer andere BCs, Konzept-Compliance).

1. <Empfehlung mit Begruendung>
2. ...

## 6. Suchstrategie & Quellen

> Volle Transparenz, was der Agent gelesen und wie er gesucht hat.

- **Vollstaendig gelesen:**
  - `concept/technical-design/<doc>.md`
  - `concept/domain-design/<doc>.md`
  - `concept/formal-spec/<ctx>/<...>.md`
- **Punktuell via `mcp__agentkit3-concepts__concept_search`:**
  - Query `<...>`: <warum gesucht>
- **Code-Scan (Glob/Grep):**
  - Pattern `<...>`: <warum>

````

## 3. Erlaubte Variationen

- Tabelle A, B oder C **darf entfallen**, wenn der BC darin keinen
  Befund hat. In diesem Fall stattdessen die Section mit dem Satz
  „Keine Befunde in dieser Kategorie." kennzeichnen — **die Section
  selbst aber behalten**.
- Die Anzahl der Eintraege pro Tabelle ist nicht limitiert.

## 4. Verbotenes

- Keine zusaetzlichen Top-Level-Sections jenseits von 1–6.
- Keine fliessenden Prosa-Absaetze in den GAP-Tabellen — alles strikt
  tabellarisch.
- Keine erfundenen Konzept-Referenzen. Wenn unklar: `concept_search`
  nutzen oder „nicht in Konzept gefunden" eintragen.
- Keine erfundenen Code-Pfade. Vor jeder Code-Referenz Read/Grep
  bestaetigen.
- Keine neuen Stories anlegen, keine `status.yaml` aendern, kein Commit
  in `stories/AG3-*`. Output ist genau **eine** Datei in
  `stories/<bc-id>-gap-analyse.md`.

## 5. Wichtige Doc-Quellen pro BC

Quelle der Wahrheit ist `concept/technical-design/_meta/domain-registry.yaml`.
Dort steht je BC eine Liste `contract_docs` (autoritative Vertraege)
und optional `member_docs` (Innenleben). Beide sind **vollstaendig** zu
lesen. Plus:

- `concept/domain-design/<dk-doc>.md` falls eine DK-Referenz im
  Eintrag steht (z. B. `DK-04`).
- `concept/formal-spec/<context>/<...>.md` falls die Inhalte eine
  formale Spec haben (Hinweis: BC-Namen und formal-spec-Ordnernamen
  korrelieren meist, sind aber nicht identisch — Agent muss
  selbststaendig matchen).
- `concept/_meta/bc-cut-decisions.md` fuer BC-Schnitt-Entscheidungen,
  die die eigene Domain betreffen.

Nachbar-BCs nur **punktuell** lesen (Doc-Read auf konkrete Frage oder
`concept_search`-Query) — kein Vollscan fremder BCs.
