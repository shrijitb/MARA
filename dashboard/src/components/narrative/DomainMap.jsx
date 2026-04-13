import { cn } from '../../utils/cn.js';
import Tooltip from '../education/Tooltip.jsx';

const ACTION = {
  enter:    { dot: '🟢', cls: 'text-profit border-l-profit', label: 'ENTERED' },
  increase: { dot: '🟢', cls: 'text-profit border-l-profit', label: 'INCREASED' },
  hold:     { dot: '⚪', cls: 'text-muted border-l-rim',     label: 'NO CHANGE' },
  watch:    { dot: '🟡', cls: 'text-warn border-l-warn',     label: 'WATCHING' },
  reduce:   { dot: '🟡', cls: 'text-warn border-l-warn',     label: 'REDUCING' },
  exit:     { dot: '🔴', cls: 'text-loss border-l-loss',     label: 'EXITED' },
};

const SRC_ICON = { gdelt: '🌐', aisstream: '⚓', edgar: '📋', nasa_firms: '🛰', ucdp: '⚔️', usgs: '🌋', fred: '📈' };

function timeAgo(iso) {
  if (!iso) return '';
  const m = Math.floor((Date.now() - new Date(iso)) / 60000);
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  return h < 24 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`;
}

function clean(rationale, action, domain) {
  if (!rationale) {
    const d = domain?.replace(/_/g, ' ') || 'this market';
    return action === 'hold' ? `No significant signals in ${d} right now.` : `Adjusting position in ${d}.`;
  }
  return rationale
    .replace(/weight_modifier:\s*[\d.]+,?\s*/gi, '')
    .replace(/(\w+_\w+):/g, (_, d) => d.replace(/_/g, ' ') + ':')
    .trim();
}

function DomainCard({ d }) {
  const cfg = ACTION[d.action] || ACTION.hold;
  const sources = d.triggered_by || [];
  const confidence = Math.round((d.confidence || 0) * 100);
  const rationale  = clean(d.rationale, d.action, d.domain);
  const ago        = timeAgo(d.expires_at);

  return (
    <div className={cn(
      'bg-black/40 border border-edge rounded-xl p-3 border-l-2 transition-all duration-300',
      cfg.cls
    )}>
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-1.5">
          <span className="text-sm leading-none">{cfg.dot}</span>
          <span className={cn('text-[10px] font-bold uppercase tracking-wider', cfg.cls.split(' ')[0])}>
            {cfg.label}:
          </span>
          <span className="text-xs font-semibold text-cream capitalize">
            {d.domain?.replace(/_/g, ' ')}
          </span>
        </div>
        {confidence > 0 && (
          <span className="text-[10px] text-muted">{confidence}%</span>
        )}
      </div>

      <p className="text-[12px] text-cream/70 leading-relaxed mb-2">
        "{rationale}"
      </p>

      {sources.length > 0 && (
        <div className="flex items-center justify-between">
          <div className="flex gap-1 flex-wrap">
            {sources.map(s => (
              <span key={s} className="text-[9px] bg-edge text-muted px-1.5 py-0.5 rounded">
                {SRC_ICON[s] || '📡'} {s}
              </span>
            ))}
          </div>
          {ago && <span className="text-[10px] text-muted shrink-0 ml-2">{ago}</span>}
        </div>
      )}
    </div>
  );
}

export default function DomainMap({ domains }) {
  const decisions = [...(domains?.decisions || [])].sort((a, b) => {
    const order = { exit: 0, reduce: 1, enter: 2, increase: 2, watch: 3, hold: 4 };
    return (order[a.action] ?? 4) - (order[b.action] ?? 4);
  });

  return (
    <div className="bg-card border border-edge rounded-2xl p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Intelligence Feed</span>
        <Tooltip term="domain" label="Market domains" />
      </div>

      {decisions.length === 0 ? (
        <div className="text-center text-muted text-xs py-6">
          No domain decisions yet. First cycle running...
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {decisions.map((d, i) => <DomainCard key={`${d.domain}-${i}`} d={d} />)}
        </div>
      )}
    </div>
  );
}
