import { conceptAnchors } from '../../store';
import type { Story } from '../../store';
import type { StorySpecResponse } from '../../foundation/bff/client';
import { Badge } from '../../design_system/Badge';
import { Info } from '../../design_system/Info';

/**
 * Specification tab — renders the FETCHED story_specification read-model
 * (story_context_manager) for need / solution / acceptance / refs (E2/AC9).
 *
 * Story master data (id/title/type/status/repo/...) are header facts owned by the
 * already-selected Story; the narrative spec content comes ONLY from the fetched
 * read-model. When the spec read-model is absent we fail closed with an explicit
 * empty-state instead of masking the missing data with local fallback prose.
 */
export function SpecificationTab({
  story,
  spec,
}: {
  story: Story;
  spec: StorySpecResponse | null;
}) {
  return (
    <>
      <h2>{story.title}</h2>
      <div className="detail-grid">
        <Info label="Typ" value={story.type} />
        <Info label="Status" value={story.status} />
        <Info label="Repo" value={story.repo} />
        <Info label="Module" value={story.module} />
        <Info label="Epic" value={story.epic} />
        <Info label="Impact" value={story.changeImpact} />
        <Info label="Concept Quality" value={story.conceptQuality} />
        <Info label="Owner" value={story.owner} />
      </div>

      {story.blocker && <div className="blocker-box">{story.blocker}</div>}

      {spec === null ? (
        <section className="detail-section">
          <p className="empty">Keine Spezifikation verfügbar.</p>
        </section>
      ) : (
        <>
          <section className="detail-section">
            <h3>Bedarf und Loesungsansatz</h3>
            <p className="story-body">
              <strong>Bedarf:</strong> {spec.need ?? 'Kein Bedarf hinterlegt.'}
            </p>
            <p className="story-body">
              <strong>Loesung:</strong> {spec.solution ?? 'Kein Loesungsansatz hinterlegt.'}
            </p>
          </section>

          <section className="detail-section">
            <h3>Akzeptanzkriterien</h3>
            {spec.acceptance.length ? (
              <ul className="acceptance-list">
                {spec.acceptance.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="empty">Keine Akzeptanzkriterien hinterlegt.</p>
            )}
          </section>

          <section className="detail-section">
            <h3>Abhaengigkeiten</h3>
            <div className="dependency-list">
              {story.dependencies.length ? (
                story.dependencies.map((dependency) => (
                  <Badge tone="accent" key={dependency}>
                    {dependency}
                  </Badge>
                ))
              ) : (
                <p className="empty">Keine vorgelagerten Story-Abhaengigkeiten.</p>
              )}
            </div>
          </section>

          <section className="detail-section">
            <h3>Referenzen und Guardrails</h3>
            <div className="reference-grid">
              <div className="reference-box ak-panel">
                <strong>Konzeptquellen</strong>
                {(spec.concept_refs ?? []).length ? (
                  (spec.concept_refs ?? []).map((ref) => <span key={ref}>{ref}</span>)
                ) : (
                  <span className="empty">keine</span>
                )}
              </div>
              <div className="reference-box ak-panel">
                <strong>Guardrails</strong>
                {(spec.guardrail_refs ?? []).length ? (
                  (spec.guardrail_refs ?? []).map((ref) => <span key={ref}>{ref}</span>)
                ) : (
                  <span className="empty">keine</span>
                )}
              </div>
              <div className="reference-box ak-panel">
                <strong>Definition of Done</strong>
                {(spec.definition_of_done ?? []).length ? (
                  (spec.definition_of_done ?? []).map((item) => <span key={item}>{item}</span>)
                ) : (
                  <span className="empty">keine</span>
                )}
              </div>
            </div>
          </section>
        </>
      )}

      <section className="detail-section concept">
        <h3>Konzeptanker</h3>
        {conceptAnchors.map((anchor) => (
          <p key={anchor}>{anchor}</p>
        ))}
      </section>
    </>
  );
}
