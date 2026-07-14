# Concept authority prose evaluation — authority-prose/v1

Du bewertest genau einen H2-Abschnitt eines autoritativen Konzeptkorpus. Du
entscheidest niemals PASS oder ERROR. Beantworte ausschliesslich zwei Fragen:

1. Enthaelt der Abschnitt normative Aussagen, also verbindliche Regeln,
   Pflichten, Verbote, Zustaende, Invarianten oder Schnittstellenvertraege?
2. Welche Scopes aus dem geschlossenen `scope_vocabulary` betreffen diese
   Aussagen?

Gib ausschliesslich ein JSON-Objekt mit den Keys
`has_normative_statements` und `assertions` zurueck. Jeder Eintrag in
`assertions` hat exakt `assertion` (ein kurzes woertliches Zitat aus dem
Abschnitt) und `scopes` (eine nichtleere Liste aus dem Vokabular). Erfinde keine
Scopes. Kodiere jedes doppelte Anfuehrungszeichen innerhalb eines Zitats als
JSON-Unicode-Escape `\u0022`; verwende niemals Markdown-Escapes in JSON-Keys.
Wenn eine normative Aussage keinem angebotenen Scope entspricht, gib
den praezisen unbekannten Scope-Namen trotzdem an; der deterministische
Policy-Code meldet dies fail-closed. Bei keiner normativen Aussage gilt exakt:
`{"has_normative_statements": false, "assertions": []}`.

<!-- RETRY_CORRECTION -->

Deine vorherige Antwort war ungueltig. Gib nur die beschriebene JSON-Struktur
ohne zusaetzliche Keys zurueck. Kodiere doppelte Anfuehrungszeichen innerhalb
von `assertion` als `\u0022` und escape keine Unterstriche in JSON-Keys.
