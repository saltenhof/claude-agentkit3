import { AlertTriangle, ShieldCheck } from 'lucide-react';
import type { ReactElement } from 'react';

import type {
  TakeoverApprovalRequest,
  TakeoverChallengeNotice,
} from '../takeoverTypes';

interface TakeoverApprovalOverlayProps {
  approval: TakeoverApprovalRequest;
  challenge: TakeoverChallengeNotice | null;
  busy: boolean;
  error: string | null;
  onConfirm: (approval: TakeoverApprovalRequest) => Promise<void>;
  onDeny: (approval: TakeoverApprovalRequest) => Promise<void>;
}

export function TakeoverApprovalOverlay({
  approval,
  challenge,
  busy,
  error,
  onConfirm,
  onDeny,
}: Readonly<TakeoverApprovalOverlayProps>): ReactElement {
  const corridorText = challenge?.loss_corridor_notice_text;
  const completeChallenge = challenge !== null
    && challenge.challenge_id === approval.challenge_id
    && challenge.loss_corridor_notice_key === 'pushed_only_loss_corridor'
    && typeof corridorText === 'string'
    && corridorText.trim().length > 0
    && approval.repo_push_status.length > 0
    && approval.repo_push_status.every(
      (repo) => typeof repo.last_pushed_head_sha === 'string'
        && repo.last_pushed_head_sha.trim().length > 0,
    );

  return (
    <dialog className="takeover-overlay" open aria-labelledby="takeover-title">
      <header>
        <AlertTriangle size={22} />
        <div>
          <span>Globale Governance-Freigabe</span>
          <h2 id="takeover-title">Ownership-Takeover für {approval.story_id}</h2>
        </div>
      </header>

      <dl className="takeover-facts">
        <div><dt>Projekt</dt><dd>{approval.project_key}</dd></div>
        <div><dt>Angefragt von</dt><dd>{approval.requested_by_principal}</dd></div>
        <div><dt>Aktueller Owner</dt><dd>{approval.owner_session_id}</dd></div>
        <div><dt>Challenge</dt><dd><code>{approval.challenge_id}</code></dd></div>
        <div><dt>Phase</dt><dd>{approval.phase}</dd></div>
        <div><dt>Begründung</dt><dd>{approval.reason}</dd></div>
      </dl>

      <div className="loss-corridor" data-notice-key={challenge?.loss_corridor_notice_key ?? 'missing'}>
        <strong><ShieldCheck size={17} /> Verlustkorridor – Pflichtbestätigung</strong>
        <p>{corridorText ?? 'Der serverautorisierte Pflichttext fehlt. Eine Bestätigung ist gesperrt.'}</p>
        <ul>
          {approval.repo_push_status.map((repo) => (
            <li key={repo.repo_id}>
              {repo.repo_id}: Übernommen wird ausschließlich der gepushte Stand{' '}
              <code>&lt;{repo.last_pushed_head_sha ?? 'sha-unbekannt'}&gt;</code>.
            </li>
          ))}
        </ul>
      </div>

      {!completeChallenge && (
        <p className="takeover-blocking">Challenge- oder SHA-Signal unvollständig – fail-closed, keine Freigabe möglich.</p>
      )}
      {error !== null && <p className="takeover-error">{error}</p>}
      <footer>
        {approval.status === 'pending' && (
          <button type="button" disabled={busy} onClick={() => void onDeny(approval)}>Ablehnen</button>
        )}
        <button
          className="primary-action"
          type="button"
          disabled={busy || !completeChallenge}
          onClick={() => void onConfirm(approval)}
        >
          Angezeigte Challenge bestätigen
        </button>
      </footer>
    </dialog>
  );
}
