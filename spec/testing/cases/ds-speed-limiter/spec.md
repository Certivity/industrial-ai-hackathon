# spec: SLD-90 Speed Limitation Device for N3 Goods Vehicles

## Product Type

An electronic speed limitation device that actively limits the maximum road speed of a heavy goods vehicle to 90 km/h by controlling engine torque and, where fitted, the transmission/retarder. It is intended for installation as original equipment or as a retrofit unit on diesel or gas-fuelled N3 goods vehicles.

## Vehicle Category

N3 — motor vehicle designed and constructed for the carriage of goods and having a maximum mass exceeding 12 tonnes; the device is fitted to the vehicle's powertrain and driveline on the production line or as a retrofit installation.

## Function

- Continuously measures vehicle speed from wheel-speed and transmission output signals and compares it with the 90 km/h set limit.
- Reduces engine torque (and applies auxiliary braking where available) when the set speed is reached, so the vehicle cannot exceed 90 km/h under its own power.
- Restores full normal control to the driver at speeds below the limit without any manual reset.
- Detects sensor, wiring and supply faults and places the vehicle in a safe, speed-limited state, signalling the fault to the driver.
- Prevents unauthorised adjustment of the set speed by locking the calibration and providing tamper detection.
- Records and stores the set speed, calibration data and fault events for later read-out.
- Operates over the full ambient temperature range and supply voltage range of the vehicle.

## Main Parts

- Electronic control unit (ECU) with microprocessor, non-volatile memory and sealed housing.
- Speed signal interface module (wheel-speed and gearbox output sensor inputs).
- Throttle/accelerator pedal position and engine torque request interface (CAN or analogue).
- Actuator output stage driving the engine torque request and, where fitted, the retarder/auxiliary brake.
- Driver warning lamp and fault indicator output.
- Vehicle speed sensor and sensor harness (if not already present on the vehicle).
- Calibration and diagnostic connector (protected service port).
- Power supply and protection circuit with reverse-polarity and overvoltage protection.

## Materials

Representative values — confirm against actual bill of materials.

| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| ECU housing       | Aluminium alloy or glass-fibre-reinforced PA66 |
| PCB               | FR-4 with copper traces, lead-free HASL finish |
| Connectors        | PBT with gold-plated brass contacts         |
| Harness insulation | XLPE or PVC, tinned copper conductors      |
| Speed sensor body | PBT or PA66, overmoulded                 |
| Warning lamp lens | Polycarbonate                            |
| Fasteners         | Zinc-plated steel or stainless steel       |
| Sealing elements  | Silicone or EPDM gaskets                 |
