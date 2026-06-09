# AG3-057 — Remediation r1 (hostile Codex review-r1.md)

Scope of this remediation: `story.md` + `status.yaml` only. No production code,
tests, or concept files touched. Every code anchor below was re-verified against
the real tree at remediation time and corrected to `file:line`.

## Must-Fix ERRORs

### MF1 — Non-code Rueckgabe/Wiring auf `execution_route=None` (review §1, §Must-Fix 1)
**Finding:** Non-code Storys als `EXECUTION` modelliert, kollidiert mit dem v3-Modell
`execution_route=None` (`types.py:80-82` `allowed_modes=(None,)`; `models.py:316`; FK-24 §24.3.2).
**Resolution:** `determine_mode` gibt jetzt `StoryMode | None` zurueck; Vorbedingung
`story_type not in {implementation, bugfix}` -> **`None`** (nicht EXECUTION). AC6 auf
„concept/research -> `None`, keine Trigger-Auswertung" umgeschrieben. Build-Pfade setzen
`execution_route=None` fuer concept/research, konsistent mit `allowed_modes=(None,)`.
Quell-Konzept FK-24 §24.3.2 als autoritativer Anker ergaenzt. (Resolved in-story.)

### MF2 — Bugfix-Exploration real in Workflow/Profil/Registry (review §2 AC7, §4, §Must-Fix 2)
**Finding:** AC7 „routing_rules routet unveraendert korrekt" ist fuer Bugfix-Exploration
real falsch. Gegenbeleg: `definitions.py:107-124` (Bugfix-Workflow ohne exploration),
`routing_rules.py:23-33` (entfernt exploration nur, fuegt sie nie hinzu),
`composition_root.py:1614-1615` (Registry registriert nur Workflow-Phasen), und drei
Tests, die „Bugfix hat nie exploration" zementieren (`test_definitions.py:77-83`,
`test_pipeline_runner.py:447-449`, `test_pipeline_handler_registry.py:89-98`).
**Resolution:** Neuer In-Scope-Punkt 5: Bugfix-Workflow um `exploration`-Phase +
`setup->exploration`/`exploration->implementation`-Transitionen erweitern (gespiegelt am
Implementation-Workflow `definitions.py:88-104`), `StoryTypeProfile[BUGFIX].phases` um
`"exploration"` ergaenzen, Handler-Registry zieht den Handler dann automatisch. Die drei
Tests sind explizit als zwingendes Test-Update Teil der Lieferung. Neues AC7b verprobt
gueltigen (EXPLORATION -> setup/exploration/impl/closure) UND ungueltigen Pfad
(EXECUTION -> setup/impl/closure). FK-23 §23.1 als autoritativer Geltungsbereich-Anker
ergaenzt. (Resolved in-story — gleicher AG3-057-Cut: das 4-Trigger-Modell macht
Bugfix-Exploration erst real; siehe Cross-Story-Hinweis unten, warum dies NICHT zu einer
anderen Story gehoert.)

### MF3 — Autoritative Feld-Owner + `concept_refs`/`concept_paths`-Mapping (review §3, §Must-Fix 3)
**Finding:** `change_impact`/`concept_quality` existieren schon in `Story`
(`story_model.py:194-195`), `concept_refs` in `StorySpecification` (`story_model.py:143`,
DB `story_repository.py:424`). Die fruehere Story forderte zusaetzlich `concept_paths` und
behandelte `change_impact`/`concept_quality` als komplett neue `| None`-Felder -> Risiko
zweiter Wahrheit.
**Resolution:** In-Scope 1 trennt jetzt klar „neu" vs. „wiederverwendet":
`change_impact: ChangeImpact | None` / `concept_quality: ConceptQuality | None` werden aus
`Story.*` **projiziert** (kein neues Persistenzfeld); `concept_paths` ist explizit die
Laufzeit-Projektion der autoritativen `StorySpecification.concept_refs` (Persistenz-Owner
bleibt `concept_refs`, kein Rename, keine zweite Spalte). `new_structures` ist ein neuer,
sauber persistierter Owner an `Story`; `vectordb_conflict` wird NUR konsumiert. AC8
entsprechend praezisiert. (Resolved in-story.)

### MF4 — Fehlende Pflichtfelder vollstaendig fail-closed testen, bes. `new_structures` (review §1, §Must-Fix 4)
**Finding:** „Pflichtfeld fehlt -> Exploration" (FK-23 §23.2.1) war nicht je Feld in ACs
operationalisiert; keine impliziten Bool-Defaults bei Pflichtfeldern.
**Resolution:** AC4 zerlegt in fuenf benannte fail-closed-Tests: `change_impact is None`,
`concept_quality is None`, leere `concept_paths`, fehlendes `new_structures` (deterministisch
`False`, belegt — kein weggeblendeter echter Wert), und Default/Unsicherheits-Pfad. In-Scope 1
deklariert die `new_structures`-Default-Semantik explizit als fail-closed. (Resolved in-story.)

