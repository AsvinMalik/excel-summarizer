/**
 * API provider selector options - which LLM handles the request.
 * Applies to both Model A (answer generation) and Model B (code generation).
 */
export const PROVIDER_OPTIONS = [
  { value: 'auto',       label: 'Auto',       desc: 'Best available — Phi3 (local) first, then cloud' },
  { value: 'cerebras',   label: 'Cerebras',   desc: 'Cloud — GPT-OSS 120B, very fast' },
  { value: 'groq',       label: 'Groq',       desc: 'Cloud — Llama 3.3 70B, high quality' },
  { value: 'phi3',       label: 'Phi3',       desc: 'Local — fast, private, no API cost' },
  { value: 'openrouter', label: 'OpenRouter', desc: 'Cloud — free-tier models (rate-limited often)' },
];
