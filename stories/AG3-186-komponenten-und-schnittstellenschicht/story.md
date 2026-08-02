# AG3-186 — Komponenten- und Schnittstellenschicht zwischen Prosa und Formal-Layer

- **Typ:** concept
- **Groesse:** L
- **Betroffen:** `concept/technical-design/`, `concept/formal-spec/`, `concept/_meta/`, FK-07
- **Herkunft:** PO-Vorgabe vom 2026-08-02, Blueprint aus dem Nachbarprojekt.

## Befund

AK3 kennt heute zwei Konzeptschichten: **Prosa** (Domaenen- und Fachkonzept) und
den **Formal-Layer**. Zwischen beiden fehlt eine Schicht, die der PO als
notwendig benannt hat und die im Nachbarprojekt bereits entsteht:

> Eine Zwischenschicht, die **Komponenten- und Schnittstellenbeschreibung**
> traegt, **von den Bounded Contexts abweichen darf** und **orthogonal** zu
> ihnen liegt — die Projektion darauf, **wie tatsaechlich in Repositories und
> Software-Artefakte geschnitten wird**.

**Was AK3 heute stattdessen hat:** die Codeprojektion existiert (FK-07 plus
Architektur-Checker), aber **kein Komponentenobjekt**. `module-registry.yaml`
ist eine flache Namensliste; Ports leben ausschliesslich in Prosa. Ein
Praezisionsboden fuer Schnittstellenvertraege waere damit nicht einmal
formulierbar.

**Der Blueprint hilft nur zur Haelfte** und das ist der wichtige Punkt: Dort ist
die Komponente **strikt kontextgebunden**, und die Codeprojektion ist
ausdruecklich ausgeklammert („eine benannte Grenze ist das Gegenteil einer
Luecke"). Der PO will genau die Flaeche, die der Blueprint offenlaesst. AK3 hat
umgekehrt die Codeprojektion und kein Komponentenobjekt. Die beiden Projekte
sind an dieser Stelle **komplementaer**, nicht deckungsgleich — der Blueprint
ist Anschlussstelle, nicht Vorlage.

Der Blueprint hat die Objektartenfrage in seinem §4.6 selbst offen und dem
Operator vorgelegt. Diese Story kann sie fuer AK3 beantworten, ohne auf das
Nachbarprojekt zu warten.

**Warum das jetzt zaehlt:** Der Sprung vom Konzept zur realen Repo-Struktur
passiert heute unausgesprochen. Jede Story, die etwas schneidet, trifft die
Entscheidung neu und begruendet sie im Kopf. Dieselbe Klasse Problem wie ueberall
sonst am 2026-08-02: eine Wahrheit ohne Eigentuemer.

## Akzeptanzkriterien

1. **Die Schicht ist als eigene Konzeptflaeche definiert**, mit Zweck,
   Abgrenzung nach oben (Prosa) und unten (Formal-Layer), und einer klaren
   Aussage, wovon sie NICHT handelt.
2. **Die Orthogonalitaet zu den Bounded Contexts ist ausgeschrieben**, nicht
   behauptet: an mindestens zwei realen Beispielen aus AK3, in denen der
   Repo-/Artefaktschnitt vom BC-Schnitt abweicht, und mit der Begruendung, warum
   die Abweichung richtig ist.
3. **Ein Komponentenobjekt existiert** — maschinenlesbar, mit Identitaet,
   Eigentuemer und Schnittstellen. Ein Bezeichner, der ausschliesslich in einem
   `owner:`-Feld vorkommt, ist kein Eigentuemer, sondern ein Etikett.
4. **Schnittstellenvertraege haben einen Mindestpraezisionsboden**, und der ist
   ausgeschrieben. Ein Port, der nur in Prosa existiert, erfuellt ihn nicht.
5. **Das Verhaeltnis zu FK-07 und zum Architektur-Checker ist geklaert:** was
   projiziert die neue Schicht, was prueft der Checker, und wo genau ist die
   Naht. Es entsteht **keine zweite Wahrheit** ueber den Repo-Schnitt.
6. **`module-registry.yaml` ist entweder abgeloest oder als das ausgewiesen, was
   es ist** — eine flache Namensliste, die den Vertrag nicht traegt.
7. **Der Blueprint ist ausgewertet und die Differenz benannt:** was uebernommen
   wird, was bewusst nicht, und wo AK3 weiter geht als das Nachbarprojekt (die
   Codeprojektion) beziehungsweise hinterherhinkt (das Komponentenobjekt).
8. Die Arbeit laeuft nach dem Verfahren aus AG3-185: Entwurf im Inkubator,
   unabhaengige mehrdimensionale Pruefung, Migration, Migrationstreue-Pruefung.
9. Alle deterministischen Konzept-Gates gruen; Decision Record mit
   Betroffenheitsmatrix.

## Abgrenzung

**Kein Code in dieser Story.** Es ist Konzeptarbeit; die Umsetzung eines
Registers oder Checkers folgt als eigene Story, wenn der Schnitt steht.

Keine Uebernahme des Blueprints als Ganzes — das Nachbarprojekt hat eine andere
Fachdomaene und eine andere Reifephase. Uebernommen wird der
projektunabhaengige Verfahrensanteil.

**Voraussetzung:** Diese Story braucht eine PO-Entscheidung auf
Meta-Konzeptebene, bevor sie beginnt — ob die Schicht ueberhaupt eingezogen wird
und mit welchem Anspruch. Ohne diese Pfosten waere jede Ausdetaillierung eine
neue Konzeptdomaene und damit ausserhalb des Agentenmandats.
