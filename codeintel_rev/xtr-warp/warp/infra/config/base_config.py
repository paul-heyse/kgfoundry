"""Base configuration class with loading and saving utilities.

This module provides BaseConfig, a frozen dataclass for managing configuration
with methods for loading from checkpoints, indices, and deprecated formats.
"""

from __future__ import annotations

import contextlib
import dataclasses
import pathlib
from dataclasses import dataclass

import ujson
from huggingface_hub import hf_hub_download
from utility.utils.save_metadata import get_metadata_only
from warp.infra.config.core_config import CoreConfig
from warp.utils.utils import torch_load_dnn


@dataclass(frozen=True)
class BaseConfig(CoreConfig):
    """Base configuration class with loading and saving capabilities.

    Extends CoreConfig with methods for loading from checkpoints, indices,
    and deprecated argument formats. Supports saving to JSON metadata files.

    Attributes
    ----------
    Inherits all attributes from CoreConfig.
    """

    @classmethod
    def from_existing(cls, *sources: CoreConfig | None) -> BaseConfig:
        """Create config by merging values from existing configs.

        Merges assigned attributes from multiple source configs, with later
        sources overriding earlier ones.

        Parameters
        ----------
        *sources : CoreConfig | None
            Source configs to merge (None values are skipped).

        Returns
        -------
        BaseConfig
            New config instance with merged attributes.
        """
        kw_args = {}

        for source in sources:
            if source is None:
                continue

            local_kw_args = dataclasses.asdict(source)
            local_kw_args = {k: local_kw_args[k] for k in source.assigned}
            kw_args = {**kw_args, **local_kw_args}

        return cls(**kw_args)

    @classmethod
    def from_deprecated_args(
        cls, args: dict[str, object]
    ) -> tuple[BaseConfig, set[str]]:
        """Create config from deprecated argument dictionary.

        Loads config from old-style argument dict, ignoring unrecognized keys.

        Parameters
        ----------
        args : dict[str, object]
            Deprecated argument dictionary.

        Returns
        -------
        tuple[BaseConfig, set[str]]
            Config instance and set of ignored unrecognized keys.
        """
        obj = cls()
        ignored = obj.configure(ignore_unrecognized=True, **args)

        return obj, ignored

    @classmethod
    def from_path(cls, name: str | pathlib.Path) -> tuple[BaseConfig, set[str]]:
        """Load config from JSON file path.

        Reads JSON config file, handling both direct config and nested
        "config" key formats.

        Parameters
        ----------
        name : str | pathlib.Path
            Path to JSON config file.

        Returns
        -------
        tuple[BaseConfig, set[str]]
            Config instance and set of ignored unrecognized keys.
        """
        with pathlib.Path(name).open(encoding="utf-8") as f:
            args = ujson.load(f)

            if "config" in args:
                args = args["config"]

        return cls.from_deprecated_args(
            args
        )  # the new, non-deprecated version functions the same at this level.

    @classmethod
    def load_from_checkpoint(cls, checkpoint_path: str) -> BaseConfig | None:
        """Load config from checkpoint directory or HuggingFace model.

        Supports both .dnn checkpoint files and HuggingFace model repositories.
        Returns None if checkpoint_path is a model name without config.

        Parameters
        ----------
        checkpoint_path : str
            Path to checkpoint directory, .dnn file, or HuggingFace model ID.

        Returns
        -------
        BaseConfig | None
            Loaded config instance, or None if config not found.
        """
        if checkpoint_path.endswith(".dnn"):
            dnn = torch_load_dnn(checkpoint_path)
            config, _ = cls.from_deprecated_args(dnn.get("arguments", {}))

            # NOTE: Decide if the line below will have any unintended
            # consequences. We don't want to overwrite those!
            config.set("checkpoint", checkpoint_path)

            return config

        with contextlib.suppress(Exception):
            checkpoint_path = hf_hub_download(
                repo_id=checkpoint_path, filename="artifact.metadata"
            ).split("artifact")[0]
        loaded_config_path = pathlib.Path(checkpoint_path) / "artifact.metadata"
        if loaded_config_path.exists():
            loaded_config, _ = cls.from_path(loaded_config_path)
            loaded_config.set("checkpoint", checkpoint_path)

            return loaded_config

        return (
            None  # can happen if checkpoint_path is something like 'bert-base-uncased'
        )

    @classmethod
    def load_from_index(cls, index_path: str | pathlib.Path) -> BaseConfig:
        """Load config from index directory metadata.

        Attempts to load from metadata.json, falling back to plan.json
        if metadata.json is not found.

        Parameters
        ----------
        index_path : str | pathlib.Path
            Path to index directory.

        Returns
        -------
        BaseConfig
            Loaded config instance.

        Raises
        ------
        FileNotFoundError
            If neither metadata.json nor plan.json exists.
        """
        # NOTE: We should start here with initial_config = ColBERTConfig(
        # config, Run().config). This should allow us to say
        # initial_config.index_root. Then, below, set config = Config(..., initial_c)

        # CONSIDER: No more plan/metadata.json. Only metadata.json to avoid
        # weird issues when loading an index.

        index_path_obj = pathlib.Path(index_path)
        try:
            metadata_path = index_path_obj / "metadata.json"
            loaded_config, _ = cls.from_path(str(metadata_path))
        except FileNotFoundError:
            metadata_path = index_path_obj / "plan.json"
            try:
                loaded_config, _ = cls.from_path(str(metadata_path))
            except FileNotFoundError as e:
                msg = f"Neither metadata.json nor plan.json found in {index_path}"
                raise FileNotFoundError(msg) from e

        return loaded_config

    def save(self, path: str | pathlib.Path, *, overwrite: bool = False) -> None:
        """Save config to JSON file.

        Exports config to JSON format with metadata and version information.

        Parameters
        ----------
        path : str | pathlib.Path
            Path to output JSON file.
        overwrite : bool
            Whether to overwrite existing file (default: False).

        Raises
        ------
        FileExistsError
            If path exists and overwrite=False.
        """
        if not overwrite and pathlib.Path(path).exists():
            msg = f"Path already exists and overwrite=False: {path}"
            raise FileExistsError(msg)

        with pathlib.Path(path).open("w", encoding="utf-8") as f:
            args = self.export()  # dict(self.__config)
            args["meta"] = get_metadata_only()
            args["meta"]["version"] = "colbert-v0.4"
            # NOTE: Add git_status details.. It can't be too large! It should
            # be a path that Runs() saves on exit, maybe!

            f.write(ujson.dumps(args, indent=4) + "\n")

    def save_for_checkpoint(self, checkpoint_path: str | pathlib.Path) -> None:
        """Save config as checkpoint metadata file.

        Saves config to artifact.metadata in checkpoint directory,
        overwriting if it exists.

        Parameters
        ----------
        checkpoint_path : str | pathlib.Path
            Path to checkpoint directory.

        Raises
        ------
        ValueError
            If checkpoint_path ends with .dnn (deprecated format).
        """
        if checkpoint_path.endswith(".dnn"):
            msg = f"{checkpoint_path}: We reserve *.dnn names for the deprecated checkpoint format."
            raise ValueError(msg)

        output_config_path = pathlib.Path(checkpoint_path) / "artifact.metadata"
        self.save(str(output_config_path), overwrite=True)
