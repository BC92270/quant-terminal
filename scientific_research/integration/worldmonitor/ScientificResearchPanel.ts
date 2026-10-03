// COPY TO: src/components/ScientificResearchPanel.ts
// Not part of the standalone build because the provided archive is missing the full
// World Monitor src/app panel-layout implementation. This wrapper uses the Panel API
// that *is* present in the archive and is intentionally minimal.

import { Panel } from './Panel';
import {
  createBrowserResearchBrain,
  OpenAiCompatibleLlm,
  ResearchWorkbench,
  type ResearchLlm,
} from '@/scientific-research';

export interface ScientificResearchPanelOptions {
  ollamaBaseUrl?: string;
  ollamaModel?: string;
}

export class ScientificResearchPanel extends Panel {
  private workbench: ResearchWorkbench | null = null;

  public constructor(options: ScientificResearchPanelOptions = {}) {
    super({
      id: 'scientific-research',
      title: 'Scientific Research Brain',
      showCount: false,
      className: 'scientific-research-panel span-4',
      infoTooltip: 'Phase 1: literature intelligence, scientific compilation, persistent memory, provenance, and structural transfer screening.',
    });

    let llm: ResearchLlm | undefined;
    if (options.ollamaBaseUrl && options.ollamaModel) {
      llm = new OpenAiCompatibleLlm({
        id: 'ollama-research',
        baseUrl: options.ollamaBaseUrl,
        model: options.ollamaModel,
      });
    }

    const brain = createBrowserResearchBrain(llm ? { llm } : {});
    this.workbench = new ResearchWorkbench({ brain });
    this.content.replaceChildren();
    void this.workbench.mount(this.content);
    this.setDataBadge('live', llm ? 'LLM compiler' : 'deterministic compiler');
  }

  public override destroy(): void {
    this.workbench?.destroy();
    this.workbench = null;
    super.destroy();
  }
}
