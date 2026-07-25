# AG3-164 — Story-Bericht

**Stand:** abgeschlossen. Alle neun Akzeptanzkriterien erfuellt, elf
Codex-Review-Runden (`review-1-codex.md` … `review-11-codex.md`).

**Abnahmeurteil (Review 11, Gesamturteil):** „Ja — AG3-164 ist in seinem eigenen
Code abnahmereif. **Freigegeben.** Am AG3-164-Code fehlt nichts mehr." Und
ausdruecklich: „Fuer den AG3-164-Code ist keine weitere fachliche Review
erforderlich."

**Code-Landung:** Der Produktionscode (`backend/installer/mcp_conformance/`,
`strict_json.py`, CP10-Integration in `bootstrap_checkpoints/cp10.py`,
`checkpoint_engine/reasons.py`) ist mit Commit `639098c1` auf `main`.

**Landeblocker aufgeloest:** Die Story hing als einzige Vorbedingung an AG3-172
(hermetische Pflichtsuite). AG3-172 ist am 2026-07-25 abgeschlossen und gelandet
(Merge `67aacafd`); die volle Suite ist seither gruen. Damit entfaellt der
Blocker.

## 1. Kernauftrag — erreicht

CP10 registriert **nur tatsaechlich lauffaehige** MCP-Server. Der Check ist
serverunabhaengig: Prozessstart mit Timeout, `initialize`, `tools/list` gegen
einen **echten Subprozess**. Fehler werden fail-closed und maschinenlesbar
klassifiziert, bei Fehlern wird **nichts** mutiert, und gueltige Fremdinhalte
der Zielkonfiguration bleiben erhalten.

Damit ist die Phantomregistrierung beseitigt: Ein Eintrag, dessen Kommando nicht
existiert oder dessen Prozess den MCP-Handshake nicht besteht, wird nicht mehr
geschrieben, sondern **ehrlich rot**.

## 2. Restgrenze — semantisch/wertgenau, NICHT lexikalisch bytegenau

Dies ist die einzige akzeptierte Restgrenze (Review 10/11, P2-1) und gehoert
ausdruecklich in diesen Bericht:

**Fremde JSON-Werte in `.mcp.json` bleiben semantisch exakt erhalten.**
Formatierung und lexikalische Bytes werden dagegen beim deterministischen
Gesamt-Write **normalisiert**. Der Merge ist also *wertgenau*, nicht
*bytegenau*: Ein fremder Eintrag behaelt Struktur, Schluessel und Werte
unveraendert, kann aber neu formatiert (Einrueckung, Schluesselreihenfolge,
Zeilenenden) aus dem Write hervorgehen.

Bewusst so entschieden: Ein bytegenauer Erhalt haette einen
Patch-/Splice-Writer erfordert, der das deterministische Rendern und die
Idempotenz des Gesamt-Writes aufgibt. Der Review hat die Abgrenzung als
**unveraendert akzeptierte Restgrenze** bewertet und ausdruecklich festgehalten,
dass sie **keinen weiteren AG3-164-Code erfordert**.

Nicht betroffen: Negativpfade. Bei Conformance-, Config-, Wire- oder
Nestingfehlern bleibt die Datei **byte-identisch** — das ist getestet und keine
Wertgleichheits-Aussage, sondern echte Byte-Gleichheit.

## 3. ARE-Server als Folgearbeit — wo er gefuehrt wird

AG3-164 macht die ARE-Phantomregistrierung ehrlich rot; es implementiert den
ARE-MCP-Server **nicht**. Die Folgearbeit ist als eigene Story gefuehrt:

**AG3-173 — „ARE-MCP-Server implementieren (macht den von 164 rot gemachten Pfad
gruen)"**, `depends_on: ["AG3-164"]`, Groesse L. Der Review hat das ausdruecklich
als ausreichend adressiert bewertet: „AG3-173 ist als konkrete Folge-Story mit
ID, Abhaengigkeit, Server-/CLI-Scope und echtem Conformance-AC ausreichend
adressiert."

Mit dem Abschluss von AG3-164 wird AG3-173 startbar.

## 4. Auswirkung auf laufende Installationen — Uebergangszustand

Der Conformance-Check laesst jeden Servereintrag ehrlich scheitern, dessen
Prozess den Handshake nicht besteht. Fuer bestehende Installationen bedeutet
das einen **bewusst in Kauf genommenen Uebergangszustand**: Solange ein
konfigurierter MCP-Server nicht wirklich lauffaehig ist, wird er nicht
registriert, sondern gemeldet.

**Richtigstellung eines veralteten Querverweises.** Die `story.md` nennt als
Auflosung dieses Uebergangs „AG3-167/168" und verweist auf AG3-161. Diese IDs
stammen aus dem **alten, ersetzten Schnitt** AG3-161..171 (Provenienz in
`stories/AG3-174-vectordb-retrieval-engine/cut-history/`). Verbindlich ist der
PO-Neuschnitt vom 2026-07-21:

| Anliegen | alter Schnitt | verbindlich jetzt |
|---|---|---|
| VektorDB-Server lauffaehig (Engine, MCP-Tools) | AG3-167 | **AG3-174** — abgeschlossen 2026-07-25 (Merge `f8c40f4c`) |
| Projektlokale Registrierung in beiden Harnessen | AG3-168 | **AG3-175** — offen, `depends_on: [AG3-164, AG3-174]` |
| Installer-Integration, Pflichtaktivierung | — | **AG3-176** — offen, `depends_on: [AG3-174, AG3-175]` |

