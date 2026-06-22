import type { ReactElement } from 'react';

import type { StorySummary } from '../types';

interface StorySheetProps {
  stories: readonly StorySummary[];
  onSelectStory: (storyId: string) => void;
}

export function StorySheet({ stories, onSelectStory }: Readonly<StorySheetProps>): ReactElement {
  return (
    <div className="sheet-view">
      <table>
        <thead>
          <tr>
            <th>Story</th>
            <th>Titel</th>
            <th>Status</th>
            <th>Modul</th>
            <th>Repo</th>
            <th>QA</th>
          </tr>
        </thead>
        <tbody>
          {stories.map((story) => (
            <tr key={story.story_id}>
              <td>
                <button
                  className="table-story-button"
                  type="button"
                  onClick={() => onSelectStory(story.story_id)}
                >
                  {story.story_id}
                </button>
              </td>
              <td>{story.title}</td>
              <td>{story.status}</td>
              <td>{story.module}</td>
              <td>{story.repos.join(', ')}</td>
              <td>{story.qa_rounds}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
