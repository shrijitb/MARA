import { cn } from '../utils/cn.js';

function Bar({ pct, warn, danger }) {
  const color = pct >= danger ? 'bg-loss' : pct >= warn ? 'bg-warn' : 'bg-line';
  return (
    <div className="w-8 h-1 bg-edge rounded-full overflow-hidden">
      <div className={cn('h-full rounded-full transition-all duration-500', color)} style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  );
}

export default function SystemMetrics({ system }) {
  if (!system) return null;
  const ollamaOk  = system.ollama_status === 'running';
  const tempColor = system.temp_celsius >= 80 ? 'text-loss' : system.temp_celsius >= 70 ? 'text-warn' : 'text-muted';

  const items = [
    { label: 'CPU',  value: `${Math.round(system.cpu_pct || 0)}%`,  bar: { pct: system.cpu_pct || 0, warn: 70, danger: 90 } },
    { label: 'RAM',  value: `${Math.round(system.ram_pct || 0)}%`,  bar: { pct: system.ram_pct || 0, warn: 80, danger: 95 } },
    { label: 'Disk', value: `${Math.round(system.disk_pct || 0)}%`, bar: { pct: system.disk_pct || 0, warn: 80, danger: 92 } },
  ];

  const uptime = (() => {
    const h = system.uptime_hours || 0;
    const d = Math.floor(h / 24), r = Math.floor(h % 24);
    return d > 0 ? `${d}d ${r}h` : `${r}h`;
  })();

  return (
    <div className="flex items-center gap-4 px-4 py-2 flex-wrap">
      {/* Bar metrics */}
      {items.map(({ label, value, bar }) => (
        <div key={label} className="flex items-center gap-1.5">
          <span className="text-[10px] text-muted">{label}</span>
          <Bar {...bar} />
          <span className="text-[10px] font-jetbrains text-data">{value}</span>
        </div>
      ))}

      {/* Temperature */}
      {system.temp_celsius != null && (
        <div className="flex items-center gap-1">
          <span className="text-[10px] text-muted">Temp</span>
          <span className={cn('text-[10px] font-jetbrains font-bold', tempColor)}>
            {Math.round(system.temp_celsius)}°C
          </span>
        </div>
      )}

      {/* AI status */}
      <div className="flex items-center gap-1.5">
        <span className={cn('w-1.5 h-1.5 rounded-full', ollamaOk ? 'bg-profit anim-pulse' : 'bg-loss')}
          style={ollamaOk ? { boxShadow: '0 0 4px #00E676' } : undefined}
        />
        <span className={cn('text-[10px] font-semibold', ollamaOk ? 'text-profit' : 'text-loss')}>
          AI {ollamaOk ? (system.ollama_model || 'Online') : 'Offline'}
        </span>
      </div>

      {/* Uptime */}
      <div className="flex items-center gap-1">
        <span className="text-[10px] text-muted">Up</span>
        <span className="text-[10px] font-jetbrains text-data">{uptime}</span>
      </div>

      {/* Device */}
      {system.device_board && (
        <span className="text-[10px] text-muted hidden xl:block">{system.device_board}</span>
      )}
    </div>
  );
}
