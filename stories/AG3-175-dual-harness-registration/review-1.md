# Review 1 — AG3-175 Dual-Harness-MCP-Registrierung

## Herkunft dieses Reviews

Die eine (PO-mandatierte) Codex-Review-Runde wurde vom Harness durch eine
**Fehlklassifikation** abgebrochen ("possible cybersecurity risk"), ausgelöst
durch Codex' eigene, legitime Reproduktionsskripte (Symlink-/Junction-Escape-
und Control-Char-TOML-Tests gegen *unseren eigenen* Code). Codex hat vor dem
Abbruch bereits Substanz gefunden; der Orchestrator hat die kritischen Fälle
**selbst reproduziert und verifiziert** und das Review vervollständigt. Ein
tool-abgebrochener Turn zählt nicht als verbrauchte Review-Runde.

Reproduktionen liefen über den echten `codex_mcp_config_writer`-Pfad
(`write_mcp_server`) gegen echte Dateien im Temp-Verzeichnis.

## Befunde

### AG3-175-R01 — BLOCKER (AC 7 Preservation) — Fremde valide TOML-Typen werden überstreng verworfen

**Ort:** `src/agentkit/harness_client/harness_adapters/codex_mcp_config_writer.py`
`_format_value` (322-342), `_emit_table` (274-307), `_strict_load_toml`
Root-Typ-Gate (528-540).

**Fakten-Beleg (Orchestrator-Reproduktion):**

```text
foreign_array_of_tables_and_datetime: REFUSED reason=mcp_configuration_invalid
    :: Codex config root key 'released' has unsupported type datetime (fail-closed).
foreign_nested_aot: REFUSED reason=mcp_configuration_invalid
    :: unsupported TOML value type dict (fail-closed).
```

Eine gültige fremde `.codex/config.toml` mit einem Top-Level-`datetime`
(`released = 1979-05-27T07:32:00Z`) oder einer Array-of-Tables (`[[plugins]]`,
`[[tool.items]]`) wird beim Voll-Reserialisieren abgelehnt. Der Merge lädt das
gesamte Dokument in ein dict und serialisiert es komplett neu; der
hand-gerollte Renderer kennt aber weder TOML-`datetime`/`date`/`time` noch
Array-of-Tables.

**Normverletzung:** AC 7 verlangt ausdrücklich, dass fremde Top-Level-Tabellen,
fremde MCP-Server und unbekannte harness-spezifische Felder **semantisch
wertgleich erhalten** bleiben — "kein überstrenges Verwerfen". Die Registrierung
scheitert hier an einer völlig legitimen Bestands-Config (byte-identisch, also
kein Teil-Write — das ist der einzige Trost).

**Fix:** Der Merge muss BELIEBIGE gültige fremde TOML-Konstrukte wertgleich
erhalten: `datetime`/`date`/`time`, Array-of-Tables, beliebig verschachtelte
Tabellen, alle Skalare. Wurzel ist der eigene Voll-Reserializer — nicht per
Sonderfall flicken. Zwei tragfähige Wege (Umsetzer wählt begründet):
(a) ein vollwertiger TOML-Serializer (z. B. `tomli-w`) — dann Dependency sauber
in `pyproject.toml` verdrahten und begründen; oder
(b) ein **textschonender surgical merge**, der ausschließlich die eigene
`[mcp_servers.story-knowledge-base]`-Tabelle einfügt/ersetzt und alle fremden
Bytes unangetastet lässt (robusteste Preservation, keine neue Dependency).

### AG3-175-R02 — BLOCKER (FAIL-CLOSED / stille Korruption) — Control-Chars in fremden Strings erzeugen ungültiges TOML

**Ort:** `codex_mcp_config_writer.py` `_format_string` (345-353).

**Fakten-Beleg (Orchestrator-Reproduktion):**

```text
foreign_control_char_value: WROTE valid_toml=TOMLDecodeError:
    Illegal character '\x08' (at line 1, column 9)
```

`_format_string` escaped nur `\`, `"`, `\n`, `\r`, `\t`. Ein fremder Stringwert
mit einem anderen Control-Char (hier U+0008 `\b`, den `tomllib` beim Laden aus
der Escape-Sequenz `"\b"` dekodiert) wird als **rohes Steuerzeichen** in die
Ausgabe geschrieben. Das Ergebnis ist kein gültiges TOML mehr — der Writer
produziert eine Datei, die er selbst nicht mehr parsen kann. Das ist stille
Korruption, kein fail-closed.

