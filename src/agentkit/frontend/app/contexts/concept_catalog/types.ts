export type ConceptLayer = 'domain' | 'technical' | 'formal';

export interface ConceptRef {
  concept_id: string;
  path: string;
  layer: ConceptLayer;
  title: string;
  status: string;
  domain: string | null;
  tags: string[];
  cross_cutting: boolean;
  defers_to: string[];
  formal_refs: string[];
}

export interface ConceptSearchHit {
  ref: string;
  title: string;
  snippet: string;
  score: number;
}
