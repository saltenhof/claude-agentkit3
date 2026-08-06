---
concept_id: META-DEC-2026-08-05-DELEGATIONSRICHTUNG
title: Concept-Decision-Record — Delegationsrichtung, etablierter Knoten und Kontextschonung des Orchestrators
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, delegation, project-edge, harness, orchestrator, review, FK-01, FK-21, FK-43, FK-45, FK-76, FK-91]
formal_scope: prose-only
---

# Concept-Decision-Record — Delegationsrichtung, etablierter Knoten und Kontextschonung des Orchestrators

Datum: 2026-08-05. Entscheider: Product Owner.

## 1. Anlass

Zwei normative Owner widersprachen sich darin, ob ein Agent die AK3-CLI direkt
aufrufen darf.

- **FK-45 §45.4 (`:352-355`)**: „Kein Agent darf die CLI direkt aufrufen. Agents
  greifen ausschliesslich ueber den `Project Edge Client` gegen die
  Control-Plane-API zu. Die CLI ist menschlicher und administrativer
  Adapterpfad." Der CLI-`run-phase` ist dort ausdruecklich **kein**
  Standard-Aufrufweg, sondern menschliche Operator-Recovery (`:329-332`).
- **FK-43 (`:470-472`, `:477-481`)**: Die produktiv konforme Skill-Variante
  bindet „die tatsaechlichen `run-phase`-Aufrufe an `{{AK3_WRAPPER}}`"; ebenso
  `export-story-md` in `lookup-userstory-core`. Skill-Bundles sind das, was ein
  Agent liest und ausfuehrt.
- **FK-21 (`:829-839`)** steht mit `export-story-md` im selben Konflikt.

Der Konflikt wurde durch AG3-189 nicht erzeugt, sondern **sichtbar gemacht**:
Vorher standen dort nackte `python -m …`-Aufrufe; nach der Interpreter-Isolation
stehen saubere Wrapper-Aufrufe — und dadurch faellt erst auf, dass der Aufruf
**als solcher** fragwuerdig ist.

### Die Rahmung war zunaechst falsch

Der Council-Orchestrator hatte die Frage als „Agent → Project Edge → API" gegen
„Agent → CLI" gestellt. Das war eine Fehlannahme ueber die Topologie. Der PO hat
sie korrigiert:

- Ein **Agent** ist die Kombination aus **Harness** und **LLM**. Das LLM laeuft
  cloudseitig; der **Harness laeuft auf der Client-Maschine** und uebersetzt
  LLM-Befehle in Betriebssystem-Instruktionen.
- Das **AK3-Backend ist kein Agent**.
- Der Server hat **keine direkte Schnittstelle** zu den Harness-Installationen
  auf fremden Rechnern. Er braucht **Project Edge als Relais**, um ueberhaupt
  delegieren zu koennen.

Damit ist der Verstoss kein Zugriffs-, sondern ein **Wegfehler**: Ein Bundle mit
`{{AK3_WRAPPER}} run-phase` schickt den Agenten ueber den **Adapter des
Menschen** statt ueber den Kanal, der fuer ihn gebaut ist.

### Der offene Punkt in FK-01

FK-01 (`:117-122`) sagt: „Die Kommunikation geht *immer* vom Arm aus … der Core
initiiert nie zur Dev-Seite." Eine Beauftragung von AK3 an einen lokalen
Review-Agenten ist damit in ihrer absoluten Form unvereinbar.

## 2. Entscheidung

**2.1 AK3 delegiert ausschliesslich an einen zuvor etablierten Knoten.**
Ein Knoten wird dadurch etabliert, dass der dort laufende Orchestrator-Agent
AK3 von sich aus aufgerufen hat — etwa mit der Umsetzung einer User Story. AK3
haelt daraufhin das Zustandsmodell; die Implementierungsagenten laufen lokal auf
diesem Knoten. **AK3 initiiert nie ins Blaue** und nie gegenueber einem Knoten
ohne bestehende Bindung.

**2.2 Innerhalb dieser Bindung darf AK3 zurueckdelegieren.** Weil die Beziehung
besteht, darf AK3 an denselben Knoten senden, dass dort Review-Agenten loslaufen
sollen. Das Relais ist Project Edge; einen anderen Weg zum Harness gibt es
nicht.

**2.3 Die Review-Beauftragung geht bewusst am Orchestrator vorbei.** Im
Normalfall bekommt der Orchestrator-Agent ueber die API zurueck „fuehre jetzt
dies aus" — genau dafuer existiert er. Die Review-Beauftragung ist davon
ausgenommen: Sie erreicht denselben Knoten, aber nicht denselben Agenten.

