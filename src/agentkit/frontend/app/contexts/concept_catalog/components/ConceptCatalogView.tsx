import { BookOpen, Search } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { ReactElement } from 'react';

import type { ConceptLayer, ConceptRef, ConceptSearchHit } from '../types';

interface ConceptCatalogViewProps {
  concepts: readonly ConceptRef[];
  error: string | null;
  searchConcepts: (query: string) => Promise<ConceptSearchHit[]>;
}

type LayerFilter = 'all' | ConceptLayer;

export function ConceptCatalogView({ concepts, error, searchConcepts }: Readonly<ConceptCatalogViewProps>): ReactElement {
  const [layerFilter, setLayerFilter] = useState<LayerFilter>('all');
  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<ConceptSearchHit[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const filteredConcepts = useMemo(
    () => concepts.filter((concept) => layerFilter === 'all' || concept.layer === layerFilter),
    [concepts, layerFilter],
  );
  const byLayer = useMemo(() => countByLayer(concepts), [concepts]);

  const runSearch = (): void => {
    const trimmed = query.trim();
    if (trimmed.length === 0) {
      setHits([]);
      setSearchError(null);
      return;
    }
    searchConcepts(trimmed)
      .then((result) => {
        setHits(result);
        setSearchError(null);
      })
      .catch((err: unknown) => {
        setHits([]);
        setSearchError(err instanceof Error ? err.message : 'Concept search failed.');
      });
  };

  return (
    <div className="concept-catalog">
      <header className="context-head">
        <div>
          <p className="eyebrow">Concept Catalog</p>
          <h2>Authoritative Concepts</h2>
        </div>
        <div className="context-health" data-health={error === null ? 'ok' : 'down'}>
          <BookOpen size={16} />
          <span>{concepts.length} refs</span>
        </div>
      </header>

      {error !== null && <div className="context-warning">{error}</div>}

      <section className="hub-summary-grid">
        <ConceptStat label="Domain" value={String(byLayer.domain)} />
        <ConceptStat label="Technical" value={String(byLayer.technical)} />
        <ConceptStat label="Formal" value={String(byLayer.formal)} />
        <ConceptStat label="Cross Cutting" value={String(concepts.filter((concept) => concept.cross_cutting).length)} />
      </section>

      <section className="concept-toolbar">
        <div className="analytics-tabs">
          {(['all', 'domain', 'technical', 'formal'] as const).map((layer) => (
            <button className={layerFilter === layer ? 'active' : ''} key={layer} type="button" onClick={() => setLayerFilter(layer)}>
              {layer}
            </button>
          ))}
        </div>
        <label className="concept-search">
          <Search size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                runSearch();
              }
            }}
            placeholder="Concept Catalog durchsuchen"
          />
          <button type="button" onClick={runSearch}>Search</button>
        </label>
      </section>

      {(hits.length > 0 || searchError !== null) && (
        <section className="concept-search-results">
          <h3>Search Results</h3>
          {searchError !== null && <div className="context-warning">{searchError}</div>}
          {hits.map((hit) => (
            <article key={hit.ref}>
              <strong>{hit.ref} · {hit.title}</strong>
              <p>{hit.snippet}</p>
            </article>
          ))}
        </section>
      )}

      <section className="concept-grid">
        {filteredConcepts.map((concept) => <ConceptCard concept={concept} key={concept.concept_id} />)}
        {filteredConcepts.length === 0 && <div className="context-empty">Keine Concepts für diesen Filter.</div>}
      </section>
    </div>
  );
}

function ConceptCard({ concept }: Readonly<{ concept: ConceptRef }>): ReactElement {
  return (
    <article className="concept-card">
      <header>
        <span>{concept.concept_id}</span>
        <strong>{concept.title}</strong>
      </header>
      <dl className="detail-list">
        <div><dt>Layer</dt><dd>{concept.layer}</dd></div>
        <div><dt>Status</dt><dd>{concept.status}</dd></div>
        <div><dt>Domain</dt><dd>{concept.domain ?? '-'}</dd></div>
      </dl>
      <div className="concept-tags">
        {concept.tags.map((tag) => <span key={`${concept.concept_id}-${tag}`}>{tag}</span>)}
      </div>
      <small>{compactPath(concept.path)}</small>
    </article>
  );
}

function ConceptStat({ label, value }: Readonly<{ label: string; value: string }>): ReactElement {
  return (
    <article className="context-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function countByLayer(concepts: readonly ConceptRef[]): Record<ConceptLayer, number> {
  return concepts.reduce<Record<ConceptLayer, number>>(
    (counts, concept) => ({ ...counts, [concept.layer]: counts[concept.layer] + 1 }),
    { domain: 0, technical: 0, formal: 0 },
  );
}

function compactPath(path: string): string {
  return path.replaceAll('\\', '/').split('/').slice(-3).join('/');
}
