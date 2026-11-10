Two-OPA161x operating-point check

1. Extract these files into the existing project directory beside BCM847.lib, jfex140.lib, and OPA161x.LIB.
2. Open virtual_two_opa_op_check.net in LTspice and run it.
3. Supplies in this check netlist are final DC values, not startup pulses. Original schematic and models are untouched.
4. The seed contains 228 node-voltage hints. It does not force node voltages.
5. On success, LTspice saves its native bias to virtual_native_two_opa_bias.txt.

Auxiliary verification: ngspice 44.2, both full OPA161x models, translated PSpice switch and TABLE syntax. U1 is NOT replaced by an ideal op amp. The seeded complete circuit converged twice.
Expected approximate values: OUT=5.000268 V; VO1=7.516117 V; VO2=7.516016 V; N008=2.499987 V; N009=3.174920 V; both internal MID nodes=4.9999975 V.
Native LTspice validation is still required.

Node names and connectivity must match the supplied Vitual_GND_fixed_cascode.net.
Your source netlist runs to 100 s but saves bias at 1.25 s. This is not the final 100 s state.
