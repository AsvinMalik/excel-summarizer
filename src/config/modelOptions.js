/**
 * User-facing model selector options.
 * MODEL_A and MODEL_B are placeholder names — the product owner will rename them.
 *
 * MODEL_A  — Grounded analysis pipeline: LLM reads verified data context blocks and
 *             a grounding verifier cross-checks every figure against real computed stats.
 *
 * MODEL_B  — Pandas sandbox pipeline: the AI generates Python/pandas code and executes
 *             it directly against the uploaded data. No preview, no hallucination risk —
 *             the code execution is the ground truth.
 *
 * To rename or reconfigure either preset, edit this file only.
 */
export const MODEL_OPTIONS = [
  {
    value: 'model_a',
    label: 'Model A',
    desc: 'Grounded analysis — LLM reads verified data context',
  },
  {
    value: 'model_b',
    label: 'Model B',
    desc: 'Pandas sandbox — AI generates & runs code on your actual data',
  },
];
