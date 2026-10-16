"""Vercel entry point for the same-origin Crossplay API."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crossplay_server import Handler


class handler(Handler):
    """Vercel invokes this request handler for each API call."""

