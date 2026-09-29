"""Library that uses try/except for a missing package."""

try:
    import nonexistent_pkg_xyz

    HAS_PKG = True
except ModuleNotFoundError:
    HAS_PKG = False
