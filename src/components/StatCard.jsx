/**
 * A single dashboard stat card driven by a live SAP metric.
 * Shows a shimmer while loading, an em dash if the value is unavailable.
 */
const StatCard = ({ label, value, sub, loading, tone = 'slate' }) => {
  const toneClasses = {
    slate: 'text-slate-900',
    amber: 'text-amber-600',
    red: 'text-red-600',
    emerald: 'text-emerald-600',
    sky: 'text-sky-600',
  }[tone] || 'text-slate-900';

  return (
    <div className="rounded-[1.75rem] border border-slate-200 bg-slate-50 p-6">
      <p className="text-sm text-slate-500">{label}</p>
      {loading ? (
        <div className="mt-4 h-9 w-24 animate-pulse rounded-lg bg-slate-200" />
      ) : (
        <p className={`mt-4 text-4xl font-semibold ${toneClasses}`}>{value}</p>
      )}
      {sub && <p className="mt-3 text-sm text-slate-600">{sub}</p>}
    </div>
  );
};

export default StatCard;
