from lex.pilot import PILOT_MARKETS, pilot_limits


def get_context(context):
	context.title = "Complimentary Pilot Engagement"
	limits = pilot_limits()
	context.pilot_markets = [
		{"currency": currency, "market": market, "limit": limits.get(currency)}
		for currency, market in PILOT_MARKETS.items()
	]
	return context
