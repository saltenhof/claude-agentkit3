---
title: Formal Spec Meta
status: active
doc_kind: meta
---

# Formal Spec Meta

Dieses Verzeichnis enthaelt die Meta-Regeln der formalen
Spezifikationsschicht.

Hier wird festgezogen:

- was formal abgedeckt werden muss
- was bewusst in Prosa bleibt
- was `compile` in AK3 bedeutet
- wie Drift zwischen Prosa und Formal-Spec verhindert wird
- wie die Ablagestruktur und die Referenzdisziplin aussieht

Solange diese Regeln nicht geaendert werden, ist dieses Verzeichnis der
stabile Einstiegspunkt fuer neue Agents auch nach Kontext-Compaction
oder in frischen Sessions.

## Dokumente

| Dokument | Inhalt |
|---|---|
| `meta-contract.md` | Autoritaetsgrenze, Scope der formalen Schicht, Compile-Begriff, Drift-Schutz |
| `syntax-contract.md` | Strukturierter Markdown-Vertrag, Pflichtfelder, normative Zonen |
| `id-and-reference-scheme.md` | IDs, Referenzen, Anker, Drift-kritische Verknuepfungen |
| `object-kinds.md` | Zulaessige formale Objektarten und ihr Minimalumfang |
| `compiler-pipeline.md` | Zielbild fuer Parse, Resolve, Consistency, Trace-Validierung, Drift-Audit |
