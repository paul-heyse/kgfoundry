"""Mixed precision training utilities for ColBERT models.

This module provides MixedPrecisionManager for handling automatic mixed
precision (AMP) training with gradient scaling and clipping.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import torch
from torch.optim import lr_scheduler

if TYPE_CHECKING:
    from torch.nn import Module

from warp.utils.utils import NullContextManager


class MixedPrecisionManager:
    """Manages mixed precision training with gradient scaling.

    Handles autocast context, gradient scaling, and gradient clipping
    for training with automatic mixed precision.

    Parameters
    ----------
    activated : bool
        Whether AMP is enabled.
    """

    def __init__(self, *, activated: bool) -> None:
        """Initialize MixedPrecisionManager.

        Parameters
        ----------
        activated : bool
            Whether AMP is enabled.
        """
        self.activated = activated

        if self.activated:
            self.scaler = torch.cuda.amp.GradScaler()

    def context(self) -> torch.cuda.amp.autocast | NullContextManager:
        """Get autocast context manager.

        Returns
        -------
        torch.cuda.amp.autocast | NullContextManager
            Autocast context if activated, NullContextManager otherwise.
        """
        return torch.cuda.amp.autocast() if self.activated else NullContextManager()

    def backward(self, loss: torch.Tensor) -> None:
        """Compute backward pass with optional gradient scaling.

        Parameters
        ----------
        loss : torch.Tensor
            Loss tensor to backpropagate.
        """
        if self.activated:
            self.scaler.scale(loss).backward()
        else:
            loss.backward()

    def step(
        self,
        colbert: Module,
        optimizer: torch.optim.Optimizer,
        scheduler: lr_scheduler.LRScheduler | None = None,
    ) -> None:
        """Perform optimizer step with gradient clipping and scaling.

        Unscales gradients, clips norms, steps optimizer, updates scaler,
        and optionally steps scheduler.

        Parameters
        ----------
        colbert : Module
            Model with parameters to clip.
        optimizer : torch.optim.Optimizer
            Optimizer to step.
        scheduler : lr_scheduler.LRScheduler | None
            Optional learning rate scheduler (default: None).
        """
        if self.activated:
            self.scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(colbert.parameters(), 2.0, error_if_nonfinite=False)

            self.scaler.step(optimizer)
            self.scaler.update()
        else:
            torch.nn.utils.clip_grad_norm_(colbert.parameters(), 2.0)
            optimizer.step()

        if scheduler is not None:
            scheduler.step()

        optimizer.zero_grad()
