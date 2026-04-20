import { useState } from 'react';
import { cn } from '../utils/cn.js';
import { useArcaData } from '../hooks/useArcaData.js';

import RegimeMood    from '../components/narrative/RegimeMood.jsx';
import MoneyFlow     from '../components/narrative/MoneyFlow.jsx';
import WorkerStory   from '../components/narrative/WorkerStory.jsx';
import DomainMap     from '../components/narrative/DomainMap.jsx';
import RiskMeter     from '../components/narrative/RiskMeter.jsx';
import TimelineView  from '../components/narrative/TimelineView.jsx';
import ThesisCard    from '../components/ThesisCard.jsx';
import PortfolioView from '../components/PortfolioView.jsx';
import BacktestReport from '../components/BacktestReport.jsx';
import SystemMetrics from '../components/SystemMetrics.jsx';
import GlobalControls from '../components/GlobalControls.jsx';
import SetupWizard   from './SetupWizard.jsx';

const TABS = [
  { id: 'home',    icon: '🏠', label: 'Home' },
  { id: 'workers', icon: '🤖', label: 'Workers' },
  { id: 'intel',   icon: '📡', label: 'Intel' },
];

export default function Dashboard({ data: initialData }) {
  const { data: liveData, setupStatus, refresh } = useArcaData();
  const [mobileTab, setMobileTab] = useState('home');
  const [showSettings, setShowSettings] = useState(false);

  // Prefer live data, fall back to initial
  const data = liveData || initialData || {};
  const { regime, workers, portfolio, domains, backtest, system } = data;

  if (showSettings) {
    return (
      <SetupWizard
        onComplete={() => { setShowSettings(false); refresh(); }}
        setupStatus={setupStatus}
      />
    );
  }

  return (
    <div className="h-screen bg-black flex flex-col overflow-hidden">
      {/* ── Top bar ── */}
      <header className="glass border-b border-edge flex items-center justify-between px-4 py-2.5 shrink-0 z-10">
        <div className="flex items-center gap-3">
          <span className="font-jetbrains text-base font-bold tracking-[0.2em] gradient-text">ARCA</span>
          {regime?.label && (
            <RegimeChip label={regime.label} />
          )}
        </div>

        <div className="flex items-center gap-3">
          {system && <CompactMetrics system={system} />}
          {data.timestamp && (
            <span className="text-muted text-xs hidden md:block font-jetbrains">
              {new Date(data.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
        </div>
      </header>

      {/* ── Main content ── */}
      <div className="flex-1 overflow-hidden relative">

        {/* Desktop: 3-column grid */}
        <div className="hidden lg:grid h-full gap-3 p-3 overflow-hidden"
          style={{ gridTemplateColumns: '300px 1fr 380px' }}
        >
          {/* Left column */}
          <div className="flex flex-col gap-3 overflow-y-auto pb-3">
            <RegimeMood regime={regime} />
            <RiskMeter portfolio={portfolio} regime={regime} />
            <MoneyFlow portfolio={portfolio} workers={workers} />
            <div className="mt-auto pt-3">
              <GlobalControls onOpenSettings={() => setShowSettings(true)} />
            </div>
          </div>

          {/* Centre column */}
          <div className="flex flex-col gap-3 overflow-y-auto pb-3">
            <PortfolioView portfolio={portfolio} workers={workers} />
            <WorkerStory workers={workers} />
            <BacktestReport backtest={backtest} />
          </div>

          {/* Right column */}
          <div className="flex flex-col gap-3 overflow-y-auto pb-3">
            <DomainMap domains={domains} />
            <TimelineView data={data} />
            <ThesisCard analyst={workers?.analyst} />
          </div>
        </div>

        {/* Tablet: 2-column grid */}
        <div className="hidden md:grid lg:hidden h-full gap-3 p-3 overflow-auto grid-cols-2 content-start">
          <RegimeMood regime={regime} />
          <RiskMeter portfolio={portfolio} regime={regime} />
          <div className="col-span-2"><MoneyFlow portfolio={portfolio} workers={workers} /></div>
          <div className="col-span-2"><WorkerStory workers={workers} /></div>
          <DomainMap domains={domains} />
          <TimelineView data={data} />
          <div className="col-span-2"><PortfolioView portfolio={portfolio} workers={workers} /></div>
          <div className="col-span-2"><ThesisCard analyst={workers?.analyst} /></div>
          <div className="col-span-2"><BacktestReport backtest={backtest} /></div>
          <div className="col-span-2"><GlobalControls onOpenSettings={() => setShowSettings(true)} /></div>
        </div>

        {/* Mobile: single column with tab switcher */}
        <div className="md:hidden h-full overflow-y-auto pb-20 p-3 flex flex-col gap-3">
          {mobileTab === 'home' && (
            <>
              <RegimeMood regime={regime} />
              <RiskMeter portfolio={portfolio} regime={regime} />
              <MoneyFlow portfolio={portfolio} workers={workers} />
              <PortfolioView portfolio={portfolio} workers={workers} />
            </>
          )}
          {mobileTab === 'workers' && (
            <WorkerStory workers={workers} />
          )}
          {mobileTab === 'intel' && (
            <>
              <DomainMap domains={domains} />
              <TimelineView data={data} />
              <ThesisCard analyst={workers?.analyst} />
              <BacktestReport backtest={backtest} />
            </>
          )}
        </div>
      </div>

      {/* ── System metrics bar (desktop only) ── */}
      <div className="hidden lg:block shrink-0 border-t border-edge">
        <SystemMetrics system={system} />
      </div>

      {/* ── Mobile bottom nav ── */}
      <nav className="md:hidden fixed bottom-0 inset-x-0 glass border-t border-edge flex z-20">
        {TABS.map(tab => (
          <button
            key={tab.id}
            onClick={() => setMobileTab(tab.id)}
            className={cn(
              'flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 text-xs font-semibold transition-colors',
              mobileTab === tab.id ? 'text-warn' : 'text-muted'
            )}
          >
            <span className="text-base leading-none">{tab.icon}</span>
            {tab.label}
          </button>
        ))}
        <button
          onClick={() => setShowSettings(true)}
          className="flex-1 flex flex-col items-center justify-center gap-0.5 py-2.5 text-xs font-semibold text-muted"
        >
          <span className="text-base leading-none">⚙</span>
          Settings
        </button>
      </nav>
    </div>
  );
}

/* ── Small helpers ─────────────────────────────────────────────── */
const REGIME_COLORS = {
  RISK_ON:     'text-profit bg-profit/10 border-profit/25',
  RISK_OFF:    'text-orange bg-orange/10 border-orange/25',
  CRISIS:      'text-loss   bg-loss/10   border-loss/25',
  TRANSITION:  'text-warn   bg-warn/10   border-warn/25',
};

function RegimeChip({ label }) {
  const cls = REGIME_COLORS[label] || REGIME_COLORS.TRANSITION;
  const weatherMap = { RISK_ON: '☀️', RISK_OFF: '🌧', CRISIS: '⛈', TRANSITION: '🌤' };
  return (
    <span className={cn('inline-flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full border', cls)}>
      {weatherMap[label]} {label.replace('_', ' ')}
    </span>
  );
}

function CompactMetrics({ system }) {
  const tempColor = system.temp_celsius >= 80 ? 'text-loss' : system.temp_celsius >= 70 ? 'text-warn' : 'text-muted';
  return (
    <div className="hidden sm:flex items-center gap-3 text-xs font-jetbrains">
      <span className="text-muted">CPU <span className="text-data">{Math.round(system.cpu_pct || 0)}%</span></span>
      <span className="text-muted">RAM <span className="text-data">{Math.round(system.ram_pct || 0)}%</span></span>
      {system.temp_celsius != null && (
        <span className={cn('font-semibold', tempColor)}>{Math.round(system.temp_celsius)}°C</span>
      )}
      <span className={system.ollama_status === 'running' ? 'text-profit' : 'text-loss'}>
        {system.ollama_status === 'running' ? '● AI' : '○ AI'}
      </span>
    </div>
  );
}
