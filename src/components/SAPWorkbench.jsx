import { useEffect, useRef, useState } from 'react';
import {
  Bot,
  Database,
  Download,
  Eye,
  FileSpreadsheet,
  Loader2,
  Send,
  User,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sendSAPQuery } from '../services/api';
import { PROVIDER_OPTIONS } from '../config/providerOptions';

/**
 * SAPWorkbench — autonomous SAP-connected RAG workspace.
 *
 * Replaces the manual-upload flow: the user asks a question, the backend's
 * AI router picks the SAP dataset, analyzes it, and returns the answer plus
 * the referenced-file metadata rendered in the persistent right-hand
 * "SAP Data Sources" sidebar.
 *
 * Layout: 3/4 chat column + 1/4 reference sidebar (grid-cols-4).
 */
const SAPWorkbench = () => {
  const [messages, setMessages] = useState([
    {
      id: 1,
      role: 'system',
      text: 'Connected to SAP procurement datasets. Ask about vendor spend, open purchase orders, vendor compliance, inventory, or contract expiries — I will locate the right SAP source and analyze it for you.',
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [currentReferencedFile, setCurrentReferencedFile] = useState(null);
  const [selectedProvider, setSelectedProvider] = useState(
    () => localStorage.getItem('procure_ai_provider_key') || 'auto'
  );
  const messagesEnd = useRef(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleProviderSelect = (value) => {
    setSelectedProvider(value);
    localStorage.setItem('procure_ai_provider_key', value);
  };

  const handleSend = async () => {
    const query = input.trim();
    if (!query || loading) return;
    setInput('');
    setMessages((prev) => [...prev, { id: Date.now(), role: 'user', text: query }]);
    setLoading(true);

    try {
      const res = await sendSAPQuery({ query, providerKey: selectedProvider });
      if (res.status === 'success') {
        setMessages((prev) => [
          ...prev,
          {
            id: Date.now() + 1,
            role: 'assistant',
            text: res.answer,
            referencedFile: res.referenced_file,
          },
        ]);
        if (res.referenced_file) setCurrentReferencedFile(res.referenced_file);
      } else {
        setMessages((prev) => [
          ...prev,
          { id: Date.now() + 1, role: 'error', text: res.error || 'The SAP query failed.' },
        ]);
        if (res.referenced_file) setCurrentReferencedFile(res.referenced_file);
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { id: Date.now() + 1, role: 'error', text: err.message || 'Request failed — is the backend running?' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-6 h-[78vh]">
      {/* ── MAIN CHAT AREA (3/4) ─────────────────────────────────────────── */}
      <div className="lg:col-span-3 flex flex-col rounded-[1.75rem] border border-slate-200 bg-white shadow-soft overflow-hidden">
        <div className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-sky-600 to-blue-700 text-white">
              <Database size={20} />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-800">SAP Procurement Intelligence</p>
              <p className="text-xs text-slate-500">Autonomous dataset routing · live pandas analysis</p>
            </div>
          </div>
          <select
            value={selectedProvider}
            onChange={(e) => handleProviderSelect(e.target.value)}
            title="AI provider for routing and analysis"
            className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700"
          >
            {PROVIDER_OPTIONS.map((p) => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          {messages.map((m) => (
            <div key={m.id} className={`flex gap-3 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {m.role !== 'user' && (
                <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${m.role === 'error' ? 'bg-red-100 text-red-600' : 'bg-slate-100 text-slate-600'}`}>
                  <Bot size={16} />
                </div>
              )}
              <div
                className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                  m.role === 'user'
                    ? 'bg-sky-600 text-white'
                    : m.role === 'error'
                      ? 'border border-red-200 bg-red-50 text-red-800'
                      : 'border border-slate-200 bg-slate-50 text-slate-800'
                }`}
              >
                {m.role === 'assistant' ? (
                  <div className="prose prose-sm max-w-none prose-table:text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                  </div>
                ) : (
                  m.text
                )}
                {m.referencedFile && (
                  <p className="mt-2 flex items-center gap-1.5 text-[11px] font-semibold text-emerald-700">
                    <FileSpreadsheet size={12} />
                    Source: {m.referencedFile.name}
                  </p>
                )}
              </div>
              {m.role === 'user' && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-100 text-sky-700">
                  <User size={16} />
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="flex items-center gap-2 text-sm text-slate-500">
              <Loader2 size={16} className="animate-spin" />
              Routing to the right SAP dataset and analyzing…
            </div>
          )}
          <div ref={messagesEnd} />
        </div>

        <div className="border-t border-slate-200 bg-white px-6 py-4">
          <div className="flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder='e.g. "Which vendor has the highest Q3 spend?" or "Total value of open POs"'
              className="flex-1 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm outline-none focus:border-sky-400"
              disabled={loading}
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim()}
              className="inline-flex items-center gap-2 rounded-2xl bg-sky-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-sky-600/10 transition hover:bg-sky-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Send size={16} />
              Ask
            </button>
          </div>
        </div>
      </div>

      {/* ── REFERENCE SIDEBAR (1/4): SAP Data Sources ────────────────────── */}
      <aside className="lg:col-span-1 flex flex-col rounded-[1.75rem] border border-slate-200 bg-white shadow-soft overflow-hidden">
        <div className="border-b border-slate-200 px-5 py-4">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-slate-500">SAP Data Sources</p>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-5">
          {currentReferencedFile ? (
            <div className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-4 shadow-sm">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-600 text-white">
                  <FileSpreadsheet size={20} />
                </div>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-slate-800" title={currentReferencedFile.name}>
                    {currentReferencedFile.name}
                  </p>
                  <p className="mt-0.5 text-[11px] font-medium text-emerald-700">
                    {currentReferencedFile.system || 'SAP export'}
                  </p>
                </div>
              </div>
              {currentReferencedFile.description && (
                <p className="mt-3 text-xs leading-5 text-slate-600">{currentReferencedFile.description}</p>
              )}
              {currentReferencedFile.last_updated && (
                <p className="mt-2 text-[11px] text-slate-400">Last updated: {currentReferencedFile.last_updated}</p>
              )}
              <div className="mt-4 flex gap-2">
                <button
                  type="button"
                  title="Mock action — wired to SAP download in production"
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700"
                >
                  <Download size={14} />
                  Download
                </button>
                <button
                  type="button"
                  title="Mock action — wired to dataset preview in production"
                  className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-emerald-300 bg-white px-3 py-2 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-50"
                >
                  <Eye size={14} />
                  Preview
                </button>
              </div>
            </div>
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-100 text-slate-400">
                <Database size={22} />
              </div>
              <p className="text-sm text-slate-400">No SAP tables referenced yet.</p>
              <p className="text-xs text-slate-400">Ask a question and the referenced dataset will appear here.</p>
            </div>
          )}
        </div>
      </aside>
    </div>
  );
};

export default SAPWorkbench;
