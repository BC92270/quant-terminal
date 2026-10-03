import type { LiteratureCandidate, LiteratureConnector, LiteratureSearchRequest } from './types.js';

export interface LiteratureSearchResult {
  candidates: LiteratureCandidate[];
  errors: Array<{ connector: string; message: string }>;
}

export class LiteratureService {
  private readonly connectors: LiteratureConnector[];

  public constructor(connectors: readonly LiteratureConnector[]) {
    this.connectors = [...connectors];
  }

  public async search(request: LiteratureSearchRequest, signal?: AbortSignal): Promise<LiteratureSearchResult> {
    const settled = await Promise.allSettled(this.connectors.map((connector) => connector.search(request, signal)));
    const candidates: LiteratureCandidate[] = [];
    const errors: LiteratureSearchResult['errors'] = [];
    const seen = new Set<string>();

    settled.forEach((result, index) => {
      const connector = this.connectors[index];
      if (!connector) return;
      if (result.status === 'rejected') {
        errors.push({ connector: connector.id, message: result.reason instanceof Error ? result.reason.message : String(result.reason) });
        return;
      }
      for (const candidate of result.value) {
        const key = candidate.doi?.toLowerCase() ?? `${candidate.provider}:${candidate.sourceId}`;
        if (seen.has(key)) continue;
        seen.add(key);
        candidates.push(candidate);
      }
    });

    candidates.sort((a, b) => {
      const citations = (b.citationCount ?? 0) - (a.citationCount ?? 0);
      if (citations !== 0) return citations;
      return (b.publishedAt ?? '').localeCompare(a.publishedAt ?? '');
    });

    return { candidates, errors };
  }
}
