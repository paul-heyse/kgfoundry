"""TorchScript runtime backend for XTR models.

This module provides XTRTorchScriptConfig and XTRTorchScriptModel for running
XTR models using PyTorch's TorchScript JIT compilation.
"""

import os
import pathlib
from dataclasses import dataclass

import torch
from transformers import AutoTokenizer
from warp.modeling.xtr import QUERY_MAXLEN, XTRTokenizer, build_xtr_model


@dataclass(frozen=True)
class XTRTorchScriptConfig:
    """Configuration for TorchScript XTR model.

    Attributes
    ----------
    batch_size : int
        Batch size (default: 1).
    num_threads : int
        Number of threads (default: 1, must match torch.get_num_threads()).
    """

    batch_size: int = 1
    num_threads: int = 1

    @property
    def filename(self) -> str:
        """Get model filename.

        Returns
        -------
        str
            Filename "xtr-base-en-torchscript.pt".
        """
        return "xtr-base-en-torchscript.pt"


class XTRTorchScriptModel:
    """TorchScript runtime model for XTR inference.

    Loads and runs XTR models using TorchScript, converting PyTorch models
    to TorchScript format if needed.

    Parameters
    ----------
    config : XTRTorchScriptConfig
        Configuration for model loading.

    Raises
    ------
    ValueError
        If num_threads doesn't match torch.get_num_threads().
    """

    def __init__(self, config: XTRTorchScriptConfig) -> None:
        """Initialize XTRTorchScriptModel with configuration.

        Parameters
        ----------
        config : XTRTorchScriptConfig
            Configuration for model loading.

        Raises
        ------
        ValueError
            If num_threads doesn't match torch.get_num_threads().
        """
        torchscript_dir = os.environ["TORCHSCRIPT_MODEL_DIR"]
        XTRTorchScriptModel._create_model_if_not_exists(torchscript_dir, config)

        self.model = torch.jit.load(str(pathlib.Path(torchscript_dir) / config.filename))
        self.model.eval()

        self.tokenizer = XTRTokenizer(AutoTokenizer.from_pretrained("google/xtr-base-en"))

        if config.num_threads != torch.torch.get_num_threads():
            msg = (
                f"config.num_threads ({config.num_threads}) must equal "
                f"torch.get_num_threads() ({torch.torch.get_num_threads()})"
            )
            raise ValueError(msg)

    @staticmethod
    def _create_model_if_not_exists(root_dir: str, config: XTRTorchScriptConfig) -> None:
        """Create TorchScript model if it doesn't exist.

        Converts PyTorch XTR model to TorchScript format and saves to disk.

        Parameters
        ----------
        root_dir : str
            Directory to save model.
        config : XTRTorchScriptConfig
            Configuration specifying batch size.
        """
        model_path = pathlib.Path(root_dir) / config.filename
        if not model_path.exists():
            base_model = build_xtr_model()

            device = torch.device("cpu")
            input_dim = (config.batch_size, QUERY_MAXLEN)
            attention_mask = torch.randint(low=1, high=1000, size=input_dim, dtype=torch.int64).to(
                device
            )
            input_ids = torch.randint(low=1, high=1000, size=input_dim, dtype=torch.int64).to(
                device
            )
            base_model.eval()

            traced_model = torch.jit.trace(base_model, (input_ids, attention_mask))
            traced_model.save(model_path)

    @property
    def device(self) -> torch.device:
        """Get device where model runs.

        Returns
        -------
        torch.device
            CPU device.
        """
        return torch.device("cpu")

    def __call__(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        """Run inference on input tensors.

        Parameters
        ----------
        input_ids : torch.Tensor
            Token IDs (batch_size x seq_len).
        attention_mask : torch.Tensor
            Attention mask (batch_size x seq_len).

        Returns
        -------
        torch.Tensor
            Model output embeddings.
        """
        with torch.inference_mode():
            return self.model(input_ids, attention_mask)
