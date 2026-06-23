# maXTouch T37 capacitive raw-data capture

Streams the touch controller's per-node capacitive measurements (T37
diagnostic object) from the PIC32MZ EF board over UART, for offline hand-shape
/ gesture training.

## Firmware side

Already wired into this project:

- `src/config/ili9488_rgb565_mxt_mzef_cu_cpro/driver/input/drv_maxtouch.[ch]`
  adds `DRV_MAXTOUCH_T37Read()` / `DRV_MAXTOUCH_IsReady()`. The read drives the
  T6 DIAGNOSTIC command and reads the T37 object page-by-page over the existing
  I2C bus.
- `src/app.c` brings up **UART6 at 115200 8N1** and streams one binary frame
  per scan (~20 Hz, see `APP_T37_PERIOD_MS`).

Default data set is **deltas** (`APP_T37_MODE = DRV_MAXTOUCH_T37_MODE_DELTAS`).
Switch to references by setting it to `DRV_MAXTOUCH_T37_MODE_REFS` in `app.c`.

### Wiring

UART6 TX is mapped to **RPB3** (`RPB3R = 7` in `plib_gpio.c`). Connect a 3.3 V
USB-serial adapter:

| adapter | board        |
| ------- | ------------ |
| RX      | RPB3 (U6TX)  |
| GND     | GND          |

> Confirm the TX pin in MPLAB Harmony **Pin Settings** if you regenerate code.
> Only TX is needed (host is read-only); the adapter must be 3.3 V logic.

## Host side

Install pyserial (numpy/matplotlib only needed for `--plot` / `--npz`):

```
pip install pyserial            # required
pip install numpy matplotlib    # optional
```

Find the port: macOS `ls /dev/tty.usb*`, Linux `/dev/ttyUSB*`, Windows `COMx`.

```bash
# live ASCII heat map in the terminal
python3 t37_reader.py --port /dev/tty.usbserial-XXXX

# live matplotlib heat map
python3 t37_reader.py --port /dev/tty.usbserial-XXXX --plot

# log labelled frames to CSV (one row per scan, nodes flattened)
python3 t37_reader.py --port /dev/ttyUSB0 --csv fist.csv   --label fist
python3 t37_reader.py --port /dev/ttyUSB0 --csv open.csv   --label open_hand

# build an ML dataset: data array shape (N, xSize, ySize), int16
python3 t37_reader.py --port /dev/ttyUSB0 --npz hands.npz  --label fist --count 500
```

Load an `.npz` capture for training:

```python
import numpy as np
d = np.load("hands.npz")
X, y = d["data"], d["label"]   # X: (N, xSize, ySize), y: labels
```

## Frame format

Little-endian, one frame per capacitive scan:

| offset | field      | bytes        | notes                                    |
| ------ | ---------- | ------------ | ---------------------------------------- |
| 0      | sync0      | 1            | `0xAA`                                   |
| 1      | sync1      | 1            | `0x55`                                   |
| 2      | mode       | 1            | `0x10` deltas, `0x11` references         |
| 3      | xSize      | 1            | matrix X channels                        |
| 4      | ySize      | 1            | matrix Y channels                        |
| 5      | nodeCount  | 2 (uint16)   | `xSize * ySize`                          |
| 7      | payload    | nodeCount*2  | int16 per node, `k = x*ySize + y`        |
| tail   | checksum   | 2 (uint16)   | sum of payload bytes mod 65536           |
