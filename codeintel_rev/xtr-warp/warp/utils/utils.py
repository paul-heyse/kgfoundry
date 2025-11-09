"""General utility functions for WARP.

This module provides helper functions for printing, timestamps, file I/O,
checkpointing, and data manipulation.
"""

from __future__ import annotations

import datetime
import itertools
import pathlib
from collections import OrderedDict, defaultdict
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, Generic, Protocol, TypeVar

if TYPE_CHECKING:
    from torch.nn import Module
    from torch.optim import Optimizer

import torch
import tqdm

# Minimum width threshold for zip_first optimization
MIN_WIDTH_FOR_ZIP_FIRST = 100

# Type variables for generic functions
T = TypeVar("T")


def print_message(*s: object, condition: bool = True, pad: bool = False) -> str:
    """Print timestamped message.

    Parameters
    ----------
    *s : Any
        Arguments to format as message.
    condition : bool
        Whether to print (default: True).
    pad : bool
        Whether to add newlines (default: False).

    Returns
    -------
    str
        Formatted message string.
    """
    s = " ".join([str(x) for x in s])
    msg = "[{}] {}".format(datetime.datetime.now(tz=datetime.UTC).strftime("%b %d, %H:%M:%S"), s)

    if condition:
        msg = msg if not pad else f"\n{msg}\n"

    return msg


def timestamp(*, daydir: bool = False) -> str:
    """Generate timestamp string.

    Parameters
    ----------
    daydir : bool
        Whether to use directory-style format (default: False).

    Returns
    -------
    str
        Timestamp string (e.g., "2024-01-15_14.30.45" or "2024/01/15/14.30.45").
    """
    format_str = f"%Y-%m{'/' if daydir else '-'}%d{'/' if daydir else '_'}%H.%M.%S"
    return datetime.datetime.now(tz=datetime.UTC).strftime(format_str)


def file_tqdm(file: object) -> Iterator[str]:
    """Iterate file with progress bar.

    Parameters
    ----------
    file : Any
        File-like object with name attribute.

    Yields
    ------
    str
        File lines.
    """
    with tqdm.tqdm(
        total=pathlib.Path(file.name).stat().st_size / 1024.0 / 1024.0, unit="MiB"
    ) as pbar:
        for line in file:
            yield line
            pbar.update(len(line) / 1024.0 / 1024.0)

        pbar.close()


def torch_load_dnn(path: str) -> dict[str, object]:
    """Load PyTorch model from file or URL.

    Parameters
    ----------
    path : str
        File path or HTTP/HTTPS URL.

    Returns
    -------
    Any
        Loaded model state dict.
    """
    if path.startswith(("http:", "https:")):
        dnn = torch.hub.load_state_dict_from_url(path, map_location="cpu")
    else:
        dnn = torch.load(path, map_location="cpu")

    return dnn


def save_checkpoint(
    path: str | pathlib.Path,
    epoch_idx: int,
    mb_idx: int,
    model: Module,
    optimizer: Optimizer,
    arguments: dict[str, object] | None = None,
) -> None:
    """Save training checkpoint to disk.

    Extracts model from distributed/data-parallel wrapper if needed and saves
    epoch, batch, model state, optimizer state, and arguments.

    Parameters
    ----------
    path : str | pathlib.Path
        Path to save checkpoint.
    epoch_idx : int
        Current epoch index.
    mb_idx : int
        Current minibatch index.
    model : Any
        Model to save (extracted from wrapper if needed).
    optimizer : Any
        Optimizer to save.
    arguments : dict[str, Any] | None
        Optional arguments dictionary (default: None).
    """
    if hasattr(model, "module"):
        model = model.module  # extract model from a distributed/data-parallel wrapper

    checkpoint = {}
    checkpoint["epoch"] = epoch_idx
    checkpoint["batch"] = mb_idx
    checkpoint["model_state_dict"] = model.state_dict()
    checkpoint["optimizer_state_dict"] = optimizer.state_dict()
    checkpoint["arguments"] = arguments

    torch.save(checkpoint, path)


