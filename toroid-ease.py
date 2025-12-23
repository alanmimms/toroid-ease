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
  Generate board outline with SHORT flap extensions.
  START flap at first trace start, END flap at last trace end.
  Board width extends to accommodate the last trace end position.
  """
  w = cfg["availableLength"]
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  pitch = cfg["pitch"]
  turnsPerLayer = cfg["turnsPerLayer"]
  traceAngle = cfg["traceAngle"]
  flapDiameter = cfg["flapDiameter"]
  offsets = cfg["offsets"]
  traceWidth = cfg["traceWidth"]
  seriesCount = cfg["seriesCount"]
  parallelCount = cfg["parallelCount"]

  layer = pcbnew.Edge_Cuts

  # Calculate trace geometry
  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  traceLen = h - 2 * marginTop
  dx = traceLen * math.tan(traceAngle)

  # SHORT flap dimensions
  flapH = flapDiameter * 0.6
  neckW = max(traceWidth, 2.5)

  # START at first trace position (series set 0)
  startOffset = offsets[0]
  startX = startOffset + pitch / 2

  # END at last trace end position (last series set)
  lastSetIdx = seriesCount - 1
  endOffset = offsets[lastSetIdx * parallelCount]
  endX = endOffset + (turnsPerLayer - 1) * pitch + pitch / 2 + dx

  # Board width must accommodate the last trace end
  boardW = max(w, endX + neckW / 2 + 0.5)

  # A-edge with START flap
  addLine(board, vec(0, 0), vec(startX - neckW/2, 0), layer)
  addLine(board, vec(startX - neckW/2, 0), vec(startX - neckW/2, -flapH), layer)
  addLine(board, vec(startX - neckW/2, -flapH), vec(startX + neckW/2, -flapH), layer)
  addLine(board, vec(startX + neckW/2, -flapH), vec(startX + neckW/2, 0), layer)
  addLine(board, vec(startX + neckW/2, 0), vec(boardW, 0), layer)

  # Right edge
  addLine(board, vec(boardW, 0), vec(boardW, h), layer)

  # B-edge with END flap
  addLine(board, vec(boardW, h), vec(endX + neckW/2, h), layer)
  addLine(board, vec(endX + neckW/2, h), vec(endX + neckW/2, h + flapH), layer)
  addLine(board, vec(endX + neckW/2, h + flapH), vec(endX - neckW/2, h + flapH), layer)
  addLine(board, vec(endX - neckW/2, h + flapH), vec(endX - neckW/2, h), layer)
  addLine(board, vec(endX - neckW/2, h), vec(0, h), layer)

  # Left edge
  addLine(board, vec(0, h), vec(0, 0), layer)

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
  """
  Generate angled traces using full-turn weaving topology.

  Full-turn weaving: Each complete turn stays on one layer pair, then alternates.
  - Odd turns (1,3,5...): L1||L2 (F_Cu+In1_Cu) at integer positions
  - Even turns (2,4,6...): L3||L4 (In2_Cu+B_Cu) at half-integer positions (offset)

  Each trace is a half-turn (A→B). The B-to-A solder joint completes the turn.
  Vias at A-edge connect between layer pairs for the next turn.

  This keeps all current flowing the same direction around the toroid.
  """
  w = cfg["availableLength"]
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  totalLayers = cfg["totalLayers"]
  parallelCount = cfg["parallelCount"]
  seriesCount = cfg["seriesCount"]
  turnsPerLayer = cfg["turnsPerLayer"]
  pitch = cfg["pitch"]
  traceWidth = cfg["traceWidth"]
  traceAngle = cfg["traceAngle"]
  offsets = cfg["offsets"]

  # Trace margins - stay clear of pads and via areas
  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  marginBottom = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5

  yStart = marginTop
  yEnd = h - marginBottom
  traceLen = yEnd - yStart
  dx = traceLen * math.tan(traceAngle)

  # Map layer index to KiCad layer
  def getKicadLayer(layerIdx):
    if totalLayers <= 2:
      return pcbnew.F_Cu if layerIdx == 0 else pcbnew.B_Cu
    if layerIdx == 0:
      return pcbnew.F_Cu
    elif layerIdx == totalLayers - 1:
      return pcbnew.B_Cu
    else:
      innerLayers = [pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu,
                     pcbnew.In4_Cu, pcbnew.In5_Cu, pcbnew.In6_Cu]
      return innerLayers[layerIdx - 1] if layerIdx - 1 < len(innerLayers) else pcbnew.B_Cu

  # For full-turn weaving with series sets:
  # Each series set gets traces at its offset position
  for setIdx in range(seriesCount):
    offset = offsets[setIdx * parallelCount]

    # Layers in this parallel set
    startLayerIdx = setIdx * parallelCount
    endLayerIdx = startLayerIdx + parallelCount

    for turn in range(turnsPerLayer):
      xBase = offset + turn * pitch + pitch / 2
      xEnd = xBase + dx

      if xBase < 0 or xEnd > w:
        continue

      # All layers in this parallel set get the same trace
      for layerIdx in range(startLayerIdx, endLayerIdx):
        pcbLayer = getKicadLayer(layerIdx)
        addTrack(board, vec(xBase, yStart), vec(xEnd, yEnd), pcbLayer, traceWidth)

def generateBtoAPads(board, cfg):
  """
  Generate B-to-A solder pads.
  CRITICAL: Bn.x MUST equal A(n+1).x for the helix to work when wrapped!
  - A-pads on F_Cu at trace start positions
  - B-pads on B_Cu at positions matching the NEXT turn's A-pad
  - Skip B(turnsPerLayer-2) because END replaces it
  """
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  turnsPerLayer = cfg["turnsPerLayer"]
  pitch = cfg["pitch"]
  btoAPadWidth = cfg["btoAPadWidth"]
  traceWidth = cfg["traceWidth"]
  offsets = cfg["offsets"]

  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  fCuOffset = offsets[0]

  # Pad Y positions
  aPadY = marginTop - btoAPadHeight / 2 - 0.1
  bPadY = h - marginTop + btoAPadHeight / 2 + 0.1

  padW = max(btoAPadWidth, traceWidth)
  padH = max(btoAPadHeight, 1.5)

  for turn in range(turnsPerLayer):
    # A-pad positions: An at turn n start
    # An.x = fCuOffset + n*pitch + pitch/2
    if turn > 0:  # Skip A0, that's START
      aX = fCuOffset + turn * pitch + pitch / 2
      addSmdPad(board, vec(aX, aPadY), f"A{turn}", padW, padH, pcbnew.F_Cu)

    # B-pad positions: Bn.x MUST equal A(n+1).x for alignment when wrapped
    # Bn.x = A(n+1).x = fCuOffset + (n+1)*pitch + pitch/2
    # Skip B(turnsPerLayer-2) = B8 because END replaces it
    if turn < turnsPerLayer - 2:  # Skip last TWO: B8 (END) and B9 (doesn't exist)
      bX = fCuOffset + (turn + 1) * pitch + pitch / 2  # Same X as A(turn+1)
      addSmdPad(board, vec(bX, bPadY), f"B{turn}", padW, padH, pcbnew.B_Cu)

def generateStartEndConnections(board, cfg):
  """
  Connect START/END THT pads to their traces.

  For full-turn weaving:
  - START connects to first trace of first series set (L1||L2) at A-edge
  - END connects to last trace of last series set at B-edge
  """
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  pitch = cfg["pitch"]
  turnsPerLayer = cfg["turnsPerLayer"]
  traceWidth = cfg["traceWidth"]
  traceAngle = cfg["traceAngle"]
  flapDiameter = cfg["flapDiameter"]
  offsets = cfg["offsets"]
  seriesCount = cfg["seriesCount"]
  parallelCount = cfg["parallelCount"]

  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  traceLen = h - 2 * marginTop
  dx = traceLen * math.tan(traceAngle)
  flapH = flapDiameter * 0.6

  # START: first trace of series set 0 at A-edge
  startOffset = offsets[0]
  startX = startOffset + pitch / 2
  startPadY = -flapH / 2
  addTrack(board, vec(startX, marginTop), vec(startX, startPadY),
           pcbnew.F_Cu, traceWidth)

  # END: last trace of last series set at B-edge
  # The last series set's offset
  lastSetIdx = seriesCount - 1
  endOffset = offsets[lastSetIdx * parallelCount]
  # Last trace end X position
  lastTraceEndX = endOffset + (turnsPerLayer - 1) * pitch + pitch / 2 + dx
  lastTraceEndY = h - marginTop

  # END pad position - at the trace end X, extending below B-edge
  endPadX = lastTraceEndX
  endPadY = h + flapH / 2

  # Simple vertical connection from trace end to pad
  addTrack(board, vec(lastTraceEndX, lastTraceEndY), vec(endPadX, endPadY),
           pcbnew.B_Cu, traceWidth)

def generateFlaps(board, cfg):
  """Add THT pads for START and END flaps."""
  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  pitch = cfg["pitch"]
  turnsPerLayer = cfg["turnsPerLayer"]
  traceAngle = cfg["traceAngle"]
  flapDiameter = cfg["flapDiameter"]
  padSize = cfg["padSize"]
  padDrill = cfg["padDrill"]
  taps = cfg["taps"]
  offsets = cfg["offsets"]
  seriesCount = cfg["seriesCount"]
  parallelCount = cfg["parallelCount"]

  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  traceLen = h - 2 * marginTop
  dx = traceLen * math.tan(traceAngle)
  flapH = flapDiameter * 0.6

  # START pad - at first trace of series set 0
  startOffset = offsets[0]
  startX = startOffset + pitch / 2
  startY = -flapH / 2
  addThtPad(board, vec(startX, startY), "START", padSize, padDrill)
  addText(board, vec(startX, startY + padSize/2 + 0.5), "S",
          pcbnew.F_SilkS, textHeight * 0.4, textThickness)

  # END pad - at last trace end of last series set
  lastSetIdx = seriesCount - 1
  endOffset = offsets[lastSetIdx * parallelCount]
  endX = endOffset + (turnsPerLayer - 1) * pitch + pitch / 2 + dx
  endY = h + flapH / 2
  addThtPad(board, vec(endX, endY), "END", padSize, padDrill)
  addText(board, vec(endX, endY - padSize/2 - 0.5), "E",
          pcbnew.B_SilkS, textHeight * 0.4, textThickness)

  # TAP pads (if any)
  for tapTurn in taps:
    if tapTurn < 1 or tapTurn > turnsPerLayer:
      print(f"Warning: Tap {tapTurn} out of range")
      continue
    tapX = startOffset + (tapTurn - 1) * pitch + pitch / 2
    addThtPad(board, vec(tapX, startY), f"T{tapTurn}", padSize, padDrill)

def generateViaFarms(board, cfg):
  """
  Via farms for full-turn weaving topology.

  Full-turn weaving current path:
  - Turn N on L1||L2: A-pad → trace (A→B) → B-pad → *solder wraps* → A-pad
  - Turn N+1 on L3||L4: A-pad → trace (A→B) → B-pad → *solder wraps* → A-pad
  - Alternating between layer pairs

  Via requirements:
  1. A-edge (A-pads): Through-hole vias connect all layers - transfers current
     from incoming solder joint (F_Cu) to the next turn's layer pair

  2. B-edge (B-pads): Need to get signal to B_Cu for solder pad
     - L1||L2 traces on F_Cu/In1_Cu need vias to B_Cu
     - L3||L4 traces on In2_Cu/B_Cu already have B_Cu access

  3. Parallel stitching: Within each layer pair, vias connect parallel layers
  """
  totalLayers = cfg["totalLayers"]
  parallelCount = cfg["parallelCount"]
  seriesCount = cfg["seriesCount"]

  # Only need vias if we have multiple layers
  if totalLayers < 2:
    return

  h = cfg["fpcHeight"]
  radial = cfg["radialThickness"]
  turnsPerLayer = cfg["turnsPerLayer"]
  pitch = cfg["pitch"]
  traceAngle = cfg["traceAngle"]
  offsets = cfg["offsets"]
  viaDrill = cfg["viaDrill"]
  viaSize = cfg["viaSize"]
  viasNeeded = cfg["viasNeeded"]

  # Via farm dimensions - sized for current capacity
  viaCols = max(2, math.ceil(math.sqrt(viasNeeded)))
  viaRows = math.ceil(viasNeeded / viaCols)
  viaSpacing = viaSize + 0.3

  marginTop = radial * 0.3 + padToEdgeGap + btoAPadHeight + 0.5
  traceLen = h - 2 * marginTop
  dx = traceLen * math.tan(traceAngle)

  # For each series set, place via farms
  for setIdx in range(seriesCount):
    offset = offsets[setIdx * parallelCount]

    for turn in range(turnsPerLayer):
      traceStartX = offset + turn * pitch + pitch / 2
      traceEndX = traceStartX + dx

      # Via farm at A-edge - through-hole to connect all layers
      # This allows current transfer between layer pairs
      # Skip for first trace of first set (START handles it)
      if not (setIdx == 0 and turn == 0):
        viaFarmY = marginTop - 0.8
        for row in range(viaRows):
          for col in range(viaCols):
            viaX = traceStartX - (viaCols - 1) * viaSpacing / 2 + col * viaSpacing
            viaY = viaFarmY - row * viaSpacing

            via = pcbnew.PCB_VIA(board)
            via.SetPosition(vec(viaX, viaY))
            via.SetDrill(toNm(viaDrill))
            via.SetWidth(toNm(viaSize))
            via.SetViaType(pcbnew.VIATYPE_THROUGH)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            board.Add(via)

      # Via farm at B-edge - connects trace layers to B_Cu for solder pad
      # Skip for last trace of last set (END handles it)
      if not (setIdx == seriesCount - 1 and turn == turnsPerLayer - 1):
        viaFarmY = h - marginTop + 0.8
        for row in range(viaRows):
          for col in range(viaCols):
            viaX = traceEndX - (viaCols - 1) * viaSpacing / 2 + col * viaSpacing
            viaY = viaFarmY + row * viaSpacing

            via = pcbnew.PCB_VIA(board)
            via.SetPosition(vec(viaX, viaY))
            via.SetDrill(toNm(viaDrill))
            via.SetWidth(toNm(viaSize))
            via.SetViaType(pcbnew.VIATYPE_THROUGH)
            via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
            board.Add(via)

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
  # No courtyard - this is a standalone FPC, not a component

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
