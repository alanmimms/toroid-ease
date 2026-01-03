# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Toroid-Ease generates FPC (Flexible Printed Circuit) designs for toroidal inductor windings in KiCad 9. The FPC wraps around the toroid cross-section: starting at the OD, down the flat face, through the ID bore as a cylinder, up the other flat face, and back to the OD where B-edge is soldered to A-edge to continue the helix.

## Running the Tool

Requires KiCad 9's Python environment (for `pcbnew` module):

```bash
./toroid-ease.py -c <core> -t <turns> -a <amps> -o <output.kicad_pcb>

# Examples
./toroid-ease.py -c T68 -t 20 -a 0.5 -o my_coil.kicad_pcb
./toroid-ease.py -c T200 -t 52 -a 1.0 --layers 2 -o high_current.kicad_pcb
./toroid-ease.py -c FT-50 -t 30 -a 0.5 --mount flat -o flat_mount.kicad_pcb
```

## CLI Parameters

Required:
- `-c, --core`: Core type (T68, T-68, FT68, FT-68 all accepted, case-insensitive)
- `-t, --turns`: Number of turns required
- `-o, --output`: Output filename (.kicad_pcb)

Optional:
- `-a, --amps`: Current capacity in amps (default: 0.5)
- `--layers`: FPC layer count, 1 or 2 (default: 2, parallel for current)
- `--copper`: Copper thickness - 0.5oz, 18u, 1oz, 35u, 2oz, 70u (default: 1oz)
- `--fpcThickness`: FPC base thickness in mm (default: 0.22)
- `--bendRadius`: Override calculated bend radius in mm
- `--slitEndDiameter`: Rip-stop semicircle diameter in mm (default: 0.8)
- `--mount`: Mounting orientation - rolling or flat (default: rolling)

## Architecture

Single-file CLI tool (~1100 lines) with these major sections:

1. **Fabrication Constants**: Well-documented constants at top for fab house adaptation
   - Trace geometry (min width, gap, annular ring)
   - Copper thickness options
   - Via geometry
   - Bend radius K-factor
   - Pad dimensions

2. **Core Database**: Expanded list of common toroids
   - T-series: T25, T30, T37, T44, T50, T68, T80, T94, T106, T130, T157, T200
   - FT-series: FT37, FT50, FT82, FT114, FT140, FT240

3. **Configuration Calculation** (`calculateConfiguration`): Determines:
   - Bend radius from FPC + copper thickness
   - Pitch at ID and OD
   - Trace width from current requirement
   - Via count for 2-layer parallel
   - Fan-out ratio

4. **Geometry Generation**:
   - `generateEdgeCuts`: Board outline with slits and flap cutouts
   - `generateSlit`: Individual slits with semicircular rip-stop endings
   - `generateWindingTraces`: Hockey-stick shaped traces
   - `generateTraceVias`: Via arrays for 2-layer parallel
   - `generateLapPads`: SMD pads for B-to-A solder joints
   - `generateFlapPads`: SMD pads on mounting flaps
   - `generateStiffener`: Stiffener outlines on User.1 layer
   - `generateFoldLines`: Dashed silkscreen at fold positions

## Layer Organization

Simple 1 or 2 layer FPC:
- **1 layer**: Single copper layer (F.Cu)
- **2 layers**: F.Cu and B.Cu in parallel, connected by vias at each winding

For 2-layer designs:
- Both layers carry the same trace pattern
- Vias at each end of each trace connect the layers
- Current capacity doubles compared to 1-layer

## Geometry Model

### FPC Layout (unfolded)
```
A-edge (OD, Y=0)
==========================================================
|  Flat face 1 (fans out toward OD)                      |
|-------- Fold Line 1 (slits here) ----------------------|
|  ID section (fixed pitch, parallel traces)             |
|-------- Fold Line 2 (slits here) ----------------------|
|  Flat face 2 (fans out toward OD)                      |
==========================================================
B-edge (OD, Y=fpcHeight)
   ^ START flap                              END flap ^
```

### Key Dimensions
- FPC height = 2 * radialThickness + axialHeight
- radialThickness = (OD - ID) / 2
- Pitch at ID = (ID * pi) / turns
- Pitch at OD = (OD * pi) / turns

### Mounting Orientations

**Rolling (default)**: Toroid "rolls" on the PCB like a tire
- Flaps extend from B-edge (bottom of FPC)
- Flaps bend tangentially from the toroid surface
- Good for compact mounting

**Flat**: Toroid lays flat on PCB (axis perpendicular to PCB)
- Flaps extend from A-edge (top of FPC)
- Flaps run parallel to toroid axis
- Good for through-hole style mounting

## Supported Cores

All cores accept variations: T68, T-68, FT68, FT-68, t68, ft-68, etc.

| Core  | OD (mm) | ID (mm) | Height (mm) |
|-------|---------|---------|-------------|
| T25   | 6.35    | 3.05    | 2.55        |
| T30   | 7.80    | 3.80    | 3.25        |
| T37   | 9.50    | 5.20    | 3.25        |
| T44   | 11.20   | 5.80    | 4.00        |
| T50   | 12.70   | 7.70    | 4.80        |
| T68   | 17.50   | 9.40    | 4.80        |
| T80   | 20.30   | 12.70   | 6.35        |
| T94   | 23.90   | 14.30   | 9.50        |
| T106  | 26.90   | 14.50   | 11.10       |
| T130  | 33.00   | 19.50   | 11.00       |
| T157  | 40.00   | 23.50   | 14.50       |
| T200  | 50.80   | 31.75   | 14.00       |
| FT37  | 9.53    | 4.75    | 3.18        |
| FT50  | 12.70   | 7.15    | 4.80        |
| FT82  | 21.00   | 13.00   | 6.35        |
| FT114 | 29.00   | 19.00   | 7.50        |
| FT140 | 35.55   | 23.00   | 12.70       |
| FT240 | 61.00   | 35.55   | 12.70       |

## Code Style

- 2-space indentation
- camelCase for variables and functions
- UPPER_SNAKE_CASE for constants
- Symbolic constants for magic numbers

## Rendering for Debugging

Use kicad-cli to export PDF for visual inspection:
```bash
kicad-cli pcb export pdf output.kicad_pcb -o output.pdf \
  --layers "F.Cu,B.Cu,Edge.Cuts,User.1,F.Silkscreen" --mode-single
```

## Design Constraints

The tool will reject designs that don't fit:
- Required trace width exceeds available pitch at ID
- Maximum trace width below fabrication minimum

When a design is rejected, error messages explain the constraint.
