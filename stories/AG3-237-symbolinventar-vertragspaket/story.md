# AG3-237 — Das Symbolinventar des Vertragspakets und der zwei gemischten Pakete

- **Typ:** concept
- **Groesse:** L
- **Abhaengigkeiten:** `depends_on: [AG3-208]` — dort ist die Regel entschieden
- **Blockiert:** AG3-209
- **Herkunft:** AG3-208 Runde 3, 2026-08-07, nach dem zweiten AC-10-Review

## Anlass

AG3-208 hat den Distributionsschnitt zielbildhaft gesetzt. Zwei unabhaengige
Reviewrunden haben denselben Fehler an vier Stellen gefunden, und er hat eine
gemeinsame Wurzel:

> **Bestehende Module wurden im Ganzen einer Distribution zugewiesen, obwohl
> sie Belange mischen.**

Dreimal derselbe Fall: `backend/governance/` pauschal Edge, obwohl FK-01
`PolicyEngine` und `IntegrityGate` ausdruecklich als Kern-Logik fuehrt.
`control_plane.models` vollstaendig Wire, obwohl es Edge **und** Kern
importiert, HTTP-Antworten baut und ein Log schreibt. `config/models.py` als
Wire, obwohl es `pathlib` importiert, das die Wire-Regel selbst verbietet.

AG3-208 hat daraus die **Regel** gemacht — `symbol_boundary_is_the_rule`,
Praefixzuweisung nur noch bei gemessener Mischungsfreiheit — und die vier
Bereiche in `pending_symbol_inventory` gestellt. Diese Story fuellt es.

**Der Satz, der die Story traegt:** Das Vertragspaket ist kein Umetikettieren
bestehender Module. Es ist neuer Code, in den Symbole **wandern**.

## Umfang, gemessen

AST-Messung aus AG3-208 Runde 3, symbolgenau, liegt als `measured_evidence` in
`concept/formal-spec/architecture-conformance/entities.md`:

| Bereich | Befund |
|---|---|
| `backend/governance/` | 13 Submodule. Edge-only: `runner` (3 Symbole), `guard_evaluation.evaluate_pre_tool_use`, `Operation`, `default_hook_definitions`. Kern-only: `integrity_gate/`, `principal_capabilities/` (4 Module), `setup_preflight_gate/`, `locks`, `guard_system.records`, `guard_system.protected_paths`, `protocols.ViolationType`. Beidseitig: `HookEvent`, `HookDefinition`, `GuardVerdict`, `HookRegistrationError` |
| `backend/installer/` | 33 kernseitig importierte Symbole (`ProjectRegistration*`, `SkillBinding*`, `GovernanceHook*`, `InstallerMutationCoordinator`, `story_dir`, `qa_story_dir`, `prompt_bundle_*`) gegen 4 Edge-only |
| `control_plane/models.py` | 63 Klassen, 66 Importsymbole: 21 nur Kern, 7 nur Edge, 38 beidseitig. Importiert `story_creation.reconciliation_evidence` (Edge) und `telemetry.events` (Kern), dazu `logging`, `json`, `HTTPStatus` |
| `config/{models,defaults,worker_health}` | `models.py` importiert `pathlib`; `defaults.py:37-65` traegt die Kern-Listener-Ports |

**Rund 150 Symbole, jedes mit eigener Begruendung.**

## Warum das eine eigene Story ist

Das ist nicht die Prosa zum Zielbild — das **ist** die inhaltliche
Spezifikation des Vertragspakets und zweier geteilter Pakete. Sie nebenher in
derselben Runde zu erfinden, in der normative Grundsatzfragen geklaert werden,
waere genau der Fehler, der die drei Reviewrunden erzeugt hat: eine Zuordnung
ohne Messung, die in Runde 4 wieder aufgemacht wird.

**Es ist auch keine mechanische Arbeit.** Jedes beidseitig importierte Symbol
ist eine Entscheidung: Wandert es ins Vertragspaket, wird es dupliziert, oder
ist der beidseitige Import selbst der Fehler. 38 solche Symbole allein in
`control_plane.models`.

## Der Zustand, den diese Story herstellt

