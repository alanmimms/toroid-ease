// ==============================================================================
// NEXRIG FPC TOROID - V8 (RESTORED GEOMETRY & FIXED FOLDS)
// ==============================================================================

mode = "3D";
Show_Core = true;       // Yellow
Show_Substrate = true;  // Clear/White
Show_Copper = true;     // Saturated Colors
Show_Solder = true;     // Silver

// --- Physical Constants ---
Core_OD = 50.80;
Core_ID = 31.75;
Core_H  = 13.97;
Corner_R = 2.0;

N_turns = 52;
Trace_W = 1.5;          // Copper Width
Cu_Thick = 0.035;       // 1 oz Copper
Subst_Thick = 0.18;     // Polyimide
Solder_Gap = 0.05;      // Solder Joint

Flag_W = 2.5;           // Pad Width
Flag_H = 3.0;           // Pad Length
Bend_Rad = 1.2;         // Corner Bend Radius

// --- Derived Geometry ---
R_OD = Core_OD / 2;
R_ID = Core_ID / 2;
H_Half = Core_H / 2;
R_Spine = R_ID + 0.1;   // Spine sits on ID wall

Deg_Per_Turn = 360 / N_turns;
OD_Pitch = (PI * Core_OD) / N_turns;
Shift_Ang = ((OD_Pitch / 2) / R_OD) * (180/PI);

// Substrate Width (Calculated for Visible Slits)
// Gap = 0.25mm
Subst_W_ID = ((PI*Core_ID)/N_turns) - 0.25; 
Subst_W_OD = ((PI*Core_OD)/N_turns) - 0.25;

// ==============================================================================
// MAIN ASSEMBLY
// ==============================================================================

if (mode == "3D") {
    if (Show_Core) 
        color([1.0, 0.9, 0.0, 1.0]) T200_Core_Precise();

    for (i = [0 : N_turns-1]) {
        rotate([0, 0, i * Deg_Per_Turn]) 
            OneTurn_Physical_V8(i);
    }
} else {
    projection(cut = false) Flat_Pattern_2D();
}

// ==============================================================================
// TURN MODULE
// ==============================================================================

module OneTurn_Physical_V8(index) {
    
    // Saturated Palette
    palette = [
        [1, 0, 0], [0, 0.8, 0], [0, 0, 1], 
        [0, 0.8, 0.8], [1, 0, 1], [1, 0.5, 0], 
        [0.6, 0, 0.8], [0, 0.4, 0.8], [1, 0, 0.4]
    ];
    turn_color = palette[index % len(palette)];

    // --- STACK-UP CALCULATIONS ---
    // We define the radial position of every layer at the OD Face (Equator)
    
    // 1. Bottom Petal (Folds UP from bottom)
    //    - Substrate sits on Core (R_OD)
    //    - Copper sits on Substrate (R_OD + Subst)
    r_bot_subst = R_OD;
    r_bot_cu    = R_OD + Subst_Thick;
    
    // 2. Solder Joint (Between Copper layers)
    r_solder    = r_bot_cu + Cu_Thick;
    
    // 3. Top Petal (Folds DOWN from top)
    //    - Copper Pad sits on Solder (R_Solder + Gap)
    //    - Substrate sits on Copper (R_Solder + Gap + Cu)
    r_top_cu    = r_solder + Solder_Gap;
    r_top_subst = r_top_cu + Cu_Thick;

    // --- SUBSTRATE RENDER ---
    if (Show_Substrate) {
        color([0.95, 0.95, 0.95, 0.3]) {
            
            // 1. Main Body (ID Spine + Top/Bottom Flat Faces)
            Generate_Continuous_Strip(
                Width_ID=Subst_W_ID, Width_OD=Subst_W_OD, 
                Thick=Subst_Thick, R_Base=R_OD, 
                Is_Copper=false
            );

            // 2. Top Flap (Outer Layer)
            Generate_Flap_Fold(
                Is_Top=true, Width=Subst_W_OD, Thick=Subst_Thick,
                R_Surface=r_top_subst // Sits on outside of stack
            );

            // 3. Bottom Flap (Inner Layer)
            Generate_Flap_Fold(
                Is_Top=false, Width=Subst_W_OD, Thick=Subst_Thick,
                R_Surface=r_bot_subst // Sits on core
            );
        }
    }

    // --- COPPER RENDER ---
    if (Show_Copper) {
        color(turn_color) {
            
            // 1. Main Body (Spine + Faces)
            // Copper is on the "Top" layer of the FPC.
            // On the flat faces, it sits ON TOP of the substrate.
            // R_Face = R_OD + Subst_Thick
            Generate_Continuous_Strip(
                Width_ID=Trace_W, Width_OD=Trace_W, 
                Thick=Cu_Thick, R_Base=R_OD + Subst_Thick, 
                Is_Copper=true
            );

            // 2. Top Flap Copper (The Pad + Trace)
            // The TRACE is on the outer face (r_top_cu + Cu?). 
            // The PAD is on the inner face (r_top_cu).
            // For this model, we draw the continuous solid connecting them.
            Generate_Flap_Fold(
                Is_Top=true, Width=Trace_W, Thick=Cu_Thick,
                R_Surface=r_top_cu, // Sits at interface
                Pad_Width=Flag_W
            );

            // 3. Bottom Flap Copper (The Pad + Trace)
            Generate_Flap_Fold(
                Is_Top=false, Width=Trace_W, Thick=Cu_Thick,
                R_Surface=r_bot_cu, // Sits at interface
                Pad_Width=Flag_W
            );
        }
    }

    // --- SOLDER JOINT ---
    if (Show_Solder) {
        color([0.8, 0.8, 0.8, 1.0]) {
            Generate_Solder_Block(R_Ref=r_solder);
        }
    }
}

