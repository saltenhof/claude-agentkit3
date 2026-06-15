/*
 * CopyButton — reusable copy-to-clipboard button.
 *
 * Accepts text as a string or a lazy function (for dynamic sources
 * such as the current story list). After a successful copy the icon
 * briefly switches to Check as feedback.
 */

import { useState } from 'react';
import type { MouseEvent } from 'react';
import { Check, Copy } from 'lucide-react';

export interface CopyButtonProps {
  text: string | (() => string);
  ariaLabel: string;
  disabled?: boolean;
  size?: 'sm' | 'md';
}

const RESET_DELAY_MS = 1500;

export function CopyButton({
  text,
  ariaLabel,
  disabled = false,
  size = 'md',
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  const handleClick = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    if (disabled) return;
    const value = typeof text === 'function' ? text() : text;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), RESET_DELAY_MS);
    } catch (error) {
      // eslint-disable-next-line no-console
      console.error('Copy failed', error);
    }
  };

  const className = [
    'copy-button',
    `copy-button--${size}`,
    copied ? 'copy-button--copied' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const iconSize = size === 'sm' ? 12 : 14;

  return (
    <button
      type="button"
      className={className}
      onClick={handleClick}
      disabled={disabled}
      aria-label={ariaLabel}
      title={ariaLabel}
    >
      {copied ? (
        <Check size={iconSize} strokeWidth={2.5} />
      ) : (
        <Copy size={iconSize} strokeWidth={2} />
      )}
    </button>
  );
}
