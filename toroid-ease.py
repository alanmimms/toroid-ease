#!/usr/bin/env python3
"""
Toroid-Ease: FPC (Flexible Printed Circuit) generator for toroidal inductors.

Generates KiCad 9 PCB files for FPC windings that wrap around toroid cores.
The FPC wraps: OD -> flat face -> ID bore -> flat face -> OD, where the
B-edge solders to the A-edge to continue the helix.

Usage:
  ./toroid-ease.py -c T68 -t 20 -a 1.0 -o my_coil.kicad_pcb
  ./toroid-ease.py -c FT-50 -t 30 -a 2.0 --layers 2 -o high_current.kicad_pcb
"""

import sys
import argparse
import math
import os
import pcbnew

# =============================================================================
# JLCPCB FLEX PCB DESIGN RULES
# =============================================================================
# Based on JLCPCB flex PCB capabilities (2024/2025)
# These are applied to the board and enforced by DRC

JLCPCB_RULES = {
  "clearance": 0.1,            # Min copper-to-copper clearance (mm)
  "track_width": 0.1,          # Min track width (mm) - JLCPCB can do 0.05mm but 0.1 is safer
  "via_drill": 0.2,            # Min via drill (mm)
  "via_diameter": 0.45,        # Min via pad diameter (mm)
  "annular_ring": 0.125,       # Min annular ring (mm)
  "hole_to_hole": 0.5,         # Min hole-to-hole spacing (mm)
  "edge_clearance": 0.2,       # Min copper-to-edge clearance (mm)
  "silk_clearance": 0.15,      # Min silk-to-edge clearance (mm)
  "min_slot_width": 0.8,       # Min routed slot/cutout width (mm)
}

# =============================================================================
# FABRICATION CONSTANTS
# =============================================================================
# Adjust these values to match your FPC fabricator's capabilities.
# These defaults target JLCPCB flex PCB production.

# --- Copper Geometry (using JLCPCB rules) ---
MIN_TRACE_WIDTH_MM = JLCPCB_RULES["track_width"]
MIN_GAP_MM = JLCPCB_RULES["clearance"]
MIN_ANNULAR_RING_MM = JLCPCB_RULES["annular_ring"]
EDGE_TO_COPPER_MM = JLCPCB_RULES["edge_clearance"]

# --- Copper Thickness Options ---
# Map of common copper weight/thickness specifications to mm
COPPER_THICKNESS = {
  "0.5oz": 0.0175,   # 17.5 microns - thinnest common FPC copper
  "18u":   0.018,    # 18 microns
  "1oz":   0.035,    # 35 microns - standard
  "35u":   0.035,    # 35 microns
  "2oz":   0.070,    # 70 microns - heavy copper
  "70u":   0.070,    # 70 microns
}

# --- Current Capacity ---
# IPC-2221 for external conductors with 20°C temperature rise.
# For 1oz copper in open air (external FPC), approximately:
#   I = 0.048 * dT^0.44 * A^0.725 where A is cross-sectional area in mil²
# For 20°C rise with 1oz copper (1.4 mil thick):
#   ~0.3mm width per amp is conservative for external traces
# Both layers carry current in parallel, so total capacity doubles.
MM_PER_AMP_1OZ = 0.3  # Conservative: mm trace width per amp for 1oz external

# Current capacity per via (0.3mm drill in 1oz copper, ~0.5A each)
AMPS_PER_VIA = 0.5

# If True, allow designs even if current capacity is below requested
ALLOW_UNDERCURRENT = True

# --- Via Geometry ---
DEFAULT_VIA_DRILL_MM = 0.3      # Via drill diameter
DEFAULT_VIA_SIZE_MM = 0.6       # Via pad diameter (drill + 2*annular ring)
VIA_SPACING_MM = 0.8            # Center-to-center via spacing in arrays

# --- Bend Radius ---
# Minimum bend radius = BEND_RADIUS_K * (FPC thickness + copper thickness)
# K factor: RA (rolled annealed) copper ~6-8, ED (electrodeposited) ~10-12
# For double-sided: K = 12 per JLCPCB guidelines
BEND_RADIUS_K = 12.0

# --- Fold Radius at Toroid Corners ---
# The toroid core has slightly rounded corners where the FPC bends.
# This radius affects the bend allowance added to the flat pattern.
# Manufacturer doesn't specify corner radius, so we assume a small value.
# Bend allowance per 90° fold = π × FOLD_RADIUS_MM / 2
FOLD_RADIUS_MM = 0.1  # Assumed toroid corner radius (mm) - tune as needed

# --- Slit/Rip-stop Geometry ---
# Rip-stop is a circular hole at the fold line, with two slits fanning outward
RIPSTOP_DIAMETER_MM = JLCPCB_RULES["min_slot_width"]  # 0.8mm minimum for routed features
SLIT_WIDTH_MM = JLCPCB_RULES["min_slot_width"]        # Slit width (laser cut)
SLIT_SPREAD_MM = 0.1                                   # How much slits spread apart at OD end

# --- SMD Pad Geometry ---
SMD_PAD_WIDTH_MM = 1.5          # Width of lap/connection pads
SMD_PAD_HEIGHT_MM = 4.0         # Height of lap/connection pads
SMD_PAD_ROUNDRECT_RATIO = 0.1   # Corner rounding ratio

# --- Stiffener ---
STIFFENER_MARGIN_MM = 1.0       # Margin around pads for stiffener outline
STIFFENER_LINE_WIDTH_MM = 0.15  # Line width for stiffener outline

# --- Silkscreen ---
SILK_LINE_WIDTH_MM = 0.15       # Silkscreen line width
SILK_DASH_LENGTH_MM = 1.0       # Length of dashes for fold lines
SILK_GAP_LENGTH_MM = 0.5        # Gap between dashes

# =============================================================================
# CORE DATABASE
# =============================================================================
# Format: "CoreName": (OD_mm, ID_mm, axialHeight_mm)
# Dimensions from manufacturer datasheets.

CORES = {
  # T-series (Micrometals/Amidon powdered iron)
  "T200": (50.80, 31.75, 14.00),
  "T157": (40.00, 23.50, 14.50),
  "T130": (33.00, 19.50, 11.00),
  "T106": (26.90, 14.50, 11.10),
  "T94":  (23.90, 14.30,  9.50),
  "T80":  (20.30, 12.70,  6.35),
  "T68":  (17.50,  9.40,  4.80),
  "T50":  (12.70,  7.70,  4.80),
  "T44":  (11.20,  5.80,  4.00),
  "T37":  ( 9.50,  5.20,  3.25),
  "T30":  ( 7.80,  3.80,  3.25),
  "T25":  ( 6.35,  3.05,  2.55),

  # FT-series (Fair-Rite ferrite toroids)
  "FT240": (61.00, 35.55, 12.70),
  "FT140": (35.55, 23.00, 12.70),
  "FT114": (29.00, 19.00,  7.50),
  "FT82":  (21.00, 13.00,  6.35),
  "FT50":  (12.70,  7.15,  4.80),
  "FT37":  ( 9.53,  4.75,  3.18),
}

# =============================================================================
# Core Lookup
# =============================================================================

def lookupCore(name):
  """
  Look up core dimensions by name.
  Accepts formats: T68, T-68, FT68, FT-68, t68, ft-68, etc.
  Returns (OD, ID, axialHeight) in mm, or None if not found.
  """
  # Normalize: uppercase, remove hyphens
  normalized = name.upper().replace("-", "")

  # Try direct lookup first
  if normalized in CORES:
    return CORES[normalized]

  # Try stripping 'F' prefix (FT68 -> T68)
  if normalized.startswith("F") and normalized[1:] in CORES:
    return CORES[normalized[1:]]

  # Try adding 'F' prefix (T68 -> FT68)
  if not normalized.startswith("F") and ("F" + normalized) in CORES:
    return CORES["F" + normalized]

  # Not found - print available cores
  print(f"Error: Core '{name}' not found.", file=sys.stderr)
  print("\nAvailable cores:", file=sys.stderr)
  print(f"  {'Name':<8} {'OD (mm)':<10} {'ID (mm)':<10} {'Height (mm)':<12}", file=sys.stderr)
  print(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*12}", file=sys.stderr)
  for coreName in sorted(CORES.keys()):
    od, coreId, height = CORES[coreName]
    print(f"  {coreName:<8} {od:<10.2f} {coreId:<10.2f} {height:<12.2f}", file=sys.stderr)
  print("\nAccepted formats: T68, T-68, FT68, FT-68 (case insensitive)", file=sys.stderr)
  return None

# =============================================================================
# Copper Thickness Parsing
# =============================================================================

def parseCopperThickness(spec):
  """
  Parse copper thickness specification.
  Accepts: "1oz", "35u", "0.5oz", "2oz", "70u", etc.
  Returns thickness in mm.
  """
  normalized = spec.lower().strip()
  if normalized in COPPER_THICKNESS:
    return COPPER_THICKNESS[normalized]

  # Try without 'u' suffix as microns
  if normalized.endswith("u"):
    try:
      microns = float(normalized[:-1])
      return microns / 1000.0
    except ValueError:
      pass

  # Try as direct mm value
  try:
    return float(normalized)
  except ValueError:
    pass

  print(f"Error: Unknown copper thickness '{spec}'", file=sys.stderr)
  print("Accepted values: 0.5oz, 18u, 1oz, 35u, 2oz, 70u", file=sys.stderr)
  sys.exit(1)

# =============================================================================
# Configuration Calculation
# =============================================================================

