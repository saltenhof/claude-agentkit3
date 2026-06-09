# AG3-103 — Remediation R1

**Datum:** 2026-06-08
**Review:** `review-r1.md` (OVERALL CHANGES-REQUESTED — 3x ERROR, 1x WARNING)
**Modus:** doc-only / Konzept-Alignment (FK-Prosa folgt der Code-/FK-34-Realitaet;
reine Code-Fixes nur gespiegelt/geroutet, nicht hier codiert).
**Geaenderte Dateien:** ausschliesslich `stories/AG3-103-*/story.md` (Rewrite) +
diese `remediation-r1.md`. `status.yaml` unveraendert (kein Feld genuin falsch).

## Kern-Diagnose

Die Review traf den zentralen Selbstwiderspruch: die Story vermischte zwei
Bedeutungen von „doc-only". In AK3 ist die Lieferung einer `type: concept`-Story
**die `concept/`-Prosa-Aenderung selbst** (kein `src/`/`tests/`-Diff). Die alte
Fassung verbot dagegen „keine `concept/`-Aenderung in dieser Story" und behauptete
„diese Story BESCHREIBT die Konzeptaenderung, fuehrt sie nicht aus" — damit
blockierten die ACs (die FK-Prosa-Rewrites verlangen) ihre eigene Ausfuehrung.

## Finding -> Resolution

| # | Finding (Severity) | Resolution |
|---|---|---|
| 1 | **Konzept-Vollstaendigkeit (WARNING):** Story ueberzeichnet die §68.2.2-Grundlage — behauptet, das „real emittierte" Payload sei bereits Code/FK-34-Hoheit, obwohl `divergence_hook.py:93-94` noch `score`/`routing` emittiert (erst nach AG3-066 FK-34-foermig). | Umformuliert: autoritativer Anker ist **FK-34 §34.8.4 + AG3-066-Zielschema**, NICHT „aktuell emittierter Code-Payload". §1 stellt jetzt explizit fest, dass Hook heute noch `score`/`routing` traegt (`:93-94`); §2.1.4, AC4a, §5, §6 sind durchgaengig auf „FK-34 + AG3-066-Zielschema" gezogen. |
| 2 | **AC-Schaerfe (ERROR):** ACs verlangen `concept/`-Rewrites, Story sagt aber „keine `concept/`-Aenderung" (Z.5/Z.52/Z.81) — Story blockiert eigene ACs. | Alle „keine `concept/`-Aenderung"-Instruktionen entfernt. Header, §2.1-Doc-only-Klarstellung, §6 stellen klar: `concept/`-Edits sind die Lieferung; verboten ist nur `src/`/`tests/`-Diff. Liste der editierten FK-Dateien explizit. |
| 3 | **Klarheit (ERROR):** Story mischte Story-Spec-Editing vs. AG3-103-Ausfuehrung („beschreibt, fuehrt nicht aus" vs. DoD „Prosa-Aenderung + Commit"). | „Beschreibt aber fuehrt nicht aus"-Framing komplett entfernt. DoD/§6/§2.1 sagen einheitlich: die Story WIRD ausgefuehrt und produziert einen `concept/`-Diff. |
| 4 | **Kontext-Sinnhaftigkeit (ERROR):** §68.2.2 richtet FK-68 nicht an Code-Realitaet aus, sondern an FK-34 + intendiertem AG3-066-Code, lehnt aber harte AG3-066-Abhaengigkeit ab waehrend „aktuelle Code-Hoheit" behauptet wird. | §2.1.4 traegt jetzt einen expliziten **Sequenzierungs-Hinweis**: Code-Migration = AG3-066; FK-68-Prosa = paralleler Nachzug auf dieselbe autoritative FK-34-Quelle, kein Build-Prerequisite. „Aktuelle Code-Hoheit"-Behauptung gestrichen. §2.2 listet die AG3-066-Code-Migration als Out-of-Scope mit Owner (keine harte Kante, da AG3-066 kein `depends_on: AG3-103` traegt). |
| MF1 | Must-Fix: „keine `concept/`-Aenderung" entfernen; nur `src/`/`tests/` verbieten. | Erledigt (siehe Finding 2). |
| MF2 | Must-Fix: §68.2.2-Wording — nicht behaupten, der aktuelle Code-Payload sei FK-34-foermig; Ordering-Note auf AG3-066 ODER „FK-68 prose aligns to FK-34 + AG3-066-Ziel". | Erledigt: beide Massnahmen — „FK-68 zieht auf FK-34 §34.8.4 + AG3-066-Zielschema nach" **plus** Sequenzierungs-Hinweis (siehe Finding 1/4). |
| MF3 | Must-Fix: Permission-TTL als expliziter PO-Klaerbedarf (FK 1800 vs. Code 600), Owner AG3-086/AG3-070; AG3-103 waehlt keinen Wert. | Erledigt: §1, §2.1.2, AC2, §5, §6 markieren den PO-Klaerbedarf; Owner sauber getrennt — **AG3-086** (Code-Wert `DEFAULT_TTL_SECONDS`), **AG3-070** (Config-Pfad `permissions.request_ttl_s`). AG3-103 setzt keinen Wert. |
| MF4 | Must-Fix: AC6 = Konzept-Gates/Frontmatter gruen + kein `src/`/`tests/`-Diff; `concept/`-Diff ist erwartet. | Erledigt: AC6 + DoD umformuliert — `git diff` zeigt nur `concept/`-Aenderungen, der `concept/`-Diff ist erwartet/gewollt. |

