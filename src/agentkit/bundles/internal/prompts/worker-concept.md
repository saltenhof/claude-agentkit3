# Worker-Prompt: Concept Story {story_id}

## Auftrag
Erstelle das Konzeptdokument fuer **{story_id}: {title}**.

## Anforderungen
- **Issue:** #{issue_nr}
- **Typ:** Concept

## Beschreibung
{body}

## Regeln
- Konzept als Markdown unter concept/ anlegen
- Fachliche Vollstaendigkeit vor Prosa
- Keine Code-Implementierung - nur Design
- Am Ende: commit + push

[SENTINEL:worker-concept-v1:{story_id}]
