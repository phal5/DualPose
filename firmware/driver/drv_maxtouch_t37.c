/*******************************************************************************
* Copyright (C) 2020 Microchip Technology Inc. and its subsidiaries.
*
* Subject to your compliance with these terms, you may use Microchip software
* and any derivatives exclusively with Microchip products.
*
* THIS SOFTWARE IS SUPPLIED BY MICROCHIP "AS IS". NO WARRANTIES, WHETHER
* EXPRESS, IMPLIED OR STATUTORY, APPLY TO THIS SOFTWARE.
*
* T37 (GEN_DIAGNOSTIC_DEBUG) capacitive raw-data read-out — extracted from
* Microchip drv_maxtouch.c for standalone reference. Insert into drv_maxtouch.c
* after mxt_obj_instances(). Requires MXT_DEBUG_DIAGNOSTIC_T37 (37).
 ******************************************************************************/

/* T6 DIAGNOSTIC sub-command used to advance T37 to the next data page */
#define MXT_T37_PAGEUP          0x01
/* T37 layout: byte0 = mode echo, byte1 = page number, then the data area */
#define MXT_T37_HDR_SIZE        2

static bool _T37_WaitI2C(DRV_I2C_TRANSFER_HANDLE th)
{
    DRV_I2C_TRANSFER_EVENT ev;
    uint32_t spins = 0;

    if (th == DRV_I2C_TRANSFER_HANDLE_INVALID)
        return false;

    do
    {
        ev = DRV_I2C_TransferStatusGet(th);
        if (ev == DRV_I2C_TRANSFER_EVENT_PENDING && ++spins > 5000000u)
            return false;
    }
    while (ev == DRV_I2C_TRANSFER_EVENT_PENDING);

    return (ev == DRV_I2C_TRANSFER_EVENT_COMPLETE);
}

static bool _T37_WriteReg8(struct DEVICE_OBJECT *pDrv, uint16_t reg, uint8_t val)
{
    uint8_t wb[3];
    DRV_I2C_TRANSFER_HANDLE th = DRV_I2C_TRANSFER_HANDLE_INVALID;

    wb[0] = (uint8_t)(reg & 0xFF);
    wb[1] = (uint8_t)(reg >> 8);
    wb[2] = val;

    DRV_I2C_WriteTransferAdd(pDrv->drvI2CHandle, I2C_MASTER_WRITE_ID,
                             wb, 3, &th);

    return _T37_WaitI2C(th);
}

static bool _T37_ReadReg(struct DEVICE_OBJECT *pDrv, uint16_t reg,
                         uint8_t *rb, size_t len)
{
    uint8_t wb[2];
    DRV_I2C_TRANSFER_HANDLE th = DRV_I2C_TRANSFER_HANDLE_INVALID;

    wb[0] = (uint8_t)(reg & 0xFF);
    wb[1] = (uint8_t)(reg >> 8);

    DRV_I2C_WriteReadTransferAdd(pDrv->drvI2CHandle, I2C_MASTER_WRITE_ID,
                                 wb, 2, rb, len, &th);

    return _T37_WaitI2C(th);
}

bool DRV_MAXTOUCH_T7Set(DRV_HANDLE handle, uint8_t idle, uint8_t active)
{
    struct DEVICE_OBJECT *pDrv = &sMAXTOUCHDriverInstances[0];

    (void)handle;

    if (!DRV_MAXTOUCH_IsReady(handle) || pDrv->data.T7_address == 0)
        return false;

    if (!_T37_WriteReg8(pDrv, pDrv->data.T7_address + 0u, idle))
        return false;
    if (!_T37_WriteReg8(pDrv, pDrv->data.T7_address + 1u, active))
        return false;

    pDrv->data.t7_cfg.idle   = idle;
    pDrv->data.t7_cfg.active = active;
    return true;
}

bool DRV_MAXTOUCH_IsReady(DRV_HANDLE handle)
{
    struct DEVICE_OBJECT *pDrv = &sMAXTOUCHDriverInstances[0];

    (void)handle;

    return (pDrv->status == SYS_STATUS_READY) &&
           (pDrv->data.object_table != NULL) &&
           (pDrv->data.T6_address != 0) &&
           (mxt_get_object(pDrv, MXT_DEBUG_DIAGNOSTIC_T37) != NULL);
}

int DRV_MAXTOUCH_T37Read(DRV_HANDLE handle, uint8_t mode,
                         int16_t *nodes, int maxNodes,
                         uint8_t *xSize, uint8_t *ySize)
{
    struct DEVICE_OBJECT *pDrv = &sMAXTOUCHDriverInstances[0];
    struct mxt_object *t37;
    static uint8_t t37buf[MXT_DATA_BUFFER_SIZE];
    uint16_t t37_addr, diag_reg, t37_size, data_per_page;
    uint16_t total_nodes, total_bytes, pages, page;
    uint16_t nodeIdx, byteIdx, off;
    int retries;

    (void)handle;

    if (nodes == NULL || maxNodes <= 0)
        return 0;

    if (!DRV_MAXTOUCH_IsReady(handle))
        return 0;

    t37 = mxt_get_object(pDrv, MXT_DEBUG_DIAGNOSTIC_T37);
    if (t37 == NULL)
        return 0;

    t37_addr = t37->start_address;
    t37_size = (uint16_t)mxt_obj_size(t37);
    if (t37_size <= MXT_T37_HDR_SIZE || t37_size > sizeof(t37buf))
        return 0;

    data_per_page = t37_size - MXT_T37_HDR_SIZE;
    diag_reg = pDrv->data.T6_address + MXT_COMMAND_DIAGNOSTIC;

    total_nodes = (uint16_t)pDrv->data.info.matrix_xsize *
                  (uint16_t)pDrv->data.info.matrix_ysize;
    if (total_nodes == 0)
        return 0;
    if (total_nodes > (uint16_t)maxNodes)
        total_nodes = (uint16_t)maxNodes;

    total_bytes = total_nodes * 2;
    pages = (total_bytes + data_per_page - 1) / data_per_page;

    if (!_T37_WriteReg8(pDrv, diag_reg, mode))
        return 0;

    nodeIdx = 0;
    byteIdx = 0;

    for (page = 0; page < pages; page++)
    {
        retries = 0;
        for (;;)
        {
            if (!_T37_ReadReg(pDrv, t37_addr, t37buf, 2))
                return 0;
            if (t37buf[0] == mode && t37buf[1] == (uint8_t)page)
                break;
            if (++retries >= 200)
                return 0;
            _mxt_DelayMS(1);
        }

        if (!_T37_ReadReg(pDrv, t37_addr, t37buf, t37_size))
            return 0;

        off = MXT_T37_HDR_SIZE;
        while ((off + 1u) < t37_size &&
               nodeIdx < total_nodes && byteIdx < total_bytes)
        {
            nodes[nodeIdx++] = (int16_t)(t37buf[off] |
                                         ((uint16_t)t37buf[off + 1] << 8));
            off += 2;
            byteIdx += 2;
        }

        if ((page + 1) < pages)
        {
            if (!_T37_WriteReg8(pDrv, diag_reg, MXT_T37_PAGEUP))
                return 0;
        }
    }

    if (xSize != NULL)
        *xSize = pDrv->data.info.matrix_xsize;
    if (ySize != NULL)
        *ySize = pDrv->data.info.matrix_ysize;

    return (int)nodeIdx;
}