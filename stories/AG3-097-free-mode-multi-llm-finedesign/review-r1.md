OVERALL: CHANGES-REQUESTED

**1. Konzept-Vollstaendigkeit: FAIL**

- ERROR: Story macht den zweiten LLM effektiv optional, FK-25 nicht. Evidence: Story AC3: “ChatGPT-Pflicht (Qwen optional)” [story.md:48](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:48). FK-25 verlangt dagegen ChatGPT plus Qwen oder Ersatz; ohne zweites LLM: “Abbruch, Eskalation an den Menschen” [25_mandatsgrenzen_feindesign_autonomie.md:555](T:/codebase/claude-agentkit3/concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md:555).
  Fix: AC ändern zu: ChatGPT mandatory, second advisor mandatory as Qwen preferred or Gemini/Grok fallback; no second LLM => deterministic `PAUSED` / `infra_unavailable`.

- ERROR: FK-25 §25.5.4 Eskalationsform fehlt. Evidence: FK fordert bei Nicht-Erreichbarkeit `status: PAUSED`, `escalation_class: "infra_unavailable"`, `escalation_reason: "Multi-LLM-Quorum nicht erreichbar"` [25_mandatsgrenzen_feindesign_autonomie.md:642](T:/codebase/claude-agentkit3/concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md:642). Story sagt nur “deterministischer Abbruch (fail-closed)” [story.md:33](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:33).
  Fix: AC mit exakt diesen Phase-/Escalation-Feldern ergänzen.

- WARNING: Session-release-Prüfung aus FK-25 §25.5.4 ist nicht als AC abgesichert. Evidence: FK: “Session korrekt released | Hub Session-Summary | Warning in Telemetrie” [25_mandatsgrenzen_feindesign_autonomie.md:631](T:/codebase/claude-agentkit3/concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md:631). Story erwähnt Freigeben im Scope [story.md:32](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:32), aber kein AC.
  Fix: AC: stats zeigen released; sonst Telemetrie-WARNING nach Severity-Semantik.

**2. AC-Schaerfe: FAIL**

- ERROR: AC6 und AC7 widersprechen sich wegen ARCH-55. Evidence: AC6 verlangt deutsches Wire-Feld `feindesign_entscheidungen` [story.md:51](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:51); AC7 verlangt “alle neuen Identifier englisch” [story.md:52](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:52). User-Hinweis ARCH-55: 8. Feld muss englischer Code-Key sein.
  Fix: AC6 auf konkreten englischen Key umstellen, z. B. `fine_design_decisions`; deutsche FK-Bezeichnung nur als Konzeptname nennen.

- ERROR: AC1 ist nicht testbar genug. Evidence: “fail-closed aus ... kein Integrity-Gate, kein FAIL-Code” [story.md:46](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:46) definiert nicht, was der Aufruf konkret zurückgibt oder wirft.
  Fix: Typisierte Reaktion festlegen, z. B. `IntegrityGateNotApplicableError` vor `integrity_gate_started`; Test prüft Exception/result plus keine Events und keine Closure-FAIL-Codes.

- WARNING: AC5 vermischt Hook-Enforcement und Subprozess-Ergebnis. FK sagt Hook blockiert den nächsten Send nach 10 [25_mandatsgrenzen_feindesign_autonomie.md:613](T:/codebase/claude-agentkit3/concept/technical-design/25_mandatsgrenzen_feindesign_autonomie.md:613); Story erwartet “Ueberschreitung -> `max_rounds_exceeded`” [story.md:50](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:50).
  Fix: Separieren: Hook-AC für 11. Send blockiert; Subprozess-AC für Runde 10 terminiert/dokumentiert nach FK.

**3. Klarheit/Eindeutigkeit: FAIL**

