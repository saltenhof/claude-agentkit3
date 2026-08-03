---
concept_id: META-DEC-2026-08-03-SECRET-SCAN-PRUEFT-FORM-NICHT-ZEICHENFOLGE
title: Concept-Decision-Record — Der Secret-Scan prueft die Credential-Form, nicht die Zeichenfolge
module: meta
cross_cutting: true
status: active
doc_kind: decision-record
authority_over: []
defers_to: []
supersedes: []
superseded_by:
tags: [meta, decision-record, security, secrets, guard-system, FK-15, FK-33]
formal_scope: prose-only
---

# Concept-Decision-Record — Der Secret-Scan prueft die Credential-Form, nicht die Zeichenfolge

Datum: 2026-08-03.

## 1. Anlass

`SecretPatternKind.CONTENT_PREFIX` hiess „Praefix" und war
`pattern.value in line` — eine Substring-Suche ueber die ganze Zeile. Der Name
sagte etwas zu, das die Implementierung nie einloeste.

Fuer `AKIA` und `ghp_` fiel das nie auf: beide kommen in natuerlicher Sprache
praktisch nicht vor. `sk-` kommt vor, und zwar haeufig — in jedem Wort, das auf
`sk` endet und mit Bindestrich weitergeht. In einem konsumierenden Projekt traf
es den Fachbegriff `risk-adjusted-attraction`, der aus dessen eigener
Formal-Spec stammt und dort dauerhaft steht. **Damit war in diesem Repository
kein vollstaendiger Commit mehr moeglich** — 472 vorgemerkte Dateien, blockiert
von einem Scanner, der Fliesstext fuer einen Schluessel hielt.

Der Schaden ist groesser als der blockierte Commit. Ein Gate, das korrekte
Arbeit dauerhaft ablehnt, erzieht zu `--no-verify`. Ein umgangenes Gate schuetzt
niemanden mehr — auch dann nicht, wenn spaeter ein echter Schluessel im Diff
liegt.

## 2. Entscheidung

**2.1 Getroffen wird die Form des ausgestellten Credentials, nicht die
Zeichenfolge.** Ein Treffer verlangt zwei Bedingungen gleichzeitig: das Praefix
steht am **Token-Anfang** (unmittelbar davor kein `[A-Za-z0-9_-]`), und danach
folgen mindestens so viele Token-Zeichen wie der **Mindestkoerper** vorgibt.
Beide sind noetig: ohne die Ankerung faellt Fachprosa, ohne den Mindestkoerper
genuegt ein Praefix am Zeilenanfang.

Die Ankerung sitzt vor dem **Praefix**, nicht vor dem Wort. In `ri|sk-adjusted`
steht links vom `sk-` ein Token-Zeichen; genau deshalb faellt der Fall heraus.

**2.2 Der Mindestkoerper ist eine Falsch-Positiv-Untergrenze, kein
Aussteller-Vertrag.** Er liegt bewusst **unterhalb** der kuerzesten dokumentierten
Ausstellung. Wuerde er auf der realen Laenge sitzen, hoerte ein verkuerztes oder
geaendertes Upstream-Format still auf, erkannt zu werden — ein Fail-open, das
niemand bemerkt. Die Grenze markiert den Punkt, ab dem natuerliche Sprache
unplausibel wird, nicht den Punkt, ab dem ein Schluessel gueltig ist.

**2.3 Die Familien folgen dem Aussteller, nicht der Historie.** Gefuehrt werden
`AKIA` und `ASIA` (AWS, dauerhaft und temporaer), die GitHub-Familien `ghp_`,
`gho_`, `ghu_`, `ghs_`, `ghr_` und `github_pat_` sowie `sk-` (OpenAI,
einschliesslich `sk-proj-`). Die vorherige Liste war auf drei historische
Beispiele eingefroren; temporaere AWS-Credentials und fuenf Sechstel der
GitHub-Formate fielen durch.

**2.4 Der Vertrag hat einen Eigentuemer im Konzept.** FK-15 §15.5.2 normiert die
Trefferbedingung; FK-33 verweist darauf statt eine zweite Fassung zu fuehren.
Die konkreten Zahlen stehen im Code, weil sie dort durchgesetzt werden — aber
**als abgeleitete Untergrenze aus 2.2**, nicht als eigenstaendige Norm.

**2.5 Der Diff-Parser unterscheidet Kopf und Nutzlast nach Position, nicht nach
Praefix.** Eine hinzugefuegte Zeile `++counter` erreicht den Parser als
`+++counter` und wurde als Dateikopf verworfen. Kopfzeilen werden nur noch
ausserhalb eines Hunks erkannt.

