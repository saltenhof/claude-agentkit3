# QA-Prompt: Semantic Review {story_id}

## Auftrag
Pruefe die Story **{story_id}: {title}** semantisch.

## Fokus
- Akzeptanzkriterien und Story-Ziel gegen die vorhandene Umsetzung pruefen
- offensichtliche Luecken in Verhalten, Randfaellen und Testabdeckung benennen
- nur konkrete, nachvollziehbare Findings formulieren

## Kontext
- Issue: #{issue_nr}
- Route: {mode}
- Projektroot: {project_root}
- Story: {title}

## Ergebnisform
- klare Findings statt allgemeiner Eindruecke
- keine Code-Aenderungen in diesem Schritt

[SENTINEL:qa-semantic-review-v1:{story_id}]
