/*
 * FastBadge — small Fast-mode signal next to the story ID.
 *
 * Rendered in the Story Inspector head, graph nodes, Kanban cards,
 * sheet cells and Ready Stack cards next to the story ID whenever
 * `mode = 'fast'` is set. Deliberately no text pill — just a
 * cyan-accented lightning icon so it does not consume space in the
 * card header.
 */

import { Zap } from 'lucide-react';
import type { Mode } from '../store';

export function FastBadge({ mode, size = 14 }: { mode?: Mode; size?: number }) {
  if (mode !== 'fast') return null;
  return (
    <span
      className="fast-badge"
      role="img"
      aria-label="Story laeuft im Fast-Mode"
      title="Fast-Mode (FK-24 §24.3.3): reduziertes Phasen-Profil, Story-scoped Guards aus."
    >
      <Zap size={size} />
    </span>
  );
}
