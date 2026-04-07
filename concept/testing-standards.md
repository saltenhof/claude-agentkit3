# Teststandards — AgentKit v3

Verbindlich fuer alle Agents und Entwickler. Verstoesse sind Deliverable-Blocker.

---

## 1. Pipeline-Robustheitstests

Fuer jede Komponente, die als Schritt in der Pipeline, Workflow-Engine oder
mehrstufigen Verarbeitungskette arbeitet, gilt:

Jeder Pipeline-Schritt MUSS durch Tests nachweisen, dass er nicht nur den
erwarteten Eingabezustand korrekt verarbeitet (Happy Path), sondern auch auf
fehlerhafte, unvollstaendige oder fehlende Eingabezustaende des vorgelagerten
Schritts robust reagiert.

### 1.1 Negativpfade an jeder Phasengrenze

Fuer jeden Uebergang von Schritt A nach Schritt B muss mindestens ein Test
existieren, der prueft: Was passiert, wenn Schritt B aufgerufen wird, aber
Schritt A nicht oder nicht vollstaendig abgeschlossen wurde?

Der Test muss beweisen, dass Schritt B den Fehler erkennt und mit einem
definierten Fehlerstatus reagiert — nicht stillschweigend durchlaeuft.

### 1.2 Kein manuelles State-Setup als Ersatz fuer Pipeline-Flow

Tests duerfen den Eingabezustand eines Pipeline-Schritts nicht manuell
zusammenbauen (z.B. per JSON in eine State-Datei schreiben), wenn dieser
Zustand im Produktionsbetrieb durch den vorgelagerten Schritt produziert wird.

State muss durch den tatsaechlichen Aufruf des vorgelagerten Schritts
entstehen. Fehlerzustaende werden durch deterministische Manipulation der
Artefakte erzeugt:

- Dateien loeschen
- Dateien korrumpieren
- Werte verfaelschen

Nicht durch direktes Setzen von Pipeline-internem State.

### 1.3 Precondition-Enforcement nachgewiesen

Wenn ein Pipeline-Schritt dokumentierte Vorbedingungen hat (z.B. "Phase X
muss abgeschlossen sein"), muss ein Test beweisen, dass der Schritt bei
Verletzung dieser Vorbedingung ablehnt.

Es reicht nicht, dass die Vorbedingung dokumentiert ist — sie muss im Code
geprueft und durch einen Test verifiziert werden.

### 1.4 Uebergangsgraph vollstaendig verprobt

Wenn die Pipeline einen definierten Uebergangsgraphen hat (erlaubte
Transitionen zwischen Schritten), muessen sowohl alle gueltigen als auch
alle ungueltigen Uebergaenge getestet sein.

- Fuer jeden **ungueltigen** Uebergang: Test, dass er abgelehnt wird.
- Fuer jeden **gueltigen** Uebergang: Test, dass er funktioniert.

---

## 2. Allgemeine Testprinzipien

### 2.1 Qualitaet vor Quantitaet

Jeder Test hat eine klare, benennbare Aussage. Keine redundanten
Happy-Path-Varianten. Kein Test ohne erkennbaren Mehrwert.

### 2.2 Modular ausfuehrbar

Jedes Modul hat eine eigenstaendige Testsuite. `pytest tests/unit/config/`
muss in Sekunden laufen, ohne Abhaengigkeiten zu anderen Modulen.
Die Gesamtsuite laeuft nur in CI oder auf explizite Anforderung.

### 2.3 Vier Testebenen

| Ebene | Verzeichnis | Geschwindigkeit | Zweck |
|---|---|---|---|
| Unit | `tests/unit/` | Sekunden | Reine Logik, keine I/O |
| Integration | `tests/integration/` | Minuten | Simulierte Zielprojekte, echte Dateisystem-Ops |
| Contract | `tests/contract/` | Sekunden | Schema-Stabilitaet, Snapshot-Vergleiche |
| E2E | `tests/e2e/` | Minuten-Stunden | Echtes Deployment + Pipeline-Durchlauf |

### 2.4 E2E = echtes Deployment

E2E-Tests sind keine Unit-Tests mit mehr Scope. Sie testen den realen
Betriebspfad:

1. AgentKit in ein simuliertes Zielprojekt installieren
2. Pipeline gegen eine Fixture-Story laufen lassen
3. Ergebnis-Artefakte pruefen

Das simulierte Zielprojekt entsteht in `tests/integration/target_project_sim/`.
Es wird durch den tatsaechlichen Install-Pfad erzeugt, nicht manuell aufgebaut.

### 2.5 Marker-basierte Selektion

```python
@pytest.mark.slow          # Langsame Tests
@pytest.mark.requires_git  # Braucht echtes Git-Repo
@pytest.mark.requires_gh   # Braucht GitHub CLI
@pytest.mark.integration   # Integrationstests
@pytest.mark.contract      # Contract/Snapshot-Tests
@pytest.mark.e2e           # End-to-End gegen Live-Systeme
```

### 2.6 Keine Mocks ausser bei technischer Notwendigkeit

Mocks sind nur bei externer I/O erlaubt (HTTP-Calls, Git-Operationen),
die in Unit-Tests nicht ausfuehrbar sind. Minimum-Prinzip: nur das
Noetigste mocken, bevorzugt Integrationstests ohne Mocks.
