import { cn } from '../../utils/cn.js';
import Tooltip from '../education/Tooltip.jsx';

function computeScore(portfolio, regime) {
  if (!portfolio) return 50;
  let s = 100;
  s -= (portfolio.drawdown_pct || 0) * 3;
  s -= (regime?.probabilities?.CRISIS || 0) * 30;
  s += Math.min((portfolio.total_pnl_pct || 0) * 2, 20);
  s -= Math.max(0, (portfolio.drawdown_pct || 0) - 10) * 2;
  return Math.max(0, Math.min(100, s));
}

function polar(cx, cy, r, deg) {
  const rad = ((deg - 90) * Math.PI) / 180;
  return { x: cx + r * Math.sin(rad), y: cy - r * Math.cos(rad) };
}

function arc(cx, cy, r, a1, a2) {
  const s = polar(cx, cy, r, a1);
  const e = polar(cx, cy, r, a2);
  return `M ${s.x} ${s.y} A ${r} ${r} 0 ${a2 - a1 > 180 ? 1 : 0} 1 ${e.x} ${e.y}`;
}

const CX = 90, CY = 82, R = 64, SW = 9;
const START = -148, END = 148;

const SEGMENTS = [
  { a1: -148, a2: -50, color: '#FF1744' },
  { a1:  -50, a2:  50, color: '#FFD740' },
  { a1:   50, a2: 148, color: '#00E676' },
];

export default function RiskMeter({ portfolio, regime }) {
  const score = computeScore(portfolio, regime);
  const needleAngle = START + (score / 100) * (END - START);
  const tip = polar(CX, CY, 52, needleAngle);

  const { text, icon, ringClass } = score >= 60
    ? { text: 'Portfolio looks good',  icon: '☀️', ringClass: 'ring-profit/15' }
    : score >= 30
    ? { text: 'Arca is being careful', icon: '🌤', ringClass: 'ring-warn/15' }
    : { text: 'Protecting capital',    icon: '⛈', ringClass: 'ring-loss/15' };

  const scoreColor = score >= 60 ? '#00E676' : score >= 30 ? '#FFD740' : '#FF1744';

  return (
    <div className={cn('bg-card border border-edge rounded-2xl p-4 ring-1', ringClass)}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] font-bold uppercase tracking-widest text-muted">Portfolio Health</span>
        <Tooltip term="drawdown" label="Portfolio health" />
      </div>

      {/* SVG gauge */}
      <div className="flex justify-center my-1">
        <svg width={180} height={104} viewBox="0 0 180 104">
          {/* Track */}
          <path d={arc(CX, CY, R, START, END)} fill="none" stroke="#1A1A1A" strokeWidth={SW} strokeLinecap="round" />

          {/* Coloured arcs */}
          {SEGMENTS.map((seg, i) => (
            <path key={i} d={arc(CX, CY, R, seg.a1, seg.a2)}
              fill="none" stroke={seg.color} strokeWidth={SW - 2}
              strokeLinecap="round" opacity={0.75} />
          ))}

          {/* Needle glow */}
          <line x1={CX} y1={CY} x2={tip.x} y2={tip.y}
            stroke={scoreColor} strokeWidth={4} strokeLinecap="round" opacity={0.2}
            style={{ filter: `blur(3px)`, transition: 'x2 0.9s ease, y2 0.9s ease' }} />

          {/* Needle */}
          <line x1={CX} y1={CY} x2={tip.x} y2={tip.y}
            stroke="#FFFDD0" strokeWidth={2} strokeLinecap="round"
            style={{ transition: 'x2 0.9s ease, y2 0.9s ease' }} />

          {/* Hub */}
          <circle cx={CX} cy={CY} r={5} fill="#FFFDD0" />
          <circle cx={CX} cy={CY} r={3} fill="#000" />

          {/* Score */}
          <text x={CX} y={CY + 24} textAnchor="middle"
            fill={scoreColor} fontSize={20} fontWeight={700}
            fontFamily="'JetBrains Mono', monospace">
            {Math.round(score)}
          </text>
        </svg>
      </div>

      {/* Label */}
      <p className="text-center text-sm font-semibold text-cream">
        {icon} {text}
      </p>
      {(portfolio?.drawdown_pct || 0) > 0 && (
        <p className="text-center text-xs text-muted mt-0.5">
          {portfolio.drawdown_pct.toFixed(1)}% below peak
        </p>
      )}
    </div>
  );
}
