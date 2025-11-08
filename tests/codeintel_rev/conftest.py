"""Shared pytest fixtures for tests in tests/codeintel_rev."""

import sys
import types

sys.modules.setdefault("faiss", types.ModuleType("faiss"))

from codeintel_rev.tests.conftest import *  # noqa: F403,E402
