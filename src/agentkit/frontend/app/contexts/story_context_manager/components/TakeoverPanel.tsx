import { AlertOctagon, GitCommitHorizontal, History, LockKeyhole } from 'lucide-react';
import type { ReactElement } from 'react';

import type { TakeoverApprovalRequest } from '../takeoverTypes';

type TakeoverEdgeState =
  | 'takeover_reconcile_required'
  | 'contested_local_writes'
  | 'remote_branch_diverged_after_takeover'
  | 'local_stale_or_dirty_takeover_target';

const EDGE_RESOLUTION: Record<TakeoverEdgeState, string> = {
  takeover_reconcile_required: 'Offiziellen takeover-reconcile-worktree-Pfad vollständig ausführen.',
  contested_local_writes: 'Konflikt administrativ prüfen und über den auditierten Reconcile-Pfad auflösen.',
  remote_branch_diverged_after_takeover: 'Remote-Divergenz administrativ gegen takeover_base_sha auflösen.',
  local_stale_or_dirty_takeover_target: 'Ziel quarantänisieren und aus takeover_base_sha neu provisionieren.',
};

interface TakeoverPanelProps {
  approval: TakeoverApprovalRequest | null;
  edgeStates?: Partial<Record<TakeoverEdgeState, boolean>>;
}

export function TakeoverPanel({ approval, edgeStates }: Readonly<TakeoverPanelProps>): ReactElement {
  return (
    <section className="takeover-panel">
      <div className="takeover-history">
        <History size={18} />
        <span>Takeover-Historie</span>
        <strong>{approval?.takeover_history_count ?? 'unbekannt'}</strong>
      </div>

      <h3><LockKeyhole size={16} /> Eigentumslage</h3>
      <dl className="takeover-facts">
        <div><dt>Owner-Session</dt><dd>{approval?.owner_session_id ?? 'unbekannt'}</dd></div>
        <div><dt>Principal</dt><dd>unbekannt</dd></div>
        <div><dt>Ownership-Epoche</dt><dd>{approval?.ownership_epoch ?? 'unbekannt'}</dd></div>
        <div><dt>Phase</dt><dd>{approval?.phase ?? 'unbekannt'}</dd></div>
        <div><dt>Offene op_ids</dt><dd>{approval?.open_operation_ids.join(', ') || 'keine gemeldet'}</dd></div>
        <div><dt>Zuletzt aktiv</dt><dd>{approval?.last_api_contact_at ?? 'unbekannt'}</dd></div>
      </dl>
      <p className="takeover-info">„Zuletzt aktiv“ ist reine Information. Inaktivität ist keine Diagnose und löst niemals einen Takeover aus.</p>

      <h3><GitCommitHorizontal size={16} /> Push-Frische und Verantwortungsgrenze</h3>
      {approval === null || approval.repo_push_status.length === 0 ? (
        <p className="takeover-blocking">Repo-Signal unbekannt – keine optimistische Freigabe.</p>
      ) : (
        <ul className="takeover-repos">
          {approval.repo_push_status.map((repo) => (
            <li key={repo.repo_id}>
              <strong>{repo.repo_id}</strong>
              <span>last_pushed_head_sha: <code>{repo.last_pushed_head_sha ?? 'unbekannt'}</code></span>
              <span>Push-Frische: {repo.last_push_at ?? 'unbekannt'} · {repo.push_lag_hint ?? 'ohne Signal'}</span>
              <span>takeover_base_sha nach Transfer: <code>unbekannt</code></span>
            </li>
          ))}
        </ul>
      )}

      <h3><AlertOctagon size={16} /> Blockierende Edge-Zustände</h3>
      <ul className="takeover-edge-states">
        {(Object.keys(EDGE_RESOLUTION) as TakeoverEdgeState[]).map((state) => {
          const signal = edgeStates?.[state];
          return (
            <li key={state} data-active={signal === true} data-known={signal !== undefined}>
              <strong>{state}</strong>
              <span>{signal === undefined ? 'Signal unbekannt – blockierend (fail-closed).' : signal ? 'Aktiv – blockierend.' : 'Nicht aktiv.'}</span>
              <small>{EDGE_RESOLUTION[state]}</small>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
