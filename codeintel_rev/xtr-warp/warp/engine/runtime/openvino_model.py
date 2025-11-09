"""OpenVINO runtime backend for XTR models.

This module provides XTROpenVinoConfig and XTROpenVinoModel for running
XTR models using Intel's OpenVINO framework.
"""

import os
import pathlib
from dataclasses import dataclass

import openvino.runtime as ov
import torch
from huggingface_hub import hf_hub_download
from optimum.intel.openvino import OVModelForSeq2SeqLM
from transformers import AutoTokenizer
from warp.modeling.xtr import XTRLinear, XTRTokenizer

OPENVINO_MODEL_FILENAME = "openvino_encoder_model.xml"


@dataclass(frozen=True)
class XTROpenVinoConfig:
    """Configuration for OpenVINO XTR model.

    Attributes
    ----------
    batch_size : int
        Batch size (must be 1, default: 1).
    num_threads : int
        Number of threads (default: 1).
    """

    batch_size: int = 1
    num_threads: int = 1


class XTROpenVinoModel:
    """OpenVINO runtime model for XTR inference.

    Loads and runs XTR models using OpenVINO, converting HuggingFace models
    to OpenVINO format if needed.

    Parameters
    ----------
    config : XTROpenVinoConfig
        Configuration for model loading (batch_size must be 1).

    Raises
    ------
    ValueError
        If batch_size != 1.
    """

    def __init__(self, config: XTROpenVinoConfig) -> None:
        """Initialize XTROpenVinoModel with configuration.

        Parameters
        ----------
        config : XTROpenVinoConfig
            Configuration for model loading (batch_size must be 1).

        Raises
        ------
        ValueError
            If batch_size != 1.
        """
        if config.batch_size != 1:
            msg = f"config.batch_size must be 1, got {config.batch_size}"
            raise ValueError(msg)

        openvino_dir = os.environ["OPENVINO_MODEL_DIR"]
        XTROpenVinoModel._quantize_model_if_not_exists(openvino_dir, config)

        self.tokenizer = XTRTokenizer(AutoTokenizer.from_pretrained("google/xtr-base-en"))
        self.linear = XTRLinear().to(self.device)
        self.linear.load_state_dict(torch.load(XTROpenVinoModel._hf_download_to_dense()))

        core = ov.Core()
        model_path = pathlib.Path(openvino_dir) / OPENVINO_MODEL_FILENAME
        model = core.read_model(str(model_path))
        ov_config = {
            "NUM_STREAMS": 1,
            "INFERENCE_NUM_THREADS": config.num_threads,
        }
        compiled_model = core.compile_model(model, "CPU", ov_config)
        self.infer_request = compiled_model.create_infer_request()

    @staticmethod
    def _hf_download_to_dense() -> str:
        """Download dense projection weights from HuggingFace.

        Returns
        -------
        str
            Path to downloaded pytorch_model.bin file.
        """
        return hf_hub_download(repo_id="google/xtr-base-en", filename="2_Dense/pytorch_model.bin")

    @staticmethod
    def _quantize_model_if_not_exists(root_dir: str, config: XTROpenVinoConfig) -> None:
        """Create OpenVINO model if it doesn't exist.

        Converts HuggingFace XTR model to OpenVINO format and saves to disk.

        Parameters
        ----------
        root_dir : str
            Directory to save model.
        config : XTROpenVinoConfig
            Configuration (unused, kept for consistency).
        """
        model_path = pathlib.Path(root_dir) / OPENVINO_MODEL_FILENAME
        if not model_path.exists():
            hf_model = OVModelForSeq2SeqLM.from_pretrained(
                "google/xtr-base-en", export=True, use_cache=False
            )
            hf_model.save_pretrained(root_dir)
            XTROpenVinoModel._hf_download_to_dense()

    @property
    def device(self) -> torch.device:
        """Get device where model runs.

        Returns
        -------
        torch.device
            CPU device (OpenVINO runs on CPU).
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
            Normalized embeddings (batch_size x seq_len x dim).
        """
        mask = (input_ids != 0).unsqueeze(2).float()
        self.infer_request.set_input_tensor(0, ov.Tensor(input_ids.numpy()))
        self.infer_request.set_input_tensor(1, ov.Tensor(attention_mask.numpy()))
        q = self.linear(torch.from_numpy(self.infer_request.infer()[0])) * mask
        return torch.nn.functional.normalize(q, dim=2)
