---
concept_id: META-DEC-2026-07-13-MERGE-LOCAL-MAIN-CREDENTIAL
title: Concept-Decision-Record — Credential-/Autorisierungs-Contract des merge_local-`main`-Updates (FK-12 ↔ FK-15)
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, merge-local, credential, provider-neutral, cli-auth, FK-12, FK-15, FK-29, AG3-152]
formal_scope: prose-only
---

# Concept-Decision-Record — merge_local-`main`-Update-Credential (FK-12 ↔ FK-15)

Datum: 2026-07-13. Record gemaess META-CONCEPT-CONSISTENCY P3.
Anlass: Der AG3-152-Abschluss-Review fand, dass FK-12 §12.7.1 den finalen
`main`-Update dem Edge-Auftrag `merge_local` zuweist, waehrend FK-12 §12.1.3 /
FK-15 §15.5.4 die Dienst-Identitaets-/Ref-Schutz-Sprache **nur** fuer `story/*`
ausformulieren. Der Implementierungs-Worker stoppte fail-closed (Konzepttreue:
kein erfundener Security-Contract). Diese Eskalation war korrekt; sie wird hier
aufgeloest — ohne Erfindung, weil das Modell die Antwort bereits traegt.

## 1. Befund (am Konzept verifiziert)

- **FK-12 §12.1** (`12_github_integration_repo_operationen.md:81-84`): „Fuer die
  CLI-Pfade uebernimmt die `git` CLI Authentifizierung, Token-Handling und Retry
  selbst"; fuer `story/*`-Pushes gilt **zusaetzlich** die Dienst-Identitaet/der
  Ref-Schutz aus §12.1.3.
- **FK-12 §12.1.2** (`:109`): abgelaufenes Token → „Mensch muss `gh auth login`
  ausfuehren". AK3 verwaltet also **kein** Transport-Credential; es setzt den
  vorauthentifizierten Host-CLI voraus.
- **FK-12 §12.1.3 / FK-15 §15.5.4**: die „AK3-/Edge-Dienst-Identitaet" ist eine
  **provider-neutrale Ref-Schutz-Capability** fuer `story/*` (Mechanik
  ausschliesslich im Provider-Adapter; „nie im Repo"), **kein** vom Edge
  gehaltenes Credential.
- **FK-12 §12.1**: Provider-Neutralitaet ist normativ (Betrieb gegen beliebige
  Git-Backends, z. B. Azure DevOps, allein durch Adapter-Austausch). Eine
  provider-spezifische Credential-Mechanik darf ausserhalb des Adapters nirgends
  auftauchen.

## 2. Praemisse (die tragende Entscheidung)

Ein Rechner = ein menschlicher Nutzer; der **Project Edge laeuft auf dessen
Maschine**. Der Nutzer hat seinen Git-CLI-Client (git-credential-helper / `gh` /
`az` / …) **bereits authentifiziert** (out-of-band, provider-spezifisch, ausserhalb
von AK3). Weil AK3 provider-neutral bleibt, trifft es **bewusst keine** Aussage
ueber die konkrete Authentifizierungs-Mechanik je Provider.

**Der `merge_local`-`main`-Update ist ein CLI-Pfad im Sinne von FK-12 §12.1:** die
`git` CLI uebernimmt die Authentifizierung. Der Project Edge haelt **kein eigenes
Credential** und braucht keins — weder fuer `story/*` noch fuer `main`.

## 3. Entscheidung

1. **Credential-Klasse des `main`-Updates:** die vorauthentifizierte Host-Git-CLI
   (FK-12 §12.1). Kein Edge-eigenes Credential, keine erfundene Service-Identitaet
   fuer `main`, keine provider-spezifische Mechanik im Konzept oder in der
   Fachlogik.
2. **Autorisierung des `main`-Updates:** das bestehende `merge_local`-Commission-
   Gating — Ownership-Epoch (FK-56 §56.8a), alle Closure-Verdicts PASSED und die
   serverseitige Push-Verifikation (FK-29 §29.1a, AG3-147). `main` wird nie direkt
   gepusht, sondern ausschliesslich ueber diesen gegateten Backend-Auftrag.
3. **Ref-Schutz von `main`:** eine Repo-/Provider-seitige Konfiguration im
   Verantwortungsbereich des Menschen (analog zu `story/*` als
   Capability-Anforderung, §12.1.3), **nicht** ein von AK3 gehaltenes Credential.
4. **FAIL-CLOSED-Randbedingung:** der Edge-Push setzt `GIT_TERMINAL_PROMPT=0` —
   fehlende/abgelaufene CLI-Auth fuehrt zu einem sofortigen, sichtbaren Fehler
   (→ Mensch: `gh auth login`, §12.1.2), niemals zu einem blockierenden
   interaktiven Prompt.

## 4. Nachzug

- FK-12 §12.7.1: praezisierende Notiz — der `merge_local`-`main`-Update folgt der
  CLI-Pfad-Auth-Praemisse (§12.1); kein separates `main`-Credential.
- FK-15 §15.5.4: Cross-Ref — die Dienst-Identitaet/der Ref-Schutz fuer `story/*`
  wird **nicht** zu einem eigenen `main`-Credential ausgeweitet; der `main`-Update
  laeuft ueber die Host-CLI-Auth (§12.1), autorisiert durch das
  `merge_local`-Commission-Gating.
- AG3-152-Code: `merge_local` `_push` nutzt bereits die Ambient-CLI-Auth (blankes
  `git push`) — konform. Verbleibender Code-Nachzug: `GIT_TERMINAL_PROMPT=0`
  (Punkt 3.4) als fail-closed-Haertung.
- Keine inhaltliche Aenderung am Ref-Schutz-Modell fuer `story/*`; rein die
  Ausweitung der Auth-Praemisse auf den `main`-Update wird explizit gemacht.
