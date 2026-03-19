"""Allow ``python -m eye_of_sauron``."""

from .checker import main

if __name__ == "__main__":
    raise SystemExit(main())
