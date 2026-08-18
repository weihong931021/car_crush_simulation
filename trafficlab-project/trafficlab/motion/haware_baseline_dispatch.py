"""Canonical Haware baseline/optimizer dispatch boundary.

The corrected ``HawareLocalizer.localize`` result is deliberately returned
unchanged in optimizer-disabled mode.  This module does not import optimizer
models, observation adapters, or authority/result mappers, so the frozen
legacy schema cannot be rewritten on that path.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Protocol, TypeVar


class FrozenBaselineIdentity(str, Enum):
    """Stable identities for the two legacy comparison paths."""

    CORRECTED_LOCALIZE = "corrected_legacy_localize"
    DIAGNOSTIC_REPROJECTION = "diagnostic_legacy_localize_reprojection"


@dataclass(frozen=True)
class HawareDispatchConfig:
    """The explicit canonical selector; disabled mode is the safe default."""

    optimizer_disabled_selected: bool = True

    def __post_init__(self) -> None:
        if type(self.optimizer_disabled_selected) is not bool:
            raise TypeError("optimizer_disabled_selected must be a bool")


class _LegacyLocalizer(Protocol):
    def localize(self, keypoints: Any) -> Any: ...

    def localize_reprojection(self, keypoints: Any) -> Any: ...


_ResultT = TypeVar("_ResultT")


def corrected_legacy_baseline(localizer: _LegacyLocalizer, keypoints: Any) -> Any:
    """Call the corrected ``localize`` baseline directly, without mapping."""
    return localizer.localize(keypoints)


def diagnostic_reprojection_baseline(localizer: _LegacyLocalizer, keypoints: Any) -> Any:
    """Call the separately identified diagnostic frozen baseline directly."""
    return localizer.localize_reprojection(keypoints)


def localize_dispatch(
    keypoints: Any,
    config: HawareDispatchConfig,
    corrected_localizer: _LegacyLocalizer,
    *,
    optimizer_localize: Optional[Callable[[], _ResultT]] = None,
) -> Any | _ResultT:
    """Dispatch to exactly one architecture.

    The disabled branch calls corrected ``localize`` with the original legacy
    input and returns its object unchanged.  The enabled branch calls only the
    supplied optimizer entry point; it cannot fall back to either baseline.
    """
    if config.optimizer_disabled_selected:
        return corrected_legacy_baseline(corrected_localizer, keypoints)
    if optimizer_localize is None:
        raise RuntimeError("optimizer selected without an optimizer entry point")
    return optimizer_localize()
