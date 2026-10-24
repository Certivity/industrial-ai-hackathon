# spec: OTA ECU Software Update Manager

## Product Type

An in-vehicle software update manager that receives, verifies and installs over-the-air updates of the electronic control unit software of a passenger car. It runs the whole update process from download to activation and reports the result back to the vehicle maker's backend.

## Vehicle Category

M1 — fitted to a passenger car that has a number of networked ECUs, a central gateway and a telematics unit.

## Function

- Downloads update packages from the maker's backend over the mobile network or Wi-Fi, together with their metadata and signatures.
- Checks the package authenticity, integrity and version compatibility before it is installed, and refuses packages that fail the checks.
- Checks that the vehicle is in a safe state before it starts an update, for example parked, in P, ignition condition OK, battery level sufficient and no active diagnostics session.
- Installs software into the target ECUs in a controlled sequence, or hands the package to a subordinate ECU flasher.
- Keeps the previous software image so that it can roll back if installation or post-install checks fail.
- Checks that the files in the vehicle match the installed software versions, and keeps a record of the software versions and of each update attempt.
- Tells the driver when an update is available, when it is in progress and when it has finished.
- Reports update status, failures and software version data to the backend for fleet management.
- Protects update data in transit and at rest, and limits who can start or approve an update.

## Main Parts

- Update manager software running on the central gateway or on a dedicated update controller.
- Download and transport module (telematics link, TLS session handling).
- Package verifier (signature and hash checking, version compatibility rules).
- Installer and rollback engine, with a flash driver interface for the target ECUs.
- Vehicle state monitor interface (parking brake, gear, ignition, battery, diagnostics).
- Human-machine interface for driver notification and consent.
- Update log and software-version registry, stored in non-volatile memory.
- Backend interface for package retrieval and for status reporting.

## Materials

Representative values — confirm against actual bill of materials.


| Component         | Typical material(s)                         |
| ------------------- | --------------------------------------------- |
| Update controller housing | Aluminium alloy or PA66-GF30 |
| Printed circuit board | FR-4 with copper traces |
| Connectors | Tin-plated copper contacts in PBT housing |
| Thermal interface | Silicone gap pad |
| Firmware storage | NAND flash (on-board, soldered) |
| Wiring harness | Copper conductors, XLPE insulation |