def calculateConfiguration(coreOd, coreId, axialHeight, turns, amps,
                           layers, copperThickness, fpcThickness,
                           bendRadius, slitEndDiameter, mount):
  """
  Calculate all geometric parameters for the FPC design.

  Returns a dict with all calculated values, or None if design is impossible.
  """
  # Calculate bend radius if not specified
  if bendRadius is None:
    bendRadius = BEND_RADIUS_K * (fpcThickness + copperThickness)

  # Core geometry
  radialThickness = (coreOd - coreId) / 2.0

  # Check if bend radius fits within radial thickness
  if bendRadius > radialThickness * 0.8:
    print(f"Warning: Bend radius {bendRadius:.2f}mm is large relative to "
          f"radial thickness {radialThickness:.2f}mm", file=sys.stderr)

  # ID circumference determines the pitch
  idCircumference = coreId * math.pi
  pitch = idCircumference / turns

  # OD circumference for fan-out calculation
  odCircumference = coreOd * math.pi
  odPitch = odCircumference / turns

  # Calculate zone/trace geometry
  # With copper zones, we fill maximum area and only need minimum gap between zones
  # Scale for copper thickness relative to 1oz (thicker copper = more capacity)
  copperScale = copperThickness / COPPER_THICKNESS["1oz"]

  # Gap between traces must accommodate petal slit lines with edge clearance
  # Slit geometry: lines run between traces at trace angle
  # Required: slit_line_width/2 + edge_clearance on each side of centerline
  # Edge clearance is typically 0.2mm, slit line width is 0.1mm
  # So gap >= 0.1mm (slit) + 2*0.2mm (edge clearance) = 0.5mm
  SLIT_LINE_WIDTH_MM = 0.1
  EDGE_CLEARANCE_MM = 0.2
  slitGapRequired = SLIT_LINE_WIDTH_MM + 2 * EDGE_CLEARANCE_MM
  gap = max(MIN_GAP_MM, slitGapRequired)  # 0.5mm minimum for edge clearance

  # Zone width at narrowest point (ID) = pitch - gap
  zoneWidthAtID = pitch - gap

  # Check if design is feasible
  if zoneWidthAtID < MIN_TRACE_WIDTH_MM:
    print(f"Error: Zone width at ID {zoneWidthAtID:.3f}mm is below "
          f"minimum {MIN_TRACE_WIDTH_MM}mm", file=sys.stderr)
    print(f"  (pitch={pitch:.3f}mm, gap={gap:.3f}mm)", file=sys.stderr)
    return None

  # For compatibility, store as traceWidth (zone width at narrowest point)
  traceWidth = zoneWidthAtID

  # Calculate required width for current capacity
  # Formula: width = amps * mm_per_amp / layers / copper_scale
  # Both layers carry current in parallel, thicker copper carries more
  requiredWidth = amps * MM_PER_AMP_1OZ / (layers * copperScale)

  # Check if current requirement can be met
  if requiredWidth > zoneWidthAtID:
    if ALLOW_UNDERCURRENT:
      print(f"Warning: Requested {amps}A requires {requiredWidth:.3f}mm width,", file=sys.stderr)
      print(f"  but zone width at ID is {zoneWidthAtID:.3f}mm. Design will proceed.", file=sys.stderr)
    else:
      print(f"Error: Required width {requiredWidth:.3f}mm exceeds "
            f"zone width {zoneWidthAtID:.3f}mm at ID", file=sys.stderr)
      return None

  # Calculate current capacity achieved at narrowest point
  # capacity = width / mm_per_amp * layers * copper_scale
  currentCapacity = zoneWidthAtID / MM_PER_AMP_1OZ * layers * copperScale

  # Via count for 2-layer parallel connection
  viasNeeded = 0
  if layers == 2:
    viasNeeded = max(2, math.ceil(amps / AMPS_PER_VIA))

  # FPC dimensions (unfolded)
  #
  # The FPC wraps around the UPPER LIMB cross-section of the toroid.
  # Cutting the toroid along its axis reveals a rectangular cross-section:
  #   - Width (axial direction): axialHeight = 14mm for T200
  #   - Height (radial direction): radialThickness = 9.525mm for T200
  #
  # The wrap path goes around this rectangle:
  #   1. OD surface (top of rectangle) - where A and B pads overlap
  #   2. Left flat face (left side of rectangle) - radialThickness
  #   3. ID surface (bottom of rectangle, through the bore) - axialHeight
  #   4. Right flat face (right side of rectangle) - radialThickness
  #   5. Back to OD surface - where B-pad overlaps next turn's A-pad
  #
  # The A-pad and B-pad regions sit on the OD surface (top of the rectangle).
  # They must overlap precisely when wrapped, spanning the axialHeight (14mm).
  # The overlap zone = radialThickness / 2 (pad size for proper overlap).
  # Distance from bend to pad = (axialHeight - padOverlapSize) / 2
  #
  # Layout (Y increasing from A-edge to B-edge):
  #   Y=0:                    A-edge of FPC
  #   Y=odSection:            OD fold A (transition to left flat face)
  #   Y=odSection+bend:       Start of flat face 1
  #   Y=odSection+bend+radial:              ID fold 1
  #   Y=odSection+2*bend+radial:            Start of ID section
  #   Y=odSection+2*bend+radial+axial:      ID fold 2
  #   Y=odSection+3*bend+radial+axial:      Start of flat face 2
  #   Y=odSection+3*bend+2*radial+axial:    OD fold B
  #   Y=fpcHeight:            B-edge of FPC

  # Bend allowance for each 90° fold at the toroid corners
  # Arc length = π × radius / 2 for a quarter circle
  bendAllowance = math.pi * FOLD_RADIUS_MM / 2.0

  # OD section geometry:
  # The OD surface spans axialHeight (14mm for T200) from bend #1 to bend #4.
  # A-pad and B-pad sit on this surface and must overlap when wrapped.
  # Layout on OD surface (from bend #1 toward center, and bend #4 toward center):
  #   - Trace from bend to pad: (axialHeight - padOverlapSize) / 2
  #   - Pad overlap zone: padOverlapSize = radialThickness / 2
  #   - Trace from pad to other bend: (axialHeight - padOverlapSize) / 2
  # Total = axialHeight, with pads overlapping in the middle.
  #
  # On UNFOLDED FPC, each OD section (from FPC edge to bend) includes:
  #   - Edge clearance
  #   - Pad (padOverlapSize)
  #   - Trace from pad to bend (where vias should go)
  padOverlapSize = radialThickness / 2.0
  traceToBend = (axialHeight - padOverlapSize) / 2.0
  odSection = EDGE_TO_COPPER_MM + padOverlapSize + traceToBend

  # Total FPC height = 2 OD sections + 2 flat faces + ID section + 4 bend allowances
  fpcHeight = (2 * odSection +
               2 * radialThickness +
               axialHeight +
               4 * bendAllowance)

  # Width = span of all traces + edge clearance on each side
  # The parallelogram has the same width at A-edge and B-edge (it's a true parallelogram)
  # For N turns: A0 to BN-1 spans N pitches (A0 at 0.5*pitch, BN-1 at (N+0.5)*pitch - but helix offset shifts B-edge)
  # At A-edge: traces span from A0 (0.5*pitch) to A(N-1) ((N-0.5)*pitch) = (N-1) pitches
  # At B-edge: traces span from B0 (1.5*pitch) to B(N-1) ((N+0.5)*pitch) = (N-1) pitches
  # Board width at A-edge: from (A0 - half_trace - clearance) to (A(N-1) + half_trace + clearance)
  # But we now have turn N-1's trace going to B(N-1), so we need room for B(N-1) as well
  # Width at A-edge: from 0 to B(N-1)'s A-edge projection + half_trace + clearance
  # Actually simpler: N turns = N traces, each trace spans 1 pitch, so total span = N pitches
  traceHalfWidth = traceWidth / 2.0
  leftMargin = EDGE_TO_COPPER_MM + traceHalfWidth  # edge_clearance + half_trace_width
  # Width needs to accommodate: A0 to B(N-1) which spans N pitches (from 0.5 to N+0.5)
  fpcWidth = turns * pitch + traceWidth + 2 * EDGE_TO_COPPER_MM

  # Fold line positions (Y coordinates on unfolded FPC)
  # There are 4 fold lines for wrapping around the toroid:
  # 1. foldOD_A: OD fold at A-edge (after OD section, before flat face 1)
  # 2. foldLine1Y: ID fold (after flat face 1, before ID bore)
  # 3. foldLine2Y: ID fold (after ID bore, before flat face 2)
  # 4. foldOD_B: OD fold at B-edge (after flat face 2, before OD section)
  #
  # Note: bend allowances are distributed around each fold point
  foldOD_A = odSection
  foldLine1Y = odSection + bendAllowance + radialThickness
  foldLine2Y = odSection + 2 * bendAllowance + radialThickness + axialHeight
  foldOD_B = odSection + 3 * bendAllowance + 2 * radialThickness + axialHeight

  # Slit positions - start at ID fold lines, extend toward pads to allow petals to spread
  # Keep slits from extending into the ID section
  slitLength = min(3.0, radialThickness * 0.5)  # 3mm or 50% of radial thickness

  # Fan-out ratio: how much wider traces get at OD vs ID
  fanRatio = odCircumference / idCircumference

  # Trace angle calculation
  # Each trace goes from A-pad center to B-pad center, with helix offset of one pitch
  # Y positions of pad centers:
  aEdgeY = EDGE_TO_COPPER_MM + padOverlapSize / 2.0
  bEdgeY = fpcHeight - EDGE_TO_COPPER_MM - padOverlapSize / 2.0
  # Delta for trace direction:
  traceHeight = bEdgeY - aEdgeY
  traceDeltaX = pitch  # Helix offset
  # Angle from vertical (degrees) - positive means trace leans right going down
  traceAngleDeg = math.degrees(math.atan2(traceDeltaX, traceHeight))

  return {
    # Core parameters
    "coreOd": coreOd,
    "coreId": coreId,
    "axialHeight": axialHeight,

    # User parameters
    "turns": turns,
    "amps": amps,
    "layers": layers,
    "mount": mount,

    # Material parameters
    "copperThickness": copperThickness,
    "fpcThickness": fpcThickness,
    "bendRadius": bendRadius,
    "slitEndDiameter": slitEndDiameter,

    # Calculated geometry
    "radialThickness": radialThickness,
    "idCircumference": idCircumference,
    "odCircumference": odCircumference,
    "pitch": pitch,
    "odPitch": odPitch,
    "traceWidth": traceWidth,
    "gap": gap,
    "fanRatio": fanRatio,

    # FPC dimensions
    "fpcWidth": fpcWidth,
    "fpcHeight": fpcHeight,
    "odSection": odSection,
    "padOverlapSize": padOverlapSize,
    "traceToBend": traceToBend,
    "bendAllowance": bendAllowance,
    "foldOD_A": foldOD_A,
    "foldLine1Y": foldLine1Y,
    "foldLine2Y": foldLine2Y,
    "foldOD_B": foldOD_B,
    "slitLength": slitLength,
    "leftMargin": leftMargin,
    "traceAngleDeg": traceAngleDeg,
    "traceHeight": traceHeight,

    # Electrical
    "currentCapacity": currentCapacity,
    "viasNeeded": viasNeeded,
  }

def printConfiguration(cfg):
  """Print all configuration parameters to stderr."""
  print("=" * 60, file=sys.stderr)
  print("TOROID-EASE FPC DESIGN", file=sys.stderr)
  print("=" * 60, file=sys.stderr)

  print("\nCore Dimensions:", file=sys.stderr)
  print(f"  OD:           {cfg['coreOd']:.2f} mm", file=sys.stderr)
  print(f"  ID:           {cfg['coreId']:.2f} mm", file=sys.stderr)
  print(f"  Axial Height: {cfg['axialHeight']:.2f} mm", file=sys.stderr)
  print(f"  Radial:       {cfg['radialThickness']:.2f} mm", file=sys.stderr)

  print("\nDesign Parameters:", file=sys.stderr)
  print(f"  Turns:        {cfg['turns']}", file=sys.stderr)
  print(f"  Current:      {cfg['amps']:.2f} A (requested)", file=sys.stderr)
  print(f"  Layers:       {cfg['layers']}", file=sys.stderr)
  print(f"  Mount:        {cfg['mount']}", file=sys.stderr)

  print("\nMaterial:", file=sys.stderr)
  print(f"  Copper:       {cfg['copperThickness']*1000:.1f} um", file=sys.stderr)
  print(f"  FPC Base:     {cfg['fpcThickness']:.2f} mm", file=sys.stderr)
  print(f"  Bend Radius:  {cfg['bendRadius']:.2f} mm", file=sys.stderr)

  print("\nCalculated Trace Geometry:", file=sys.stderr)
  print(f"  Pitch at ID:  {cfg['pitch']:.3f} mm", file=sys.stderr)
  print(f"  Pitch at OD:  {cfg['odPitch']:.3f} mm", file=sys.stderr)
  print(f"  Trace Width:  {cfg['traceWidth']:.3f} mm", file=sys.stderr)
  print(f"  Gap:          {cfg['gap']:.3f} mm", file=sys.stderr)
  print(f"  Fan Ratio:    {cfg['fanRatio']:.2f}x", file=sys.stderr)

  print("\nFPC Dimensions (unfolded parallelogram):", file=sys.stderr)
  print(f"  Width:        {cfg['fpcWidth']:.2f} mm", file=sys.stderr)
  print(f"  Height:       {cfg['fpcHeight']:.2f} mm", file=sys.stderr)
  print(f"  Helix Skew:   {cfg['pitch']:.2f} mm (B-edge shifted right)", file=sys.stderr)

  print("\nOD Section Layout (each end):", file=sys.stderr)
  print(f"  Total:        {cfg['odSection']:.2f} mm", file=sys.stderr)
  print(f"    Edge clear: {EDGE_TO_COPPER_MM:.2f} mm", file=sys.stderr)
  print(f"    Pad:        {cfg['padOverlapSize']:.2f} mm (overlap zone)", file=sys.stderr)
  print(f"    Trace:      {cfg['traceToBend']:.2f} mm (to bend, vias here)", file=sys.stderr)

  print("\nWrap Path:", file=sys.stderr)
  print(f"  Flat Face:    {cfg['radialThickness']:.2f} mm (each, radialThickness)", file=sys.stderr)
  print(f"  ID Section:   {cfg['axialHeight']:.2f} mm (axialHeight)", file=sys.stderr)
  print(f"  Bend Allow:   {cfg['bendAllowance']:.3f} mm (each of 4 folds)", file=sys.stderr)
  print(f"  Fold Radius:  {FOLD_RADIUS_MM:.2f} mm (toroid corner radius)", file=sys.stderr)

  print("\nFold Positions:", file=sys.stderr)
  print(f"  OD Fold A:    Y = {cfg['foldOD_A']:.2f} mm", file=sys.stderr)
  print(f"  ID Fold 1:    Y = {cfg['foldLine1Y']:.2f} mm", file=sys.stderr)
  print(f"  ID Fold 2:    Y = {cfg['foldLine2Y']:.2f} mm", file=sys.stderr)
  print(f"  OD Fold B:    Y = {cfg['foldOD_B']:.2f} mm", file=sys.stderr)

  print("\nElectrical:", file=sys.stderr)
  print(f"  Current Cap:  {cfg['currentCapacity']:.2f} A", file=sys.stderr)
  if cfg['layers'] == 2:
    print(f"  Vias/trace:   {cfg['viasNeeded']}", file=sys.stderr)

  print("\nSlit Geometry:", file=sys.stderr)
  print(f"  Slit Length:  {cfg['slitLength']:.2f} mm", file=sys.stderr)
  print(f"  Rip-stop Dia: {cfg['slitEndDiameter']:.2f} mm", file=sys.stderr)

  print("=" * 60, file=sys.stderr)

