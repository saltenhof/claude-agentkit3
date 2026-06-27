# Worker-Prompt: Remediation fuer {story_id} (Runde {round_nr})

## Auftrag
Behebe die QA-Findings aus der Verify-Phase \
fuer **{story_id}: {title}**.

## Findings
{feedback}

## Regeln
- NUR die genannten Findings adressieren
- Keine Scope-Erweiterung
- Tests aktualisieren wenn noetig
- Am Ende: commit + push

[SENTINEL:worker-remediation-v1:{story_id}]
