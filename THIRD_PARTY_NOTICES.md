# Third-Party Notices

This project combines original code with third-party components.
Each component retains its original license.

## 1. TouchPose (cited reference)

- **Project:** TouchPose — Hand Pose Prediction, Depth Estimation, and Touch
  Classification from Capacitive Images
- **Authors:** Karan Ahuja, Paul Streli, Christian Holz (ETH SIPLab)
- **License:** [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
- **Links:**
  - https://siplab.org/projects/TouchPose
  - https://github.com/eth-siplab/TouchPose
  - https://doi.org/10.1145/3472749.3474801

TouchPose is **cited as related literature** in this project.
**No TouchPose source code or dataset is included** in this repository.

If you use TouchPose code or data directly, you must comply with CC BY-NC-SA 4.0
(non-commercial use, attribution, share-alike). Commercial use requires
contacting SIPLab: https://siplab.org/contact

## 2. Microchip MPLAB Harmony

- **Components:**
  - `firmware/driver/drv_maxtouch_t37.c` — derived from Microchip `drv_maxtouch.c`
  - `firmware/driver/drv_maxtouch_t37.h` — API declarations for the above
  - `firmware/app.c`, `firmware/app.h` — based on MPLAB Harmony application templates
- **Copyright:** (C) Microchip Technology Inc.
- **License:** [MPLAB Harmony Integrated Software Framework License](https://www.microchip.com/development-tools-tools-and-software/mplab-x-ide/mplab-harmony)
  (see also `mplab_harmony_license.md` in the original Harmony distribution)

Microchip software may be used and distributed **only with Microchip microcontroller
products** (e.g. PIC32MZ). Source code from the Harmony framework is subject to
Microchip's license terms and is not relicensed under the MIT License above.

## 3. Python dependencies

| Package     | License   | Notes                          |
|-------------|-----------|--------------------------------|
| pyserial    | BSD-3     | Required for host tools        |
| numpy       | BSD-3     | Optional (ML / plotting)       |
| matplotlib  | PSF-based | Optional (plotting)            |
| h5py        | BSD-3     | Optional (HDF5 export)         |

## Attribution summary

When sharing or submitting this project, please retain:

1. This `THIRD_PARTY_NOTICES.md` file
2. The `LICENSE` file
3. The TouchPose reference section in `README.md`
4. Microchip copyright headers in firmware files