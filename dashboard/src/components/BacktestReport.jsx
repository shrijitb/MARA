import { cn } from '../utils/cn.js';
import Tooltip from './education/Tooltip.jsx';

function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
  catch { return iso; }
}

function ScoreBar({ label, value, goodBelow, term }) {
  const threshold = goodBelow ? 0.40 : 0.95;
  const passes = goodBelow ? (value || 0) < threshold : (value || 0) > threshold;
  const color = passes ? 'bg-profit' : (value || 0) > (goodBelow ? 0.7 : 0.5) ? 'bg-loss' : 'bg-warn';
  const textColor = passes ? 'text-profit' : 'text-warn';
  const pct = Math.min((value || 0) * 100, 100);

  return (
    <div>
      <div className="flex justify-between items-center mb-1">
        <span className="flex items-center gap-1 text-[10px] text-muted">
          {label} <Tooltip term={term} />
        </span>
        <span className={cn('text-[10px] font-jetbrains font-bold', textColor)}>{(value || 0).toFixed(2)}</span>
      </div>
      <div className="h-1 bg-edge rounded-full">
        <div className={cn('h-full rounded-full transition-all duration-700', color)} style={{ width: `${pct}%` }} />
      </div>
      <div className={cn('text-[9px] mt-0.5', passes ? 'text-profit' : 'text-warn')}>
        {passes
          ? goodBelow ? '✓ No overfitting detected' : '✓ Trustworthy result'
          : goodBelow ? `High overfitting risk (max ${threshold})` : `Below threshold (min ${threshold})`
        }
      </div>
    </div>
  );
}

function StrategyCard({ name, result }) {
  if (!result) return null;
  const passed  = result.promoted === true;
  const display = name === 'swing_macd' ? 'Trend Strategy (MACD)' : name === 'range_mean_revert' ? 'Ranging Strategy (Mean Reversion)' : name.replace(/_/g, ' ');
  const icon    = name === 'swing_macd' ? '📈' : '📉';

  return (
    <div className={cn(
      'rounded-xl p-3 border transition-all',
      passed ? 'bg-profit/4 border-profit/15' : 'bg-black/40 border-edge'
    )}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm">{icon}</span>
          <span className="text-xs font-bold text-cream">{display}</span>
        </div>
        <span className={cn(
          'text-[10px] font-bold px-2 py-0.5 rounded-full border',
          passed ? 'bg-profit/10 text-profit border-profit/25' : 'bg-loss/10 text-loss border-loss/20'
        )}>
          {passed ? '✅ Passed' : '❌ No change'}
        </span>
      </div>

      <p className="text-[11px] text-muted leading-relaxed italic mb-3">
        {passed
          ? `Found better settings after ${result.trials_run || 200} tests. New parameters applied automatically.`
          : `Tested ${result.trials_run || 200} variations. Risk of overfitting — keeping current settings.`
        }
      </p>

      <div className="flex flex-col gap-2">
        {result.pbo != null && <ScoreBar label="PBO (overfitting)"      value={result.pbo}                     goodBelow={true}  term="pbo" />}
        {(result.dsr ?? result.oos_sharpe) != null && <ScoreBar label="DSR (trustworthiness)" value={result.dsr ?? result.oos_sharpe} goodBelow={false} term="dsr" />}
      </div>

      {passed && result.new_params && (
        <div className="mt-2.5 px-2.5 py-1.5 bg-profit/5 border border-profit/15 rounded-lg text-[10px] font-jetbrains text-profit/80">
          New params: {Object.entries(result.new_params).map(([k, v]) => `${k}=${v}`).join(', ')}
        </div>
      )}
    </div>
  );
}

export default function BacktestReport({ backtest }) {
  if (!backtest) {
    return (
      <div className="bg-card border border-edge rounded-2xl p-4">
        <div className="text-[10px] font-bold uppercase tracking-widest text-muted mb-3">Nightly Checkup</div>
        <p className="text-xs text-muted text-center py-5">First checkup runs at 2:00 AM</p>
      </div>
    );
  }

  const { last_run, swing_macd, range_mean_revert, ...rest } = backtest;

  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Nightly Checkup</span>
        {last_run && <span className="text-[10px] text-muted font-jetbrains">{fmtDate(last_run)}</span>}
      </div>

      <div className="flex flex-col gap-2.5">
        <StrategyCard name="swing_macd"       result={swing_macd} />
        <StrategyCard name="range_mean_revert" result={range_mean_revert} />
        {Object.entries(rest).map(([k, v]) =>
          v && typeof v === 'object' ? <StrategyCard key={k} name={k} result={v} /> : null
        )}
      </div>
    </div>
  );
}
