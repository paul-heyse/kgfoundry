"""ONNX runtime backend for XTR models.

This module provides XTROnnxConfig and XTROnnxModel for running XTR models
using ONNX Runtime with optional quantization.
"""

import os
import pathlib
from dataclasses import dataclass
from enum import Enum, auto

import onnxruntime as ort
import torch
from onnxruntime import quantization as ort_quantization
from onnxruntime.quantization import QuantType, quantize_dynamic
from onnxruntime.transformers import optimizer as transformers_optimizer
from transformers import AutoTokenizer
from warp.modeling.xtr import QUERY_MAXLEN, XTRTokenizer, build_xtr_model


class XTROnnxQuantization(Enum):
    """ONNX quantization strategies.

    NONE : No quantization.
    PREPROCESS : Preprocessing only.
    DYN_QUANTIZED_QINT8 : Dynamic INT8 quantization.
    QUANTIZED_QATTENTION : Quantized attention.
    """

    NONE = auto()
    PREPROCESS = auto()
    DYN_QUANTIZED_QINT8 = auto()
    QUANTIZED_QATTENTION = auto()


@dataclass(frozen=True)
class XTROnnxConfig:
    """Configuration for ONNX XTR model.

    Attributes
    ----------
    batch_size : int
        Batch size (default: 1).
    opset_version : int
        ONNX opset version (default: 16).
    quantization : XTROnnxQuantization
        Quantization strategy (default: NONE).
    num_threads : int
        Number of threads (default: 1).
    """

    batch_size: int = 1
    opset_version: int = 16
    quantization: XTROnnxQuantization = XTROnnxQuantization.NONE

    num_threads: int = 1

    @property
    def base_name(self) -> str:
        """Get base model name.

        Returns
        -------
        str
            Base name with version and batch size.
        """
        return f"xtr.v={self.opset_version}.batch={self.batch_size}"

    @property
    def base_filename(self) -> str:
        """Get base filename.

        Returns
        -------
        str
            Base filename with .onnx extension.
        """
        return f"{self.base_name}.onnx"

    @property
    def filename(self) -> str:
        """Get full filename with quantization suffix if applicable.

        Returns
        -------
        str
            Model filename.
        """
        if self.quantization == XTROnnxQuantization.NONE:
            return self.base_filename
        return f"{self.base_name}.{self.quantization.name}.onnx"


class XTROnnxModel:
    """ONNX runtime model for XTR inference.

    Loads and runs XTR models using ONNX Runtime, converting PyTorch models
    to ONNX format and applying quantization if needed.

    Parameters
    ----------
    config : XTROnnxConfig
        Configuration for model loading and quantization.
    """

    def __init__(self, config: XTROnnxConfig) -> None:
        """Initialize XTROnnxModel with configuration.

        Parameters
        ----------
        config : XTROnnxConfig
            Configuration for model loading and quantization.
        """
        onnx_dir = os.environ["ONNX_MODEL_DIR"]
        XTROnnxModel._quantize_model_if_not_exists(onnx_dir, config)

        model_path = pathlib.Path(onnx_dir) / config.filename
        model_path.stat().st_size / (1024 * 1024)

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = config.num_threads
        sess_opts.inter_op_num_threads = config.num_threads
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL

        self.model = ort.InferenceSession(
            model_path,
            sess_opts,
        )

        self.tokenizer = XTRTokenizer(AutoTokenizer.from_pretrained("google/xtr-base-en"))

    @property
    def device(self) -> torch.device:
        """Get device where model runs.

        Returns
        -------
        torch.device
            CPU device (ONNX Runtime runs on CPU).
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
        return torch.from_numpy(
            self.model.run(
                ["Q"],
                {
                    "input_ids": input_ids.numpy(),
                    "attention_mask": attention_mask.numpy(),
                },
            )[0]
        )

    @staticmethod
    def _quantize_model_if_not_exists(root_dir: str, config: XTROnnxConfig) -> None:
        """Create and quantize ONNX model if it doesn't exist.

        Converts PyTorch XTR model to ONNX format and applies quantization
        strategy if specified.

        Parameters
        ----------
        root_dir : str
            Directory to save model.
        config : XTROnnxConfig
            Configuration specifying batch size, opset version, and quantization.

        Raises
        ------
        AssertionError
            If quantization strategy is invalid (should never occur).
        """
        base_model_path = pathlib.Path(root_dir) / config.base_filename
        if not base_model_path.exists():
            pathlib.Path(root_dir).mkdir(exist_ok=True, parents=True)
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
            with torch.no_grad():
                torch.onnx.export(
                    base_model,
                    args=(input_ids, {"attention_mask": attention_mask}),
                    f=str(base_model_path),
                    opset_version=config.opset_version,
                    do_constant_folding=True,
                    input_names=["input_ids", "attention_mask"],
                    output_names=["Q"],
                )

        if config.quantization == XTROnnxQuantization.NONE:
            return

        quantization = config.quantization

        config.quantization = XTROnnxQuantization.PREPROCESS
        preprocessed_model_path = pathlib.Path(root_dir) / config.filename
        config.quantization = quantization

        if not preprocessed_model_path.exists():
            ort_quantization.shape_inference.quant_pre_process(
                str(base_model_path),
                str(preprocessed_model_path),
                skip_symbolic_shape=False,
            )

        model_path = pathlib.Path(root_dir) / config.filename
        if (
            config.quantization == XTROnnxQuantization.PREPROCESS
            or pathlib.Path(model_path).exists()
        ):
            return

        if config.quantization == XTROnnxQuantization.DYN_QUANTIZED_QINT8:
            quantize_dynamic(preprocessed_model_path, model_path, weight_type=QuantType.QInt8)
            return

        if config.quantization == XTROnnxQuantization.QUANTIZED_QATTENTION:
            optimized_model = transformers_optimizer.optimize_model(
                preprocessed_model_path, "bert", num_heads=12, hidden_size=768
            )
            optimized_model.save_model_to_file(model_path)
            return

        raise AssertionError  # We should never reach this point.