# =============================================================================
# Geometry Helpers
# =============================================================================

def toNm(mm):
  """Convert mm to nanometers (KiCad internal units)."""
  return int(mm * 1e6)

# Board origin offset (in mm) - used to position FPC on the KiCad page
_originX = 0.0
_originY = 0.0

def setOrigin(x, y):
  """Set the board origin offset in mm."""
  global _originX, _originY
  _originX = x
  _originY = y

def vec(x, y):
  """Create a KiCad VECTOR2I from mm coordinates, applying origin offset."""
  return pcbnew.VECTOR2I(toNm(x + _originX), toNm(y + _originY))

def addLine(board, start, end, layer, width=0.1):
  """Add a line segment to the board."""
  seg = pcbnew.PCB_SHAPE(board)
  seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
  seg.SetStart(start)
  seg.SetEnd(end)
  seg.SetLayer(layer)
  seg.SetWidth(toNm(width))
  board.Add(seg)
  return seg

def addArc(board, center, start, angle_deg, layer, width=0.1):
  """Add an arc to the board. Angle is in degrees, positive = CCW."""
  arc = pcbnew.PCB_SHAPE(board)
  arc.SetShape(pcbnew.SHAPE_T_ARC)
  arc.SetCenter(center)
  arc.SetStart(start)
  arc.SetArcAngleAndEnd(pcbnew.EDA_ANGLE(angle_deg, pcbnew.DEGREES_T))
  arc.SetLayer(layer)
  arc.SetWidth(toNm(width))
  board.Add(arc)
  return arc

def addCircle(board, center, radius, layer, width=0.1):
  """Add a circle to the board."""
  circle = pcbnew.PCB_SHAPE(board)
  circle.SetShape(pcbnew.SHAPE_T_CIRCLE)
  circle.SetCenter(center)
  circle.SetEnd(pcbnew.VECTOR2I(center.x + toNm(radius), center.y))
  circle.SetLayer(layer)
  circle.SetWidth(toNm(width))
  board.Add(circle)
  return circle

def addTrack(board, start, end, layer, width):
  """Add a copper track to the board."""
  track = pcbnew.PCB_TRACK(board)
  track.SetStart(start)
  track.SetEnd(end)
  track.SetLayer(layer)
  track.SetWidth(toNm(width))
  board.Add(track)
  return track

def addVia(board, pos, drill, size):
  """Add a through-hole via to the board."""
  via = pcbnew.PCB_VIA(board)
  via.SetPosition(pos)
  via.SetDrill(toNm(drill))
  via.SetWidth(toNm(size))
  via.SetViaType(pcbnew.VIATYPE_THROUGH)
  via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
  board.Add(via)
  return via

def addSmdPad(board, pos, name, width, height, layer, roundrect=True, angleDeg=0):
  """Add an SMD pad to the board via a footprint.

  Args:
    angleDeg: Rotation angle in degrees (0 = long axis vertical, 90 = horizontal)
  """
  fp = pcbnew.FOOTPRINT(board)
  fp.SetPosition(pos)
  fp.SetReference(f"PAD{name}")
  fp.SetValue(name)
  fp.Reference().SetVisible(False)
  fp.Value().SetVisible(False)

  pad = pcbnew.PAD(fp)
  pad.SetPosition(pos)
  pad.SetName(str(name))
  pad.SetNumber(str(name))
  pad.SetSize(pcbnew.VECTOR2I(toNm(width), toNm(height)))
  if roundrect:
    pad.SetShape(pcbnew.PAD_SHAPE_ROUNDRECT)
    pad.SetRoundRectRadiusRatio(SMD_PAD_ROUNDRECT_RATIO)
  else:
    pad.SetShape(pcbnew.PAD_SHAPE_RECT)
  pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
  lset = pcbnew.LSET()
  lset.AddLayer(layer)
  pad.SetLayerSet(lset)

  # Apply rotation if specified
  if angleDeg != 0:
    pad.SetOrientation(pcbnew.EDA_ANGLE(angleDeg, pcbnew.DEGREES_T))

  fp.Add(pad)
  board.Add(fp)
  return pad

def addText(board, pos, text, layer, height=1.0, thickness=0.15):
  """Add text to the board."""
  txt = pcbnew.PCB_TEXT(board)
  txt.SetText(text)
  txt.SetPosition(pos)
  txt.SetLayer(layer)
  txt.SetTextHeight(toNm(height))
  txt.SetTextThickness(toNm(thickness))
  txt.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
  txt.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
  board.Add(txt)
  return txt

# =============================================================================
# Board Setup and Design Rules
# =============================================================================

def applyJLCPCBRules(board):
  """
  Apply JLCPCB flex PCB design rules to the board.
  These rules are stored in the board file and enforced by DRC.
  """
  settings = board.GetDesignSettings()

  # Set board-level constraints (DRC minimums)
  settings.m_MinClearance = toNm(JLCPCB_RULES["clearance"])
  settings.m_TrackMinWidth = toNm(JLCPCB_RULES["track_width"])
  settings.m_ViasMinSize = toNm(JLCPCB_RULES["via_diameter"])
  settings.m_MinThroughDrill = toNm(JLCPCB_RULES["via_drill"])
  settings.m_ViasMinAnnularWidth = toNm(JLCPCB_RULES["annular_ring"])
  settings.m_HoleClearance = toNm(JLCPCB_RULES["hole_to_hole"])
  settings.m_CopperEdgeClearance = toNm(JLCPCB_RULES["edge_clearance"])
  settings.m_SilkClearance = toNm(JLCPCB_RULES["silk_clearance"])

  # Also set default netclass clearance to match JLCPCB rules
  # This prevents netclass 'Default' from overriding with larger clearance
  try:
    netSettings = settings.m_NetSettings
    defaultNetclass = netSettings.GetDefaultNetclass()
    defaultNetclass.SetClearance(toNm(JLCPCB_RULES["clearance"]))
    defaultNetclass.SetTrackWidth(toNm(JLCPCB_RULES["track_width"]))
  except Exception as e:
    print(f"Note: Could not set netclass defaults: {e}", file=sys.stderr)

def setLayerColors(board):
  """Set custom layer colors for better visibility."""
  # Note: Layer colors are typically set in the project file, not the board.
  # This function is a placeholder for when color customization is needed.
  # User.1 should be bright blue - this is handled in KiCad settings.
  pass

# =============================================================================
# Edge Cuts Generation
# =============================================================================

