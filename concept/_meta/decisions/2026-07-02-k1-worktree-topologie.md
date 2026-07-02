---
concept_id: META-DEC-2026-07-02-K1-WORKTREE-TOPOLOGIE
title: Concept-Decision-Record — K1 Dev-lokale Worktree-Topologie und Pushed-only
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, worktree-topologie, pushed-only, ownership-transfer, edge]
formal_scope: prose-only
---

# Concept-Decision-Record — K1 Dev-lokale Worktree-Topologie und Pushed-only

Datum: 2026-07-02. Record gemaess META-CONCEPT-CONSISTENCY P3
(Blast-Radius-Pflicht bei normativen Aenderungen).

## 1. Anlass

Die im Session-Ownership-Strang (Commits `3ae011e4` + `1bb4ed8a`)
offen gebliebene Frage K1 (Worktree-Remote-Topologie) wurde durch
zwei PO-Entscheidungen vom 2026-07-02 entschieden. Der zugehoerige
K1-Delta-Entwurf (`_temp/entwurf-k1-worktree-topologie.md`,
Version 4) wurde in drei Review-Runden (Codex + LLM-Hub) geprueft
und von beiden Reviewern freigegeben; die Verankerungs-Matrix
(Entwurf §7) ist die Grundlage dieses Eingriffs. Das Delta
ueberholt bewusst Teile der erst kuerzlich verankerten
Session-Ownership-Konzepte (FK-56 §56.13c/e, FK-30 §30.6.3,
FK-31 §31.1.3c, `state-storage.entity.takeover-worktree-snapshot`).

## 2. Entscheidung

**PO-Entscheidung I — Worktrees leben dev-lokal:** AgentKit darf
niemals annehmen, dass es backend-seitig physischen Zugriff auf
einen Worktree hat. Akteursmodell fuer physische
Worktree-Operationen: Agent, Project Edge (beauftragt, meldend) oder
niemand. Das Backend kennt Branch-Refs, SHAs und Edge-Meldungen —
nie das Dateisystem. Es gilt ein Modell fuer beide
Installationsformen (Loopback und Remote). Heimat: FK-10 §10.2.4a.

**PO-Entscheidung II — pushed-only:** Fuer AgentKit existiert nur
der auf den Story-Branch committete UND gepushte Stand. Das
Uebergabeobjekt eines Transfers ist ein SHA (`takeover_base_sha`),
nie ein Dateizustand; akzeptierter Verlustkorridor mit
Pflichttext-Kommunikation in Challenge und Freigabe-Overlay.
Heimat: FK-10 §10.2.4b (Regel + Sync-Punkte-Hybrid), FK-56
§56.13c/e (Transfer-Mechanik).

Kernkonsequenzen (je in ihrer Single-Assertion-Heimat verankert):

1. **Ausfuehrungsort-Grundsatz** (FK-10 §10.2.4a): physische
   Git-/Worktree-Operationen laufen als Edge-Auftrag, ueber die
   Code-Backend-API (nur Reads/Compare/Push-Verifikation) — oder
   entfallen.
2. **Closure-Merge als Hybrid mit Edge-Merge als Default**
   (FK-29 §29.1a, FK-12 §12.5.2): Auftragsart `merge_local`;
   Kandidatenbildung, `locked_sha`-CAS, `pre_merge_sha`-Rollback und
   Multi-Repo-Stufen vertraglich unveraendert; API-Merge nur als
   spaeterer Strang mit FK-29-Aequivalenznachweis.
3. **Transfer-Record statt inhaltstragendem Snapshot**
   (formal.state-storage v4, FK-56 §56.13c): `takeover_base_sha`
   atomar beim Confirm; Pre-Confirm-Refresh optional; kein
   Post-Confirm-A-Push aendert das Uebergabeobjekt.
4. **Worktree-Identitaets-Klassifikation + Quarantaene-Semantik**
   (FK-56 §56.13e): Same-Worktree via Marker+Pfadbindung uebernimmt
   den Pfad, nie den Inhalt (atomare Quarantaene, nie `git stash`);
   sonst Reprovisionierung aus `takeover_base_sha`.
5. **Salvage-Commit entfaellt** (FK-31 §31.1.3c): menschliche
   Verwertung quarantaenierter Inhalte ausserhalb des Vertrags;
   Wiedereinfuehrung nur durch den aktuellen Owner via
   Commit/Push/QA.
