/**
 * @file twai_can_daemon.c
 * @brief Reference Implementation: ESP-IDF TWAI Controller with Auto Bus-Off Recovery
 */

#include "twai_can_daemon.h"
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"

static const char *TAG = "TWAI_DAEMON";

static bool s_is_initialized = false;
static bool s_bus_off = false;
static TaskHandle_t s_rx_task_handle = NULL;
static twai_rx_callback_t s_rx_callback = NULL;

static void twai_rx_worker_task(void *arg)
{
    ESP_LOGI(TAG, "TWAI RX worker task started on Core %d", xPortGetCoreID());

    while (1) {
        twai_message_t rx_msg;
        esp_err_t ret = twai_receive(&rx_msg, pdMS_TO_TICKS(100));
        if (ret == ESP_OK) {
            if (s_rx_callback) {
                s_rx_callback(&rx_msg);
            }
        } else if (ret != ESP_ERR_TIMEOUT) {
            // Check for driver alerts (Bus-Off, Recovery, etc.)
            uint32_t alerts = 0;
            twai_read_alerts(&alerts, 0);

            if (alerts & TWAI_ALERT_BUS_OFF) {
                s_bus_off = true;
                ESP_LOGE(TAG, "TWAI Bus-Off detected! Initiating auto-recovery...");
                twai_initiate_recovery();
            }
            if (alerts & TWAI_ALERT_BUS_RECOVERED) {
                ESP_LOGI(TAG, "TWAI Bus recovery complete. Restarting driver...");
                twai_start();
                s_bus_off = false;
            }
        }
    }
}

esp_err_t twai_daemon_init(const twai_daemon_config_t *config)
{
    if (!config) return ESP_ERR_INVALID_ARG;
    if (s_is_initialized) return ESP_ERR_INVALID_STATE;

    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(
        (gpio_num_t)config->tx_gpio,
        (gpio_num_t)config->rx_gpio,
        TWAI_MODE_NORMAL
    );
    g_config.rx_queue_len = 32;
    g_config.tx_queue_len = 32;
    g_config.alerts_mask = TWAI_ALERT_BUS_OFF | TWAI_ALERT_BUS_RECOVERED | TWAI_ALERT_ERR_PASS | TWAI_ALERT_ABOVE_ERR_WARN;

    twai_timing_config_t t_config = config->timing;
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    esp_err_t ret = twai_driver_install(&g_config, &t_config, &f_config);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to install TWAI driver: %s", esp_err_to_name(ret));
        return ret;
    }

    ret = twai_start();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "Failed to start TWAI driver: %s", esp_err_to_name(ret));
        twai_driver_uninstall();
        return ret;
    }

    s_rx_callback = config->rx_callback;
    s_bus_off = false;

    uint32_t stack_size = config->rx_task_stack_size > 0 ? config->rx_task_stack_size : 4096;
    int core_id = (config->rx_task_core == 0) ? 0 : 1;

    BaseType_t task_ret = xTaskCreatePinnedToCore(
        twai_rx_worker_task,
        "CAN_RX_Task",
        stack_size,
        NULL,
        configMAX_PRIORITIES - 3,
        &s_rx_task_handle,
        core_id
    );

    if (task_ret != pdPASS) {
        ESP_LOGE(TAG, "Failed to create CAN RX worker task");
        twai_stop();
        twai_driver_uninstall();
        return ESP_ERR_NO_MEM;
    }

    s_is_initialized = true;
    ESP_LOGI(TAG, "TWAI daemon initialized (TX: GPIO %d, RX: GPIO %d)", config->tx_gpio, config->rx_gpio);
    return ESP_OK;
}

esp_err_t twai_daemon_transmit(uint32_t id, const uint8_t *data, uint8_t len, bool is_ext, uint32_t timeout_ms)
{
    if (!s_is_initialized) return ESP_ERR_INVALID_STATE;
    if (s_bus_off) return ESP_ERR_INVALID_STATE;
    if (len > 8) len = 8;

    twai_message_t tx_msg;
    memset(&tx_msg, 0, sizeof(tx_msg));
    tx_msg.identifier = id;
    tx_msg.extd = is_ext ? 1 : 0;
    tx_msg.data_length_code = len;
    if (data && len > 0) {
        memcpy(tx_msg.data, data, len);
    }

    return twai_transmit(&tx_msg, pdMS_TO_TICKS(timeout_ms));
}

bool twai_daemon_is_bus_off(void)
{
    return s_bus_off;
}

esp_err_t twai_daemon_deinit(void)
{
    if (!s_is_initialized) return ESP_ERR_INVALID_STATE;

    if (s_rx_task_handle) {
        vTaskDelete(s_rx_task_handle);
        s_rx_task_handle = NULL;
    }

    twai_stop();
    twai_driver_uninstall();

    s_is_initialized = false;
    s_bus_off = false;
    s_rx_callback = NULL;
    return ESP_OK;
}
