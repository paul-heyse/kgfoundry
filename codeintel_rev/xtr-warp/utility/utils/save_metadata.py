"""Metadata collection and persistence utilities for experiment provenance.

This module provides functions to collect system and Git metadata, format it
as JSON, and save it to files for experiment tracking and reproducibility.
"""

from __future__ import annotations

import copy
import pathlib
import socket
import sys
import time
from pathlib import Path

import git
import ujson
from warp.utils.utils import Dotdict


def get_metadata_only() -> dict[str, object]:
    """Collect system and Git metadata without command-line arguments.

    Gathers hostname, Git branch/hash/commit datetime, current datetime,
    and command-line arguments. Handles cases where Git repository is not
    available gracefully.

    Returns
    -------
    Any
        DotDict object containing metadata fields:
        - hostname: System hostname
        - git_branch: Active Git branch name (if available)
        - git_hash: Git commit hash (if available)
        - git_commit_datetime: Commit datetime string (if available)
        - current_datetime: Current system datetime
        - cmd: Command-line invocation string
    """
    args = Dotdict()

    args.hostname = socket.gethostname()
    try:
        args.git_branch = git.Repo(search_parent_directories=True).active_branch.name
        args.git_hash = git.Repo(search_parent_directories=True).head.object.hexsha
        args.git_commit_datetime = str(
            git.Repo(search_parent_directories=True).head.object.committed_datetime
        )
    except git.exc.InvalidGitRepositoryError:
        pass
    args.current_datetime = time.strftime("%b %d, %Y ; %l:%M%p %Z (%z)")
    args.cmd = " ".join(sys.argv)

    return args


def get_metadata(args: object) -> dict[str, object]:
    """Collect system, Git, and argument metadata for experiment tracking.

    Extends the provided arguments dictionary with system metadata including
    hostname, Git information, timestamps, and command-line arguments.
    Deep copies input arguments to avoid mutation.

    Parameters
    ----------
    args : Any
        Arguments object (typically a dotdict) to extend with metadata.
        May contain an input_arguments attribute that will be converted
        to a dictionary.

    Returns
    -------
    dict[str, Any]
        Dictionary containing all metadata fields:
        - All fields from input args
        - hostname: System hostname
        - git_branch: Active Git branch name
        - git_hash: Git commit hash
        - git_commit_datetime: Commit datetime string
        - current_datetime: Current system datetime
        - cmd: Command-line invocation string
        - input_arguments: Converted input arguments dict (if available)
    """
    args = copy.deepcopy(args)

    args.hostname = socket.gethostname()
    args.git_branch = git.Repo(search_parent_directories=True).active_branch.name
    args.git_hash = git.Repo(search_parent_directories=True).head.object.hexsha
    args.git_commit_datetime = str(
        git.Repo(search_parent_directories=True).head.object.committed_datetime
    )
    args.current_datetime = time.strftime("%b %d, %Y ; %l:%M%p %Z (%z)")
    args.cmd = " ".join(sys.argv)

    try:
        args.input_arguments = copy.deepcopy(args.input_arguments.__dict__)
    except (TypeError, RecursionError):
        args.input_arguments = None

    return dict(args.__dict__)


# NOTE: No reason for deepcopy. But: (a) Call provenance() on objects that can,
# (b) Only save simple, small objects. No massive lists or models or weird stuff!
# With that, I think we don't even need (necessarily) to restrict things to input_arguments.


def format_metadata(metadata: dict[str, Any]) -> str:
    """Format metadata dictionary as indented JSON string.

    Parameters
    ----------
    metadata : dict[str, Any]
        Metadata dictionary to format.

    Returns
    -------
    str
        JSON-formatted string with 4-space indentation.

    Raises
    ------
    TypeError
        If metadata is not a dictionary.
    """
    if not isinstance(metadata, dict):
        msg = f"metadata must be a dict, got {type(metadata).__name__}"
        raise TypeError(msg)

    return ujson.dumps(metadata, indent=4)


def save_metadata(path: str | Path, args: object) -> dict[str, object]:
    """Collect metadata and save it to a JSON file.

    Gathers metadata from arguments and system, formats it as JSON,
    and writes it to the specified path. Ensures the file doesn't
    already exist before writing.

    Parameters
    ----------
    path : str | Path
        File path where metadata will be saved (must not exist).
    args : Any
        Arguments object to collect metadata from.

    Returns
    -------
    dict[str, Any]
        The metadata dictionary that was saved.

    Raises
    ------
    FileExistsError
        If the output path already exists.
    """
    if pathlib.Path(path).exists():
        msg = f"Output path already exists: {path}"
        raise FileExistsError(msg)

    with pathlib.Path(path).open("w", encoding="utf-8") as output_metadata:
        data = get_metadata(args)
        output_metadata.write(format_metadata(data) + "\n")

    return data
