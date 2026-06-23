# Firmware integration notes

Base project: Microchip **gfx_apps_pic32mz_ef** → `apps/legato_quickstart/firmware`
Config: `ili9488_rgb565_mxt_mzef_cu_cpro`

## Modified files (in Harmony project)

| File | Change |
|------|--------|
| `src/app.c`, `src/app.h` | T37 UART streaming state machine |
| `driver/input/drv_maxtouch.c` | T37 read-out (see `driver/drv_maxtouch_t37.c`) |
| `driver/input/drv_maxtouch.h` | T37 API (see `driver/drv_maxtouch_t37.h`) |
| `peripheral/gpio/plib_gpio.c` | `RPB3R = 7` (UART6 TX on RPB3) |
| `peripheral/i2c/master/plib_i2c2_master.c` | `I2C2BRG = 242` (~200 kHz, was 4992/~10 kHz) |

## I2C speed fix

```c
/* plib_i2c2_master.c — I2C2_Initialize() */
I2C2BRG = 242;   /* ~200 kHz at PBCLK2=100 MHz (was 4992 → ~10 kHz) */
```

Without this change T37 page reads take ~700 ms/frame.

## UART pin remap

```c
/* plib_gpio.c — GPIO_Initialize() */
RPB3R = 7;   /* RPB3 → U6TX */
```

Connect a 3.3 V USB-serial adapter: adapter RX → RPB3, GND → GND.