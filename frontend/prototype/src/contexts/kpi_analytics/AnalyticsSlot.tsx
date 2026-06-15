import type { ReactElement } from 'react';

export function AnalyticsSlot(): ReactElement {
  return (
    <div className="analytics-slot" data-testid="analytics-slot">
      <div className="analytics-slot__placeholder">
        <p>Analytics werden von AG3-094 bereitgestellt.</p>
      </div>
    </div>
  );
}