def generateEdgeCuts(board, cfg):
  """
  Generate board outline as Edge.Cuts layer with sawtooth edges and petal separators.

  Creates independent petals for each winding, connected only at the ID section.
  Each petal separator has:
  - A 180° arc centered ON the fold line (bend #2 or #3), opening away from midline
  - Two lines extending from arc ends at the trace angle toward the edge
  - A horizontal closing line at the edge (just past the pad area)
  """
  layer = pcbnew.Edge_Cuts
  width = 0.05  # Edge cut line width (minimum for visibility)

  fpcHeight = cfg["fpcHeight"]
  turns = cfg["turns"]
  pitch = cfg["pitch"]
  traceWidth = cfg["traceWidth"]
  gap = cfg["gap"]
  foldLine1Y = cfg["foldLine1Y"]  # Bend #2
  foldLine2Y = cfg["foldLine2Y"]  # Bend #3
  foldOD_A = cfg["foldOD_A"]      # Bend #1
  foldOD_B = cfg["foldOD_B"]      # Bend #4
  mount = cfg["mount"]
  leftMargin = cfg.get("leftMargin", 0)
  traceAngleDeg = cfg.get("traceAngleDeg", 0)

  # Flap dimensions - just enough for pad + small margin
  flapLength = 5.0
  maxPadWidth = pitch - gap
  padWidth = min(maxPadWidth, max(SMD_PAD_WIDTH_MM, traceWidth))
  # Flap width must be wider than trace to provide edge clearance
  flapWidth = traceWidth + 2 * EDGE_TO_COPPER_MM  # trace + clearance on each side

  # Ripstop radius (arc radius at fold line)
  ripstopRadius = RIPSTOP_DIAMETER_MM / 2.0

  # Helix offset for parallelogram shape
  helixOffset = pitch
  cfg["helixOffset"] = helixOffset

  # Board width at A-edge (top) - minimal, just enough for traces with edge clearance
  # Last trace A-edge center is at leftMargin + (turns - 0.5) * pitch
  # Right edge needs traceWidth/2 + edge clearance beyond that
  boardWidth = leftMargin + (turns - 0.5) * pitch + traceWidth/2 + EDGE_TO_COPPER_MM
  cfg["boardWidth"] = boardWidth

  # Calculate petal boundary X position at any Y (follows trace angle)
  padOverlapSize = cfg.get("padOverlapSize", SMD_PAD_HEIGHT_MM)
  aEdgeY = EDGE_TO_COPPER_MM + padOverlapSize / 2.0
  bEdgeY = fpcHeight - EDGE_TO_COPPER_MM - padOverlapSize / 2.0
  traceHeight = bEdgeY - aEdgeY

  # Trace angle tangent (dx/dy ratio)
  traceSlope = pitch / traceHeight if traceHeight > 0 else 0

  def boundaryX(petalIdx, y):
    """Calculate X position of boundary between petals at Y."""
    baseX = leftMargin + petalIdx * pitch
    if traceHeight > 0:
      frac = (y - aEdgeY) / traceHeight
      return baseX + pitch * frac
    return baseX

  # Y positions where slits meet the edge (just past pad area)
  padHeight = padOverlapSize
  slitEndY_A = EDGE_TO_COPPER_MM + padHeight + 0.3  # Just past A-pad
  slitEndY_B = fpcHeight - EDGE_TO_COPPER_MM - padHeight - 0.3  # Just past B-pad

  # Main outline: left edge, A-edge with sawtooth, right edge, B-edge with sawtooth
  startFlapX = leftMargin + pitch / 2.0
  endFlapX = leftMargin + (turns - 1 + 1.5) * pitch

  # Build outline by tracing around all petals
  # The slits create a sawtooth pattern at the A and B edges

  if mount == "flat":
    # Left edge (from bottom to top)
    addLine(board, vec(helixOffset, fpcHeight), vec(0, 0), layer, width)

    # A-edge with START flap and sawtooth pattern
    addLine(board, vec(0, 0), vec(startFlapX - flapWidth/2, 0), layer, width)
    addLine(board, vec(startFlapX - flapWidth/2, 0), vec(startFlapX - flapWidth/2, -flapLength), layer, width)
    addLine(board, vec(startFlapX - flapWidth/2, -flapLength), vec(startFlapX + flapWidth/2, -flapLength), layer, width)
    addLine(board, vec(startFlapX + flapWidth/2, -flapLength), vec(startFlapX + flapWidth/2, 0), layer, width)
    addLine(board, vec(startFlapX + flapWidth/2, 0), vec(boardWidth, 0), layer, width)

    # Right edge (from top to bottom)
    addLine(board, vec(boardWidth, 0), vec(boardWidth + helixOffset, fpcHeight), layer, width)

    # B-edge with END flap
    addLine(board, vec(boardWidth + helixOffset, fpcHeight), vec(endFlapX + flapWidth/2, fpcHeight), layer, width)
    addLine(board, vec(endFlapX + flapWidth/2, fpcHeight), vec(endFlapX + flapWidth/2, fpcHeight + flapLength), layer, width)
    addLine(board, vec(endFlapX + flapWidth/2, fpcHeight + flapLength), vec(endFlapX - flapWidth/2, fpcHeight + flapLength), layer, width)
    addLine(board, vec(endFlapX - flapWidth/2, fpcHeight + flapLength), vec(endFlapX - flapWidth/2, fpcHeight), layer, width)
    addLine(board, vec(endFlapX - flapWidth/2, fpcHeight), vec(helixOffset, fpcHeight), layer, width)

  else:  # rolling mount - START on A-edge, END on B-edge
    # V-shaped slits instead of arcs - two lines meeting at the fold line
    # This fits in the gap without requiring arc clearance

    # Pre-calculate boundary 1 slot position (between START/A0 and A1)
    # START flap will extend from board edge to this slot
    edgeClearance = 0.2
    halfSlotWidth = max(0.025, gap/2 - edgeClearance - width/2)

    vPointX_1 = boundaryX(1, foldLine1Y)
    deltaY_1 = foldLine1Y
    deltaX_1 = deltaY_1 * traceSlope
    centerAtEdge_1 = vPointX_1 - deltaX_1  # Boundary 1 at A-edge
    slot1_leftEdge = centerAtEdge_1 - halfSlotWidth
    slot1_rightEdge = centerAtEdge_1 + halfSlotWidth
    slot1_leftVpoint = vPointX_1 - halfSlotWidth
    slot1_rightVpoint = vPointX_1 + halfSlotWidth

    # START flap: trace aligned with turn 0's A-edge position, flap provides edge clearance
    # Turn 0's A-edge is at leftMargin + 0.5*pitch
    turn0_X = leftMargin + 0.5 * pitch
    startFlapLeftX = turn0_X - traceWidth/2 - EDGE_TO_COPPER_MM  # Just enough for edge clearance
    startFlapRightX = slot1_leftEdge  # Flap right edge meets slot left edge
    startFlapWidth = startFlapRightX - startFlapLeftX
    cfg["startFlapLeftX"] = startFlapLeftX
    cfg["startFlapRightX"] = startFlapRightX
    cfg["startFlapWidth"] = startFlapWidth
    cfg["startFlapCenterX"] = turn0_X  # Trace at turn 0's actual position

    # Left edge (diagonal for parallelogram) - starts at startFlapLeftX, not 0
    leftEdgeBottomX = startFlapLeftX + helixOffset  # B-edge left corner
    addLine(board, vec(leftEdgeBottomX, fpcHeight), vec(startFlapLeftX, 0), layer, width)

    # A-edge with integrated petal cutouts (V-shaped sawtooth pattern)
    # START flap extends from startFlapLeftX to slot1_leftEdge, with flap extending downward
    addLine(board, vec(startFlapLeftX, 0), vec(startFlapLeftX, -flapLength), layer, width)  # Left edge of flap
    addLine(board, vec(startFlapLeftX, -flapLength), vec(startFlapRightX, -flapLength), layer, width)  # Bottom of flap
    addLine(board, vec(startFlapRightX, -flapLength), vec(slot1_leftEdge, 0), layer, width)  # Right edge to A-edge

    # Boundary 1 slot V-shape (between START/A0 and A1)
    addLine(board, vec(slot1_leftEdge, 0), vec(slot1_leftVpoint, foldLine1Y), layer, width)
    addLine(board, vec(slot1_leftVpoint, foldLine1Y), vec(slot1_rightVpoint, foldLine1Y), layer, width)
    addLine(board, vec(slot1_rightVpoint, foldLine1Y), vec(slot1_rightEdge, 0), layer, width)
    currentX = slot1_rightEdge

    for i in range(2, turns - 1):
      # Boundary between petals at fold line
      vPointX = boundaryX(i, foldLine1Y)
      vPointY = foldLine1Y

      # Gap at A-edge (Y=0), centered on projected boundary
      deltaY = foldLine1Y
      deltaX = deltaY * traceSlope
      centerAtEdge = vPointX - deltaX

      # Slot width: need edge clearance (0.2mm) on each side of slot within gap
      # slot_half_width = gap/2 - edge_clearance - line_half_width
      edgeClearance = 0.2
      halfSlotWidth = max(0.025, gap/2 - edgeClearance - width/2)
      leftEdgeX = centerAtEdge - halfSlotWidth
      rightEdgeX = centerAtEdge + halfSlotWidth

      # Slit legs go parallel to traces (at traceSlope)
      leftVpointX = vPointX - halfSlotWidth
      rightVpointX = vPointX + halfSlotWidth

      # Line along A-edge to left slit start
      addLine(board, vec(currentX, 0), vec(leftEdgeX, 0), layer, width)
      # Left slit line going down (parallel to trace)
      addLine(board, vec(leftEdgeX, 0), vec(leftVpointX, vPointY), layer, width)
      # Horizontal line connecting the two legs at fold line
      addLine(board, vec(leftVpointX, vPointY), vec(rightVpointX, vPointY), layer, width)
      # Right slit line going back up (parallel to trace)
      addLine(board, vec(rightVpointX, vPointY), vec(rightEdgeX, 0), layer, width)
      currentX = rightEdgeX

    # Pre-calculate last boundary slot position on A-edge (between A50 and END/A51)
    vPointX_lastA = boundaryX(turns - 1, foldLine1Y)
    deltaY_lastA = foldLine1Y
    deltaX_lastA = deltaY_lastA * traceSlope
    centerAtEdge_lastA = vPointX_lastA - deltaX_lastA  # Last boundary at A-edge
    slotLastA_leftEdge = centerAtEdge_lastA - halfSlotWidth
    slotLastA_rightEdge = centerAtEdge_lastA + halfSlotWidth
    slotLastA_leftVpoint = vPointX_lastA - halfSlotWidth
    slotLastA_rightVpoint = vPointX_lastA + halfSlotWidth

    # END flap on A-edge: trace aligned with turn 51's A-edge position
    # Turn 51's A-edge is at leftMargin + (turns - 1 + 0.5) * pitch = leftMargin + (turns - 0.5) * pitch
    # But turn 51's B-edge (B51) is one pitch further right
    turn51_A_X = leftMargin + (turns - 0.5) * pitch
    turn51_B_X = leftMargin + (turns + 0.5) * pitch  # B51 position

    endFlapLeftX = slotLastA_rightEdge  # Flap left edge meets slot right edge
    endFlapRightX = turn51_A_X + traceWidth/2 + EDGE_TO_COPPER_MM  # END flap right edge
    endFlapWidth = endFlapRightX - endFlapLeftX
    cfg["endFlapLeftX"] = endFlapLeftX
    cfg["endFlapRightX"] = endFlapRightX
    cfg["endFlapWidth"] = endFlapWidth
    cfg["endFlapCenterX"] = turn51_A_X  # Trace at turn 51's actual A-edge position

    # Board right edge extends to B51 (turn 51's B-edge), not just END flap
    boardRightEdgeX = turn51_B_X + traceWidth/2 + EDGE_TO_COPPER_MM

    # Slot at last A-edge boundary (between A50 and END/A51)
    addLine(board, vec(currentX, 0), vec(slotLastA_leftEdge, 0), layer, width)
    addLine(board, vec(slotLastA_leftEdge, 0), vec(slotLastA_leftVpoint, foldLine1Y), layer, width)
    addLine(board, vec(slotLastA_leftVpoint, foldLine1Y), vec(slotLastA_rightVpoint, foldLine1Y), layer, width)
    addLine(board, vec(slotLastA_rightVpoint, foldLine1Y), vec(slotLastA_rightEdge, 0), layer, width)

    # END flap on A-edge (extends upward like START) - open shape, not closed loop
    addLine(board, vec(slotLastA_rightEdge, 0), vec(slotLastA_rightEdge, -flapLength), layer, width)  # Left edge up
    addLine(board, vec(slotLastA_rightEdge, -flapLength), vec(endFlapRightX, -flapLength), layer, width)  # Top of flap
    addLine(board, vec(endFlapRightX, -flapLength), vec(endFlapRightX, 0), layer, width)  # Right edge down

    # A-edge continues from END flap to board right edge (for turn 51 trace area)
    addLine(board, vec(endFlapRightX, 0), vec(boardRightEdgeX, 0), layer, width)

    # Right edge - diagonal like left edge (parallelogram shape)
    # Goes from A-edge to B-edge with helix offset
    rightEdgeTopX = boardRightEdgeX
    rightEdgeBottomX = boardRightEdgeX + helixOffset
    addLine(board, vec(rightEdgeTopX, 0), vec(rightEdgeBottomX, fpcHeight), layer, width)

    # B-edge with boundary slots including B51
    currentX = rightEdgeBottomX

    # B-edge slots from turns-1 down to 1 (include boundary 51 for B50/B51)
    for i in range(turns - 1, 0, -1):
      # Boundary between petals at fold line
      vPointX = boundaryX(i, foldLine2Y)
      vPointY = foldLine2Y

      # Gap at B-edge (Y=fpcHeight), centered on projected boundary
      deltaY = fpcHeight - foldLine2Y
      deltaX = deltaY * traceSlope
      centerAtEdge = vPointX + deltaX

      # Slot width: need edge clearance (0.2mm) on each side of slot within gap
      # slot_half_width = gap/2 - edge_clearance - line_half_width
      edgeClearance = 0.2
      halfSlotWidth = max(0.025, gap/2 - edgeClearance - width/2)
      leftEdgeX = centerAtEdge - halfSlotWidth
      rightEdgeX = centerAtEdge + halfSlotWidth

      # Slit legs go parallel to traces
      leftVpointX = vPointX - halfSlotWidth
      rightVpointX = vPointX + halfSlotWidth

      # Line along B-edge to right slit start
      addLine(board, vec(currentX, fpcHeight), vec(rightEdgeX, fpcHeight), layer, width)
      # Right slit line going up (parallel to trace)
      addLine(board, vec(rightEdgeX, fpcHeight), vec(rightVpointX, vPointY), layer, width)
      # Horizontal line connecting the two legs at fold line
      addLine(board, vec(rightVpointX, vPointY), vec(leftVpointX, vPointY), layer, width)
      # Left slit line going back down (parallel to trace)
      addLine(board, vec(leftVpointX, vPointY), vec(leftEdgeX, fpcHeight), layer, width)
      currentX = leftEdgeX

    # Finish B-edge to left corner (must match the left edge starting point)
    addLine(board, vec(currentX, fpcHeight), vec(leftEdgeBottomX, fpcHeight), layer, width)

