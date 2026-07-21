# AG3-175 — Projektlokale MCP-Registrierung fuer Claude Code und Codex (Mini-Story)

- **Typ:** implementation
- **Groesse:** M — von **S** angehoben (Review 175-P2-1). Ein semantischer
  TOML-Writer mit Foreign-Data-Erhalt, Konfliktklassifikation, Zwei-Dateien-
  Koordination und digest-/wertgleicher Conformance-Bindung ist keine reine
  Konfigurationszeile. Der Scope bleibt unveraendert und fachlich klein
  isoliert; die Groessenkorrektur erfordert **keinen** weiteren Schnitt.
- **Review-Budget:** **maximal eine Codex-Review-Runde** (PO-Vorgabe). Der
  Umfang ist bewusst klein, damit das haelt.
- **depends_on:** [AG3-164, AG3-174] — braucht den Conformance-Check (164)
  und den lauffaehigen MCP-Server (174).
- **unblocks:** [AG3-176]
- **Quell-Konzept:** FK-76 §76.5.4 (MCP-Registrierungsvertrag, verankert im
  Decision Record 2026-07-21, Rand 4); FK-50 §50.3 CP 10 (Registrierung nach
  Conformance-Check)
- **Herkunft:** PO-Neuschnitt 2026-07-21. Der gesamte harness-spezifische
  Anteil des Vorhabens.

## Kontext / Problem

Der harness-spezifische Anteil des VektorDB-Vorhabens ist im Kern nur die
**Registrierung** des Story-Knowledge-Base-Servers in der jeweiligen
Harness-Konfiguration. Server (AG3-174) und Conformance-Guard (AG3-164)
existieren; hier wird der Server projektlokal in beiden Harnessen eingetragen,
und **nur** nach bestandenem Conformance-Check.

Der Vertrag ist vorab verankert (FK-76 §76.5.4): projektlokal, `required`,
semantischer Merge, fail-closed, niemals Userspace — fuer Claude Code
(`.mcp.json`) und Codex (`.codex/config.toml`) als Spiegelung desselben
Vertrags.

## Scope

### In Scope

1. **Ein einmal gerenderter, digest-/wertgleich gebundener Server-Spec**
   (Review 175-P0-1). Der in AG3-174 geforderte unveraenderliche
   `McpServerSpec` (`command`/`args`/`cwd`/`env` vollstaendig gerendert) wird
   **einmal** gerendert, strikt validiert, mit AG3-164 **geprobt** und **genau
   dieses Objekt ohne erneute Ableitung** in beide Harness-Formate projiziert.
   Kein getrennt konstruiertes Pruefkommando: der geprobte, der geschriebene
   und (per AG3-174) der konsumierte Spec sind identisch gebunden.
2. **Claude Code:** Projekt-`.mcp.json`-Eintrag fuer den
   Story-Knowledge-Base-Server aus genau diesem Spec (`env` mit `PROJECT_ID`
   und Endpunktwerten, projektlokales `cwd`). CP10 bleibt Owner.
3. **Codex:** projektlokale `.codex/config.toml`, Tabelle
   `[mcp_servers.story-knowledge-base]` mit `command`, `args`, `cwd`, `env`
   (identische `PROJECT_ID`/Endpunktwerte wie Claude Code, aus demselben Spec)
   und `required = true`. **Ein** Codex-TOML-Writer im Harness-Adapter,
   semantischer Merge, der fremde Tabellen erhaelt; fail-closed bei
   unparsebarer/konfligierender Konfiguration. **Niemals** `~/.codex/`.
4. **Registrierung erst nach bestandenem Conformance-Check** (AG3-164): kein
   Eintrag ohne bestandenen Check, kein Teil-Schreiben.
5. **Ehrliche Zwei-Dateien-Fehlersemantik** (Review 175-P1-1). Es gibt **keine**
   gemeinsame atomare Dateisystemtransaktion ueber `.mcp.json` und
   `.codex/config.toml`. Vertrag: beide Bestandsdateien werden **vor dem ersten
   Write** strikt gelesen, konfliktgeprueft und vollstaendig gerendert;
   Conformance- oder ein Parse-/Konfliktfehler bewirkt **null Writes**. Jeder
   Einzelwrite ist fuer sich atomar. Bei I/O-Fehler **nach** dem ersten Write
   wird best-effort aus gebundenem Before-Image zurueckgerollt und ein
   benannter `registration_incomplete`-Fehler geliefert; ein Wiederholungslauf
   konvergiert idempotent. Das unvermeidbare Crashfenster zwischen zwei Dateien
   wird **dokumentiert, nicht als Atomizitaet verkauft**.