6. **Neue Guard-Zustaende** (FK-30 §30.6.3):
   `remote_branch_diverged_after_takeover`,
   `local_stale_or_dirty_takeover_target`; Reconcile =
   Quarantaene + Reprovisionierung, Mensch nur bei Scheitern oder
   unklarer Identitaet (`contested_local_writes`).
7. **Edge-Command-Queue** (FK-91 §91.1b): eigener Auftrags-Endpoint
   (Ack/Result, `op_id`-Vertrag, Objekt-Serialisierung);
   Auftragsarten provision_worktree, teardown_worktree,
   preflight_probe, sync_push, takeover_reconcile, merge_local;
   Result-Typen branch_ref_report, push_status_report,
   worktree_report, Quarantaene-Details; serverseitige
   Push-Verifikation der harten Barrieren gegen das Code-Backend.
8. **Zweistufige Ex-Owner-Push-Barriere** (FK-12 §12.1.3 Mechanik;
   FK-15 §15.5.4 Zugriffs-/Credential-Modell; FK-55 §55.9
   Capability-Einordnung): regelgeschuetzte `story/*`-Refs +
   AK3-/Edge-Dienst-Identitaet (provider-neutral, s. Nachtrag PO-Direktive III) nur fuer den aktuellen Owner/Epoch;
   Edge-Push-Gate online-pflichtig, Sync-Fallback gilt nicht fuer
   den Push-Pfad.
9. **Preflight 7/8 als Edge-Probe** (FK-22 §22.3.1): Backend
   entscheidet mit Ownership-Kontext; differenzierte Befunde statt
   Sammel-FAIL; „stale fremd" vs. „legitim uebernommen".
10. **workspace_locator-Trennung** (FK-10 §10.2.4a): `project_root`
    ist reiner backend-lokaler State-Anker; die Worktree-Anker-Rolle
    entfaellt ersatzlos; physische Pfade sind ausschliesslich
    Edge-gemeldete `worktree_roots`.

### Namens- und Formalentscheidungen

- **`takeover-transfer-record`** ersetzt
  `takeover-worktree-snapshot` (formal.state-storage.entities,
  schema_version 3 → 4); Identitaet unveraendert
  `(project_key, story_id, run_id, ownership_epoch)`, Attribute je
  Repo: `repo_id`, `takeover_base_sha`, `last_push_at`,
  `push_lag_hint`, `base_quality` (fresh_push | stale_push),
  `challenge_ref`, `confirm_ref`. Die `stale_results`-Invariante
  bleibt unveraendert.
- **formal.operating-modes.commands** (schema_version 2 → 3): Die
  Signatur von `confirm-run-ownership-takeover` sagte „with
  unchanged run_id and worktree_roots" — der worktree_roots-Anteil
  widerspricht dem neuen Modell (Edge-gemeldete Roots der neuen
  Session) und wurde praezisiert; `run_id` bleibt unveraendert.
- **Wire-Contract `takeover-reconcile-worktree`** bleibt namens- und
  pfadgleich; nur die Semantik wurde auf den SHA-Abgleich
  praezisiert (FK-91 §91.1a).
- **Neue Endpoints der Command-Queue** unter
  `/v1/project-edge/...` analog zur bestehenden
  Project-Edge-Gruppe; der Bundle-Sync wird nicht ueberladen
  (eigener Auftrags-Endpoint gemaess Codex-Review W4/§9.5).

## 3. Alternativen

- **Co-Location-Betriebsannahme (backend-lokale Worktrees):**
  verworfen (PO). Sie wuerde erzwingen, dass Harnesse auf dem
  Server laufen; Menschen koennten nie lokal arbeiten,
  Mehrentwickler-Parallelitaet (Entwickler A: Stories A/B/C,
  Entwickler B: D/E/F, je auf eigener Maschine) waere unmoeglich.
  Co-located Zugriff bleibt Zufall der Installation, kein
  Betriebsmodell.
