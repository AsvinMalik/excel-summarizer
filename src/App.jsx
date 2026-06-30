import { useState, useEffect } from 'react';
import {
  Layers,
  FileText,
  BarChart3,
  ShieldCheck,
  MessageCircle,
  CircleDollarSign,
} from 'lucide-react';
import ProcurementAssistant from './components/ProcurementAssistant';
import RFQBuilder from './components/RFQBuilder';
import AuthPanel from './components/AuthPanel';
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
  const [documents, setDocuments] = useState([]);
  const [activeDoc, setActiveDoc] = useState(null);
  const [sessionId] = useState(() => localStorage.getItem('procure_session') || `session-${Date.now()}`);
  const { user, loading, logout, isFirebaseConfigured } = useAuth();
  const requiresAuth = isFirebaseConfigured;

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
              <p className="text-sm font-semibold uppercase tracking-[0.24em] text-slate-500">Platform overview</p>
              <div className="mt-6 grid gap-4">
                <div className="rounded-3xl border border-slate-200 p-5">
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Contracts analyzed</p>
                  <p className="mt-3 text-3xl font-semibold text-slate-900">1,264</p>
                </div>
                <div className="rounded-3xl border border-slate-200 p-5">
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Vendor records</p>
                  <p className="mt-3 text-3xl font-semibold text-slate-900">482</p>
                </div>
                <div className="rounded-3xl border border-slate-200 p-5">
                  <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Risk flags raised</p>
                  <p className="mt-3 text-3xl font-semibold text-slate-900">37</p>
                </div>
              </div>
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
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Renewals due</p>
                  <p className="mt-4 text-4xl font-semibold text-slate-900">24</p>
                  <p className="mt-3 text-sm text-slate-600">Contracts expiring in the next 60 days.</p>
                </div>
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Spend exposure</p>
                  <p className="mt-4 text-4xl font-semibold text-slate-900">$18.4M</p>
                  <p className="mt-3 text-sm text-slate-600">Total spend at risk from unreviewed renewals.</p>
                </div>
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">High-risk contracts</p>
                  <p className="mt-4 text-4xl font-semibold text-slate-900">7</p>
                  <p className="mt-3 text-sm text-slate-600">Contracts with unresolved compliance or liability issues.</p>
                </div>
              </div>
            </div>
          )}

          {activeSection === 'contracts' && (
            <div>
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Contracts</p>
              <h2 className="mt-3 text-2xl font-semibold text-slate-900">Smart contract review workflows</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-3">
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Agreements analyzed</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">512</p>
                  <p className="mt-3 text-sm text-slate-600">Fully processed contract documents with clause-level details.</p>
                </div>
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Clause extractions</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">1,804</p>
                  <p className="mt-3 text-sm text-slate-600">Payment, termination, indemnity, SLA, and renewal clauses extracted.</p>
                </div>
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Review throughput</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">84%</p>
                  <p className="mt-3 text-sm text-slate-600">Of contract summaries reviewed by legal and procurement teams.</p>
                </div>
              </div>
            </div>
          )}

          {activeSection === 'rfq' && (
            <div>
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">RFQ Automation</p>
              <h2 className="mt-3 text-2xl font-semibold text-slate-900">Generate compliant RFQs in minutes</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-2">
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Template reuse</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">100+</p>
                  <p className="mt-3 text-sm text-slate-600">Standardized RFQ formats for regulated industries and enterprise vendors.</p>
                </div>
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Time saved</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">65%</p>
                  <p className="mt-3 text-sm text-slate-600">Faster tender creation with inherited contract terms and compliance controls.</p>
                </div>
              </div>
              <div className="mt-10">
                <RFQBuilder documents={documents} activeDoc={activeDoc} sessionId={sessionId} />
              </div>
            </div>
          )}

          {activeSection === 'risk' && (
            <div>
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">Risk</p>
              <h2 className="mt-3 text-2xl font-semibold text-slate-900">Enterprise risk posture for procurement teams</h2>
              <div className="mt-8 grid gap-4 md:grid-cols-3">
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">High-severity issues</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">14</p>
                  <p className="mt-3 text-sm text-slate-600">Contracts flagged for indemnity, liability, or termination concerns.</p>
                </div>
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Compliance gaps</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">22</p>
                  <p className="mt-3 text-sm text-slate-600">Regulatory risk items identified in vendor agreements and RFQ terms.</p>
                </div>
                <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
                  <p className="text-sm text-slate-500">Audit readiness</p>
                  <p className="mt-4 text-3xl font-semibold text-slate-900">98%</p>
                  <p className="mt-3 text-sm text-slate-600">Contracts and reports classified for executive review and audit retention.</p>
                </div>
              </div>
            </div>
          )}

          {activeSection === 'assistant' && (
            <div className="mt-4">
              <ProcurementAssistant
                documents={documents}
                setDocuments={setDocuments}
                activeDoc={activeDoc}
                setActiveDoc={setActiveDoc}
                sessionId={sessionId}
              />
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