**2.4 Der Grund dafuer ist Kontextschonung, und er ist normativ.** Der
Orchestrator soll mit den Sparringsrunden **nicht belastet** werden. Sein
Kontext ist die knappe Ressource des gesamten Ablaufs; ein Orchestrator, der
jede Reviewrunde mitliest, verliert genau die Uebersicht, fuer die er da ist.

Dieser Satz steht hier, damit der Bypass nicht spaeter als „unnoetige zweite
Kante" wegoptimiert wird. Er ist keine Bequemlichkeit, sondern der Zweck.

**2.5 FK-45s Regel bleibt, praezisiert.** „Kein Agent darf die CLI direkt
aufrufen" gilt unveraendert. Die CLI ist der Adapterpfad des **Menschen**;
Agenten erreichen AK3 ueber Project Edge und werden ueber Project Edge erreicht.
Skill-Bundles duerfen einen Agenten daher **nicht** zu `{{AK3_WRAPPER}}`-Aufrufen
anweisen.

**2.6 FK-01s Absolutheit wird qualifiziert, nicht aufgegeben.** Der Core
initiiert nicht **gegenueber einem beliebigen** Entwicklerrechner und hat
weiterhin **keinen Dateisystem-Zugriff** auf ihn. Er darf gegenueber einem
**durch vorherigen Pull etablierten** Knoten initiieren, ausschliesslich ueber
das Relais und ausschliesslich fuer Delegationen, die bewusst am Orchestrator
vorbeigefuehrt werden.

## 3. Begruendung

**Warum nicht der einfachere Weg — alles ueber den Orchestrator?** Weil er
funktioniert und trotzdem falsch ist: Der Orchestrator wuerde jede Reviewrunde
durch seinen Kontext schleusen. Der Preis ist nicht Rechenzeit, sondern
Urteilsfaehigkeit an der Stelle, an der Ueberblick gebraucht wird.

