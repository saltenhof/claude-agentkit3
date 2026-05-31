# AG3-049: Codex-Harness-Adapter — CodexSettingsWriter Vollausbau

<!-- AG3-049 (Stefan-Entscheidung 2026-05-25): Folge-Story zu AG3-031.

RE-SCOPE v1 (2026-05-25, Orchestrator): urspruengliche Fassung stuetzte AC#2/#3
auf eine "FK-30 §30.11"-Mappingtabelle + .codex-Schema, die dort NICHT existieren
(§30.11 mappt Tool->fachliche Operation, nicht Toolname->Toolname; §30.11.5 =
"per Codex-Standard"; FK-50 CP9 verweist zirkulaer zurueck auf §30.11). Re-geankert
an den bestehenden Codex-Runtime-Adapter + FK-50 CP9.

RE-SCOPE v2 (2026-05-25, nach Codex-Vorlage job-6f07a9f5 = SEGEN VERWEIGERT):
Codex hat per Recherche der offiziellen OpenAI-Codex-Hook-Doku
(developers.openai.com/codex/hooks) sechs blockierende Punkte geliefert. Diese
Fassung arbeitet sie ein:
- Luecke A -> Variante I mit REALER Codex-Konvention `.codex/hooks.json`
  (dreistufige Shape), NICHT der frueher angenommenen flachen
  `[[hooks.<event>]]`-matcher+command-Form.
- "Settings-Matcher" vs "adapter-normalisierter Toolname" sauber getrennt.
- Luecke B -> tokenweises partielles Mapping (kein All-or-nothing).
- Merge-Identitaet Event+Matcher+Command (nicht matcher-only).
- Command parse/validate statt blind ersetzen.
- Neues AK zur Codex-Trust-Layer-Aktivierungsgrenze.
Diese Fassung muss erneut Codex zum Segen vorgelegt werden, bevor ein Worker
beauftragt wird. -->

**Typ:** Implementation
**Groesse:** M (durch Codex-Auflagen tendenziell M+)
**Abhaengigkeiten:** AG3-031 (Governance-Top-Surfaces + Settings-Writer-Geruest);
beruehrt denselben Writer wie AG3-031-Hotfix „Matcher-Identitaet" — Reihenfolge beachten.
**Quell-Konzepte und Quell-Code (autoritativ, in dieser Reihenfolge):**
- `https://developers.openai.com/codex/hooks` — **reale Codex-Hook-Konvention**
  (Dateiformat, dreistufige Shape, Matcher-Tokens, Trust-Layer). ZEITABHAENGIG:
  der Worker MUSS die aktuelle Shape gegen diese Doku verifizieren.
- `src/agentkit/governance/harness_adapters/codex/event_mapping.py` — Quelle der
  **AK3-internen Codex-Adapter-Klassifikation** (NICHT automatisch die
  Codex-Settings-Matcher-Syntax — siehe §1a Auflage 2)
- `src/agentkit/governance/harness_adapters/codex/cli.py` — Command-Form
  `agentkit-hook-codex {phase} {hook_id}`
- `FK-30 §30.3.1` (Claude-Matcher-Schema = Quelle der zu mappenden Tokens)
- `FK-30 §30.11.2 / §30.11.3` (Adapter-Architektur + Vertrag)
- `FK-50 §CP9` (register_hooks Merge/Idempotenz, Installer-Andockung)

---

## 1. Kontext

AG3-031 lieferte `Governance.register_hooks(hook_definitions)` mit
`ClaudeCodeSettingsWriter` (produktiv, `.claude/settings.json`) und
`CodexSettingsWriter` (Stub). Diese Story macht den `CodexSettingsWriter`
produktiv.

## 1a. Codex-Auflagen (job-6f07a9f5, eingearbeitet — vor Re-Vorlage pruefen)

**Auflage 1 — Reales Codex-Hook-Format (Luecke A = Variante I).**
Codex-Hooks sind **dreistufig**, nicht flach. Offiziell unterstuetzt Codex
`.codex/hooks.json` oder inline `[hooks]` in `.codex/config.toml`; die Shape ist
**Event -> Matcher-Gruppe -> Handler-Liste** mit `type="command"` + `command`.
**Gewaehlt (Stefan 2026-05-25): `.codex/hooks.json`** — hook-spezifisch, beruehrt
keine fremden `config.toml`-Keys. Der Worker MUSS die exakte aktuelle Shape gegen
`developers.openai.com/codex/hooks` verifizieren (zeitabhaengig). KEINE erfundene
AK3-Minimalform.

