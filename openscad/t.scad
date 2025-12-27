$fa=1;
$fs=0.4;

/* [toroid] */
// Distance between flat faces
toroidH=14.0;
// Outside diameter
od=50.8;
// Inside diameter
id=31.8;

/* [windings] */
// Number of turns
turns = 52;
// Width of windings
turnW = 1.3;
/* [solder pad] */
// width
padW = 2.5;
// height
padH = 1.5;
// angle to fit windings
turnsA = 355;

/* [start/end tabs] */
// length
tabL = 10;
// width
tabW = 3;

/* [FPC] */
// dielectric thickness
dielectricT = 0.025;
// copper thickness
cuT = 0.035;
// Thickness overall
fpcT = 0.2;
// Bend radius
bendR = 10*fpcT;


// The toroid itself
difference() {
  cylinder(h=toroidH, d=od, center=true);
  cylinder(h=toroidH+1, d=id, center=true);
}

pitchA = turnsA / turns;
idPitch = PI * id * (360 / turnsA);

for (t=[0:turns-1]) {
  rotate([0,0,360 - turnsA + pitchA*t])
  translate([0,id/2,0])
  color("red")
  sphere(r=turnW/2);
}
