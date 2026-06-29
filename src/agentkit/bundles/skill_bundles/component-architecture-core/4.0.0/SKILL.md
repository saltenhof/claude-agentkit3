---
name: component-architecture
description: Design a software component architecture from concept documents, domain models, or requirement descriptions. Use this skill whenever someone asks to identify components, design a component structure, create a component diagram, define module boundaries, break a system into components, or asks "what are the components of X". Also use when reviewing whether an existing component cut is correct, when someone says a design feels like a god object, or when architectural boundaries need to be clarified, or when a component list mixes domain components with infrastructure (API Gateway, Event Bus, Database, Utils). Invoke proactively when concept documents or domain descriptions are present and no component structure exists yet, or when an existing architecture lists deployment units or technical layers instead of domain responsibilities.
user-invocable: true
---

# Component Architecture Skill

Guide an agent through identifying, designing, and validating a software component architecture from existing domain knowledge — concept documents, domain models, use cases, or system descriptions.

---

## What is a Software Component

A software component is a **logical bundle of classes with exactly one clearly bounded domain responsibility**. It is not a deployment unit, not a technical layer, not a flow step.

A genuine component has all of the following:

| Property | What it means |
|---|---|
| **Domain responsibility** | One clearly statable reason to exist — not "handles stuff for phase 2" but "manages the lifecycle of story context across a run" |
| **Provided interface** | An explicit contract of what it offers to callers |
| **Required interface** | Explicitly declared dependencies — no hidden assumptions |
| **Encapsulation** | Internals are invisible; no access except through the interface |
| **Replaceability** | Any other implementation with the same interface can substitute it |
| **Coarser than a class** | Bundles multiple classes; a single class is not a component |

**What a component is NOT:**
- A deployment unit — components exist cleanly inside monoliths
- A flow step — "Setup", "Execution", "Phase1" are not component names
- A category label — "Infrastructure", "Utils", "Common", "Helpers" are not component names
- A class with a longer name

---

## Identification Process

Work through these steps in order. Do not jump to naming components before understanding the domain.

### Step 1 — Understand the domain first

Read all available input: concept documents, domain model, use cases, system descriptions, architecture guardrails. Do not name any component yet.

Build mental clarity on:
- What is the core purpose of the system?
- What are the distinct domain responsibilities it must fulfill?
- Who are the actors and what do they need from the system?

### Step 2 — Find domain clusters

Ask the primary question: **What belongs together domain-wise?**

This takes priority over technical similarity, stability, or change frequency. Domain cohesion comes first.

Practical indicators of a natural cluster:
- The same domain concepts appear together repeatedly
- The same stakeholder or expert owns this area
- A language shift occurs — when the vocabulary changes, a boundary likely exists (Fowler: *"a different model emerges when the language changes"*)
- Changing one thing in the cluster rarely requires touching the other cluster

Do not cut along technical layers (data access, messaging, API). Cut along domain responsibilities.

### Step 3 — Name by responsibility, not position

Give each candidate a name that describes its domain task. Apply this test:

> *"Can I state in one sentence what this component is responsible for, without mentioning the flow, the phase, or a technical mechanism?"*

If the answer is no, the name is wrong or the responsibility is unclear. Fix it before proceeding.

**Good names:** `StoryContextManager`, `ArtifactManager`, `TelemetryService`, `GuardSystem`
**Bad names:** `SetupExecutor`, `Phase2Handler`, `CommonUtils`, `DataLayer`

### Step 4 — Validate each candidate

For every candidate component, answer these questions:

1. Can you name an identifiable provided interface?
2. Can you name identifiable required interfaces (dependencies)?
3. Could it be replaced by another implementation with the same interface?
4. Does it have exactly **one** domain responsibility?
5. Is it clearly coarser than a single class?

If any answer is No → merge with a neighbor, split into focused pieces, or reclassify as a class (not a component).

### Step 5 — Determine the hierarchy

Apply the sub-component rule to every candidate:

> If a component is called by **exactly one** other component → it is a sub-component of that caller.
> If it is called by **multiple** components → it is an independent top-level component.

This produces a two-level hierarchy naturally. Do not force more nesting than the call structure justifies.

### Step 6 — Check for cycles

Sketch the dependency graph (top-level components only). **Cycles are always wrong** (Acyclic Dependencies Principle).

If A depends on B and B depends on A, choose one resolution:
- **Introduce an abstraction** — extract an interface that both depend on; the cycle disappears
- **Extract a shared component** — if they share a concept, move it to a new component C; both A and B depend on C, not on each other

### Step 7 — Refine with three checks

**CCP check (Common Closure Principle):**
When requirement X changes, how many components must change? If the answer is consistently more than one, what changes together should live together.

**CRP check (Common Reuse Principle):**
Does a client have to depend on things from this component that it never uses? If yes, the component bundles domain-unrelated things — split it.

**Size check:**
Is one component dramatically larger or smaller than its peers? Too large usually means multiple hidden responsibilities. Too small usually means it is actually a class.

---

## Red Flags

Stop and fix before proceeding when any of these appear:

- Component name is a category: `Infrastructure`, `Utils`, `Common`, `Shared`, `Helpers`, `Layer`
- Component name describes a flow position: `SetupPhase`, `Step1`, `ExecutionUnit`
- Component name is a technical deployment concern: `ApiGateway`, `EventBus`, `Database`, `MessageBroker`, `Cache`, `LoadBalancer` — these are infrastructure, not domain components. Persistence, messaging, and routing are expressed as **required interfaces** on domain components, not as named components in the diagram.
- No identifiable interface can be described
- Multiple unrelated domain responsibilities bundled together
- A cycle exists in the dependency graph
- A client must depend on parts of the component it never uses

---

## Naming Rules

- English, PascalCase
- Name reflects the domain responsibility of the component
- Suffix conventions (optional but helpful): `Manager`, `Service`, `Registry`, `Engine`, `Gateway`, `Adapter`, `Store` — only when they accurately describe the role

---

## Practical Mindset

Component design is a **living artifact**. The first cut is an informed hypothesis. When new domain insights emerge, when dependencies prove wrong, when a boundary turns out to be too coarse or too fine — adjust the cut. That is the normal process, not a failure.

What is not acceptable: using labels as structure. A component that only has a name but no definable interface and no clearly bounded responsibility is not a component. It is a label.

Functional decomposition (one component per feature or per flow step) consistently produces god objects and tight coupling. Cut by domain responsibility, not by function list.

---

## Output Format

Produce the result in three parts:

### Part 1 — Component List

```
- ComponentName                  — one-sentence domain responsibility
  - SubComponentName             — one-sentence domain responsibility
  - SubComponentName             — one-sentence domain responsibility
- ComponentName                  — one-sentence domain responsibility
```

### Part 2 — Dependency Summary

List only top-level component dependencies. Format:

```
ComponentA  →  ComponentB, ComponentC
ComponentD  →  ComponentB
```

Arrows point from the component that depends to the component it depends on. Higher in the hierarchy = more dependencies on things below.

### Part 3 — Red Flags and Open Questions

List any violations found, components that were reclassified as classes, cycles detected, or boundaries that remain uncertain and need domain input to resolve.
