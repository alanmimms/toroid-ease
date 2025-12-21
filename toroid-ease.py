#!/usr/bin/env python3

import sys
import argparse
import math
import pcbnew
import os

# --- Constants & Config ---
MIN_TRACK_GAP_MM = 0.15      # 6 mil gap (Standard Fab capability)
MM_PER_AMP = 0.3             # Copper width estimation (Adjust for 1oz/2oz)
LENGTH_SAFETY_FACTOR = 0.95  # Use 95% of ID circumference to avoid overlap binding

# Core Dictionary: Name -> (Outer Diameter mm, Inner Diameter mm, Height mm)
CORES = {
    "T-68": (17.5, 9.4, 4.8),
    "T-50": (12.7, 7.7, 4.8),
    "T-37": (9.5, 5.2, 3.25),
    "T-200": (50.8, 31.8, 14.0)
}

# --- Compatibility Wrapper ---
if hasattr(pcbnew, 'FPID'):
    PCB_FPID = pcbnew.FPID
elif hasattr(pcbnew, 'LIB_ID'):
    PCB_FPID = pcbnew.LIB_ID
else:
    PCB_FPID = None

def create_rolled_fpc_board(args):
    # --- 1. Validate Inputs & Physics ---
    if args.core not in CORES:
        print(f"Error: Core {args.core} not found. Available: {list(CORES.keys())}")
        sys.exit(1)
        
    od, id_mm, height_mm = CORES[args.core]
    
    # Parse Ampacity
    current_amps = float(args.ampacity) if args.ampacity else 0.5
    needed_track_width = current_amps * MM_PER_AMP
    
    # Parse Angle (Coverage)
    # Default to 360 (full wrap) if not specified
    target_angle = float(args.angle) if args.angle else 360.0
    
    # Calculate Available Space
    # Full circumference of the inner surface
    full_inner_circ = id_mm * math.pi * LENGTH_SAFETY_FACTOR
    
    # Effective length we are allowed to use based on requested angle
    available_length = full_inner_circ * (target_angle / 360.0)
    
    # Calculate Required Space
    num_turns = int(args.turns)
    # Each turn needs: Track Width + Gap
    pitch_needed = needed_track_width + MIN_TRACK_GAP_MM
    total_len_needed = pitch_needed * num_turns
    
    # --- FAILURE CHECK ---
    if total_len_needed > available_length:
        print("\n!!! DESIGN REJECTED: COIL WILL NOT FIT !!!")
        print(f"  Core: {args.core} (ID: {id_mm}mm)")
        print(f"  Turns: {num_turns}")
        print(f"  Current: {current_amps}A -> Requires {needed_track_width:.2f}mm track width")
        print(f"  Min Gap: {MIN_TRACK_GAP_MM}mm")
        print("-" * 40)
        print(f"  Available Arc Length ({target_angle}°): {available_length:.2f} mm")
        print(f"  Required Arc Length:                 {total_len_needed:.2f} mm")
        
        # Calculate how much "Over" we are
        # Angle required to fit this on the CURRENT core
        angle_required = (total_len_needed / full_inner_circ) * 360.0
        
        # ID required to fit this in the TARGET angle
        # new_circ = total_len_needed * (360/target_angle)
        # new_id = new_circ / (pi * safety)
        circ_required_for_angle = total_len_needed * (360.0 / target_angle)
        id_required = circ_required_for_angle / (math.pi * LENGTH_SAFETY_FACTOR)
        
        print(f"\n  >>> To make this fit, you need:")
        print(f"      1. A larger coverage angle: {angle_required:.1f}° (on this core)")
        print(f"      2. OR a larger Core ID:     {id_required:.2f} mm")
        sys.exit(1)
    
    # --- Pass: Calculate Final Dimensions ---
    # We fit! Now we determine exact pitch to fill the space (or just use tight pack?)
    # Usually better to spread them out to fill the 'available_length' exactly?
    # Yes, distribute turns evenly over the target angle.
    
    actual_pitch = available_length / num_turns
    # Recalculate track width to maximize copper? 
    # Or stick to the requirement? 
    # Better to expand track width to fill the gap, leaving only MIN_GAP.
    # This reduces resistance.
    final_track_width = actual_pitch - MIN_TRACK_GAP_MM
    
    print(f"Design Accepted.")
    print(f"  Track Width: {final_track_width:.3f} mm (Req: {needed_track_width:.2f})")
    print(f"  Gap:         {MIN_TRACK_GAP_MM} mm")
    print(f"  Total Width: {available_length:.2f} mm")

    # --- 2. Board Setup ---
    board = pcbnew.BOARD()
    lib_name = "ToroidWinding"
    fp_name = f"FPC_Winding_{args.core}_{args.turns}T"
    
    footprint = pcbnew.FOOTPRINT(board)
    footprint.SetValue(fp_name)
    footprint.SetReference("L1")
    
    if PCB_FPID:
        try:
            footprint.SetFPID(PCB_FPID(f"{lib_name}:{fp_name}"))
        except:
            pass 
            
    board.Add(footprint)
    
    # Board Dimensions
    pcb_width = available_length
    pcb_height = 25.0 # Default length of the solenoid cylinder
    
    # --- 3. Geometry Helpers ---
    def to_nm(mm): return int(mm * 1e6)
    
    def add_line(p1, p2, layer, width=0.1):
        seg = pcbnew.PCB_SHAPE(footprint)
        seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
        seg.SetStart(p1)
        seg.SetEnd(p2)
        seg.SetLayer(layer)
        seg.SetWidth(to_nm(width))
        footprint.Add(seg)

    def add_pad(pos, name, size_mm):
        pad = pcbnew.PAD(footprint)
        pad.SetSize(pcbnew.VECTOR2I(to_nm(size_mm), to_nm(size_mm)))
        pad.SetDrillSize(pcbnew.VECTOR2I(to_nm(size_mm*0.6), to_nm(size_mm*0.6)))
        pad.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        pad.SetAttribute(pcbnew.PAD_ATTRIB_PTH)
        pad.SetLayerSet(pcbnew.LSET.AllCuMask())
        pad.SetPosition(pos)
        pad.SetName(str(name))
        pad.SetNumber(str(name))
        footprint.Add(pad)
        return pad

    # --- 4. Generate Windings ---
    
    # Margins for Tabs/Slots
    slot_depth = 2.0
    margin_top = 1.0
    margin_bot = slot_depth + 1.0
    
    # Start/End Pads
    start_x = actual_pitch / 2.0
    start_y = pcb_height - 1.5
    start_pos = pcbnew.VECTOR2I(to_nm(start_x), to_nm(start_y))
    add_pad(start_pos, "1", 2.0)
    
    end_x = pcb_width - (actual_pitch / 2.0)
    end_y = 1.5
    end_pos = pcbnew.VECTOR2I(to_nm(end_x), to_nm(end_y))
    add_pad(end_pos, "2", 2.0)
    
    # Tracks
    layer_cu = pcbnew.F_Cu
    for i in range(num_turns):
        x_c = (i + 0.5) * actual_pitch
        p_top = pcbnew.VECTOR2I(to_nm(x_c), to_nm(margin_top))
        p_bot = pcbnew.VECTOR2I(to_nm(x_c), to_nm(pcb_height - margin_bot))
        add_line(p_top, p_bot, layer_cu, final_track_width)
        
    # Connect Pads
    add_line(start_pos, pcbnew.VECTOR2I(to_nm(start_x), to_nm(pcb_height - margin_bot)), layer_cu, final_track_width)
    add_line(end_pos, pcbnew.VECTOR2I(to_nm(end_x), to_nm(margin_top)), layer_cu, final_track_width)
    
    # --- 5. Generate Edge Cuts & Mechanicals ---
    
    # Params
    num_tabs = 10
    tab_height = 3.0
    tab_w_base = 3.0
    tab_w_tip = 1.8
    slot_clearance = 0.2
    
    # Build Outline Points
    pts = []
    
    # Start (0,0)
    pts.append(pcbnew.VECTOR2I(0, 0))
    
    # Top Edge (Tabs)
    tab_pitch = pcb_width / num_tabs
    for t in range(num_tabs):
        cx = (t + 0.5) * tab_pitch
        xl = cx - (tab_w_base/2.0)
        xr = cx + (tab_w_base/2.0)
        txl = cx - (tab_w_tip/2.0)
        txr = cx + (tab_w_tip/2.0)
        
        pts.append(pcbnew.VECTOR2I(to_nm(xl), 0))
        pts.append(pcbnew.VECTOR2I(to_nm(txl), to_nm(-tab_height)))
        pts.append(pcbnew.VECTOR2I(to_nm(txr), to_nm(-tab_height)))
        pts.append(pcbnew.VECTOR2I(to_nm(xr), 0))
        
    pts.append(pcbnew.VECTOR2I(to_nm(pcb_width), 0))
    pts.append(pcbnew.VECTOR2I(to_nm(pcb_width), to_nm(pcb_height)))
    
    # Bottom Edge (Slits)
    slit_w = tab_w_base + slot_clearance
    for t in range(num_tabs - 1, -1, -1):
        cx = (t + 0.5) * tab_pitch
        xl = cx - (slit_w/2.0)
        xr = cx + (slit_w/2.0)
        
        pts.append(pcbnew.VECTOR2I(to_nm(xr), to_nm(pcb_height)))
        pts.append(pcbnew.VECTOR2I(to_nm(xr), to_nm(pcb_height - slot_depth)))
        pts.append(pcbnew.VECTOR2I(to_nm(xl), to_nm(pcb_height - slot_depth)))
        pts.append(pcbnew.VECTOR2I(to_nm(xl), to_nm(pcb_height)))
        
    pts.append(pcbnew.VECTOR2I(0, to_nm(pcb_height)))
    pts.append(pcbnew.VECTOR2I(0, 0))
    
    # Draw Edge Cuts
    layer_edge = pcbnew.Edge_Cuts
    for i in range(len(pts)-1):
        add_line(pts[i], pts[i+1], layer_edge)

    # U-Cuts for Castellations
    def get_u_cut_points(center_pos, is_top_edge):
        r = 1.0 
        cx, cy = center_pos.x, center_pos.y
        offset = to_nm(r)
        if is_top_edge:
            return [
                pcbnew.VECTOR2I(cx - offset, 0),
                pcbnew.VECTOR2I(cx - offset, offset),
                pcbnew.VECTOR2I(cx + offset, offset),
                pcbnew.VECTOR2I(cx + offset, 0)
            ]
        else:
            h = to_nm(pcb_height)
            return [
                pcbnew.VECTOR2I(cx - offset, h),
                pcbnew.VECTOR2I(cx - offset, h - offset),
                pcbnew.VECTOR2I(cx + offset, h - offset),
                pcbnew.VECTOR2I(cx + offset, h)
            ]

    u_top = get_u_cut_points(end_pos, True)
    for i in range(len(u_top)-1):
        add_line(u_top[i], u_top[i+1], layer_edge)

    u_bot = get_u_cut_points(start_pos, False)
    for i in range(len(u_bot)-1):
        add_line(u_bot[i], u_bot[i+1], layer_edge)
        
    # --- 6. Save ---
    out_file = args.output
    if out_file.endswith(".kicad_mod"):
        out_file = out_file.replace(".kicad_mod", ".kicad_pcb")
        
    if os.path.exists(out_file):
        os.remove(out_file)
        
    pcbnew.SaveBoard(out_file, board)
    print(f"Created {out_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--turns", required=True)
    parser.add_argument("-c", "--core", required=True)
    parser.add_argument("-a", "--ampacity", help="Current in Amps (default 0.5)")
    parser.add_argument("--angle", help="Target Coverage Angle (default 360)")
    parser.add_argument("-o", "--output", required=True)
    
    args = parser.parse_args()
    create_rolled_fpc_board(args)
