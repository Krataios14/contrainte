# Exact rigid transforms

Contrainte's exact-transform kernel represents a three-dimensional local-to-parent
rigid transform without binary floating point. It is the algebraic foundation for
interface mating, cycle closure, assembly synthesis, datum propagation, and exact
frame evidence.

## Contract

`contrainte.exact-rigid-transform/0.1` contains:

- `unit`, fixed to `mm`;
- `translation`, with x, y, and z canonical reduced rational strings; and
- `basis`, whose x, y, and z axes are stored as column vectors.

The parser proves exactly that every axis has unit length, every pair is orthogonal,
and the determinant is +1. Reflections, approximate matrices, unreduced fractions,
noncanonical spellings, subclasses that could override arithmetic, and scalars above
the 128-character resource bound are rejected.

`A.compose(B)` means `A * B`: `B` is applied first. A transform maps local points
into its parent frame. `inverse()` returns the exact inverse, and
`child.relative_to(parent)` computes `parent.inverse().compose(child)`.

All vector, rotation, and transform objects are frozen and slotted. Operations fail
closed if an exact output would exceed the scalar bound. The schema uses rational
translations because arbitrary sequences of exact frame composition can produce
fractions even when released interface origins begin as finite decimal millimetres.

## Evidence boundary

This module establishes rigid-transform algebra only. It does not by itself prove:

- that two component interfaces are compatible;
- that an assembly graph is connected, fully constrained, or cycle-consistent;
- that placed B-reps are collision-free or meet clearance requirements;
- that a frame is attached to persistent semantic topology;
- that nominal exact placement remains valid under tolerances or deformation; or
- that a mechanism is kinematically or dynamically valid.

Those claims require separate assembly, geometry, tolerance, and physics evidence.

## Deliberate limits

Only millimetres and rationally representable proper rotations are accepted in schema
0.1. There is no uncertainty model, interval transform, affine deformation, scale,
reflection, projective transform, quaternion, or floating-angle input. A later kernel
projection may convert exact values to floating point for Open CASCADE or OpenUSD,
but the conversion must remain an explicitly non-authoritative boundary.
