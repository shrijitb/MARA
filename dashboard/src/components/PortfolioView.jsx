import { cn } from '../utils/cn.js';
import Tooltip from './education/Tooltip.jsx';

function Sparkline({ values, positive }) {
  if (!values?.length) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const rng = max - min || 1;
  const W = 48, H = 16;
  const step = W / (values.length - 1);
  const pts = values.map((v, i) => `${i * step},${H - ((v - min) / rng) * H}`).join(' ');
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
      <polyline points={pts} fill="none"
        stroke={positive ? '#00E676' : '#FF1744'}
        strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function buildPositions(workers, portfolio) {
  const rows = [];
  if (workers?.nautilus) {
    const w = workers.nautilus;
    rows.push({ id: 'nautilus', name: w.last_signal?.instrument || 'BTC-USDT', icon: '🤖', pnlUsd: w.pnl_usd || 0, pnlPct: w.pnl_pct || 0, alloc: w.allocated_usd || portfolio?.allocations?.nautilus?.usd || 0 });
  }
  if (workers?.prediction_markets) {
    const w = workers.prediction_markets;
    rows.push({ id: 'pm', name: 'Prediction Markets', icon: '🔮', pnlUsd: w.pnl_usd || 0, pnlPct: w.pnl_pct || 0, alloc: w.allocated_usd || portfolio?.allocations?.prediction_markets?.usd || 0 });
  }
  (workers?.core_dividends?.holdings || []).forEach(h => {
    rows.push({ id: `div-${h.ticker}`, name: h.ticker, icon: '💰', pnlUsd: ((h.pnl_pct || 0) / 100) * ((h.shares || 0) * (h.price || 0)), pnlPct: h.pnl_pct || 0, alloc: (h.shares || 0) * (h.price || 0) });
  });
  return rows.sort((a, b) => b.pnlPct - a.pnlPct);
}

export default function PortfolioView({ portfolio, workers }) {
  const pnl      = portfolio?.total_pnl_usd || 0;
  const pnlPct   = portfolio?.total_pnl_pct || 0;
  const total    = portfolio?.total_capital_usd || 0;
  const deployed = portfolio?.deployed_usd || 0;
  const free     = portfolio?.free_usd || 0;
  const dd       = portfolio?.drawdown_pct || 0;
  const up       = pnl >= 0;
  const positions = buildPositions(workers, portfolio);

  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Your Positions</span>
        <Tooltip term="sparkline" label="Position chart" />
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-4 p-3 bg-black/40 rounded-xl">
        {[
          { label: 'Total Gain', value: `${up ? '+' : ''}$${pnl.toFixed(2)}`, sub: `${up ? '+' : ''}${pnlPct.toFixed(1)}%`, color: up ? 'text-profit' : 'text-loss' },
          { label: 'Deployed',   value: `$${deployed.toFixed(2)}`, color: 'text-data' },
          { label: 'Cash',       value: `$${free.toFixed(2)}`, color: 'text-data' },
          { label: 'Drawdown',   value: `${dd.toFixed(1)}%`, color: dd > 10 ? 'text-loss' : dd > 5 ? 'text-warn' : 'text-data', tooltip: true },
        ].map(({ label, value, sub, color, tooltip }) => (
          <div key={label}>
            <div className="flex items-center gap-1 text-[9px] font-bold uppercase tracking-widest text-muted mb-0.5">
              {label} {tooltip && <Tooltip term="drawdown" />}
            </div>
            <div className={cn('text-sm font-bold font-jetbrains', color)}>{value}</div>
            {sub && <div className={cn('text-[10px] font-jetbrains', color)}>{sub}</div>}
          </div>
        ))}
      </div>

      {/* Positions */}
      {positions.length === 0 ? (
        <p className="text-xs text-muted text-center py-4">No open positions yet</p>
      ) : (
        <div className="flex flex-col divide-y divide-edge/50">
          {positions.map((pos) => {
            const up = pos.pnlPct >= 0;
            return (
              <div key={pos.id} className="flex items-center gap-3 py-2.5 group hover:bg-surface/30 -mx-1 px-1 rounded-lg transition-colors">
                <span className="text-lg leading-none">{pos.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-xs font-bold font-jetbrains text-cream truncate">{pos.name}</div>
                  <div className="text-[10px] text-muted">${pos.alloc.toFixed(2)} allocated</div>
                </div>
                <Sparkline
                  values={[0.4, 0.5, 0.45, 0.6, 0.55, up ? 0.75 : 0.35]}
                  positive={up}
                />
                <div className="text-right shrink-0">
                  <div className={cn('text-xs font-bold font-jetbrains', up ? 'text-profit' : 'text-loss')}>
                    {up ? '+' : ''}${Math.abs(pos.pnlUsd).toFixed(2)}
                  </div>
                  <div className={cn('text-[10px] font-jetbrains', up ? 'text-profit' : 'text-loss')}>
                    {up ? '+' : ''}{pos.pnlPct.toFixed(1)}%
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
