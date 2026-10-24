# spec: Transponder Engine Immobilizer System (TEIS-1)

## Product Type

An electronic engine immobilizer that pairs a coded transponder key with an ECU-linked authentication module so the engine can only be started with an authorised key. It disables the powertrain control path whenever the correct key code is not confirmed.

## Vehicle Category

M1 — fitted to a passenger car with a 12 V electrical system, a conventional ignition switch with START position, and a factory engine control unit.

## Function

- Reads the transponder key code via an inductive coil around the ignition lock when the key is inserted or in range.
- Sends a challenge to the key and verifies the encrypted response against stored key data.
- Authenticates to the engine control unit over the vehicle network before allowing ignition/fuel injection.
- Keeps the engine immobilised (crank blocked or injection/fuel cut) if the key is missing, unknown, or the link is broken.
- Allows enrolment and deletion of keys by a service procedure using the valid key and diagnostic access.
- Reports immobiliser status and fault codes over the diagnostic interface and records authentication events.
- Retains its configuration and key data in non-volatile memory across battery disconnection.

## Main Parts

- Immobilizer control module (transponder reader and authentication electronics).
- Inductive antenna coil around the ignition lock barrel.
- Coded transponder key (transponder chip embedded in the key head).
- Engine control unit interface / CAN link harness and connector set.
- Status indicator (LED) and diagnostic connector interface.

## Materials

Representative values — confirm against actual bill of materials.


| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| Module housing    | PA66-GF30 polyamide (glass-filled)         |
| PCB               | FR-4 epoxy glass laminate with copper      |
| Antenna coil      | Copper wire, PBT former                   |
| Key head shell    | ABS/PC blend                              |
| Transponder chip  | Silicon die in epoxy package              |
| Connectors        | Tin-plated brass contacts, PBT housing    |
| Sealing           | Silicone gasket / potting compound         |
