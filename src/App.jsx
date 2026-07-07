import { useState, useEffect } from 'react';
import {
  Layers,
  FileText,
  BarChart3,
  ShieldCheck,
  MessageCircle,
  CircleDollarSign,
} from 'lucide-react';
import SAPWorkbench from './components/SAPWorkbench';
import RFQBuilder from './components/RFQBuilder';
import AuthPanel from './components/AuthPanel';
import StatCard from './components/StatCard';
import SapInsightPanel from './components/SapInsightPanel';
import { useSapMetrics, fmtUsd, fmtNum } from './hooks/useSapMetrics';
import { useAuth } from './context/AuthContext';

const sections = [
  { id: 'dashboard', label: 'Dashboard', icon: BarChart3 },
  { id: 'contracts', label: 'Contracts', icon: FileText },
  { id: 'rfq', label: 'RFQs', icon: CircleDollarSign },
  { id: 'risk', label: 'Risk', icon: ShieldCheck },
  { id: 'assistant', label: 'Assistant', icon: MessageCircle },
];

const FeatureCard = ({ title, description, badge }) => (
  <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-soft hover:-translate-y-1 transition">
    <div className="flex items-center justify-between gap-3 mb-5">
      <p className="text-sm font-semibold text-slate-800">{title}</p>
      <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-semibold text-sky-700">{badge}</span>
    </div>
    <p className="text-sm leading-6 text-slate-600">{description}</p>
  </div>
);

