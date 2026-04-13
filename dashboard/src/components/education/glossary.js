export const GLOSSARY = {
  regime:
    "The overall mood of the market. Like weather for stocks — sunny means things are calm and going up.",
  sharpe:
    "A score for how good returns are compared to the risk taken. Above 1.0 is good, above 2.0 is excellent.",
  drawdown:
    "How far your portfolio has dropped from its highest point. Lower is better. 5% means you're 5% below your peak.",
  macd:
    "A signal that shows when a price trend is getting stronger or weaker. Arka uses this to decide when to buy or sell.",
  pbo:
    "Probability of Backtest Overfitting — a test that checks if a strategy's past success was real skill or just luck. Below 0.40 means real.",
  dsr:
    "Deflated Sharpe Ratio — adjusts performance scores to account for testing many strategies. Above 0.95 is trustworthy.",
  funding_rate:
    "A fee that crypto traders pay each other every 8 hours. Arka can earn this fee by being on the right side of the market.",
  adx:
    "Average Directional Index — a number showing how strong a price trend is. Above 25 means strong trend, below 20 means sideways market.",
  ofi:
    "Order Flow Imbalance — measures whether more people are buying or selling right now at a given price.",
  stop_loss:
    "An automatic safety net. If the price drops this much from where Arka bought, it automatically sells to limit your losses.",
  paper_trading:
    "Practice mode using fake money. Everything works exactly like real trading, but no real money is at risk.",
  circuit_breaker:
    "An emergency override. If something extreme happens in the market, Arka automatically becomes extra cautious.",
  domain:
    "A category of markets Arka tracks. Examples: 'crypto' for Bitcoin/Ethereum, 'us_equities' for stocks, 'prediction markets' for event betting.",
  volatility:
    "How much prices are bouncing around. High volatility means bigger swings up and down.",
  basis:
    "The price difference between buying something now (spot) vs. agreeing to buy it later (futures). Arka can profit from this gap.",
  insider_buying:
    "When company executives buy their own company's stock with personal money. This is usually a positive sign they believe in the company.",
  advisory_only:
    "This worker gives advice and analysis but doesn't place actual trades. Its recommendations inform Arka's decisions.",
  eight_k:
    "An 8-K is a special filing companies must submit when something important happens — like a merger, executive change, or major financial event.",
  risk_check:
    "A safety review of any recommended trade before Arka acts on it. Checks drawdown limits, position sizes, and risk exposure.",
  regime_probability:
    "How confident Arka is about each possible market mood, shown as percentages. They always add up to 100%.",
  allocation:
    "How much money Arka has assigned to each worker to manage. Changes based on the market regime.",
  sparkline:
    "A tiny chart showing recent price movement at a glance — rising means price went up, falling means it went down.",
  hmm:
    "Hidden Markov Model — the math Arka uses to classify market regimes. It looks at patterns in multiple data sources simultaneously.",
  conflict_score:
    "A 0–100 score measuring global conflict intensity using satellite data, news feeds, and market proxies. Above 25 triggers WAR_PREMIUM regime.",
  oos_sharpe:
    "Out-of-sample Sharpe — how well a strategy performed on data it was never trained on. This is the honest test of whether it really works.",
};
