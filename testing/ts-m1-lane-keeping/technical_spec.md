# spec: Automated Lane Keeping System for Motorway Driving

## Product Type

An automated driving system that, when activated, continuously steers and maintains the vehicle within its motorway lane at speeds up to the system limit, under the supervision of a fallback-ready driver.

## Vehicle Category

M1 (passenger car), fitted to a vehicle equipped with electric power steering, a forward-looking camera and/or radar, and a driver monitoring interface on the vehicle CAN bus.

## Function

- Keeps the vehicle centred in the detected lane by commanding steering torque/angle through the electric power steering.
- Controls vehicle speed up to a defined maximum (e.g. 60 km/h) and maintains a safe following distance.
- Detects driver availability and issues escalating warnings and a minimal-risk manoeuvre if the driver does not respond.
- Performs a minimal-risk stop within its lane when the driver fails to take over.
- Provides a human-machine interface showing system status, availability and activation state.
- Records and reports operational data (e.g. event data recorder / DSSAD) for incident reconstruction.

## Main Parts

- Forward camera module with image processing ECU.
- Radar or LiDAR sensor (optional redundancy).
- Central automated driving control unit (ALKS ECU).
- Steering actuation interface to the electric power steering.
- Driver monitoring system (in-cabin camera and/or steering-torque sensing).
- HMI: cluster indicators, warnings, activation buttons.
- Data storage device (DSSAD / event data recorder).

## Materials

Representative values — confirm against actual bill of materials.

| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| Camera housing    | PA66-GF30, aluminium alloy                  |
| Radar housing     | PBT, aluminium die-cast                     |
| ALKS ECU housing  | Aluminium alloy, steel sheet                |
| PCB assemblies    | FR-4, copper, solder (SAC)                  |
| Wiring harness    | Copper, PVC/XLPE insulation                 |
| HMI display       | Glass, polycarbonate, LCD/TFT module        |
| Data storage unit | Aluminium, NAND flash, FR-4                 |