def load_checkpoint(
    path: str | pathlib.Path,
    model: Module,
    checkpoint: dict[str, object] | None = None,
    optimizer: Optimizer | None = None,
    *,
    do_print: bool = True,
) -> dict[str, object]:
    """Load training checkpoint from disk.

    Loads checkpoint, updates model and optionally optimizer state dicts,
    and prints checkpoint info.

    Parameters
    ----------
    path : str | pathlib.Path
        Path to checkpoint file or URL.
    model : Any
        Model to load state into.
    checkpoint : dict[str, Any] | None
        Pre-loaded checkpoint dict (default: None, loads from path).
    optimizer : Any | None
        Optional optimizer to load state into (default: None).
    do_print : bool
        Whether to print loading messages (default: True).

    Returns
    -------
    dict[str, Any]
        Loaded checkpoint dictionary.
    """
    if do_print:
        print_message("#> Loading checkpoint", path, "..")

    if checkpoint is None:
        checkpoint = load_checkpoint_raw(path)

    try:
        model.load_state_dict(checkpoint["model_state_dict"])
    except (RuntimeError, KeyError):
        print_message("[WARNING] Loading checkpoint with strict=False")
        model.load_state_dict(checkpoint["model_state_dict"], strict=False)

    if optimizer:
        optimizer.load_state_dict(checkpoint["optimizer_state_dict"])

    if do_print:
        print_message("#> checkpoint['epoch'] =", checkpoint["epoch"])
        print_message("#> checkpoint['batch'] =", checkpoint["batch"])

    return checkpoint


def load_checkpoint_raw(path: str) -> dict[str, Any]:
    """Load checkpoint from file or URL, removing 'module.' prefix.

    Loads checkpoint and removes 'module.' prefix from state dict keys
    (for compatibility with distributed training).

    Parameters
    ----------
    path : str
        File path or HTTP/HTTPS URL.

    Returns
    -------
    dict[str, Any]
        Checkpoint dictionary with cleaned state dict.
    """
    if path.startswith(("http:", "https:")):
        checkpoint = torch.hub.load_state_dict_from_url(path, map_location="cpu")
    else:
        checkpoint = torch.load(path, map_location="cpu")

    state_dict = checkpoint["model_state_dict"]
    new_state_dict = OrderedDict()
    for k, v in state_dict.items():
        name = k
        if k[:7] == "module.":
            name = k[7:]
        new_state_dict[name] = v

    checkpoint["model_state_dict"] = new_state_dict

    return checkpoint


def create_directory(path: str | pathlib.Path) -> None:
    """Create directory if it doesn't exist.

    Creates directory with parents, printing message if it already exists.

    Parameters
    ----------
    path : str | pathlib.Path
        Directory path to create.
    """
    if pathlib.Path(path).exists():
        print_message("#> Note: Output directory", path, "already exists\n\n")
    else:
        print_message("#> Creating directory", path, "\n\n")
        pathlib.Path(path).mkdir(parents=True)




def f7(seq: Sequence[Any]) -> list[Any]:
    """Remove duplicates from sequence while preserving order.

    Source: https://stackoverflow.com/a/480227/1493011.

    Parameters
    ----------
    seq : Sequence[Any]
        Input sequence.

    Returns
    -------
    list[Any]
        List with duplicates removed, preserving order.
    """
    seen = set()
    return [x for x in seq if not (x in seen or seen.add(x))]


def batch(
    group: Sequence[Any], bsize: int, *, provide_offset: bool = False
) -> Iterator[tuple[int, Sequence[Any]] | Sequence[Any]]:
    """Batch sequence into fixed-size chunks.

    Parameters
    ----------
    group : Sequence[Any]
        Sequence to batch.
    bsize : int
        Batch size.
    provide_offset : bool
        Whether to include offset in yield (default: False).

    Yields
    ------
    tuple[int, Sequence[Any]] | Sequence[Any]
        Batches, optionally with offset.
    """
    offset = 0
    while offset < len(group):
        lst = group[offset : offset + bsize]
        yield ((offset, lst) if provide_offset else lst)
        offset += len(lst)


class Dotdict(dict):
    """Dictionary with dot notation access.

    Allows accessing dictionary keys as attributes using dot notation.
    Credit: derek73 @ https://stackoverflow.com/questions/2352181.

    Examples
    --------
    >>> d = Dotdict({"key": "value"})
    >>> d.key
    'value'
    """

    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


class DotdictLax(dict):
    """Dictionary with lax dot notation access.

    Allows accessing dictionary keys as attributes, returning None
    if key doesn't exist (unlike dotdict which raises KeyError).
    """

    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__


