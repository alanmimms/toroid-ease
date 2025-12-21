### Project: Toroid-Ease (NexRig FPC Inductor Generator)

#### 1. Abstract

**Toroid-Ease** is a Python-based design automation tool for KiCad 9.
  It generates manufacturing files for **Flexible Printed Circuits
  (FPC)** that serve as high-performance, repeatable toroidal inductor
  windings. Instead of winding magnet wire by hand around a toroid
  core, this tool generates a flat FPC strip that rolls into a
  cylinder and locks into shape, creating a precision solenoid "liner"
  that sits inside standard powdered-iron RF cores (e.g., T-68, T-50).

This component was created along the way to building the larger
**NexRig** project (an Envelope Elimination and Restoration HF
transceiver).

#### 2. The Problem & Solution

* **The Problem:** Hand-winding toroids is tedious, inconsistent, and
    difficult to reproduce exactly across multiple units. High-current
    windings require thick wire that is hard to manage.

* **The Solution:** An FPC "insert" provides exact inductance,
    consistent stray capacitance, and high current capacity (via wide
    flat tracks) in a package that can be mass-manufactured.

#### 3. Mechanical & Electrical Geometry

The generator creates a 2-layer FPC strip with the following features:

* **Form Factor:** A rectangular strip sized exactly to the **Inner
    Circumference** of a specific magnetic core (e.g., T-68).

* **Winding Topology:**

* **Tracks:** Vertical parallel copper tracks run from top to bottom,
    forming a solenoid coil when the strip is rolled into a tube.

* **Turns:** The script auto-calculates the pitch and track width to
    fit the requested number of turns () and Current () within the
    core's ID.


* **Locking Mechanism (The "Coffee Sleeve"):**

* **Edge B (Top):** Features **Trapezoidal Tabs** extending outwards.

* **Edge A (Bottom):** Features **Rectangular Slits** (slots) cut into
    the PCB body.

* **Assembly:** When rolled, the tabs slide into the slots to
    mechanically lock the cylinder shape before insertion into the
    core.


* **Termination:**

* **Castellated Pads:** The Start and End connections are essentially
    plated half-holes (castellations) with a specific "U-shaped" edge
    cut. This allows the coil to be soldered vertically onto a
    motherboard or wired easily.



#### 4. The Software (`toroid-ease.py`)

The tool is a CLI script using the **KiCad 9 Python API**.

* **Inputs:**
* `-c`: Core Type (e.g., `T-68`).
* `-t`: Number of Turns (e.g., `54`).
* `-a`: Target Current in Amps (e.g., `3.5`) — used to calculate track width.
* `--angle`: Angular coverage (default 360°).


* **Logic:**

1. **Physics Check:** Calculates if the requested turns + required
copper width fit inside the core.

2. **Rejection:** If the design is physically impossible (tracks would
overlap), it aborts and suggests a larger core or fewer turns.

3. **Generation:** Draws the Board Outline, Copper Tracks, Tabs,
Slits, and Castellation cuts using KiCad's geometric primitives
(`PCB_SHAPE`, `SHAPE_T_SEGMENT`).


* **Output:**
* A `.kicad_pcb` board file. This format is used because the FPC is a standalone product to be manufactured, not just a footprint on another board.



#### 5. Current Status (As of Dec 20, 2025)

* **Functionality:** The script works for KiCad 9. It successfully
    handles the tab/slot geometry, castellation cuts, and physics
    validation.

* **Known Constraints:**

* **Gap:** Hardcoded safety gap of 0.15mm (6 mil) for FPC fabrication.

* **Density:** It enforces a strict "No Overlap" rule.


* **Immediate Next Step:** Validating the generated design in KiCad's
    DRC to ensure the calculated gaps are truly manufacturable,
    followed by implementing **Panelization** (placing multiple strips
    on one manufacturing panel).

#### 6. Example Usage

```bash
./toroid-ease.py -t 54 -c T-68 -a 3.5 -o t68-54t-3.5a.kicad_pcb

```

*(If the coil is too dense, the script will reject it and tell you the required Core ID size.)*
