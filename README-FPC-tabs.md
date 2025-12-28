# FPC Design Notes: Stiffeners & Solder Tabs

**Goal:** Create reliable, hand-solderable tabs for connecting the
Flex PCB to the main Rigid PCB without trace cracking or delamination.

## The "Golden Rule" of Stress Relief

The number one failure point in Flex PCBs is the transition from
"Flexible" to "Rigid."

If the **Coverlay** (insulation) stops at the exact same line where
the **Stiffener** starts, all the bending stress is concentrated on
bare, thin copper. It *will* crack.

**The Fix:** The Coverlay must extend *under* the Stiffener.

### The Stack-up Diagram

This is the cross-section of the tab. The "Transition Zone" is where
the magic happens.

```text
       <-- FLEXIBLE CABLE SIDE          RIGID TAB SIDE -->
                                   |
                  (BENDING POINT)  |
                                   v
    TOP SIDE (Stiffener)
-----------------------------------+-----------------------------------
                                   |  [ FR4 Stiffener (0.3mm) ]
                                   |-----------------------------------
                                   |  [ Adhesive ]
               --------------------+-----------------------------------
               [ Coverlay (Insulation) goes UNDER the stiffener!      ]
               -------------------------------------------+   (Open)
                                                          |
----------------------------------------------------------+   (Pad)
[ Copper Trace (1oz)                                      ]
----------------------------------------------------------+
[ Polyimide Base (Substrate)                              ]
----------------------------------------------------------+

                                   |<-- 1.0mm Overlap -->|
                                      (Safe Zone)

```

## Design Checklist (Gerber Setup)

### 1. Stiffener & Coverlay Overlap

* [ ] **Rule:** The Stiffener must overlap the Coverlay by at least
      **0.75mm (30 mils)**.

* [ ] **In CAD:** Your solder mask opening (Coverlay opening) should
      not start until you are **1mm inside** the stiffener outline.

* [ ] **Result:** When the cable bends, it bends against the protected
      sandwich (Stiffener + Coverlay + Copper), not against bare
      copper.

### 2. Stiffener Specs

* **Material:** FR4 (Glass Epoxy).

* **Thickness:** 0.2mm to 0.4mm (Standard usually 0.3mm).

* *Why:* Thick enough to stay flat for soldering, thin enough to keep
  profile low.


* **Layer:** Define on a dedicated Mechanical layer (e.g., `Eco1.User`
  or `User.Comments`) and denote it clearly in fabrication notes.

### 3. Solderability Tips (The "Lap Joint")

Since we are soldering these tabs manually to a base PCB:

* **Orientation:** Pads on Bottom, Stiffener on Top.

* **Via-in-Tab:** Place 1-2 plated vias (0.3mm drill) inside the
  solder pad area of the tab.

* *Benefit:* You can apply the soldering iron to the *top* (Stiffener
  side) of the via. Heat travels down the barrel to the pad on the
  bottom. No need to awkwardly heat the side of the sandwich.



## Summary Table for Manufacturing

| Feature | Specification |
| --- | --- |
| **Flex Copper Weight** | 1oz (Note: Stiffer than 0.5oz, ensure bend radius is large) |
| **Stiffener Type** | FR4 |
| **Stiffener Thickness** | 0.3mm (recommended) |
| **Coverlay Color** | Yellow (Standard) or Black |
| **Surface Finish** | ENIG (Immersion Gold) - Essential for reliable soldering |
