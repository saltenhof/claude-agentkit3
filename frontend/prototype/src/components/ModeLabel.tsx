/*
 * ModeLabel — Story-Mode-Anzeige im Story-Inspector-Header.
 *
 * Bei `mode === 'fast'`: auffaelliges FAST-Label mit Zap-Icon.
 * Bei Standard-Mode (`'standard'` oder undefined): dezentes
 * "STANDARD"-Label oder kein Label (Konfiguration via `showStandard`).
 *
 * FK-24 §24.3.3: Fast und Standard sind fachlich ausschliesslich;
 * der Mode-Lock ist projektweit sichtbar. Auf Story-Ebene zeigt
 * dieses Label den Story-spezifischen Mode.
 */

import { Zap } from 'lucide-react';
import type { Mode } from '../store';

interface ModeLabelProps {
  mode?: Mode;
  /** Wenn true, wird auch bei Standard-Mode ein neutrales Label gezeigt.
   *  Default: false (Standard-Mode zeigt kein Label). */
  showStandard?: boolean;
}

export function ModeLabel({ mode, showStandard = false }: ModeLabelProps) {
  const isFast = mode === 'fast';

  if (!isFast && !showStandard) return null;

  if (isFast) {
    return (
      <span
        className="mode-label mode-label--fast"
        role="img"
        aria-label="Story laeuft im Fast-Mode (FK-24 §24.3.3)"
        title="Fast-Mode: Exploration entfaellt; QA-Schichten 2–4 OUT; Story-scoped Guards deaktiviert. Nur Baseline-Guards aktiv."
      >
        <Zap size={12} aria-hidden="true" className="mode-label__icon" />
        FAST
      </span>
    );
  }

  return (
    <span
      className="mode-label mode-label--standard"
      aria-label="Story laeuft im Standard-Mode"
      title="Standard-Mode: vollstaendige 4-Phasen-Pipeline mit Exploration und QA-Subflow."
    >
      STANDARD
    </span>
  );
}
