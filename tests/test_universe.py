from market_pulse.universe.loaders import load_sp500


def test_load_sp500_returns_non_empty():
    tickers = load_sp500()
    assert len(tickers) >= 20
    assert "AAPL" in tickers


def test_load_sp500_returns_unique_upper_case():
    tickers = load_sp500()
    assert len(set(tickers)) == len(tickers)
    assert all(t == t.upper() for t in tickers)
