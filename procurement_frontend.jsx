import React, { useState, useRef, useEffect } from 'react';
import { Send, Upload, FileText, Plus, Settings, LogOut, BarChart3, Zap, Search, X, Download, Menu } from 'lucide-react';

const ProcurementAssistant = () => {
  const [messages, setMessages] = useState([
    {
      id: 1,
      type: 'system',
      text: 'Welcome to Procure.ai — your enterprise procurement intelligence platform. Upload contracts, request quotations, analyze vendor data, or ask anything about your procurement operations.',
    }
  ]);
  const [input, setInput] = useState('');
  const [documents, setDocuments] = useState([
    { id: 1, name: 'Acme Corporation Agreement 2024', type: 'contract', status: 'analyzed', uploadDate: '2024-01-15' },
    { id: 2, name: 'Vendor Master Data Q4 2024', type: 'spreadsheet', status: 'indexed', uploadDate: '2024-01-14' },
    { id: 3, name: 'ServiceNow MSA - Renewal', type: 'contract', status: 'pending', uploadDate: '2024-01-13' },
  ]);
  const [activeDoc, setActiveDoc] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mode, setMode] = useState('chat'); // chat, analyze, generate, report
  const [analyzing, setAnalyzing] = useState(false);
  const messagesEnd = useRef(null);

  useEffect(() => {
    messagesEnd.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSendMessage = () => {
    if (!input.trim()) return;
    const newMessage = { id: Date.now(), type: 'user', text: input };
    setMessages([...messages, newMessage]);
    setInput('');
    setAnalyzing(true);
    setTimeout(() => {
      setAnalyzing(false);
      setMessages(prev => [...prev, {
        id: Date.now() + 1,
        type: 'assistant',
        text: 'I\'ve processed your request. Based on the uploaded contracts and vendor data, here\'s what I found...'
      }]);
    }, 1500);
  };

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (file) {
      const newDoc = {
        id: Date.now(),
        name: file.name,
        type: file.name.endsWith('.pdf') || file.name.endsWith('.docx') ? 'contract' : 'spreadsheet',
        status: 'processing',
        uploadDate: new Date().toLocaleDateString(),
      };
      setDocuments([newDoc, ...documents]);
      setMessages(prev => [...prev, {
        id: Date.now(),
        type: 'system',
        text: `📄 Processing "${file.name}"... I'll extract clauses, summarize terms, and index for search in ~30 seconds.`
      }]);
      setTimeout(() => {
        setDocuments(docs => docs.map(d => d.id === newDoc.id ? { ...d, status: 'analyzed' } : d));
      }, 2000);
    }
  };

  const QuickActions = () => (
    <div className="grid grid-cols-2 gap-2 mb-6">
      <button className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-blue-50 to-blue-100 border border-blue-200 rounded-lg hover:shadow-md transition text-sm font-medium text-blue-900">
        <Zap size={16} /> Summarize
      </button>
      <button className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-amber-50 to-amber-100 border border-amber-200 rounded-lg hover:shadow-md transition text-sm font-medium text-amber-900">
        <FileText size={16} /> Extract clauses
      </button>
      <button className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-emerald-50 to-emerald-100 border border-emerald-200 rounded-lg hover:shadow-md transition text-sm font-medium text-emerald-900">
        <Plus size={16} /> Generate RFQ
      </button>
      <button className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-purple-50 to-purple-100 border border-purple-200 rounded-lg hover:shadow-md transition text-sm font-medium text-purple-900">
        <BarChart3 size={16} /> Build report
      </button>
    </div>
  );

  const DocumentCard = ({ doc }) => (
    <div
      onClick={() => setActiveDoc(doc.id)}
      className={`p-3 rounded-lg border cursor-pointer transition ${
        activeDoc === doc.id
          ? 'bg-blue-50 border-blue-300 shadow-md'
          : 'bg-white border-gray-200 hover:border-gray-300'
      }`}
    >
      <div className="flex items-start gap-2 mb-2">
        <FileText size={18} className={activeDoc === doc.id ? 'text-blue-600' : 'text-gray-600'} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-gray-900 truncate">{doc.name}</p>
          <p className="text-xs text-gray-500">{doc.uploadDate}</p>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className={`text-xs px-2 py-1 rounded font-medium ${
          doc.status === 'analyzed' ? 'bg-green-100 text-green-800' :
          doc.status === 'indexed' ? 'bg-blue-100 text-blue-800' :
          'bg-yellow-100 text-yellow-800'
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
        {/* Header */}
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

        {/* Documents Section */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="mb-6">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Documents</h2>
            <div className="space-y-2">
              {documents.map(doc => (
                <DocumentCard key={doc.id} doc={doc} />
              ))}
            </div>
          </div>

          <label className="block w-full">
            <div className="border-2 border-dashed border-gray-600 rounded-lg p-4 text-center cursor-pointer hover:border-blue-400 hover:bg-gray-700 transition">
              <Upload size={20} className="mx-auto mb-2 text-gray-400" />
              <p className="text-xs font-medium text-gray-300">Upload contract or data</p>
              <input type="file" className="hidden" onChange={handleFileUpload} />
            </div>
          </label>
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-gray-700 space-y-2">
          <button className="w-full flex items-center gap-2 px-4 py-2 text-sm rounded-lg hover:bg-gray-700 transition text-gray-300">
            <Settings size={16} /> Settings
          </button>
          <button className="w-full flex items-center gap-2 px-4 py-2 text-sm rounded-lg hover:bg-gray-700 transition text-gray-300">
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </div>
    </div>
  );

  const MessageBubble = ({ msg }) => (
    <div className={`mb-4 flex ${msg.type === 'user' ? 'justify-end' : 'justify-start'}`}>
      <div className={`max-w-2xl px-4 py-3 rounded-lg ${
        msg.type === 'user'
          ? 'bg-blue-600 text-white rounded-br-none'
          : msg.type === 'system'
          ? 'bg-blue-50 text-blue-900 border border-blue-200'
          : 'bg-gray-100 text-gray-900'
      }`}>
        <p className="text-sm leading-relaxed">{msg.text}</p>
      </div>
    </div>
  );

  return (
    <div className="h-screen bg-white flex">
      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <div className="flex-1 flex flex-col">
        {/* Top Bar */}
        <div className="border-b border-gray-200 bg-white px-6 py-4 flex items-center justify-between">
          <button onClick={() => setSidebarOpen(!sidebarOpen)} className="lg:hidden">
            <Menu size={24} />
          </button>
          <h2 className="text-lg font-semibold text-gray-900">
            {activeDoc ? documents.find(d => d.id === activeDoc)?.name : 'Procurement Assistant'}
          </h2>
          <div className="flex items-center gap-2">
            <button className="p-2 rounded-lg hover:bg-gray-100 transition">
              <Download size={18} className="text-gray-600" />
            </button>
            <div className="w-8 h-8 bg-gradient-to-br from-blue-500 to-blue-600 rounded-full"></div>
          </div>
        </div>

        {/* Chat Area */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {messages.map(msg => (
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

        {/* Input Area */}
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
          <p className="text-xs text-gray-500 mt-3">
            💡 Tip: Try asking "Summarize Acme contract" or "Which vendors expire next month?"
          </p>
        </div>
      </div>
    </div>
  );
};

export default ProcurementAssistant;
