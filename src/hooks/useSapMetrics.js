import { useCallback, useEffect, useState } from 'react';
import { getSapMetrics } from '../services/api';

/**
 * Loads SAP-derived dashboard metrics once and exposes a refresh().
 * Every stat card in the app reads from this single source, so the whole
 * dashboard reflects the same SAP snapshot (mock now, live SAP later).
 */
export function useSapMetrics() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    try {
      setMetrics(await getSapMetrics({ force }));
    } catch (err) {
      setError(err.message || 'Could not load SAP metrics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { metrics, loading, error, refresh: () => load(true) };
}

/** Compact USD formatter: 18400000 -> "$18.4M", 4200 -> "$4.2K". */
export function fmtUsd(value) {
  if (value == null || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `$${(value / 1e3).toFixed(1)}K`;
  return `$${value.toFixed(0)}`;
}

/** Thousands-separated integer, or an em dash while loading/absent. */
export function fmtNum(value) {
  if (value == null || Number.isNaN(value)) return '—';
  return Number(value).toLocaleString('en-US');
}