`pending_symbol_inventory` ist **leer**. Damit greift die Vorbedingung von
`distribution_membership_is_total_and_disjoint`, und AG3-209 kann den Schnitt
ausfuehren, ohne zu raten.

## Ausweitung auf alle 44 Pakete — Korrektur 2026-08-07

Diese Story war zuerst auf die vier Pending-Bereiche geschnitten. Das dritte
AC-10-Review hat gezeigt, dass dieser Schnitt eine **Fluchttuer** war:

- `cli` gilt als „vollstaendig Edge" (`FK-10:1183`) — **zehn Zeilen** nachdem
  dieselbe Datei es als geteilt mit vier Kern-Kommandopfaden erklaert
  (`FK-10:1173`), was der Dispatcher bestaetigt (`cli/main.py:203-227`).
- `control_plane` gilt als „vollstaendig Kern", obwohl `control_plane.models`
  gerade auf Pending steht.
- `failure_corpus`, `bootstrap`, `implementation` und `telemetry` gelten als
  vollstaendig Kern und tragen Edge-Durchgriffe
  (`failure_corpus/writer_client.py:20`, `failure_corpus/cli.py:212`).

Vier bekannte Mischungen ehrlich auf Pending zu stellen, waehrend andere
bekannte Mischungen weiterhin als rein gelten, ist derselbe Fehler in kleinerem
Massstab. **Der Umfang ist deshalb alle 44 unmittelbaren Backend-Subpakete**,
nicht nur die vier.

## Was als Symbol zaehlt — Definition vor Messung

Die Messung aus AG3-208 Runde 3 mischt Einheiten: 13 Module, 33 importierte
Symbole, 63 Klassen, fuer `config` gar keine Zahl. Bevor gemessen wird, ist
festzulegen und im Konzept zu verankern:

- Was die **Zaehleinheit** ist (Modul, oeffentliches Top-Level-Symbol,
  Importkante) und warum.
- Wie **Mischungsfreiheit** bewiesen wird — die Bedingung, unter der
  `symbol_boundary_is_the_rule` eine Praefixzuweisung ueberhaupt zulaesst.
- Dass diese Bedingung fuer **jedes** praefixzugewiesene Paket erfuellt ist,
  nicht nur angenommen.

Die Zahl „rund 150" oben ist damit ein **Startwert aus einer Vormessung**, kein
Sollwert. Die belastbare Zahl entsteht erst nach der Definition.

## Scope

### In Scope

- Die Zaehleinheit und das Kriterium fuer Mischungsfreiheit, im Konzept
  verankert.
- Fuer **alle 44** Backend-Subpakete: entweder eine praefixweite Zuordnung mit
  **gemessenem** Nachweis der Mischungsfreiheit, oder ein Symbolschnitt.
- Fuer jedes gemischte Paket die Zuordnung je Symbol: Edge, Kern, Wire — oder
  die begruendete Feststellung, dass der beidseitige Import selbst der Fehler
  ist und in AG3-209 aufgeloest wird.
- Die Zielmodule des Vertragspakets: welche **neuen** Module entstehen und
  welche Symbole hineinwandern. Nicht: welche bestehenden Module umetikettiert
  werden.
- Die Arithmetik ueber die 44 wird neu gerechnet und ist danach eine
  **Klassifikation**, keine blosse Mengenaddition.

### Out of Scope

- **Jede Codeaenderung.** Diese Story spezifiziert; AG3-209 fuehrt aus.
- Der Bau des Packaging-Gates. Ebenfalls AG3-209.
- Die elf verwaisten Kommandopfade. Owner PO.
- Die Textnachzuege (AG3-236, FK-91-Befehlszeilen).

## Akzeptanzkriterien

1. **Zaehleinheit und Mischungsfreiheits-Kriterium sind im Konzept verankert**
   und binden `symbol_boundary_is_the_rule`.
2. **`pending_symbol_inventory` ist leer**, und **jedes** der 44 Subpakete
   traegt eine Zuordnung, die `symbol_boundary_is_the_rule` erfuellt.
