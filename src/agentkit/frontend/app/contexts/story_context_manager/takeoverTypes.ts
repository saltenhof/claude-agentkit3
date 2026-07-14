export type TakeoverApprovalStatus = 'pending' | 'approved' | 'denied' | 'expired' | 'invalidated';

export interface TakeoverRepoPushStatus {
  repo_id: string;
  last_pushed_head_sha: string | null;
  last_push_at: string | null;
  push_lag_hint: string | null;
}

export interface TakeoverApprovalRequest {
  approval_id: string;
  challenge_id: string;
  project_key: string;
  story_id: string;
  run_id: string;
  requested_by_principal: string;
  reason: string;
  owner_session_id: string;
  ownership_epoch: number;
  binding_version: number;
  phase: string;
  last_api_contact_at: string | null;
  open_operation_ids: string[];
  repo_push_status: TakeoverRepoPushStatus[];
  takeover_history_count: number;
  status: TakeoverApprovalStatus;
  requested_at: string;
  expires_at: string | null;
}

export interface TakeoverChallengeNotice {
  challenge_id: string;
  loss_corridor_notice_key: string;
  loss_corridor_notice_text: string;
}

export interface TakeoverApprovalsResponse {
  approvals: TakeoverApprovalRequest[];
  challenges: TakeoverChallengeNotice[];
}

export interface TakeoverChallenge {
  challenge_id: string;
  loss_corridor_notice_key: string;
  loss_corridor_notice_text: string;
}

export interface TakeoverMutationResult {
  status: 'offered' | 'pending_human_approval' | 'committed' | 'replayed' | 'challenge_reissued' | 'rejected';
  op_id: string;
  error_code?: string | null;
  takeover_challenge?: TakeoverChallenge | null;
}

export interface TakeoverRequestContext {
  project_key: string;
  story_id: string;
  run_id: string;
  session_id: string;
  worktree_roots: string[];
}