def generatePetalSlitWithArc(board, arcCenterX, arcCenterY, edgeY, arcRadius, traceSlope, layer, width, openUpward=True):
  """
  Generate a petal separator slit with arc at fold line extending to edge.

  Geometry:
  - 180° arc centered at (arcCenterX, arcCenterY) on the fold line
  - Arc opens away from FPC midline (upward for A-side, downward for B-side)
  - Two lines extend from arc endpoints at trace angle toward edgeY
  - Horizontal line at edgeY connects the two lines, closing the slit

  Args:
    arcCenterX, arcCenterY: Center of the arc (on the fold line)
    edgeY: Y position where slit meets the edge (just past pad area)
    arcRadius: Radius of the semicircular arc (ripstop)
    traceSlope: dx/dy ratio for trace angle
    openUpward: True if arc opens toward smaller Y (A-side), False for B-side
  """
  import math

  # Arc endpoints (left and right of center)
  arcLeftX = arcCenterX - arcRadius
  arcRightX = arcCenterX + arcRadius

  # Distance from arc to edge
  deltaY = arcCenterY - edgeY if openUpward else edgeY - arcCenterY
  if deltaY <= 0:
    return  # Edge is past the arc, nothing to draw

  # X offset for trace angle
  deltaX = deltaY * traceSlope

  # Line endpoints at the edge (following trace angle from arc endpoints)
  if openUpward:
    # Lines go from arc upward to edgeY
    leftLineEndX = arcLeftX - deltaX
    rightLineEndX = arcRightX - deltaX
    leftLineEndY = edgeY
    rightLineEndY = edgeY

    # Draw closed slit:
    # 1. Left line from edge to arc
    addLine(board, vec(leftLineEndX, edgeY), vec(arcLeftX, arcCenterY), layer, width)
    # 2. Arc from left to right, going through bottom (opening toward ID section)
    addArc(board, vec(arcCenterX, arcCenterY), vec(arcLeftX, arcCenterY), 180, layer, width)
    # 3. Right line from arc to edge
    addLine(board, vec(arcRightX, arcCenterY), vec(rightLineEndX, edgeY), layer, width)
    # 4. Horizontal line at edge to close
    addLine(board, vec(rightLineEndX, edgeY), vec(leftLineEndX, edgeY), layer, width)
  else:
    # Lines go from arc downward to edgeY
    leftLineEndX = arcLeftX + deltaX
    rightLineEndX = arcRightX + deltaX
    leftLineEndY = edgeY
    rightLineEndY = edgeY

    # Draw closed slit:
    # 1. Left line from edge to arc
    addLine(board, vec(leftLineEndX, edgeY), vec(arcLeftX, arcCenterY), layer, width)
    # 2. Arc from left to right, going through top (opening toward ID section)
    addArc(board, vec(arcCenterX, arcCenterY), vec(arcLeftX, arcCenterY), -180, layer, width)
    # 3. Right line from arc to edge
    addLine(board, vec(arcRightX, arcCenterY), vec(rightLineEndX, edgeY), layer, width)
    # 4. Horizontal line at edge to close
    addLine(board, vec(rightLineEndX, edgeY), vec(leftLineEndX, edgeY), layer, width)

def generateClosedSlot(board, x1, y1, x2, y2, slotWidth, ripstopRadius, layer, width):
  """
  Generate a closed slot shape (internal cutout) for petal separation.

  The slot is a rectangle with semicircular ends, forming a closed shape.
  This creates an internal routing channel in the FPC.

  Args:
    x1, y1: Center of one end of the slot
    x2, y2: Center of the other end of the slot
    slotWidth: Width of the rectangular portion
    ripstopRadius: Radius of the semicircular ends
    layer: Edge.Cuts layer
    width: Line width for drawing
  """
  import math

  # Calculate slot direction
  dx = x2 - x1
  dy = y2 - y1
  length = math.sqrt(dx*dx + dy*dy)
  if length == 0:
    return

  # Unit vector along slot
  ux = dx / length
  uy = dy / length

  # Perpendicular unit vector
  px = -uy
  py = ux

  # Half-widths
  halfSlot = slotWidth / 2.0

  # Four corners of the rectangular portion
  # Using slot width for the parallel edges, ripstop radius for the ends
  corner1 = (x1 + px * halfSlot, y1 + py * halfSlot)  # Start, left side
  corner2 = (x2 + px * halfSlot, y2 + py * halfSlot)  # End, left side
  corner3 = (x2 - px * halfSlot, y2 - py * halfSlot)  # End, right side
  corner4 = (x1 - px * halfSlot, y1 - py * halfSlot)  # Start, right side

  # Draw closed slot: left edge, end arc, right edge, start arc
  # Left edge
  addLine(board, vec(corner1[0], corner1[1]), vec(corner2[0], corner2[1]), layer, width)

  # End arc (semicircle at end point)
  addArc(board, vec(x2, y2), vec(corner2[0], corner2[1]), -180, layer, width)

  # Right edge
  addLine(board, vec(corner3[0], corner3[1]), vec(corner4[0], corner4[1]), layer, width)

  # Start arc (semicircle at start point)
  addArc(board, vec(x1, y1), vec(corner4[0], corner4[1]), -180, layer, width)

def generatePetalSeparator(board, x1, y1, x2, y2, ripstopRadius, layer, width, goingDown=True):
  """
  DEPRECATED - Use generateClosedSlot instead.
  Generate a petal separator as a closed slot shape from board edge to fold line.

  The separator is a narrow slot that extends from the board edge to the fold line,
  with a semicircular ripstop at the fold end to prevent tearing.

  Args:
    x1, y1: Start point (edge point for A-side, fold point for B-side)
    x2, y2: End point (fold point for A-side, edge point for B-side)
    ripstopRadius: Radius of the ripstop semicircle (also determines slot width)
    goingDown: True if going from smaller Y to larger Y
  """
  # Slot width = ripstop diameter
  slotHalfWidth = ripstopRadius

  # Determine which end has the ripstop (the fold line end)
  if y1 < y2:  # A-side: y1=0 (edge), y2=foldLine1Y (fold)
    edgeX, edgeY = x1, y1
    foldX, foldY = x2, y2
    arcOpensDown = True  # Arc opens toward ID section (larger Y)
  else:  # B-side: y1=foldLine2Y (fold), y2=fpcHeight (edge)
    foldX, foldY = x1, y1
    edgeX, edgeY = x2, y2
    arcOpensDown = False  # Arc opens toward ID section (smaller Y)

  # Calculate the angle of the slot (from edge to fold)
  import math
  dx = foldX - edgeX
  dy = foldY - edgeY
  length = math.sqrt(dx*dx + dy*dy)
  if length == 0:
    return

  # Perpendicular offset for slot width
  perpX = -dy / length * slotHalfWidth
  perpY = dx / length * slotHalfWidth

  # Create closed slot:
  # For A-side (edge at top, fold at bottom):
  # 1. Left edge of slot: from (edgeX-perp, edgeY) to (foldX-perp, foldY)
  # 2. Ripstop arc at fold (semicircle opening toward ID section)
  # 3. Right edge of slot: from (foldX+perp, foldY) to (edgeX+perp, edgeY)
  # The top of the slot is open (extends to board edge)

  leftEdgeTop = (edgeX + perpX, edgeY + perpY)
  leftEdgeFold = (foldX + perpX, foldY + perpY)
  rightEdgeFold = (foldX - perpX, foldY - perpY)
  rightEdgeTop = (edgeX - perpX, edgeY - perpY)

  if arcOpensDown:
    # A-side: slot from edge (Y=0) to fold, arc opens down
    addLine(board, vec(leftEdgeTop[0], leftEdgeTop[1]), vec(leftEdgeFold[0], leftEdgeFold[1]), layer, width)
    # Arc from left fold point to right fold point, going through bottom
    addArc(board, vec(foldX, foldY), vec(leftEdgeFold[0], leftEdgeFold[1]), -180, layer, width)
    addLine(board, vec(rightEdgeFold[0], rightEdgeFold[1]), vec(rightEdgeTop[0], rightEdgeTop[1]), layer, width)
  else:
    # B-side: slot from fold to edge (Y=fpcHeight), arc opens up
    addLine(board, vec(leftEdgeTop[0], leftEdgeTop[1]), vec(leftEdgeFold[0], leftEdgeFold[1]), layer, width)
    # Arc from right fold point to left fold point, going through top
    addArc(board, vec(foldX, foldY), vec(rightEdgeFold[0], rightEdgeFold[1]), -180, layer, width)
    addLine(board, vec(rightEdgeFold[0], rightEdgeFold[1]), vec(rightEdgeTop[0], rightEdgeTop[1]), layer, width)

