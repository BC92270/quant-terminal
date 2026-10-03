import { DeterministicScientificCompiler } from '../compiler/deterministic.js';
import { LlmScientificCompiler } from '../compiler/llm.js';
import { ResearchBrain } from './research-brain.js';
import { CrossrefConnector } from '../literature/crossref.js';
import { LiteratureService } from '../literature/service.js';
import type { ResearchLlm } from '../llm/types.js';
import { LocalStorageResearchStore } from '../storage/local-storage.js';
import type { ResearchStore } from '../storage/store.js';

export interface BrowserResearchBrainOptions {
  mailto?: string;
  llm?: ResearchLlm;
  store?: ResearchStore;
  storageKey?: string;
}

export function createBrowserResearchBrain(options: BrowserResearchBrainOptions = {}): ResearchBrain {
  const connectorOptions: { mailto?: string } = {};
  if (options.mailto) connectorOptions.mailto = options.mailto;
  const literature = new LiteratureService([new CrossrefConnector(connectorOptions)]);
  const compiler = options.llm ? new LlmScientificCompiler(options.llm) : new DeterministicScientificCompiler();
  const store = options.store ?? new LocalStorageResearchStore(options.storageKey ?? 'wm-scientific-research-v1');
  return new ResearchBrain({ literature, compiler, store });
}