- ERROR: Story sagt gleichzeitig deutsches Feld und englischen Code-Key, nennt aber keinen englischen Zielnamen. Evidence: Scope “8. Change-Frame-Bestandteil `feindesign_entscheidungen`” und direkt danach “Wire-Feld ... englisch” [story.md:35](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:35).
  Fix: Ein einziges Ziel benennen: `fine_design_decisions`, Unterfelder `decision_id`, `question`, `context`, `decision`, `rationale`, `normative_basis`, `discussion`, etc.

- WARNING: “Falls physischer Umzug ... minimal als benannte Surface + melden” ist eine Scope-Flucht. Evidence: [story.md:30](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:30).
  Fix: Entweder Namespace als Muss definieren oder Story splitten. Kein “melden” als Ersatz fuer AC.

- NIT: Gap-Referenzen sind schlampig: “FK-46-56” [story.md:15](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:15), “FK-13-25” [story.md:17](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:17).
  Fix: Auf `FK-56` und `FK-25` korrigieren.

**4. Kontext-Sinnhaftigkeit: FAIL**

- ERROR: Story behauptet konsumierbaren `llm_session_stats`-Transport, aber AK3-Code hat ihn nicht. Evidence: Hub client hat `acquire/send/release/resume`, aber kein stats-API [client.py:92](T:/codebase/claude-agentkit3/src/agentkit/multi_llm_hub/client.py:92), [client.py:206](T:/codebase/claude-agentkit3/src/agentkit/multi_llm_hub/client.py:206); BFF GET/POST kennt Status, Sessions, Events, Acquire, Send, Release, aber kein stats [routes.py:96](T:/codebase/claude-agentkit3/src/agentkit/multi_llm_hub/http/routes.py:96), [routes.py:112](T:/codebase/claude-agentkit3/src/agentkit/multi_llm_hub/http/routes.py:112). Story nennt `llm_session_stats` als vorhandenen Transport [story.md:21](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:21).
  Fix: Entweder minimalen read-only `session_stats` Adapter/Model/Route in Scope nehmen oder die Story von einer vorherigen Adapter-Story abhängig machen.

- ERROR: Story verlangt eine `frozen`/`frozen_at`-Invariante, die der Code explizit nicht hat. Evidence: Story: “`frozen`/`frozen_at`-Invariante wahren” [story.md:69](T:/codebase/claude-agentkit3/stories/AG3-097-free-mode-multi-llm-finedesign/story.md:69). Code: “does not enforce a `frozen`/`frozen_at` consistency invariant” [change_frame.py:277](T:/codebase/claude-agentkit3/src/agentkit/exploration/change_frame.py:277).
  Fix: Formulierung ersetzen durch “bestehendes Freeze-Verhalten nicht ändern”; keine nicht existente Invariante verlangen.

- PASS-Teilbefund: Die Ist-Zustand-Anker `guard_evaluation.py:96-105`, `FineDesignEvaluator` bei [fine_design.py:102](T:/codebase/claude-agentkit3/src/agentkit/exploration/mandate/fine_design.py:102), `ChangeFrame` bei [change_frame.py:270](T:/codebase/claude-agentkit3/src/agentkit/exploration/change_frame.py:270), PROJECT_STRUCTURE `operating_mode_resolver` [PROJECT_STRUCTURE.md:120](T:/codebase/claude-agentkit3/PROJECT_STRUCTURE.md:120), und `projectedge/runtime.py` OperatingMode [runtime.py:28](T:/codebase/claude-agentkit3/src/agentkit/projectedge/runtime.py:28) existieren.

**Must-Fix ERROR List**

1. Deutsches Change-Frame-Codefeld durch englischen Wire-Key ersetzen.
2. ChatGPT plus zweiten LLM verbindlich machen; “Qwen optional” korrigieren.
3. `infra_unavailable` / `PAUSED` / konkrete escalation_reason in AC aufnehmen.
4. AC1 mit konkreter fail-closed Reaktion typisieren.
5. `llm_session_stats`-Adapterluecke entweder in Scope nehmen oder als harte Dependency auslagern.
6. Nicht existente `frozen`/`frozen_at`-Invariante aus der Story entfernen.
