import { cn } from '../../utils/cn.js';

function fmtTime(iso) {
  if (!iso) return '';
  try { return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
  catch { return ''; }
}

function buildEvents(data) {
  if (!data) return [];
  const events = [];
  const workerNames = { nautilus: '🤖 Trading Bot', prediction_markets: '🔮 Predictions', analyst: '🧠 Analyst', core_dividends: '💰 Savings' };

  Object.entries(data.workers || {}).forEach(([key, w]) => {
    if (!w?.last_signal_time || !w?.last_signal) return;
    const sig = w.last_signal;
    events.push({
      time: w.last_signal_time,
      icon: '🤖',
      title: workerNames[key] || key,
      body: `${sig.action || 'Signal'}${sig.instrument ? ': ' + sig.instrument : ''} — ${sig.rationale || w.current_action || ''}`,
      color: 'bg-info/10 border-info/25',
    });
  });

  if (data.backtest?.last_run) {
    const bt = data.backtest;
    const strats = Object.entries(bt).filter(([k]) => k !== 'last_run');
    const promoted = strats.filter(([, v]) => v?.promoted).map(([k]) => k.replace('_', ' '));
    events.push({
      time: bt.last_run,
      icon: '🔬',
      title: 'Nightly Checkup',
      body: promoted.length ? `Improved: ${promoted.join(', ')} ✅` : 'No improvements this run. Current settings kept.',
      color: 'bg-warn/8 border-warn/20',
    });
  }

  (data.domains?.decisions || []).forEach(d => {
    if (d.action === 'hold') return;
    const icons = { exit: '🔴', enter: '🟢', increase: '🟢', reduce: '🟡', watch: '🟡' };
    events.push({
      time: d.expires_at,
      icon: icons[d.action] || '📡',
      title: '📰 Intelligence',
      body: `${d.action?.toUpperCase()}: ${d.domain?.replace(/_/g, ' ')} — ${(d.rationale || '').slice(0, 90)}`,
      color: d.action === 'exit' ? 'bg-loss/8 border-loss/20' : 'bg-profit/8 border-profit/20',
    });
  });

  return events
    .filter(e => e.time)
    .sort((a, b) => new Date(b.time) - new Date(a.time))
    .slice(0, 8);
}

export default function TimelineView({ data }) {
  const events = buildEvents(data);

  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <div className="text-[10px] font-bold uppercase tracking-widest text-muted mb-3">
        Today's Activity
      </div>

      {events.length === 0 ? (
        <div className="text-xs text-muted text-center py-5">Waiting for first cycle...</div>
      ) : (
        <div className="flex flex-col">
          {events.map((evt, i) => (
            <div key={i} className="flex gap-2.5 pb-4 relative">
              {/* Vertical connector */}
              {i < events.length - 1 && (
                <div className="absolute left-[13px] top-6 bottom-0 w-px bg-edge" />
              )}

              {/* Icon bubble */}
              <div className={cn(
                'w-7 h-7 rounded-full border flex items-center justify-center text-sm shrink-0 z-1 bg-card',
                evt.color || 'bg-surface border-edge'
              )}>
                {evt.icon}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0 pt-0.5">
                <div className="flex items-baseline justify-between gap-2 mb-0.5">
                  <span className="text-[11px] font-bold text-cream truncate">{evt.title}</span>
                  <span className="text-[10px] text-muted shrink-0 font-jetbrains">{fmtTime(evt.time)}</span>
                </div>
                <p className="text-[11px] text-muted leading-snug line-clamp-2">{evt.body}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
