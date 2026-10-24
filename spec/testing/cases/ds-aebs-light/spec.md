# spec: Forward Camera-Radar Automatic Emergency Braking System (CAMRAD-AEB)

## Product Type

A forward-facing automatic emergency braking system that fuses a windshield-mounted camera with a front grille-mounted radar to detect vehicles and pedestrians ahead and apply the brakes when a collision is imminent. It provides forward collision warning and autonomous braking, including at low speeds for pedestrian protection.

## Vehicle Category

M1 — fitted to a passenger car (up to eight seats) with a conventional hydraulically actuated service brake system and a 12 V electrical architecture.

## Function

- Detects and tracks vehicles and pedestrians ahead in the host vehicle's path using camera and radar fusion.
- Estimates time-to-collision and warns the driver via visual, audible and haptic alerts.
- Increases brake pressure automatically to avoid or mitigate a rear-end collision with a moving or stationary vehicle.
- Brakes automatically to avoid or mitigate a collision with a pedestrian in the vehicle's path, including at low speeds.
- Provides a driver-selectable or default-on activation state and reports system status and failures to the driver.
- Coordinates with the electronic stability control and brake system to deliver the commanded deceleration.

## Main Parts

- Forward monocular camera module with image processing unit, mounted behind the windshield.
- 76-79 GHz radar sensor module mounted in the front grille or bumper.
- Fusion electronic control unit (ECU) running perception and decision software.
- Brake pressure modulator / ESC hydraulic unit interface for pressure build-up and release.
- Driver warning interface: instrument cluster display, warning chime and seat/steering haptic actuator.
- Wiring harness, connectors and CAN/FlexRay network interface.
- Mounting brackets with adjustment and calibration features for camera and radar.

## Materials

Representative values — confirm against actual bill of materials.

| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| Camera housing    | PA66-GF30 polyamide, aluminium heat spreader |
| Camera lens       | Optical-grade glass and PMMA/PC lenses       |
| Radar housing     | PBT/PA66-GF30 thermoplastic, die-cast aluminium base |
| Radar radome      | PC/ABS blend                                 |
| Fusion ECU housing| Aluminium alloy (ADC12) or PA66-GF30          |
| Mounting brackets | Steel (DC01) or PA66-GF30                    |
| Wiring harness    | Copper conductors, PVC or XLPE insulation    |
| PCB assemblies    | FR-4 laminate, SnAgCu solder, gold-plated contacts |