**Normverletzung:** AC 7 (wertgleiche Erhaltung) und FAIL-CLOSED. Eine
Reparatur darf nie zu ungültigem/korruptem Output führen.

**Fix:** Alle TOML-relevanten Control-Chars (U+0000–U+001F außer den kurzen
Escapes, U+007F) korrekt escapen (`\uXXXX`) — oder über Weg (a)/(b) aus R01
lösen, dann entfällt das Problem strukturell. Regression: fremder Wert mit
Control-Char → Ausgabe bleibt valides, wertgleiches TOML.

### AG3-175-R03 — MAJOR (Test-Substanz) — Die gelieferten Tests belegen die geforderten Matrizen nicht

**Ort:** `tests/unit/harness_client/test_codex_mcp_config_writer.py`,
`tests/contract/installer/test_dual_harness_mcp_registration.py`.

**Fakten-Beleg (Codex vor Abbruch):** Die Suite ist grün (`28 passed`),
bestätigt aber die geforderten Verträge nicht:
- der AC-5-"Probe"-Test ruft **keinen** Conformance-Check auf (geprobter ≠
  nachweislich geschriebener Spec);
- der Konflikt-Test enthält **keinen** belegten Fremd-belegt-eigener-Name-
  Konflikt;
- die Dual-/TOML-Matrix lässt u. a. `cwd`, Duplicate-Key/Table sowie
  Symlink/Junction aus.

Das ist dieselbe Klasse wie in AG3-174: Tests laufen an den echten Grenzen
vorbei und geben falsche grüne Sicherheit. (Duplicate-Key und Symlink/Junction
sind im Produktcode via `tomllib` bzw. `_assert_path_contained` **abgedeckt** —
nur eben nicht getestet.)

**Fix:** Tests an den ECHTEN Grenzen ergänzen:
- AC 5: real durch den AG3-164-Probe-Pfad; Post-Probe-Feldänderung
  (PROJECT_ID/Endpoint/cwd/env) blockt den Write am echten Pfad
  (`mcp_probe_binding_mismatch`);
- echter Fremd-belegt-eigener-Name-Konflikt → benannter Fehler, beide Dateien
  byte-identisch;
- Matrix um `cwd` (Typ/leer), Duplicate-Key/-Table, Symlink/Junction-Escape,
  ungültiges UTF-8 ergänzen — je benannter Fehler + beide Dateien byte-identisch;
- die R01/R02-Preservation-Fälle (fremdes datetime, array-of-tables, nested AoT,
  control-char-behafteter Wert) als dauerhafte Regressionen: Registrierung
  erfolgreich UND Ergebnis valides, wertgleiches TOML.

### AG3-175-N01 — NIT (Orchestrator-Feinschliff) — Digest koerziert env-Werte zu String

**Ort:** `bound_spec.py` `canonical_spec_digest` (60): `str(v)`.

Der Digest unterscheidet `env={'PORT':'1'}` nicht von `{'PORT':1}`. Praktisch
harmlos, weil `_validate_entry_types` einen nicht-String-env-Wert beim Write
ohnehin ablehnt. Der Vollständigkeit halber sollte der Digest keine Koerzierung
vornehmen (er soll Identität beweisen, nicht normalisieren). Kein Blocker.

## Gesamturteil

**Nachbessern.** R01 und R02 sind echte, reproduzierte Korrektheits-/
fail-closed-Blocker gegen AC 7: eine legitime fremde Codex-Config bricht die
Registrierung (R01) bzw. wird zu ungültigem TOML korrumpiert (R02). Beide haben
dieselbe Wurzel — der hand-gerollte Voll-Reserializer. R03 ist echte
Test-Substanz (die eine Runde muss die geforderten Matrizen wirklich beweisen).

**Muss der Umsetzer fixen (BLOCKER/MAJOR):** R01, R02, R03.
**Orchestrator-Feinschliff (NIT):** N01.

Sonst ist die Umsetzung tragfähig: der Writer ist grundsätzlich fail-closed
gebaut (strikte Entry-Typen, Userspace-Refusal, Containment/Symlink-Guard,
non-finite-Float-Ablehnung), die Digest-Bindung existiert, und die
Zwei-Dateien-Koordination trennt Render vor Write. Die Blocker liegen konkret
in der TOML-Serialisierungsstrategie.
