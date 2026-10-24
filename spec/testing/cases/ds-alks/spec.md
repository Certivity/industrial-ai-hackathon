# spec: Motorway Low-Speed Automated Lane Keeping System (MLS-ALKS)

## Product Type

An automated driving system that takes over lateral and longitudinal control of a passenger car on motorways and similar dual-carriageway roads at speeds up to 60 km/h, monitors the driver for takeover availability, and, if the driver does not respond, executes a minimum risk manoeuvre to bring the vehicle to a safe stop in its lane.

## Vehicle Category

M1 — fitted to a series-production passenger car with automatic transmission, electric power-assisted steering and a brake system capable of external deceleration demand.

## Function

- Maintains the vehicle within its lane using camera and radar perception of lane markings and road boundaries.
- Controls vehicle speed up to a maximum of 60 km/h and keeps a safe following distance to the vehicle ahead.
- Detects other road users and obstacles in the vehicle's path and initiates braking or steering response within the system's declared operational limits.
- Monitors the driver continuously (gaze direction, head pose, hands on/off wheel) and issues escalating prompts when the driver is not available to resume control.
- Performs a minimum risk manoeuvre — deceleration in lane with hazard warning activation — if the driver fails to respond after the escalation period.
- Records and makes available to the driver the system status, active/inactive state, and the detection of the operational domain boundaries.
- Logs event data and failures for diagnostic and post-incident analysis.
- Supports over-the-air security patches and approval-relevant software updates with version traceability.

## Main Parts

- Forward camera module (monocular or stereo) with integrated image processing.
- Front and corner radar sensors.
- Driver monitoring camera and infrared illumination unit in the steering column/dashboard.
- Central ADAS computing unit with sensor fusion and decision software.
- Steering angle and torque interface to the electric power steering.
- Brake and powertrain interface unit for longitudinal control requests.
- Human-machine interface: cluster display, warning chimes, haptic seat/steering feedback.
- Redundant power supply and watchdog circuitry.
- Event data recorder and software update module.
- Actuator for hazard warning lamps during the minimum risk manoeuvre.

## Materials

Representative values — confirm against actual bill of materials.

| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| Camera housing    | Aluminium alloy (EN AC-AlSi10Mg) or PA66-GF30 |
| Radome cover      | PC/ABS blend, painted on interior surface   |
| Lens elements     | Optical glass / PMMA, AR-coated             |
| PCBA substrate    | FR4 with lead-free HASL, ENIG contacts      |
| Connector shells  | PA66-GF30, gold-plated brass contacts       |
| Wiring harness    | XLPE-insulated copper, halogen-free conduit |
| Mounting brackets | Steel DC01, zinc-nickel plated              |
| HMI lens          | PMMA, hard-coated                            |
