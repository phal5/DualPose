/*******************************************************************************
  MPLAB Harmony Application Source File

  Company:
    Microchip Technology Inc.

  File Name:
    app.c

  Summary:
    This file contains the source code for the MPLAB Harmony application.

  Description:
    This file contains the source code for the MPLAB Harmony application.  It
    implements the logic of the application's state machine and it may call
    API routines of other MPLAB Harmony modules in the system, such as drivers,
    system services, and middleware.  However, it does not call any of the
    system interfaces (such as the "Initialize" and "Tasks" functions) of any of
    the modules in the system or make any assumptions about when those functions
    are called.  That is the responsibility of the configuration-specific system
    files.
 *******************************************************************************/

// *****************************************************************************
// *****************************************************************************
// Section: Included Files
// *****************************************************************************
// *****************************************************************************

#include "app.h"
#include "definitions.h"           /* UART6_*, DRV_MAXTOUCH_*, SYS_TIME_* */
#include <string.h>

// *****************************************************************************
// *****************************************************************************
// Section: T37 capacitive raw-data streaming configuration
// *****************************************************************************
// *****************************************************************************

/* Which diagnostic data set to stream:
     DRV_MAXTOUCH_T37_MODE_DELTAS - signed delta from the running reference
     DRV_MAXTOUCH_T37_MODE_REFS   - raw reference (baseline) values          */
#define APP_T37_MODE        DRV_MAXTOUCH_T37_MODE_DELTAS

/* Frame pacing floor. The real per-frame cost is now the T37 I2C read plus
   the UART transfer (tens of ms), so this is just a small floor to avoid
   starving the rest of the system; it no longer caps the frame rate.        */
#define APP_T37_PERIOD_MS   10

/* UART baud for the raw-data link (matches the host reader). 460800 keeps a
   336-node frame (~681 B) under ~15 ms on the wire. BRGH is set in the UART6
   plib so the real baud matches.                                            */
#define APP_UART_BAUD       460800

/* Last linear node that carries live data is x=13,y=7 -> k=13*24+7=319, so we
   only need nodes 0..319 (5 pages) and can skip the all-dead tail page 6
   (k320..335 = x13's unwired Y8..23). Reading 320 instead of 336 nodes drops
   one of the six T37 I2C page reads. NOTE: measured T7 acquisition tuning had
   no effect on the rate -- the floor is the controller's per-page diagnostic
   serve latency (~10-12 ms/page), so page count is the only real lever left.  */
#define APP_T37_READ_NODES  320

/* Upper bound on matrix nodes (matrix_xsize * matrix_ysize). The mXT336T on
   this board reports a fixed 14 x 24 = 336 node matrix, so 336 is the real
   cap; the previous 1024 just wasted ~2.8 KB of RAM across the two buffers.  */
#define APP_T37_MAX_NODES   336

/* Only the first APP_T37_LIVE_YSIZE Y-lines are physically wired on this
   panel. The controller still scans/reports a 24-line matrix, but Y8..23 are
   always zero (224 dead nodes per frame, interleaved 16-per-X-line). We pack
   just the live region before sending so the host gets a clean 14 x 8 grid
   and the frame shrinks from ~681 to ~233 bytes. Set equal to the reported
   ySize (or larger) to disable cropping. NOTE: this does NOT raise the frame
   rate -- the rate floor is the T37 I2C page read, and the controller still
   emits all 24 Y-lines over I2C regardless. To cut the I2C cost the maXTouch
   matrix config itself must be reduced to 8 Y-lines (config/.xcfg reflash).  */
#define APP_T37_LIVE_YSIZE  8

/* Binary frame:
     [0]=0xAA [1]=0x55 [2]=mode [3]=xSize [4]=ySize
     [5]=nodeCount_lo [6]=nodeCount_hi
     [7..]=nodeCount * int16 little-endian
     [tail]=checksum_lo checksum_hi   (16-bit sum of all payload bytes)       */
#define APP_FRAME_SYNC0     0xAA
#define APP_FRAME_SYNC1     0x55
#define APP_FRAME_HDR_LEN   7
#define APP_FRAME_MAX_LEN   (APP_FRAME_HDR_LEN + APP_T37_MAX_NODES * 2 + 2)

// *****************************************************************************
// *****************************************************************************
// Section: Global Data Definitions
// *****************************************************************************
// *****************************************************************************

/* Capacitive raw node values for the most recent frame. */
static int16_t          appT37Nodes[APP_T37_MAX_NODES];

/* Assembled UART frame buffer (must persist until the async write finishes). */
static uint8_t          appT37Frame[APP_FRAME_MAX_LEN];

/* One-shot pacing timer between frames. */
static SYS_TIME_HANDLE  appT37Timer = SYS_TIME_HANDLE_INVALID;

// *****************************************************************************
/* Application Data

  Summary:
    Holds application data

  Description:
    This structure holds the application's data.

  Remarks:
    This structure should be initialized by the APP_Initialize function.

    Application strings and buffers are be defined outside this structure.
*/

APP_DATA appData;

// *****************************************************************************
// *****************************************************************************
// Section: Application Callback Functions
// *****************************************************************************
// *****************************************************************************

/* TODO:  Add any necessary callback functions.
*/

// *****************************************************************************
// *****************************************************************************
// Section: Application Local Functions
// *****************************************************************************
// *****************************************************************************


/* Re-arm the one-shot pacing timer for the next frame. */
static void APP_T37_ArmTimer(void)
{
    appT37Timer = SYS_TIME_HANDLE_INVALID;
    (void)SYS_TIME_DelayMS(APP_T37_PERIOD_MS, &appT37Timer);
}

