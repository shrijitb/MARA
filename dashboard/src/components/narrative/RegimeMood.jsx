import { cn } from '../../utils/cn.js';
import Tooltip from '../education/Tooltip.jsx';

const REGIME = {
  RISK_ON: {
    icon: '☀️',  label: 'Clear Skies',    anim: 'anim-sun',
    ring: 'ring-profit/20', glow: 'shadow-[0_0_30px_rgba(0,230,118,0.08)]',
    badge: 'bg-profit/10 text-profit border-profit/25',
    bar:   'bg-profit',
    tip: 'Markets are calm and trending upward. Good conditions for trading.',
  },
  RISK_OFF: {
    icon: '🌧',  label: 'Storm Brewing',   anim: 'anim-cloud',
    ring: 'ring-orange/20', glow: 'shadow-[0_0_30px_rgba(255,145,0,0.08)]',
    badge: 'bg-orange/10 text-orange border-orange/25',
    bar:   'bg-orange',
    tip: 'Markets are pulling back. Arca is being more careful with your money.',
  },
  CRISIS: {
    icon: '⛈',  label: 'Red Alert',       anim: 'anim-lightning',
    ring: 'ring-loss/25', glow: 'shadow-[0_0_30px_rgba(255,23,68,0.10)]',
    badge: 'bg-loss/10 text-loss border-loss/30',
    bar:   'bg-loss',
    tip: 'Markets are in crisis. Arca is protecting your capital.',
  },
  TRANSITION: {
    icon: '🌤',  label: 'Shifting Winds',  anim: 'anim-cloud',
    ring: 'ring-warn/20', glow: 'shadow-[0_0_30px_rgba(255,215,64,0.08)]',
    badge: 'bg-warn/10 text-warn border-warn/25',
    bar:   'bg-warn',
    tip: 'Markets are changing direction. Arca is watching closely.',
  },
};

const PROB_KEYS = ['RISK_ON', 'TRANSITION', 'RISK_OFF', 'CRISIS'];
const PROB_COLORS = ['bg-profit', 'bg-warn', 'bg-orange', 'bg-loss'];
const PROB_TEXT   = ['text-profit', 'text-warn', 'text-orange', 'text-loss'];

export default function RegimeMood({ regime }) {
  const label  = regime?.label || 'TRANSITION';
  const cfg    = REGIME[label] || REGIME.TRANSITION;
  const probs  = regime?.probabilities || {};
  const cb     = regime?.circuit_breaker_active;
  const score  = regime?.conflict_score;

  return (
    <div className={cn(
      'rounded-2xl border p-4 ring-1 transition-all duration-500',
      'bg-card border-edge',
      cfg.ring, cfg.glow,
      cb && 'anim-pulse-border',
    )}>
      {/* Label row */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Market Weather</span>
        <Tooltip term="regime" label="Market regime" />
      </div>

      {/* Weather icon + mood */}
      <div className="flex items-center gap-3 mb-4">
        <span className={cn('text-5xl leading-none', cfg.anim)}>{cfg.icon}</span>
        <div>
          <p className="text-xl font-bold text-cream leading-tight">{cfg.label}</p>
          <span className={cn(
            'inline-block mt-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border',
            cfg.badge
          )}>
            {label.replace('_', ' ')}
          </span>
        </div>
      </div>

      {/* Probability bar */}
      <div className="mb-3">
        <div className="flex h-1.5 rounded-full overflow-hidden gap-px mb-2">
          {PROB_KEYS.map((k, i) => {
            const pct = ((probs[k] || 0) * 100).toFixed(0);
            return +pct > 1 ? (
              <div
                key={k}
                className={cn('rounded-sm transition-all duration-700', PROB_COLORS[i])}
                style={{ width: `${pct}%` }}
                title={`${k}: ${pct}%`}
              />
            ) : null;
          })}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {PROB_KEYS.map((k, i) => {
            const pct = Math.round((probs[k] || 0) * 100);
            return pct > 1 ? (
              <span key={k} className={cn('text-[10px] flex items-center gap-1', PROB_TEXT[i])}>
                <span className={cn('w-1.5 h-1.5 rounded-sm inline-block', PROB_COLORS[i])} />
                {k.replace('_', ' ')} {pct}%
              </span>
            ) : null;
          })}
        </div>
      </div>

      {/* Conflict score */}
      {score != null && (
        <div className="flex items-center gap-2 text-[11px] text-muted border-t border-edge pt-2.5 mt-2">
          <span>⚔️ Conflict index</span>
          <span className={cn(
            'font-jetbrains font-bold',
            score > 50 ? 'text-loss' : score > 25 ? 'text-warn' : 'text-profit'
          )}>
            {score.toFixed(1)}
          </span>
          <Tooltip term="conflict_score" />
        </div>
      )}

      {/* Circuit breaker */}
      {cb && (
        <div className="mt-2.5 flex items-center gap-2 px-3 py-2 rounded-lg bg-warn/8 border border-warn/30 text-warn text-xs">
          <span className="anim-pulse">⚡</span>
          Emergency override active — Arca is being extra cautious
        </div>
      )}
    </div>
  );
}