function App() {
  const [activeSection, setActiveSection] = useState('assistant');
  // documents/activeDoc retained for the RFQ builder flow; the assistant is
  // now the SAP-connected workbench and no longer takes uploaded documents.
  const [documents] = useState([]);
  const [activeDoc] = useState(null);
  const [sessionId] = useState(() => localStorage.getItem('procure_session') || `session-${Date.now()}`);
  const { user, loading, logout, isFirebaseConfigured } = useAuth();
  const requiresAuth = isFirebaseConfigured;

  // Live SAP-derived dashboard metrics — one snapshot feeds every stat card.
  const { metrics, loading: metricsLoading, error: metricsError } = useSapMetrics();
  const m = metrics || {};

  useEffect(() => {
    localStorage.setItem('procure_session', sessionId);
  }, [sessionId]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white/90 backdrop-blur sticky top-0 z-20">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-600 to-blue-700 text-white shadow-lg shadow-slate-900/5">
              <Layers size={24} />
            </div>
            <div>
              <p className="text-sm font-semibold text-slate-700">Procure.ai</p>
              <p className="text-xs text-slate-500">Enterprise procurement intelligence for analysis, automation, and insight.</p>
            </div>
          </div>
          {user && (
            <div className="flex items-center gap-3">
              <p className="text-sm text-slate-600">Signed in as <span className="font-semibold text-slate-900">{user.email}</span></p>
              <button onClick={logout} className="rounded-full bg-slate-100 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-200 transition">Sign out</button>
            </div>
          )}
          <div className="hidden sm:flex items-center gap-4 text-slate-600">
            <button className="rounded-full bg-slate-100 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-200 transition">Product</button>
            <button className="rounded-full bg-slate-100 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-200 transition">Solutions</button>
            <button className="rounded-full bg-slate-100 px-4 py-2 text-sm font-medium text-slate-800 hover:bg-slate-200 transition">Contact</button>
          </div>
        </div>
      </header>

      <main className={activeSection === 'assistant' ? 'px-4 py-10' : 'mx-auto max-w-7xl px-6 py-10'}>
        {!loading && !user && requiresAuth ? (
          <section className="mx-auto max-w-7xl rounded-[2rem] border border-slate-200 bg-white p-6 shadow-soft">
            <AuthPanel />
          </section>
        ) : (
          <>
            <section className="mx-auto max-w-7xl grid gap-8 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="space-y-6">
            <div className="rounded-[2rem] border border-slate-200 bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950 px-8 py-10 text-white shadow-soft">
              <p className="text-sm uppercase tracking-[0.26em] text-slate-400">Enterprise Procurement Analytics</p>
              <h1 className="mt-6 text-4xl font-semibold leading-tight sm:text-5xl">Analyze contracts, vendor spend, and compliance with a single intelligent platform.</h1>
              <p className="mt-6 max-w-2xl text-base text-slate-300">Procure.ai combines contract intelligence, spreadsheet Q&A, RFQ generation, and executive reporting into a polished, audit-ready web experience.</p>
              <div className="mt-8 grid gap-3 sm:grid-cols-2">
                <div className="rounded-3xl bg-white/10 p-5">
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Live analysis</p>
                  <p className="mt-3 text-lg font-semibold">Active vendor dashboards</p>
                </div>
                <div className="rounded-3xl bg-white/10 p-5">
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-300">Compliance</p>
                  <p className="mt-3 text-lg font-semibold">Regulated industry controls</p>
                </div>
              </div>
            </div>

            <div className="grid gap-5 md:grid-cols-2">
              <FeatureCard
                title="Contract Intelligence"
                description="Extract summaries, risks, clause excerpts, and compliance flags from agreements in seconds."
                badge="Core"
              />
              <FeatureCard
                title="Spend & Vendor Analytics"
                description="Query vendor performance, contract expiry, and spend trends directly from spreadsheet data."
                badge="Insights"
              />
              <FeatureCard
                title="RFQ & Report Generation"
                description="Create professional RFQs and executive reports with embedded procurement safeguards."
                badge="Execute"
              />
              <FeatureCard
                title="Audit-Ready Workflow"
                description="Maintain traceability and control with structured outputs and tool-driven summaries."
                badge="Governance"
              />
            </div>
          </div>

          <aside className="space-y-6">
            <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-soft">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">Platform overview</p>
                <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-emerald-700">
                  {metricsError ? 'SAP offline' : (m.source || 'SAP')}
                </span>
              </div>
              <div className="mt-6 grid gap-4">
                {[
                  { label: 'Active contracts', value: fmtNum(m.overview?.active_contracts) },
                  { label: 'Vendor records', value: fmtNum(m.overview?.vendor_records) },
                  { label: 'Risk flags raised', value: fmtNum(m.overview?.risk_flags) },
                ].map((stat) => (
                  <div key={stat.label} className="rounded-3xl border border-slate-200 p-5">
                    <p className="text-xs uppercase tracking-[0.24em] text-slate-500">{stat.label}</p>
                    {metricsLoading ? (
                      <div className="mt-3 h-8 w-20 animate-pulse rounded-lg bg-slate-200" />
                    ) : (
                      <p className="mt-3 text-3xl font-semibold text-slate-900">{stat.value}</p>
                    )}
                  </div>
                ))}
              </div>
              {metricsError && (
                <p className="mt-4 text-xs text-amber-600">{metricsError}</p>
              )}
            </div>
            <div className="rounded-[2rem] border border-slate-200 bg-white p-6 shadow-soft">
              <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">Product navigation</p>
              <div className="mt-6 space-y-3">
                {sections.map(({ id, label, icon: Icon }) => (
                  <button
                    key={id}
                    onClick={() => setActiveSection(id)}
                    className={`flex w-full items-center justify-between gap-3 rounded-3xl px-4 py-3 text-left text-sm font-medium transition ${
                      activeSection === id
                        ? 'bg-sky-600 text-white shadow-lg shadow-sky-600/10'
                        : 'border border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100'
                    }`}
                  >
                    <span className="flex items-center gap-2">
                      <Icon size={18} />
                      {label}
                    </span>
                    <span className="text-xs uppercase tracking-[0.24em] text-slate-400">Go</span>
                  </button>
                ))}
              </div>
            </div>
          </aside>
            </section>

            <section className={activeSection === 'assistant' ? 'mt-10' : 'mt-10 mx-auto max-w-7xl rounded-[2rem] border border-slate-200 bg-white p-6 shadow-soft'}>
          {activeSection === 'dashboard' && (
            <div>
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Dashboard</p>
                  <h2 className="mt-3 text-2xl font-semibold text-slate-900">Procurement intelligence at a glance</h2>
                </div>
                <button className="inline-flex items-center rounded-full bg-sky-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-sky-600/10 hover:bg-sky-700 transition">Review key insights</button>
              </div>
              <div className="mt-8 grid gap-4 lg:grid-cols-3">
                <StatCard
                  label="Renewals due"
                  value={fmtNum(m.dashboard?.renewals_due)}
                  sub={`Contracts expiring in the next ${m.dashboard?.renewal_horizon_days ?? 90} days.`}
                  loading={metricsLoading}
                  tone="amber"
                />
                <StatCard
                  label="Spend exposure"
                  value={fmtUsd(m.dashboard?.spend_exposure_usd)}
                  sub="Contract value at risk from unreviewed renewals."
                  loading={metricsLoading}
                  tone="red"
                />
                <StatCard
                  label="Open purchase orders"
                  value={fmtNum(m.dashboard?.open_purchase_orders)}
                  sub="Purchasing commitments not yet fully delivered."
                  loading={metricsLoading}
                />
              </div>
              <SapInsightPanel section="dashboard" />
            </div>
          )}

          {activeSection === 'contracts' && (
            <div>
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Contracts</p>
              <h2 className="mt-3 text-2xl font-semibold text-slate-900">Contract portfolio from SAP</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-3">
                <StatCard
                  label="Total agreements"
                  value={fmtNum(m.contracts?.total_agreements)}
                  sub="Outline agreements and contracts in the SAP register."
                  loading={metricsLoading}
                />
                <StatCard
                  label="Total contract value"
                  value={fmtUsd(m.contracts?.total_contract_value_usd)}
                  sub="Aggregate committed value across all contracts."
                  loading={metricsLoading}
                  tone="sky"
                />
                <StatCard
                  label="Auto-renewal contracts"
                  value={fmtNum(m.contracts?.auto_renewal_count)}
                  sub="Contracts set to renew automatically — review before expiry."
                  loading={metricsLoading}
                  tone="amber"
                />
              </div>
              {m.contracts?.expiring_soon?.length > 0 && (
                <div className="mt-6 overflow-x-auto rounded-2xl border border-slate-200">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
                      <tr>
                        <th className="px-4 py-3">Contract</th>
                        <th className="px-4 py-3">Vendor</th>
                        <th className="px-4 py-3">Expires</th>
                        <th className="px-4 py-3 text-right">Value</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {m.contracts.expiring_soon.map((c) => (
                        <tr key={c.contract}>
                          <td className="px-4 py-3 font-medium text-slate-800">{c.contract}</td>
                          <td className="px-4 py-3 text-slate-600">{c.vendor}</td>
                          <td className="px-4 py-3 text-slate-600">{c.valid_to}</td>
                          <td className="px-4 py-3 text-right text-slate-800">{fmtUsd(c.value_usd)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <SapInsightPanel section="contracts" />
            </div>
          )}

          {activeSection === 'rfq' && (
            <div>
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">RFQ Automation</p>
              <h2 className="mt-3 text-2xl font-semibold text-slate-900">Sourcing & vendor spend from SAP</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-3">
                <StatCard
                  label="Active vendors"
                  value={fmtNum(m.vendors?.total_vendors)}
                  sub="Suppliers available for sourcing and RFQ distribution."
                  loading={metricsLoading}
                />
                <StatCard
                  label="Total vendor spend"
                  value={fmtUsd(m.vendors?.total_spend_usd)}
                  sub={m.vendors?.top_vendor_by_spend
                    ? `Top vendor: ${m.vendors.top_vendor_by_spend.name} (${fmtUsd(m.vendors.top_vendor_by_spend.spend_usd)}).`
                    : 'Aggregate spend across all vendors.'}
                  loading={metricsLoading}
                  tone="sky"
                />
                <StatCard
                  label="Open PO value"
                  value={fmtUsd(m.vendors?.open_po_value_usd)}
                  sub="Value of purchase orders currently open."
                  loading={metricsLoading}
                  tone="amber"
                />
              </div>
              <SapInsightPanel section="vendors" />
              <div className="mt-10">
                <RFQBuilder documents={documents} activeDoc={activeDoc} sessionId={sessionId} />
              </div>
            </div>
          )}

          {activeSection === 'risk' && (
            <div>
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Risk</p>
              <h2 className="mt-3 text-2xl font-semibold text-slate-900">Vendor risk posture from SAP</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-3">
                <StatCard
                  label="High-risk vendors"
                  value={fmtNum(m.risk?.high_risk_vendors)}
                  sub="Vendors rated High in the SAP compliance master."
                  loading={metricsLoading}
                  tone="red"
                />
                <StatCard
                  label="Compliance gaps"
                  value={fmtNum(m.risk?.compliance_gaps)}
                  sub="Vendors with no certifications or a blocked flag."
                  loading={metricsLoading}
                  tone="amber"
                />
                <StatCard
                  label="High-risk contract value"
                  value={fmtUsd(m.risk?.high_risk_contract_value_usd)}
                  sub="Committed contract value tied to high-risk or blocked vendors."
                  loading={metricsLoading}
                  tone="red"
                />
              </div>
              <SapInsightPanel section="risk" />
            </div>
          )}

          {activeSection === 'assistant' && (
            <div className="mt-4 mx-auto max-w-7xl">
              {/* SAP-connected RAG workspace — replaces the manual-upload
                  assistant. ProcurementAssistant remains in the codebase for
                  one-line rollback if the pivot is reverted. */}
              <SAPWorkbench />
            </div>
          )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}

export default App;
