#include "twai_daemon.h"

static const char *TAG = "CAN Daemon";

twai_node_handle_t g_twai_node_hdl = nullptr;
frameDispatcher_t *dispatchCANFrame = nullptr;

bool CAN_RX_TimedOut = false;
bool g_twai_bus_off = false;

TaskHandle_t CAN_RX_tsk_hdl = nullptr;
QueueHandle_t g_twai_rx_queue = nullptr;

// -----------------------------------------------------------------------------
// TX Frame Pool (Zero-copy asynchronous transmission without stack dangling)
// -----------------------------------------------------------------------------

#define TWAI_TX_POOL_SIZE 32

struct twai_tx_slot_t
{
    twai_frame_t frame;
    uint8_t buffer[8];
};

static twai_tx_slot_t s_tx_slots[TWAI_TX_POOL_SIZE];
static QueueHandle_t s_tx_pool_queue = nullptr;

// -----------------------------------------------------------------------------
// Driver Callbacks (ISR Context)
// -----------------------------------------------------------------------------

static IRAM_ATTR bool twai_tx_done_cb(twai_node_handle_t handle, const twai_tx_done_event_data_t *edata, void *user_ctx)
{
    BaseType_t high_task_woken = pdFALSE;

    if (edata != nullptr && edata->done_tx_frame != nullptr)
    {
        const twai_frame_t *done_frame = edata->done_tx_frame;
        // Verify pointer belongs to s_tx_slots pool
        if (done_frame >= &s_tx_slots[0].frame && done_frame <= &s_tx_slots[TWAI_TX_POOL_SIZE - 1].frame)
        {
            twai_tx_slot_t *slot = (twai_tx_slot_t *)done_frame;
            if (s_tx_pool_queue != nullptr)
            {
                xQueueSendFromISR(s_tx_pool_queue, &slot, &high_task_woken);
            }
        }
    }

    return (high_task_woken == pdTRUE);
}

static IRAM_ATTR bool twai_rx_done_cb(twai_node_handle_t handle, const twai_rx_done_event_data_t *edata, void *user_ctx)
{
    twai_queued_frame_t q_frame = {};
    twai_frame_t rx_frame = {};
    rx_frame.buffer = q_frame.data;
    rx_frame.buffer_len = sizeof(q_frame.data);
    BaseType_t high_task_woken = pdFALSE;

    if (twai_node_receive_from_isr(handle, &rx_frame) == ESP_OK)
    {
        q_frame.header = rx_frame.header;
        q_frame.buffer_len = (uint8_t)rx_frame.buffer_len;
        if (g_twai_rx_queue != nullptr)
        {
            xQueueSendFromISR(g_twai_rx_queue, &q_frame, &high_task_woken);
        }
    }

    return (high_task_woken == pdTRUE);
}

static IRAM_ATTR bool twai_state_change_cb(twai_node_handle_t handle, const twai_state_change_event_data_t *edata, void *user_ctx)
{
    if (edata->new_sta == TWAI_ERROR_BUS_OFF)
    {
        g_twai_bus_off = true;
        ESP_EARLY_LOGW(TAG, "TWAI entered BUS_OFF! Initiating recovery...");
        twai_node_recover(handle);
    }
    else if (edata->new_sta == TWAI_ERROR_ACTIVE)
    {
        g_twai_bus_off = false;
        ESP_EARLY_LOGI(TAG, "TWAI returned to ERROR_ACTIVE.");
    }
    else if (edata->new_sta == TWAI_ERROR_PASSIVE)
    {
        ESP_EARLY_LOGW(TAG, "TWAI entered ERROR_PASSIVE.");
    }
    else if (edata->new_sta == TWAI_ERROR_WARNING)
    {
        ESP_EARLY_LOGW(TAG, "TWAI entered ERROR_WARNING.");
    }

    return false;
}

static IRAM_ATTR bool twai_error_cb(twai_node_handle_t handle, const twai_error_event_data_t *edata, void *user_ctx)
{
    return false;
}

// -----------------------------------------------------------------------------
// Driver Init & Lifecycle
// -----------------------------------------------------------------------------