### MF5 — `project_root`-Signatur/Fallback widerspruchsfrei (review §2 WARNING, §Must-Fix 5)
**Finding:** Signatur verlangte `project_root: Path`, AC forderte „fehlendes `project_root`"
+ CWD-Fallback — widerspruechlich.
**Resolution:** Signatur auf `project_root: Path | None = None` geaendert (In-Scope 2);
AC5 spricht jetzt von `project_root=None -> CWD-Fallback + WARNING`. Konsistent mit FK-22
§22.8.1 Bug-Fix-Hinweis. (Resolved in-story.)

## WARNINGs

### W1 — `project_root` Signatur/Fallback
Identisch mit MF5 (im Review als WARNING in §2 gefuehrt). Resolved wie oben.

## Korrigierte/verifizierte Code-Anker (review §4 „Kontext-Sinnhaftigkeit")
Alle vom Review als korrekt bestaetigten Anker beibehalten und gegen den realen Tree
nachgeprueft: `context_builder.py:155/168/227/250`, `models.py:316` (`execution_route`),
`models.py:393-400` (Allowed-Mode-Validator; frueher ungenau als `:395-400` notiert — auf
den realen Validator-Block korrigiert). Neu/praeziser verankert: `routing_rules.py:23-33`
und `:38-42`, `definitions.py:107-124` (Bugfix) und `:88-104` (Implementation als Vorlage),
`composition_root.py:1614-1615`, `story_model.py:97-105/109-114/143/194-195`,
`story_repository.py:424`, `context_builder.py:70-109` (`_resolve_authoritative_mode`).
Die im Review als falsch markierte Aussage „routing_rules routet unveraendert korrekt"
ist entfernt und durch den belegten Gegenstand (In-Scope 5 / AC7b) ersetzt.

## Konzept-Drift-Befund (ARCH-55 / typisiert statt Strings)
Der FK-22 §22.8.1-Referenztext vergleicht Trigger 2 gegen den Stringliteral
`"Architecture Impact"`. Das reale `ChangeImpact`-Enum (`story_model.py:97-105`) hat diesen
Wert NICHT (`"Local"`/`"Component"`/`"Cross-Component"`). Die Story bindet Trigger 2 jetzt
typisiert an `ChangeImpact.CROSS_COMPONENT` und verbietet explizit einen Stringvergleich
gegen einen nicht existierenden Enum-Wert. Die FK-22-↔-Code-Stringdivergenz ist als
doc-only-Nachzug zu melden (siehe Cross-Story-Voraussetzungen).

## status.yaml
`depends_on` um **AG3-054** ergaenzt: In-Scope 5 modifiziert die Bugfix-Workflow-Definition,
die Profil-`phases` und die von `build_pipeline_handler_registry` aufgeloeste Phasenmenge —
allesamt von AG3-054 (`completed`) etabliert. Damit ist AG3-054 eine echte Vorbedingung, die
zuvor fehlte. Keine weiteren Felder geaendert (`phase: review_pending` bleibt korrekt fuer
den laufenden Review-Zyklus).

## Genuine cross-story Voraussetzungen / Folge-Einheiten
1. **AG3-068 (Welle 2) — Produzent `vectordb_conflict`.** AG3-057 konsumiert das Flag nur
   (fail-closed `False`). Autoritativ bestaetigt durch `_STORY_INDEX.md` Dedup-Notiz: „Der
   `vectordb_conflict`-Konsument bleibt bei AG3-057, der Produzent ist AG3-068." Kein
   Scope-Transfer noetig; AG3-057 bleibt lauffaehig ohne AG3-068 (Default absent).
2. **AG3-077 — ARE-Bundle-Load (FK-22 §22.4b).** Bleibt Out-of-Scope mit klarem Owner; war
   schon korrekt verlagert.
3. **doc-only Konzept-Nachzug — FK-22 §22.8.1 Stringdrift.** Der FK-22-Referenztext nennt
   `change_impact == "Architecture Impact"`, das es im Code-Enum nicht gibt. Dies ist ein
   FK-Prosa-vs-Code-Drift (Code ist autoritativ via typisiertem Enum). Gehoert in den
   doc-only Konzept-Nachzug (`_STORY_INDEX.md` Welle 10, AG3-101..104 Muster) bzw. an die
   FK-22-zustaendige doc-only-Einheit — **nicht** in den AG3-057-Code-Cut. AG3-057 bindet
   korrekt an `ChangeImpact.CROSS_COMPONENT` und meldet den Drift, mehr nicht.

Hinweis zur Cut-Treue MF2: Die Bugfix-Workflow-/Profil-/Registry-Erweiterung ist bewusst
**innerhalb** AG3-057 gehalten und NICHT an eine andere Story geroutet, weil der
`_STORY_INDEX.md` keine Story traegt, die „Bugfix-Workflow erhaelt Exploration-Phase"
liefert (AG3-058 ist Terminalitaet, haengt seinerseits von AG3-057 ab). Die
Bugfix-Exploration ist die unmittelbare, untrennbare Konsequenz davon, dass das
4-Trigger-Modell (FK-23 §23.1) Bugfix einschliesst — sie gehoert damit fachlich in genau
diesen Cut.
