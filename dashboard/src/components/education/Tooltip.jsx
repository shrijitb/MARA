import { useState, useRef, useEffect } from 'react';
import { cn } from '../../utils/cn.js';
import { GLOSSARY } from './glossary.js';

export default function Tooltip({ term, label, children }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  const def = GLOSSARY[term] || children || 'No definition available.';

  useEffect(() => {
    if (!open) return;
    const hide = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', hide);
    return () => document.removeEventListener('mousedown', hide);
  }, [open]);

  return (
    <span ref={ref} className="relative inline-flex items-center">
      <button
        onClick={() => setOpen(v => !v)}
        aria-label={`What is ${label || term}?`}
        className="inline-flex items-center gap-0.5 text-[10px] text-muted/70 hover:text-muted transition-colors px-1 py-0.5 rounded cursor-pointer select-none"
      >
        <span className="text-xs">ⓘ</span>
        {label && <span>{label}</span>}
      </button>

      {open && (
        <div
          className={cn(
            'absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-56 z-50',
            'bg-modal border border-line rounded-xl p-3 shadow-2xl anim-fade-in',
          )}
        >
          {label && (
            <p className="text-[10px] font-bold uppercase tracking-widest text-warn mb-1.5">{label}</p>
          )}
          <p className="text-xs text-cream leading-relaxed">{def}</p>
          {/* Arrow */}
          <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-line" />
        </div>
      )}
    </span>
  );
}
