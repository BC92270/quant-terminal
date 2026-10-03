import type { ScientificAnalysis, ScientificPaper } from '../domain/types.js';

export interface ScientificCompiler {
  readonly id: string;
  compile(paper: ScientificPaper, signal?: AbortSignal): Promise<ScientificAnalysis>;
}