3. **Jede praefixweite Zuordnung traegt `measured_evidence`.** Eine
   Praefixzuweisung ohne Messung ist ein Verstoss gegen AC 1, kein Sonderfall.
   Ausdruecklich einzuschliessen sind die vom Review benannten Gegenbeispiele
   `cli`, `control_plane`, `failure_corpus`, `bootstrap`, `implementation`,
   `telemetry`.
4. **Kein bestehendes Modul wird pauschal Wire.** Die Zielmodule des
   Vertragspakets sind benannt, und fuer jedes steht, welche Symbole einwandern.
5. **Die Wire-Regel gilt fuer den spezifizierten Inhalt**: kein `pathlib`, kein
   I/O, kein Import aus Edge oder Kern, ausschliesslich `/v1`-Vokabular.
   Nachgewiesen gegen die tatsaechlichen Symbole, nicht gegen die Modulnamen.
6. **Die Arithmetik ueber die 44 Backend-Subpakete geht auf**, ist nachgerechnet
   und jede Klasse ist durch AC 3 gedeckt.
7. Alle **sechs** bindenden deterministischen Konzept-Gates gruen (AGENTS.md;
   W2/W3 sind seit der PO-Entscheidung 2026-08-02 kein Abnahmekriterium und
   werden nie als "gruen" mitgezaehlt); Referenzintegritaet ohne
   neue Baseline-Eintraege.

**Der Rueckfallbeweis gehoert NICHT hierher.** Ein geprueftes `NOT_RUN` setzt
das Packaging-Gate voraus, das AG3-209 baut — und AG3-209 haengt an dieser
Story. Diese Story stellt nur sicher, dass die Vorbedingung
`pending_symbol_inventory is empty` in der Gate-Checkliste **referenziert** ist,
damit AG3-209 sie nicht uebersehen kann. Der Revert-Red-Beweis ist Abnahme-
kriterium von AG3-209.

## Vorgefundene Widersprueche aus AG3-208 — Eingangsliste

