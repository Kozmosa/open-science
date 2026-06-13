from ainrf.db.connection import connect  # noqa: F401
from ainrf.db.migration import run_pending, registry  # noqa: F401
import ainrf.db.migrations  # noqa: F401 — register all migrations
