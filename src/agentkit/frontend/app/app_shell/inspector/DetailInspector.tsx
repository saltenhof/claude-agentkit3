import { Check, CircleX, RotateCcw, X } from 'lucide-react';
import { useState } from 'react';
import type { ReactElement } from 'react';

import type { AppActions } from '../../App';
import type { StoryDetail } from '../../contexts/story_context_manager/types';

interface DetailInspectorProps {
  detail: StoryDetail | null;
  loading: boolean;
  onClose: () => void;
  actions: AppActions;
}

export function DetailInspector({ detail, loading, onClose, actions }: DetailInspectorProps): ReactElement {
  const [tab, setTab] = useState<'spec' | 'evidence' | 'kpi' | 'flow'>('spec');
  const [draftTitle, setDraftTitle] = useState('');

  if (loading) {
    return <aside className="inspector"><div className="loading-state">Lade Story...</div></aside>;
  }
  if (detail === null) {
    return <aside className="inspector inspector-empty" />;
  }

  const story = detail.summary;
  const spec = detail.spec;

  return (
    <aside className="inspector">
      <header className="inspector-head">
        <div>
          <span>{story.story_id}</span>
          <h2>{story.title}</h2>
        </div>
        <button className="icon-button" type="button" onClick={onClose} title="Schliessen">
          <X size={18} />
        </button>
      </header>

      <div className="command-row">
        <button
          type="button"
          disabled={story.status !== 'Backlog'}
          onClick={() => void actions.approveStory(story.story_id)}
          title="Approve"
        >
          <Check size={16} /> Approve
        </button>
        <button
          type="button"
          disabled={story.status !== 'Approved'}
          onClick={() => void actions.rejectStory(story.story_id)}
          title="Reject"
        >
          <RotateCcw size={16} /> Reject
        </button>
        <button
          type="button"
          disabled={!['Backlog', 'Approved'].includes(story.status)}
          onClick={() => void actions.cancelStory(story.story_id, 'Cancelled from AgentKit UI')}
          title="Cancel"
        >
          <CircleX size={16} /> Cancel
        </button>
      </div>

      <div className="field-editor">
        <input
          value={draftTitle}
          onChange={(event) => setDraftTitle(event.target.value)}
          placeholder={story.title}
        />
        <button
          type="button"
          disabled={draftTitle.trim().length === 0}
          onClick={() => {
            void actions.updateStoryFields(story.story_id, { title: draftTitle.trim() });
            setDraftTitle('');
          }}
        >
          Speichern
        </button>
      </div>

      <nav className="inspector-tabs">
        <button type="button" data-active={tab === 'spec'} onClick={() => setTab('spec')}>Spezifikation</button>
        <button type="button" data-active={tab === 'evidence'} onClick={() => setTab('evidence')}>Ergebnis</button>
        <button type="button" data-active={tab === 'kpi'} onClick={() => setTab('kpi')}>KPIs</button>
        <button type="button" data-active={tab === 'flow'} onClick={() => setTab('flow')}>Ablauf</button>
      </nav>

      <div className="inspector-body">
        {tab === 'spec' && (
          <section>
            <h3>Bedarf</h3>
            <p>{spec?.need || 'keine Angabe'}</p>
            <h3>Loesung</h3>
            <p>{spec?.solution || 'keine Angabe'}</p>
            <h3>Akzeptanz</h3>
            <List values={spec?.acceptance ?? []} empty="keine Akzeptanzkriterien" />
            <h3>Konzeptanker</h3>
            <List values={spec?.concept_refs ?? []} empty="keine Konzeptanker" />
          </section>
        )}
        {tab === 'evidence' && (
          <section>
            <h3>Gates</h3>
            <List values={detail.gates.map((gate) => `${gate.state}: ${gate.label}`)} empty="keine Gates" />
            <h3>Events</h3>
            <List values={detail.events.map((event) => `${event.time} ${event.type}`)} empty="keine Events" />
          </section>
        )}
        {tab === 'kpi' && (
          <section>
            <h3>Runtime</h3>
            <p>{story.processing_time || 'keine Laufzeit'}</p>
            <h3>QA</h3>
            <p>{story.qa_rounds} Runden</p>
          </section>
        )}
        {tab === 'flow' && (
          <section>
            <h3>Phasen</h3>
            <List values={detail.phases.map((phase) => `${phase.state}: ${phase.label}`)} empty="keine Phasen" />
          </section>
        )}
      </div>
    </aside>
  );
}

function List({ values, empty }: { values: string[]; empty: string }): ReactElement {
  if (values.length === 0) {
    return <p>{empty}</p>;
  }
  return (
    <ul>
      {values.map((value) => (
        <li key={value}>{value}</li>
      ))}
    </ul>
  );
}
