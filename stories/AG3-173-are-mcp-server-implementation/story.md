# AG3-173 — ARE-MCP-Server implementieren: den an features.are gebundenen agentkit-are-mcp-Befehl real bereitstellen

- **Typ:** implementation
- **Groesse:** L
- **depends_on:** [AG3-164] — der generische MCP-Conformance-Check ist die
  Abnahme, gegen die dieser Server bestehen muss.
- **unblocks:** []
- **Quell-Konzept:** FK-03 §3.1 (`are.mcp_server` an `features.are`
  gebunden); FK-50 (CP10-Registrierung, Conformance-Vorbedingung);
  ARE-Fachkonzept (Owner benennt die massgeblichen FK-Abschnitte im Setup)
- **Herkunft:** Folge-Story aus AG3-164. Verlangt vom unabhaengigen
  Reviewer in `stories/AG3-164-are-mcp-phantom-registration/review-9-codex.md`
  als benannter Auflösungspfad fuer den dort ehrlich rot gemachten
  ARE-Registrierungspfad.

## Kontext / Problem

AG3-164 hat einen generischen MCP-Conformance-Check als
Registrierungsvorbedingung gebaut: CP10 schreibt einen MCP-Server-Eintrag
in die Zielprojekt-`.mcp.json` erst, nachdem der referenzierte Server
Prozessstart, `initialize` und `tools/list` bestanden hat. Fuer den
Story-Knowledge-Base-Server wird dieser Vertrag durch AG3-167/AG3-168
erfuellt.

Fuer den **ARE-MCP-Server** bleibt er offen: CP10 registriert bei
`features.are: true` den Konsolen-Befehl `agentkit-are-mcp`, der nicht in
`pyproject.toml` unter `[project.scripts]` steht und nicht existiert.
AG3-164 macht das jetzt **ehrlich rot** — die Registrierung scheitert
fail-closed, statt einen toten Eintrag zu schreiben. Der Defekt ist damit
sichtbar, aber die Faehigkeit fehlt.

Diese Story schliesst die Luecke: Sie implementiert den ARE-MCP-Server,
sodass die Registrierung bei aktivem `features.are` den Conformance-Check
besteht.

**Abgrenzung zu AG3-164:** AG3-164 baute den Guard und die ehrliche
Fehlermeldung — nicht den Server. Diese Story baut den Server, nicht den
Guard. Der Guard aus AG3-164 ist unveraendert die Abnahme, gegen die der
Server hier antritt.

## Scope

### In Scope

1. **ARE-MCP-Server implementieren** (Produktionscode unter
   `src/agentkit/`), stdio-Transport, mit den fachlich in FK-03/dem
   ARE-Fachkonzept normierten Tools. Der genaue Toolschnitt ist im Setup
   aus den Konzepten abzuleiten; der Umsetzungsagent liest sie selbst und
   stoppt bei Konflikt.
2. **Konsolen-Befehl `agentkit-are-mcp`** in `pyproject.toml`
   `[project.scripts]` registrieren, sodass das von CP10 geschriebene
   Kommando aufloest.
3. **Conformance-Bestehen:** Der Server besteht den generischen
   MCP-Conformance-Check aus AG3-164 (Prozessstart mit Timeout,
   `initialize`, wohlgeformte nicht leere `tools/list`) — belegt durch
   einen Test, der den Server durch genau dieses Gate schickt.
4. **Projektlokale Bindung** analog zum Story-Knowledge-Base-Server:
   Registrierung ausschliesslich projektlokal, `env` traegt die
   erforderlichen Werte (`ARE_MCP_SERVER` bzw. die im ARE-Konzept
   normierten), `required = true`, kein Userspace.
5. **Tests** nach CLAUDE.md-Pflichtregeln, inkl. Negativpfade und einem
   Conformance-Durchlauf gegen den echten Server-Subprozess.

### Out of Scope

- Aenderungen am generischen Conformance-Check (AG3-164, abgeschlossen).
- Story-Knowledge-Base-Server und VektorDB-Kette (AG3-161…AG3-171).
- ARE-Fachlogik, die ueber den MCP-Server-Zugang hinausgeht — nur der
  MCP-Server-Zugang ist Gegenstand dieser Story.

## Akzeptanzkriterien

1. `agentkit-are-mcp` existiert als Konsolen-Befehl und startet einen
   MCP-Server ueber stdio.
2. Bei `features.are: true` besteht die CP10-Registrierung: Der Server
   durchlaeuft den AG3-164-Conformance-Check und der Eintrag wird
   geschrieben — belegt durch einen Test, der den frueheren
   `mcp_command_not_found`-Fehlschlag nun in einen Erfolg wandelt.
3. Der Server ist projektlokal gebunden (kein Userspace) und traegt
   `required = true`.
4. Ein `features.are: false`-Lauf bleibt unveraendert `SKIPPED`.
5. `pytest` gruen, Coverage haelt 85 %; `mypy src`, `ruff check src tests`
   sauber; Konzept-Gates gruen, falls Konzeptdateien angefasst.

## Definition of Done

- Alle Akzeptanzkriterien erfuellt.
- Kein Produktionscode ausserhalb `src/agentkit/`; kein God-File; keine
  Mocks fuer den Conformance-Durchlauf (echter Subprozess).
- Story-Bericht dokumentiert den aus den ARE-Konzepten abgeleiteten
  Toolschnitt und etwaige Konzeptkonflikte.

## Konzept-Referenzen

FK-03 §3.1 · FK-50 (CP10, Conformance-Vorbedingung aus AG3-164) ·
ARE-Fachkonzept (im Setup zu identifizieren)

## Guardrail-Referenzen

FAIL-CLOSED · ZERO DEBT (loest die von AG3-164 sichtbar gemachte Luecke) ·
SINGLE SOURCE OF TRUTH · ARCH-55