// ==============================================================================
// GEOMETRY GENERATORS
// ==============================================================================

module Generate_Continuous_Strip(Width_ID, Width_OD, Thick, R_Base, Is_Copper) {
    
    // Correct ID Radius:
    // Substrate sits on R_ID. Copper sits on R_ID - Subst (if inside).
    // Actually, ID Spine is inside hole. 
    // Substrate touches R_ID wall. Copper is "inside" the substrate loop.
    // R_Spine_Eff = R_ID - (Is_Copper ? Subst_Thick : 0);
    // Let's use R_Spine global which is slightly inside hole.
    r_spine = R_Spine - (Is_Copper ? Subst_Thick : 0);

    // Z-Offset for Flat Faces:
    // Substrate sits on +/- H_Half.
    // Copper sits on +/- (H_Half + Subst).
    z_face_top = H_Half + (Is_Copper ? Subst_Thick : 0);
    z_face_btm = -H_Half - (Is_Copper ? Subst_Thick : 0);
    
    // --- 1. ID SPINE ---
    hull() {
        translate([r_spine, -Width_ID/2, -H_Half]) cube([Thick, Width_ID, 0.01]);
        translate([r_spine, -Width_ID/2,  H_Half]) cube([Thick, Width_ID, 0.01]);
    }

    // --- 2. TOP FACE (Radial Spoke) ---
    hull() {
        // ID Corner
        translate([r_spine, -Width_ID/2, z_face_top]) 
            cube([Thick, Width_ID, Thick]);
        
        // OD Corner (Stop at R_Base)
        // This was missing in V7!
        translate([R_Base, -Width_OD/2, z_face_top]) 
            cube([Thick, Width_OD, Thick]);
    }

    // --- 3. BOTTOM FACE (Radial Spoke) ---
    hull() {
        // ID Corner
        translate([r_spine, -Width_ID/2, z_face_btm - Thick]) 
            cube([Thick, Width_ID, Thick]);
        
        // OD Corner
        translate([R_Base, -Width_OD/2, z_face_btm - Thick]) 
            cube([Thick, Width_OD, Thick]);
    }
}

module Generate_Flap_Fold(Is_Top, Width, Thick, R_Surface, Pad_Width=0) {
    
    // Angle: Top folds Right (-Shift), Bottom folds Left (+Shift)
    angle = Is_Top ? -Shift_Ang : Shift_Ang;
    
    // Z-Start: Top starts at H_Half (plus stack), Bottom starts at -H_Half
    // We need to match the R_Surface geometry
    // If we are Top Flap, we start at Z = +H_Half + (R_Surface - R_OD) roughly
    // Let's rely on the R_Surface to define the radial "Wall"
    
    z_hinge = Is_Top ? H_Half : -H_Half;
    z_dir   = Is_Top ? 1 : -1; // 1 = Up, -1 = Down (relative to center)
    
    eff_width = (Pad_Width > 0) ? Pad_Width : Width;

    rotate([0, 0, angle]) {
        
        // --- 1. THE BEND (Corner Hinge) ---
        // This hull connects the Flat Face (Horizontal) to the Vertical Drop
        hull() {
            // A. Face Anchor (Horizontal)
            // Sit exactly at R_OD, Z_Hinge (plus stack offset)
            // We use R_Surface as the 'Vertical' plane, so we back up slightly for the horizontal anchor
            translate([R_Surface - Bend_Rad, -Width/2, z_hinge + (z_dir * (R_Surface - R_OD))])
                cube([Thick, Width, Thick]);

            // B. The Bulge (45 deg)
            translate([R_Surface + Bend_Rad*0.3, -Width/2, z_hinge + (z_dir * Bend_Rad*0.3)])
                cube([Thick, Width, Thick]);
                
            // C. The Vertical Start
            translate([R_Surface, -Width/2, z_hinge + (z_dir * 2.0)]) // 2mm down/up
                cube([Thick, Width, Thick]);
        }
        
        // --- 2. THE DROP (Vertical Leg) ---
        hull() {
             // Top of Leg
            translate([R_Surface, -Width/2, z_hinge + (z_dir * 2.0)]) 
                cube([Thick, Width, Thick]);
            
            // Bottom of Leg (Top of Pad)
            pad_top_z = Is_Top ? Flag_H/2 : -Flag_H/2;
            translate([R_Surface, -eff_width/2, pad_top_z]) 
                cube([Thick, eff_width, Thick]);
        }
        
        // --- 3. THE PAD (Equator) ---
        // Only draw if we have a pad width
        if (Pad_Width > 0) {
            translate([R_Surface, -eff_width/2, -Flag_H/2]) 
                cube([Thick, eff_width, Flag_H]);
        }
    }
}

module Generate_Solder_Block(R_Ref) {
    rotate([0, 0, -Shift_Ang]) {
        translate([R_Ref, -Flag_W/2 + 0.1, -Flag_H/2 + 0.1]) 
            cube([Solder_Gap, Flag_W - 0.2, Flag_H - 0.2]);
    }
}

module T200_Core_Precise() {
     CrossSection_W = (Core_OD - Core_ID) / 2;
     Center_R = (Core_OD + Core_ID) / 4;
     rotate_extrude($fn=100) translate([Center_R, 0, 0]) difference() {
         square([CrossSection_W, Core_H], center=true);
         translate([CrossSection_W/2, Core_H/2]) circle(r=Corner_R, $fn=30);
         translate([-CrossSection_W/2, Core_H/2]) circle(r=Corner_R, $fn=30);
         translate([-CrossSection_W/2, -Core_H/2]) circle(r=Corner_R, $fn=30);
         translate([CrossSection_W/2, -Core_H/2]) circle(r=Corner_R, $fn=30);
     }
}

module Flat_Pattern_2D() {}