# Legacy functions kept for reference but not used
def generateMainOutline(board, cfg, layer, width, flapLength, flapWidth):
  """
  Generate the main board outline as a skewed parallelogram.

  The FPC is a parallelogram, not a rectangle, because each trace's B-edge
  is shifted one pitch to the right relative to its A-edge (helix offset).
  This creates a skew where the bottom edge (B-edge at Y=fpcHeight) is
  shifted right by one pitch relative to the top edge (A-edge at Y=0).

  The skew angle matches the trace angle through the ID section.
  """
  fpcWidth = cfg["fpcWidth"]
  fpcHeight = cfg["fpcHeight"]
  turns = cfg["turns"]
  pitch = cfg["pitch"]
  mount = cfg["mount"]
  leftMargin = cfg.get("leftMargin", 0)

  # Helix offset: B-edge is shifted right by one pitch relative to A-edge
  helixOffset = pitch

  # Flap positions - include leftMargin
  # START flap is on A-edge (Y=0)
  startFlapX = leftMargin + pitch / 2.0

  # END flap at last trace's B-edge position (where the last trace ENDS)
  # Last trace (turn N-1) has B-edge at X = leftMargin + (N-1 + 1.5) * pitch = leftMargin + (N + 0.5) * pitch
  endFlapX = leftMargin + (turns - 1 + 1.5) * pitch

  # Board width for A-edge (top)
  # The A-edge needs to span from X=0 to the last trace's A-edge + margin
  boardWidthTop = leftMargin + (turns - 0.5) * pitch + flapWidth/2 + 1.0

  # Board width for B-edge (bottom) - shifted by helix offset
  # The B-edge is already shifted right, so we use the same width but add helixOffset to all X coords
  boardWidthBottom = boardWidthTop

  # For compatibility, store as boardWidth (at A-edge)
  boardWidth = boardWidthTop
  cfg["boardWidth"] = boardWidth
  cfg["helixOffset"] = helixOffset

  # Build outline points as parallelogram
  # A-edge (top, Y=0): from X=0 to X=boardWidth
  # B-edge (bottom, Y=H): from X=helixOffset to X=boardWidth+helixOffset
  points = []

  if mount == "rolling":
    # Flaps extend from B-edge (bottom, Y = fpcHeight)
    # Start at top-left, go clockwise
    points.append((0, 0))                                    # Top-left (A-edge)
    points.append((boardWidth, 0))                           # Top-right (A-edge)
    points.append((boardWidth + helixOffset, fpcHeight))     # Bottom-right (B-edge, shifted)
    # END flap on B-edge (shifted by helixOffset)
    endFlapXB = endFlapX  # endFlapX is already calculated for B-edge position
    points.append((endFlapXB + flapWidth/2, fpcHeight))      # To end flap right
    points.append((endFlapXB + flapWidth/2, fpcHeight + flapLength))  # End flap down
    points.append((endFlapXB - flapWidth/2, fpcHeight + flapLength))  # End flap bottom
    points.append((endFlapXB - flapWidth/2, fpcHeight))      # End flap left up
    # START flap on B-edge - shifted by helixOffset
    startFlapXB = startFlapX + helixOffset
    points.append((startFlapXB + flapWidth/2, fpcHeight))    # To start flap right
    points.append((startFlapXB + flapWidth/2, fpcHeight + flapLength))  # Start flap down
    points.append((startFlapXB - flapWidth/2, fpcHeight + flapLength))  # Start flap bottom
    points.append((startFlapXB - flapWidth/2, fpcHeight))    # Start flap left up
    points.append((helixOffset, fpcHeight))                  # Bottom-left (B-edge, shifted)

  else:  # flat mount
    # START flap extends from A-edge (top, Y = 0)
    # END flap extends from B-edge (bottom, Y = fpcHeight)
    # The outline is a parallelogram: B-edge shifted right by helixOffset
    # Start at bottom-left, go clockwise
    points.append((helixOffset, fpcHeight))                  # Bottom-left (B-edge, shifted)
    # END flap on B-edge
    points.append((endFlapX - flapWidth/2, fpcHeight))       # To end flap left
    points.append((endFlapX - flapWidth/2, fpcHeight + flapLength))  # End flap left down
    points.append((endFlapX + flapWidth/2, fpcHeight + flapLength))  # End flap bottom
    points.append((endFlapX + flapWidth/2, fpcHeight))       # End flap right up
    points.append((boardWidth + helixOffset, fpcHeight))     # Bottom-right (B-edge, shifted)
    points.append((boardWidth, 0))                           # Top-right (A-edge)
    # START flap on A-edge
    points.append((startFlapX + flapWidth/2, 0))             # To start flap right
    points.append((startFlapX + flapWidth/2, -flapLength))   # Start flap right up
    points.append((startFlapX - flapWidth/2, -flapLength))   # Start flap top
    points.append((startFlapX - flapWidth/2, 0))             # Start flap left down
    points.append((0, 0))                                    # Top-left (A-edge)

  # Create closed polygon using line segments
  for i in range(len(points)):
    p1 = points[i]
    p2 = points[(i + 1) % len(points)]  # Wrap around to close
    addLine(board, vec(p1[0], p1[1]), vec(p2[0], p2[1]), layer, width)

def generateRipstopWithSlitsAngled(board, foldX, foldY, edgeX, edgeY, ripstopRadius, layer, width):
  """
  Generate a circular rip-stop hole with two slits that follow the trace boundary angle.

  Creates a CLOSED shape consisting of:
  1. A 180° circular arc (rip-stop semicircle) at the fold line
  2. Two slits connecting the arc endpoints to a closing line near the board edge
  3. The slits follow the same angle as the trace boundary gap

  Args:
    foldX: X position of ripstop center at the fold line
    foldY: Y position of ripstop center (fold line Y)
    edgeX: X position of boundary at the board edge (follows helix angle)
    edgeY: Y position near the board edge (with gap from actual edge)
    ripstopRadius: Radius of the rip-stop circle
    layer: Edge.Cuts layer
    width: Line width for drawing
  """
  # Determine direction based on foldY vs edgeY
  goingUp = edgeY < foldY  # Slits go toward smaller Y (A-edge)

  # Arc endpoints are on the circle at foldY (left and right of center)
  arcLeftX = foldX - ripstopRadius
  arcRightX = foldX + ripstopRadius

  # Slit endpoints follow the boundary angle
  # The boundary moves from foldX at foldY to edgeX at edgeY
  # Offset the slit endpoints by ripstopRadius in the same direction as the arc endpoints
  leftEndX = edgeX - ripstopRadius
  rightEndX = edgeX + ripstopRadius

  if goingUp:
    # Slits go from fold line toward Y=edgeY (smaller Y, A-edge)
    # Arc opens toward larger Y (ID section) - goes through bottom of circle

    # Draw CLOSED path clockwise:
    # 1. Right slit: from near-edge up to arc right point
    addLine(board, vec(rightEndX, edgeY), vec(arcRightX, foldY), layer, width)

    # 2. Arc: from right point to left point, going through bottom (clockwise = -180°)
    addArc(board, vec(foldX, foldY), vec(arcRightX, foldY), -180, layer, width)

    # 3. Left slit: from arc left point down to near-edge
    addLine(board, vec(arcLeftX, foldY), vec(leftEndX, edgeY), layer, width)

    # 4. Closing line: across at the near-edge Y
    addLine(board, vec(leftEndX, edgeY), vec(rightEndX, edgeY), layer, width)

  else:
    # Slits go from fold line toward Y=edgeY (larger Y, B-edge)
    # Arc opens toward smaller Y (ID section) - goes through top of circle

    # Draw CLOSED path clockwise:
    # 1. Left slit: from near-edge up to arc left point
    addLine(board, vec(leftEndX, edgeY), vec(arcLeftX, foldY), layer, width)

    # 2. Arc: from left point to right point, going through top (clockwise = -180°)
    addArc(board, vec(foldX, foldY), vec(arcLeftX, foldY), -180, layer, width)

    # 3. Right slit: from arc right point down to near-edge
    addLine(board, vec(arcRightX, foldY), vec(rightEndX, edgeY), layer, width)

    # 4. Closing line: across at the near-edge Y
    addLine(board, vec(rightEndX, edgeY), vec(leftEndX, edgeY), layer, width)


def generateClosedSlit(board, cfg, x, yStart, length, layer, width):
  """
  Generate a single slit as a closed slot shape.

  The slot is a rectangle with semicircular ends, forming a closed shape.
  """
  slitWidth = SLIT_WIDTH_MM
  halfWidth = slitWidth / 2.0

  yEnd = yStart + length
  yDir = 1 if length > 0 else -1

  # For a closed slot shape:
  # - Two parallel lines (left and right edges)
  # - Two semicircular ends (at yStart and yEnd)

  # Left edge (from start semicircle to end semicircle)
  addLine(board, vec(x - halfWidth, yStart), vec(x - halfWidth, yEnd), layer, width)

  # Right edge (from end semicircle to start semicircle)
  addLine(board, vec(x + halfWidth, yEnd), vec(x + halfWidth, yStart), layer, width)

  # Semicircle at the end (rip-stop)
  arcCenterEnd = vec(x, yEnd)
  if yDir > 0:
    arcStartEnd = vec(x - halfWidth, yEnd)
    addArc(board, arcCenterEnd, arcStartEnd, -180, layer, width)
  else:
    arcStartEnd = vec(x + halfWidth, yEnd)
    addArc(board, arcCenterEnd, arcStartEnd, -180, layer, width)

  # Semicircle at the start (closes the slot at fold line)
  arcCenterStart = vec(x, yStart)
  if yDir > 0:
    arcStartStart = vec(x + halfWidth, yStart)
    addArc(board, arcCenterStart, arcStartStart, -180, layer, width)
  else:
    arcStartStart = vec(x - halfWidth, yStart)
    addArc(board, arcCenterStart, arcStartStart, -180, layer, width)

# =============================================================================
# Winding Trace Generation
# =============================================================================

def generateWindingTraces(board, cfg):
  """
  Generate copper traces for all windings.

  Each winding is a "hockey stick" shape:
  - Vertical section at ID (between fold lines)
  - Angled sections on flat faces (fanning out toward OD)
  - Pads at OD edges for lap joints
  """
  turns = cfg["turns"]
  layers = cfg["layers"]

  # Generate all traces (turns 0 to N-1)
  # START replaces A0 pad but turn 0 trace still exists (A0->B0)
  # END replaces A51 pad but turn 51 trace still exists (A51->B51)
  # This makes START and END identical in structure
  for turnIdx in range(turns):
    # Generate trace on F.Cu
    generateSingleTrace(board, cfg, turnIdx, pcbnew.F_Cu)

    # Generate trace on B.Cu if 2-layer
    if layers == 2:
      generateSingleTrace(board, cfg, turnIdx, pcbnew.B_Cu)
      # Generate vias to connect the two layers
      generateTraceVias(board, cfg, turnIdx)

def generateSingleTrace(board, cfg, turnIdx, layer):
  """
  Generate a single winding trace as connected track segments.

  CRITICAL for helix: B-pad of turn N must align with A-pad of turn N+1
  when the FPC wraps around the toroid. This means:
  - A-edge X position: (turnIdx + 0.5) * pitch
  - B-edge X position: (turnIdx + 1.5) * pitch (shifted by one pitch!)

  The trace path (from A-edge to B-edge):
  1. Start at A-pad position (Y near 0, OD)
  2. Angle through flat face 1 toward ID
  3. Straight through ID section (angled to create pitch offset)
  4. Angle through flat face 2 toward OD
  5. End at B-pad position (Y near fpcHeight, OD) - shifted by one pitch!
  """
  pitch = cfg["pitch"]
  traceWidth = cfg["traceWidth"]
  foldLine1Y = cfg["foldLine1Y"]
  foldLine2Y = cfg["foldLine2Y"]
  fpcHeight = cfg["fpcHeight"]
  turns = cfg["turns"]
  leftMargin = cfg.get("leftMargin", 0)

  # A-edge position (where this trace starts) - offset by leftMargin
  aEdgeX = leftMargin + (turnIdx + 0.5) * pitch

  # B-edge position (where this trace ends) - SHIFTED BY ONE PITCH for helix!
  # Last trace (turn 51) B-edge at leftMargin + 52.5*pitch, but END flap handles it
  bEdgeX = leftMargin + (turnIdx + 1.5) * pitch

  # Y coordinates - MUST match pad center positions exactly for DRC connection
  # Pad centers are at: padHeight/2 + EDGE_TO_COPPER_MM from edges
  padHeight = SMD_PAD_HEIGHT_MM
  aEdgeY = padHeight / 2.0 + EDGE_TO_COPPER_MM
  bEdgeY = fpcHeight - padHeight / 2.0 - EDGE_TO_COPPER_MM

  # The trace angles through the ID section to create the pitch offset
  # At fold lines, interpolate X position
  # Fold line 1 is at Y = foldLine1Y (top of ID section)
  # Fold line 2 is at Y = foldLine2Y (bottom of ID section)

  # Linear interpolation of X from A-edge to B-edge based on Y
  totalHeight = bEdgeY - aEdgeY
  fold1Frac = (foldLine1Y - aEdgeY) / totalHeight
  fold2Frac = (foldLine2Y - aEdgeY) / totalHeight

  fold1X = aEdgeX + (bEdgeX - aEdgeX) * fold1Frac
  fold2X = aEdgeX + (bEdgeX - aEdgeX) * fold2Frac

  # Draw the trace segments
  # A-edge to fold line 1 (flat face 1, angling toward ID)
  addTrack(board, vec(aEdgeX, aEdgeY), vec(fold1X, foldLine1Y), layer, traceWidth)

  # Fold line 1 to fold line 2 (ID section, continuing the angle)
  addTrack(board, vec(fold1X, foldLine1Y), vec(fold2X, foldLine2Y), layer, traceWidth)

  # Fold line 2 to B-edge (flat face 2, angling toward OD)
  addTrack(board, vec(fold2X, foldLine2Y), vec(bEdgeX, bEdgeY), layer, traceWidth)

