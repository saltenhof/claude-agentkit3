---
concept_id: META-DEC-2026-08-03-ERSTZUGANG-BOOTSTRAP
title: Concept-Decision-Record — Erstzugang und Startvertrauen
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to:
  - target: FK-01
    scope: trust-boundaries
    reason: Die lokale Maschinen-Trust-Boundary bleibt dort autoritativ
  - target: FK-15
    scope: secrets
    reason: Geheimnisklassen und Auth-Lebenszyklen bleiben dort autoritativ
  - target: FK-10
    scope: runtime-topology
    reason: Core-Topologie und Erstregistrierungsreihenfolge bleiben dort autoritativ
  - target: FK-91
    scope: api-catalog
    reason: Auth- und Installationsendpunkte sowie deren Idempotenz bleiben dort autoritativ
  - target: FK-72
    scope: ui-bff-topology
    reason: Die Ein-Prozess-Regel des UI-BFF bleibt dort autoritativ
supersedes: []
superseded_by:
tags: [meta, decision-record, security, bootstrap, credentials, AG3-180]
formal_scope: prose-only
---

# Concept-Decision-Record — Erstzugang und Startvertrauen

Datum: 2026-08-03. Record gemaess META-CONCEPT-CONSISTENCY P3/W4 fuer AG3-180.

## 1. Anlass

Eine leere AK3-Installation konnte kein Strategenpasswort produktiv anlegen.
Ohne Passwort gab es keine Session, ohne Session kein Projekt-Token und ohne
Projekt-Token keinen betriebsfaehigen Project-Edge. Tests hatten den fehlenden
Erstzugang durch direkte Passwortanlage verdeckt. Zugleich waren zwei
Geheimnisklassen unzureichend getrennt: das Strategenpasswort darf nie
persistenter Klartext sein, waehrend der Thin-Client sein Projekt-Token
notwendig im Klartext verwenden und deshalb lokal geschuetzt speichern muss.

## 2. Entscheidung

Der Strategen-Erstzugang ist eine atomare, einmalige lokale Core-CLI-Mutation.
Die anonyme HTTP-Bootstrap-Mutation entfaellt, weil ein HTTP-Server weder ein
echtes Terminal noch menschliche Kenntnis des gelieferten Passworts belegen
kann. Der Backend-Admin gibt das Passwort im interaktiven Terminal auf der
Core-Maschine zweimal ein; der lokale Credential-Owner persistiert nur dessen
Argon2id-Hash. Ein
betriebssystemspezifischer Prozess-Lock plus atomare Dateipublikation bestimmt
bei Konkurrenz genau einen Gewinner. Deshalb kann weder ein zweiter Gewinner
noch ueber die produktive Bootstrap-Oberflaeche ein maschinell erzeugtes, dem
Backend-Admin unbekanntes gueltiges Passwort entstehen.

Backend-Admin und Client-Bediener sind getrennte Rollen auf getrennten
Maschinen. Der authentifizierte Admin erzeugt das Projekt-Token mit
`<absolute-agentkit-wrapper> auth issue-token` kernseitig. Der Server erhaelt und persistiert nur
Token-ID und Hash; die Core-CLI gibt den Klartext nach der Registrierung einmal
aus und schreibt keine lokale ProjectEdge-Credential. Die Uebergabe an den
Client-Bediener liegt ausserhalb von AK3. Auf dem Entwicklerrechner prueft
`<absolute-agentkit-wrapper> auth store-token` den ausgehaendigten Bearer ueber einen read-only
HTTPS-Projektaufruf und publiziert ihn ohne Strategen-Login atomar als aktive
`.agentkit/credentials`. Ein Anforderungs- oder Genehmigungsworkflow wird nicht
eingefuehrt. Rotation wiederholt diese Uebergabe fuer das neue Token und endet
mit dem adminseitigen Widerruf der alten Token-ID.

Beide Geheimnisdateien muessen ihren Schutz wirksam belegen: auf POSIX Modus
`0600`, auf Windows eine vererbungsfreie DACL mit genau einem expliziten
`FullControl`-Allow fuer die aktuelle Benutzer-SID. Kann AK3 den Schutz nicht
setzen oder messen, wird das Geheimnis nicht verwendet. Geheimnis-verarbeitende
CLI-Verben verlangen stdin, stdout und stderr an einem Terminal; andernfalls
brechen sie vor Einlesen, Erzeugung oder Ausgabe des Geheimnisses ab.

## 3. Alternativen

- Ein serverseitig erzeugtes Erstpasswort wurde verworfen: ein Abbruch nach
  Speicherung, aber vor Anzeige, hinterliesse einen gueltigen unbekannten Hash
  ohne anmeldbaren Recovery-Weg.
- Ein Bootstrap ueber jede erreichbare Control-Plane-Adresse wurde verworfen:
  vor der ersten Authentisierung waere Erreichbarkeit gleich Administrator-
  Uebernahme.
- Eine auf Loopback begrenzte anonyme HTTP-Bootstrap-Route wurde ebenfalls
  verworfen: die Herkunft belegt lokalen Maschinenzugriff, aber weder ein
  interaktives Terminal noch die Kenntnis des Passworts durch den Bediener.
