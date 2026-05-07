/*
 * NumberStepper — wiederverwendbarer Zahleneingabe-Stepper im Dark-Theme.
 *
 * Ersetzt das native <input type="number"> samt Browser-Spinner, die
 * sich nicht ins Theme einfuegen. Eigene Buttons + ein zentrierter
 * Input geben volle Kontrolle ueber Farben, Borders und Hover-States.
 */

import { Minus, Plus } from 'lucide-react';

export interface NumberStepperProps {
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  ariaLabel?: string;
}

export function NumberStepper({
  value,
  onChange,
  min = 0,
  max,
  step = 1,
  ariaLabel,
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
        disabled={value <= min}
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
        onChange={(event) => {
          const parsed = Number(event.target.value);
          onChange(clamp(parsed));
        }}
      />
      <button
        type="button"
        className="number-stepper__btn"
        onClick={increment}
        disabled={max !== undefined && value >= max}
        aria-label="Erhöhen"
      >
        <Plus size={14} strokeWidth={2.5} />
      </button>
    </div>
  );
}
