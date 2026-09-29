"""Library with an optional dependency (alog behind try/except) and a
required dependency (yaml imported directly)."""

import yaml

try:
    import alog
except ImportError:
    pass
