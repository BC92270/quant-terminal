import type { LlmRequest, LlmResponse, ResearchLlm } from './types.js';

interface ChatCompletionResponse {
  model?: string;
  choices?: Array<{ message?: { content?: string | null } }>;
}

export interface OpenAiCompatibleLlmOptions {
  id?: string;
  baseUrl: string;
  model: string;
  apiKey?: string;
  fetchImpl?: typeof fetch;
  extraHeaders?: Record<string, string>;
}

export class OpenAiCompatibleLlm implements ResearchLlm {
  public readonly id: string;
  private readonly baseUrl: string;
  private readonly model: string;
  private readonly apiKey: string | undefined;
  private readonly fetchImpl: typeof fetch;
  private readonly extraHeaders: Record<string, string>;

  public constructor(options: OpenAiCompatibleLlmOptions) {
    this.id = options.id ?? 'openai-compatible';
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.model = options.model;
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
    this.extraHeaders = options.extraHeaders ?? {};
  }

  public async complete(request: LlmRequest, signal?: AbortSignal): Promise<LlmResponse> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...this.extraHeaders,
    };
    if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`;

    const body: Record<string, unknown> = {
      model: this.model,
      messages: request.messages,
      temperature: request.temperature ?? 0.1,
    };
    if (request.maxTokens !== undefined) body.max_tokens = request.maxTokens;
    if (request.jsonMode) body.response_format = { type: 'json_object' };

    const init: RequestInit = {
      method: 'POST',
      headers,
      body: JSON.stringify(body),
    };
    if (signal) init.signal = signal;
    const response = await this.fetchImpl(`${this.baseUrl}/v1/chat/completions`, init);
    if (!response.ok) {
      throw new Error(`${this.id} completion failed: HTTP ${response.status}`);
    }
    const payload = await response.json() as ChatCompletionResponse;
    const text = payload.choices?.[0]?.message?.content?.trim();
    if (!text) throw new Error(`${this.id} returned an empty completion`);
    return { text, provider: this.id, model: payload.model ?? this.model };
  }
}