**Auflage 2 — Settings-Matcher != adapter-normalisierter Toolname.**
`event_mapping.py` ist die Quelle der AK3-internen Adapter-Klassifikation
(Tool -> fachliche Operation), NICHT automatisch die Codex-Settings-Matcher-
Syntax. Reale Codex-PreToolUse-Matcher (laut OpenAI-Doku): u. a. `Bash`,
`apply_patch`, MCP-Toolnamen; `apply_patch` deckt Edit/Write; WebSearch wird
aktuell nicht interceptet. Die Story trennt klar:
- **emittierter Settings-Matcher** = das, was in `.codex/hooks.json` steht
  (Codex-eigene Matcher-Syntax/Regex),
- **adapter-normalisierter Toolname** = interne Klassifikation in `event_mapping.py`.
Der Worker verifiziert die realen Codex-Matcher-Tokens gegen die Doku.

**Auflage 3 — Luecke B: tokenweises partielles Mapping (kein All-or-nothing).**
- Bekannte, in Codex nicht repraesentierbare Tokens (z. B. `Agent`) entfallen
  **tokenweise** mit dokumentierter Mapping-Diagnose; die uebrigen Tokens eines
  Matchers bleiben aktiv (Beispiel `Bash|Write|Edit|Read|Grep|Glob|Agent`:
  `Agent` faellt weg, Rest bleibt -> Hook bleibt fuer die anderen Tools gueltig).
- Nur wenn ein Matcher nach Entfernung **aller** bekannten nicht-repraesentier-
  baren Tokens **leer** ist, wird fuer Codex kein Hook geschrieben — als
  dokumentierte Nicht-Anwendbarkeit (sichtbare Diagnose, nicht still).
- **Unbekannte, nicht klassifizierte Tokens -> ERROR** (FAIL CLOSED).
Begruendung: verhindert sowohl stillen Passthrough als auch Ueberreaktion, die
bestehende Guard-Abdeckung loescht.

**Auflage 4 — Merge-Identitaet = Event + Matcher + Command (NICHT matcher-only).**
FK-30 §30.3.1 hat mehrere Hooks mit identischem Matcher (z. B. `Bash`:
branch_guard + story_creation_guard). UPSERT nur nach Matcher loescht Governance.
Identitaet mindestens Event + Matcher + Command (bzw. Hook-ID). Bei der
dreistufigen Codex-Shape gehoeren mehrere Handler unter dieselbe Matcher-Gruppe.
HINWEIS: dieselbe Klasse Bug existiert im `ClaudeCodeSettingsWriter` und wird im
separaten AG3-031-Hotfix behoben; diese Story muss den Codex-Pfad konsistent dazu
bauen.

**Auflage 5 — Command parse/validate statt blind ersetzen.**
Erwartet exakt `agentkit-hook-claude {phase} {hook_id}` ->
`agentkit-hook-codex {phase} {hook_id}`. Unerwartete Command-Form -> typisierter
Fehler, kein stiller Passthrough.

**Auflage 6 — Codex-Trust-Layer-Aktivierungsgrenze.**
Repo-lokale Codex-Hooks laufen nur in **trusted** `.codex`-Layern; nicht-managed
Hooks werden uebersprungen (OpenAI-Doku). Eine Behauptung „voll hook-aktiviert"
muss diese Grenze abbilden ODER als Installer/Checkpoint-Folgearbeit (FK-50/FK-51)
blockierend ausweisen. Diese Story bildet die Grenze als AK + Doku ab; die
tatsaechliche Trust-Aktivierung ist Installer-Sache (FK-50) und hier Out of Scope.

## 2. Scope

### 2.1 In Scope

#### 2.1.1 Hook-Command-Mapping (Claude -> Codex), parse/validate
`CodexSettingsWriter` parst pro `HookDefinition` den Command exakt als
`agentkit-hook-claude {phase} {hook_id}` und emittiert
`agentkit-hook-codex {phase} {hook_id}`. Abweichende Form -> typisierter Fehler
(Auflage 5).

#### 2.1.2 Tool-Matcher-Mapping (reale Codex-Matcher, tokenweise)
Claude-Matcher-Tokens (FK-30 §30.3.1) werden tokenweise auf reale
Codex-Settings-Matcher gemappt (Auflage 2 + 3). **Vollstaendige Klassifikation
aller §30.3.1-Tokens** (vom Worker gegen die Live-Doku zu verifizieren — die
Tabelle ist die Story-Spezifikation, die Doku der Drift-Check):

