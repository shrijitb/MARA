import { useState } from 'react';
import { cn } from '../../utils/cn.js';
import Tooltip from '../education/Tooltip.jsx';

const META = {
  nautilus: {
    icon: '🤖', name: 'Trading Bot',
    ring: 'ring-info/20',  badge: 'bg-info/10 text-info border-info/25',
    accent: 'border-l-info', glow: 'shadow-[0_0_20px_rgba(0,176,255,0.05)]',
    tooltipTerm: 'sharpe', tooltipLabel: 'Strategy',
  },
  prediction_markets: {
    icon: '🔮', name: 'Predictions',
    ring: 'ring-purple/20', badge: 'bg-purple/10 text-purple border-purple/25',
    accent: 'border-l-purple', glow: 'shadow-[0_0_20px_rgba(224,64,251,0.05)]',
    tooltipTerm: 'domain', tooltipLabel: 'Prediction markets',
  },
  analyst: {
    icon: '🧠', name: 'Analyst',
    ring: 'ring-warn/20', badge: 'bg-warn/10 text-warn border-warn/25',
    accent: 'border-l-warn', glow: 'shadow-[0_0_20px_rgba(255,215,64,0.05)]',
    tooltipTerm: 'advisory_only', tooltipLabel: 'AI Analyst',
  },
  core_dividends: {
    icon: '💰', name: 'Savings',
    ring: 'ring-profit/20', badge: 'bg-profit/10 text-profit border-profit/25',
    accent: 'border-l-profit', glow: 'shadow-[0_0_20px_rgba(0,230,118,0.05)]',
    tooltipTerm: 'allocation', tooltipLabel: 'Dividend strategy',
  },
};

function humanize(key, data) {
  if (!data) return 'Standing by.';
  if (key === 'nautilus') {
    const sym = (data.last_signal?.instrument || 'BTC-USDT').split('-')[0];
    const pnl = data.pnl_usd || 0;
    const dir = pnl >= 0 ? 'up' : 'down';
    const sl  = ((data.stop_loss_pct || 0.02) * 100).toFixed(0);
    if (data.open_positions > 0)
      return `Watching ${sym}. I bought earlier and I'm ${dir} $${Math.abs(pnl).toFixed(2)}. Safety net triggers if it drops ${sl}%.`;
    if (data.adx_state === 'ambiguous')
      return `Scanning ${sym} — market isn't showing a clear direction yet. Waiting for a stronger signal.`;
    return `Scanning ${sym} for an entry. Market is ${data.adx_state || 'ranging'}. Waiting for the right moment.`;
  }
  if (key === 'prediction_markets') {
    const n = data.markets_monitored || 0;
    const pnl = data.pnl_usd || 0;
    if (data.open_positions > 0)
      return `Watching ${n} prediction markets. ${data.open_positions} active bet${data.open_positions !== 1 ? 's' : ''}. ${pnl >= 0 ? 'Doing well.' : "Some bets haven't played out yet."}`;
    return `Scanning ${n} prediction markets. No opportunity found yet.`;
  }
  if (key === 'analyst') {
    const outlook = data.thesis?.director?.market_outlook || 'neutral';
    const driver  = data.thesis?.director?.key_drivers?.[0] || 'current market conditions';
    const ok      = data.thesis?.risk?.approved;
    return `Outlook: ${outlook.charAt(0).toUpperCase() + outlook.slice(1)}. Main driver: ${driver}. ${ok ? 'Risk check passed.' : 'Flagged concerns.'}`;
  }
  if (key === 'core_dividends') {
    const h = data.holdings || [];
    if (!h.length) return 'Waiting to buy dividend stocks.';
    return `Holding ${h.map(x => x.ticker).join(' and ')}. These pay dividends every quarter. Next payout expected Q3.`;
  }
  return data.current_action || 'Standing by.';
}

function StatusDot({ status }) {
  const map = {
    running: { dot: 'bg-profit', pulse: true,  label: 'Online',   text: 'text-profit' },
    paused:  { dot: 'bg-warn',   pulse: false, label: 'Paused',   text: 'text-warn'   },
    crashed: { dot: 'bg-loss',   pulse: true,  label: 'Offline',  text: 'text-loss'   },
    default: { dot: 'bg-rim',    pulse: false, label: 'Starting', text: 'text-muted'  },
  };
  const cfg = map[status] || map.default;
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn('w-1.5 h-1.5 rounded-full', cfg.dot, cfg.pulse && 'anim-pulse')}
        style={cfg.dot === 'bg-profit' ? { boxShadow: '0 0 5px #00E676' } : undefined} />
      <span className={cn('text-[10px] font-bold', cfg.text)}>{cfg.label}</span>
    </div>
  );
}

