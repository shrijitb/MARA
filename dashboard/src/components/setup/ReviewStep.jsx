import { cn } from '../../utils/cn.js';

export default function ReviewStep({ onBack, onLaunch, setupStatus, launching }) {
  const s = setupStatus || {};

  const checks = [
    { label: 'Paper trading active',        ok: true,                   note: null },
    { label: 'OKX exchange',                ok: s.okx_configured,       note: s.okx_configured ? null : 'paper trades without live keys' },
    { label: 'AI model (Ollama)',            ok: s.ollama_ready,         note: s.ollama_ready ? null : 'pulling model on first start…' },
    { label: 'Telegram alerts',             ok: s.telegram_configured,  note: s.telegram_configured ? null : 'skipped — add later in settings' },
    { label: 'FRED macro data',             ok: s.fred_configured,      note: s.fred_configured ? null : 'using yfinance fallback' },
    { label: 'Prediction markets (Kalshi)', ok: s.kalshi_configured,    note: s.kalshi_configured ? null : 'skipped — add later' },
  ];

  return (
    <div className="anim-fade-in max-w-md mx-auto">
      <div className="bg-card border border-edge rounded-2xl p-6 mb-4">
        <div className="text-center mb-6">
          <div className="text-5xl mb-3">🚀</div>
          <h2 className="text-xl font-bold text-cream">Ready to launch</h2>
          <p className="text-sm text-muted mt-1.5 leading-relaxed">
            Arca will start in paper trading mode. No real money is at risk.
          </p>
        </div>

        {/* Checklist */}
        <div className="bg-black/50 rounded-xl overflow-hidden mb-5">
          {checks.map(({ label, ok, note }) => (
            <div key={label} className="flex items-start gap-3 px-4 py-2.5 border-b border-edge last:border-0">
              <span className={cn('text-sm shrink-0 mt-0.5', ok ? 'text-profit' : 'text-warn')}>
                {ok ? '✓' : '—'}
              </span>
              <div>
                <span className="text-xs text-cream">{label}</span>
                {note && <p className="text-[10px] text-muted mt-0.5">{note}</p>}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-start gap-2 p-3 bg-info/5 border border-info/15 rounded-xl text-xs text-muted">
          <span className="shrink-0">🤖</span>
          <span>The regime classifier runs its first cycle within 90 seconds of launch. Check the dashboard to see Arca's market read.</span>
        </div>
      </div>

      <div className="flex gap-2.5">
        <button onClick={onBack} className={ghost}>← Back</button>
        <button
          onClick={onLaunch}
          disabled={launching}
          className={cn(
            'flex-1 py-3.5 font-bold text-sm rounded-xl transition-all duration-200',
            launching
              ? 'bg-line text-muted cursor-wait'
              : 'bg-profit text-black hover:bg-profit/90 active:scale-[0.98]'
          )}
        >
          {launching ? '⏳ Starting Arca...' : '🚀 Launch Arca'}
        </button>
      </div>
    </div>
  );
}

const ghost = 'px-5 py-3 bg-transparent border border-edge text-muted text-sm rounded-xl hover:border-line hover:text-cream transition-all';
