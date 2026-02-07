"""Web server and search functionality."""

from .server import start_server
from .search import SearchIndex

__all__ = ["start_server", "SearchIndex"]
