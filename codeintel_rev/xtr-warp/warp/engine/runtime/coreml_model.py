"""CoreML runtime backend for XTR models.

This module provides XTRCoreMLConfig and XTRCoreMLModel for running
XTR models using Apple's CoreML framework.
"""

import os
from dataclasses import dataclass
from pathlib import Path

import coremltools as ct
import numpy as np
import torch
from transformers import AutoTokenizer
from warp.modeling.xtr import QUERY_MAXLEN, XTRTokenizer, build_xtr_model


@dataclass(frozen=True)
class XTRCoreMLConfig:
    """Configuration for CoreML XTR model.

    Attributes
    ----------
    batch_size : int
        Batch size (default: 1).
    num_threads : int
        Number of threads (default: 1, currently ignored).
    """

    batch_size: int = 1

    # NOTE Currently, num_threads value is ignored. It is just keeped for consistency.
    num_threads: int = 1

    @property
    def base_name(self) -> str:
        """Get base model name.

        Returns
        -------
        str
            Base name "xtr".
        """
        return "xtr"

    @property
    def base_filename(self) -> str:
        """Get base filename.

        Returns
        -------
        str
            Base filename "xtr.mlpackage".
        """
        return f"{self.base_name}.mlpackage"

    @property
    def filename(self) -> str:
        """Get full filename.

        Returns
        -------
        str
            Model filename.
        """
        return self.base_filename


class XTRCoreMLModel:
    """CoreML runtime model for XTR inference.

    Loads and runs XTR models using CoreML, converting PyTorch models
    to CoreML format if needed.

    Parameters
    ----------
    config : XTRCoreMLConfig
        Configuration for model loading.
    """

    def __init__(self, config: XTRCoreMLConfig) -> None:
        """Initialize XTRCoreMLModel with configuration.

        Parameters
        ----------
        config : XTRCoreMLConfig
            Configuration for model loading.
        """
        coreml_dir = os.environ["COREML_MODEL_DIR"]
        XTRCoreMLModel._create_model_if_not_exists(coreml_dir, config)

        model_path = Path(coreml_dir) / config.filename

        root_directory = Path(model_path)
        sum(f.stat().st_size for f in root_directory.glob("**/*") if f.is_file()) / (
            1024 * 1024
        )

        self.model = ct.models.MLModel(model_path)

        self.tokenizer = XTRTokenizer(
            AutoTokenizer.from_pretrained("google/xtr-base-en")
        )

    @property
    def device(self) -> torch.device:
        """Get device where model runs.

        Returns
        -------
        torch.device
            CPU device (CoreML runs on CPU).
        """
        return torch.device("cpu")

    def __call__(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
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
        output = self.model.predict(
            {
                "input_ids": input_ids.numpy().astype(np.int32),
                "attention_mask": attention_mask.numpy().astype(np.int32),
            }
        )
        return torch.from_numpy(next(iter(output.values())))

    @staticmethod
    def _create_model_if_not_exists(root_dir: str, config: XTRCoreMLConfig) -> None:
        """Create CoreML model if it doesn't exist.

        Converts PyTorch XTR model to CoreML format and saves to disk.

        Parameters
        ----------
        root_dir : str
            Directory to save model.
        config : XTRCoreMLConfig
            Configuration specifying batch size.
        """
        base_model_path = Path(root_dir) / config.base_filename
        if not Path(base_model_path).exists():
            Path(root_dir).mkdir(exist_ok=True, parents=True)

            base_model = build_xtr_model()
            base_model.eval()

            input_dim = (config.batch_size, QUERY_MAXLEN)
            device = torch.device("cpu")
            input_ids = torch.randint(
                low=1, high=1000, size=input_dim, dtype=torch.int32
            ).to(device)
            attention_mask = torch.randint(
                low=0, high=1, size=input_dim, dtype=torch.int32
            ).to(device)

            traced_model = torch.jit.trace(base_model, (input_ids, attention_mask))
            traced_model(input_ids, attention_mask)

            ct_input_ids_input = ct.TensorType(
                shape=ct.Shape(shape=(1, 32)), dtype=np.int32
            )
            ct_attention_mask_input = ct.TensorType(
                shape=ct.Shape(shape=(1, 32)), dtype=np.int32
            )

            ct_model = ct.convert(
                traced_model,
                convert_to="mlprogram",
                inputs=[ct_input_ids_input, ct_attention_mask_input],
                compute_precision=ct.precision.FLOAT32,
            )

            ct_model.save(base_model_path)
