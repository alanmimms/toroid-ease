#!/usr/bin/env python3

import sys
import argparse
import math
import os
import pcbnew

# --- Fabrication Limits ---
minGapMm = 0.15           # Minimum trace-to-trace gap
minTraceWidthMm = 0.15    # Minimum trace width

# --- Current Capacity ---
mmPerAmp = 0.3            # Trace width per amp (1oz copper)
ampsPerVia = 0.4          # Current capacity per via (0.3mm drill)

# --- Pad/Via Geometry ---
annularRingRatio = 1.8    # Pad diameter = drill * this
viaAnnularRatio = 2.0     # Via pad diameter = drill * this
defaultViaDrill = 0.3     # Typical FPC via drill
defaultPadDrill = 1.0     # THT pad drill for flaps

# --- Mechanical ---
flapMargin = 1.0          # Margin around pad on flaps
flapNeckWidth = 2.0       # Width of neck connecting flap to board
tabSlotClearance = 0.1    # Clearance for tab in slot
tabWidthBase = 2.5        # Width of tab at base
tabWidthTip = 2.0         # Width of tab at tip (narrower)
tabHeight = 3.0           # How far tab extends
tabSlotCount = 4          # Number of tab/slot pairs
lengthSafetyFactor = 0.95 # Use 95% of ID circumference

# --- Soldering ---
padToEdgeGap = 0.5        # Gap between pad and edge
btoAPadHeight = 1.5       # Height of B-to-A pads

# --- Silkscreen ---
silkLineWidth = 0.15
textHeight = 1.0
textThickness = 0.15

# --- Courtyard ---
courtyardMargin = 0.25

# --- Core Database: name -> (od, id, axialHeight) in mm ---
Cores = {
  "T68": (17.5, 9.4, 4.8),
  "T50": (12.7, 7.7, 4.8),
  "T37": (9.5, 5.2, 3.25),
  "T200": (50.8, 31.8, 14.0)
}

# =============================================================================
# Core Lookup
# =============================================================================

def lookupCore(name):
  normalized = name.upper().replace("-", "")
  if normalized.startswith("F"):
    normalized = normalized[1:]
  if normalized in Cores:
    return Cores[normalized]

  print(f"Error: Core '{name}' not found.")
  print("\nAvailable cores:")
  print(f"  {'Name':<8} {'OD (mm)':<10} {'ID (mm)':<10} {'Height (mm)':<10}")
  print(f"  {'-'*8} {'-'*10} {'-'*10} {'-'*10}")
  for coreName, (od, coreId, height) in Cores.items():
    print(f"  {coreName:<8} {od:<10.2f} {coreId:<10.2f} {height:<10.2f}")
  print("\nAccepted formats: T68, T-68, FT68, FT-68 (case insensitive)")
  return None

# =============================================================================
# Configuration Calculation
# =============================================================================

