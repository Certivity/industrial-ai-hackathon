# spec: Highway Driver Assist with Adaptive Cruise and Lane Centring

## Product Type

A driver control assistance system that combines adaptive cruise control with lane centring to keep the car at a set speed, at a set following distance, and near the centre of its lane, while supervising the driver's hands and attention. It assists the driver; it does not drive the car and can be overridden at any time.

## Vehicle Category

M1 — a passenger car with an electric power steering rack, a full-width electronic brake system, and a forward camera plus forward radar; fitted only to vehicles whose steering, braking and powertrain interfaces have been approved for this function.

## Function

- Holds a driver-selected speed up to a configured maximum when the road ahead is clear.
- Adjusts speed to keep a selected time gap to the vehicle ahead, down to a standstill and restart where supported.
- Applies steering torque to keep the car centred in the detected lane on roads where lane markings are valid.
- Detects whether the driver's hands are on the wheel through a torque/capacitance sensor in the steering rim.
- Monitors the driver with a cabin camera and tracks gaze and head pose to check attention to the road.
- Escalates from visual and audible warnings to a tightened hands-on demand, then to a controlled deceleration and hazard-light activation if the driver does not respond.
- Suspends lane centring automatically when lane markings are lost, weather limits the camera, or the driver overrides the steering.
- Records the last events (engagement state, warnings, sensor status) in a non-volatile event data recorder for later read-out.
- Reports the system state, set speed, gap and hands-on status on the instrument cluster.
- Accepts software updates only after authenticity and compatibility checks.

## Main Parts

- Forward camera module with image processor, mounted behind the windscreen at the top centre.
- Forward radar sensor in the front bumper or grille.
- Driver monitoring camera and infrared illuminator in the steering column or overhead console.
- Hands-on detection sensor built into the steering wheel rim.
- Assistance control unit running the speed, gap, steering and driver-supervision logic.
- Steering angle and torque sensor on the steering column, and the electric power steering control unit that executes the torque request.
- Brake and powertrain interface module that receives deceleration and acceleration requests.
- Human-machine interface: cluster display, telltales, chime speaker and steering-wheel switches.
- Event data recorder.
- Wiring harness, connectors and power supply protection.

## Materials

Representative values — confirm against actual bill of materials.

| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| Camera housing    | Aluminium alloy (ADC12) or PA66-GF30          |
| Lens elements     | Optical glass, PMMA                          |
| Radar housing     | PBT-GF30                                     |
| Radar radome      | PC/ABS                                       |
| Steering rim sensor | Copper foil, PET film, silicone potting    |
| Driver camera housing | PC/ABS                                   |
| Control unit housing | Aluminium die-cast, tin-plated PCB         |
| Harness           | Copper conductors, PVC or XLPE insulation    |
| Connectors        | PA66, brass contacts, gold or tin plating    |

#
