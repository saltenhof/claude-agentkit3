# Harness-Mechanik: Claude Code (Council-Orchestrator)

Du bist der Main-Agent einer Claude-Code-Session. So spawnst und
steuerst du Gremiums-Worker mit Kontexterhalt.

## Spawn-Wege (in dieser Praeferenzreihenfolge)

1. **Harness-Bridge-Plugin** (falls MCP-Tools `subagent__submit` /
   `subagent__result` o. ae. verfuegbar): fremde Harnesses/Modelle
   (z. B. Codex, Grok, GLM, Kimi) als interaktive Agents mit
   Workspace-Zugriff. Kontexterhalt ueber `resume_job_id` auf den
   jeweils letzten terminalen Job desselben Teilnehmers — NIE eine
   frische Session fuer Folgerunden. Setze den Workspace des Workers auf
   seine Sandbox (`workers/<id>/`), nicht auf das Projekt-Root; gib den
   Korpus als read-only Kopie in `inbox/corpus/`.
2. **LLM-Hub** (falls MCP-Tools `llm_acquire`/`llm_send`/`llm_release`
   verfuegbar): reine Text-Teilnehmer ohne Dateizugriff. EIN `acquire`
   fuer den ganzen Lauf, alle Runden ueber dieselbe Session senden,
   `release` erst am Ende. Eingaben (Briefing, Korpus-Auszuege, fremde
   versiegelte Proposals) uebergibst du als Dateianhaenge/Prompt-Inhalt;
   die Proposal-Antwort schreibst DU in die jeweilige `outbox/` (der
   Teilnehmer hat kein Dateisystem — du bist sein Schreibarm, die
   Outbox-Disziplin gilt trotzdem).
3. **Claude-CLI-Teilnehmer**: `claude -p "<prompt>" --output-format json`
   → `session_id` aus dem JSON merken; JEDE Folgerunde mit
   `--resume <session_id>` (nie ohne — sonst Kontextverlust).
4. **Interne Sub-Agenten** (Task-Tool): fuer Claude-Teilnehmer ohne
   Persistenzbedarf ueber Runden hinweg nur geeignet, wenn du den
   Rundenkontext im Prompt vollstaendig mitgibst; fuer Mehrrunden-Laeufe
   bevorzuge 1–3.

## Parallelitaet

Dispatch an alle Teilnehmer einer Runde in EINEM Zug (parallele
Tool-Calls bzw. Hintergrund-Jobs) — sequenzielles Senden laesst Modelle
minutenlang aufeinander warten. Notiere je Dispatch `prompt_digest` und
Eingabe-Digests in `ROUND.json`; beim Eintreffen `proposal_digest` und
`outcome`.

## Grenzen durchsetzen

In AK3-registrierten Projekten blockieren Guards Worker-Schreibzugriffe
ausserhalb ihrer Outbox. Ohne solche Guards (externe Backends) gilt:
Worker-Workspace = Sandbox-Verzeichnis; niemals das Projekt-Root als
Workspace eines Workers. Pruefe nach jeder Runde per `git status` /
Verzeichnisvergleich, dass keine Fremdschreibungen passiert sind.

## Review-/Receipt-Reviewer

Fuer Projection-Receipts brauchst du einen Reviewer mit anderem Principal
UND anderer Session als der Schreibende. Praktisch: ein Bridge-Job eines
anderen Modells (z. B. Codex) oder eine separate `claude -p`-Session
(anderes Modell/Session-ID). Dokumentiere beide Principals im Receipt.
