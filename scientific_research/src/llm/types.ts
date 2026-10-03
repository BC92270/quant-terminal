export interface LlmMessage {
  role: 'system' | 'user' | 'assistant';
  content: string;
}

export interface LlmRequest {
  messages: LlmMessage[];
  temperature?: number;
  maxTokens?: number;
  jsonMode?: boolean;
}

export interface LlmResponse {
  text: string;
  provider: string;
  model: string;
}

export interface ResearchLlm {
  readonly id: string;
  complete(request: LlmRequest, signal?: AbortSignal): Promise<LlmResponse>;
}
