import type {
  StoryEvidenceResponse,
  CoverageAcceptanceResponse,
  AreEvidenceResponse,
} from '../../foundation/bff/client';
import { Badge } from '../../design_system/Badge';
import { Info } from '../../design_system/Info';

type CoverageAcceptance = CoverageAcceptanceResponse['story_coverage_acceptance'];
type AreEvidence = AreEvidenceResponse['story_are_evidence'];

function bundleTone(status: string): string {
  if (status === 'UNRESOLVED') return 'danger';
  if (status === 'REQUESTED') return 'warning';
  return 'success';
}

/**
 * Evidence / result tab — renders the FETCHED evidence read-model (artifacts BC)
 * plus the requirements-coverage read-models (acceptance + ARE-evidence) from
 * AG3-091 (E2/AC9). No local Story fallback synthesis: missing read-models fail
 * closed with explicit empty-states so the tab never masks absent data.
 */
export function EvidenceTab({
  evidence,
  coverageAcceptance,
  coverageAreEvidence,
}: {
  evidence: StoryEvidenceResponse | null;
  coverageAcceptance: CoverageAcceptance | null;
  coverageAreEvidence: AreEvidence | null;
}) {
  return (
    <>
      <h2>Ergebnis und Evidenz</h2>

      <section className="detail-section">
        <h3>QA-Zyklus und Evidence Bundle</h3>
        {evidence === null ? (
          <p className="empty">Noch kein QA-Zyklus gelaufen.</p>
        ) : (
          <>
            <div className="evidence-summary">
              <Info label="QA Cycle" value={evidence.qa_cycle_id ?? '-'} />
              <Info label="Round" value={String(evidence.qa_cycle_round ?? 0)} />
              <Info label="Evidence Epoch" value={evidence.evidence_epoch ?? '-'} />
              <Info label="Fingerprint" value={evidence.evidence_fingerprint ?? '-'} />
              <Info label="Manifest" value={evidence.manifest_hash ?? '-'} />
            </div>
            <div className="bundle-list">
              {evidence.bundle_entries.length ? (
                evidence.bundle_entries.map((entry) => (
                  <div className="bundle-entry" key={`${entry.authority}-${entry.path}`}>
                    <Badge tone={bundleTone(entry.status)}>{entry.authority}</Badge>
                    <span>{entry.path}</span>
                    <Badge tone={bundleTone(entry.status)}>{entry.status}</Badge>
                  </div>
                ))
              ) : (
                <p className="empty">Kein Evidence-Bundle vorhanden.</p>
              )}
            </div>
          </>
        )}
      </section>

      <section className="detail-section">
        <h3>Akzeptanzkriterien-Abdeckung</h3>
        {coverageAcceptance === null ? (
          <p className="empty">Coverage nicht verfügbar.</p>
        ) : coverageAcceptance.acceptance_criteria.length ? (
          <ul className="acceptance-list">
            {coverageAcceptance.acceptance_criteria.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : (
          <p className="empty">Keine Akzeptanzkriterien verknüpft.</p>
        )}
      </section>

      <section className="detail-section">
        <h3>Anforderungs-Evidenz (ARE)</h3>
        {coverageAreEvidence === null ? (
          <p className="empty">ARE-Evidenz nicht verfügbar.</p>
        ) : coverageAreEvidence.linked_requirements.length ? (
          <div className="gate-list">
            {coverageAreEvidence.linked_requirements.map((req) => (
              <div className="bundle-entry" key={req.are_item_id}>
                <Badge tone="accent">{req.kind}</Badge>
                <span>{req.are_item_id}</span>
                <Badge tone={req.coverage_status === 'covered' ? 'success' : 'warning'}>
                  {req.coverage_status}
                </Badge>
              </div>
            ))}
          </div>
        ) : (
          <p className="empty">Keine verknüpften Anforderungen.</p>
        )}
      </section>
    </>
  );
}