6. **TOML-Striktheits- und Erhaltungs-Matrix** (Review 175-P1-2; FK-76
   §76.5.4). Der Codex-Writer lehnt vor jedem Write hart ab:
   nicht-tabellenfoermiges `mcp_servers`, falsch typisierte Root-/`mcp_servers`-
   /Server-Shape, falsche Typen fuer `command`/`args`/`cwd`/`env`/`required`,
   ungueltiges UTF-8, doppelte Tabelle/Keys, fremd belegter eigener
   Servername, Symlink-/Junction-Ausbruch aus dem Project-Root. Umgekehrt
   bleiben **fremde Top-Level-Tabellen, fremde MCP-Server und unbekannte
   harness-spezifische Felder** semantisch **wertgleich erhalten** (kein
   ueberstrenges Verwerfen). Benutzerpfade werden auch ueber Environment-/
   Symlink-Aliase nie beschrieben.
7. Beide Merges idempotent, fremde Eintraege erhalten.

### Out of Scope

- Der Server, seine Tools, Ingest, Corpus (AG3-174).
- CP10a-Erstindex, Producer, Aktivierung, Skill (AG3-176).
- Der generische Conformance-Check selbst (AG3-164, fertig) — hier nur
  konsumiert, nicht neu ausgepraegt.
- E2E gegen echte Infrastruktur (nachgelagert mit dem PO).

## Betroffene Dateien

| Datei | Aenderungsart |
|---|---|
| `src/agentkit/harness_client/harness_adapters/codex/` | aendern — MCP-Config-Writer, semantischer Merge |
| `src/agentkit/backend/installer/bootstrap_checkpoints/cp10.py` | aendern — Codex-Registrierung, ein gerenderter Spec in beide Formate, Zwei-Dateien-Koordination |
| `tests/unit/installer/`, `tests/unit/harness/`, `tests/contract/` | neu/erweitern — digest-/wertgleiche Bindung, TOML-Matrix, Zwei-Dateien-Fehlersemantik |

## Akzeptanzkriterien

1. Nach einem Installationslauf ist der Server in **beiden** projektlokalen
   Konfigurationen registriert; beide Merges sind idempotent und erhalten
   fremde Eintraege.
2. Codex-Eintrag traegt `env` (`PROJECT_ID` + Endpunkt) und `required = true`;
   ein Test belegt feldweise Wertgleichheit mit dem `.mcp.json`-Eintrag.
3. Ein Test beweist: **keine** Benutzer-/Globalkonfiguration geschrieben
   (isoliertes `CODEX_HOME`); aus einem zweiten Projektordner ist die
   Registrierung nicht sichtbar. Auch ueber Environment-/Symlink-Aliase wird
   kein Benutzerpfad beschrieben.
4. Registrierung erfolgt erst nach bestandenem Conformance-Check; ein
   fehlgeschlagener Check schreibt keinen Eintrag (auch keinen teilweisen).
5. **Digest-/wertgleiche Bindung** (Review 175-P0-1): Ein Contract-Test
   projiziert genau den geprobten `McpServerSpec` in beide Formate; veraendert
   der Test **nach der Probe ein Feld**, muss der Write verhindert werden. Die
   Negativmatrix umfasst Nicht-Default-Endpunkte, leeren/falschen `cwd`,
   fehlende Environment-Felder und abweichende `PROJECT_ID`.
6. **Zwei-Dateien-Fehlersemantik** (Review 175-P1-1): Ein Conformance- oder
   Parse-/Konfliktfehler bewirkt **null Writes** (beide Dateien byte-identisch
   zum Ausgangsstand); ein simulierter I/O-Fehler nach dem ersten Write loest
   best-effort-Rollback aus dem Before-Image aus und liefert einen benannten
   `registration_incomplete`-Fehler; ein Wiederholungslauf konvergiert
   idempotent.
7. **TOML-Striktheits-/Erhaltungs-Matrix** (Review 175-P1-2): Adversarialer
   Contract-Test fuer ungueltiges UTF-8, doppelte Tabelle/Keys, falsche Root-/
   `mcp_servers`-/Server-Shape, falsche Typen fuer `command`/`args`/`cwd`/`env`/
   `required`, fremd belegten eigenen Namen und Symlink ausserhalb des
   Project-Roots — jeder Fall: benannter Fehler, **beide Dateien
   byte-identisch**. Positiv bleiben fremde Top-Level-Tabellen, fremde
   MCP-Server und unbekannte harness-spezifische Felder semantisch wertgleich
   erhalten.

## Definition of Done

- Alle Akzeptanzkriterien erfuellt; `pytest` gruen, Coverage haelt 85 %;
  `mypy src`, `ruff check src tests` sauber; Konzept-Gates gruen, falls
  beruehrt.
- **Eine** Codex-Review-Runde; Findings eingearbeitet; keine weitere Runde.

## Konzept-Referenzen

FK-76 §76.5.4 · FK-50 §50.3 CP 10 · Decision Record
`2026-07-21-vectordb-edge-sharpening.md` (Rand 4)

## Guardrail-Referenzen

FAIL-CLOSED · SINGLE SOURCE OF TRUTH (ein Codex-Writer) · NO ERROR
BYPASSING · ARCH-55
