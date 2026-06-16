/*
 * NumberStepper — reusable numeric input stepper for the dark theme.
 *
 * Replaces the native <input type="number"> together with its browser
 * spinner, which cannot be styled to match the theme. Custom buttons
 * plus a centred input give full control over colors, borders and
 * hover states.
 */

import { Minus, Plus } from 'lucide-react';

export interface NumberStepperProps {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  ariaLabel?: string;
  /** Disable all controls — used when offline or project is archived (AC6). */
  disabled?: boolean;
}

export function NumberStepper({
  value,
  onChange,
  min = 0,
  max,
  step = 1,
  ariaLabel,
  disabled = false,
}: NumberStepperProps) {
  const clamp = (next: number): number => {
    if (Number.isNaN(next)) return value;
    let result = next;
    if (min !== undefined) result = Math.max(min, result);
    if (max !== undefined) result = Math.min(max, result);
    return result;
  };

  const decrement = () => onChange(clamp(value - step));
  const increment = () => onChange(clamp(value + step));

  return (
    <div className="number-stepper" role="group" aria-label={ariaLabel}>
      <button
        type="button"
        className="number-stepper__btn"
        onClick={decrement}
        disabled={disabled || value <= min}
        aria-label="Verringern"
      >
        <Minus size={14} strokeWidth={2.5} />
      </button>
      <input
        type="number"
        className="number-stepper__input"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => {
          const parsed = Number(event.target.value);
          onChange(clamp(parsed));
        }}
      />
      <button
        type="button"
        className="number-stepper__btn"
        onClick={increment}
        disabled={disabled || (max !== undefined && value >= max)}
        aria-label="Erhöhen"
      >
        <Plus size={14} strokeWidth={2.5} />
      </button>
    </div>
  );
}
