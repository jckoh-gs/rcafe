"""Errors the application layer raises for conditions callers should handle."""


class WeatherUnavailableError(LookupError):
    """No observation for this location (outside the covered stations, or KMA unreachable)."""


class NotReadyError(LookupError):
    """Required data has not been prepared yet (cafe tastes, weather scenarios)."""
