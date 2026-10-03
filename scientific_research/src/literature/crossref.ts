import type { LiteratureCandidate, LiteratureConnector, LiteratureSearchRequest } from './types.js';
import { stripHtml, uniqueStrings } from '../utils/text.js';

interface CrossrefAuthor {
  given?: string;
  family?: string;
  ORCID?: string;
  affiliation?: Array<{ name?: string }>;
}

interface CrossrefDateParts {
  'date-parts'?: number[][];
}

interface CrossrefItem {
  DOI?: string;
  title?: string[];
  author?: CrossrefAuthor[];
  published?: CrossrefDateParts;
  'published-online'?: CrossrefDateParts;
  'published-print'?: CrossrefDateParts;
  'container-title'?: string[];
  abstract?: string;
  URL?: string;
  subject?: string[];
  'is-referenced-by-count'?: number;
}

interface CrossrefResponse {
  message?: {
    items?: CrossrefItem[];
  };
}

export interface CrossrefConnectorOptions {
  fetchImpl?: typeof fetch;
  mailto?: string;
  baseUrl?: string;
}

function dateFromParts(input: CrossrefDateParts | undefined): string | undefined {
  const parts = input?.['date-parts']?.[0];
  const year = parts?.[0];
  if (!year) return undefined;
  const month = Math.min(12, Math.max(1, parts?.[1] ?? 1));
  const day = Math.min(31, Math.max(1, parts?.[2] ?? 1));
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

function buildAuthor(author: CrossrefAuthor): LiteratureCandidate['authors'][number] {
  const name = [author.given, author.family].filter(Boolean).join(' ').trim() || 'Unknown author';
  const affiliation = author.affiliation?.map((item) => item.name?.trim()).filter((value): value is string => Boolean(value)).join('; ');
  const result: LiteratureCandidate['authors'][number] = { name };
  if (author.ORCID) result.orcid = author.ORCID.replace(/^https?:\/\/orcid\.org\//, '');
  if (affiliation) result.affiliation = affiliation;
  return result;
}

export class CrossrefConnector implements LiteratureConnector {
  public readonly id = 'crossref';
  private readonly fetchImpl: typeof fetch;
  private readonly mailto: string | undefined;
  private readonly baseUrl: string;

  public constructor(options: CrossrefConnectorOptions = {}) {
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
    this.mailto = options.mailto;
    this.baseUrl = (options.baseUrl ?? 'https://api.crossref.org/v1').replace(/\/$/, '');
  }

  public async search(request: LiteratureSearchRequest, signal?: AbortSignal): Promise<LiteratureCandidate[]> {
    if (!request.query.trim()) return [];
    const limit = Math.min(50, Math.max(1, request.limit ?? 10));
    const url = new URL(`${this.baseUrl}/works`);
    url.searchParams.set('query.bibliographic', request.query.trim());
    url.searchParams.set('rows', String(limit));
    url.searchParams.set('select', 'DOI,title,author,published,container-title,abstract,URL,subject,is-referenced-by-count');
    if (this.mailto) url.searchParams.set('mailto', this.mailto);

    const filters: string[] = [];
    if (request.fromDate) filters.push(`from-pub-date:${request.fromDate}`);
    if (request.untilDate) filters.push(`until-pub-date:${request.untilDate}`);
    if (filters.length) url.searchParams.set('filter', filters.join(','));

    const init: RequestInit = {
      method: 'GET',
      headers: { Accept: 'application/json' },
    };
    if (signal) init.signal = signal;
    const response = await this.fetchImpl(url, init);
    if (!response.ok) {
      throw new Error(`Crossref search failed: HTTP ${response.status}`);
    }

    const payload = await response.json() as CrossrefResponse;
    return (payload.message?.items ?? []).flatMap((item) => {
      const title = item.title?.[0]?.trim();
      const sourceId = item.DOI?.trim() || item.URL?.trim();
      if (!title || !sourceId) return [];
      const publishedAt = dateFromParts(item.published) ?? dateFromParts(item['published-online']) ?? dateFromParts(item['published-print']);
      const candidate: LiteratureCandidate = {
        provider: this.id,
        sourceId,
        title,
        authors: (item.author ?? []).map(buildAuthor),
        subjects: uniqueStrings(item.subject ?? []),
      };
      if (publishedAt) candidate.publishedAt = publishedAt;
      const venue = item['container-title']?.[0]?.trim();
      if (venue) candidate.venue = venue;
      if (item.DOI) candidate.doi = item.DOI;
      if (item.URL) candidate.url = item.URL;
      if (item.abstract) candidate.abstract = stripHtml(item.abstract);
      if (typeof item['is-referenced-by-count'] === 'number') candidate.citationCount = item['is-referenced-by-count'];
      return [candidate];
    });
  }
}