**2.6 Text-Ausgaben von Fremdprozessen werden auf UTF-8 gepinnt.**
`text=True` ohne `encoding` dekodiert mit der bevorzugten Kodierung der
Plattform: UTF-8 unter Linux und macOS, cp1252 unter deutschem Windows.
Derselbe Code las damit denselben Repository-Inhalt auf der einen Maschine
korrekt und brach auf der anderen ab. Ein Wert, der von der Maschine abhaengt,
ist kein Wert. Ein Contract-Test haelt die Klasse ueber `src/`, `tools/`,
`scripts/` und `tests/` geschlossen und weist nach, dass er die bekannten
Umgehungen faengt — Alias, Re-Import, `getattr`, `partial`, `**kwargs`,
`encoding=None` und jedes nicht-UTF-8-Literal.

**2.7 Gepinnt heisst nicht strikt: wem die Bytes gehoeren, entscheidet.**
Strikt zu dekodieren ist richtig, wo AK3 die Bytes besitzt — eigene
Konzeptdateien, JSON-Protokolle. Es ist **falsch** fuer den Diff eines fremden
Repositorys, fuer Committext und fuer ein Diagnoseprotokoll: dort macht ein
einziges abweichendes Byte aus einem funktionierenden Werkzeug einen
dauerhaften Blocker — genau der Schaden, gegen den 2.1 antritt. Fremdbesessene
Ausgabe wird deshalb **ersetzend** gelesen; die Entscheidung faellt weiter am
Rueckgabewert, nicht am Zeichensatz. Ein Fremdprozess, den AK3 startet,
bekommt zusaetzlich `PYTHONIOENCODING=utf-8` — steuern statt hoffen.

## 3. Was NICHT entschieden wurde — und warum

**Schutz gegen absichtliche Verschleierung.** Hier ist genau zu unterscheiden,
was diese Entscheidung kostet und was sie nicht kostet:

- **Zerlegung *hinter* einem vollstaendigen Praefix** — `"sk-" "proj-…"` — hat
  die alte Substring-Suche **getroffen** und trifft jetzt nicht mehr. Das ist
  eine **bewusst hingenommene Abdeckungseinbusse**, kein Randfall.

  Sie ist **nicht technisch alternativlos.** Ein sprachnaher Matcher, der
  unmittelbar benachbarte String-Literale derselben Zeile zusammenzieht und
  danach dieselbe Formpruefung anwendet, wuerde den Fall fangen und
  `risk-adjusted` weiterhin nicht treffen. Der gewaehlte Matcher arbeitet
  bewusst **sprachneutral auf der Rohzeile**: er kennt weder Python noch
  JavaScript noch YAML und braucht keine Grammatik nachzuziehen, wenn eine neue
  Sprache dazukommt. Diese Einfachheit ist der Grund, dass die Abdeckung hier
  endet — nicht eine Unmoeglichkeit. Wer sie zurueckholen will, baut einen
  sprachbewussten Matcher; das ist eine eigene Entscheidung mit eigenem Preis.
- **Zerlegung des Praefixes selbst** (`"sk" "-" "proj-…"`), Base64,
  URL-Encoding: umgehen **beide** Implementierungen. Das ist die Reichweite des
  Werkzeugs, nicht diese Entscheidung.

Der Pre-Commit-Scan adressiert das **versehentliche** Einchecken. Die Grenze
wird hier benannt, damit niemand dem Scanner eine Zusage entnimmt, die er nie
geben kann — und damit die eingebuesste Abdeckung sichtbar bleibt statt
weggeredet zu werden.

**Der Realitaetsnachweis gegen die Aussteller.** Praefixe und Laengen stammen
aus Dokumentation, nicht aus einem Lauf gegen AWS, GitHub oder OpenAI —
Testschluessel dieser Anbieter liegen hier nicht vor. Nach
`CLAUDE.md` „REALITAETSNACHWEIS AN FREMDSYSTEM-GRENZEN" ist das eine **benannte
Luecke mit Grund**, kein gruener Haken. 2.2 ist die Antwort darauf: die
Untergrenze ist so gewaehlt, dass sie eine Formataenderung ueberlebt.

## 4. Konsequenzen

- Fachprosa mit Credential-Praefix im Wortinneren blockiert keinen Commit mehr;
  der belegte Anlassfall ist als Regressionstest gegen den **realen**
  Konzeptkorpus gefuehrt, nicht gegen erfundene Zeilen.
- Temporaere AWS-Keys und die vollstaendige GitHub-Familie werden erkannt.
- Der Structural Check meldet keine leere Aenderungsmenge mehr, wenn die
  Basis-Referenz nicht aufloesbar ist — fehlende Evidenz ist ABWESEND, nicht
  „sauber".
- Ein fremder Hook, der die Marker nur *erwaehnt*, verliert seinen eigenen Code
  nicht mehr: Sentinels werden als vollstaendige Zeile erkannt.
- `.env.*` blockiert jetzt tatsaechlich, wie FK-15 §15.5.2 es seit jeher sagt.