**Herkunft und Status.** AG3-208 ist am 2026-08-07 per PO-Entscheid
geschlossen worden. Die hier aufgezaehlten Stellen sind **bewusst nicht
korrigiert**: sie liegen alle dort, wo AG3-237 beim Messen ohnehin
schreibt, und sie vorher zu glaetten hiesse, den Schnitt an zwei Stellen
nacheinander zu machen — genau das verbietet `CLAUDE.md`
§KEINE KOMPATIBILITAETSSCHICHTEN („der Schnitt wird an einer Stelle
gemacht, nicht an zweien nacheinander"). Nach §ZERO DEBT bleibt damit nur
der zweite zulaessige Weg: die Luecke **unveraendert sichtbar** lassen und
entscheidungsreif melden. Das ist diese Liste.

**Verbindlich fuer AG3-237:** Jede der folgenden Stellen wird bei der
Messung **ersetzt**, nicht ergaenzt. Keine darf nach Abschluss dieser
Story in ihrer heutigen Form stehen bleiben.

**Warum die Liste vollstaendig sein muss.** Der Korpus fuehrt dieselben
Module heute in drei unterschiedlichen Gewissheitsgraden — „offen",
„vorlaeufig" und „Spezifikation des Schnitts". Wer misst, muss wissen,
welche Aussage er ersetzt und welche er bestaetigt; ohne diese Liste
muesste AG3-237 selbst waehlen und wuerde damit wieder raten.

### A — Zuordnungen, die im maschinenlesbaren Vertrag stehen

| # | Locator | Was dort steht | Warum es falsch ist |
|---|---|---|---|
| A1 | `concept/formal-spec/architecture-conformance/entities.md:1653-1659` (`distributions[wire].module_prefixes`) | Sechs Backend-Praefixe sind der Wire-Distribution zugewiesen: `agentkit.backend.control_plane.third_party_models`, `agentkit.backend.core_types.operating_mode`, `agentkit.backend.core_types.verify_evidence`, `agentkit.backend.story_exit.http_models`, `agentkit.backend.story_reset.http_models`, `agentkit.backend.story_split.http_models` | Das ist eine Klassifikation von Backend-Inhalt, obwohl `distribution_classification_status: open` daneben steht. Der vorangestellte `# VORLAEUFIG`-Kommentar (`:1650-1652`) aendert die **operative** Bedeutung des Feldes nicht: `module_prefixes` ist die Zuordnung, die ein Gate liest — ein Kommentar wird nicht mitgelesen. Keiner der sechs Praefixe ist symbolgenau vermessen |
| A2 | `entities.md:1550-1558` (Kommentar zu `distribution_prefix_resolution`) | Der Aufloesungsmechanismus wird an drei Beispielen erklaert: `agentkit.backend -> core`, `agentkit.backend.governance -> edge`, `agentkit.backend.config.models -> wire` | Alle drei Beispiele sind **zurueckgezogene** Zuordnungen. `agentkit.backend -> core` war die entfernte Auffangregel, `governance` und `config.models` stehen als gemessen gemischt im `pending_symbol_inventory`. Ein Beispiel ist keine Norm, aber es ist die einzige Stelle, an der ein Leser den Mechanismus versteht — und es lehrt die falsche Zuordnung |
| A3 | `entities.md:1792-1794` (`symbol_boundary.backend_config_models`) | `split_required: false` fuer `agentkit.backend.config.models` | Direkter Widerspruch zu `concept/technical-design/10_runtime_deployment_speicher.md:1274-1278`, das fuer dasselbe Modul sagt, die Grenze verlaufe **innerhalb** und es „muss deshalb geteilt werden". Genau eine der beiden Aussagen kann stimmen; welche, entscheidet die Messung |

### B — Zuordnungen in der Prosa

| # | Locator | Was dort steht | Warum es falsch ist |
|---|---|---|---|
| B1 | `concept/technical-design/30_hook_adapter_guard_enforcement.md:520-527` | „Distributionszuordnung dieser Module (**normativ**) … Ihr Auslieferungsbesitzer ist die Edge-Distribution", geltend fuer **alle** `agentkit.backend.governance.*`- und `agentkit.backend.telemetry.hooks`-Locatoren des Kapitels | `governance/` ist gemessen gemischt: `integrity_gate/`, `principal_capabilities/`, `setup_preflight_gate/`, `locks` und `guard_system.records` werden ausschliesslich kernseitig importiert, und FK-01 §1.1a fuehrt `PolicyEngine`, `IntegrityGate` und Governance-Adjudication ausdruecklich als Kern-Logik. Die Aussage traegt das Wort „normativ" und ist damit die staerkste verbliebene Fehlzuweisung |
| B2 | `concept/technical-design/01_systemkontext_und_architekturprinzipien.md:623` (§1.4.3 Zonentabelle) | „Zone 1 — Plattform: Hooks und Guard-Engine \| Entwicklerrechner \| `agentkit-project-edge`" | Dieselbe Fehlzuweisung wie B1, in einem anderen Kapitel. Die Zone-1-Aussage ueber den **Ausfuehrungsort** ist richtig; die Spalte „Distribution" behauptet zusaetzlich eine Paketzugehoerigkeit von `governance/`, die nicht gemessen ist |
| B3 | `01_systemkontext_und_architekturprinzipien.md:250-252` (§1.2.2 Komponentenzuordnung) und `PROJECT_STRUCTURE.md:149-150` (Distributionstabelle, Spalte „Inhalt") | Edge enthaelt „Hook-Wrapper, **Guard-Engine**, Project-Edge-Client, **Bediener-CLI**, **Installer**"; Kern enthaelt „Pipeline, QA-Subflow, **Governance-Adjudication**, … " | Vier Inhaltszusagen ueber Pakete, die als gemischt oder offen gefuehrt werden: `governance/`, `cli/`, `installer/`. Die Zeile liest sich als Paketliste, nicht als Prozessliste |
| B4 | `10_runtime_deployment_speicher.md:1208` (Tabelle B, Spalte „Beleg") | „Der uebrige `code_backend/` **bleibt Kern**" — in derselben Zeile, deren Befundspalte „restliches `code_backend/` nicht gemessen" sagt | Zuweisung und Nichtmessung stehen nebeneinander in einer Zeile. Die Befundspalte wurde nachgezogen, die Belegspalte nicht |
| B5 | `10_runtime_deployment_speicher.md:1218-1224` (Absatz „Gegenkanten Kern→Edge") | Die 46 Gegenkanten „entstehen ausnahmslos in Modulen, die nach dieser Matrix **ohnehin zum Edge gehoeren**" | Beruft sich auf die zurueckgezogene Matrix. Die genannten Module (`governance/runner.py`, `cli/auth_commands.py`, `installer/*`) liegen alle in Paketen, deren Zuordnung offen ist — das Argument setzt genau das voraus, was AG3-237 erst misst |
| B6 | `10_runtime_deployment_speicher.md:1274-1281` (Abschnitt D) | Die Symbolliste gilt „als **Spezifikation des Schnitts**: AG3-209 teilt das Modul so, dass danach wieder die Praefixregel allein genuegt" | Benennt AG3-209 als Adressaten und die Liste als Spezifikation, obwohl AG3-237 den Inhalt des Vertragspakets erst bestimmt. Dritte Gewissheitsstufe neben „offen" und „vorlaeufig" — dieselben Module, drei verschiedene Verbindlichkeiten |
| B7 | `10_runtime_deployment_speicher.md:1249-1263` (Abschnitt D, Tabelle „Aufgenommen wird") | Sieben Wire-Inhalte werden namentlich aufgezaehlt, darunter „aus `backend/control_plane/models` **nur die 38 beidseitig genutzten Klassen**" und das Konfigurationsschema | Die Zahl 38 stammt aus einer Import-Zaehlung, nicht aus einer Symbolentscheidung; welche 38 es sind, steht nirgends. Als Inhaltsvorgabe fuer das Vertragspaket ist sie nicht umsetzbar |

### C — Ausserhalb der AG3-237-Messung: gehoert zurueck an den PO

| # | Locator | Was dort steht | Warum es hierher gemeldet wird |
|---|---|---|---|
| C1 | `concept/formal-spec/architecture-conformance/invariants.md:263-269` und `entities.md:1816-1819` | Beide sagen, die beidseitige Deklaration von `agentkit-wire` sei „**mandated by** `no_inter_distribution_package_dependency`" bzw. „VORGESCHRIEBEN … `no_inter_distribution_package_dependency` verlangt die Kanten" | **Diese Stelle beruehrt die Klassifikation nicht.** `no_inter_distribution_package_dependency` *erlaubt* die Kanten Edge→Wire und Kern→Wire lediglich (`invariants.md:237-249`); **vorgeschrieben** werden sie durch die Runtime-Sollmengen zusammen mit `declared_dependencies_match_normative_sets` (`:250-258`). Der Decision Record §9.6 traegt die Korrektur bereits, die Formal-Spec zweimal nicht. Das ist eine Wortlautkorrektur im Dependency-Vertrag, unabhaengig davon, wie die 44 Pakete zugeordnet werden — sie faellt **nicht** in den Auftrag dieser Story. **ERLEDIGT am 2026-08-07 in AG3-208** — das Zitat oben dokumentiert den Vorher-Zustand und bleibt als Beleg stehen |

### Abgrenzung dieser Liste

Die Liste umfasst **keine** Stellen, die nach dem Schnitt weiter gelten:
Artefaktnamen und Importwurzeln, die Maschinen- und Zustandsgrenze, der
Entry-Point- und CLI-Vertrag, die Dependency-Regeln und der
Gate-Mechanismus sind in AG3-208 entschieden und bleiben unberuehrt. Was
hier steht, sind ausschliesslich Aussagen ueber die **Zugehoerigkeit von
Backend-Code**.

## Definition of Done

- AC 1–7 erfuellt, jedes mit benanntem Beleg.
- **Jeder Eintrag der Eingangsliste (A1–A3, B1–B7) ist ersetzt**, nicht
  ergaenzt; je Eintrag ist der neue Wortlaut mit Locator belegt. C1 ist
  **in AG3-208 behoben** (2026-08-07) und nicht Gegenstand dieser Story.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` §ZERO DEBT RULE — die Zuordnung wird hergestellt, nicht behauptet
- `CLAUDE.md` §FIX THE MODEL, NOT THE SYMPTOM — die Wurzel war die
  Pauschalzuweisung, nicht die vier Einzelbefunde
- `CLAUDE.md` §FAIL-CLOSED — AC 6