esp_err_t initCAN(frameDispatcher_t *frameDispatcher)
{
    if (g_twai_node_hdl != nullptr)
    {
        ESP_LOGW(TAG, "TWAI driver already initialized");
        return ESP_OK;
    }

    dispatchCANFrame = frameDispatcher;

    // Initialize TX frame pool queue
    if (s_tx_pool_queue == nullptr)
    {
        s_tx_pool_queue = xQueueCreate(TWAI_TX_POOL_SIZE, sizeof(twai_tx_slot_t *));
        if (s_tx_pool_queue == nullptr)
        {
            ESP_LOGE(TAG, "Failed to create TWAI TX pool queue");
            return ESP_ERR_NO_MEM;
        }
        for (int i = 0; i < TWAI_TX_POOL_SIZE; i++)
        {
            twai_tx_slot_t *slot = &s_tx_slots[i];
            xQueueSend(s_tx_pool_queue, &slot, 0);
        }
    }

    // Initialize RX queue for ISR handoff upfront before enabling callbacks/node
    if (g_twai_rx_queue == nullptr)
    {
        g_twai_rx_queue = xQueueCreate(32, sizeof(twai_queued_frame_t));
        if (g_twai_rx_queue == nullptr)
        {
            ESP_LOGE(TAG, "Failed to create TWAI RX queue");
            return ESP_ERR_NO_MEM;
        }
    }

    twai_onchip_node_config_t node_config = {};
    node_config.io_cfg.tx = (gpio_num_t)CONFIG_CAN_TX;
    node_config.io_cfg.rx = (gpio_num_t)CONFIG_CAN_RX;
    node_config.io_cfg.quanta_clk_out = (gpio_num_t)-1;
    node_config.io_cfg.bus_off_indicator = (gpio_num_t)-1;
    node_config.bit_timing.bitrate = 500000;
    node_config.fail_retry_cnt = -1; // Retransmit until success or bus-off
    node_config.tx_queue_depth = TWAI_TX_POOL_SIZE;
#if CONFIG_CAN_ENABLE_LOOPBACK
    node_config.flags.enable_loopback = 1;
#endif

    esp_err_t ret = twai_new_node_onchip(&node_config, &g_twai_node_hdl);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Failed to allocate TWAI node: %s", esp_err_to_name(ret));
        return ret;
    }

    twai_event_callbacks_t cbs = {
        .on_tx_done = twai_tx_done_cb,
        .on_rx_done = twai_rx_done_cb,
        .on_state_change = twai_state_change_cb,
        .on_error = twai_error_cb,
    };

    ret = twai_node_register_event_callbacks(g_twai_node_hdl, &cbs, nullptr);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Failed to register TWAI event callbacks: %s", esp_err_to_name(ret));
        twai_node_delete(g_twai_node_hdl);
        g_twai_node_hdl = nullptr;
        return ret;
    }

    ret = twai_node_enable(g_twai_node_hdl);
    if (ret != ESP_OK)
    {
        ESP_LOGE(TAG, "Failed to enable TWAI node: %s", esp_err_to_name(ret));
        twai_node_delete(g_twai_node_hdl);
        g_twai_node_hdl = nullptr;
        return ret;
    }

    ESP_LOGD(TAG, "TWAI modern driver started successfully (500 kbps, TX: %d, RX: %d)", CONFIG_CAN_TX, CONFIG_CAN_RX);

    // Only create worker task if a frame dispatcher is attached
    if (dispatchCANFrame != nullptr)
    {
        BaseType_t twai_core_id = CONFIG_CAN_CORE_AFFINITY;
        if (xTaskCreatePinnedToCore(CAN_RX_Task, "twai RX worker", 4096, NULL, 5, &CAN_RX_tsk_hdl, twai_core_id) != pdPASS)
        {
            ESP_LOGE(TAG, "Failed to create TWAI RX worker task");
            return ESP_FAIL;
        }
        else
        {
            ESP_LOGD(TAG, "TWAI RX worker task created on Core %d", (int)twai_core_id);
        }
    }

    return ESP_OK;
}

// -----------------------------------------------------------------------------
// Transmission APIs
// -----------------------------------------------------------------------------