- Serverseitige Erzeugung und Rueckgabe des Projekt-Token-Klartexts wurde
  verworfen: die idempotente HTTP-Replay-Antwort wuerde selbst zum
  Geheimnisspeicher.
- Ein gemeinsamer pauschaler Satz „Geheimnisse liegen nie im Klartext“ wurde
  verworfen: er ist fuer Passwoerter richtig, macht aber ein verwendbares
  Bearer-Token auf dem Thin-Client unmoeglich.
- `chmod` als plattformuebergreifender Nachweis wurde verworfen: unter Windows
  belegt es keine wirksame Zugriffsbegrenzung.

## 4. Impact-Sweep (P3/W4)

Geprueft wurden FK-15 als Eigentuemer von Secrets und API-Auth, FK-01 als
Eigentuemer der Trust Boundaries, FK-10 fuer Core-Topologie,
Erstregistrierungsreihenfolge und Ablageorte, FK-91 fuer API-Katalog und
Idempotenz, FK-72 fuer die BFF-Prozesstopologie sowie ARCH-49 fuer das Verbot
von Secrets in normaler Konfiguration.
FK-15 trennt die Geheimnislebenszyklen und die beiden Personen: der Admin
bootstrapped und stellt kernseitig aus, der Client-Bediener speichert und nutzt
den ausgehaendigten Bearer ohne Strategenpasswort. Der Projektkontext besteht
kernseitig vor der Tokenausstellung; CP10d verwendet danach ausschliesslich die
bereits auf dem Laptop aktive Credential. FK-01 bleibt unveraendert: weil keine anonyme
HTTP-Bootstrap-Oberflaeche existiert, wird aus der lokalen Core-CLI-Mutation
keine globale Loopback-Pflicht abgeleitet; Loopback- und Remote-Core aus FK-10
bleiben beide nutzbar. `.agentkit/credentials` wird als explizite, eng
begrenzte Ausnahme zur absoluten Speicherformulierung in §15.5.1 und als
dedizierter Credential-Speicher statt allgemeiner Konfigurationsquelle
eingeordnet; beide normativen Aussagen nennen nun dieselbe Grenze. Der fruehere
`AGENTKIT_PROJECT_API_TOKEN`-Env-Vertrag entfaellt zugunsten dieser typisierten
Datei. FK-15 §15.8.1 trennt deshalb lokale Hilfsdienste von der in FK-10
autorisierten Loopback- oder dedizierten Server-Topologie des Core. Der
Replay-Vertrag schliesst nun auch den
Server-Crash nach Domain-Commit und
vor Claim-Finalisierung: ausschliesslich ein exakter Domain-State-Beleg darf
den passenden Orphan-Claim terminalisieren. Der Client serialisiert die
atomare Publikation der ausgehaendigten Credential und der Installer haelt
denselben OS-Prozesslock waehrend CP10d. Session-Erzeugung,
Validierung und Widerruf sind ueber beide Listener-Prozesse gemeinsam
synchronisiert. Sessions sind an die Passwortgeneration gebunden, abgelaufene
Records werden beim naechsten Zugriff bereinigt, und ein Fehler der physischen
Gesamtbereinigung nach Hash-Publikation laesst den Claim fuer Recovery stehen.
Passwort- und
Token-Idempotenz binden den Projektkontext; Passwortrotation und Tokenwiderruf
geben ihre wiederverwendbare `op_id` vor dem Request aus. Der idempotente
Logout-Replay bestaetigt bei fehlender Zielsitzung nur den bereits erreichten
Abmeldezustand und erweitert keine sonstige anonyme Mutationsoberflaeche. Das
persistierte Strategen-Credential ist schema-geschlossen auf `admin`,
Argon2id-PHC und bekannte Felder; `last_rotation_op_id` liefert zusammen mit
dem neuen Hash den operationsspezifischen Orphan-Recovery-Beleg. UI-BFF und
Project-API sind getrennt startbare REST-Endpunkte derselben Control-Plane-
Anwendung und teilen einen autoritativen, owner-only geschuetzten Session-Store
unter einem Prozess-Lock. Strategen-Login und administrative Auth-Routen sind
fuer Browser und Operator-CLI auf beiden Profilen erreichbar, waehrend
Project-Tokens dort principal-basiert verboten bleiben. FK-72 §72.8 bleibt
widerspruchsfrei: dessen Ein-Prozess-Regel gilt fuer die BC-aligned Module des
UI-BFF und zieht die Project-API nicht in denselben Prozess.
TLS-Startzertifikat, globale editierbare
Installation und Fremdinstallations-End-to-End-Lauf bleiben ausserhalb dieses
Records.

## 5. Betroffenheitsmatrix

