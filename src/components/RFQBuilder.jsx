import { useState } from 'react';
import { Download, FileText, ShieldCheck, BarChart3, Sparkles, X, Clock, TrendingDown, AlertTriangle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import { generateRFQ, generateReport, analyzeForRFQ, autoFillRFQ } from '../services/api';

const CHART_COLORS = ['#0284c7', '#7c3aed', '#059669', '#d97706', '#dc2626', '#0891b2', '#65a30d', '#db2777'];

const ReportChart = ({ chartType, chartData, chartTitle }) => {
  if (!chartType || !Array.isArray(chartData) || chartData.length === 0) return null;

  return (
    <div className="rounded-3xl border border-slate-200 bg-white p-5">
      <p className="text-sm uppercase tracking-[0.24em] text-slate-500">{chartTitle || 'Key metrics'}</p>
      <div className="mt-4 h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {chartType === 'pie' ? (
            <PieChart>
              <Pie data={chartData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={90} label={({ name }) => name}>
                {chartData.map((_, index) => (
                  <Cell key={index} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          ) : chartType === 'line' ? (
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Line type="monotone" dataKey="value" stroke="#0284c7" strokeWidth={2} />
            </LineChart>
          ) : (
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip />
              <Bar dataKey="value" fill="#0284c7" radius={[6, 6, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
};

const formatValue = (value) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return null;
  return `$${Number(value).toLocaleString('en-US')}`;
};

const NOTE_MAX_CHARS = 700;

const AnalysisNote = ({ text }) => {
  if (!text) return null;
  const truncated = text.length > NOTE_MAX_CHARS ? `${text.slice(0, NOTE_MAX_CHARS)}…` : text;
  return (
    <div className="prose prose-sm max-w-none text-slate-600 prose-p:my-1 prose-headings:text-sm prose-headings:font-semibold prose-headings:my-1">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ node, ...props }) => <table className="w-full border-collapse my-2 text-xs" {...props} />,
          thead: ({ node, ...props }) => <thead className="bg-slate-100" {...props} />,
          tr: ({ node, ...props }) => <tr className="even:bg-slate-50" {...props} />,
          th: ({ node, ...props }) => <th className="border border-slate-300 px-2 py-1 text-left font-semibold text-slate-700" {...props} />,
          td: ({ node, ...props }) => <td className="border border-slate-200 px-2 py-1 align-top" {...props} />,
        }}
      >
        {truncated}
      </ReactMarkdown>
    </div>
  );
};

const ReportMarkdown = ({ text }) => {
  if (!text) return null;
  return (
    <div className="prose prose-sm max-w-none text-slate-700 prose-headings:font-semibold prose-headings:text-slate-900">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ node, ...props }) => <table className="w-full border-collapse my-3 text-sm" {...props} />,
          thead: ({ node, ...props }) => <thead className="bg-slate-100" {...props} />,
          tr: ({ node, ...props }) => <tr className="even:bg-slate-50" {...props} />,
          th: ({ node, ...props }) => <th className="border border-slate-300 px-3 py-2 text-left font-semibold text-slate-700" {...props} />,
          td: ({ node, ...props }) => <td className="border border-slate-200 px-3 py-2 align-top" {...props} />,
          pre: ({ node, ...props }) => <pre className="whitespace-pre-wrap break-words overflow-x-auto rounded-md bg-slate-900 text-slate-100 p-3 text-xs" {...props} />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
};

const PRIORITY_STYLES = {
  high: 'bg-rose-50 text-rose-700 border-rose-200',
  medium: 'bg-amber-50 text-amber-700 border-amber-200',
  low: 'bg-slate-100 text-slate-600 border-slate-200',
};

const RFQSuggestionCard = ({ candidate, onGenerate, onSkip, generating }) => (
  <div className="rounded-3xl border border-slate-200 bg-white p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="text-base font-semibold text-slate-900">{candidate.vendor}</p>
        <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500">
          {formatValue(candidate.value) && <span>{formatValue(candidate.value)}</span>}
          {candidate.expiry && (
            <span className="inline-flex items-center gap-1">
              <Clock size={12} /> Expires {candidate.expiry}
            </span>
          )}
          {candidate.score !== null && candidate.score !== undefined && (
            <span className="inline-flex items-center gap-1">
              <TrendingDown size={12} /> Score {candidate.score}
            </span>
          )}
        </div>
      </div>
      <span className={`rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wide ${PRIORITY_STYLES[candidate.priority] || PRIORITY_STYLES.medium}`}>
        {candidate.priority} priority
      </span>
    </div>

    {candidate.reasons?.length > 0 && (
      <div className="mt-3 flex flex-wrap gap-2">
        {candidate.reasons.map((reason, idx) => (
          <span key={idx} className="inline-flex items-center gap-1 rounded-full bg-slate-50 border border-slate-200 px-3 py-1 text-xs text-slate-600">
            <AlertTriangle size={11} className="text-amber-500" /> {reason}
          </span>
        ))}
      </div>
    )}

    <div className="mt-4 flex gap-2">
      <button
        onClick={() => onGenerate(candidate)}
        disabled={generating}
        className="inline-flex items-center gap-2 rounded-full bg-sky-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-sky-700 disabled:opacity-50"
      >
        <FileText size={14} /> Generate RFQ
      </button>
      <button
        onClick={() => onSkip(candidate.vendor)}
        className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-4 py-2 text-xs font-semibold text-slate-600 transition hover:bg-slate-200"
      >
        <X size={14} /> Skip
      </button>
    </div>
  </div>
);

const defaultRFQ = {
  company_name: 'Acme Corporation',
  description: 'Enterprise cloud infrastructure services with managed support and 99.99% availability.',
  quantity: 100,
  unit_of_measure: 'VM instances',
  quality_standards: 'ISO 9001, SOC 2 Type II',
  delivery_location: 'Primary data center, Dallas, TX',
  timeline: 'Delivery within 45 days of award',
  special_terms: 'Vendor must accept change orders within 10 business days.',
};

const blankRfqInput = () => ({
  company_name: defaultRFQ.company_name,
  document_number: 'RFQ-20240612-001',
  date_issued: new Date().toISOString().split('T')[0],
  response_deadline: new Date(Date.now() + 14 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
  executive_summary: defaultRFQ.description,
  scope_of_work: ['Cloud environment provisioning', 'Managed support and monitoring', 'Quarterly performance reporting'],
  quantity: defaultRFQ.quantity,
  unit_of_measure: defaultRFQ.unit_of_measure,
  quality_standards: defaultRFQ.quality_standards,
  delivery_location: defaultRFQ.delivery_location,
  timeline: defaultRFQ.timeline,
  terms_and_conditions: [
    '30 day payment terms from invoice date.',
    'Vendor must carry general liability insurance of at least $5M.',
    'Performance guarantee: 99.99% uptime for the managed service.',
    'Termination for convenience with 60 days notice.',
  ],
  evaluation_criteria: {
    price: '40%',
    quality_and_capability: '35%',
    delivery_timeline: '15%',
    financial_stability: '10%',
  },
  requested_info: [
    'Pricing breakdown (unit, volume, implementation fees)',
    'References from 3 similar clients',
    'Proof of insurance and SOC 2 compliance',
    'Implementation timeline and resource plan',
    'Support SLA and escalation procedures',
  ],
  legal_certifications: [
    'Vendor certifies they are not debarred under FAR 9.4.',
    'Vendor is compliant with OFAC sanctions.',
    'Pricing is good faith and not collusive.',
  ],
});

const RFQBuilder = ({ documents = [], activeDoc = null, sessionId }) => {
  const [activeTab, setActiveTab] = useState('rfq');
  const [rfqInput, setRfqInput] = useState(blankRfqInput());
  const [reportFocus, setReportFocus] = useState('');
  const [rfqDraft, setRfqDraft] = useState(null);
  const [reportDraft, setReportDraft] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Smart RFQ detection state
  const [candidates, setCandidates] = useState(null);
  const [analysisNote, setAnalysisNote] = useState('');
  const [documentsAnalyzed, setDocumentsAnalyzed] = useState(0);
  const [analyzing, setAnalyzing] = useState(false);
  const [autoFilling, setAutoFilling] = useState(null); // vendor name currently being filled
  const [skippedVendors, setSkippedVendors] = useState([]);
  const [reviewMode, setReviewMode] = useState(false);
  const [autoFilledFrom, setAutoFilledFrom] = useState(null);

  const buildDocumentContext = () => {
    const activeDocument = activeDoc ? documents.find((doc) => doc.id === activeDoc) : null;
    return {
      active_document: activeDocument
        ? { doc_id: activeDocument.doc_id, name: activeDocument.name, type: activeDocument.type, status: activeDocument.status }
        : null,
      documents: documents.map((doc) => ({ doc_id: doc.doc_id, id: doc.id, name: doc.name, type: doc.type, status: doc.status })),
    };
  };

  const updateField = (key, value) => {
    setRfqInput((prev) => ({ ...prev, [key]: value }));
  };

  const updateRfqArray = (key, index, value) => {
    setRfqInput((prev) => {
      const items = [...prev[key]];
      items[index] = value;
      return { ...prev, [key]: items };
    });
  };

  const handleAnalyzeContracts = async () => {
    setAnalyzing(true);
    setError(null);
    try {
      const response = await analyzeForRFQ({ sessionId, context: buildDocumentContext() });
      setCandidates(response.candidates || []);
      setAnalysisNote(response.analysis_note || '');
      setDocumentsAnalyzed(response.documents_analyzed || 0);
      setSkippedVendors([]);
    } catch (err) {
      setError(err.message);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleSkipCandidate = (vendor) => {
    setSkippedVendors((prev) => [...prev, vendor]);
  };

  const handleGenerateFromCandidate = async (candidate) => {
    setAutoFilling(candidate.vendor);
    setError(null);
    try {
      const response = await autoFillRFQ({ sessionId, context: buildDocumentContext(), vendor: candidate.vendor });
      setRfqInput((prev) => ({
        ...prev,
        ...response,
        scope_of_work: response.scope_of_work?.length ? response.scope_of_work : prev.scope_of_work,
        terms_and_conditions: response.terms_and_conditions?.length ? response.terms_and_conditions : prev.terms_and_conditions,
        requested_info: response.requested_info?.length ? response.requested_info : prev.requested_info,
        legal_certifications: response.legal_certifications?.length ? response.legal_certifications : prev.legal_certifications,
        evaluation_criteria: Object.keys(response.evaluation_criteria || {}).length ? response.evaluation_criteria : prev.evaluation_criteria,
      }));
      setAutoFilledFrom({ vendor: candidate.vendor, fields: response.auto_filled_fields || [] });
      setReviewMode(true);
      setRfqDraft(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setAutoFilling(null);
    }
  };

  const handleStartBlank = () => {
    setRfqInput(blankRfqInput());
    setAutoFilledFrom(null);
    setReviewMode(true);
    setRfqDraft(null);
  };

  const handleBackToSuggestions = () => {
    setReviewMode(false);
    setAutoFilledFrom(null);
  };

  const handleGenerateRFQ = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await generateRFQ({ input: rfqInput });
      setRfqDraft(response);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateReport = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await generateReport({ sessionId, context: buildDocumentContext(), focus: reportFocus.trim() || undefined });
      setReportDraft(response);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const visibleCandidates = (candidates || []).filter((c) => !skippedVendors.includes(c.vendor));
  const highCount = visibleCandidates.filter((c) => c.priority === 'high').length;
  const mediumCount = visibleCandidates.filter((c) => c.priority === 'medium').length;

  return (
    <div className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
      <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-soft">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Procurement flow</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-900">Generate RFQs and reports with governance built in</h2>
          </div>
          <div className="rounded-full bg-slate-50 px-4 py-2 text-xs font-semibold uppercase tracking-[0.28em] text-slate-600">Polished workflow</div>
        </div>

        <div className="mt-6 flex flex-wrap gap-2">
          <button
            onClick={() => setActiveTab('rfq')}
            className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
              activeTab === 'rfq' ? 'bg-sky-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
          >
            RFQ Builder
          </button>
          <button
            onClick={() => setActiveTab('report')}
            className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
              activeTab === 'report' ? 'bg-sky-600 text-white' : 'bg-slate-100 text-slate-700 hover:bg-slate-200'
            }`}
          >
            Executive Report
          </button>
        </div>

        {activeTab === 'rfq' ? (
          !reviewMode ? (
            <div className="mt-8 space-y-6">
              <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-sky-50 to-blue-50 p-5">
                <div className="flex items-center gap-3">
                  <div className="rounded-2xl bg-white p-2.5 shadow-sm">
                    <Sparkles size={20} className="text-sky-600" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-900">Smart RFQ Detection</p>
                    <p className="text-xs text-slate-600">
                      Analyzes your uploaded contracts/vendor data for expiring terms, low performance, pricing outliers, and risk flags.
                    </p>
                  </div>
                </div>
                <button
                  onClick={handleAnalyzeContracts}
                  disabled={analyzing || documents.length === 0}
                  className="mt-4 inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-sky-700 disabled:opacity-50"
                >
                  <Sparkles size={16} /> {analyzing ? 'Analyzing…' : 'Analyze Contracts'}
                </button>
                {documents.length === 0 && (
                  <p className="mt-2 text-xs text-slate-500">Upload a contract or vendor spreadsheet in the Assistant tab first.</p>
                )}
              </div>

              {candidates !== null && (
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-3 text-xs">
                    <span className="rounded-full bg-rose-50 border border-rose-200 px-3 py-1 font-semibold text-rose-700">{highCount} high priority</span>
                    <span className="rounded-full bg-amber-50 border border-amber-200 px-3 py-1 font-semibold text-amber-700">{mediumCount} medium priority</span>
                    <span className="text-slate-500">{documentsAnalyzed} document(s) analyzed</span>
                  </div>
                  <AnalysisNote text={analysisNote} />

                  {visibleCandidates.length > 0 ? (
                    <div className="space-y-3">
                      {visibleCandidates.map((candidate) => (
                        <RFQSuggestionCard
                          key={candidate.vendor}
                          candidate={candidate}
                          onGenerate={handleGenerateFromCandidate}
                          onSkip={handleSkipCandidate}
                          generating={autoFilling === candidate.vendor}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-3xl border border-dashed border-slate-300 bg-white p-6 text-center text-sm text-slate-500">
                      No RFQ opportunities detected in the current data.
                    </div>
                  )}
                </div>
              )}

              <button
                onClick={handleStartBlank}
                className="text-sm font-medium text-slate-500 underline decoration-dotted hover:text-slate-700"
              >
                Or start a blank RFQ manually
              </button>

              {error && <p className="text-sm text-rose-600">{error}</p>}
            </div>
          ) : (
            <div className="mt-8 space-y-6">
              <button onClick={handleBackToSuggestions} className="text-sm font-medium text-sky-600 hover:text-sky-700">
                ← Back to suggestions
              </button>

              {autoFilledFrom && (
                <div className="rounded-3xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800">
                  Pre-filled from <strong>{autoFilledFrom.vendor}</strong>'s data
                  {autoFilledFrom.fields.length > 0 && (
                    <> — auto-filled: {autoFilledFrom.fields.join(', ')}</>
                  )}
                  . Review and adjust before generating.
                </div>
              )}

              <div className="grid gap-4 lg:grid-cols-2">
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Company name</span>
                  <input
                    value={rfqInput.company_name}
                    onChange={(e) => updateField('company_name', e.target.value)}
                    className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Document number</span>
                  <input
                    value={rfqInput.document_number}
                    onChange={(e) => updateField('document_number', e.target.value)}
                    className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  />
                </label>
              </div>

              <div className="grid gap-4 lg:grid-cols-3">
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Issue date</span>
                  <input
                    type="date"
                    value={rfqInput.date_issued}
                    onChange={(e) => updateField('date_issued', e.target.value)}
                    className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Response deadline</span>
                  <input
                    type="date"
                    value={rfqInput.response_deadline}
                    onChange={(e) => updateField('response_deadline', e.target.value)}
                    className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Quantity</span>
                  <input
                    type="number"
                    value={rfqInput.quantity}
                    onChange={(e) => updateField('quantity', Number(e.target.value))}
                    className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  />
                </label>
              </div>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">Executive summary</span>
                <textarea
                  value={rfqInput.executive_summary}
                  onChange={(e) => updateField('executive_summary', e.target.value)}
                  rows={4}
                  className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                />
              </label>

              <div className="grid gap-4 lg:grid-cols-2">
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Delivery location</span>
                  <input
                    value={rfqInput.delivery_location}
                    onChange={(e) => updateField('delivery_location', e.target.value)}
                    className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  />
                </label>
                <label className="block">
                  <span className="text-sm font-medium text-slate-700">Timeline</span>
                  <input
                    value={rfqInput.timeline}
                    onChange={(e) => updateField('timeline', e.target.value)}
                    className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                  />
                </label>
              </div>

              <label className="block">
                <span className="text-sm font-medium text-slate-700">Quality and compliance standards</span>
                <input
                  value={rfqInput.quality_standards}
                  onChange={(e) => updateField('quality_standards', e.target.value)}
                  className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                />
              </label>

              <div className="grid gap-4 lg:grid-cols-2">
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-slate-800">Scope of work</h3>
                  {rfqInput.scope_of_work.map((item, index) => (
                    <input
                      key={index}
                      value={item}
                      onChange={(e) => updateRfqArray('scope_of_work', index, e.target.value)}
                      className="w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                    />
                  ))}
                </div>
                <div className="space-y-4">
                  <h3 className="text-sm font-semibold text-slate-800">Terms and conditions</h3>
                  {rfqInput.terms_and_conditions.map((item, index) => (
                    <input
                      key={index}
                      value={item}
                      onChange={(e) => updateRfqArray('terms_and_conditions', index, e.target.value)}
                      className="w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                    />
                  ))}
                </div>
              </div>

              <div className="flex flex-wrap gap-3 pt-4">
                <button
                  onClick={handleGenerateRFQ}
                  disabled={loading}
                  className="inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-sky-700 disabled:opacity-50"
                >
                  <FileText size={18} /> Generate RFQ Draft
                </button>
                <button
                  onClick={handleGenerateReport}
                  disabled={loading}
                  className="inline-flex items-center gap-2 rounded-full bg-slate-100 px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-200 disabled:opacity-50"
                >
                  <BarChart3 size={18} /> Create Report Summary
                </button>
              </div>

              {error && <p className="text-sm text-rose-600">{error}</p>}
            </div>
          )
        ) : (
          <div className="mt-8 space-y-6">
            <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-sky-50 to-blue-50 p-5">
              <p className="text-sm font-semibold text-slate-900">AI-structured executive report</p>
              <p className="mt-1 text-xs text-slate-600">
                The report's sections, findings, and chart (if the data supports one) are determined by the AI from your
                uploaded document — not a fixed template. Optionally tell it what to focus on below.
              </p>
            </div>

            {documents.length === 0 && (
              <p className="text-xs text-slate-500">Upload a contract or vendor spreadsheet in the Assistant tab first.</p>
            )}

            <label className="block">
              <span className="text-sm font-medium text-slate-700">Focus (optional)</span>
              <textarea
                value={reportFocus}
                onChange={(e) => setReportFocus(e.target.value)}
                rows={3}
                placeholder="e.g. focus on contracts expiring this quarter, or on vendor risk"
                className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
              />
            </label>

            <button
              onClick={handleGenerateReport}
              disabled={loading || documents.length === 0}
              className="inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-sky-700 disabled:opacity-50"
            >
              <ShieldCheck size={18} /> {loading ? 'Generating…' : 'Generate Report'}
            </button>
            {error && <p className="text-sm text-rose-600">{error}</p>}
          </div>
        )}
      </div>

      <div className="rounded-[2rem] border border-slate-200 bg-slate-50 p-6 shadow-soft">
        <div className="flex items-center gap-3 text-slate-700">
          <div className="rounded-2xl bg-white p-3 shadow-sm">
            <Download size={24} />
          </div>
          <div>
            <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Preview</p>
            <h3 className="text-xl font-semibold text-slate-900">Draft output</h3>
          </div>
        </div>

        {activeTab === 'rfq' ? (
          rfqDraft ? (
            <div className="mt-6 space-y-4">
              <div className="rounded-3xl border border-slate-200 bg-white p-5">
                <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Executive summary</p>
                <p className="mt-3 text-sm leading-6 text-slate-700">{rfqDraft.executive_summary}</p>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="rounded-3xl border border-slate-200 bg-white p-5">
                  <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Scope of work</p>
                  <ul className="mt-3 space-y-2 text-sm text-slate-700">
                    {rfqDraft.scope_of_work.map((item, index) => (
                      <li key={index}>• {item}</li>
                    ))}
                  </ul>
                </div>
                <div className="rounded-3xl border border-slate-200 bg-white p-5">
                  <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Key terms</p>
                  <ul className="mt-3 space-y-2 text-sm text-slate-700">
                    {rfqDraft.terms_and_conditions.map((item, index) => (
                      <li key={index}>• {item}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          ) : (
            <div className="mt-6 rounded-3xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
              {candidates === null
                ? 'Click "Analyze Contracts" to detect RFQ opportunities, or start a blank RFQ manually.'
                : 'Generate an RFQ draft to preview professional procurement language and structure.'}
            </div>
          )
        ) : reportDraft ? (
          <div className="mt-6 space-y-4">
            <div className="rounded-3xl border border-slate-200 bg-white p-5">
              <ReportMarkdown text={reportDraft.report_markdown} />
            </div>
            <ReportChart
              chartType={reportDraft.chart_type}
              chartData={reportDraft.chart_data}
              chartTitle={reportDraft.chart_title}
            />
          </div>
        ) : (
          <div className="mt-6 rounded-3xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
            Generate a report draft to preview executive insights and action items.
          </div>
        )}
      </div>
    </div>
  );
};

export default RFQBuilder;