Der VektorDB-Eintrag ist also seit AG3-174 durch einen **wirklich startbaren**
Server hinterlegt; die Registrierung selbst liefert **AG3-175**. Bis dahin
bleibt der Eintrag konsistent mit AG3-164 ehrlich rot statt als Phantom
geschrieben — genau das beabsichtigte Verhalten, nicht ein Defekt.

Die ARE-Seite bleibt bis AG3-173 ehrlich rot.

## 5. Validatoren und Gates (Stand 2026-07-26, `main` = `f8c40f4c`)

| Pruefung | Ergebnis |
|---|---|
| `pytest` (volle Suite) | **10530 passed, 14 skipped, 0 failed** |
| `ruff check src tests tools/concept_ingester tools/concept_governance` | **All checks passed** |
| `mypy src` | **Success: no issues found in 998 source files** |
| Coverage (explizit `--cov`) | **> 85 %** (Schwelle gehalten) |
| Konzept-Gates | gruen (Review 11 AC 9: „die vorgelegten Gates sind gruen") |
| Conformance-Positivpfad | echter Subprozess, kein Mock — Minimalserver **und** offizieller MCP-SDK-Server bestehen `initialize` + `tools/list` |

**Hinweis zur Vollstaendigkeit der Belege.** Review 11 nennt als
Orchestrator-Punkt 4 auch „vollstaendige CI-/Jenkins-/Sonar-Belege". Die in
dieser Tabelle dokumentierten Belege sind **lokal** erhoben. Ein Jenkins-Build
und ein Sonar-Gate-Lauf fuer den aktuellen `main`-Stand sind **nicht** Teil
dieses Berichts und stehen aus. Das wird hier benannt statt implizit als
erledigt gefuehrt (SEVERITY-SEMANTIK).

**Erwaehnenswerte Umfeldbefunde** (nicht AG3-164 zuzurechnen, waehrend des
Abschlusses aufgefallen und je gemeldet):
- Die 85-%-Coverage-Schwelle wird durch den in `CLAUDE.md` vorgeschriebenen
  Standardbefehl `pytest` **nicht** durchgesetzt (`addopts` enthaelt kein
  `--cov`); die Zahl oben ist explizit gemessen.
- Die beiden LLM-gestuetzten Konzept-Gates (W2 Authority-Prose, W3
  Scope-Consistency) brechen vor jeder Bewertung an der offenen Frage Q2
  (`doc_kind`-Vokabular) ab und liefern daher kein Signal.
- Das in der Review-Kette vorgesehene `llm_hub`-Gegenreview war nicht
  erreichbar (`ECONNREFUSED 127.0.0.1:9600`).

## 6. Akzeptanzkriterien

| AC | Status | Belegt durch (Review 11) |
|---|---|---|
| AC 1 — ARE=true, Kommando fehlt: ehrlicher Fehler | **erfuellt** | CP10 liefert `FAILED/mcp_command_not_found` |
| AC 2 — kein `are-mcp`-Teilwrite | **erfuellt** | Conformance und Config-Pruefung vor dem einzigen atomaren Write; Negativpfade erhalten vorhandene Bytes |
| AC 3 — generischer Check fuer mindestens zwei Definitionen | **erfuellt** | verschiedene Serverdefinitionen, derselbe serverunabhaengige Check |
| AC 4 — Falsch-Gruen ausgeschlossen | **erfuellt** | Kommando-, Prozess-, Wire-, Schema-, Config-Shape- und Nestingfehler benannt abgewiesen |
| AC 5 — realer positiver MCP-Subprozess | **erfuellt** | Minimalserver und offizieller SDK-Server als echte Subprozesse |
| AC 6 — Ressourcensauberkeit | **erfuellt** | Prozessbaum-, Deadline-, Pump- und kombinierte Cleanup-Fehlerpfade total und regressionsgeprueft |
| AC 7 — ARE=false bleibt SKIPPED | **erfuellt** | bewusst abwesendes Feature ohne Probe und Write `SKIPPED` |
| AC 8 — Idempotenz, Fremdinhalt, Dry-run/Verify | **erfuellt** | gueltige Fremdwerte semantisch erhalten; ungueltige Dateien scheitern in allen Modi byte-identisch; read-only startet keine Conformance. Lexikalische Byte-Normalisierung = dokumentierte Restgrenze (§2) |
| AC 9 — FK-50 und Konzept-Gates | **erfuellt** | Implementierung, Reason-Katalog, gemeinsame iterative Tiefengrenze und FK-50 stimmen ueberein |

## 7. Entblockt

| Story | Bedingung | Status nach diesem Abschluss |
|---|---|---|
| **AG3-173** (ARE-MCP-Server) | `depends_on: [AG3-164]` | **ready** |
| **AG3-175** (Dual-Harness-Registrierung) | `depends_on: [AG3-164, AG3-174]` — beide jetzt `completed` | **ready** |

`unblocks` in `status.yaml` nennt noch die alten IDs `AG3-168`/`AG3-171` aus dem
ersetzten Schnitt; verbindlich sind die `depends_on`-Kanten der aktuellen Stories
(`stories/README.md` §2.1: `depends_on` ist autoritativ).
