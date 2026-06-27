"""polymarket-microstructure-lab.

Read-only research & backtesting lab for Polymarket crypto Up/Down markets.

HARD CONSTRAINTS (enforced by construction, not just convention):
  * No live trading, no order placement, no authenticated CLOB trading endpoints.
  * No wallet connection, no private keys.
  * No Telegram/Discord/copy-trading/signal-selling.
  * No scraping of X/Twitter or Telegram.
  * Only public / read-only APIs.
"""

__version__ = "0.1.0"
