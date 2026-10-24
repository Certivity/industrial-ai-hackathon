# spec: Connected Car Telematics Control Unit (TCU-1)

## Product Type

A factory-fitted telematics control unit that provides the vehicle with cellular remote connectivity and a secure over-the-air (OTA) software and data update path. It links the vehicle's internal networks to a cloud back end and manages software updates for the vehicle's electronic control units.

## Vehicle Category

M1 — fitted to a passenger car (up to eight seats) with a 12 V electrical system and a body-mounted, roof or under-dash mounting position.

## Function

- Maintains cellular (4G/5G) connectivity to a remote back end for telemetry and remote services.
- Acts as a secure gateway between the vehicle's CAN/Ethernet networks and the external network.
- Receives, verifies, stores and distributes software updates to target ECUs over the OTA interface.
- Reports software version and update status to the back end and to the driver.
- Provides power management and safe shutdown for the unit and attached networks.
- Supports remote diagnostics, eCall data transport and fleet data collection.
- Broadcasts no radio emissions beyond the approved EMC limits and tolerates in-vehicle interference.

## Main Parts

- Main enclosure with mounting bracket.
- Main PCB with application processor, secure element and cellular modem.
- Cellular antenna(s) (LTE/5G main and diversity), GNSS antenna.
- Back-up battery or supercapacitor for orderly shutdown.
- Vehicle interface connector (CAN, LIN, Ethernet, power).
- Software: bootloader, operating system, update agent and cyber-security stack.

## Materials

Representative values — confirm against actual bill of materials.


| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| Enclosure         | Die-cast aluminium alloy (AlSi), powder-coated |
| Mounting bracket  | Steel, zinc-plated                          |
| PCB               | FR-4 glass-reinforced epoxy, copper, solder SAC305 |
| Connector housing | PBT/PA66 glass-filled thermoplastic         |
| Antenna           | PCB trace or stamped metal, FPC with copper |
| Sealing/gaskets   | Silicone or EPDM rubber                     |
