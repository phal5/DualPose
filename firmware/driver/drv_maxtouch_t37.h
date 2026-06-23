/*******************************************************************************
* Copyright (C) 2020 Microchip Technology Inc. and its subsidiaries.
*
* maXTouch T37 (GEN_DIAGNOSTIC_DEBUG) capacitive raw-data interface.
* Add these declarations to drv_maxtouch.h (before the closing extern "C" block).
* Base project: MPLAB Harmony legato_quickstart
* Config: ili9488_rgb565_mxt_mzef_cu_cpro
 ******************************************************************************/

#ifndef DRV_MAXTOUCH_T37_H
#define DRV_MAXTOUCH_T37_H

#include <stdint.h>
#include <stdbool.h>
#include "driver.h"

/* T37 diagnostic data-set selectors (written to T6 DIAGNOSTIC command) */
#define DRV_MAXTOUCH_T37_MODE_DELTAS   0x10   /* signed delta from reference */
#define DRV_MAXTOUCH_T37_MODE_REFS     0x11   /* unsigned reference values   */

bool DRV_MAXTOUCH_IsReady ( DRV_HANDLE handle );

bool DRV_MAXTOUCH_T7Set ( DRV_HANDLE handle, uint8_t idle, uint8_t active );

int DRV_MAXTOUCH_T37Read ( DRV_HANDLE handle,
                           uint8_t    mode,
                           int16_t   *nodes,
                           int        maxNodes,
                           uint8_t   *xSize,
                           uint8_t   *ySize );

#endif /* DRV_MAXTOUCH_T37_H */