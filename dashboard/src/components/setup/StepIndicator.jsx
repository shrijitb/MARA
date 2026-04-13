import { cn } from '../../utils/cn.js';

const STEPS = ['Welcome', 'Device', 'Exchange', 'Data', 'Telegram', 'Launch'];

export default function StepIndicator({ current }) {
  return (
    <div className="flex items-center gap-0 mb-8 overflow-x-auto pb-1">
      {STEPS.map((label, i) => {
        const done   = i < current;
        const active = i === current;
        return (
          <div key={i} className="flex items-center flex-1 min-w-0">
            <div className="flex flex-col items-center gap-1.5 shrink-0">
              {/* Circle */}
              <div className={cn(
                'w-7 h-7 rounded-full border-2 flex items-center justify-center text-xs font-bold transition-all duration-300',
                done   ? 'border-profit bg-profit text-black'
                : active ? 'border-warn bg-warn/10 text-warn'
                : 'border-line bg-transparent text-muted'
              )}>
                {done ? '✓' : i + 1}
              </div>
              <span className={cn(
                'text-[9px] font-bold uppercase tracking-wider whitespace-nowrap',
                active ? 'text-cream' : done ? 'text-profit' : 'text-muted'
              )}>
                {label}
              </span>
            </div>
            {/* Connector */}
            {i < STEPS.length - 1 && (
              <div className={cn(
                'flex-1 h-px mx-1.5 mb-5 transition-all duration-300',
                done ? 'bg-profit' : 'bg-edge'
              )} />
            )}
          </div>
        );
      })}
    </div>
  );
}
