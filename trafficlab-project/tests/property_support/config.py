"""Deterministic configuration and replay metadata for Haware properties."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Callable, TypeVar

import hypothesis
from hypothesis import Phase, note, seed, settings
from hypothesis.database import DirectoryBasedExampleDatabase


MIN_SUCCESSFUL_EXAMPLES = 100
DEFAULT_CI_SEED = 20260727
HYPOTHESIS_VERSION = hypothesis.__version__
PROPERTY_MODULE_PATTERN = re.compile(r"^test_property_(\d{2})_[a-z0-9_]+$")
F = TypeVar("F", bound=Callable[..., Any])


def _environment_int(name: str, default: int, *, minimum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}")
    return value


CI_SEED = _environment_int("HAWARE_HYPOTHESIS_SEED", DEFAULT_CI_SEED, minimum=0)
MAX_EXAMPLES = _environment_int(
    "HAWARE_HYPOTHESIS_MAX_EXAMPLES", MIN_SUCCESSFUL_EXAMPLES, minimum=MIN_SUCCESSFUL_EXAMPLES
)
DATABASE_PATH = Path(
    os.environ.get("HAWARE_HYPOTHESIS_DATABASE", ".hypothesis/haware-localization-accuracy")
)
PROPERTY_SETTINGS = settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    database=DirectoryBasedExampleDatabase(DATABASE_PATH),
    print_blob=True,
    report_multiple_bugs=True,
    phases=(Phase.explicit, Phase.reuse, Phase.generate, Phase.target, Phase.shrink),
)

def deterministic_property(property_number: int) -> Callable[[F], F]:
    """Apply the CI settings and seed, enforcing one numbered module per property."""
    if not 1 <= property_number <= 19:
        raise ValueError("property_number must be in the design range 1..19")

    def decorate(test: F) -> F:
        module_name = test.__module__.rsplit(".", 1)[-1]
        match = PROPERTY_MODULE_PATTERN.fullmatch(module_name)
        if match is None or int(match.group(1)) != property_number:
            expected = f"test_property_{property_number:02d}_<short_title>.py"
            raise RuntimeError(f"Property {property_number} must be defined only in {expected}")
        return seed(CI_SEED)(PROPERTY_SETTINGS(test))  # type: ignore[return-value]

    return decorate


def _identity_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    digest = getattr(value, "digest", None)
    if isinstance(digest, str):
        return digest
    identity = getattr(value, "content_identity", None)
    identity_digest = getattr(identity, "digest", None)
    if isinstance(identity_digest, str):
        return identity_digest
    raise TypeError("identity must be a string, ContentIdentity, or canonical model")


def failure_metadata(*, replay_identity: Any, profile_identity: Any, run_identity: Any) -> str:
    """Return stable metadata printed with a failing generated example."""
    return json.dumps(
        {
            "ci_seed": CI_SEED,
            "hypothesis_version": HYPOTHESIS_VERSION,
            "profile_identity": _identity_text(profile_identity),
            "replay_identity": _identity_text(replay_identity),
            "run_identity": _identity_text(run_identity),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def record_failure_metadata(*, replay_identity: Any, profile_identity: Any, run_identity: Any) -> None:
    """Attach replay/profile/run identities to Hypothesis failure output."""
    note(failure_metadata(
        replay_identity=replay_identity,
        profile_identity=profile_identity,
        run_identity=run_identity,
    ))