| Claude-Token | Codex-Settings-Ziel | Klasse |
|---|---|---|
| `Bash` | `Bash` | mappbar |
| `Write` | `apply_patch` | mappbar (apply_patch deckt Datei-Schreiben) |
| `Edit` | `apply_patch` | mappbar |
| `Read` | — | bekannt-nicht-repraesentierbar (Codex interceptet keinen Read-Matcher) |
| `Grep` | — | bekannt-nicht-repraesentierbar |
| `Glob` | — | bekannt-nicht-repraesentierbar |
| `Agent` | — | bekannt-nicht-repraesentierbar |
| `WebSearch` | — | bekannt-nicht-repraesentierbar (Codex interceptet WebSearch nicht) |
| `WebFetch` | — | bekannt-nicht-repraesentierbar |
| `*_send` | MCP-Tool-Matcher-Regex **oder** bekannt-nicht-repraesentierbar | vom Worker gegen Live-Doku entscheiden |

Regeln: mappbare Tokens -> Codex-Ziel; `apply_patch`-Ziel dedupliziert (Write+Edit
ergeben EIN `apply_patch`); bekannt-nicht-repraesentierbare Tokens entfallen
tokenweise mit Diagnose; ein Token, das in KEINER Zeile dieser Tabelle steht
(also nicht aus §30.3.1 bekannt) -> ERROR (FAIL CLOSED). Wenn ein Matcher nach
Entfall aller nicht-repraesentierbaren Tokens leer ist -> kein Codex-Hook,
dokumentierte Nicht-Anwendbarkeit. Beispiel `Bash|Write|Edit|Read|Grep|Glob|Agent`
-> `Bash|apply_patch` (Read/Grep/Glob/Agent entfallen, Hook bleibt gueltig).

