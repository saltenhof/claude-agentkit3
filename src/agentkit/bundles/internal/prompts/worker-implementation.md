# Worker-Prompt: Implementation Story {story_id}

## Auftrag
Implementiere die User Story **{story_id}: {title}**.

## Story-Details
- **Story:** {story_id}
- **Typ:** Implementation
- **Modus:** {mode}
- **Groesse:** {size}

## Akzeptanzkriterien
{body}

## Arbeitsverzeichnis
{project_root}

## Worktree-Kontext
<!-- FK-22 §22.6.4 / FK-26 §26.2.2: Worktree-Map und Spawn-CWD -->
{worktree_context}

## Regeln
- Lies CLAUDE.md im Projektroot zuerst
- Implementiere vollstaendig - keine TODOs, keine Stubs
- Tests schreiben fuer neue Logik
- Schreiben in nicht-teilnehmende Repos ist verboten
- Am Ende: commit + push

[SENTINEL:worker-implementation-v1:{story_id}]
