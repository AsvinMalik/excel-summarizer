import React, { useState, useRef, useEffect } from 'react';
import {
  Send,
  Upload,
  FileText,
  Plus,
  Settings,
  LogOut,
  BarChart3,
  Zap,
  X,
  Download,
  Menu,
  Loader2,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeRaw from 'rehype-raw';
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize';
import { uploadDocument, sendChat, downloadInsightsPdf } from '../services/api';
import { saveDocumentMetadata, deleteDocumentMetadata, getUserDocuments, saveChatMessage } from '../services/firestoreService';
import { useAuth } from '../context/AuthContext';

const ProcurementAssistant = () => {
  const [messages, setMessages] = useState([
    {
      id: 1,
      type: 'system',
      text: 'Welcome to Procure.ai — your enterprise procurement intelligence platform. Upload contracts, request quotations, analyze vendor data, or ask anything about your procurement operations.',
    },
  ]);
  const [input, setInput] = useState('');
  const [documents, setDocuments] = useState([]);
  const [activeDoc, setActiveDoc] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [downloadingInsights, setDownloadingInsights] = useState(false);
  const [sessionId] = useState(() => localStorage.getItem('procure_session') || `session-${Date.now()}`);
  const { user, logout } = useAuth();
  const messagesEnd = useRef(null);

  useEffect(() => {
    localStorage.setItem('procure_session', sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (!user) return;

    let cancelled = false;
    getUserDocuments(user.uid)
      .then((storedDocs) => {
        if (!cancelled && storedDocs.length > 0) {
          setDocuments(storedDocs);
        }
      })
      .catch((error) => {
        console.error('Failed to load documents from Firestore:', error);
      });

    return () => {
      cancelled = true;
    };
  }, [user]);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = async (overrideText) => {
    const userText = (overrideText ?? input).trim();
    if (!userText) return;
    const newMessage = { id: Date.now(), type: 'user', text: userText };
    setMessages((prev) => [...prev, newMessage]);
    if (overrideText === undefined) setInput('');
    setAnalyzing(true);

    try {
      const activeDocument = activeDoc ? documents.find((doc) => doc.id === activeDoc) : null;
      const context = {
        active_document: activeDocument
          ? { doc_id: activeDocument.doc_id, name: activeDocument.name, type: activeDocument.type, status: activeDocument.status }
          : null,
        documents: documents.map((doc) => ({ doc_id: doc.doc_id, id: doc.id, name: doc.name, type: doc.type, status: doc.status })),
      };

      const response = await sendChat({ sessionId, userQuery: userText, context });
      const assistantText = Array.isArray(response.response)
        ? response.response
            .map((block) => (typeof block === 'string' ? block : block.text || JSON.stringify(block)))
            .join('\n\n')
        : response.response?.toString() || 'No response available.';

      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          type: 'assistant',
          text: assistantText,
        },
      ]);

      if (user) {
        saveChatMessage(user.uid, sessionId, 'user', userText).catch(() => {});
        saveChatMessage(user.uid, sessionId, 'assistant', assistantText).catch(() => {});
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 1,
          type: 'assistant',
          text: `Error: ${error.message}`,
        },
      ]);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDownloadInsights = async () => {
    if (downloadingInsights) return;
    setDownloadingInsights(true);
    try {
      const activeDocument = activeDoc ? documents.find((doc) => doc.id === activeDoc) : null;
      const context = {
        active_document: activeDocument
          ? { doc_id: activeDocument.doc_id, name: activeDocument.name, type: activeDocument.type, status: activeDocument.status }
          : null,
        documents: documents.map((doc) => ({ doc_id: doc.doc_id, id: doc.id, name: doc.name, type: doc.type, status: doc.status })),
      };

      const blob = await downloadInsightsPdf({ sessionId, context });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'procure_ai_insights.pdf';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 3,
          type: 'assistant',
          text: `Error generating insights report: ${error.message}`,
        },
      ]);
    } finally {
      setDownloadingInsights(false);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const isContract = file.name.toLowerCase().endsWith('.pdf') || file.name.toLowerCase().endsWith('.docx');
    const isSpreadsheet = file.name.toLowerCase().endsWith('.xlsx') || file.name.toLowerCase().endsWith('.xls') || file.name.toLowerCase().endsWith('.csv');
    const newDoc = {
      id: Date.now(),
      name: file.name,
      type: isContract ? 'contract' : isSpreadsheet ? 'spreadsheet' : 'data',
      status: 'processing',
      uploadDate: new Date().toLocaleDateString(),
    };
    setDocuments((prev) => [newDoc, ...prev]);
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now() + 2,
        type: 'system',
        text: `📄 Uploading "${file.name}" and starting processing...`,
      },
    ]);

    try {
      const result = await uploadDocument({ file, company: 'Procure.ai', userId: user?.uid || 'anon' });
      setDocuments((docs) => docs.map((doc) => (doc.id === newDoc.id ? { ...doc, status: 'analyzed', doc_id: result.doc_id } : doc)));
      if (user) {
        await saveDocumentMetadata(user.uid, { ...newDoc, doc_id: result.doc_id, status: 'analyzed' });
      }
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 3,
          type: 'assistant',
          text: `Upload complete: ${result.filename} is queued for analysis.`,
        },
      ]);
    } catch (error) {
      setDocuments((docs) => docs.filter((doc) => doc.id !== newDoc.id));
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now() + 3,
          type: 'assistant',
          text: `Upload failed: ${error.message}`,
        },
      ]);
    }
  };

  const handleDeleteDocument = async (id) => {
    const docToDelete = documents.find((d) => d.id === id);
    if (!docToDelete) return;
    // Attempt backend delete if doc has a backend id
      if (docToDelete.doc_id) {
      try {
        await fetch(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/document/${encodeURIComponent(docToDelete.doc_id)}`, { method: 'DELETE' });
      } catch (e) {
        // ignore network errors for demo
      }
        if (user) {
          try {
            await deleteDocumentMetadata(user.uid, docToDelete.doc_id);
          } catch (e) {
            // ignore Firestore delete errors for now
          }
        }
    }
    setDocuments((prev) => prev.filter((d) => d.id !== id));
    setMessages((prev) => [
      ...prev,
      { id: Date.now() + 7, type: 'system', text: `Deleted document: ${docToDelete.name}` },
    ]);
  };

  const quickActions = [
    {
      id: 'summarize',
      label: 'Summarize',
      icon: Zap,
      gradient: 'from-blue-50 to-blue-100',
      border: 'border-blue-200',
      text: 'text-blue-900',
      buildPrompt: (activeDocument) =>
        activeDocument
          ? `Summarize "${activeDocument.name}" and highlight the key points.`
          : 'Summarize the uploaded documents and highlight the key points.',
    },
    {
      id: 'extract-clauses',
      label: 'Extract clauses',
      icon: FileText,
      gradient: 'from-amber-50 to-amber-100',
      border: 'border-amber-200',
      text: 'text-amber-900',
      buildPrompt: (activeDocument) =>
        activeDocument
          ? `Extract the key clauses (payment, termination, indemnity, SLA, renewal) from "${activeDocument.name}".`
          : 'Extract key clauses (payment, termination, indemnity, SLA, renewal) from the uploaded contracts.',
    },
    {
      id: 'generate-rfq',
      label: 'Generate RFQ',
      icon: Plus,
      gradient: 'from-emerald-50 to-emerald-100',
      border: 'border-emerald-200',
      text: 'text-emerald-900',
      buildPrompt: (activeDocument) =>
        activeDocument
          ? `Generate a professional RFQ based on "${activeDocument.name}".`
          : 'Generate a professional RFQ template for our procurement needs.',
    },
    {
      id: 'build-report',
      label: 'Build report',
      icon: BarChart3,
      gradient: 'from-purple-50 to-purple-100',
      border: 'border-purple-200',
      text: 'text-purple-900',
      buildPrompt: (activeDocument) =>
        activeDocument
          ? `Build an executive report summarizing spend, risk, and vendor performance based on "${activeDocument.name}".`
          : 'Build an executive procurement report summarizing spend, risk, and vendor performance.',
    },
  ];

  const handleQuickAction = (action) => {
    if (analyzing) return;
    const activeDocument = activeDoc ? documents.find((doc) => doc.id === activeDoc) : null;
    handleSendMessage(action.buildPrompt(activeDocument));
  };

  const QuickActions = () => (
    <div className="grid grid-cols-2 gap-2 mb-6">
      {quickActions.map((action) => (
        <button
          key={action.id}
          type="button"
          onClick={() => handleQuickAction(action)}
          disabled={analyzing}
          className={`flex items-center gap-2 px-3 py-2 bg-gradient-to-r ${action.gradient} border ${action.border} rounded-lg hover:shadow-md transition text-sm font-medium ${action.text} disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          <action.icon size={16} /> {action.label}
        </button>
      ))}
    </div>
  );

  const DocumentCard = ({ doc }) => (
    <div
      onClick={() => setActiveDoc(doc.id)}
      className={`relative p-3 rounded-lg border cursor-pointer transition ${
        activeDoc === doc.id
          ? 'bg-blue-50 border-blue-300 shadow-md'
          : 'bg-white border-gray-200 hover:border-gray-300'
      }`}
    >
      <button
        onClick={(e) => {
          e.stopPropagation();
          handleDeleteDocument(doc.id);
        }}
        className="absolute top-2 right-2 w-6 h-6 flex items-center justify-center rounded-full hover:bg-gray-100 text-gray-500"
        aria-label="Delete document"
      >
        <X size={14} />
      </button>
      <div className="flex items-start gap-2 mb-2">
        <FileText size={18} className={activeDoc === doc.id ? 'text-blue-600' : 'text-gray-600'} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">{doc.name}</p>
          <p className="text-xs text-gray-500">{doc.uploadDate}</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className={`text-xs px-2 py-1 rounded font-medium ${
          doc.status === 'analyzed' ? 'bg-green-100 text-green-800' : doc.status === 'indexed' ? 'bg-blue-100 text-blue-800' : 'bg-yellow-100 text-yellow-800'
        }`}>
          {doc.status === 'analyzed' ? '✓ Ready' : doc.status === 'indexed' ? '🔍 Indexed' : '⏳ Processing'}
        </span>
      </div>
    </div>
  );

  const Sidebar = () => (
    <div className={`fixed inset-y-0 left-0 w-72 bg-gradient-to-b from-gray-900 to-gray-800 text-white transform transition z-40 ${
      sidebarOpen ? 'translate-x-0' : '-translate-x-full'
    } lg:relative lg:translate-x-0`}>
      <div className="h-full flex flex-col">
        <div className="p-6 border-b border-gray-700">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-gradient-to-br from-blue-400 to-blue-600 rounded-lg flex items-center justify-center">
                <span className="text-white font-bold">P</span>
              </div>
              <h1 className="text-lg font-bold">Procure.ai</h1>
            </div>
            <button onClick={() => setSidebarOpen(false)} className="lg:hidden">
              <X size={20} />
            </button>
          </div>
          <p className="text-xs text-gray-400">Enterprise Procurement Platform</p>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-6">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Documents</h2>
            <div className="space-y-2">
              {documents.map((doc) => (
                <DocumentCard key={doc.id} doc={doc} />
              ))}
            </div>
          </div>

              <label className="block w-full">
                <div className="border-2 border-dashed border-gray-600 rounded-lg p-4 text-center cursor-pointer hover:border-blue-400 hover:bg-gray-700 transition">
                  <Upload size={20} className="mx-auto mb-2 text-gray-400" />
                  <p className="text-xs font-medium text-gray-300">Upload contract or data</p>
                  <p className="text-xs text-gray-500 mt-1">Accepted: PDF, DOCX, XLSX, XLS, CSV</p>
                  <input type="file" className="hidden" onChange={handleFileUpload} accept=".pdf,.docx,.xlsx,.xls,.csv" />
                </div>
              </label>
        </div>

        <div className="p-6 border-t border-gray-700 space-y-2">
          <button className="w-full flex items-center gap-2 px-4 py-2 text-sm rounded-lg hover:bg-gray-700 transition text-gray-300">
            <Settings size={16} /> Settings
          </button>
          <button
            onClick={logout}
            className="w-full flex items-center gap-2 px-4 py-2 text-sm rounded-lg hover:bg-gray-700 transition text-gray-300"
          >
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </div>
    </div>
  );

  const MessageBubble = ({ msg }) => (
    <div className={`mb-4 flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
      <div className={`px-4 py-3 rounded-lg ${msg.type === 'user' ? 'max-w-2xl' : 'max-w-[min(94%,72rem)]'} ${
        msg.type === 'user'
          ? 'bg-blue-600 text-white rounded-br-none'
          : msg.type === 'system'
          ? 'bg-blue-50 text-blue-900 border border-blue-200'
          : 'bg-gray-100 text-gray-900'
      }`}>
        {msg.type === 'user' ? (
          <p className="text-sm leading-relaxed">{msg.text}</p>
        ) : (
          <div className="prose prose-sm max-w-none overflow-x-auto prose-headings:mt-3 prose-headings:mb-2 prose-headings:font-semibold prose-p:my-2">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeRaw, [rehypeSanitize, defaultSchema]]}
              components={{
                table: ({ node, ...props }) => (
                  <table className="w-full border-collapse my-3 text-sm" {...props} />
                ),
                thead: ({ node, ...props }) => <thead className="bg-slate-100" {...props} />,
                tr: ({ node, ...props }) => <tr className="even:bg-slate-50" {...props} />,
                th: ({ node, ...props }) => (
                  <th className="border border-slate-300 px-3 py-2 text-left font-semibold text-slate-700" {...props} />
                ),
                td: ({ node, ...props }) => (
                  <td className="border border-slate-200 px-3 py-2 align-top" {...props} />
                ),
              }}
            >
              {msg.text}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <div className="h-[85vh] bg-slate-50 flex overflow-hidden rounded-[2rem] border border-slate-200 shadow-soft">
      <Sidebar />

      <div className="flex-1 flex flex-col">
        <div className="border-b border-gray-200 bg-white px-6 py-4 flex items-center justify-between">
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="lg:hidden">
            <Menu size={24} />
          </button>
          <h2 className="text-lg font-semibold text-gray-900">{activeDoc ? documents.find((d) => d.id === activeDoc)?.name : 'Procurement Assistant'}</h2>
          <div className="flex items-center gap-2">
            <div className="relative group">
              <button
                onClick={handleDownloadInsights}
                disabled={downloadingInsights}
                className="p-2 rounded-lg hover:bg-gray-100 transition disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {downloadingInsights ? (
                  <Loader2 size={18} className="text-gray-600 animate-spin" />
                ) : (
                  <Download size={18} className="text-gray-600" />
                )}
              </button>
              <span className="pointer-events-none absolute right-0 top-full mt-2 whitespace-nowrap rounded-md bg-gray-900 px-2.5 py-1.5 text-xs font-medium text-white opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100 z-10">
                {downloadingInsights ? 'Generating insights…' : 'Download insights'}
              </span>
            </div>
            <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-blue-600 rounded-full"></div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}
          {analyzing && (
            <div className="flex justify-start">
              <div className="bg-gray-100 text-gray-900 px-4 py-3 rounded-lg rounded-bl-none">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 bg-gray-600 rounded-full animate-bounce"></div>
                  <p className="text-sm">Analyzing documents...</p>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEnd} />
        </div>

        <div className="border-t border-gray-200 bg-white p-6">
          <QuickActions />
          <div className="flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyPress={(e) => e.key === 'Enter' && handleSendMessage()}
              placeholder="Ask about contract terms, vendor performance, spend analysis, RFQs..."
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            />
            <button
              onClick={handleSendMessage}
              disabled={!input.trim()}
              className="px-4 py-3 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:shadow-lg transition disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <Send size={18} />
            </button>
          </div>
          <p className="text-xs text-gray-500 mt-3">💡 Tip: Try asking "Summarize Acme contract" or "Which vendors expire next month?"</p>
        </div>
      </div>
    </div>
  );
};

export default ProcurementAssistant;
