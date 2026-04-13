import { useState } from 'react';
import { cn } from '../../utils/cn.js';

const SOURCES = [
  { icon: '📰', label: 'FRED', desc: 'Federal Reserve economic data — interest rates, inflation', link: 'https://fred.stlouisfed.org/docs/api/api_key.html', keys: [{ id: 'FRED_API_KEY', placeholder: 'FRED API key', type: 'text' }] },
  { icon: '🛰', label: 'NASA FIRMS', desc: 'Satellite fire detection — supply chain disruption alerts', link: 'https://firms.modaps.eosdis.nasa.gov/api/area/', keys: [{ id: 'NASA_FIRMS_API_KEY', placeholder: 'NASA FIRMS key', type: 'text' }] },
  { icon: '⚓', label: 'AISstream', desc: 'Global ship tracking — shipping lane disruptions', link: 'https://aisstream.io', keys: [{ id: 'AISSTREAM_API_KEY', placeholder: 'AISstream key', type: 'text' }] },
  { icon: '🌍', label: 'UCDP', desc: 'Uppsala Conflict Data — armed conflict events worldwide', link: 'https://ucdp.uu.se/apidocs/', keys: [{ id: 'UCDP_API_TOKEN', placeholder: 'UCDP token', type: 'text' }] },
  { icon: '🔮', label: 'Kalshi', desc: 'Regulated US prediction markets — trade on real outcomes', link: 'https://kalshi.com', keys: [{ id: 'KALSHI_EMAIL', placeholder: 'Account email', type: 'email' }, { id: 'KALSHI_PASSWORD', placeholder: 'Account password', type: 'password' }] },
];

export default function DataStep({ onNext, onBack, onSave }) {
  const [vals, setVals] = useState({});
  const [saving, setSaving] = useState(false);
  const set = (k, v) => setVals(prev => ({ ...prev, [k]: v }));

  async function save() {
    setSaving(true);
    const creds = Object.fromEntries(Object.entries(vals).filter(([, v]) => v?.trim()));
    if (Object.keys(creds).length) await onSave(creds);
    setSaving(false);
    onNext();
  }

  return (
    <div className="anim-fade-in max-w-md mx-auto">
      <div className="bg-card border border-edge rounded-2xl p-6 mb-4">
        <p className="text-[10px] font-bold uppercase tracking-widest text-muted mb-1">Step 4 of 6</p>
        <div className="flex items-center gap-2 mb-2">
          <h2 className="text-xl font-bold text-cream">Data Sources</h2>
          <span className="text-[9px] font-bold uppercase tracking-wider bg-edge text-muted px-2 py-0.5 rounded-full">All optional</span>
        </div>
        <p className="text-sm text-muted leading-relaxed mb-5">
          Arka works without these — free fallbacks cover the basics. Adding them improves the intelligence layer.
        </p>

        <div className="space-y-2.5">
          {SOURCES.map(src => (
            <div key={src.label} className="bg-black/50 border border-edge rounded-xl p-3.5">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="text-base">{src.icon}</span>
                  <span className="text-xs font-bold text-cream">{src.label}</span>
                </div>
                <a href={src.link} target="_blank" rel="noopener noreferrer"
                  className="text-[10px] text-warn/80 hover:text-warn transition-colors">
                  Get free key →
                </a>
              </div>
              <p className="text-[11px] text-muted mb-2.5">{src.desc}</p>
              <div className="space-y-1.5">
                {src.keys.map(field => (
                  <input
                    key={field.id}
                    type={field.type}
                    placeholder={field.placeholder}
                    value={vals[field.id] || ''}
                    onChange={e => set(field.id, e.target.value)}
                    className="w-full px-3 py-2 bg-card border border-edge rounded-lg text-cream text-xs font-jetbrains outline-none focus:border-warn/40 transition-colors placeholder:text-muted/30"
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-2.5">
        <button onClick={onBack} className={ghost}>← Back</button>
        <button onClick={onNext} className={cn(ghost, 'text-muted/60 hover:text-muted')}>Skip all</button>
        <button onClick={save} disabled={saving} className={cn(primary, saving && 'opacity-70')}>
          {saving ? 'Saving...' : 'Save & Next →'}
        </button>
      </div>
    </div>
  );
}

const primary = 'flex-1 py-3 bg-warn text-black font-bold text-sm rounded-xl hover:bg-warn/90 active:scale-[0.98] transition-all';
const ghost   = 'px-4 py-3 bg-transparent border border-edge text-muted text-sm rounded-xl hover:border-line hover:text-cream transition-all';
