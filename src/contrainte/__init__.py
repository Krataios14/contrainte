"""Contrainte's evidence-first deterministic engineering core."""

from .assembly import Assembly, PartOccurrence, RigidTransform
from .axial import AxialCase, AxialResult, solve_axial_case
from .cad import PrismaticPart, ThroughHole, compile_part, verify_cad_bundle
from .component import ArtifactRef, ComponentInterface, ComponentManifest
from .materials import MaterialRecord
from .pipeline import compile_bundle, verify_bundle
from .program import DesignProgram, DesignTask, GoalContract
from .release import ComponentReleaseRequest, derive_component_manifest
from .solid import SolidProgram
from .workspace import DesignWorkspace, ObjectRef

__all__ = [
    "ArtifactRef",
    "Assembly",
    "AxialCase",
    "AxialResult",
    "ComponentInterface",
    "ComponentManifest",
    "ComponentReleaseRequest",
    "DesignProgram",
    "DesignTask",
    "DesignWorkspace",
    "GoalContract",
    "MaterialRecord",
    "ObjectRef",
    "PartOccurrence",
    "PrismaticPart",
    "RigidTransform",
    "SolidProgram",
    "ThroughHole",
    "compile_bundle",
    "compile_part",
    "derive_component_manifest",
    "solve_axial_case",
    "verify_bundle",
    "verify_cad_bundle",
]

__version__ = "0.1.0"