| Stelle | Disposition | Begruendung |
|--------|-------------|-------------|
| FK-15 §15.5.1 | geaendert | Das allgemeine Speicherverbot und die beiden eng benannten Credential-Speicher werden ohne Widerspruch gemeinsam normiert. |
| FK-15 §15.8.1 | geaendert | Lokale Hilfsdienste bleiben lokal; der Core darf gemaess FK-10 auf Loopback oder als geschuetzter dedizierter Server binden. |
| FK-15 §15.10.2/§15.10.3 | geaendert | UI-BFF und Project-API werden als getrennt startbare Profile derselben Sicherheitsdomaene statt als Principal-Firewall klargestellt. Der Backend-Admin besitzt den lokalen interaktiven Core-CLI-Owner; atomare Einmaligkeit, Admin-Kenntnis, schema-geschlossene `admin`-/Argon2id-Ablage, Rechte, Abbruch, prozessuebergreifend gemeinsam synchronisierter Session-Widerruf, wiederverwendbare Rotations-`op_id` und operationsspezifisch beleggebundene Orphan-Recovery werden vollstaendig normiert; die anonyme HTTP-Mutation entfaellt. |
| FK-15 §15.10.4 | geaendert | Adminseitige kernlokale Tokenerzeugung und Einmalausgabe ohne Core-Credential werden von der ausserhalb AK3 liegenden Uebergabe und der laptopseitigen HTTPS-Pruefung/Publikation ohne Strategenpasswort getrennt. Rechte, Abbruch, Rotation und Revocation bleiben rollengetrennt. |
| FK-15 §15.10.5 | geaendert | Die HTTP-Ausnahmen, der seiteneffektfreie Logout-Replay bei bereits fehlender Zielsitzung und die sonst nur Strategen erlaubte Auth-Administrationsoberflaeche werden explizit ausgewiesen. |
| FK-01 Trust Boundaries | geprueft, nicht geaendert | Die lokale Maschinen-Trust-Boundary ist bereits autoritativ; FK-15 detailliert nur deren Auth-Anwendung. |
| FK-10 Core-Topologie, Hochfahrreihenfolge und Ablageorte | geprueft | Die Rollenentscheidung verlangt einen vor Tokenausstellung bestehenden Projektkontext und eine vor CP10d gespeicherte Laptop-Credential; die normative FK-10-Nachfuehrung liegt ausserhalb des AG3-180-R2-Mandats. |
| FK-72 §72.8 BFF-Topologie | geprueft, nicht geaendert | Die Ein-Prozess-Regel ordnet die BC-aligned Module innerhalb des UI-BFF. Die separat startbare Project-API bleibt der zweite FK-10-REST-Endpunkt; beide Prozesse teilen nur den autoritativen Auth-Zustandsowner. |
| FK-91 API-Katalog und Idempotenz | geprueft | `store-token` ist eine zweite lokale Credential-Owner-Ausnahme neben `bootstrap`; die normative FK-91-Katalogkorrektur liegt ausserhalb des AG3-180-R2-Mandats. Projektkontext bleibt Teil jeder serverseitigen Idempotenzidentitaet. |
| ARCH-49 Secrets | geprueft, nicht geaendert | Der dedizierte Credential-Speicher ist keine normale editierbare Konfiguration; serverseitig bleibt nur der Hash. |
| `src/agentkit/backend/auth/` und Auth-HTTP | geaendert | Lokaler CLI-Bootstrap, Prozess-Lock, statischer Principal-Vertrag, insert-only Tokenidentitaet, Rotation und Revocation setzen den Vertrag um. |
| `agentkit.shared`-Namespace und Deployment-Unit-Struktur | geaendert | Die unerlaubte sechste Deployment Unit entfaellt; Core-Dateirechte liegen in `backend/boundary/filesystem`, Edge-Dateirechte eigenstaendig in `harness_client/projectedge`. |
| ProjectEdge Credential-/Env-Vertrag | geaendert | `.agentkit/credentials` ersetzt `AGENTKIT_PROJECT_API_TOKEN`; fehlende, ungueltige und unsichere Zustaende werden fail-closed unterschieden, die ausgehaendigte Credential wird nach HTTPS-Pruefung atomar publiziert. |
| Auth-Autorisierungsoberflaeche | geaendert | Der authentifizierte Principal wird bis in die Auth-Routen getragen; Project-Tokens duerfen keine Strategen- oder Tokenadministration ausfuehren. |
| Architekturkonformitaets-Entities | geaendert | Der lokale CLI-Credential-Owner darf den Auth-Adapter aufrufen; der Auth-Adapter darf die Core-Dateirechte-Boundary fuer seinen Hash-Speicher verwenden. |
| CLI und Installer | geaendert | `issue-token` gibt nur aus, `store-token` prueft und speichert; `register-project` liest kein Strategenpasswort und verwendet die bereits aktive Credential. |
| Auth-, CLI- und Integrationsnachweise | geaendert | Fehlende anonyme HTTP-Bootstrap-Route auch ueber eine reale authentifizierte Nicht-Loopback-Anfrage, getrennte Admin-/Laptop-Prozesse und -Verzeichnisse, Zwei-Prozess-Bootstrap-Rennen, Rechte und Geheimniskanal werden belegt. |
| AG3-188, AG3-189, AG3-187 | nicht betroffen | TLS-Startzertifikat, globale editierbare Installation und Fremdinstallationslauf bleiben explizit ausser Scope. |
