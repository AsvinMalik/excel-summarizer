import { useState } from 'react';
import { Download, FileText, ShieldCheck, BarChart3 } from 'lucide-react';
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
import { generateRFQ, generateReport } from '../services/api';

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

const RFQBuilder = () => {
  const [activeTab, setActiveTab] = useState('rfq');
  const [rfqInput, setRfqInput] = useState({
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
  const [reportInput, setReportInput] = useState({
    report_type: 'spend',
    title: 'Spend and Renewal Analysis',
    scope: 'All strategic vendors and high renewal risk contracts',
    timeframe: 'Last 12 months',
    filters: 'High-risk vendors, expiring contracts, top 10 spend categories',
  });
  const [rfqDraft, setRfqDraft] = useState(null);
  const [reportDraft, setReportDraft] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

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
      const response = await generateReport({ input: reportInput });
      setReportDraft(response);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

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
          <div className="mt-8 space-y-6">
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
        ) : (
          <div className="mt-8 space-y-6">
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Report title</span>
              <input
                value={reportInput.title}
                onChange={(e) => setReportInput((prev) => ({ ...prev, title: e.target.value }))}
                className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
              />
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Scope</span>
              <textarea
                value={reportInput.scope}
                onChange={(e) => setReportInput((prev) => ({ ...prev, scope: e.target.value }))}
                rows={3}
                className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
              />
            </label>
            <div className="grid gap-4 lg:grid-cols-2">
              <label className="block">
                <span className="text-sm font-medium text-slate-700">Report type</span>
                <select
                  value={reportInput.report_type}
                  onChange={(e) => setReportInput((prev) => ({ ...prev, report_type: e.target.value }))}
                  className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                >
                  <option value="spend">Spend Analysis</option>
                  <option value="vendor">Vendor Summary</option>
                  <option value="risk">Risk Assessment</option>
                </select>
              </label>
              <label className="block">
                <span className="text-sm font-medium text-slate-700">Timeframe</span>
                <input
                  value={reportInput.timeframe}
                  onChange={(e) => setReportInput((prev) => ({ ...prev, timeframe: e.target.value }))}
                  className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
                />
              </label>
            </div>
            <label className="block">
              <span className="text-sm font-medium text-slate-700">Filters</span>
              <textarea
                value={reportInput.filters}
                onChange={(e) => setReportInput((prev) => ({ ...prev, filters: e.target.value }))}
                rows={3}
                className="mt-2 w-full rounded-3xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900"
              />
            </label>
            <button
              onClick={handleGenerateReport}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-full bg-sky-600 px-5 py-3 text-sm font-semibold text-white transition hover:bg-sky-700 disabled:opacity-50"
            >
              <ShieldCheck size={18} /> Generate Report Draft
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
              Generate an RFQ draft to preview professional procurement language and structure.
            </div>
          )
        ) : reportDraft ? (
          <div className="mt-6 space-y-4">
            <div className="rounded-3xl border border-slate-200 bg-white p-5">
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Report summary</p>
              <p className="mt-3 text-sm leading-6 text-slate-700">{reportDraft.executive_summary}</p>
            </div>
            <ReportChart
              chartType={reportDraft.chart_type}
              chartData={reportDraft.chart_data}
              chartTitle={reportDraft.chart_title}
            />
            <div className="rounded-3xl border border-slate-200 bg-white p-5">
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Key findings</p>
              <ul className="mt-3 space-y-2 text-sm text-slate-700">
                {reportDraft.key_findings.map((item, index) => (
                  <li key={index}>• {item}</li>
                ))}
              </ul>
            </div>
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
