/*
 * FastBadge — kleines Fast-Mode-Signal hinter der Story-ID.
 *
 * Wird im Story-Inspector-Head, in Graph-Knoten, Kanban-Karten,
 * Sheet-Zellen und Ready-Stack-Kaerten neben der Story-ID gerendert,
 * sobald `mode = 'fast'` gesetzt ist. Bewusst kein Text-Pill -- nur
 * ein cyan-akzentuiertes Blitz-Icon, damit es im Card-Header keinen
 * Platz frisst.
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
