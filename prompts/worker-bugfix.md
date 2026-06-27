# Worker-Prompt: Bugfix Story {story_id}

## Auftrag
Behebe den Bug beschrieben in **{story_id}: {title}**.

## Bug-Details
- **Issue:** #{issue_nr}
- **Typ:** Bugfix

## Fehlerbeschreibung
{body}

## Arbeitsverzeichnis
{project_root}

## Regeln
- Reproduzierenden Test ZUERST schreiben (muss vor dem Fix fehlschlagen)
- Dann den Bug fixen
- Test muss nach dem Fix gruen sein
- Am Ende: commit + push

[SENTINEL:worker-bugfix-v1:{story_id}]
