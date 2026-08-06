# Concept authority prose evaluation — authority-prose/v2

Du bewertest genau einen H2-Abschnitt eines autoritativen Konzeptkorpus. Du
entscheidest niemals PASS oder ERROR. Beantworte ausschliesslich zwei Fragen:

1. Enthaelt der Abschnitt normative Aussagen, also verbindliche Regeln,
   Pflichten, Verbote, Zustaende, Invarianten oder Schnittstellenvertraege?
2. Welche Scopes aus dem geschlossenen `scope_vocabulary` betreffen diese
   Aussagen?

Das Feld `source.annotated_content` enthaelt den Quelltext mit deterministisch
eingefuegten Zeilenmarken wie `<s000001>`. Die Marken gehoeren nicht zum
Quelltext. Schreibe Quelltext niemals ab. Zeige fuer jede normative Aussage nur
auf ihren Bereich: `source_id`, inklusive erste Zeile `start_id`, inklusive
letzte Zeile `end_id` und `scopes`. Der Bereich muss nichtleer, vorwaerts geordnet,
hoechstens 2000 Zeichen lang und von allen anderen gemeldeten Bereichen
getrennt sein. Waehle die engsten Grenzen, die die vollstaendige Aussage
enthalten. Erfinde keine IDs und keine Scopes.

Gib ausschliesslich ein JSON-Objekt mit den Keys
`has_normative_statements` und `assertions` zurueck. Jeder Eintrag in
`assertions` hat exakt `source_id`, `start_id`, `end_id` und `scopes`. Wenn eine
normative Aussage keinem angebotenen Scope entspricht, gib den praezisen
unbekannten Scope-Namen trotzdem an; der deterministische Policy-Code meldet
dies fail-closed. Eine normative Antwort hat beispielsweise diese Form:
`{"has_normative_statements": true, "assertions": [{"source_id": "...", "start_id": "s000002", "end_id": "s000003", "scopes": ["..."]}]}`.
Bei keiner normativen Aussage gilt exakt:
`{"has_normative_statements": false, "assertions": []}`.
