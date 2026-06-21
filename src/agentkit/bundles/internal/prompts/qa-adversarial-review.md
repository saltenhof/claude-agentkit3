# QA-Prompt: Adversarial Review {story_id}

## Auftrag
Untersuche die Story **{story_id}: {title}** auf schwache Stellen und Gegenbeispiele.

## Fokus
- Kantenfaelle, Fehlerpfade und instabile Annahmen suchen
- benoetigte Angriffs- oder Regressionstests benennen
- nur belastbare Kritikpunkte mit klarer Stoerwirkung melden

## Kontext
- Issue: #{issue_nr}
- Route: {mode}
- Projektroot: {project_root}
- Story: {title}

## Ergebnisform
- Findings priorisieren
- keine Produktionseingriffe in diesem Schritt

[SENTINEL:qa-adversarial-review-v1:{story_id}]