- **API-Merge (reine Code-Backend-API-Variante fuer den finalen
  Merge):** verworfen (Machbarkeits-Review Runde 2, Codex ERROR).
  Die GitHub-API bietet kein exact-old-head-CAS (Aequivalent zu
  `--force-with-lease=<locked_sha>`), keine integrierte
  Kandidatenbildung mit Gruen-Barriere und keine belastbare
  Multi-Repo-Rollback-Semantik — sie traegt die FK-29-Vertraege
  nicht. Normiert wurde der Hybrid mit Edge-Merge als Default; ein
  API-Merge bleibt nur als spaeterer eigener Strang mit
  FK-29-Aequivalenznachweis zulaessig.
- **WIP-Ref-Push (uncommittete Staende als Ref):** verworfen
  (Reviews R1: Governance-Risiken, Branch-Guard-Kollision;
  PO-Entscheidung II macht ihn zusaetzlich modellwidrig).
- **Bounded Best-Effort-Final-Sync / forensische Nachreichung nach
  Confirm:** entfallen — unter pushed-only existiert nichts
  Nachreichbares; A's Edge quarantaeniert lokale Reste lokal.

## 4. Impact-Sweep (P3)

Lexikalische Sweeps ueber `concept/` am 2026-07-02 (ripgrep):

- `takeover-worktree-snapshot|Takeover-Snapshot|takeover_base_sha` →
  formal.state-storage/entities.md, FK-30 §30.6.3, FK-56 §56.13c,
  FK-91 §91.1a, FK-31 §31.1.3c (implizit), FK-72 §72.14.7 — alle
  umgestellt. Historischer Treffer im Decision-Record
  `2026-07-02-session-ownership-nachverankerung.md` bleibt
  unveraendert (Audit-Fakt ueber den damaligen Stand).
- `Salvage|salvage` → nur FK-31 §31.1.3c (Heimat, ersetzt) und
  FK-30 §30.6.3 (Referenz, umgestellt).
