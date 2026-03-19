"""Eye of Sauron — security-pattern scanner."""

from importlib import metadata

try:
    __version__ = metadata.version("eye-of-sauron")
except metadata.PackageNotFoundError:
    # Running from a source tree without ``pip install`` (see pyproject ``version`` for releases).
    __version__ = "0.0.0+local"
