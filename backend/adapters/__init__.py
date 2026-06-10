"""Boundary adapters between the analysis engine and external persistence.

Only modules in this package may import from the top-level ``storage`` package.
Pipeline code must depend on these adapters (or remain pure analysis) instead of
calling ``storage`` directly.
"""
