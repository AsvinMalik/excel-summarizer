const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

async function uploadDocument({ file, company, userId }) {
  const formData = new FormData();
  formData.append('file', file);
  if (company) formData.append('company', company);
  if (userId) formData.append('user_id', userId);

  const response = await fetch(`${BASE_URL}/api/upload`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    throw new Error(`Upload failed: ${response.statusText}`);
  }

  return response.json();
}

async function sendChat({ sessionId, userQuery, context, modelKey = 'model_a', providerKey = 'auto' }) {
  const response = await fetch(`${BASE_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, user_query: userQuery, context, model_key: modelKey, provider_key: providerKey }),
  });

  if (!response.ok) {
    throw new Error(`Chat request failed: ${response.statusText}`);
  }

  return response.json();
}

async function listDocuments(userId) {
  const response = await fetch(`${BASE_URL}/api/documents?user_id=${encodeURIComponent(userId)}`);
  if (!response.ok) {
    throw new Error(`Document list failed: ${response.statusText}`);
  }
  return response.json();
}

async function querySpreadsheet(query) {
  const response = await fetch(`${BASE_URL}/api/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });

  if (!response.ok) {
    throw new Error(`Query failed: ${response.statusText}`);
  }

  return response.json();
}

async function generateRFQ({ input }) {
  const response = await fetch(`${BASE_URL}/api/rfq`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    throw new Error(`RFQ generation failed: ${response.statusText}`);
  }

  return response.json();
}

async function generateReport({ sessionId, context, focus }) {
  const response = await fetch(`${BASE_URL}/api/report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, context, focus }),
  });

  if (!response.ok) {
    throw new Error(`Report generation failed: ${response.statusText}`);
  }

  return response.json();
}

async function downloadInsightsPdf({ sessionId, context }) {
  const response = await fetch(`${BASE_URL}/api/insights/pdf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, context }),
  });

  if (!response.ok) {
    throw new Error(`Insights PDF generation failed: ${response.statusText}`);
  }

  return response.blob();
}

async function analyzeForRFQ({ sessionId, context }) {
  const response = await fetch(`${BASE_URL}/api/analyze-for-rfq`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, context }),
  });

  if (!response.ok) {
    throw new Error(`RFQ analysis failed: ${response.statusText}`);
  }

  return response.json();
}

async function autoFillRFQ({ sessionId, context, vendor }) {
  const response = await fetch(`${BASE_URL}/api/auto-fill-rfq`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, context, vendor }),
  });

  if (!response.ok) {
    throw new Error(`RFQ auto-fill failed: ${response.statusText}`);
  }

  return response.json();
}

async function refineRFQDraft({ draft, instruction }) {
  const response = await fetch(`${BASE_URL}/api/rfq/refine`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft, instruction }),
  });

  if (!response.ok) {
    throw new Error(`RFQ refinement failed: ${response.statusText}`);
  }

  return response.json();
}

async function exportRFQPdf({ draft }) {
  const response = await fetch(`${BASE_URL}/api/rfq/export-pdf`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ draft }),
  });

  if (!response.ok) {
    throw new Error(`RFQ export failed: ${response.statusText}`);
  }

  return response.blob();
}

async function getDocumentMeta(docId) {
  const response = await fetch(`${BASE_URL}/api/document/${encodeURIComponent(docId)}`);
  if (!response.ok) throw new Error(`Meta fetch failed: ${response.statusText}`);
  return response.json();
}

async function fetchSheetData({ docId, sheetName, offset = 0, limit = 100 }) {
  const params = new URLSearchParams({ offset, limit });
  const response = await fetch(
    `${BASE_URL}/api/document/${encodeURIComponent(docId)}/sheet/${encodeURIComponent(sheetName)}?${params}`
  );
  if (!response.ok) {
    throw new Error(`Sheet data fetch failed: ${response.statusText}`);
  }
  return response.json();
}

export {
  uploadDocument,
  sendChat,
  listDocuments,
  querySpreadsheet,
  generateRFQ,
  generateReport,
  downloadInsightsPdf,
  analyzeForRFQ,
  autoFillRFQ,
  refineRFQDraft,
  exportRFQPdf,
  fetchSheetData,
  getDocumentMeta,
};