# AG3-185 — Agentisches Konzeptpruefverfahren normieren

- **Typ:** implementation
- **Groesse:** L
- **Betroffen:** FK-78, `concept/_meta/konzept-konsistenz-governance.md`, `AGENTS.md`, `concept-incubator/`
- **Herkunft:** PO-Entscheidungen vom 2026-08-02; Entwurf liegt in `concept-incubator/konzeptpruefung-verfahren/workspace/` (Commit `fb38a9e7`).

## Befund

Die Konzeptpruefung wird umgestellt: weg von LLM-Hub-Gates, an die
Konzeptanteile geschickt werden in der Hoffnung auf saubere Modellantworten, hin
zu nativen KI-Agenten ueber die Harness-Bridge, denen von aussen nur Leitplanken,
Ziele und Nachweispflichten vorgegeben werden.

**Der Anlass war Erfuellbarkeit, nicht Bequemlichkeit.** Die W2/W3-Pre-Merge-
Pflicht war nicht erfuellbar: ein reproduzierbarer `HUB_UNREACHABLE` oberhalb
einer Partitionsgroesse von 35 666 Zeichen und ein fehlender Retry in
`collect_scope_findings`, der einen kompletten Sweep an einem einzigen
nicht-woertlichen Modellzitat beendet. Eine Regel, die dasteht und nicht
erfuellbar ist, erzieht zur stillen Umgehung — in AG3-179 Runde 1 ist genau das
passiert („alle Konzept-Gates gruen", obwohl nur die statischen liefen).

**Was am 2026-08-02 schon verankert ist** (`AGENTS.md`, Commits `273c8bac`,
`19747fea`): die Aussetzung der Pflicht, die drei Pruefachsen der unabhaengigen
Agentenvorlage, und das Agentenmandat — frei in Strategie und Handeln, nicht in
Ziel und Leitplanken; neue normative Inhalte nur als Ausdetaillierung eines
groeber definierten Inhalts mit benennbarer Ankerstelle, ohne Widerspruch, ohne
neue Konzeptdomaene; fehlt der Anker, holt der Agent den PO.

**Was fehlt: die normative Nachfuehrung.** `AGENTS.md` ist lokale
Agenteninstruktion, kein Konzeptdokument. FK-78 §78.14 sagt weiterhin „LLM nur
als Bewertungsfunktion, kein Werkzeug entscheidet frei" ohne die ratifizierte
Praezisierung, und `konzept-konsistenz-governance.md` §6 fuehrt die
Betriebspflicht unveraendert.

**Der Entwurf liegt vor** und enthaelt zwoelf Befunde. Die wichtigsten:

- **Die Migrationstreue-Pruefung fehlt nicht**, wie zunaechst berichtet. Sie ist
  in DK-16 §6 und FK-78 §78.10/§78.11 normiert und in `promotion_check.py`
  implementiert, inklusive Diff-Hunk-Reverse-Trace. Was fehlt, ist enger: sie
  haengt am Atom-Register eines `FULL_ATOM`-Laufs, es gibt keine leichte
  Freigabebasis und keinen Auftragsvertrag fuer den pruefenden Agenten — und sie
  ist im AK3-Korpus **noch nie durchgelaufen**.
- **`interface` ist ein falscher Freund.** Im Blueprint ist `schnittstelle/`
  eine Tracking-Grenze, kein Reviewgate. Dazu eine Layoutkollision: FK-78
  schneidet lauf-orientiert, Blueprint und PO themen-orientiert.
- **Drei importfaehige Bausteine fehlen AK3:** `gap_class` (ohne sie ist „wir
  haben die Luecke benannt" ein Freifahrtschein), der **kalte
  Implementierbarkeitstest** (das einzige Werkzeug, das Abwesenheit findet,
  waehrend jedes AK3-Gate nur vorhandene Aussagen prueft), und **Freigabe-
  kriterien fuer `status: active`** (ohne sie ist eine Freigabe eine Meinung).
- **Konstruktiver Gegenbefund:** Der Request-Pack-/Receipt-Vertrag aus FK-78
  §78.14 ist ausfuehrerneutral, `spawn_mode` kennt `harness-bridge` bereits. Der
  Wechsel Hub → Bridge ist ein **Adaptertausch, kein Verfahrenswechsel**.

## Akzeptanzkriterien

1. **Der Entwurf geht durch das Verfahren, das er beschreibt** — mehrdimensionale
   unabhaengige Pruefung, danach Migration in die Norm, danach eine
   Migrationstreue-Pruefung. Nicht per Direkteintrag. Es waere eine schlechte
   Pointe, ausgerechnet die Regel „nicht direkt in die Norm schreiben" per
   Direkteintrag zu normieren.
2. **FK-78 §78.14 traegt die ratifizierte Praezisierung** des Agentenmandats im
   Wortlaut, den `AGENTS.md` seit 2026-08-02 fuehrt. Kein Widerspruch mehr
   zwischen Konzept und Agenteninstruktion.
3. **`konzept-konsistenz-governance.md` §6 ist nachgezogen**, mit Decision
   Record und Betroffenheitsmatrix (der Wortlaut liegt im Entwurf `B`).
4. **Die Migrationstreue-Pruefung ist einmal wirklich gelaufen**, auf einem
   echten Aenderungssatz dieses Korpus. Eine normierte und implementierte
   Mechanik, die nie benutzt wurde, ist praktisch eine Behauptung.
5. **Es gibt eine leichte Freigabebasis** fuer kleine additive Aenderungen, ohne
   `FULL_ATOM`-Lauf — oder eine begruendete Feststellung, warum jede
   Konzeptaenderung den vollen Lauf braucht.
6. **Der Auftragsvertrag des pruefenden Agenten ist ausgeschrieben:** Ziel,
   Leitplanken, Nachweispflichten, Abbruchkriterien. Er waehlt seine Strategie
   selbst; was er schuldet, steht fest.
7. **Die drei Bausteine sind entschieden** — `gap_class`, kalter
   Implementierbarkeitstest, Freigabekriterien fuer `status: active`: jeweils
   uebernommen und normiert, oder mit Begruendung verworfen.
8. **Die Layout- und Begriffsfrage ist geklaert** (`workspace`/`interface` vs.
   FK-78-Begriffe, Thema-aussen vs. Lauf-aussen). Eine dritte Benennung fuer
   dieselbe Sache entsteht dabei nicht.
9. **Die acht offenen Entscheidungen aus Entwurf `D` sind beantwortet** — vom PO,
   wo sie ihm gehoeren; vom Umsetzer mit Begruendung, wo sie technisch sind.
   Insbesondere: wird ruhender Bestand weiter geprueft? Das neue Verfahren folgt
   der Aenderung und sieht ihn sonst nie wieder an.
10. Alle deterministischen Konzept-Gates gruen; W4-Decision-Record vorhanden.

## Abgrenzung

Kein Bau der Hub-Ersatzmechanik ueber das hinaus, was der Adaptertausch
erfordert. Kein Retry-Vertrag fuer W2/W3 — das Verfahren wird ersetzt, nicht
repariert (PO-Entscheidung 2026-08-02).

Die Komponenten-/Schnittstellenschicht ist eigene Arbeit (AG3-186).
