Komponenten-Design und -Schnitt
ARCH-01 Schneide Komponenten entlang fachlicher Domaenengrenzen, nicht technischer Schichten.

ARCH-02 Fachlichkeit ist die primaere Ordnung. Jede Geschaeftsregel hat genau eine autoritative Stelle.

ARCH-03 Keine zirkulaeren Abhaengigkeiten zwischen Komponenten. Ausnahmslos.

ARCH-04 Jede fachliche Entitaet hat ein klar definiertes fuehrendes System (Single Source of Truth).

ARCH-05 Keine God-Klassen. Jede Service-Methode hat einen klaren, abgegrenzten Auftrag.

Schnittstellen-Design (APIs, Contracts)
ARCH-06 Schnittstellen definieren Vertraege, nicht Implementierungen.

ARCH-07 Remote-Schnittstellen haben einen expliziten Versionierungsmechanismus ab Tag 1.

ARCH-08 Schnittstellen sind minimal: exponiere das Notwendige, nie das Moegliche.

ARCH-09 Idempotenz als Default fuer alle zustandsveraendernden Schnittstellen.

ARCH-10 APIs exponieren dedizierte externe Datenstrukturen, nie das interne Datenmodell 1:1.

ARCH-11 Standardisierte Fehler-Contracts (z.B. RFC 7807) fuer externe APIs.

Verantwortlichkeiten und Zustaendigkeiten
ARCH-12 Orchestrierung und Geschaeftslogik grundsaetzlich getrennt. Transaktionssteuerung gehoert in die Orchestrierungsschicht.

ARCH-13 Cross-Cutting Concerns per Middleware/Decorator/Aspekt. Ausnahme: inline-Logging ist erlaubt.

ARCH-14 Domaenenbegriffe explizit modellieren statt in Strings, Flags und if-Ketten zu verstecken.

Fehlerhandling
ARCH-15 Fehler in zwei Klassen: behebbar (Retry, Fallback) vs. nicht-behebbar (Propagation).

ARCH-16 Fail fast bei ungueltigen Invarianten intern. Fail safe bei externen Unsicherheiten.

ARCH-17 Fehler dort behandeln, wo die Entscheidungskompetenz liegt.

ARCH-18 Fehler anreichern, nicht ersetzen. Root-Cause erhalten.

ARCH-19 Jeder Catch-Block hat eine klare Absicht. Silent-Catches vermeiden.

ARCH-20 Fachliche Fehler via Return-Types (Result/Either). Exceptions nur fuer Systemfehler.

ARCH-21 Technische Exceptions an Systemgrenzen in fachliche Fehlercodes transformieren.

ARCH-54 Fehler-Grenzen architektonisch definieren (Quasar-Konzept: Sicherheitsfassade an der Grenze der Risikogemeinschaft).

Abhaengigkeiten und Kopplung
ARCH-22 Code-Blutgruppen: A-Code (Fachlogik), T-Code (Infrastruktur), R-Code (Adapter), Null-Code (Utilities). AT-Code minimieren.

ARCH-23 Strategische Dependencies (z.B. Spring) duerfen sichtbar sein. Austauschbare Libraries hinter Abstraktion wrappen.

ARCH-24 Transitive Abhaengigkeiten nicht zweckentfremden. Explizit deklarieren.

ARCH-25 Temporal Coupling vermeiden: keine implizite Reihenfolge.

ARCH-26 Runtime-Abhaengigkeiten per DI (Constructor Injection bevorzugt), Factory oder Service Registry.

ARCH-27 Kein verteilter Monolith. Synchron gekoppelte, gemeinsam deployte Services sind schlimmer als ein Monolith.

ARCH-28 Design for Deletability: Loeschbarkeit ueber generische Wiederverwendbarkeit.

Datenfluss und Zustandsmanagement
ARCH-29 Immutability als Default. Mutation nur in dedizierten State-Ownern.

ARCH-30 Unidirektionaler Datenfluss. Bidirektionaler Flow erfordert Begruendung.

ARCH-31 Seiteneffekte an die Raender. Kern-Transformationen als reine Funktionen.

ARCH-32 Commands und Queries trennen (CQS). Leseoperationen mutieren nicht.

Testbarkeit
ARCH-33 Jede Komponente testbar ohne Produktiv-Instanzen ihrer Abhaengigkeiten.

ARCH-34 Test-Pyramide einhalten. Architektur muss Unit-Tests auf Komponentenebene ermoeglichen.

ARCH-35 Teste beobachtbares Verhalten und Vertraege, nicht private Details.

ARCH-36 Zeit und Zufall als injizierbare Abhaengigkeiten isolieren.

Erweiterbarkeit und Wartbarkeit
ARCH-37 DRY gilt fuer Fachlogik, nicht fuer zufaellig identische Strukturen.

ARCH-38 Deprecated Code mit Deadline versehen und dann hart loeschen.

ARCH-39 Jede Abstraktion durch reale Anwendungsfaelle gerechtfertigt. Keine spekulativen Abstraktionen.

Synchrone vs. Asynchrone Patterns
ARCH-40 Synchron als Default. Asynchronitaet nur bei I/O-Bound, Lifecycle-Entkopplung oder Fire-and-Forget.

ARCH-41 Events sind Fakten, Commands sind Wuensche. Nicht vermischen.

ARCH-42 Asynchrone Kommunikation braucht explizite Delivery-Garantien und Idempotency-Keys.

ARCH-43 Timeouts und Deadlines an Prozess- und Verteilungsgrenzen.

ARCH-44 Backpressure explizit designen. Unbegrenzte Queues sind ein Fehler.

ARCH-45 Events schema-validiert in den Broker schreiben.

ARCH-46 Outbox-Pattern fuer gleichzeitiges Schreiben in DB und Message Broker.

Sicherheit
ARCH-47 Input-Validierung am Systemrand: Parse, don’t validate.

ARCH-48 Defense in Depth auf mehreren Ebenen. Default = Deny.

ARCH-49 Secrets nie in Code, Config-Dateien oder Container-Images.

Konfiguration
ARCH-50 Nur tatsaechlich variable Werte in die Konfiguration. Fachlich feststehende Konstanten duerfen im Code stehen.

ARCH-51 Konfigurationswerte haben klare Semantik, Wertebereich und sinnvolle Defaults. Fehlende Config = Startfehler.

ARCH-52 Environments unterscheiden sich nur in Konfiguration, nie im Code.

Beobachtbarkeit
ARCH-53 Correlation-IDs an der Systemgrenze erzeugen und ueber alle Komponentengrenzen propagieren.

