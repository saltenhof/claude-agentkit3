# AG3-074 — Remediation R1 (Antwort auf review-r1.md)

Status der Vorlage: review-r1.md = OVERALL CHANGES-REQUESTED. Alle vier Must-Fix,
beide blockierenden ERRORs (Kontext-Sinnhaftigkeit FAIL + Konzept-Vollstaendigkeit)
sowie alle WARNINGs sind unten einzeln aufgeloest. Geaendert wurde **ausschliesslich**
`story.md` dieser Story; `status.yaml` ist unveraendert (kein Feld war genuin falsch —
Begruendung unter „status.yaml"). Produktionscode/Tests/Konzepte/andere Stories:
nicht angefasst. AG3-057-Template-Struktur beibehalten; ARCH-55-konform.

Faktenbasis am realen Code verifiziert (Anker geprueft):
- `StoryStatus = Backlog|Approved|In Progress|Done|Cancelled` (StrEnum), kein `Open`,
  kein `terminal_state`-Typ (`story_model.py:34-46`).
- `_TERMINAL_STATUSES = {Done, Cancelled}` (`service.py:91-93`).
- `cancel_story` deckt `Backlog|Approved -> Cancelled` ab (`service.py:594-652`,
  `_check_transition` bei `:640`); `complete_story` ist der einzige
  `In Progress -> Done`-Pfad (`service.py:737-761`).
- Closure setzt Done ueber `ClosurePhaseHandler` → `_transition_story_done`
  → `complete_story` (`closure/phase.py:326-334`, `:1082-1097`).
- `implementation_contract`-Restriktion durchgesetzt (`models.py:402-426`).
- `exit_class|ExitClass` → kein Treffer in `src/agentkit`; `terminal_state` nur lokale
  PhaseState-Variable (`engine.py:751`).
- Dashboard-Lesepfad mappt Lifecycle→Spalte mit Default-auf-`Cancelled`
  (`kpi_analytics/dashboard/service.py:48-83`).
- FK-59 §59.6.1/§59.6.2/§59.8 #2/#3/#4/§59.11/§59.12 wie in der Story zitiert
  (`concept/technical-design/59_*.md:210-333`).
- AG3-073 besitzt die administrative `In Progress -> Cancelled`-Transition + den
  `exit_class=viability_handoff`-Producer und weist die konsolidierte Achse + §59.8
  (inkl. #4) ausdruecklich AG3-074 zu (`stories/AG3-073-*/story.md:80,:92,:106`).
- AG3-072 setzt `Cancelled` + `scope_split`, spiegelt Achse an AG3-074
  (`stories/AG3-072-*/story.md:53,:90`).
- AG3-071 setzt **kein** `Cancelled`/`exit_class`, bleibt restartbar; Reset-Stati
  `RESETTING`/`RESET_FAILED` sind kein `terminal_state`
  (`stories/AG3-071-*/story.md:60,:92`).

---

## ERROR-1 (Konzept-Vollstaendigkeit) + Must-Fix-1 — `Cancelled`/#4 zu eng, kollidiert mit `cancel_story`
**Finding:** #4 forderte „`Cancelled` nur ueber Split/Reset/Exit-Records" und verbot
damit implizit den erlaubten Frontend-`cancel_story`-Pfad (`Backlog|Approved ->
Cancelled`). FK-59 §59.8 #4 verbietet `Cancelled` nur als Ergebnis **normaler
Closure-Semantik**.
**Resolution:** #4 (§2.1) und AC5 (§3) komplett umformuliert. #4 ist jetzt strikt auf
die **normale Closure** begrenzt: `complete_story()` aus dem Closure-Pfad fuehrt die
Ergebnisachse nur auf `Done`, nie auf `Cancelled` (Test gegen `ClosurePhaseHandler` →
`_transition_story_done` → `complete_story`, `closure/phase.py:326-334`/`:1082-1097`).
Der administrative `cancel_story`-Pfad (`service.py:594-652`) ist explizit
**unberuehrt und erlaubt** und bekommt einen Abgrenzungs-/Regressionstest (AC5). Die
globale „nur Split/Reset/Exit setzen Cancelled"-Regel ist ersatzlos gestrichen.

## ERROR-2 (Kontext-Sinnhaftigkeit FAIL) + Must-Fix-4 — Producer-/Orchestrierungs-Aussage in der Achsen-Story
**Finding:** #4 zog ueber „nur ueber Split/Reset/Exit-Records" eine Producer-/
Orchestrierungs-Aussage in AG3-074; AG3-073 besitzt die Story-Exit-Orchestration,
FK-58 §58 defert `exit_class` an FK-59.
**Resolution:** AG3-074 konsequent auf **Achsen-Typen + Ableitungsfunktion +
Constraint-Funktion** reduziert. Neuer Header-Satz + neue Guardrail „SAUBERER
STORY-CUT" stellen klar: keine Status-Mutation, kein Producer, keine
Orchestrierung. §2.2 weist alle Producer-/Mutations-/Run-Terminal-Pfade an
AG3-071/072/073 (mit verifizierten Story-Zeilen-Ankern). #4 ist als
Closure-Pfad-Test formuliert (Konsum/Beobachtung), nicht als Producer-Regel.

## ERROR-3 (AC-Schaerfe) + Must-Fix-1 — AC5 nicht testbar ohne Cancel zu brechen
**Finding:** AC5 war als globale „nur Split/Reset/Exit setzen Cancelled"-Regel nicht
eindeutig testbar, ohne `cancel_story` zu verbieten.
**Resolution:** AC5 ist jetzt ein konkreter Test gegen `ClosurePhaseHandler` →
`_transition_story_done()` → `complete_story()` (Closure → `derive_terminal_state ==
Done`) **plus** ein Abgrenzungstest, dass `cancel_story` aus `Backlog`/`Approved`
weiterhin erfolgreich `Cancelled` erzeugt (gueltiges Ergebnis, kein normaler Closure).

## WARNING (Konzept-Vollstaendigkeit) + Must-Fix-2 — Reset-Zwischenstati widerspruechlich
**Finding:** Scope verlangte Mapping inkl. `RESETTING`/`RESET_FAILED`, AC1
relativierte mit „falls vorhanden"; diese Werte existieren im realen `StoryStatus`
nicht.
**Resolution:** Conditional/future-kompatible Variante gewaehlt (statt AG3-071 als
harte Dependency aufzunehmen — siehe „status.yaml" + „Cross-Story" zur Begruendung).
§1 Kontext-Konflikt-Check + §2.1.1 + §2.2 + AC1 stellen klar: die Reset-Stati sind
**heute keine** `StoryStatus`-Member; ihr Typ-Schnitt ist AG3-071-Owner. Die feste
Signatur `derive_terminal_state(StoryStatus)` arbeitet nur auf realen Membern mit
`else → Open`; AC1 fordert einen **Erschoepfungstest** (jeder reale Member abgedeckt,
keine `else`-Luecke) statt eines Pflichttests gegen Phantom-Member. Damit fallen
kuenftige nicht-terminale Member automatisch auf `Open`.

## WARNING (AC-Schaerfe) + Must-Fix-3 — AC6 zu offen („ueberall wo gebraucht")
**Finding:** AC6 („ueberall dort verfuegbar … z. B. KPI/Dashboard") definierte keine
konkrete Schnittstelle; der Dashboard-Lesepfad hat eigene Mapping-Logik mit
Default-auf-`Cancelled`.
**Resolution:** Scope-#6 + AC8 konkretisiert auf **eine importierbare, reine
Funktion** `derive_terminal_state(...)` im `story-contracts`-BC als einzige
kanonische Ableitung. Der Dashboard-/KPI-Lesepfad (`dashboard/service.py:48-83`)
wird **nur als kuenftiger Consumer benannt**; sein Umbau ist explizit
**out-of-scope** (Owner AG3-082/AG3-084). Keine offene „ueberall"-Forderung mehr.

## WARNING (Klarheit) — Signatur „abgeleitet aus StoryStatus" unklar
**Finding:** „abgeleitet aus `StoryStatus`" + Reset-Stati typfachlich unklar; keine
festgelegte Signatur.
**Resolution:** Feste Signatur `derive_terminal_state(status: StoryStatus) ->
TerminalState` durchgaengig festgelegt (§2.1.1, AC1, AC8, Guardrails, §6). Die
Constraint-Funktion bekommt ebenfalls eine feste Signatur
`validate_exit_class_constraints(terminal_state, exit_class | None) -> None`
(§2.1.3, AC3/AC7). Reset-Stati ausdruecklich nicht Teil des Inputs.

## Anker-Korrekturen (file:line auf Ist-Zustand)
- `service.py:91-93` (`_TERMINAL_STATUSES`) beibehalten; `complete_story` praezisiert
  auf `service.py:737-761`; `cancel_story` auf `service.py:594-652` ergaenzt.
- Closure-#4-Anker ergaenzt: `closure/phase.py:326-334` (Step 4 →
  `_transition_story_done`) und `:1082-1097` (`_transition_story_done` →
  `complete_story`).
- Dashboard-Consumer-Anker ergaenzt: `kpi_analytics/dashboard/service.py:48-83`.
- `_resolve_operating_mode` praezisiert auf `runtime.py:1977-1986`.
- Veralteter Hinweis-Anker `projectedge/runtime.py` (kein verifizierter Treffer)
  entfernt; nur der real verifizierte Owner `control_plane/runtime.py:1977-1986`
  bleibt.
- Reset-/Split-/Exit-Owner-Anker auf die realen Story-Zeilen gesetzt
  (`AG3-071-*/story.md:60,:92`; `AG3-072-*/story.md:53,:90`;
  `AG3-073-*/story.md:80,:92,:106`).

## status.yaml
Unveraendert. `depends_on: [AG3-073]` bleibt korrekt (AG3-073 ist der direkte
Konsument der Achse + Constraint). **AG3-071 wurde bewusst NICHT als Dependency
aufgenommen:** AG3-071 liefert weder eine `StoryStatus`-Erweiterung noch einen
`exit_class`-Producer (es setzt explizit **kein** `Cancelled`/`exit_class`); eine
harte Dependency wuerde AG3-071 Scope andichten, den es nicht hat. Die
Reset-Stati-Frage ist daher als future-kompatible `else → Open`-Regel statt als
Dependency aufgeloest.

---

## Genuine Cross-Story-Voraussetzungen (an den Auftraggeber gespiegelt)
1. **AG3-073** (hart, bereits in `status.yaml`) — konsumiert die Achse + Constraint
   und setzt `Cancelled`/`exit_class=viability_handoff`. AG3-074 baut nur Typ +
   Constraint; das **Setzen** ist AG3-073.
2. **AG3-072** (weicher Konsument) — setzt `Cancelled`/`exit_class=scope_split`,
   konsumiert dieselbe Constraint-Funktion. Keine harte Reihenfolge-Abhaengigkeit zu
   AG3-074, da AG3-072 bei noch fehlender Achse lokal `StoryStatus.CANCELLED` setzt
   und das Mapping spiegelt.
3. **AG3-071 — KEINE Dependency, aber offener Typ-Schnitt:** der Reset-Zwischenstati-
   Typ-Schnitt (`RESETTING`/`RESET_FAILED` als `StoryStatus`-Member vs. separate
   administrative Achse) ist AG3-071-Owner und heute **nicht** gebaut. AG3-074
   behandelt das future-kompatibel (`else → Open`), erzwingt aber **keinen** Test
   gegen Phantom-Werte. Sollte AG3-071 diese Werte spaeter als `StoryStatus`-Member
   einfuehren, ist `derive_terminal_state` ohne Aenderung korrekt — ein
   Bestaetigungstest dort waere ein AG3-071-Folgepunkt, kein AG3-074-Scope.
4. **AG3-082/AG3-084 (KPI/Dashboard)** — kuenftige Consumer von
   `derive_terminal_state`, falls der Dashboard-Lesepfad
   (`dashboard/service.py:48-83`) von seiner Eigen-Mapping-Logik (Default-auf-
   `Cancelled`) auf die kanonische Ableitung umgestellt werden soll. Out-of-scope
   fuer AG3-074; nur als Consumer benannt.

## Geaenderte Dateien (nur AG3-074)
- `stories/AG3-074-terminal-state-exit-class-invariants/story.md` (vollstaendig
  ueberarbeitet, AG3-057-Template-Struktur beibehalten; ARCH-55-konform).
- `stories/AG3-074-terminal-state-exit-class-invariants/remediation-r1.md` (diese Datei).
- `status.yaml`: **nicht** geaendert (kein Feld genuin falsch).
