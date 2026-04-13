import { cn } from '../utils/cn.js';
import Tooltip from './education/Tooltip.jsx';

function MidBar({ value }) {
  // value: –1 to +1
  const clamped = Math.max(-1, Math.min(1, value || 0));
  const pct = Math.abs(clamped) * 50; // 0–50%
  const positive = clamped >= 0;
  const color = clamped > 0.1 ? 'bg-profit' : clamped < -0.1 ? 'bg-loss' : 'bg-muted';

  return (
    <div className="relative h-1.5 bg-edge rounded-full overflow-visible">
      {/* Center pin */}
      <div className="absolute left-1/2 top-0 bottom-0 w-px bg-line" />
      {/* Fill */}
      <div
        className={cn('absolute top-0 bottom-0 rounded-full transition-all duration-700', color)}
        style={{ [positive ? 'left' : 'right']: '50%', width: `${pct}%` }}
      />
    </div>
  );
}

function ConfBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 70 ? 'bg-profit' : pct >= 40 ? 'bg-warn' : 'bg-muted';
  return (
    <div>
      <div className="flex justify-between text-[10px] text-muted mb-1">
        <span>Confidence</span>
        <span className={cn('font-jetbrains font-bold', pct >= 70 ? 'text-profit' : pct >= 40 ? 'text-warn' : 'text-muted')}>{pct}%</span>
      </div>
      <div className="h-1 bg-edge rounded-full">
        <div className={cn('h-full rounded-full transition-all duration-700', color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export default function ThesisCard({ analyst }) {
  const thesis   = analyst?.thesis;
  const director = thesis?.director;
  const quant    = thesis?.quant;
  const risk     = thesis?.risk;

  if (!thesis) {
    return (
      <div className="bg-card border border-edge rounded-2xl p-4">
        <div className="text-[10px] font-bold uppercase tracking-widest text-muted mb-3">AI Analysis</div>
        <p className="text-xs text-muted text-center py-6">Waiting for analyst cycle...</p>
      </div>
    );
  }

  const outlookColor = director?.market_outlook === 'bullish' ? 'text-profit'
    : director?.market_outlook === 'bearish' ? 'text-loss' : 'text-warn';

  return (
    <div className="bg-card border border-edge rounded-2xl p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">AI Analysis</span>
        <Tooltip term="advisory_only" label="What is this?" />
      </div>

      {/* Director block */}
      {director && (
        <div className="bg-black/50 rounded-xl p-3">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm">📊</span>
            <span className="text-xs font-semibold text-cream">Market Outlook:</span>
            <span className={cn('text-xs font-bold capitalize', outlookColor)}>
              {director.market_outlook}
            </span>
          </div>

          {director.thesis && (
            <p className="text-[12px] text-muted leading-relaxed italic mb-2">
              "{director.thesis}"
            </p>
          )}

          {director.key_drivers?.length > 0 && (
            <ul className="flex flex-col gap-0.5">
              {director.key_drivers.slice(0, 3).map((d, i) => (
                <li key={i} className="text-[11px] text-cream/70 flex gap-2">
                  <span className="text-profit shrink-0">·</span>{d}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* Quant block */}
      {quant && (
        <div className="bg-black/50 rounded-xl p-3 flex flex-col gap-2.5">
          <div className="flex items-center gap-2">
            <span className="text-sm">🎯</span>
            <span className="text-xs font-semibold text-cream">Signal</span>
            <span className="text-[10px] font-jetbrains font-bold text-muted">
              {quant.signal_strength > 0 ? '+' : ''}{(quant.signal_strength || 0).toFixed(2)}
            </span>
            <Tooltip term="sharpe" label="Signal quality" />
          </div>
          <MidBar value={quant.signal_strength} />
          <ConfBar value={quant.confidence} />
          {quant.recommended_instruments?.length > 0 && (
            <p className="text-[11px] text-muted">
              Recommends: <span className="text-cream font-jetbrains">{quant.recommended_instruments.join(', ')}</span>
              {quant.position_sizing_hint && <span> · {quant.position_sizing_hint} position</span>}
            </p>
          )}
        </div>
      )}

      {/* Risk block */}
      {risk && (
        <div className={cn(
          'rounded-xl p-3 border',
          risk.approved
            ? 'bg-profit/5 border-profit/20'
            : 'bg-loss/5 border-loss/20'
        )}>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm">{risk.approved ? '✅' : '🚫'}</span>
            <span className={cn('text-xs font-bold', risk.approved ? 'text-profit' : 'text-loss')}>
              Risk Check: {risk.approved ? 'Approved' : 'Blocked'}
            </span>
            <Tooltip term="risk_check" label="Risk check" />
          </div>
          {risk.risk_flags?.length > 0 && (
            <p className="text-[11px] text-loss mb-1">⚠️ {risk.risk_flags.join(', ')}</p>
          )}
          <p className="text-[11px] text-muted leading-relaxed">
            {risk.reasoning || `Max position: ${Math.round((risk.max_position_pct || 0) * 100)}% of capital.`}
          </p>
        </div>
      )}
    </div>
  );
}
