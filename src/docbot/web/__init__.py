"""Web server and search functionality."""

from .server import create_app
from .search import SearchIndex

__all__ = ["create_app", "SearchIndex"]