- `workspace_locator|project_root|StateBackendWorktreeRepository|SubprocessGitBackend`
  → normativ relevant: FK-10 §10.2.4 („run store / worktree
  anchor"-Kopplung — korrigiert, §10.2.4a). Uebrige
  `project_root`-Treffer (FK-17 §Locator-Felder, FK-18
  `project_spaces`, FK-43/FK-50/FK-51 `Skills.bind_skill`,
  FK-44 §44.4.1 Prompt-Materialisierung, FK-22 §22.8
  `determine_mode`, formal.installer.entities) bezeichnen den
  backend-lokalen State-Anker bzw. den dev-seitigen Project Space
  und sind mit der neuen Trennung vereinbar — nicht geaendert.
- `worktree_roots` in formal-spec → formal.operating-modes:
  `confirm-run-ownership-takeover`-Signatur trug „unchanged
  worktree_roots" — praezisiert (schema_version 3); Entities
  (`worktree_roots` als Bindungsattribut) und Invarianten
  (`story_execution_requires_lock_binding_and_worktree_match`)
  bleiben gueltig (die Roots sind jetzt Edge-gemeldet, die
  Invariante prueft weiterhin den Match).
- `git worktree|clean -xfd|fetch origin` → FK-12, FK-29, FK-10
  (alle umgestellt bzw. mit Ausfuehrungsort-Absatz versehen) sowie
  FK-04 (Operator-Runbook `git worktree list` — menschlicher
  Handgriff auf der Dev-Maschine, kein Backend-Zugriff: unveraendert).
- `\.agent-guard|Governance-Deaktivierung|Reset-Detach|Change-Evidence`
  → FK-22/FK-31/FK-30/FK-55/FK-15/FK-92/FK-05: `.agent-guard`-
  Exporte sind dev-lokale Projektionen des Edge (konsistent);
  physische Detail-Operationen ausserhalb der Matrix (z. B.
  FK-53 §53.7.8 Worktree-Detach beim Reset,
  Verify-Layer-1-Change-Evidence in FK-27/FK-28) sind durch den
  generischen Ausfuehrungsort-Grundsatz (FK-10 §10.2.4a: Edge,
  Code-Backend-API oder entfallen) normativ gedeckt; ihr
  Detail-Umzug ist GAP-/Story-Arbeit (Entwurf §8), keine
  Konzeptluecke.
- `completion.push` → FK-33 §Structural-Checks, FK-27 (bestehende
  Push-Barriere; Erhebungs-/Verifikationsumstellung ist in FK-10
  §10.2.4b normiert, die Check-Kataloge bleiben unveraendert).

## 5. Betroffenheitsmatrix

| Stelle | Klassifikation | Begruendung |
|---|---|---|
| FK-10 §10.2.4 | geaendert | Backend-seitige `project_root`/Worktree-Kopplung entfernt; Verweis auf §10.2.4a |
| FK-10 §10.2.4a (neu) | geaendert | Topologie-Regel, Akteursmodell, Ausfuehrungsort-Grundsatz, workspace_locator-Trennung (Heimat) |
| FK-10 §10.2.4b (neu) | geaendert | Pushed-only-Regel, Sync-Punkte-Hybrid, Push-Frische, WIP-Ref-Verwurf (Heimat) |
| FK-10 §10.2.2 / §10.4.2 / §10.5.3 / §10.6.1 | geaendert | implizite Backend-Ausfuehrungs-Annahmen (gh-CLI, Worktree-/Branch-Cleanup, Setup-Idempotenz, Remote-Fehlerbild) auf Edge-Auftraege umgestellt |
| FK-12 §12.1 | geaendert | Ausfuehrungsort dev-lokal + Code-Backend-API nur lesend/verifizierend; Abgrenzung schreibender Adapter |
| FK-12 §12.1.3 (neu) | geaendert | AK3-/Edge-Dienst-Identitaet + regelgeschuetzte `story/*`-Refs als Provider-Capability (Heimat; s. Nachtrag PO-Direktive III) |
| FK-12 §12.4.3 / §12.5 / §12.7.1 | geaendert | serverseitige Push-Verifikation; setup/teardown_worktree und merge_local als Edge-Auftraege |
| FK-22 §22.3.1 | geaendert | Checks 7/8 als Edge-Probe (`preflight_probe`) mit Backend-Entscheid; differenzierte Befunde; „stale fremd" vs. „legitim uebernommen" |
| FK-22 §22.6.2 / §22.6.3 | geaendert | Worktree-Provisionierung als Edge-Auftrag; Pfade Edge-gemeldet |
| FK-29 §29.1a.1 | geaendert (praezisiert) | Ausfuehrungsort Edge (`merge_local`); CAS-/Rollback-/Multi-Repo-Vertraege ausdruecklich unveraendert; API-Merge nur mit Aequivalenznachweis; Closure-Resume-Cross-Fall |
| FK-56 Glossar `ownership-transfer` | geaendert | Uebergabeobjekt SHA, Edge-gemeldete worktree_roots |
| FK-56 §56.13c | geaendert (ersetzt) | Transfer-Record + `takeover_base_sha` statt Snapshot; Immobilitaet des Uebergabeobjekts; Verlustkorridor-Pflichttext; Ex-Owner-Quarantaene |
| FK-56 §56.13e | geaendert (ersetzt) | Worktree-Identitaets-Klassifikation; Quarantaene-Semantik (nie `git stash`); Reprovisionierung |
| FK-30 §30.6.3 | geaendert (ersetzt) | Reconcile = Quarantaene + Reprovisionierung auf `takeover_base_sha`; Mensch nur bei Scheitern/unklarer Identitaet; +2 neue Zustaende |
| FK-31 §31.1.3c | geaendert (Inhalt ersetzt, Anker unveraendert) | Salvage-Commit entfaellt; Quarantaene-Hinweis; Wiedereinfuehrung nur durch aktuellen Owner via Commit/Push/QA |
| FK-91 §91.1a (Reconcile-Zeile) | geaendert | SHA-Semantik gegen Transfer-Record; benannte Fehlerbilder |
| FK-91 §91.1b (neu) | geaendert | Edge-Command-Queue: Endpoints, Auftragsarten, Result-Typen, serverseitige Push-Verifikation (API-Heimat) |
| formal.state-storage.entities (v4) | geaendert | `takeover-transfer-record` ersetzt `takeover-worktree-snapshot` |
| formal.state-storage.invariants | nicht betroffen | keine Invariante referenziert den Snapshot; `stale_results`-Invariante bleibt |
| formal.operating-modes.commands (v3) | geaendert | Confirm-Signatur: worktree_roots-Rebinding statt „unchanged" |
| formal.operating-modes.entities/invariants/events | nicht betroffen | `worktree_roots`-Attribut und Match-Invariante bleiben gueltig (Edge-gemeldete Roots) |
| FK-15 §15.5.1 / §15.5.4 (neu) | geaendert | Dienst-Identitaet als Credential-Klasse (s. Nachtrag PO-Direktive III); Edge-Push-Gate online-pflichtig, Sync-Fallback gilt nicht fuer den Push-Pfad |
| FK-55 §55.9 | geaendert | Story-Branch-Push nur ueber offiziellen Edge-Push-Pfad; doppelte Sperre fuer disowned Sessions |
| FK-36 §36.6.3 | geaendert (minimal) | Marker-Materialisierung dev-lokal durch den Edge; Marker als Identitaetsanker des Takeover |
| FK-44 | geprueft, nicht geaendert | Prompt-Materialisierung ist dev-seitige Bundle-Mechanik im Project Space (Ebene 2/3), kein Backend-Dateizugriff auf Worktrees |
| FK-72 §72.14.7 | geaendert (minimal) | Push-Frische statt Dirty-Stand (Backend kennt kein Dateisystem); Verlustkorridor-Pflichttext im Overlay; Transfer-Record statt Snapshot; +2 Zustaende |
| FK-29 §29.1.6 / §29.1a.2–.6 | nicht betroffen | Vertraege (Barriere, CAS, Rollback, Sanity-Gate) unveraendert — nur der Ausfuehrungsort ist in §29.1a.1 praezisiert |
| FK-53 §53.7.8, FK-27/FK-28 (Change-Evidence), FK-58, FK-20 | geprueft, nicht geaendert | physische Detailoperationen durch den generischen Ausfuehrungsort-Grundsatz (FK-10 §10.2.4a) gedeckt; Detail-Umzug ist GAP-/Story-Arbeit (Entwurf §8) |
| FK-04 (Runbook `git worktree list`) | geprueft, nicht geaendert | menschlicher Operator-Handgriff auf der Dev-Maschine, kein Backend-Worktree-Zugriff |
| FK-33 §33.x / FK-27 §27.x (`completion.push`) | geprueft, nicht geaendert | Check-Katalog bleibt; Erhebung/Verifikation der Barriere ist in FK-10 §10.2.4b normiert |
| `concept/_meta/decisions/2026-07-02-session-ownership-nachverankerung.md` | nicht betroffen | historischer Audit-Fakt; beschreibt den damaligen Stand (Snapshot-Entitaet) korrekt |
| stories/README.md §6.7 | geaendert | Prozessstand K1 (Nachtrag) + naechster Schritt GAP-Update |


## Nachtrag: PO-Direktive III — Provider-Neutralitaet (2026-07-02)

Nach WP-K1, vor dem Commit, ergaenzte der PO: AgentKit darf nicht mit
GitHub-Spezifika verschraubt werden (Einsatz gegen Azure DevOps in ~2
Monaten geplant). Pures git ist unkritisch; Provider-API-Spezifika sind
so schmal wie moeglich zu halten.

**Disposition (im selben uncommitteten Diff umgesetzt):**
- FK-12 §12.1: Provider-Neutralitaets-Grundsatz (GitHub = Referenz-
  Provider; bevorzugt git-Protokoll — backend-seitige Ref-Reads/
  Push-Verifikation via `git ls-remote`; Provider-Funktionen nur ueber
  schmale, austauschbare Adapter-Schnittstelle; Spezifika nie ausserhalb
  des Adapters). Tabellen-/CLI-Formulierungen entkoppelt (`gh` nur als
  GitHub-Werkzeug im Adapter-Rahmen).
- FK-12 §12.1.3: Ref-Schutz als Capability-Anforderung an den Provider
  (GitHub: App/Rulesets; Azure DevOps: Service-Principal/Branch-
  Security — Mechanik nur im Adapter); Degradations-Regel: Edge-Push-
  Gate ist die ueberall verpflichtende Basis, fehlende Provider-
  Capability ist ein WARNING-pflichtiger Betriebs-Befund.
- FK-15 §15.5.4 + Tabelle, FK-55 §55.9: "App-Identitaet" →
  "Dienst-Identitaet" (provider-neutral, Mechanik im Adapter).
- FK-10 §10.2.4a-Ausfuehrungsort-Aufzaehlung: Ref-Reads/Push-
  Verifikation bevorzugt via git-Protokoll statt "Code-Backend-API".
- FK-91-Push-Verifikation: verweist auf FK-12 §12.1 (neutral), keine
  Aenderung noetig.
