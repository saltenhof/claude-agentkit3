# Harness-Mechanik: Codex (Council-Orchestrator)

Du bist der Main-Agent einer Codex-Session. Der Prozess ist identisch zu
`process-core.md`; hier nur die Codex-spezifische Spawn-/Resume-Mechanik.

## Spawn-Wege

1. **Codex-CLI-Teilnehmer**: `codex exec "<prompt>"` startet einen
   nicht-interaktiven Lauf und gibt eine Session/Thread-ID aus; Folge-
   runden desselben Teilnehmers IMMER ueber `codex exec resume
   <session-id> "<prompt>"` (bzw. `codex resume` interaktiv) — nie eine
   frische Session fuer Runde 2+. Setze das Arbeitsverzeichnis des
   Teilnehmers per `--cd workers/<id>/` auf seine Sandbox und den
   Sandbox-Modus restriktiv (`--sandbox workspace-write`), damit er
   physisch nur dort schreiben kann; den Korpus gibst du als read-only
   Kopie in `inbox/corpus/`.
2. **Fremde Modelle** (Claude, GLM, Grok, ...): ueber deren CLIs im
   selben Muster (Session starten, ID merken, immer resumen) oder ueber
   einen verfuegbaren Multi-LLM-Hub/eine Bridge. Reine Text-Teilnehmer
   ohne Dateizugriff: du bist ihr Schreibarm — die Antwort landet in
   ihrer `outbox/`, die Outbox-Disziplin gilt unveraendert.
3. **MCP-Tools**: Falls deine Codex-Konfiguration MCP-Server fuer
   Harness-Bridge oder LLM-Hub bereitstellt, nutze sie analog zu 1/2
   (eine Session je Teilnehmer, Resume statt Neu-Start).

## Parallelitaet

Starte die Dispatches einer Runde als parallele Hintergrundprozesse
statt sequenziell — plattformgerecht: unter POSIX-Shells
`codex exec ... &` je Teilnehmer und anschliessend `wait`; unter
PowerShell (Windows-Primaersystem)
`Start-Process codex -ArgumentList 'exec','...' -PassThru` je Teilnehmer
und `Wait-Process` auf die gesammelten Prozesse (oder `Start-Job`/
`Receive-Job`). `ROUND.json` fuehrt je Teilnehmer
Dispatch-/Receipt-Digests und `outcome`.

## Grenzen durchsetzen

Codex-Sandboxing ist dein Enforcement: Worker-Prozesse laufen mit
Workspace = ihrer Sandbox, niemals mit dem Projekt-Root. In
AK3-registrierten Projekten greifen zusaetzlich die AK3-Hooks
(`.codex/hooks.json`). Pruefe nach jeder Runde, dass ausserhalb der
Outboxen nichts geschrieben wurde.

## Review-/Receipt-Reviewer

Projection-Receipts verlangen einen Reviewer mit anderem Principal UND
anderer Session als der Schreibende — praktisch: eine separate Session
eines anderen Modells (z. B. `claude -p` oder ein Hub-Backend).
Dokumentiere beide Principals und Session-Handles im Receipt.
