# Auto-generated overlay for runtime.__init__. Edit as needed for precise types.
from typing import Any

from codeintel_rev.runtime.cells import NullRuntimeCellObserver as NullRuntimeCellObserver
from codeintel_rev.runtime.cells import RuntimeCell as RuntimeCell
from codeintel_rev.runtime.cells import RuntimeCellCloseResult as RuntimeCellCloseResult
from codeintel_rev.runtime.cells import RuntimeCellInitContext as RuntimeCellInitContext
from codeintel_rev.runtime.cells import RuntimeCellInitResult as RuntimeCellInitResult
from codeintel_rev.runtime.cells import RuntimeCellObserver as RuntimeCellObserver
from codeintel_rev.runtime.factory_adjustment import (
    DefaultFactoryAdjuster as DefaultFactoryAdjuster,
)
from codeintel_rev.runtime.factory_adjustment import FactoryAdjuster as FactoryAdjuster
from codeintel_rev.runtime.factory_adjustment import NoopFactoryAdjuster as NoopFactoryAdjuster

__all__ = ['DefaultFactoryAdjuster', 'FactoryAdjuster', 'NoopFactoryAdjuster', 'NullRuntimeCellObserver', 'RuntimeCell', 'RuntimeCellCloseResult', 'RuntimeCellInitContext', 'RuntimeCellInitResult', 'RuntimeCellObserver']

def __getattr__(name: str) -> Any: ...
