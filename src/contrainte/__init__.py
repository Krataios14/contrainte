"""Contrainte's evidence-first deterministic engineering core."""

from .assembly import Assembly, PartOccurrence, RigidTransform
from .axial import AxialCase, AxialResult, solve_axial_case
from .cad import PrismaticPart, ThroughHole, compile_part, verify_cad_bundle
from .component import (
    ArtifactRef,
    ComponentInterface,
    ComponentManifest,
    ExactInterfaceFrame,
)
from .exact_transform import ExactRigidTransform, ExactRotation3, ExactVector3
from .interface_assembly import (
    InconclusiveReason,
    InterfaceAssembly,
    InterfaceAssemblyResult,
    InterfaceEndpoint,
    InterfaceMate,
    InterfaceOccurrence,
    MateAlternative,
    SelectedMateAlternative,
    SolvedOccurrence,
    SolveStatus,
    solve_interface_assembly,
    verify_interface_assembly_result,
    verify_interface_assembly_solution,
)
from .materials import MaterialRecord
from .pipeline import compile_bundle, verify_bundle
from .program import DesignProgram, DesignTask, GoalContract
from .release import ComponentReleaseRequest, derive_component_manifest
from .sketch import (
    CircularHole,
    SketchConstraint,
    SketchExtrusion,
    SketchPoint,
    SketchProfile,
    compile_sketch_extrusion,
    solve_constraints,
    verify_sketch_bundle,
)
from .solid import SolidProgram
from .workspace import DesignWorkspace, ObjectRef

__all__ = [
    "ArtifactRef",
    "Assembly",
    "AxialCase",
    "AxialResult",
    "CircularHole",
    "ComponentInterface",
    "ComponentManifest",
    "ComponentReleaseRequest",
    "DesignProgram",
    "DesignTask",
    "DesignWorkspace",
    "ExactInterfaceFrame",
    "ExactRigidTransform",
    "ExactRotation3",
    "ExactVector3",
    "GoalContract",
    "InconclusiveReason",
    "InterfaceAssembly",
    "InterfaceAssemblyResult",
    "InterfaceEndpoint",
    "InterfaceMate",
    "InterfaceOccurrence",
    "MateAlternative",
    "MaterialRecord",
    "ObjectRef",
    "PartOccurrence",
    "PrismaticPart",
    "RigidTransform",
    "SelectedMateAlternative",
    "SketchConstraint",
    "SketchExtrusion",
    "SketchPoint",
    "SketchProfile",
    "SolidProgram",
    "SolveStatus",
    "SolvedOccurrence",
    "ThroughHole",
    "compile_bundle",
    "compile_part",
    "compile_sketch_extrusion",
    "derive_component_manifest",
    "solve_axial_case",
    "solve_constraints",
    "solve_interface_assembly",
    "verify_bundle",
    "verify_cad_bundle",
    "verify_interface_assembly_result",
    "verify_interface_assembly_solution",
    "verify_sketch_bundle",
]

__version__ = "0.1.0"