esp_err_t twai_transmit_frame(const twai_frame_t *frame, int timeout_ms)
{
    if (g_twai_node_hdl == nullptr || frame == nullptr)
    {
        return ESP_ERR_INVALID_STATE;
    }

    if (g_twai_bus_off)
    {
        return ESP_ERR_INVALID_STATE;
    }

    if (s_tx_pool_queue == nullptr)
    {
        return ESP_ERR_INVALID_STATE;
    }

    TickType_t wait_ticks = (timeout_ms <= 0) ? 0 : pdMS_TO_TICKS(timeout_ms);
    twai_tx_slot_t *slot = nullptr;

    if (xQueueReceive(s_tx_pool_queue, &slot, wait_ticks) != pdTRUE || slot == nullptr)
    {
        ESP_LOGD(TAG, "TX frame pool exhausted (all slots pending transmission)");
        return ESP_ERR_TIMEOUT;
    }

    slot->frame = *frame;
    slot->frame.buffer = slot->buffer;
    size_t copy_len = (frame->buffer_len <= sizeof(slot->buffer)) ? frame->buffer_len : sizeof(slot->buffer);
    slot->frame.buffer_len = copy_len;
    if (frame->buffer != nullptr && copy_len > 0)
    {
        memcpy(slot->buffer, frame->buffer, copy_len);
    }

    esp_err_t ret = twai_node_transmit(g_twai_node_hdl, &slot->frame, timeout_ms);
    if (ret != ESP_OK)
    {
        xQueueSend(s_tx_pool_queue, &slot, 0);
    }

    return ret;
}

esp_err_t twai_transmit_msg(uint32_t can_id, const uint8_t *data, uint8_t dlc, bool is_ext, int timeout_ms)
{
    if (g_twai_node_hdl == nullptr || (data == nullptr && dlc > 0))
    {
        return ESP_ERR_INVALID_STATE;
    }

    if (g_twai_bus_off)
    {
        return ESP_ERR_INVALID_STATE;
    }

    if (s_tx_pool_queue == nullptr)
    {
        return ESP_ERR_INVALID_STATE;
    }

    TickType_t wait_ticks = (timeout_ms <= 0) ? 0 : pdMS_TO_TICKS(timeout_ms);
    twai_tx_slot_t *slot = nullptr;

    if (xQueueReceive(s_tx_pool_queue, &slot, wait_ticks) != pdTRUE || slot == nullptr)
    {
        ESP_LOGD(TAG, "TX frame pool exhausted (all slots pending transmission)");
        return ESP_ERR_TIMEOUT;
    }

    slot->frame = {};
    slot->frame.header.id = can_id;
    slot->frame.header.dlc = dlc;
    slot->frame.header.ide = is_ext ? 1 : 0;
    slot->frame.header.rtr = 0;
    slot->frame.buffer = slot->buffer;
    slot->frame.buffer_len = dlc;
    if (data != nullptr && dlc > 0)
    {
        uint8_t copy_bytes = (dlc <= sizeof(slot->buffer)) ? dlc : sizeof(slot->buffer);
        memcpy(slot->buffer, data, copy_bytes);
    }

    esp_err_t ret = twai_node_transmit(g_twai_node_hdl, &slot->frame, timeout_ms);
    if (ret != ESP_OK)
    {
        xQueueSend(s_tx_pool_queue, &slot, 0);
    }

    return ret;
}

esp_err_t twai_receive_queued_frame(twai_queued_frame_t *frame, TickType_t wait_ticks)
{
    if (g_twai_rx_queue == nullptr || frame == nullptr)
    {
        return ESP_ERR_INVALID_STATE;
    }
    if (xQueueReceive(g_twai_rx_queue, frame, wait_ticks) == pdTRUE)
    {
        return ESP_OK;
    }
    return ESP_ERR_TIMEOUT;
}

esp_err_t twai_clear_rx_queue()
{
    if (g_twai_rx_queue == nullptr)
    {
        return ESP_ERR_INVALID_STATE;
    }
    xQueueReset(g_twai_rx_queue);
    return ESP_OK;
}

// -----------------------------------------------------------------------------
// RX Ingestion Worker Task
// -----------------------------------------------------------------------------

void CAN_RX_Task(void *pvParameters)
{
    ESP_LOGD(TAG, "CAN_RX_Task has started");
    twai_queued_frame_t q_frame;
    CAN_RX_TimedOut = false;

    while (true)
    {
        if (xQueueReceive(g_twai_rx_queue, &q_frame, pdMS_TO_TICKS(CONFIG_CAN_RX_TIMEOUT_MS)) == pdPASS)
        {
            CAN_RX_TimedOut = false;
            if (dispatchCANFrame != nullptr)
            {
                twai_frame_t rx_frame = {};
                rx_frame.header = q_frame.header;
                rx_frame.buffer = q_frame.data;
                rx_frame.buffer_len = q_frame.buffer_len;

                if (dispatchCANFrame(&rx_frame) != ESP_OK)
                {
                    ESP_LOGD(TAG, "Frame dispatcher returned an error for ID: 0x%03lX", q_frame.header.id);
                }
            }
        }
        else
        {
            CAN_RX_TimedOut = true;
        }
    }
}