def flatten(seq: Sequence[Sequence[Any]]) -> list[Any]:
    """Flatten nested sequence into single list.

    Parameters
    ----------
    seq : Sequence[Sequence[Any]]
        Nested sequence to flatten.

    Returns
    -------
    list[Any]
        Flattened list.
    """
    result = []
    for _list in seq:
        result += _list

    return result


def zipstar(
    seq: Sequence[Sequence[Any]],
    *,
    lazy: bool = False,
) -> list[list[Any]] | Iterator[tuple[Any, ...]]:
    """Transpose nested sequence (faster than zip(*L)).

    Much faster alternative to A, B, C = zip(*[(a, b, c), (a, b, c), ...]).
    May return lists or tuples depending on lazy parameter.

    Parameters
    ----------
    seq : Sequence[Sequence[Any]]
        Nested sequence to transpose.
    lazy : bool
        Whether to return lazy iterator (default: False).

    Returns
    -------
    list[list[Any]] | Iterator[tuple[Any, ...]]
        Transposed sequence as list or iterator.
    """
    if len(seq) == 0:
        return seq

    width = len(seq[0])

    if width < MIN_WIDTH_FOR_ZIP_FIRST:
        return [[elem[idx] for elem in seq] for idx in range(width)]

    seq_zipped = zip(*seq, strict=False)

    return seq_zipped if lazy else list(seq_zipped)


def zip_first(l1: Sequence[Any], l2: Sequence[Any]) -> list[tuple[Any, Any]]:
    """Zip two sequences, validating length if first is tuple/list.

    Parameters
    ----------
    l1 : Sequence[Any]
        First sequence.
    l2 : Sequence[Any]
        Second sequence.

    Returns
    -------
    list[tuple[Any, Any]]
        Zipped list of tuples.

    Raises
    ------
    ValueError
        If l1 is tuple/list and length doesn't match zipped result.
    """
    length = len(l1) if type(l1) in {tuple, list} else None

    zipped_result = list(zip(l1, l2, strict=False))

    if length not in {None, len(zipped_result)}:
        msg = f"zip_first() failure: length differs! Expected {length}, got {len(zipped_result)}"
        raise ValueError(msg)

    return zipped_result


def int_or_float(val: str) -> int | float:
    """Parse string as int or float.

    Parameters
    ----------
    val : str
        String to parse.

    Returns
    -------
    int | float
        Parsed integer or float.
    """
    if "." in val:
        return float(val)

    return int(val)


def load_ranking(
    path: str | pathlib.Path,
    types: Iterator[type[int | float]] | None = None,
    *,
    lazy: bool = False,
) -> list[list[int | float]]:
    """Load ranking from file or PyTorch checkpoint.

    Loads ranking lists from PyTorch checkpoint or TSV file, optionally
    applying type conversion.

    Parameters
    ----------
    path : str | pathlib.Path
        Path to ranking file or checkpoint.
    types : Iterator[type[int | float]] | None
        Iterator of types for conversion (default: None, auto-detect).
    lazy : bool
        Whether to use lazy loading (default: False).

    Returns
    -------
    list[list[int | float]]
        List of ranking lists.
    """
    print_message(f"#> Loading the ranked lists from {path} ..")

    try:
        lists = torch.load(path)
        lists = zipstar([lst.tolist() for lst in tqdm.tqdm(lists)], lazy=lazy)
    except (FileNotFoundError, EOFError, OSError):
        if types is None:
            types = itertools.cycle([int_or_float])

        with pathlib.Path(path).open(encoding="utf-8") as f:
            lists = [
                [typ(x) for typ, x in zip_first(types, line.strip().split("\t"))]
                for line in file_tqdm(f)
            ]

    return lists


def save_ranking(
    ranking: Sequence[Sequence[int | float]], path: str | pathlib.Path
) -> list[torch.Tensor]:
    """Save ranking to PyTorch checkpoint.

    Parameters
    ----------
    ranking : Sequence[Sequence[int | float]]
        Ranking lists to save.
    path : str | pathlib.Path
        Path to save checkpoint.

    Returns
    -------
    list[torch.Tensor]
        List of tensor lists that were saved.
    """
    lists = zipstar(ranking)
    lists = [torch.tensor(lst) for lst in lists]

    torch.save(lists, path)

    return lists