def calculateConfiguration(od, coreId, axialHeight, angle, turnsRequired,
                           currentRequired, maxLayers, taps, viaDrill, padDrill):
  availableLength = coreId * math.pi * (angle / 360.0) * lengthSafetyFactor
  radialThickness = (od - coreId) / 2

  # FPC height: front face + ID cylinder + rear face
  fpcHeight = 2 * radialThickness + axialHeight

  # Wedge count for triangular spreading slits on flat faces
  idCircumference = coreId * math.pi * (angle / 360.0)
  odCircumference = od * math.pi * (angle / 360.0)
  expansionDistance = odCircumference - idCircumference
  # Each wedge slit allows some expansion
  wedgeSlitWidth = 1.5  # Width at OD end of triangular slit
  wedgeCount = max(3, math.ceil(expansionDistance / wedgeSlitWidth))

  # Valid layer counts for KiCad (1, 2, 4, 6, 8...)
  bestConfig = None

  for parallelCount in range(1, maxLayers + 1):
    for seriesCount in range(1, (maxLayers // parallelCount) + 1):
      totalLayers = parallelCount * seriesCount
      if totalLayers > maxLayers:
        continue
      # KiCad requires even layer counts >= 4, or 1-2
      if totalLayers > 2 and totalLayers % 2 != 0:
        continue

      # Turns per layer
      if seriesCount == 1:
        turnsPerLayer = turnsRequired
      else:
        turnsPerLayer = math.ceil(turnsRequired / seriesCount)

      # Check fit with offsets
      if seriesCount > 1:
        offsetLoss = (seriesCount - 1) * 0.5
        effectiveTurns = turnsPerLayer + math.ceil(offsetLoss)
      else:
        effectiveTurns = turnsPerLayer

      if effectiveTurns < 1:
        continue

      pitch = availableLength / turnsPerLayer

      if seriesCount > 1:
        lastTraceX = (seriesCount - 1) * (pitch / 2) + (turnsPerLayer - 0.5) * pitch
        if lastTraceX > availableLength:
          continue

      traceWidth = pitch - minGapMm
      if traceWidth < minTraceWidthMm:
        continue

      currentCapacity = traceWidth * mmPerAmp * parallelCount
      if currentCapacity < currentRequired:
        continue

      # Valid configuration
      offsets = []
      for layer in range(totalLayers):
        setIndex = layer // parallelCount
        offset = setIndex * (pitch / 2)
        offsets.append(offset)

      traceAngle = math.atan2(pitch, fpcHeight)

      viasNeeded = math.ceil(currentRequired / ampsPerVia)
      viaSize = viaDrill * viaAnnularRatio
      viaCols = math.ceil(math.sqrt(viasNeeded))
      viaRows = math.ceil(viasNeeded / viaCols)
      viaSpacing = viaSize + 0.3
      viaFarmWidth = viaCols * viaSpacing
      viaFarmHeight = viaRows * viaSpacing

      padSize = padDrill * annularRingRatio
      flapDiameter = padSize + 2 * flapMargin

      # B-to-A pad width should match trace width for current capacity
      btoAPadWidth = max(traceWidth, 1.5)

      config = {
        "od": od,
        "id": coreId,
        "axialHeight": axialHeight,
        "angle": angle,
        "availableLength": availableLength,
        "radialThickness": radialThickness,
        "fpcHeight": fpcHeight,
        "wedgeCount": wedgeCount,
        "parallelCount": parallelCount,
        "seriesCount": seriesCount,
        "totalLayers": totalLayers,
        "turnsPerLayer": turnsPerLayer,
        "actualTurns": turnsRequired,
        "turnsRequired": turnsRequired,
        "traceWidth": traceWidth,
        "pitch": pitch,
        "traceAngle": traceAngle,
        "offsets": offsets,
        "currentCapacity": currentCapacity,
        "currentRequired": currentRequired,
        "viasNeeded": viasNeeded,
        "viaDrill": viaDrill,
        "viaSize": viaSize,
        "viaFarmWidth": viaFarmWidth,
        "viaFarmHeight": viaFarmHeight,
        "padDrill": padDrill,
        "padSize": padSize,
        "flapDiameter": flapDiameter,
        "btoAPadWidth": btoAPadWidth,
        "taps": taps or []
      }

      if bestConfig is None or totalLayers < bestConfig["totalLayers"]:
        bestConfig = config
      elif totalLayers == bestConfig["totalLayers"]:
        if traceWidth > bestConfig["traceWidth"]:
          bestConfig = config

    if bestConfig is not None and bestConfig["parallelCount"] == parallelCount:
      break

  return bestConfig

def printConfiguration(cfg):
  print("\n" + "=" * 50)
  print("DESIGN CONFIGURATION")
  print("=" * 50)
  print(f"  Core: OD={cfg['od']}mm, ID={cfg['id']}mm, H={cfg['axialHeight']}mm")
  print(f"  Angle: {cfg['angle']}°")
  print(f"  Available length: {cfg['availableLength']:.2f}mm")
  print(f"  FPC height: {cfg['fpcHeight']:.2f}mm")
  print()
  print(f"  Turns required: {cfg['turnsRequired']}")
  print(f"  Turns achieved: {cfg['actualTurns']}")
  print(f"  Current required: {cfg['currentRequired']}A")
  print(f"  Current capacity: {cfg['currentCapacity']:.2f}A")
  print()
  print(f"  Layer configuration: {cfg['totalLayers']} layers")
  print(f"    - {cfg['parallelCount']} parallel for current")
  print(f"    - {cfg['seriesCount']} series sets for turns")
  print()
  print(f"  Trace width: {cfg['traceWidth']:.3f}mm")
  print(f"  Trace pitch: {cfg['pitch']:.3f}mm")
  print(f"  Trace angle: {math.degrees(cfg['traceAngle']):.2f}°")
  print(f"  Trace gap: {minGapMm}mm")
  print()
  print(f"  Wedges for spreading: {cfg['wedgeCount']}")
  print(f"  Via farm: {cfg['viasNeeded']} vias")
  if cfg['taps']:
    print(f"  Taps at turns: {cfg['taps']}")
  print("=" * 50 + "\n")

def printRejection(od, coreId, axialHeight, angle, turnsRequired, currentRequired, maxLayers):
  availableLength = coreId * math.pi * (angle / 360.0) * lengthSafetyFactor
  maxTurnsPerLayer = int(availableLength / (minTraceWidthMm + minGapMm))

  print("\n" + "!" * 50)
  print("DESIGN REJECTED: Cannot meet requirements")
  print("!" * 50)
  print(f"  Core: OD={od}mm, ID={coreId}mm")
  print(f"  Available length: {availableLength:.2f}mm")
  print(f"  Max turns per layer: {maxTurnsPerLayer}")
  print(f"  Turns required: {turnsRequired}")
  print(f"  Current required: {currentRequired}A")
  print("!" * 50 + "\n")

# =============================================================================
# Geometry Helpers
# =============================================================================

def toNm(mm):
  return int(mm * 1e6)

def vec(x, y):
  return pcbnew.VECTOR2I(toNm(x), toNm(y))

def addLine(board, start, end, layer, width=0.1):
  seg = pcbnew.PCB_SHAPE(board)
  seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
  seg.SetStart(start)
  seg.SetEnd(end)
  seg.SetLayer(layer)
  seg.SetWidth(toNm(width))
  board.Add(seg)

def addCircle(board, center, radius, layer, width=0.1):
  circle = pcbnew.PCB_SHAPE(board)
  circle.SetShape(pcbnew.SHAPE_T_CIRCLE)
  circle.SetCenter(center)
  circle.SetEnd(pcbnew.VECTOR2I(center.x + toNm(radius), center.y))
  circle.SetLayer(layer)
  circle.SetWidth(toNm(width))
  board.Add(circle)

def addTrack(board, start, end, layer, width):
  track = pcbnew.PCB_TRACK(board)
  track.SetStart(start)
  track.SetEnd(end)
  track.SetLayer(layer)
  track.SetWidth(toNm(width))
  board.Add(track)

def addVia(board, pos, drill, size, startLayer, endLayer):
  via = pcbnew.PCB_VIA(board)
  via.SetPosition(pos)
  via.SetDrill(toNm(drill))
  via.SetWidth(toNm(size))
  via.SetViaType(pcbnew.VIATYPE_THROUGH)
  via.SetLayerPair(startLayer, endLayer)
  board.Add(via)

def addThtPad(board, pos, name, padSize, drill):
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
  pad.SetSize(pcbnew.VECTOR2I(toNm(padSize), toNm(padSize)))
  pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
  pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
  pad.SetDrillSize(pcbnew.VECTOR2I(toNm(drill), toNm(drill)))
  pad.SetLayerSet(pcbnew.LSET.AllCuMask())

  fp.Add(pad)
  board.Add(fp)
  return pad

def addSmdPad(board, pos, name, width, height, layer):
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
  pad.SetShape(pcbnew.PAD_SHAPE_RECT)
  pad.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
  lset = pcbnew.LSET()
  lset.AddLayer(layer)
  pad.SetLayerSet(lset)

  fp.Add(pad)
  board.Add(fp)
  return pad

def addText(board, pos, text, layer, height=1.0, thickness=0.15):
  txt = pcbnew.PCB_TEXT(board)
  txt.SetText(text)
  txt.SetPosition(pos)
  txt.SetLayer(layer)
  txt.SetTextHeight(toNm(height))
  txt.SetTextThickness(toNm(thickness))
  txt.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER)
  txt.SetVertJustify(pcbnew.GR_TEXT_V_ALIGN_CENTER)
  board.Add(txt)

# =============================================================================
# Geometry Generation
# =============================================================================

def generateBoardOutline(board, cfg):
  """
  Generate board outline with:
  - Triangular wedge slits on front and rear flat faces (for spreading)
  - Tab slots on A-edge (top)
  - Trapezoidal tabs on B-edge (bottom)
  - START flap at A-edge (connects to first trace on F_Cu)
  - END flap at B-edge (connects to last trace on B_Cu)
  """
  w = cfg["availableLength"]
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  axial = cfg["axialHeight"]
  wedgeCount = cfg["wedgeCount"]
  pitch = cfg["pitch"]
  turnsPerLayer = cfg["turnsPerLayer"]
  traceAngle = cfg["traceAngle"]
  flapDiameter = cfg["flapDiameter"]
  offsets = cfg["offsets"]
  totalLayers = cfg["totalLayers"]

  layer = pcbnew.Edge_Cuts

  # Key Y positions
  yAEdge = 0                    # A-edge (OD, top)
  yFrontFold = radial           # Front face ends, ID starts
  yRearFold = radial + axial    # ID ends, rear face starts
  yBEdge = h                    # B-edge (OD, bottom)

  # Layer offsets
  fCuOffset = offsets[0]
  bCuOffset = offsets[totalLayers - 1]

  # Calculate flap positions
  flapRadius = flapDiameter / 2
  startFlapX = fCuOffset + pitch / 2  # First trace start position on F_Cu
  # End flap at last turn's B-edge position (includes angle offset and layer offset)
  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  marginBottom = marginTop
  traceLen = h - marginTop - marginBottom
  dx = traceLen * math.tan(traceAngle)
  endFlapX = bCuOffset + (turnsPerLayer - 1) * pitch + pitch / 2 + dx

  # START flap Y position (extends above A-edge)
  startFlapY = -flapRadius - 0.5
  # END flap Y position (extends below B-edge)
  endFlapY = h + flapRadius + 0.5

  # Tab/slot positions (avoid START flap on A-edge, END flap on B-edge)
  tabMarginLeft = flapDiameter + 2  # Margin for START flap
  tabMarginRight = 2  # Small margin on right side
  tabUsableWidth = w - tabMarginLeft - tabMarginRight
  tabSpacing = tabUsableWidth / max(1, tabSlotCount)

  # Wedge slit positions on flat faces
  wedgeWidth = w / wedgeCount

  # --- Build outline clockwise from top-left ---
  pts = []

  # A-EDGE (top, Y=0) with START flap and slots
  pts.append((0, yAEdge))

  # START flap neck and flap shape
  startNeckLeft = startFlapX - flapNeckWidth / 2
  startNeckRight = startFlapX + flapNeckWidth / 2

  pts.append((startNeckLeft, yAEdge))
  pts.append((startNeckLeft, startFlapY + flapRadius))
  pts.append((startFlapX - flapRadius, startFlapY))
  pts.append((startFlapX, startFlapY - flapRadius))
  pts.append((startFlapX + flapRadius, startFlapY))
  pts.append((startNeckRight, startFlapY + flapRadius))
  pts.append((startNeckRight, yAEdge))

  # Continue along A-edge, adding slots
  for i in range(tabSlotCount):
    slotCenterX = tabMarginLeft + (i + 0.5) * tabSpacing
    slotWidth = tabWidthTip + tabSlotClearance
    slotLeft = slotCenterX - slotWidth / 2
    slotRight = slotCenterX + slotWidth / 2
    slotDepth = tabHeight + 0.3

    # Skip if slot overlaps with START flap
    if slotLeft < startNeckRight + 1:
      continue

    pts.append((slotLeft, yAEdge))
    pts.append((slotLeft, yAEdge + slotDepth))
    pts.append((slotRight, yAEdge + slotDepth))
    pts.append((slotRight, yAEdge))

  # To right edge
  pts.append((w, yAEdge))

  # RIGHT EDGE
  pts.append((w, yBEdge))

  # B-EDGE (bottom) with END flap and trapezoidal tabs
  # First check if END flap is within board width
  endNeckLeft = endFlapX - flapNeckWidth / 2
  endNeckRight = endFlapX + flapNeckWidth / 2

  # Find where END flap should be inserted among the tabs
  # Go from right to left along B-edge
  tabPositions = []
  for i in range(tabSlotCount - 1, -1, -1):
    tabCenterX = tabMarginLeft + (i + 0.5) * tabSpacing
    # Skip tabs that overlap with END flap
    if abs(tabCenterX - endFlapX) < tabWidthBase / 2 + flapNeckWidth / 2 + 1:
      continue
    tabPositions.append(tabCenterX)

  # Sort tab positions from right to left for clockwise traversal
  tabPositions.sort(reverse=True)

  currentX = w
  endFlapDrawn = False

  for tabCenterX in tabPositions:
    # Check if we should draw END flap before this tab
    if not endFlapDrawn and tabCenterX < endFlapX and endNeckRight < w:
      # Draw END flap
      pts.append((endNeckRight, yBEdge))
      pts.append((endNeckRight, endFlapY - flapRadius))
      pts.append((endFlapX + flapRadius, endFlapY))
      pts.append((endFlapX, endFlapY + flapRadius))
      pts.append((endFlapX - flapRadius, endFlapY))
      pts.append((endNeckLeft, endFlapY - flapRadius))
      pts.append((endNeckLeft, yBEdge))
      endFlapDrawn = True

    # Draw this tab
    baseLeft = tabCenterX - tabWidthBase / 2
    baseRight = tabCenterX + tabWidthBase / 2
    tipLeft = tabCenterX - tabWidthTip / 2
    tipRight = tabCenterX + tabWidthTip / 2
    tabBottom = yBEdge + tabHeight

    pts.append((baseRight, yBEdge))
    pts.append((tipRight, tabBottom))
    pts.append((tipLeft, tabBottom))
    pts.append((baseLeft, yBEdge))

  # If END flap hasn't been drawn yet (it's to the left of all tabs), draw it now
  if not endFlapDrawn and endNeckRight < w:
    pts.append((endNeckRight, yBEdge))
    pts.append((endNeckRight, endFlapY - flapRadius))
    pts.append((endFlapX + flapRadius, endFlapY))
    pts.append((endFlapX, endFlapY + flapRadius))
    pts.append((endFlapX - flapRadius, endFlapY))
    pts.append((endNeckLeft, endFlapY - flapRadius))
    pts.append((endNeckLeft, yBEdge))

  # To left edge
  pts.append((0, yBEdge))

  # LEFT EDGE
  pts.append((0, yAEdge))

  # Draw main outline
  for i in range(len(pts) - 1):
    addLine(board, vec(pts[i][0], pts[i][1]), vec(pts[i+1][0], pts[i+1][1]), layer)

  # --- Triangular wedge slits on flat faces ---
  # These are true slits: point at fold line, open at OD edge
  # This allows the flat faces to spread when wrapped around toroid

  slitWidthAtOd = 1.2  # Width at OD edge

  for i in range(1, wedgeCount):
    slitX = i * wedgeWidth

    # Front face slit (from front fold to A-edge)
    # Point at fold, open/wide at OD (A-edge)
    # Draw two lines forming a V from fold to OD edge
    addLine(board, vec(slitX, yFrontFold), vec(slitX - slitWidthAtOd/2, yAEdge), layer)
    addLine(board, vec(slitX, yFrontFold), vec(slitX + slitWidthAtOd/2, yAEdge), layer)

    # Rear face slit (from rear fold to B-edge)
    # Point at fold, open/wide at OD (B-edge)
    addLine(board, vec(slitX, yRearFold), vec(slitX - slitWidthAtOd/2, yBEdge), layer)
    addLine(board, vec(slitX, yRearFold), vec(slitX + slitWidthAtOd/2, yBEdge), layer)

def generateFoldLines(board, cfg):
  """Dashed fold lines at ID edges."""
  w = cfg["availableLength"]
  radial = cfg["radialThickness"]
  axial = cfg["axialHeight"]

  layer = pcbnew.F_SilkS
  dashLen = 1.0
  gapLen = 0.5

  y1 = radial
  y2 = radial + axial

  x = 0
  while x < w:
    endX = min(x + dashLen, w)
    addLine(board, vec(x, y1), vec(endX, y1), layer, silkLineWidth)
    addLine(board, vec(x, y2), vec(endX, y2), layer, silkLineWidth)
    x = endX + gapLen

def generateTraces(board, cfg):
  """Generate angled traces on all layers."""
  w = cfg["availableLength"]
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  totalLayers = cfg["totalLayers"]
  turnsPerLayer = cfg["turnsPerLayer"]
  pitch = cfg["pitch"]
  traceWidth = cfg["traceWidth"]
  traceAngle = cfg["traceAngle"]
  offsets = cfg["offsets"]

  # Trace margins - stay clear of pads and slits
  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  marginBottom = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5

  yStart = marginTop
  yEnd = h - marginBottom
  traceLen = yEnd - yStart
  dx = traceLen * math.tan(traceAngle)

  for layerIdx in range(totalLayers):
    pcbLayer = pcbnew.F_Cu if layerIdx == 0 else pcbnew.B_Cu
    if totalLayers > 2:
      if layerIdx == 0:
        pcbLayer = pcbnew.F_Cu
      elif layerIdx == totalLayers - 1:
        pcbLayer = pcbnew.B_Cu
      else:
        innerLayers = [pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu,
                       pcbnew.In4_Cu, pcbnew.In5_Cu, pcbnew.In6_Cu]
        pcbLayer = innerLayers[layerIdx - 1] if layerIdx - 1 < len(innerLayers) else pcbnew.B_Cu

    offset = offsets[layerIdx]

    for turn in range(turnsPerLayer):
      xStart = offset + turn * pitch + pitch / 2
      xEnd = xStart + dx

      if xStart < 0 or xEnd > w:
        continue

      addTrack(board, vec(xStart, yStart), vec(xEnd, yEnd), pcbLayer, traceWidth)

def generateBtoAPads(board, cfg):
  """
  Generate B-to-A solder pads.
  - A-edge pads on F_Cu (top layer) - receive connection from previous turn
  - B-edge pads on B_Cu (bottom layer) - connect to next turn
  Pads are staggered (alternating Y positions) to allow wider pads.
  Pads align with trace endpoints on their respective layers.
  """
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  turnsPerLayer = cfg["turnsPerLayer"]
  pitch = cfg["pitch"]
  traceAngle = cfg["traceAngle"]
  btoAPadWidth = cfg["btoAPadWidth"]
  traceWidth = cfg["traceWidth"]
  offsets = cfg["offsets"]
  totalLayers = cfg["totalLayers"]

  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  marginBottom = marginTop
  traceLen = h - marginTop - marginBottom
  dx = traceLen * math.tan(traceAngle)

  # Layer offsets for F_Cu (layer 0) and B_Cu (last layer)
  fCuOffset = offsets[0]  # Always 0 for first series set
  bCuOffset = offsets[totalLayers - 1]  # May be pitch/2 or more for later series sets

  # Base Y positions for pads
  aPadYBase = padToEdgeGap + btoAPadHeight / 2
  bPadYBase = h - padToEdgeGap - btoAPadHeight / 2

  # Stagger amount for alternating pads
  stagger = btoAPadHeight * 0.8

  for turn in range(turnsPerLayer):
    # Stagger: even turns closer to edge, odd turns further
    yOffset = stagger if turn % 2 == 1 else 0

    # A-edge pad (receives connection from previous turn's B-pad)
    # Aligns with F_Cu trace start position
    # Skip turn 0 - that's START
    if turn > 0:
      aX = fCuOffset + turn * pitch + pitch / 2  # Trace start on F_Cu
      aY = aPadYBase + yOffset
      addSmdPad(board, vec(aX, aY), f"A{turn}", btoAPadWidth, btoAPadHeight, pcbnew.F_Cu)

    # B-edge pad (connects to next turn's A-pad)
    # Aligns with B_Cu trace end position
    # Skip last turn - that's END
    if turn < turnsPerLayer - 1:
      bX = bCuOffset + turn * pitch + pitch / 2 + dx  # Trace end on B_Cu
      bY = bPadYBase - yOffset
      addSmdPad(board, vec(bX, bY), f"B{turn}", btoAPadWidth, btoAPadHeight, pcbnew.B_Cu)

def generateStartEndConnections(board, cfg):
  """
  Connect START flap to first trace (top layer, A-edge).
  Connect END flap to last trace (bottom layer, B-edge).
  """
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  pitch = cfg["pitch"]
  turnsPerLayer = cfg["turnsPerLayer"]
  traceWidth = cfg["traceWidth"]
  traceAngle = cfg["traceAngle"]
  flapDiameter = cfg["flapDiameter"]
  offsets = cfg["offsets"]
  totalLayers = cfg["totalLayers"]

  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  marginBottom = marginTop
  traceLen = h - marginTop - marginBottom
  dx = traceLen * math.tan(traceAngle)

  flapRadius = flapDiameter / 2
  startFlapY = -flapRadius - 0.5  # START flap above A-edge
  endFlapY = h + flapRadius + 0.5  # END flap below B-edge

  # Layer offsets
  fCuOffset = offsets[0]
  bCuOffset = offsets[totalLayers - 1]

  # START connection: from first trace start to START pad (on F_Cu)
  startX = fCuOffset + pitch / 2  # First trace on F_Cu
  startTraceY = marginTop
  addTrack(board, vec(startX, startTraceY), vec(startX, startFlapY + flapRadius + 0.5),
           pcbnew.F_Cu, traceWidth)

  # END connection: from last trace end to END pad (on B_Cu)
  endTraceX = bCuOffset + (turnsPerLayer - 1) * pitch + pitch / 2 + dx  # Last trace on B_Cu
  endTraceY = h - marginBottom
  addTrack(board, vec(endTraceX, endTraceY), vec(endTraceX, endFlapY - flapRadius - 0.5),
           pcbnew.B_Cu, traceWidth)

def generateFlaps(board, cfg):
  """Add THT pads for START (at A-edge) and END (at B-edge) flaps."""
  pitch = cfg["pitch"]
  turnsPerLayer = cfg["turnsPerLayer"]
  flapDiameter = cfg["flapDiameter"]
  padSize = cfg["padSize"]
  padDrill = cfg["padDrill"]
  traceAngle = cfg["traceAngle"]
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  taps = cfg["taps"]
  offsets = cfg["offsets"]
  totalLayers = cfg["totalLayers"]

  flapRadius = flapDiameter / 2
  startFlapY = -flapRadius - 0.5  # START flap above A-edge
  endFlapY = h + flapRadius + 0.5  # END flap below B-edge

  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  marginBottom = marginTop
  traceLen = h - marginTop - marginBottom
  dx = traceLen * math.tan(traceAngle)

  # Layer offsets
  fCuOffset = offsets[0]
  bCuOffset = offsets[totalLayers - 1]

  # START pad (at A-edge, connects to F_Cu)
  startX = fCuOffset + pitch / 2
  addThtPad(board, vec(startX, startFlapY), "START", padSize, padDrill)
  addText(board, vec(startX, startFlapY - flapRadius - 1), "START",
          pcbnew.F_SilkS, textHeight * 0.7, textThickness)

  # END pad (at B-edge, connects to B_Cu)
  endX = bCuOffset + (turnsPerLayer - 1) * pitch + pitch / 2 + dx
  addThtPad(board, vec(endX, endFlapY), "END", padSize, padDrill)
  addText(board, vec(endX, endFlapY + flapRadius + 1), "END",
          pcbnew.B_SilkS, textHeight * 0.7, textThickness)

  # TAP pads (if any) - these would need their own flap cutouts
  # For now, add them along the A-edge
  for tapTurn in taps:
    if tapTurn < 1 or tapTurn > turnsPerLayer:
      print(f"Warning: Tap {tapTurn} out of range")
      continue
    tapX = fCuOffset + (tapTurn - 1) * pitch + pitch / 2
    addThtPad(board, vec(tapX, startFlapY), f"T{tapTurn}", padSize, padDrill)
    addText(board, vec(tapX, startFlapY - flapRadius - 1), f"T{tapTurn}",
            pcbnew.F_SilkS, textHeight * 0.6, textThickness)

def generateViaFarms(board, cfg):
  """Via farms to connect parallel layers."""
  if cfg["parallelCount"] <= 1:
    return

  pitch = cfg["pitch"]
  turnsPerLayer = cfg["turnsPerLayer"]
  viaDrill = cfg["viaDrill"]
  viaSize = cfg["viaSize"]
  viasNeeded = cfg["viasNeeded"]
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]

  viaSpacing = viaSize + 0.3
  cols = math.ceil(math.sqrt(viasNeeded))
  rows = math.ceil(viasNeeded / cols)

  # Place via farms near A-edge for start and between series groups
  viaY = radial * 0.5

  def addViaFarmAt(centerX, centerY):
    startX = centerX - (cols - 1) * viaSpacing / 2
    startY = centerY - (rows - 1) * viaSpacing / 2
    count = 0
    for row in range(rows):
      for col in range(cols):
        if count >= viasNeeded:
          return
        x = startX + col * viaSpacing
        y = startY + row * viaSpacing
        addVia(board, vec(x, y), viaDrill, viaSize, pcbnew.F_Cu, pcbnew.B_Cu)
        count += 1

  # Via farm at start
  addViaFarmAt(pitch / 2, viaY)

  # Via farm at end
  addViaFarmAt((turnsPerLayer - 0.5) * pitch, viaY)

