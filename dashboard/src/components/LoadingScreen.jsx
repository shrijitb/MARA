export default function LoadingScreen() {
  return (
    <div className="h-screen bg-black flex flex-col items-center justify-center gap-6">
      {/* Animated glyph */}
      <div className="relative">
        <div className="text-6xl anim-sun select-none">⚡</div>
        <div className="absolute inset-0 flex items-center justify-center">
          <div
            className="w-20 h-20 rounded-full border border-warn/20"
            style={{ animation: 'spin 3s linear infinite' }}
          />
        </div>
      </div>

      {/* Wordmark */}
      <div className="text-center">
        <p className="font-jetbrains text-3xl font-bold tracking-[0.3em] gradient-text">ARCA</p>
        <p className="text-muted text-xs mt-1 tracking-widest uppercase">Agentic Risk-Kinetic Allocator</p>
      </div>

      {/* Loading bar */}
      <div className="w-48 h-px bg-edge rounded-full overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{
            width: '45%',
            background: 'linear-gradient(90deg, transparent, #FFD740, transparent)',
            backgroundSize: '200% 100%',
            animation: 'shimmer 1.5s linear infinite',
          }}
        />
      </div>

      <p className="text-muted text-xs flex items-center gap-2">
        <span className="anim-spin inline-block">◌</span>
        Connecting to system...
      </p>
    </div>
  );
}