def generateTraceVias(board, cfg, turnIdx):
  """
  Generate via array for a single trace to connect F.Cu and B.Cu.

  Vias are placed in the OD trace sections (between pad and bend), NOT on
  the flat faces. This positions them where they can do the most good for
  current sharing between layers, and away from the fold stress zones.

  A gap is maintained between the bend and the first via to reduce stress
  during installation and thermal cycling.
  """
  viasNeeded = cfg["viasNeeded"]
  if viasNeeded == 0:
    return

  turns = cfg["turns"]

  pitch = cfg["pitch"]
  fpcHeight = cfg["fpcHeight"]
  leftMargin = cfg.get("leftMargin", 0)
  foldOD_A = cfg["foldOD_A"]
  foldOD_B = cfg["foldOD_B"]
  padOverlapSize = cfg["padOverlapSize"]
  traceToBend = cfg["traceToBend"]

  # Trace endpoints (same calculation as generateSingleTrace)
  aEdgeX = leftMargin + (turnIdx + 0.5) * pitch
  bEdgeX = leftMargin + (turnIdx + 1.5) * pitch

  # Y coordinates for trace endpoints (pad centers)
  aEdgeY = EDGE_TO_COPPER_MM + padOverlapSize / 2.0
  bEdgeY = fpcHeight - EDGE_TO_COPPER_MM - padOverlapSize / 2.0

  # Total height for X interpolation
  totalHeight = bEdgeY - aEdgeY

  # Gap from bend to first via (reduces stress during folding)
  bendGap = 0.5  # mm from bend to nearest via

  # Via placement in OD trace sections:
  # A-side: from pad edge to (bend - gap)
  # B-side: from (bend + gap) to pad edge
  padEdgeA = EDGE_TO_COPPER_MM + padOverlapSize
  viaStartA = padEdgeA + 0.3  # Small gap from pad for hole clearance
  viaEndA = foldOD_A - bendGap

  viaStartB = foldOD_B + bendGap
  padEdgeB = fpcHeight - EDGE_TO_COPPER_MM - padOverlapSize
  viaEndB = padEdgeB - 0.3  # Small gap from pad for hole clearance

  # Check if there's room for vias in each section
  zoneAHeight = viaEndA - viaStartA
  zoneBHeight = viaEndB - viaStartB

  # Distribute vias between A-side and B-side OD sections
  viasPerSection = max(1, viasNeeded // 2)

  # A-side OD trace section (between pad A and bend #1)
  if zoneAHeight >= DEFAULT_VIA_SIZE_MM:
    for i in range(viasPerSection):
      frac = (i + 0.5) / viasPerSection
      viaY = viaStartA + zoneAHeight * frac
      # Interpolate X position along the trace
      viaFrac = (viaY - aEdgeY) / totalHeight
      viaX = aEdgeX + (bEdgeX - aEdgeX) * viaFrac
      addVia(board, vec(viaX, viaY), DEFAULT_VIA_DRILL_MM, DEFAULT_VIA_SIZE_MM)

  # B-side OD trace section (between bend #4 and pad B)
  if zoneBHeight >= DEFAULT_VIA_SIZE_MM:
    for i in range(viasPerSection):
      frac = (i + 0.5) / viasPerSection
      viaY = viaStartB + zoneBHeight * frac
      # Interpolate X position along the trace
      viaFrac = (viaY - aEdgeY) / totalHeight
      viaX = aEdgeX + (bEdgeX - aEdgeX) * viaFrac
      addVia(board, vec(viaX, viaY), DEFAULT_VIA_DRILL_MM, DEFAULT_VIA_SIZE_MM)

# =============================================================================
# SMD Pad Generation
# =============================================================================

def generateLapPads(board, cfg):
  """
  Generate SMD lap pads for winding interconnections.

  Pads are rotated to align with the trace angle so there's no angle change
  through the solder joint. This also makes the petal separators simpler
  since they can follow the same angle all the way to the board edge.

  A-pads on F.Cu at A-edge (top, Y near 0) - at trace START positions
  B-pads on B.Cu at B-edge (bottom, Y near fpcHeight) - at trace END positions

  Due to helix offset:
  - A-pad of turn N is at X = (N + 0.5) * pitch
  - B-pad of turn N is at X = (N + 1.5) * pitch (same as A-pad of turn N+1)
  """
  turns = cfg["turns"]
  pitch = cfg["pitch"]
  fpcHeight = cfg["fpcHeight"]
  traceWidth = cfg["traceWidth"]
  gap = cfg["gap"]
  mount = cfg["mount"]
  leftMargin = cfg.get("leftMargin", 0)
  traceAngleDeg = cfg.get("traceAngleDeg", 0)

  # Pad dimensions - must fit within pitch with gap clearance
  # padWidth <= pitch - gap to avoid overlapping adjacent pads
  maxPadWidth = pitch - gap
  padWidth = min(maxPadWidth, max(SMD_PAD_WIDTH_MM, traceWidth))
  padHeight = SMD_PAD_HEIGHT_MM

  # Pad Y positions - center of overlap zone
  padOverlapSize = cfg.get("padOverlapSize", padHeight)
  aPadY = EDGE_TO_COPPER_MM + padOverlapSize / 2.0
  bPadY = fpcHeight - EDGE_TO_COPPER_MM - padOverlapSize / 2.0

  # Pad rotation to align with trace angle
  # Trace goes from top-left to bottom-right, so positive rotation aligns with it
  padAngle = traceAngleDeg

  for turnIdx in range(turns):
    # A-pad position (trace start) - offset by leftMargin
    aPadX = leftMargin + (turnIdx + 0.5) * pitch

    # B-pad position (trace end, shifted by one pitch for helix)
    # B50 is at leftMargin + 51.5 * pitch, same as END flap center (turn 51's A-edge)
    bPadX = leftMargin + (turnIdx + 1.5) * pitch

    # For rolling mount:
    # - Turn 0: START flap connects, so skip A-pad
    # - Turn N-1: END flap connects, so skip B-pad
    # For flat mount:
    # - Similar logic

    # A-pads: skip first turn (START flap handles A0) and last turn (END flap handles A51)
    # This mirrors how START/END work identically - both replace an A-pad
    # Place on BOTH layers so traces on both layers connect
    if turnIdx > 0 and turnIdx < turns - 1:
      addSmdPad(board, vec(aPadX, aPadY), f"A{turnIdx}", padWidth, padHeight,
                pcbnew.F_Cu, angleDeg=padAngle)
      addSmdPad(board, vec(aPadX, aPadY), f"A{turnIdx}b", padWidth, padHeight,
                pcbnew.B_Cu, angleDeg=padAngle)

    # B-pads: skip last turn (no B51 - board doesn't extend that far)
    # Place on BOTH layers so traces on both layers connect
    if turnIdx < turns - 1:
      addSmdPad(board, vec(bPadX, bPadY), f"B{turnIdx}", padWidth, padHeight,
                pcbnew.F_Cu, angleDeg=padAngle)
      addSmdPad(board, vec(bPadX, bPadY), f"B{turnIdx}b", padWidth, padHeight,
                pcbnew.B_Cu, angleDeg=padAngle)

def generateFlapPads(board, cfg):
  """
  Generate SMD pads on the mounting flaps and connect them to traces.
  Also generates vias to join F.Cu and B.Cu on the flaps for full current capacity.
  """
  turns = cfg["turns"]
  pitch = cfg["pitch"]
  fpcHeight = cfg["fpcHeight"]
  traceWidth = cfg["traceWidth"]
  gap = cfg["gap"]
  mount = cfg["mount"]
  leftMargin = cfg.get("leftMargin", 0)
  viasNeeded = cfg.get("viasNeeded", 0)
  layers = cfg["layers"]

  # Pad dimensions - must fit within pitch with gap clearance
  maxPadWidth = pitch - gap
  padWidth = min(maxPadWidth, max(SMD_PAD_WIDTH_MM, traceWidth))
  padHeight = SMD_PAD_HEIGHT_MM

  # Flap length - must match edge cuts generation
  flapLength = 5.0

  # Trace endpoint Y positions - must match generateSingleTrace and generateLapPads
  traceAY = padHeight / 2.0 + EDGE_TO_COPPER_MM
  traceBY = fpcHeight - padHeight / 2.0 - EDGE_TO_COPPER_MM

  if mount == "rolling":
    # START flap covers full A0 petal - use center calculated in generateMainOutline
    startFlapX = cfg.get("startFlapCenterX", leftMargin + pitch / 2.0)
    startPadY = -flapLength / 2.0  # Flap extends upward (negative Y)

    # Create START pad on both layers
    addSmdPad(board, vec(startFlapX, startPadY), "START", padWidth, padHeight, pcbnew.F_Cu)
    if layers == 2:
      addSmdPad(board, vec(startFlapX, startPadY), "STARTb", padWidth, padHeight, pcbnew.B_Cu)

    # Connect START pad to first trace (turn 0) at A-edge
    addTrack(board, vec(startFlapX, startPadY + padHeight/2),
             vec(startFlapX, traceAY), pcbnew.F_Cu, traceWidth)
    if layers == 2:
      addTrack(board, vec(startFlapX, startPadY + padHeight/2),
               vec(startFlapX, traceAY), pcbnew.B_Cu, traceWidth)

    # END flap on A-edge (like START) - use center calculated in generateMainOutline
    # END is at turn 51's A-edge position, replacing the A51 lap pad
    endFlapX = cfg.get("endFlapCenterX", leftMargin + (turns - 0.5) * pitch)
    endPadY = -flapLength / 2.0  # Same as START - flap extends upward

    addSmdPad(board, vec(endFlapX, endPadY), "END", padWidth, padHeight, pcbnew.F_Cu)
    if layers == 2:
      addSmdPad(board, vec(endFlapX, endPadY), "ENDb", padWidth, padHeight, pcbnew.B_Cu)

    # Connect END pad to last trace at A-edge (turn 51's A-edge position)
    addTrack(board, vec(endFlapX, endPadY + padHeight/2),
             vec(endFlapX, traceAY), pcbnew.F_Cu, traceWidth)
    if layers == 2:
      addTrack(board, vec(endFlapX, endPadY + padHeight/2),
               vec(endFlapX, traceAY), pcbnew.B_Cu, traceWidth)

  else:  # flat mount
    # START flap extends from A-edge at first trace position
    startFlapX = leftMargin + pitch / 2.0
    startPadY = -flapLength / 2.0

    # Pad on BOTH layers so traces on both layers connect (B.Cu faces PCB when mounted)
    addSmdPad(board, vec(startFlapX, startPadY), "START", padWidth, padHeight, pcbnew.B_Cu)
    addSmdPad(board, vec(startFlapX, startPadY), "STARTf", padWidth, padHeight, pcbnew.F_Cu)

    # Connect to first trace
    addTrack(board, vec(startFlapX, startPadY + padHeight/2),
             vec(startFlapX, traceAY), pcbnew.F_Cu, traceWidth)
    if layers == 2:
      addTrack(board, vec(startFlapX, startPadY + padHeight/2),
               vec(startFlapX, traceAY), pcbnew.B_Cu, traceWidth)

    # END flap at the END of the last trace (its B-edge position)
    # For flat mount, END flap extends from B-edge (bottom, Y=fpcHeight) downward
    lastTraceEndX = leftMargin + (turns - 1 + 1.5) * pitch  # Last trace's B-edge X
    if lastTraceEndX > cfg["fpcWidth"] - padWidth:
      lastTraceEndX = cfg["fpcWidth"] - padWidth / 2.0
    endPadY = fpcHeight + flapLength / 2.0  # Bottom flap center

    # Pad on BOTH layers so traces on both layers connect
    addSmdPad(board, vec(lastTraceEndX, endPadY), "END", padWidth, padHeight, pcbnew.B_Cu)
    addSmdPad(board, vec(lastTraceEndX, endPadY), "ENDf", padWidth, padHeight, pcbnew.F_Cu)

    # Connect END pad to the END of the last trace (at B-edge Y position)
    # The last trace ends at (lastTraceEndX, traceBY), route down to the flap
    addTrack(board, vec(lastTraceEndX, traceBY),
             vec(lastTraceEndX, endPadY - padHeight/2), pcbnew.F_Cu, traceWidth)
    if layers == 2:
      addTrack(board, vec(lastTraceEndX, traceBY),
               vec(lastTraceEndX, endPadY - padHeight/2), pcbnew.B_Cu, traceWidth)

# =============================================================================
# Stiffener Generation
# =============================================================================

def generateStiffener(board, cfg):
  """
  Generate stiffener outlines on User.1 layer.

  Stiffeners are placed at the flap areas to provide rigidity
  for soldering and handling.
  """
  layer = pcbnew.User_1
  lineWidth = STIFFENER_LINE_WIDTH_MM

  fpcHeight = cfg["fpcHeight"]
  mount = cfg["mount"]
  margin = STIFFENER_MARGIN_MM
  flapLength = 5.0  # Must match edge cuts generation

  # Use flap dimensions calculated in generateMainOutline
  # These are set in cfg when the edge cuts are generated
  startFlapLeftX = cfg.get("startFlapLeftX", 0)
  startFlapRightX = cfg.get("startFlapRightX", 2.8)  # fallback
  endFlapLeftX = cfg.get("endFlapLeftX", 0)
  endFlapRightX = cfg.get("endFlapRightX", 2.8)  # fallback

  if mount == "rolling":
    # START stiffener at A-edge flap (extending upward from Y=0)
    # Stiffener width matches full A0 petal width
    x1 = startFlapLeftX
    x2 = startFlapRightX
    y1 = 0  # Starts at A-edge
    y2 = -flapLength - margin  # Extends past flap end

    addLine(board, vec(x1, y1), vec(x2, y1), layer, lineWidth)
    addLine(board, vec(x2, y1), vec(x2, y2), layer, lineWidth)
    addLine(board, vec(x2, y2), vec(x1, y2), layer, lineWidth)
    addLine(board, vec(x1, y2), vec(x1, y1), layer, lineWidth)

    # END stiffener at A-edge flap (extending upward from Y=0, like START)
    # Stiffener width matches full A51 petal width
    x1 = endFlapLeftX
    x2 = endFlapRightX
    y1 = 0  # Starts at A-edge
    y2 = -flapLength - margin  # Extends past flap end (upward)

    addLine(board, vec(x1, y1), vec(x2, y1), layer, lineWidth)
    addLine(board, vec(x2, y1), vec(x2, y2), layer, lineWidth)
    addLine(board, vec(x2, y2), vec(x1, y2), layer, lineWidth)
    addLine(board, vec(x1, y2), vec(x1, y1), layer, lineWidth)

  else:  # flat mount
    # START stiffener at A-edge flap (extending upward from Y=0)
    # Stiffener width matches full A0 petal width
    x1 = startFlapLeftX
    x2 = startFlapRightX
    y1 = 0  # Starts at A-edge
    y2 = -flapLength - margin  # Extends past flap end

    addLine(board, vec(x1, y1), vec(x2, y1), layer, lineWidth)
    addLine(board, vec(x2, y1), vec(x2, y2), layer, lineWidth)
    addLine(board, vec(x2, y2), vec(x1, y2), layer, lineWidth)
    addLine(board, vec(x1, y2), vec(x1, y1), layer, lineWidth)

    # END stiffener at B-edge flap (extending downward from Y=fpcHeight)
    # Stiffener width matches full B51 petal width
    x1 = endFlapLeftX
    x2 = endFlapRightX
    y1 = fpcHeight  # Starts at B-edge
    y2 = fpcHeight + flapLength + margin  # Extends past flap end

    addLine(board, vec(x1, y1), vec(x2, y1), layer, lineWidth)
    addLine(board, vec(x2, y1), vec(x2, y2), layer, lineWidth)
    addLine(board, vec(x2, y2), vec(x1, y2), layer, lineWidth)
    addLine(board, vec(x1, y2), vec(x1, y1), layer, lineWidth)

  # Label the stiffener layer
  # For rolling mount, both stiffeners are at A-edge (top), so put label at top
  labelY = -flapLength - margin - 2.0 if mount == "rolling" else fpcHeight + flapLength + margin + 2.0
  addText(board, vec(cfg["fpcWidth"]/2, labelY), "STIFFENER OUTLINE",
          layer, 1.5, 0.15)

# =============================================================================
# Fold Line Markings
# =============================================================================

def generateFoldLines(board, cfg):
  """
  Generate dotted fold line markings on silkscreen.

  There are 4 fold lines for wrapping around the toroid:
  1. foldOD_A: OD to flat face transition (where pads end, bend #1)
  2. foldLine1Y: Flat face to ID transition (bend #2)
  3. foldLine2Y: ID to flat face transition (bend #3)
  4. foldOD_B: Flat face to OD transition (bend #4)

  Lines span the full FPC width with dotted style.
  """
  layer = pcbnew.F_SilkS
  boardWidth = cfg.get("boardWidth", cfg["fpcWidth"])
  foldLine1Y = cfg["foldLine1Y"]  # Flat face to ID
  foldLine2Y = cfg["foldLine2Y"]  # ID to flat face
  fpcHeight = cfg["fpcHeight"]

  # Fold positions near OD edges
  foldOD_A = cfg["foldOD_A"]
  foldOD_B = cfg["foldOD_B"]

  dashLen = SILK_DASH_LENGTH_MM
  gapLen = SILK_GAP_LENGTH_MM

  # Keep silk inside board edges with margin
  silkMargin = 0.6

  # Get helix offset for skewed parallelogram
  helixOffset = cfg.get("helixOffset", 0)

  def drawDottedLine(y):
    """Draw dotted line across full FPC width at given Y."""
    # Calculate X positions at this Y, accounting for parallelogram shape
    yFrac = y / fpcHeight if fpcHeight > 0 else 0
    startX = helixOffset * yFrac + silkMargin
    endX = boardWidth + helixOffset * yFrac - silkMargin

    x = startX
    while x < endX:
      segEnd = min(x + dashLen, endX)
      addLine(board, vec(x, y), vec(segEnd, y), layer, SILK_LINE_WIDTH_MM)
      x = segEnd + gapLen

  # Draw all 4 fold lines as full-width dotted lines
  drawDottedLine(foldOD_A)
  drawDottedLine(foldLine1Y)
  drawDottedLine(foldLine2Y)
  drawDottedLine(foldOD_B)

# =============================================================================
# Main Board Generation
# =============================================================================

def createBoard(args):
  """Create the KiCad board from command-line arguments."""

  # Parse copper thickness
  copperThickness = parseCopperThickness(args.copper)

  # Look up core
  coreData = lookupCore(args.core)
  if coreData is None:
    sys.exit(1)

  coreOd, coreId, axialHeight = coreData

  # Calculate configuration
  cfg = calculateConfiguration(
    coreOd, coreId, axialHeight,
    args.turns, args.amps,
    args.layers, copperThickness, args.fpcThickness,
    args.bendRadius, args.slitEndDiameter, args.mount
  )

  if cfg is None:
    print("\nDesign not feasible with given parameters.", file=sys.stderr)
    sys.exit(1)

  # Print configuration to stderr
  printConfiguration(cfg)

  # Create output filename
  outFile = args.output
  if not outFile.endswith(".kicad_pcb"):
    outFile += ".kicad_pcb"

  outDir = os.path.dirname(outFile)
  if outDir and not os.path.exists(outDir):
    os.makedirs(outDir)

  # Create board
  board = pcbnew.BOARD()

  # Set layer count and apply JLCPCB design rules
  settings = board.GetDesignSettings()
  settings.SetCopperLayerCount(cfg["layers"])

  # Apply JLCPCB design rules
  applyJLCPCBRules(board)

  # Set board origin offset to center FPC on the page
  # KiCad uses top-left as origin, with Y increasing downward
  # Typical A4 sheet is 297mm x 210mm
  sheetWidth = 297.0
  sheetHeight = 210.0
  flapLen = 10.0  # Flap length

  # Total FPC dimensions including flaps
  fpcTotalWidth = cfg["fpcWidth"] + cfg["pitch"]  # Include helix offset
  # Both mounting modes now have START on A-edge (top) and END on B-edge (bottom)
  fpcTotalHeight = cfg["fpcHeight"] + 2 * flapLen  # Flaps at top and bottom
  topOffset = flapLen  # START flap extends upward from A-edge

  # Center on sheet
  originX = (sheetWidth - fpcTotalWidth) / 2.0
  originY = (sheetHeight - fpcTotalHeight) / 2.0 + topOffset
  setOrigin(originX, originY)

  # Generate geometry
  print("\nGenerating geometry...", file=sys.stderr)

  generateEdgeCuts(board, cfg)
  print("  Edge cuts with slits: done", file=sys.stderr)

  generateWindingTraces(board, cfg)
  print(f"  Winding traces ({cfg['turns']} turns): done", file=sys.stderr)

  generateLapPads(board, cfg)
  generateFlapPads(board, cfg)
  print("  SMD pads: done", file=sys.stderr)

  generateStiffener(board, cfg)
  print("  Stiffener outlines: done", file=sys.stderr)

  generateFoldLines(board, cfg)
  print("  Fold line markings: done", file=sys.stderr)

  # Save board
  if os.path.exists(outFile):
    os.remove(outFile)

  pcbnew.SaveBoard(outFile, board)

  print(f"\nCreated: {outFile}", file=sys.stderr)
  print(f"Open in KiCad 9 to view.", file=sys.stderr)

# =============================================================================
# Main Entry Point
# =============================================================================

def main():
  parser = argparse.ArgumentParser(
    description="Generate FPC toroid winding for KiCad 9",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog="""
Examples:
  %(prog)s -c T68 -t 20 -a 1.0 -o my_coil.kicad_pcb
  %(prog)s -c FT-50 -t 30 -a 2.0 --layers 2 -o high_current.kicad_pcb
  %(prog)s -c T200 -t 52 -a 3.5 --mount flat -o flat_mount.kicad_pcb

Copper thickness options: 0.5oz, 18u, 1oz, 35u, 2oz, 70u
Mount options: rolling (toroid rolls on PCB), flat (toroid lays flat)
"""
  )

  parser.add_argument("-c", "--core", required=True,
    help="Core type (e.g., T68, FT-50, T200)")
  parser.add_argument("-t", "--turns", type=int, required=True,
    help="Number of turns")
  parser.add_argument("-a", "--amps", type=float, default=0.5,
    help="Current capacity in amps (default: 0.5)")
  parser.add_argument("-o", "--output", required=True,
    help="Output filename (.kicad_pcb)")

  parser.add_argument("--layers", type=int, choices=[1, 2], default=2,
    help="FPC layer count: 1 or 2 (default: 2)")
  parser.add_argument("--copper", type=str, default="1oz",
    help="Copper thickness (default: 1oz)")
  parser.add_argument("--fpcThickness", type=float, default=0.22,
    help="FPC base thickness in mm (default: 0.22)")
  parser.add_argument("--bendRadius", type=float, default=None,
    help="Override calculated bend radius in mm")
  parser.add_argument("--slitEndDiameter", type=float, default=0.8,
    help="Rip-stop semicircle diameter in mm (default: 0.8)")
  parser.add_argument("--mount", choices=["rolling", "flat"], default="rolling",
    help="Mounting orientation (default: rolling)")

  args = parser.parse_args()
  createBoard(args)

if __name__ == "__main__":
  main()