def generateCourtyard(board, cfg):
  w = cfg["availableLength"]
  h = cfg["fpcHeight"]
  flapDiameter = cfg["flapDiameter"]

  margin = courtyardMargin
  flapExtent = flapDiameter + 1  # START flap at top, END flap at bottom
  tabExtent = tabHeight + 0.5

  left = -margin
  right = w + margin
  top = -flapExtent - margin  # Account for START flap
  # Account for both END flap and tabs at bottom
  bottom = h + max(flapExtent, tabExtent) + margin

  layer = pcbnew.F_CrtYd

  addLine(board, vec(left, top), vec(right, top), layer, 0.05)
  addLine(board, vec(right, top), vec(right, bottom), layer, 0.05)
  addLine(board, vec(right, bottom), vec(left, bottom), layer, 0.05)
  addLine(board, vec(left, bottom), vec(left, top), layer, 0.05)

# =============================================================================
# Main
# =============================================================================

def createBoard(args):
  coreData = lookupCore(args.core)
  if coreData is None:
    sys.exit(1)

  od, coreId, axialHeight = coreData

  taps = []
  if args.taps:
    try:
      taps = [int(t.strip()) for t in args.taps.split(",")]
    except ValueError:
      print("Error: --taps must be comma-separated integers")
      sys.exit(1)

  cfg = calculateConfiguration(
    od, coreId, axialHeight,
    args.angle, args.turns, args.amps, args.maxLayers,
    taps, args.viaDrill, args.padDrill)

  if cfg is None:
    printRejection(od, coreId, axialHeight, args.angle,
                   args.turns, args.amps, args.maxLayers)
    sys.exit(1)

  printConfiguration(cfg)

  outFile = args.output
  if not outFile.endswith(".kicad_pcb"):
    outFile += ".kicad_pcb"

  outDir = os.path.dirname(outFile)
  if outDir and not os.path.exists(outDir):
    os.makedirs(outDir)

  board = pcbnew.BOARD()

  if cfg["totalLayers"] > 2:
    settings = board.GetDesignSettings()
    settings.SetCopperLayerCount(cfg["totalLayers"])

  generateBoardOutline(board, cfg)
  generateFoldLines(board, cfg)
  generateTraces(board, cfg)
  generateBtoAPads(board, cfg)
  generateStartEndConnections(board, cfg)
  generateFlaps(board, cfg)
  generateViaFarms(board, cfg)
  generateCourtyard(board, cfg)

  if os.path.exists(outFile):
    os.remove(outFile)

  pcbnew.SaveBoard(outFile, board)

  baseName = outFile[:-10] if outFile.endswith(".kicad_pcb") else outFile
  print(f"Created project files:")
  print(f"  {baseName}.kicad_pro")
  print(f"  {baseName}.kicad_pcb")
  print(f"\nOpen in KiCad 9 to view.")

def main():
  parser = argparse.ArgumentParser(
    description="Generate FPC toroid winding for KiCad")

  parser.add_argument("-c", "--core", required=True)
  parser.add_argument("-t", "--turns", type=int, required=True)
  parser.add_argument("-a", "--amps", type=float, default=0.5)
  parser.add_argument("-l", "--maxLayers", type=int, default=6)
  parser.add_argument("--angle", type=float, default=360.0)
  parser.add_argument("--taps", type=str)
  parser.add_argument("--viaDrill", type=float, default=0.3)
  parser.add_argument("--viaSize", type=float, default=0.6)
  parser.add_argument("--padDrill", type=float, default=1.0)
  parser.add_argument("-o", "--output", required=True)

  args = parser.parse_args()
  createBoard(args)

if __name__ == "__main__":
  main()
