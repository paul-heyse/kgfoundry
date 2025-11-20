# SPDX-License-Identifier: MIT
"""Tests for GOID normalization and hashing."""

from __future__ import annotations

from pathlib import Path

from codeintel_rev.ids.goid import EntityDescriptor, RepoSnapshot, compute_goid

from tests._helpers import assertions


def test_compute_goid_normalizes_language_and_paths() -> None:
    """Language casing, relative paths, and line bounds should be normalized."""
    snapshot = RepoSnapshot(repo="DemoRepo", commit="deadbeef")
    descriptor = EntityDescriptor(
        language="Python",
        kind="function",
        rel_path=Path("./pkg//alpha.py"),
        qualname="  Demo.run  ",
        start_line=0,
        end_line=-1,
    )
    goid = compute_goid(snapshot, descriptor)
    assertions.expect_equal(goid.language, "python")
    assertions.expect_equal(goid.rel_path, "pkg/alpha.py")
    assertions.expect_equal(goid.qualname, "Demo.run")
    assertions.expect_true(goid.start_line is None)
    assertions.expect_true(goid.end_line is None)


def test_compute_goid_hash_changes_with_span() -> None:
    """Hash and URN should change when source span changes."""
    snapshot = RepoSnapshot(repo="DemoRepo", commit="deadbeef")
    descriptor = EntityDescriptor(
        language="python",
        kind="function",
        rel_path="pkg/alpha.py",
        qualname="Demo.run",
        start_line=10,
        end_line=20,
    )
    goid_one = compute_goid(snapshot, descriptor)
    modified = EntityDescriptor(
        language="python",
        kind="function",
        rel_path="pkg/alpha.py",
        qualname="Demo.run",
        start_line=30,
        end_line=40,
    )
    goid_two = compute_goid(snapshot, modified)
    assertions.expect_true(goid_one.h128 != goid_two.h128)
    assertions.expect_true(goid_one.urn != goid_two.urn)