## Zusaetzlich: Anker-Korrekturen auf reale file:line

- `requests.py:41` -> **`requests.py:42`** (`DEFAULT_TTL_SECONDS: int = 600` steht real auf Z.42).
- FK-Anker praezisiert/verifiziert: FK-90 §90.2 „Stage-ID = Dateiname" `90_schema_katalog.md:90-94`; FK-93 §93.5a TTL-Zeile `93_defaults_schwellwerte.md:64`; FK-68 §68.2.2 Payload-Row `68_telemetrie_eventing_workflow_metriken.md:362` (Heading `:358`); FK-34 §34.8.4 Feldtabelle `34_llm_bewertungen_adversarial_testing_runtime.md:580-582` (Sektion `:570`); Hook-Emission `divergence_hook.py:93-94`; Routes `routes.py:39-52`; Enum-Werte `pattern.py:50-60`.
- AG3-066-Routing-Belege auf reale Zeilen gesetzt (`stories/AG3-066-review-divergence-quorum/story.md:14`, `:32`, `:65`).

## Selbst-Konsistenz / „kein Fremd-Scope behaupten"

- Es wird NICHT behauptet, AG3-066 liefere die FK-68-Prosa (AG3-066 liefert das
  Code-Schema und **routet** die Prosa an AG3-103). AG3-103 besitzt jetzt die
  §68.2.2-Prosa-Zeile als eigenen Scope (Finding-Schliessung des verwaisten
  Cross-Story-Routings).
- Code-Owner-Stories (AG3-065/068/070/078/081/085/086/091/099) sind als
  Out-of-Scope mit Owner benannt, nicht als von AG3-103 geliefert.
- ARCH-55: kein deutscher Identifier/Key in die FK-Prosa eingefuehrt; die deutschen
  Enum-Werte werden als Code-Verstoss an AG3-078 gespiegelt, nicht in der FK kaschiert.

## Genuine Cross-Story-Voraussetzungen / Hinweise an den Orchestrator

1. **AG3-066 (Implementation) — Code-Schema-Migration `review_divergence`:** kein
   harter Build-Prerequisite zu AG3-103 (beide ziehen unabhaengig auf FK-34
   §34.8.4; AG3-066 deklariert kein `depends_on: AG3-103`). Konsistenz-Hinweis:
   sobald AG3-066 gemerged ist, ist der Code FK-34-foermig und die hier
   nachgezogene FK-68-Prosa deckungsgleich mit dem real emittierten Payload. Bis
   dahin ist die FK-Prosa der autoritativen FK-34-Quelle voraus — das ist der
   gewollte Nachzug-Zustand, kein Widerspruch.
2. **Permission-TTL (600 vs. 1800) — PO-Entscheidung offen:** Bevor AG3-086
   (Code-Wert) bzw. AG3-070 (Config-Pfad) den TTL final setzen, braucht es eine
   PO-Klaerung, welcher Wert gilt. AG3-103 dokumentiert die Drift, entscheidet sie
   nicht (SEVERITY: aktiver Handlungsauftrag, kein still liegengelassener Warning).
3. **status.yaml `depends_on: [AG3-070, AG3-085]`** wurde NICHT geaendert (Review
   flaggte es nicht; ausserhalb des engen Remediation-Mandats). Hinweis zur
   Pruefung durch den Orchestrator: fuer eine reine doc-only-Nachzug-Story, die FK
   an die bestehende Realitaet angleicht, sind harte `depends_on`-Kanten zu
   Code-Stories fachlich fragwuerdig — der Body (§2.2) und die
   `scope-extension-note.md` argumentieren explizit gegen Build-Prerequisites. Ggf.
   in der Execution-Planung pruefen; hier bewusst nicht eigenmaechtig veraendert.
