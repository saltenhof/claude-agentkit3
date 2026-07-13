---
concept_id: META-DEC-2026-07-13-VERIFY-EVIDENCE-EDGE-EXECUTION
title: Concept-Decision-Record — Verify-Evidenz am Project Edge
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, verify-evidence, edge, ownership-fence, preflight]
formal_scope: prose-only
---

# Concept-Decision-Record — Verify-Evidenz am Project Edge

Datum: 2026-07-13. Record gemaess META-CONCEPT-CONSISTENCY P3,
auf Grundlage des Design Freeze fuer AG3-156.

## 1. Anlass

FK-10 §10.2.4a verbietet Backend-Annahmen ueber physischen Zugriff
auf dev-lokale Ziel-Worktrees. Evidence Assembler, Import Resolver
und Request Resolver enthielten noch solche Leseflaechen. Eine
einfache synchrone Verlagerung in einen Edge-Call loest das Problem
nicht: Die synchrone QA-Subflow-Anfrage haelt nach FK-91 §91.1a
Regel 14 den `(project_key, story_id)`-Claim, waehrend der mutierende
Result-POST denselben Claim benoetigt. Warten innerhalb derselben
Anfrage wuerde daher konstruktiv blockieren.

## 2. Entscheidung

Entschieden ist Variante (a): ein zweistufiger
`collect_verify_evidence`-Edge-Command-Batch nutzt die bestehende
Phase-Yield/Resume-Grenze. Die Speicherung erfolgt in
`edge_command_records` (K5 Postgres-only); es gibt keine neue Tabelle
und kein neues allgemeines Async-Framework.

### 2.1 Timing-Modell

1. **Wait-point A:** Die Implementation-Phase commissioned
   `base_collection`, persistiert `PAUSED` und beendet die Anfrage.
   Der Story-Claim ist frei. Der Client pollt den Edge, der
   Result-POST terminalisiert nur den CommandRecord; Resume baut aus
   Stage-1-Dateien und Import-Snapshot das Basis-Manifest.
2. **Once-only Preflight:** Vor dem LLM-Aufruf wird ein gefencter
   terminaler Attempt-Audit-Record mit Request-Hash geschrieben. Raw
   Response, kanonische Requests, Request-Digest und Basis-Manifest
   werden danach gemeinsam im ausfuehrbaren Stage-B-CommandRecord
   checkpointed. Ein Crash vor diesem Checkpoint erzeugt einen neuen
   Attempt; alte und neue Attempts werden nie gemischt.
3. **Wait-point B:** Die Phase commissioned den
   `dynamic_requests`-Batch und yielded erneut. Result-POST schreibt
   nur den Record. Resume wendet D3 und Bundle-Erweiterung unter dem
   aktiven Rule-15-Ownership-Fence an und setzt erst danach den
   QA-Subflow fort.
4. **Bounded wait:** Die UTC-Deadline steht im Checkpoint. Open vor
   Deadline bleibt `PAUSED`; nach Deadline supersedet Resume den
   offenen Record gefenct und erzeugt pro Request `TIMEOUT`/
   `UNRESOLVED`. Der Backend-Request schlaeft nie und kann einen
   pausierten Client nicht selbst wecken.

### 2.2 Identitaet und Fence

`batch_id` ist der Hash ueber Run, Implementation-Attempt,
Candidate-Digest, Stage und Preflight-Template-Version.
`generation` bindet zusaetzlich Owner-Session/Epoch beziehungsweise
Preflight-Attempt. Resultate muessen Batch, Generation, Candidate-
und Request-Digest echoen. Ein Mismatch wird vor dem Terminal-Commit
abgewiesen. Candidate-/Ownership-Drift supersedet eine alte offene
Generation unter dem Story-Claim vor Commissioning der neuen.
`EdgeCommandRecord.ownership_epoch` bleibt Audit; der aktuelle
Rule-15-Read ist der Write-Fence.

### 2.3 Sicherheitsvertrag fuer Tests

LLM-Text ist niemals Shell-Text. `NEED_TEST_EVIDENCE` akzeptiert nur
den typisierten `VerifyTestCommand` fuer `pytest`, eine geschlossene
Argument-Whitelist, relative Ziele und einen harten Timeout. Der
Project Edge revalidiert den Vertrag und startet argumentweise mit
`shell=False`. Nicht konforme Eingaben werden als
`TEST_COMMAND_REJECTED` gemeldet und nicht ausgefuehrt.

## 3. Alternativen

- **Naiver bounded wait in der QA-Anfrage:** verworfen. Er haelt den
  Claim, hinter dem der Result-POST serialisiert werden muss, und
  laeuft daher systematisch in Timeout/Deadlock.
- **Variante (b), eigener Agenten-Turn:** verworfen. Sie wuerde einen
  zweiten Ergebnis-/Turn-Kanal einfuehren, obwohl Command-Queue und
  Phase-Resume bereits die benoetigte Lebenszyklusgrenze besitzen.
- **Neues Async-Framework oder neue Tabelle:** verworfen. Es
  dupliziert `edge_command_records`, Vergabe/Ack/Result und den
  bestehenden Pause-State ohne zusaetzliche Fachsemantik.
- **Backend-Fallback bei nicht erreichbarem Edge:** verworfen. Er
  verletzt die Worktree-Topologie und waere ein Error-Bypass. Der
  normative Pfad bleibt sichtbar `TIMEOUT`/`UNRESOLVED`.

## 4. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-47 §47.2/§47.3/§47.5 | geaendert | Edge-Erhebung, Backend-D3, zwei Wait-points, Deadline und Crash-Attempt |
| FK-46 §46.1–§46.5 | geaendert | Import Resolver konsumiert content-gebundenen Snapshot statt Worktree |
| FK-28 §28.3.0–§28.3.4 | geaendert | Assembler-Grenze und AG3-147-Ausnahme normiert |
| FK-33 §33.6.3 | geaendert | Sonar-Attestation setzt keinen Backend-Git-/Worktree-Zugriff voraus |
| FK-91 §91.1b/§91.1b.1 | geaendert | neue Command-/Result-Art und Timing-/Fence-Vertrag |
| FK-10 §10.2.4a/b | geprueft, nicht geaendert | bestehende Topologie- und pushed-only-Heimat traegt die Entscheidung |
| FK-20/FK-39 | geprueft, nicht geaendert | vorhandenes `PAUSED`/Resume und vorhandener Edge-Pausegrund werden wiederverwendet |
| `formal.state-storage` | geprueft, nicht geaendert | bestehendes `edge-command-record`; keine neue Entitaet |
| Project-Edge-Bundle-SSOT | geaendert | `src/agentkit/bundles/target_project/tools/agentkit/projectedge.py` nutzt den erweiterten Command-Loop |
| Frontend | nicht betroffen | Story-Lane schliesst `src/agentkit/frontend/**` aus |

## 5. Folgen

Result-POST und Bundle-Anwendung sind zeitlich getrennt. Ein
terminales Result ist noch keine QA-Wirkung; erst ein client-
getriebenes Resume unter gueltiger Ownership darf es anwenden.
Exit, Reset, Transfer oder Candidate-Drift machen alte Resultate
wirkungslos. Der Review bleibt bei Edge-Ausfall lauffaehig, aber die
fehlende Evidenz bleibt als benannter Befund im Bundle sichtbar.
