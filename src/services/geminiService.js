import { getGenerativeModel } from 'firebase/vertexai-preview';
import { vertexAI, isFirebaseConfigured } from '../firebase';

const DEFAULT_MODEL = 'gemini-2.0-flash';

export const isGeminiAvailable = () => Boolean(isFirebaseConfigured && vertexAI);

export const generateProcurementReply = async ({ prompt, systemInstruction }) => {
  if (!isGeminiAvailable()) {
    throw new Error(
      'Firebase is not fully configured. Add your Web App config to .env (see .env.example).'
    );
  }

  const model = getGenerativeModel(vertexAI, {
    model: DEFAULT_MODEL,
    systemInstruction,
  });

  const result = await model.generateContent(prompt);
  return result.response.text();
};

export const streamProcurementReply = async ({ prompt, systemInstruction, onChunk }) => {
  if (!isGeminiAvailable()) {
    throw new Error(
      'Firebase is not fully configured. Add your Web App config to .env (see .env.example).'
    );
  }

  const model = getGenerativeModel(vertexAI, {
    model: DEFAULT_MODEL,
    systemInstruction,
  });

  const streamResult = await model.generateContentStream(prompt);
  let fullText = '';

  for await (const chunk of streamResult.stream) {
    const chunkText = chunk.text();
    fullText += chunkText;
    if (onChunk) {
      onChunk(chunkText, fullText);
    }
  }

  return fullText;
};