/* True when the pacing interval has elapsed (or the timer could not arm). */
static bool APP_T37_TimerExpired(void)
{
    if (appT37Timer == SYS_TIME_HANDLE_INVALID)
        return true;

    return (SYS_TIME_DelayIsComplete(appT37Timer) == true);
}

/* Pack a node set into appT37Frame[] and return the total frame length. */
static size_t APP_T37_BuildFrame(uint8_t mode, uint8_t xSize, uint8_t ySize,
                                 const int16_t *nodes, uint16_t nodeCount)
{
    size_t   i, p = 0;
    uint16_t checksum = 0;

    appT37Frame[p++] = APP_FRAME_SYNC0;
    appT37Frame[p++] = APP_FRAME_SYNC1;
    appT37Frame[p++] = mode;
    appT37Frame[p++] = xSize;
    appT37Frame[p++] = ySize;
    appT37Frame[p++] = (uint8_t)(nodeCount & 0xFF);
    appT37Frame[p++] = (uint8_t)(nodeCount >> 8);

    for (i = 0; i < nodeCount; i++)
    {
        uint8_t lo = (uint8_t)(nodes[i] & 0xFF);
        uint8_t hi = (uint8_t)((uint16_t)nodes[i] >> 8);

        appT37Frame[p++] = lo;
        appT37Frame[p++] = hi;
        checksum = (uint16_t)(checksum + lo + hi);
    }

    appT37Frame[p++] = (uint8_t)(checksum & 0xFF);
    appT37Frame[p++] = (uint8_t)(checksum >> 8);

    return p;
}

/* Read one T37 frame and push it out on UART6. Skips a cycle if the UART is
   still busy sending the previous frame (so the buffer is never clobbered). */
static void APP_T37_CaptureAndSend(void)
{
    uint8_t xSize = 0, ySize = 0;
    int     nodeCount;
    size_t  len;

    /* Don't overwrite a frame the UART is still transmitting. */
    if (UART6_WriteIsBusy())
        return;

    /* Read one real capacitive raw-data frame from the maXTouch T37 object
       (blocking polled I2C). Skip this cycle on failure / not-ready. */
    nodeCount = DRV_MAXTOUCH_T37Read(DRV_HANDLE_INVALID, APP_T37_MODE,
                                     appT37Nodes, APP_T37_READ_NODES,
                                     &xSize, &ySize);
    if (nodeCount <= 0)
        return;

    /* Drop the always-zero Y-lines (keep the live 14 x 8 region). In-place is
       safe: the write index j never overtakes the read index x*ySize+y. Guard
       that every source index we touch (max = (xSize-1)*ySize + LIVE_Y-1) was
       actually read -- nodeCount can be < xSize*ySize because we intentionally
       skip the all-dead tail page (APP_T37_READ_NODES).                       */
    if (xSize > 0 && ySize > APP_T37_LIVE_YSIZE &&
        nodeCount >= (int)((uint16_t)(xSize - 1) * ySize + APP_T37_LIVE_YSIZE))
    {
        uint16_t j = 0, x, y;
        for (x = 0; x < xSize; x++)
            for (y = 0; y < APP_T37_LIVE_YSIZE; y++)
                appT37Nodes[j++] = appT37Nodes[(uint16_t)x * ySize + y];
        ySize     = APP_T37_LIVE_YSIZE;
        nodeCount = (int)j;
    }

    len = APP_T37_BuildFrame(APP_T37_MODE, xSize, ySize,
                             appT37Nodes, (uint16_t)nodeCount);

    (void)UART6_Write(appT37Frame, len);
}


// *****************************************************************************
// *****************************************************************************
// Section: Application Initialization and State Machine Functions
// *****************************************************************************
// *****************************************************************************

/*******************************************************************************
  Function:
    void APP_Initialize ( void )

  Remarks:
    See prototype in app.h.
 */

void APP_Initialize ( void )
{
    /* Place the App state machine in its initial state. */
    appData.state = APP_STATE_INIT;

    appT37Timer = SYS_TIME_HANDLE_INVALID;
}


/******************************************************************************
  Function:
    void APP_Tasks ( void )

  Remarks:
    See prototype in app.h.
 */

void APP_Tasks ( void )
{

    /* Check the application's current state. */
    switch ( appData.state )
    {
        /* Application's initial state. */
        case APP_STATE_INIT:
        {
            appData.state = APP_STATE_T37_SETUP;
            break;
        }

        case APP_STATE_T37_SETUP:
        {
            /* Bring UART6 up at the raw-data link baud. */
            UART_SERIAL_SETUP setup;
            setup.baudRate  = APP_UART_BAUD;
            setup.parity    = UART_PARITY_NONE;
            setup.dataWidth = UART_DATA_8_BIT;
            setup.stopBits  = UART_STOP_1_BIT;
            UART6_SerialSetup(&setup, UART6_FrequencyGet());

            appData.state = APP_STATE_T37_WAIT_READY;
            break;
        }

        case APP_STATE_T37_WAIT_READY:
        {
            /* Wait until the touch controller has been enumerated
               (object table parsed, T6/T37 available). */
            if (DRV_MAXTOUCH_IsReady(DRV_HANDLE_INVALID))
            {
                APP_T37_ArmTimer();
                appData.state = APP_STATE_T37_CAPTURE;
            }
            break;
        }

        case APP_STATE_T37_CAPTURE:
        {
            if (APP_T37_TimerExpired())
            {
                APP_T37_CaptureAndSend();
                APP_T37_ArmTimer();
            }
            break;
        }

        case APP_STATE_SERVICE_TASKS:
        {
            break;
        }

        /* The default state should never be executed. */
        default:
        {
            break;
        }
    }
}


/*******************************************************************************
 End of File
 */
