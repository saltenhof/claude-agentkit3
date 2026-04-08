Pipeline-Robustheitstests

  Für jede Komponente, die als Schritt in einer Pipeline, Workflow-Engine oder mehrstufigen Verarbeitungskette arbeitet, gilt:

  Jeder Pipeline-Schritt MUSS durch Tests nachweisen, dass er nicht nur den erwarteten Eingabezustand korrekt verarbeitet (Happy Path), sondern auch auf fehlerhafte, unvollständige oder fehlende Eingabezustände des vorgelagerten Schritts robust reagiert.

  Konkret:

  1. Negativpfade an jeder Phasengrenze: Für jeden Übergang von Schritt A nach Schritt B muss mindestens ein Test existieren, der prüft: Was passiert, wenn Schritt B aufgerufen wird, aber Schritt A nicht oder nicht vollständig abgeschlossen wurde? Der Test muss beweisen, dass Schritt B den Fehler erkennt und mit einem definierten Fehlerstatus reagiert (nicht stillschweigend durchläuft).
  2. Kein manuelles State-Setup als Ersatz für Pipeline-Flow: Tests dürfen den Eingabezustand eines Pipeline-Schritts nicht manuell zusammenbauen (z.B. per JSON in eine State-Datei schreiben), wenn dieser Zustand im Produktionsbetrieb durch den vorgelagerten Schritt produziert wird. State muss durch den tatsächlichen Aufruf des vorgelagerten Schritts entstehen. Fehlerzustände werden durch deterministische Manipulation
  der Artefakte (Dateien löschen, korrumpieren, Werte verfälschen) erzeugt — nicht durch direktes Setzen von Pipeline-internem State.
  3. Precondition-Enforcement nachgewiesen: Wenn ein Pipeline-Schritt dokumentierte Vorbedingungen hat (z.B. "Phase X muss abgeschlossen sein"), muss ein Test beweisen, dass der Schritt bei Verletzung dieser Vorbedingung ablehnt. Es reicht nicht, dass die Vorbedingung dokumentiert ist — sie muss im Code geprüft und durch einen Test verifiziert werden.
  4. Übergangsgraph vollständig verprobt: Wenn die Pipeline einen definierten Übergangsgraphen hat (erlaubte Transitionen zwischen Schritten), müssen sowohl alle gültigen als auch alle ungültigen Übergänge getestet sein. Für jeden ungültigen Übergang: Test, dass er abgelehnt wird. Für jeden gültigen Übergang: Test, dass er funktioniert.