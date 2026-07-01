/**
 * Centralized model selector config. Edit here to swap labels, add providers,
 * or change descriptions without touching component code.
 */
export const MODEL_OPTIONS = [
  {
    value: 'auto',
    label: 'Auto',
    desc: 'Best available (Phi3 → Groq → Cerebras → OpenRouter)',
  },
  {
    value: 'phi3',
    label: 'Phi3',
    desc: 'Local — fast, private, no API cost',
  },
  {
    value: 'groq',
    label: 'Groq',
    desc: 'Cloud — Llama 3.3 70B, high quality',
  },
  {
    value: 'cerebras',
    label: 'Cerebras',
    desc: 'Cloud — GPT-OSS 120B, very fast',
  },
  {
    value: 'openrouter',
    label: 'OpenRouter',
    desc: 'Cloud — free-tier models (Llama, Nemotron)',
  },
];
