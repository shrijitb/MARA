import { cn } from '../../utils/cn.js';
import Tooltip from '../education/Tooltip.jsx';

const WORKERS = [
  { key: 'nautilus',           icon: '🤖', label: 'Trading Bot',  barColor: 'bg-info',   glowColor: 'shadow-[0_0_6px_rgba(0,176,255,0.4)]' },
  { key: 'prediction_markets', icon: '🔮', label: 'Predictions',  barColor: 'bg-purple', glowColor: 'shadow-[0_0_6px_rgba(224,64,251,0.4)]' },
  { key: 'analyst',            icon: '🧠', label: 'Analyst',      barColor: 'bg-warn',   glowColor: 'shadow-[0_0_6px_rgba(255,215,64,0.4)]' },
  { key: 'core_dividends',     icon: '💰', label: 'Savings',      barColor: 'bg-profit', glowColor: 'shadow-[0_0_6px_rgba(0,230,118,0.4)]' },
];

function FlowRow({ icon, label, barColor, glowColor, usd, totalDeployed }) {
  const pct = totalDeployed > 0 ? Math.min((usd / totalDeployed) * 100, 100) : 0;
  return (
    <div className="group">
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="text-sm">{icon}</span>
          <span className="text-xs text-muted group-hover:text-cream transition-colors">{label}</span>
        </div>
        <span className="text-xs font-jetbrains text-data">${usd?.toFixed(2) || '0.00'}</span>
      </div>
      <div className="h-1.5 bg-edge rounded-full overflow-hidden relative">
        <div
          className={cn('h-full rounded-full relative overflow-hidden transition-all duration-700', barColor, glowColor)}
          style={{ width: `${pct}%` }}
        >
          {/* Shimmer */}
          <div className="absolute inset-y-0 left-0 w-1/2"
            style={{
              background: 'linear-gradient(90deg,transparent,rgba(255,255,255,0.3),transparent)',
              animation: 'shimmer 2s linear infinite',
            }}
          />
        </div>
      </div>
    </div>
  );
}

export default function MoneyFlow({ portfolio, workers }) {
  const pnl      = portfolio?.total_pnl_usd || 0;
  const pnlPct   = portfolio?.total_pnl_pct || 0;
  const total    = portfolio?.total_capital_usd || 0;
  const deployed = portfolio?.deployed_usd || 0;
  const free     = portfolio?.free_usd || 0;
  const deployPct = total > 0 ? Math.round((deployed / total) * 100) : 0;
  const up = pnl >= 0;

  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Capital Flow</span>
        <Tooltip term="allocation" label="Allocation" />
      </div>

      {/* Big number */}
      <div className="mb-4">
        <div className="font-jetbrains text-3xl font-bold text-cream leading-none">
          ${total.toFixed(2)}
        </div>
        <div className="flex items-center gap-2 mt-1.5">
          <span className={cn('text-sm font-bold font-jetbrains', up ? 'text-profit' : 'text-loss')}>
            {up ? '↑' : '↓'} ${Math.abs(pnl).toFixed(2)}
          </span>
          <span className={cn('text-xs font-semibold px-1.5 py-0.5 rounded', up ? 'bg-profit/10 text-profit' : 'bg-loss/10 text-loss')}>
            {up ? '+' : ''}{pnlPct.toFixed(2)}%
          </span>
          <span className="text-xs text-muted">all time</span>
        </div>
      </div>

      {/* Deployed overview */}
      <div className="mb-4">
        <div className="flex justify-between text-[10px] text-muted mb-1.5">
          <span>Deployed <span className="font-jetbrains text-data">${deployed.toFixed(2)}</span></span>
          <span>Cash <span className="font-jetbrains text-data">${free.toFixed(2)}</span></span>
        </div>
        <div className="h-2 bg-edge rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-700"
            style={{
              width: `${deployPct}%`,
              background: 'linear-gradient(90deg, #00B0FF, #E040FB)',
            }}
          />
        </div>
        <div className="text-right text-[10px] text-muted mt-1">{deployPct}% deployed</div>
      </div>

      {/* Per-worker breakdown */}
      <div className="flex flex-col gap-2.5 pt-3 border-t border-edge">
        {WORKERS.map(w => {
          const usd = portfolio?.allocations?.[w.key]?.usd
            || workers?.[w.key]?.allocated_usd || 0;
          return (
            <FlowRow key={w.key} {...w} usd={usd} totalDeployed={deployed || 1} />
          );
        })}
        {free > 0 && (
          <FlowRow icon="🏦" label="Cash Reserve" barColor="bg-rim" glowColor="" usd={free} totalDeployed={total || 1} />
        )}
      </div>
    </div>
  );
}
