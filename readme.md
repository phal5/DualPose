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



\## Related Work



This project \*\*references\*\* the following prior work as literature. No TouchPose source code or dataset is included in this repository.



\*\*TouchPose\*\* (Ahuja, Streli & Holz, UIST 2021) — reconstructs 3D hand pose from capacitive touch images. We cite it as background for capacitive-image-based hand pose estimation and implement our own T37 data pipeline on PIC32MZ + maXTouch.



&#x20; \* Paper: [TouchPose: Hand Pose Prediction, Depth Estimation, and Touch Classification from Capacitive Images](https://static.siplab.org/papers/uist2021-touchpose.pdf)

&#x20; \* Project: [siplab.org/projects/TouchPose](https://siplab.org/projects/TouchPose)

&#x20; \* Code / dataset: [github.com/eth-siplab/TouchPose](https://github.com/eth-siplab/TouchPose)



\## Dataset



&#x20; \* \*\*Training HDF5 (in-repo):\*\* `datasets/paired_dataset_denoised.h5`, `datasets/paired_dataset_multitask.h5`

&#x20; \* \*\*Raw T37 captures (Google Drive):\*\* [DualPose Dataset](https://drive.google.com/drive/folders/1WaiR5Ex2nTYrEpaZOljRAX_dZrCXyOna?usp=sharing) — CSV / NPZ capacitive recordings



\## Repository Structure



```
DualPose/
├── datasets/           # paired HDF5 training data
├── models/             # DualPose.ipynb
├── firmware/           # PIC32 custom firmware (T37 UART streaming)
│   ├── app.c / app.h
│   ├── driver/         # drv_maxtouch T37 extension
│   └── INTEGRATION.md
├── host/               # PC-side Python tools
│   ├── t37_reader.py
│   ├── t37_heatmap.py
│   └── t37_to_h5.py
└── docs/
    ├── SETUP.md
    └── T37_TROUBLESHOOTING.md
```



> The full MPLAB Harmony project (thousands of boilerplate files) is excluded. Only custom firmware and host tools are included.



\## Quick Start (Host)



```bash
pip install pyserial
# optional: pip install numpy matplotlib

python3 host/t37_reader.py --port /dev/cu.usbmodemXXXX --plot
```



\## Firmware



Replace `app.c` in the MPLAB Harmony `legato_quickstart` project with `firmware/app.c`, apply the drv_maxtouch T37 extension and I2C/UART patches in `firmware/INTEGRATION.md`, then build and flash.



UART6 @ 460800 baud. Binary frame: sync `0xAA 0x55` + mode + matrix dims + int16 nodes + checksum.



\## License



| Component | License | Notes |
|-----------|---------|-------|
| Original code (`host/`, T37 app logic) | MIT | see `LICENSE` |
| TouchPose (cited reference) | CC BY-NC-SA 4.0 | no code/data included |
| Microchip Harmony (`drv_maxtouch`, etc.) | Microchip Harmony License | PIC32 only |



See `THIRD_PARTY_NOTICES.md` for details.



\-----



\# DualPose: 카메라 없는 3D 손 포즈 추정



양면 정전용량 디스플레이 패널에서 raw capacitive 데이터를 수집하여, 카메라나 웨어러블 센서 없이 3D 손 포즈를 추정하는 시스템입니다.



\## 참고 문헌



본 프로젝트는 아래 선행 연구를 \*\*참고 문헌\*\*으로 인용합니다. TouchPose 코드/데이터셋은 포함하지 않습니다.



\*\*TouchPose\*\* (Ahuja, Streli & Holz, UIST 2021) — 정전용량 터치 이미지로부터 3D 손 포즈를 추정하는 연구입니다.



&#x20; \* 논문: [TouchPose paper](https://static.siplab.org/papers/uist2021-touchpose.pdf)

&#x20; \* 프로젝트: [siplab.org/projects/TouchPose](https://siplab.org/projects/TouchPose)



\## 데이터



&#x20; \* \*\*학습 HDF5 (저장소 내):\*\* `datasets/paired_dataset_denoised.h5`, `datasets/paired_dataset_multitask.h5`

&#x20; \* \*\*Raw T37 캡처 (Google Drive):\*\* [DualPose Dataset](https://drive.google.com/drive/folders/1WaiR5Ex2nTYrEpaZOljRAX_dZrCXyOna?usp=sharing)



\## 구성



```
DualPose/
├── datasets/           # 학습용 HDF5
├── models/             # DualPose.ipynb
├── firmware/           # PIC32 펌웨어 (T37 UART 스트리밍)
├── host/               # PC Python 도구
└── docs/               # 설정 / 트러블슈팅
```



\## 빠른 시작 (호스트)



```bash
pip install pyserial
python3 host/t37_reader.py --port /dev/cu.usbmodemXXXX --plot
```



\## 라이선스



| 구성 요소 | 라이선스 | 비고 |
|-----------|----------|------|
| 본인 작성 코드 | MIT | `LICENSE` |
| TouchPose (참고 문헌) | CC BY-NC-SA 4.0 | 코드/데이터 미포함 |
| Microchip Harmony | Microchip Harmony License | PIC32 전용 |



\-----