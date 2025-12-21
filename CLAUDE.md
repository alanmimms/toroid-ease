# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Toroid-Ease generates FPC (Flexible Printed Circuit) designs for toroidal inductor windings in KiCad 9. The FPC wraps around the toroid cross-section: starting at the OD, down the flat face, through the ID bore as a cylinder, up the other flat face, and back to the OD where B-edge is soldered to A-edge to continue the helix.

## Running the Tool

Requires KiCad 9's Python environment (for `pcbnew` module):

```bash
./toroid-ease.py -c <core> -t <turns> -a <amps> -o <output.kicad_pcb>

# Examples
./toroid-ease.py -c T68 -t 20 -a 1.0 -o my_coil.kicad_pcb
./toroid-ease.py -c FT-50 -t 30 -a 2.0 --maxLayers 4 -o high_current.kicad_pcb
./toroid-ease.py -c T200 -t 60 -a 0.5 --taps 20,40 -o tapped_coil.kicad_pcb
```

## CLI Parameters

- `-c, --core`: Core type (T68, T-68, FT68, FT-68 all accepted)
- `-t, --turns`: Number of turns required
- `-a, --amps`: Current capacity in amps (default: 0.5)
- `-l, --maxLayers`: Maximum layer count (default: 6)
- `--angle`: Angular coverage in degrees (default: 360)
- `--taps`: Comma-separated turn numbers for tap flaps
- `--viaDrill`, `--viaSize`, `--padDrill`: Via and pad dimensions

## Architecture

Single-file CLI tool with these major sections:

1. **Configuration calculation** (`calculateConfiguration`): Determines optimal layer configuration (parallel for current, series for turns), trace width/pitch, via farm sizing. Uses progressive half-pitch offsets for series layer sets to minimize inter-layer capacitance.

2. **Geometry generation**:
   - `generateBoardOutline`: Board shape with slits at OD edges for spreading
   - `generateFoldLines`: Dashed silkscreen at ID fold lines
   - `generateTabsAndSlots`: Alignment tabs (B-edge) and slots (A-edge) per wedge
   - `generateTraces`: Copper traces on all layers with offsets
   - `generateViaFarms`: Via arrays connecting parallel layers
   - `generateBtoAPads`: Rectangular pads for B-to-A soldering
   - `generateFlaps`: Start/end/tap flaps with THT pads extending from OD edge

## Layer Organization

For multi-layer designs requiring both current capacity and more turns:
- Adjacent layers are paralleled for current (L1+L2, L3+L4, etc.)
- Layer sets are in series for more turns
- Progressive offset (half-pitch per series set) reduces capacitance
- Via farms aggregate parallel layers before B-to-A solder joints

## Supported Cores

T68, T50, T37, T200 (with aliases: T-68, FT68, FT-68, etc.)

## Code Style

- 2-space indentation
- camelCase for variables and functions (e.g., `minGapMm`, `toNm`)
- Symbolic constants for magic numbers
