\-----



\# DualPose: Camera-Free 3D Hand Pose Estimation



DualPose is a novel 3D hand pose estimation system that leverages dual-sided capacitive display panels to capture raw capacitive data, enabling accurate hand pose tracking without the need for cameras or wearable sensors.



\## Overview



Unlike standard touchscreens that only return 2D contact coordinates, this system utilizes the \*\*maXTouch T37 diagnostic interface\*\* to stream raw 14×24 capacitive matrices from dual-stacked display panels. By reconstructing 3D hand poses from these capacitive images, the system provides a low-cost, camera-free solution for AR/VR interaction and HCI applications.



\## Key Innovations



&#x20; \* \*\*Dual-Sided Sensing:\*\* Unlike single-sided "TouchPose" implementations, this dual-layered architecture captures both front and back hand capacitive distributions, significantly improving 3D depth estimation.

&#x20; \* \*\*Optimized Firmware:\*\* Eliminated I2C and UART bottlenecks to increase data streaming rates from 1 Hz to approximately 17 Hz, providing sufficient data density for machine learning.

&#x20; \* \*\*Wrist-Centric Canonicalization:\*\* Introduced a canonical coordinate system transformation based on the wrist, which improved the Mean Per Joint Position Error (MPJPE) from 38 mm down to 18 mm.

&#x20; \* \*\*Advanced Regression Model:\*\* Utilizes \*\*CoordConv\*\* for explicit spatial awareness, \*\*ResNet\*\* for feature extraction, and \*\*Huber Loss\*\* for robustness against tracking outliers, outperforming baseline CNN models.



\## System Architecture



&#x20; \* \*\*Hardware:\*\* Dual maXTouch Curiosity Pro boards controlled by PIC32MZ EF MCU boards.

&#x20; \* \*\*Data Acquisition:\*\* Ground truth labels were collected using dual depth cameras during training; however, the model performs \*\*inference entirely camera-free\*\* using only capacitive input.

&#x20; \* \*\*Data Pipeline:\*\* Includes global alignment via the Kabsch algorithm, time-series noise removal, and anatomical pruning to ensure high-quality training data.



\## Performance



The proposed model achieves a 3D joint estimation error of \*\*12.65 mm\*\*, representing an approximately \*\*17.7% improvement\*\* over the baseline CNN model. It effectively predicts all 21 hand joints, including fingers that are hovering above the display without direct contact.



\## Research Context



This project was developed as part of the \*Game Contents Capstone Design\* curriculum. It builds upon foundational work in touch-based gesture sensing while introducing novel architectural and signal-processing improvements for 3D reconstruction.



\-----