#### 2.1.3 `.codex/hooks.json` (reale dreistufige Shape — gepinnt)
Schreiben der Hooks in `.codex/hooks.json` gemaess realer dreistufiger Codex-Shape:
root `hooks` -> Event-Array -> Matcher-Gruppe (`matcher` + verschachteltes
`hooks`-Array) -> Handler (`type: "command"` + `command`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "agentkit-hook-codex pre branch_guard" }
        ]
      }
    ]
  }
}
```

Die Live-Doku (`developers.openai.com/codex/hooks`) ist Drift-Check, nicht
Primaerersatz: der Worker verifiziert die exakte aktuelle Shape und meldet
Abweichungen, aber dieses Skelett ist die Story-Spezifikation.

#### 2.1.4 Merge / Idempotenz (Event+Matcher+Command), FK-50 CP9
Fremd-Hooks bleiben erhalten; Identitaet Event+Matcher+Command/Hook-ID; mehrere
Handler pro Matcher-Gruppe zulaessig; fail-closed bei kaputter Datei (Auflage 4).

#### 2.1.5 Tests
- Command parse/validate (gueltig -> remap; ungueltig -> Fehler)
- Matcher-Mapping-Matrix ueber die §30.3.1-Token-Klassen, NICHT nur `Agent`:
  - mappbar: `Bash` -> `Bash`; `Write`+`Edit` -> EIN `apply_patch` (dedupe)
  - Lese-Token: `Read` (bzw. `Grep`/`Glob`) -> entfaellt tokenweise mit Diagnose
  - Web-Token: `WebSearch` (bzw. `WebFetch`) -> entfaellt tokenweise
  - `*_send` -> gemaess Live-Doku-Entscheid (MCP-Regex oder Entfall) — Test pinnt die gewaehlte Regel
  - Teil-Entfall: `Bash|Write|Edit|Read|Grep|Glob|Agent` -> `Bash|apply_patch`
- leerer Matcher nach Entfall -> dokumentierte Nicht-Anwendbarkeit (kein Hook)
- Token NICHT aus §30.3.1 (z.B. `Frobnicate`) -> ERROR (FAIL CLOSED)
- `.codex/hooks.json` Schema parse-back gegen die gepinnte dreistufige Shape (§2.1.3)
- Merge: zwei Hooks gleicher Matcher unter gleichem Event (mehrere Handler je
  Matcher-Gruppe) bleiben BEIDE erhalten
- Fail-closed bei kaputter bestehender Datei
- Contract: `register_hooks` schreibt fuer Codex korrekte Commands + Shape

### 2.2 Out of Scope
- ClaudeCodeSettingsWriter (AG3-031 + dessen Hotfix).
- register_hooks/deactivate_locks-Top-Surface (AG3-031).
- Codex-Runtime-Adapter (event_mapping/decision_mapping/cli) — bereits implementiert.
- Tatsaechliche Codex-Trust-Layer-Aktivierung (Installer, FK-50/FK-51).
- Andere Harness-Adapter ausser Codex.

## 3. Betroffene Dateien
| Datei | Aenderungsart | Beschreibung |
|---|---|---|
| `src/agentkit/governance/harness_adapters/settings_writer.py` | Modifiziert | `CodexSettingsWriter` Stub -> produktiv (Command-validate + tokenweises Matcher-Mapping + `.codex/hooks.json` dreistufig + Merge) |
| `tests/unit/governance/harness_adapters/test_codex_settings_writer.py` | Neu | Mapping-, Schema-, Merge-, Fail-closed-Tests |

## 4. Akzeptanzkriterien
1. Command parse/validate `agentkit-hook-claude {phase} {hook_id}` -> `agentkit-hook-codex {phase} {hook_id}`; abweichend -> typisierter Fehler.
2. Tokenweises Matcher-Mapping gemaess der vollstaendigen §2.1.2-Klassifikationstabelle (alle §30.3.1-Tokens); `Write`+`Edit` dedupliziert zu EINEM `apply_patch`; bekannt-nicht-repraesentierbare Tokens entfallen tokenweise mit Diagnose; Token ausserhalb der Tabelle -> ERROR. Tests decken mind. ein Lese-Token, ein Web-Token und `*_send` ab.
3. Leerer Matcher nach Entfall -> kein Codex-Hook, dokumentierte Nicht-Anwendbarkeit (nicht still).
4. `.codex/hooks.json` entspricht der gepinnten dreistufigen Shape aus §2.1.3 (root `hooks` -> Event-Array -> Matcher-Gruppe -> Handler `type:"command"`+`command`); Live-Doku als Drift-Check verifiziert.
5. Merge-Identitaet Event+Matcher+Command/Hook-ID; gleiche-Matcher-Hooks bleiben alle erhalten; fail-closed bei kaputter Datei.
6. AK zur Codex-Trust-Layer-Grenze dokumentiert; tatsaechliche Aktivierung als FK-50-Folgearbeit ausgewiesen.
7. Keine Stub-Markierung mehr; keine erfundene Schema-Normativitaet.
8. Pflichtbefehle gruen: pytest unit + contract; mypy --strict; ruff clean; Coverage >=85%.

## 5. Definition of Done
- AK 1-8 erfuellt.
- `.venv\Scripts\python -m pytest tests/unit/governance/harness_adapters -q` gruen.
- mypy --strict gruen, ruff clean, Sonar gruen.
- Committed auf `main`.

## 6. Quell-Referenzen (autoritativ)
- **`developers.openai.com/codex/hooks`** — reale Codex-Hook-Konvention (zeitabhaengig, verifizieren)
- **`governance/harness_adapters/codex/event_mapping.py`** — AK3-Adapter-Klassifikation
- **`governance/harness_adapters/codex/cli.py`** — `agentkit-hook-codex`-Command
- **FK-30 §30.3.1 / §30.11.2 / §30.11.3** — Claude-Matcher + Adapter-Vertrag
- **FK-50 §CP9** — register_hooks Merge/Idempotenz + Trust-Aktivierung

## 7. Guardrail-Referenzen
- **ZERO DEBT**: kein Stub-Adapter; keine erfundene Schema-Normativitaet; keine still ueberschriebenen Hooks.
- **FAIL CLOSED**: unbekannte Tokens + abweichende Commands -> typisierter Fehler; leerer Matcher -> dokumentierte Nicht-Anwendbarkeit, nicht still.
- **FIX THE MODEL**: Tool-Klassifikation aus der einen Quelle; reale Codex-Konvention statt Eigenerfindung.

## 8. Hinweise fuer den Sub-Agent
- `developers.openai.com/codex/hooks` SELBST aufrufen und die aktuelle Shape +
  Matcher-Tokens + Trust-Regeln verifizieren, bevor du Annahmen aus dieser Story
  uebernimmst. Bei Abweichung: Story-Annahme korrigieren und melden.
- Settings-Matcher (Codex-Syntax) und adapter-normalisierten Toolname
  (event_mapping.py) NICHT vermischen.
- HARTE VORBEDINGUNG: Der AG3-031-Hotfix „Hook-Identitaet 4-Tupel" ist auf `main`
  gemergt (Commit `d93c0ee`). Vor dem Bearbeiten von
  `governance/harness_adapters/settings_writer.py` MUSST du den aktuellen Stand
  von `main` lesen/rebasen (read-latest), weil Claude- und Codex-Writer im selben
  Modul dieselbe Identitaets-Semantik (Event+Matcher+Command) teilen. Baue den
  Codex-Merge konsistent zur 4-Tupel-Identitaet des Claude-Writers.
- Bei jedem weiteren ungedeckten Punkt: HART STOPPEN und melden. AK2 NICHT veraendern.