function PauseModal({ name, onConfirm, onCancel, busy }) {
  const [text, setText] = useState('');
  const ok = text === 'PAUSE';
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.85)', backdropFilter: 'blur(8px)' }}>
      <div className="anim-slide-up w-full max-w-xs bg-modal border border-line rounded-2xl p-6 shadow-2xl">
        <h3 className="text-cream font-bold text-base mb-2">Pause {name}?</h3>
        <p className="text-muted text-sm leading-relaxed mb-4">
          No new trades will be placed. Open positions stay open.
        </p>
        <label className="text-[10px] font-bold text-muted uppercase tracking-widest mb-1.5 block">
          Type <span className="text-warn font-jetbrains">PAUSE</span> to confirm
        </label>
        <input
          autoFocus
          value={text}
          onChange={e => setText(e.target.value.toUpperCase())}
          placeholder="PAUSE"
          className="w-full px-3 py-2 bg-black border border-line rounded-lg text-cream text-sm font-jetbrains outline-none focus:border-warn/50 mb-4 transition-colors placeholder:text-muted/30"
        />
        <div className="flex gap-2">
          <button onClick={onCancel}
            className="flex-1 py-2 rounded-lg bg-surface border border-line text-muted text-sm hover:text-cream transition-colors">
            Cancel
          </button>
          <button onClick={() => ok && onConfirm()} disabled={!ok || busy}
            className={cn('flex-1 py-2 rounded-lg text-sm font-bold transition-all',
              ok ? 'bg-warn text-black hover:bg-warn/90 cursor-pointer' : 'bg-edge text-muted cursor-not-allowed')}>
            {busy ? '...' : 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  );
}

function WorkerCard({ workerKey, data }) {
  const meta = META[workerKey];
  const [showPause, setShowPause] = useState(false);
  const [pausing, setPausing] = useState(false);
  if (!meta) return null;

  const pnl       = data?.pnl_usd || 0;
  const allocated = data?.allocated_usd || 0;
  const status    = data?.status || 'starting';
  const up        = pnl >= 0;
  const story     = humanize(workerKey, data);

  async function doPause() {
    setPausing(true);
    await fetch('/api/pause', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ worker: workerKey }) });
    setPausing(false);
    setShowPause(false);
  }
  async function doResume() {
    await fetch('/api/resume', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ worker: workerKey }) });
  }

  return (
    <>
      <div className={cn(
        'bg-card rounded-xl border border-edge p-4 ring-1 transition-all duration-300',
        'border-l-2', meta.accent, meta.ring, meta.glow,
      )}>
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-xl leading-none">{meta.icon}</span>
            <span className="text-sm font-bold text-cream">{meta.name}</span>
          </div>
          <StatusDot status={status} />
        </div>

        {/* Story */}
        <p className="text-[13px] text-cream/80 leading-relaxed italic mb-3 pl-3 border-l border-rim">
          "{story}"
        </p>

        {/* Advisory badge */}
        {data?.advisory_only && (
          <div className="flex items-center gap-1.5 text-xs text-muted mb-2">
            <span>🔍</span> Advisory only — no direct trades
            <Tooltip term="advisory_only" />
          </div>
        )}

        {/* Metrics */}
        {!data?.advisory_only && (
          <div className="flex gap-4 pt-2.5 border-t border-edge/60 mb-2.5">
            <div>
              <div className="text-[9px] font-bold uppercase tracking-widest text-muted mb-0.5">Managing</div>
              <div className="text-xs font-bold font-jetbrains text-data">${allocated.toFixed(2)}</div>
            </div>
            <div>
              <div className="text-[9px] font-bold uppercase tracking-widest text-muted mb-0.5">Gain</div>
              <div className={cn('text-xs font-bold font-jetbrains', up ? 'text-profit' : 'text-loss')}>
                {up ? '+' : ''}${pnl.toFixed(2)}
              </div>
            </div>
            {data?.open_positions != null && (
              <div>
                <div className="text-[9px] font-bold uppercase tracking-widest text-muted mb-0.5">Positions</div>
                <div className="text-xs font-bold font-jetbrains text-data">{data.open_positions}</div>
              </div>
            )}
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between">
          <Tooltip term={meta.tooltipTerm} label={meta.tooltipLabel} />
          {status !== 'paused'
            ? <button onClick={() => setShowPause(true)}
                className="text-[10px] text-muted hover:text-cream border border-edge hover:border-line rounded-md px-2.5 py-1 transition-all">
                ⏸ Pause
              </button>
            : <button onClick={doResume}
                className="text-[10px] text-profit border border-profit/30 hover:bg-profit/10 rounded-md px-2.5 py-1 transition-all">
                ▶ Resume
              </button>
          }
        </div>
      </div>

      {showPause && (
        <PauseModal
          name={meta.name}
          onConfirm={doPause}
          onCancel={() => setShowPause(false)}
          busy={pausing}
        />
      )}
    </>
  );
}

export default function WorkerStory({ workers }) {
  return (
    <div className="flex flex-col gap-3">
      <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Workers</span>
      {['nautilus', 'prediction_markets', 'analyst', 'core_dividends'].map(k => (
        <WorkerCard key={k} workerKey={k} data={workers?.[k]} />
      ))}
    </div>
  );
}
