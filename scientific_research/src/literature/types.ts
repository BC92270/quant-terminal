import type { AuthorIdentity, ScientificDomain } from '../domain/types.js';

export interface LiteratureSearchRequest {
  query: string;
  limit?: number;
  fromDate?: string;
  untilDate?: string;
  domain?: ScientificDomain;
}

export interface LiteratureCandidate {
  provider: string;
  sourceId: string;
  title: string;
  authors: AuthorIdentity[];
  publishedAt?: string;
  venue?: string;
  doi?: string;
  url?: string;
  abstract?: string;
  subjects: string[];
  citationCount?: number;
}

export interface LiteratureConnector {
  readonly id: string;
  search(request: LiteratureSearchRequest, signal?: AbortSignal): Promise<LiteratureCandidate[]>;
}
