OVERALL CHANGES-REQUESTED

Per-Dimension: alle vier CHANGES-REQUESTED.
R3 geloest: status.yaml = eigener BC-9-Planning-Schreibpfad (nicht ProjectionAccessor.write_projection); 9+dependency_edge=10 erhalten; FK-69 ProjectionKind bleibt 7.

Remaining Must-Fix ERROR:
- AG3-099 nutzt noch EventTypeId (real: EventType, events.py:18) und sagt AG3-081 liefert "Emitter-Infrastruktur"; generische Emitter-Infra existiert bereits (emitters.py:19, storage.py:23). Kanonischer Split: AG3-081 liefert EventType-Katalog/Mandatory-Payload-Contract; generische Emitter-Infra ist vorhanden; AG3-099 besitzt fachliche BC14-Emission/Tests. EventTypeId, "Emitter-Infrastruktur", Integrity-Dim-8 aus den Dependency-Formulierungen entfernen. (story.md:42/47/59/64/77)
(job-d9f197a1)