def groupby_first_item(lst: Sequence[Sequence[Any]]) -> defaultdict[Any, list[Any]]:
    """Group sequences by their first item.

    Parameters
    ----------
    lst : Sequence[Sequence[Any]]
        Sequence of sequences to group.

    Returns
    -------
    defaultdict[Any, list[Any]]
        Dictionary mapping first items to lists of remaining items.
    """
    groups = defaultdict(list)

    for first, *rest_items in lst:
        rest = rest_items[0] if len(rest_items) == 1 else rest_items
        groups[first].append(rest)

    return groups


def process_grouped_by_first_item(
    lst: Sequence[Sequence[Any]],
) -> Iterator[tuple[Any, list[Any]]]:
    """Process sequences grouped by first item.

    Requires items in list to already be grouped by first item.
    Yields groups as they are encountered.

    Parameters
    ----------
    lst : Sequence[Sequence[Any]]
        Sequence of sequences, already grouped by first item.

    Yields
    ------
    tuple[Any, list[Any]]
        Tuple of (first_item, list_of_remaining_items).

    Raises
    ------
    ValueError
        If items are not properly grouped (same first item appears twice).
    """
    groups = defaultdict(list)

    started = False
    last_group = None

    for first, *rest_items in lst:
        rest = rest_items[0] if len(rest_items) == 1 else rest_items

        if started and first != last_group:
            yield (last_group, groups[last_group])
            if first in groups:
                msg = f"{first} seen earlier --- violates precondition."
                raise ValueError(msg)

        groups[first].append(rest)

        last_group = first
        started = True

    return groups


def grouper(iterable: Sequence[T], n: int, fillvalue: T | None = None) -> Iterator[tuple[T | None, ...]]:
    """Collect data into fixed-length chunks or blocks.

    Example: grouper('ABCDEFG', 3, 'x') --> ABC DEF Gxx
    Source: https://docs.python.org/3/library/itertools.html#itertools-recipes.

    Parameters
    ----------
    iterable : Sequence[Any]
        Sequence to group.
    n : int
        Chunk size.
    fillvalue : Any
        Value to fill last chunk if needed (default: None).

    Returns
    -------
    Iterator[tuple[Any, ...]]
        Iterator over chunks of size n.
    """
    args = [iter(iterable)] * n
    return itertools.zip_longest(*args, fillvalue=fillvalue)


def lengths2offsets(lengths: Sequence[int]) -> Iterator[tuple[int, int]]:
    """Convert sequence lengths to (start, end) offset pairs.

    Parameters
    ----------
    lengths : Sequence[int]
        Sequence of lengths.

    Yields
    ------
    tuple[int, int]
        Tuple of (start_offset, end_offset) for each length.
    """
    offset = 0

    for length in lengths:
        yield (offset, offset + length)
        offset += length


# see https://stackoverflow.com/a/45187287
class NullContextManager(Generic[T]):
    """No-op context manager.

    Provides context manager interface that does nothing.
    Useful for conditional context managers.
    """

    def __init__(self, dummy_resource: T | None = None) -> None:
        """Initialize NullContextManager.

        Parameters
        ----------
        dummy_resource : T | None
            Resource to return from __enter__ (default: None).
        """
        self.dummy_resource = dummy_resource

    def __enter__(self) -> T | None:
        """Enter context (no-op).

        Returns
        -------
        Any
            Dummy resource.
        """
        return self.dummy_resource

    def __exit__(self, *args: object) -> None:
        """Exit context (no-op).

        Parameters
        ----------
        *args : Any
            Exception info (ignored).
        """


def load_batch_backgrounds(args: object, qids: Sequence[str | int]) -> list[str] | None:
    """Load background contexts for query IDs.

    Parameters
    ----------
    args : Any
        Arguments object with qid2backgrounds, collection, and collectionX.
    qids : Sequence[str | int]
        Query IDs to load backgrounds for.

    Returns
    -------
    list[str] | None
        List of background strings joined with [SEP], or None if no backgrounds.
    """
    if args.qid2backgrounds is None:
        return None

    qbackgrounds = []

    for qid in qids:
        back = args.qid2backgrounds[qid]

        if len(back) and isinstance(back[0], int):
            x = [args.collection[pid] for pid in back]
        else:
            x = [args.collectionX.get(pid, "") for pid in back]

        x = " [SEP] ".join(x)
        qbackgrounds.append(x)

    return qbackgrounds