**Warum nicht die CLI?** Sie laeuft als lokaler Prozess unter den Zugangsdaten
des **Operators**. Ein Agent, der sie aufruft, handelt unter fremder Identitaet
— genau die Trennung, die AG3-214 („Ein Writer, ein Vertrag") gerade etabliert
hat. Nach AG3-214 gehen mutierende CLI-Verben zwar ueber authentisiertes HTTPS
an den Writer, das urspruengliche Argument „der Agent umgeht die Control Plane"
traegt also nicht mehr. Das Identitaetsargument traegt weiter.

**Warum kein Kompromiss (lesende Aufrufe erlaubt, schreibende nicht)?** Eine
zusaetzliche Grenze, die im Zweifel niemand kennt. Der Weg ueber Project Edge
existiert fuer beide Richtungen; es gibt keinen Anlass, daneben einen zweiten zu
dulden.

## 4. Konsequenzen und Nachweise

1. Produktiv bindbare Skill-Bundles enthalten **keine** an den Agenten
   gerichteten `{{AK3_WRAPPER}}`-Aufrufe mehr. Wo ein Bundle den **menschlichen**
   Recovery-Pfad dokumentiert, ist das als solches kenntlich zu machen.
2. Fuer jede heute per CLI im Bundle beauftragte Faehigkeit muss ein
   Project-Edge-Weg existieren. Wo keiner existiert, ist das ein Befund mit
   Owner — kein Grund, den CLI-Aufruf zu belassen.
3. FK-01 traegt die Qualifizierung aus 2.6; die Formulierung „der Core
   initiiert nie" bleibt sonst unveraendert gueltig.
4. FK-45 behaelt seine Regel und benennt zusaetzlich die Gegenrichtung
   (AK3 → Project Edge → Agent) als vorgesehenen Weg.
5. FK-91 fuehrt den Delegationsvertrag der Gegenrichtung.
6. Der Nachweis ist ein Lauf, in dem eine Review auf dem etablierten Knoten
   startet, **ohne** dass der Orchestrator-Agent die Runde in seinem Kontext
   gesehen hat.

## 5. Impact-Sweep (P3/W4)

Gesucht wurde nach normativen Aussagen ueber (a) die Richtung des
Kommandokanals, (b) die Zulaessigkeit agentischer CLI-Aufrufe, (c) den Weg, auf
dem Arbeit den Harness erreicht.

Betroffen: FK-01 (Kommandokanal, Trust Boundary), FK-45 (CLI-Regel,
Pull-Modell §45.1.1), FK-43 (Skill-Bundle-Aufrufe), FK-21 (`export-story-md`),
FK-76 (Harness-Anbindung), FK-91 (API-/Ereignisvertrag der Gegenrichtung).

Nicht betroffen: FK-30 (Hook-Enforcement — Hooks sind OS-Prozesse mit
stdin/stdout und bleiben unveraendert CLI-basiert, FK-45 `:348`), FK-50
(Installer-Bootstrap ist Operator-Pfad).

### Korrektur des Impact-Sweeps (2026-08-05, nach AG3-224 R1)

**Dieser Sweep war unvollstaendig, und die urspruengliche Einordnung von FK-10
war falsch.** Statt der oben vermuteten sechs Dokumente sind **sechzehn**
betroffen.

Zusammensetzung, nachrechenbar gegen die Matrix in §6:

| Gruppe | Anzahl | Dokumente |
|---|---:|---|
| urspruenglich vermutet | 6 | FK-01, FK-21, FK-43, FK-45, FK-76, FK-91 |
| Korrektur einer Fehleinordnung | 1 | FK-10 |
| Sweep-Nachtrag Prosa | 8 | FK-02, FK-13, FK-15, FK-20, FK-26, FK-28, FK-49, FK-68 |
| Sweep-Nachtrag (`_meta`) | 1 | `concept/_meta/bc-cut-decisions.md` |
| **Sweep-Nachtrag formale Kommando-Signaturen** | **11** | `formal-spec/`: `deterministic-checks`, `escalation`, `exploration`, `installer`, `integrity-gate`, `principal-capabilities`, `story-creation`, `story-reset`, `story-split`, `story-workflow`, `telemetry-analytics` — je `commands.md` |
| **Nachfolgequalifizierung** | **1** | `_meta/decisions/2026-08-04-installationsisolation.md` |
| **Sweep-Nachtrag Fences und Diagramme** | **2** | FK-33 (ausfuehrbare Prosa-Beispiele ohne Akteur), FK-47 (Sequenzdiagramm mit direktem Agentenweg) |
| **Summe betroffen** | **30** | |
| geprueft, unveraendert | 1 | `formal-spec/guard-system/commands.md` — bereits als Operator-CLI qualifiziert |

**Die Zahl 16 war ebenfalls falsch** und stand hier bis zur zweiten
Reviewrunde. Sie war intern korrekt gegen die damalige Matrix und gegen den
tatsaechlichen Bestand trotzdem zu klein: Sie zaehlte nur die Dokumente, die
zum Zeitpunkt der Korrektur als betroffen **bekannt** waren, und ignorierte,
dass elf formale Kommando-Dokumente bereits geaendert worden waren.

**Das ist derselbe Fehler zum zweiten Mal, eine Ebene tiefer.** Zuerst wurde
ein Sweep aus der Erinnerung als Ergebnis formuliert; dann wurde seine
Korrektur gegen die eigene Matrix gerechnet statt gegen den Bestand. Beide Male
war die Zahl belegbar falsch und beide Male hat erst ein unabhaengiges Review
es gefunden.

Methode des Nachtrags-Sweeps (AG3-224 R1/R2): Suche ueber `concept/**` und
`guardrails/**`, Grundmenge **383 Dateien**, entlang von vier Musterfamilien —
Kommandorichtung/Initiative/Pull/Delegation, Agent+CLI/Wrapper/Bash/`run-phase`/
Export, Project Edge/Harness/Relais/etablierter Knoten/Operatorpfad,
Kontextschonung/Orchestrator-Bypass. Vereinigung der Kandidaten: 161 Dateien;
davon nach Kontextpruefung 16 betroffen.

**FK-10 ist betroffen**, entgegen der urspruenglichen Aussage. Die Begruendung
„die Lokalitaet aendert sich nicht, nur die Richtung einer Kante" war der
Fehler: Genau diese Kante steht in FK-10.

- `10_runtime_deployment_speicher.md:153-160` fuehrt die Prozesslandschaft
  `Orchestrator → Bash-Tool → CLI`.
- `:184-187` sagt, Harness-Sessions riefen Operationen ueber „CLI/Project-Edge"
  auf und Project-Edge/CLI werde durch „Agent via Bash-Tool oder Operator"
  gestartet.
- Dem Diagramm `:118-169` fehlt die Rueckdelegationskante
  Backend → Project Edge → Harness.

Das widerspricht FK-45 §45.4, FK-91 §91.1 und dem Relaisvertrag dieses Records.

**Die Lehre gehoert zum Record, nicht in eine Fussnote:** Ein Impact-Sweep, der
aus der Erinnerung entsteht, ist eine Hypothese. Er wurde hier als Ergebnis
formuliert und war zu 40 % falsch. Kuenftige Records fuehren den Sweep als
Suchergebnis mit Methode, oder sie kennzeichnen ihn als ungeprueft.

## 6. Betroffenheitsmatrix

| Dokument | Betroffen | Aenderung |
|---|---|---|
| FK-01 | ja | §Kommandokanal: Qualifizierung nach 2.6 — Initiative gegenueber etabliertem Knoten, weiterhin kein Dateisystem-Zugriff |
| FK-45 | ja | CLI-Regel bleibt; Gegenrichtung AK3 → Project Edge → Agent wird als vorgesehener Weg benannt; Verhaeltnis zu §45.1.1 (Pull) geklaert |
| FK-43 | ja | Skill-Bundles weisen Agenten nicht zu Wrapper-Aufrufen an; menschliche Recovery-Pfade werden als solche kenntlich |
| FK-21 | ja | `export-story-md` analog |
| FK-76 | ja | Harness-Anbindung: Project Edge als Relais beider Richtungen |
| FK-91 | ja | Delegationsvertrag der Gegenrichtung |
| FK-10 | **ja** (Korrektur) | Prozesslandschaft `:153-160` fuehrt `Orchestrator → Bash-Tool → CLI`; `:184-187` laesst Agenten CLI/Project-Edge starten; dem Diagramm `:118-169` fehlt die Rueckdelegationskante |
| FK-02, FK-13, FK-15, FK-20, FK-26, FK-28, FK-49, FK-68 | **ja** (Sweep-Nachtrag) | Aussagen zu Aufrufweg bzw. Kommandorichtung; auf Project Edge oder ausdruecklich menschliche CLI-Recovery qualifiziert |
| `_meta/bc-cut-decisions.md` | **ja** (Sweep-Nachtrag) | Owner-Schnitt praezisiert: Trust Boundary → FK-01, Wirevertrag → FK-91, Harness-Topologie → FK-76; setzt keine zweite Richtungsregel |
| `formal-spec/`: `deterministic-checks`, `escalation`, `exploration`, `installer`, `integrity-gate`, `principal-capabilities`, `story-creation`, `story-reset`, `story-split`, `story-workflow`, `telemetry-analytics` — je `commands.md` (**11**) | **ja** (Sweep-Nachtrag Signaturen) | 17 von 18 Wrapper-Signaturen nannten keinen Akteur. Alle qualifiziert als menschlicher/administrativer Operator-CLI-Pfad; `WRAPPER_UNQUALIFIED=0` |
| `_meta/decisions/2026-08-04-installationsisolation.md` | **ja** (Nachfolgequalifizierung) | Historische Aussagen bleiben; ergaenzt um Verweis auf diesen Entscheid — der Record entscheidet Interpreter-/Wrapperisolation, nicht die Akteursfrage |
| FK-33 | **ja** (Sweep-Nachtrag Fences) | Drei ausfuehrbare Wrapper-Aufrufe unter „CLI-Integration" ohne Akteur; als Operator-CLI-Pfad qualifiziert |
| FK-47 | **ja** (Sweep-Nachtrag Diagramme) | Sequenzdiagramm zeichnete `C (Client/Orchestrator) → Backend` direkt, waehrend Project Edge separater Teilnehmer war |
| `formal-spec/guard-system/commands.md` | nein (geprueft) | Signatur war bereits als Operator-CLI qualifiziert |
| FK-30 | nein | Hooks bleiben OS-Prozesse, unveraendert CLI-basiert |
| FK-50 | nein | Installer ist Operator-Pfad |

**Summe betroffen: 30 Dokumente** — 6 + 1 (FK-10) + 8 (Prosa) + 1 (`bc-cut-decisions`)
+ 11 (formale Signaturen) + 1 (Nachfolgequalifizierung) + 2 (FK-33, FK-47).
Die Zahl stimmt mit der Zusammensetzung in §5 ueberein; beide sind gegen den
tatsaechlich geaenderten Bestand gerechnet, nicht gegeneinander.

## 7. Offene Punkte

- Die Umsetzung ist noch nicht erfolgt. Sie ist als Story erfasst; dieser Record
  verankert die Entscheidung, nicht ihre Ausfuehrung.
- Ob fuer **jede** heute im Bundle per CLI beauftragte Faehigkeit bereits ein
  Project-Edge-Aequivalent existiert, ist ungeprueft. Fehlt eines, ist es zu
  bauen (Konsequenz 2), nicht zu umgehen.
