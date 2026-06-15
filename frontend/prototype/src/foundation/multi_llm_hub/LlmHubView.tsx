import { useEffect, useState } from 'react';
import { Send } from 'lucide-react';
import { Badge } from '../../design_system/Badge';
import { Info } from '../../design_system/Info';
import {
  hubSessions,
  hubBackends,
  initialHubMessages,
  type HubBackendName,
  type HubBackendStatus,
  type HubMessage,
  type HubSendMode,
  type HubSession,
  type HubSessionStatus,
} from './hubFixtures';

function formatDuration(ms: number | null): string {
  if (ms === null) return 'n/a';
  return ms < 1000 ? `${ms} ms` : `${Math.round(ms / 1000)} s`;
}

function statusTone(status: HubBackendStatus | HubSessionStatus): string {
  if (status === 'healthy' || status === 'active') return 'success';
  if (status === 'degraded' || status === 'released') return 'warning';
  return 'cancelled';
}

export function LlmHubView() {
  const [selectedSessionId, setSelectedSessionId] = useState('s-1777776058738-59e0b427');
  const [sendMode, setSendMode] = useState<HubSendMode>('broadcast');
  const [selectedBackends, setSelectedBackends] = useState<Set<HubBackendName>>(
    new Set(['chatgpt', 'gemini', 'qwen']),
  );
  const [activeResponseBackend, setActiveResponseBackend] = useState<HubBackendName>('chatgpt');
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<HubMessage[]>(initialHubMessages);

  const selectedSession: HubSession =
    hubSessions.find((session) => session.session_id === selectedSessionId) ?? hubSessions[0];
  const activeSessions = hubSessions.filter((session) => session.status === 'active');
  const totalSlots = hubBackends.reduce((sum, backend) => sum + backend.slots_total, 0);
  const usedSlots = hubBackends.reduce((sum, backend) => sum + backend.slots_in_use, 0);
  const availableTargets = selectedSession.llms;
  const effectiveTargets =
    sendMode === 'broadcast'
      ? availableTargets
      : sendMode === 'single'
        ? [activeResponseBackend].filter((backend) => availableTargets.includes(backend))
        : availableTargets.filter((backend) => selectedBackends.has(backend));
  const sessionMessages = messages.filter(
    (message) => message.session_id === selectedSession.session_id,
  );

  useEffect(() => {
    if (!selectedSession.llms.includes(activeResponseBackend)) {
      setActiveResponseBackend(selectedSession.llms[0]);
    }
    setSelectedBackends(new Set(selectedSession.llms));
  }, [activeResponseBackend, selectedSession.llms]);

  const toggleBackend = (backend: HubBackendName) => {
    setSelectedBackends((current) => {
      const next = new Set(current);
      if (next.has(backend)) next.delete(backend);
      else next.add(backend);
      return next;
    });
  };

  const sendMessage = () => {
    const text = draft.trim();
    if (!text || effectiveTargets.length === 0) return;
    const now = new Date();
    const time = now.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
    const baseId = `${selectedSession.session_id}-${now.getTime()}`;
    setMessages((current) => [
      ...current,
      { id: `${baseId}-user`, session_id: selectedSession.session_id, role: 'user', text, at: time },
      ...effectiveTargets.map((backend) => ({
        id: `${baseId}-${backend}`,
        session_id: selectedSession.session_id,
        backend,
        role: 'assistant' as const,
        text: `Mock response from ${backend}: request accepted via ${sendMode === 'broadcast' ? 'broadcast message' : sendMode === 'single' ? 'single target' : 'targets map'}.`,
        at: time,
        status: 'ok' as const,
      })),
    ]);
    setDraft('');
  };

  return (
    <div className="hub-page">
      <section className="hub-summary">
        <article className="hub-active-sessions ak-panel">
          <header>
            <span>Active Sessions</span>
            <strong>{activeSessions.length}</strong>
          </header>
          <div>
            {activeSessions.map((session) => (
              <button
                className={session.session_id === selectedSession.session_id ? 'active' : ''}
                key={session.session_id}
                type="button"
                onClick={() => setSelectedSessionId(session.session_id)}
              >
                <strong>{session.owner}</strong>
                <span>{session.llms.join(' · ')}</span>
              </button>
            ))}
          </div>
        </article>
        <Info label="Slot Usage" value={`${usedSlots}/${totalSlots}`} />
        <Info label="Free Slots" value={String(totalSlots - usedSlots)} />
      </section>

      <section className="hub-backends">
        {hubBackends.map((backend) => (
          <article className="hub-backend-card ak-panel" key={backend.name}>
            <header>
              <div>
                <strong>{backend.label}</strong>
                <span>{backend.name}</span>
              </div>
              <Badge tone={statusTone(backend.status)}>{backend.status}</Badge>
            </header>
            <div className="hub-slotbar">
              <span style={{ width: `${(backend.slots_in_use / backend.slots_total) * 100}%` }} />
            </div>
            <dl>
              <div>
                <dt>Slots</dt>
                <dd>
                  {backend.slots_in_use}/{backend.slots_total}
                </dd>
              </div>
              <div>
                <dt>Sends</dt>
                <dd>{backend.sends}</dd>
              </div>
              <div>
                <dt>Responses</dt>
                <dd>{backend.responses}</dd>
              </div>
              <div>
                <dt>Avg</dt>
                <dd>{formatDuration(backend.avg_response_ms)}</dd>
              </div>
            </dl>
            <div className="hub-holders">
              {backend.holders.length > 0 ? (
                backend.holders.map((holder) => (
                  <span key={`${backend.name}-${holder.session_id}`}>{holder.owner}</span>
                ))
              ) : (
                <span>no holder</span>
              )}
            </div>
          </article>
        ))}
      </section>

      <section className="hub-workbench">
        <aside className="hub-sessions ak-panel">
          <header>
            <div>
              <h2>Conversations</h2>
              <span>{hubSessions.length} sessions</span>
            </div>
            <Badge tone="info">/api/sessions</Badge>
          </header>
          <div className="hub-session-list">
            {hubSessions.map((session) => (
              <button
                className={session.session_id === selectedSession.session_id ? 'active' : ''}
                key={session.session_id}
                type="button"
                onClick={() => setSelectedSessionId(session.session_id)}
              >
                <span>
                  <strong>{session.owner}</strong>
                  <small>{session.description}</small>
                </span>
                <span className="hub-session-meta">
                  <Badge tone={statusTone(session.status)}>{session.status}</Badge>
                  <small>{session.llms.join(' · ')}</small>
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="hub-chat ak-panel">
          <header className="hub-chat-head">
            <div>
              <h2>{selectedSession.description}</h2>
              <span>
                {selectedSession.owner} · {selectedSession.session_id}
              </span>
            </div>
            <div className="hub-chat-head__badges">
              <Badge tone={selectedSession.resumable ? 'accent' : 'neutral'}>
                {selectedSession.resumable ? 'resumable' : 'leased'}
              </Badge>
              <Badge tone={statusTone(selectedSession.status)}>{selectedSession.status}</Badge>
            </div>
          </header>

          <div className="hub-target-bar">
            <div className="hub-segmented">
              {(['broadcast', 'group', 'single'] as HubSendMode[]).map((mode) => (
                <button
                  className={sendMode === mode ? 'active' : ''}
                  key={mode}
                  type="button"
                  onClick={() => setSendMode(mode)}
                >
                  {mode === 'broadcast' ? 'All' : mode === 'group' ? 'Subgroup' : 'Single'}
                </button>
              ))}
            </div>
            <div className="hub-targets">
              {availableTargets.map((backend) => (
                <button
                  className={[
                    effectiveTargets.includes(backend) ? 'active' : '',
                    sendMode === 'broadcast' ? 'locked' : '',
                  ]
                    .filter(Boolean)
                    .join(' ')}
                  disabled={sendMode === 'broadcast'}
                  key={backend}
                  type="button"
                  onClick={() => {
                    if (sendMode === 'single') setActiveResponseBackend(backend);
                    if (sendMode === 'group') toggleBackend(backend);
                  }}
                >
                  {backend}
                </button>
              ))}
            </div>
          </div>

          <div className="hub-response-tabs">
            {availableTargets.map((backend) => (
              <button
                className={activeResponseBackend === backend ? 'active' : ''}
                key={backend}
                type="button"
                onClick={() => setActiveResponseBackend(backend)}
              >
                {backend}
              </button>
            ))}
          </div>

          <div className="hub-response-grid">
            {availableTargets.map((backend) => (
              <section className={activeResponseBackend === backend ? 'active' : ''} key={backend}>
                <header>
                  <strong>{backend}</strong>
                  <Badge tone={effectiveTargets.includes(backend) ? 'accent' : 'neutral'}>
                    {effectiveTargets.includes(backend) ? 'targeted' : 'idle'}
                  </Badge>
                </header>
                <div className="hub-message-list">
                  {sessionMessages
                    .filter((message) => message.role === 'user' || message.backend === backend)
                    .map((message) => (
                      <article className={`hub-message role-${message.role}`} key={`${backend}-${message.id}`}>
                        <span>
                          {message.role === 'user' ? 'you' : backend} · {message.at}
                        </span>
                        <p>{message.text}</p>
                      </article>
                    ))}
                </div>
              </section>
            ))}
          </div>

          <footer className="hub-composer">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="Message to selected Hub session"
              rows={3}
            />
            <button className="ak-button ak-button--primary" type="button" onClick={sendMessage}>
              <Send size={16} />
              Send
            </button>
          </footer>
        </section>
      </section>
    </div>
  );
}
