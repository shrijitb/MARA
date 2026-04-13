const POINTS = [
  { icon: '🤖', text: 'Arka is an AI that watches markets and manages trades for you' },
  { icon: '📊', text: 'Multiple strategies + live intelligence data work together automatically' },
  { icon: '🔒', text: 'Your money stays on the exchange — Arka only sends trade instructions' },
  { icon: '📄', text: 'Everything starts in paper mode. Zero risk until you decide to go live.' },
];

export default function WelcomeStep({ onNext }) {
  return (
    <div className="anim-fade-in max-w-md mx-auto text-center">
      {/* Logo */}
      <div className="mb-10">
        <div className="text-6xl mb-4 anim-sun inline-block select-none">⚡</div>
        <h1 className="font-jetbrains text-4xl font-bold tracking-[0.25em] gradient-text">ARKA</h1>
        <p className="text-muted text-sm mt-2 tracking-widest">Agentic Risk-Kinetic Allocator</p>
      </div>

      {/* Feature points */}
      <div className="bg-card border border-edge rounded-2xl p-6 mb-8 text-left space-y-4">
        {POINTS.map(({ icon, text }, i) => (
          <div key={i} className="flex items-start gap-3.5">
            <span className="text-xl shrink-0 mt-0.5">{icon}</span>
            <p className="text-sm text-cream/85 leading-relaxed">{text}</p>
          </div>
        ))}
      </div>

      <button
        onClick={onNext}
        className="w-full py-3.5 bg-warn text-black font-bold text-sm rounded-xl hover:bg-warn/90 active:scale-[0.98] transition-all duration-150 tracking-wide"
      >
        Let's set up →
      </button>
    </div>
  );
}
