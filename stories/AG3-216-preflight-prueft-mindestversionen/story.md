# AG3-216 — Der Preflight prueft Importierbarkeit, nicht Erfuellbarkeit

- **Typ:** implementation
- **Groesse:** S
- **Abhaengigkeiten:** `depends_on: ["AG3-206"]`
- **Quell-Konzept:** FK-50 (Installer, Eingangsgrenze)
- **Herkunft:** Nebenbefund am 2026-08-04 aus der Sonar-Remediation. Ein
  Sub-Agent bemerkte beim Pruefen eines S930-False-Positives, dass der Code
  eine API benutzt, die die Deklaration nicht zusagt.

## Befund — belegt

`src/agentkit/backend/auth/http/routes.py:766` ruft
`ValidationError.errors(include_input=False, include_url=False)`. Das ist der
AG3-180-Sicherheitsfix, der verhindert, dass ein Geheimnis ueber `input` in
eine HTTP-Fehlerantwort gelangt.

Die Deklaration sagte `pydantic>=2.0`. Das Schluesselwort `include_input`
existiert dort nicht. Unter einer zulaessigen, aber zu alten Version haette der
Sicherheitsfix einen `TypeError` geworfen statt zu redigieren.

Empirisch geklaert und am 2026-08-04 als `5db51bea` behoben: 2.0.3 laesst sich
auf Python 3.14 nicht einmal bauen, 2.1.0 hat kein Wheel, 2.12.0 traegt die
Signatur nachweislich. Untergrenze steht jetzt auf `>=2.12`.

**Der Einzelfall ist behoben. Die Luecke, die ihn moeglich gemacht hat, nicht.**

## Warum das AG3-206 unmittelbar betrifft

AG3-206 hat gerade festgeschrieben: *die Deklaration ist die einzige
Paketwahrheit.* Ihr Preflight leitet den Pflichtsatz aus `pyproject.toml` ab
und prueft ihn, bevor irgendetwas laeuft — er prueft aber nur, ob die Pakete
**importierbar** sind, nicht, ob die installierte Version den deklarierten
Bereich **erfuellt**.

Damit gilt der Satz nur halb. Eine Deklaration, die eine Untergrenze nennt, die
niemand durchsetzt, ist eine Aussage ohne Wirkung — und der Fall oben zeigt,
dass sie sicherheitsrelevant sein kann.

Die Umkehrung ist genauso teuer: Wer eine Untergrenze anhebt, weil der Code
eine neuere API braucht, hat heute keinen Mechanismus, der eine veraltete
Umgebung findet. Er erfaehrt es zur Laufzeit, an der Stelle, an der die API
fehlt — im Zweifel in einem Fehlerpfad, den niemand fahrt.

## Scope

### In Scope

- Der Runtime-Preflight prueft die **installierte Version** jedes deklarierten
  Pflichtpakets gegen den deklarierten Bereich (Unter- **und** Obergrenze; das
  Repo pinnt beidseitig, siehe `mcp>=1.2.0,<2` und `weaviate-client>=4.9,<5.0`).
- Verletzung ist fail-closed ein Fehler mit Paketname, gefundener Version,
  gefordertem Bereich und dem Kommando, das es korrigiert — dieselbe
  Diagnosequalitaet wie beim fehlenden Paket (AG3-206 AC 1).
- Exakte Pins (`tokenizers==0.21.0`, `tomlkit==0.15.1`) werden mitgeprueft; bei
  ihnen ist Drift besonders teuer, weil sie bewusst gesetzt wurden.

### Out of Scope

- Keine Aenderung an bestehenden Versionsgrenzen. Diese Story setzt durch, was
  deklariert ist; sie bewertet die Grenzen nicht neu.
- Kein Aufloesen transitiver Abhaengigkeiten. Geprueft wird der deklarierte
  Pflichtsatz, nicht der volle Baum.

## Akzeptanzkriterien

1. **Eine zu alte Version bricht den Preflight**, mit Paketname, gefundener
   Version, gefordertem Bereich und Beschaffungskommando. Nachgewiesen an einer
   echten Wegwerf-Umgebung mit genau einer unterschrittenen Grenze — nicht
   simuliert (AG3-206 hat den Massstab gesetzt: zwei Wegwerf-venvs, real
   gefahren).
2. **Eine zu neue Version bricht ebenso**, wo eine Obergrenze deklariert ist.
   Ein Bereich, der nur nach unten durchgesetzt wird, ist halb durchgesetzt.
3. **Der Nachweis laeuft gegen die Deklaration, nicht gegen eine Liste.** Eine
   geaenderte Grenze in `pyproject.toml` wirkt ohne Codeaenderung — dieselbe
   Regel wie AG3-206 AC 2, aus demselben Grund.
4. **Der belegte Anlassfall ist als Regressionstest gedeckt:** eine Umgebung,
   in der `pydantic` die deklarierte Untergrenze unterschreitet, wird
   abgewiesen, bevor die Auth-Oberflaeche startet.
5. **Volle Suite gruen** (Jenkins), `ruff`, `mypy --strict`, alle
   deterministischen Konzept-Gates. FK-50 nachgezogen, wo die Eingangsgrenze
   beschrieben ist; Decision Record nur, falls die Norm sich aendert.

## Definition of Done

- AC 1-5 erfuellt, jedes mit benanntem Beleg (Kommando, Ausgabe, Testname).
- Coverage haelt die 85-%-Schwelle.
- Unabhaengiges Codex-Review bis zum Abbruchkriterium aus `CLAUDE.md`.

## Guardrail-Referenzen

- `CLAUDE.md` „FAIL-CLOSED" — eine unerfuellte Deklaration ist ein
  unvollstaendiger Zustand, kein Grenzfall
- `CLAUDE.md` „SINGLE SOURCE OF TRUTH IST PFLICHT" — die Deklaration ist die
  Paketwahrheit oder sie ist es nicht
- `CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" — AC 1 und AC 2
  gegen echte Umgebungen, nicht gegen Attrappen
