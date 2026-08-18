"""RF-R2-001 -> Pine model-tree exporter — architecture stub, fails closed.

Per ``ML-001-R2-CLEAN-REBUILD-SPEC.md`` Section 13 (PINE COMPATIBILITY
ARCHITECTURE), the only sanctioned way to represent RF-R2-001 in Pine is
Approach B: an automated exporter that translates the *trained* model
artifact's actual tree structure into generated Pine nested-conditional
code, tree-by-tree, deterministically. Approach C ("replace the model
with something Pine-native and call it equivalent") is explicitly
rejected by the spec itself.

No trained RF-R2-001 artifact has ever existed in this repository or its
git history (see
``ML-001-R2-PYTHON-PINE-SIMULATOR-FORENSIC-BASELINE.md`` for the
independently-verified search). Because there is nothing to export,
this module's public entry point fails closed rather than generating
any Pine model code, fabricated or otherwise.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from utils.exceptions import EAFactoryError

MODEL_EXPORT_ARCHITECTURE = "APPROACH_B_TRAINED_TREE_TRANSLATION"


class ModelArtifactMissingError(EAFactoryError):
    """Raised by export_model_to_pine when no artifact exists at the
    given path. This is a deliberate fail-closed outcome, not an error
    to be silently worked around."""


def export_model_to_pine(model_artifact_path: Union[str, Path]) -> str:
    """Translate a *trained* RF-R2-001 artifact into Pine model code.

    Args:
        model_artifact_path: path to a persisted, checksummed RF-R2-001
            model artifact (e.g. produced by
            ``core.ml_r2.model_r2.RFR2Model.save()``).

    Returns:
        Generated Pine v6 source implementing the model's tree ensemble
        as nested conditionals, deterministically derived from the
        artifact's actual fitted structure.

    Raises:
        ModelArtifactMissingError: always, in this environment — no file
            exists at any path this project has ever used for a trained
            RF-R2-001 artifact, because none has ever been trained and
            persisted. This function deliberately does not fall back to
            generating placeholder, approximate, or substitute-model
            Pine code under any circumstance.
    """
    path = Path(model_artifact_path)
    if not path.exists():
        raise ModelArtifactMissingError(
            "MODEL_ARTIFACT_MISSING: no trained RF-R2-001 artifact found at "
            f"'{path}'. Per spec Section 13 Approach B, Pine model code may "
            "only be generated from a real, trained, checksummed artifact — "
            "this exporter refuses to fabricate one."
        )
    # Reached only once a real, trained, persisted RF-R2-001 artifact
    # exists somewhere in this environment. As of this report, that has
    # never happened, so this branch has never executed and its
    # tree-translation logic is intentionally not implemented yet —
    # writing it now, untested against a real artifact, would be
    # speculative code with no way to verify correctness.
    raise NotImplementedError(
        "Tree-structure translation (spec Section 13 Approach B) is not yet "
        "implemented. This branch is only reachable once a real trained "
        "RF-R2-001 artifact exists; implement and validate it against that "
        "artifact when it does, not speculatively beforehand."
    )
