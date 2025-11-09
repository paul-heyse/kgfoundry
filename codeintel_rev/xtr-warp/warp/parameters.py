"""Global parameters for WARP models.

This module provides global device configuration and other shared parameters.
"""

import torch

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
