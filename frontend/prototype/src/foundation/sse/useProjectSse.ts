/**
 * useProjectSse — frontend SSE consumer hook (AG3-094, FK-72 §72.12).
 *
 * Pattern: Initial-GET + EventSource subscribe (FK-72 §72.12.1 Z.270).
 * - On mount or (re-)connect: fires onReconnect() which the caller uses for
 *   a fresh initial-GET re-sync (lossy-re-sync, FK-72 §72.12.4 Z.306).
 * - On relevant server-sent event: fires onEvent(event) so the caller can
 *   re-fetch or field-patch depending on the topic.
 * - Browser EventSource auto-reconnects on network drops (WHATWG SSE spec).
 * - When the EventSource fails to connect (error event without any previous
 *   open): calls onOffline() so the shell can show the "Verbindung verloren"
 *   indicator (FK-72 §72.14.6 Z.503).
 * - NO frontend REST polling loop (FK-72 §72.12.1 Z.281).
 *
 * Topic sets are typed (ARCH-55 English identifiers, no free strings).
 * The server enforces topic filtering; the client only books the topics it needs.
 */

import { useEffect, useRef } from 'react';

/** Typed SSE topic identifiers (FK-91 §91.8.3 / FK-72 §72.5). */
export type SseTopic = 'kpi' | 'telemetry' | 'failure_corpus' | 'stories' | 'phases' | 'planning';

/** Typed topic sets per view (FK-72 §72.5, FK-91 §91.8.3). */
export const ANALYTICS_TOPICS: readonly SseTopic[] = ['kpi', 'telemetry', 'failure_corpus'];
export const KANBAN_TOPICS: readonly SseTopic[] = ['stories', 'phases'];
export const GRAPH_TOPICS: readonly SseTopic[] = ['planning'];

export interface SseEvent {
  topic: string;
  data: unknown;
  rawEvent: MessageEvent;
}

export interface UseProjectSseOptions {
  /** Backend base URL (empty = relative). */
  baseUrl: string;
  /** Project key to scope the SSE stream. */
  projectKey: string;
  /** Topic set to subscribe to. */
  topics: readonly SseTopic[];
  /** Called on every (re-)connect, including the initial open. Use to fire the initial-GET re-sync. */
  onReconnect: () => void;
  /** Called when a server event arrives. */
  onEvent: (event: SseEvent) => void;
  /** Called when the connection cannot be established or is lost (offline indicator). */
  onOffline?: () => void;
  /** Called when the connection (re-)opens after an offline period. */
  onOnline?: () => void;
  /** Whether to subscribe. When false the EventSource is not opened. */
  enabled?: boolean;
}

/**
 * Subscribe to the project-scoped SSE stream.
 *
 * Does NOT fire `onReconnect` in unit tests when window.EventSource is
 * undefined — callers that inject a mock transport must set enabled=false
 * or provide a jsdom EventSource shim.
 */
export function useProjectSse({
  baseUrl,
  projectKey,
  topics,
  onReconnect,
  onEvent,
  onOffline,
  onOnline,
  enabled = true,
}: UseProjectSseOptions): void {
  const onReconnectRef = useRef(onReconnect);
  const onEventRef = useRef(onEvent);
  const onOfflineRef = useRef(onOffline);
  const onOnlineRef = useRef(onOnline);

  onReconnectRef.current = onReconnect;
  onEventRef.current = onEvent;
  onOfflineRef.current = onOffline;
  onOnlineRef.current = onOnline;

  useEffect(() => {
    if (!enabled) return;
    if (typeof window === 'undefined' || typeof window.EventSource === 'undefined') return;

    const topicsParam = topics.join(',');
    const url = `${baseUrl}/v1/projects/${encodeURIComponent(projectKey)}/events?topics=${encodeURIComponent(topicsParam)}`;

    let es: EventSource;

    const open = () => {
      es = new window.EventSource(url);

      es.onopen = () => {
        onOnlineRef.current?.();
        // Every (re-)connect triggers a fresh initial-GET re-sync (lossy,
        // FK-72 §72.12.4 Z.306: no sequence-cursor, no acknowledge).
        onReconnectRef.current();
      };

      es.onerror = () => {
        // Fire offline for BOTH: initial failure (never opened) AND drops on an
        // already-established stream (E4 fix — FK-72 §72.14.6 Z.503).
        // The browser EventSource auto-reconnects; onopen fires again on restore
        // and calls onOnline + onReconnect for the lossy re-sync.
        onOfflineRef.current?.();
      };

      es.onmessage = (rawEvent: MessageEvent) => {
        let data: unknown;
        try {
          data = JSON.parse(rawEvent.data as string);
        } catch {
          data = rawEvent.data;
        }
        // topic is carried in event.lastEventId or a custom "event:" field.
        // When the server sends "event: kpi\ndata: {...}", rawEvent.type === 'kpi'.
        // For generic "data: {...}" messages rawEvent.type === 'message'.
        const topic = rawEvent.type === 'message' ? 'message' : rawEvent.type;
        onEventRef.current({ topic, data, rawEvent });
      };

      // Also subscribe to named topic events (server sends "event: <topic>").
      for (const topic of topics) {
        es.addEventListener(topic, (rawEvent: MessageEvent) => {
          let data: unknown;
          try {
            data = JSON.parse(rawEvent.data as string);
          } catch {
            data = rawEvent.data;
          }
          onEventRef.current({ topic, data, rawEvent });
        });
      }
    };

    open();

    return () => {
      es.close();
    };
    // topics is intentionally not in deps — it is typed const per view; changes
    // require a full re-mount which is controlled by the caller via enabled/projectKey.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl, projectKey, enabled]);
}
