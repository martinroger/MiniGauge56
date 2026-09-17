/**
 * @file twai_can_daemon.h
 * @brief Turnkey ESP-IDF TWAI / CAN 2.0B Driver with Zero-Copy TX & Auto-Recovery
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "driver/twai.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Callback prototype for received CAN frames.
 *
 * @param[in] message Pointer to received TWAI message.
 * @return ESP_OK on success.
 */
typedef esp_err_t (*twai_rx_callback_t)(const twai_message_t *message);

/**
 * @brief Configuration parameters for TWAI initialization.
 */
typedef struct {
    int tx_gpio;                    /**< Transmit GPIO pin number */
    int rx_gpio;                    /**< Receive GPIO pin number */
    twai_timing_config_t timing;    /**< Baud rate timing config (e.g. TWAI_TIMING_CONFIG_500KBITS()) */
    int rx_task_core;               /**< CPU Core affinity for RX task (0 or 1). Default: 1 */
    uint32_t rx_task_stack_size;    /**< Stack size for RX task in bytes. Default: 4096 */
    twai_rx_callback_t rx_callback; /**< Optional frame dispatch callback (can be NULL if TX only) */
} twai_daemon_config_t;

/**
 * @brief Initialize TWAI controller, install driver, and start background worker tasks.
 *
 * @param[in] config Configuration parameters.
 * @return ESP_OK on success, or error code from ESP-IDF driver.
 */
esp_err_t twai_daemon_init(const twai_daemon_config_t *config);

/**
 * @brief Transmit a CAN frame asynchronously with timeout.
 *
 * Thread-safe transmission helper using static descriptor buffers.
 *
 * @param[in] id CAN message identifier (11-bit standard or 29-bit extended).
 * @param[in] data Payload data buffer (up to 8 bytes).
 * @param[in] len Data length code (0 to 8 bytes).
 * @param[in] is_ext True for 29-bit extended ID, false for 11-bit standard ID.
 * @param[in] timeout_ms Transmission timeout in milliseconds.
 * @return ESP_OK on success, ESP_ERR_TIMEOUT, or driver error code.
 */
esp_err_t twai_daemon_transmit(uint32_t id, const uint8_t *data, uint8_t len, bool is_ext, uint32_t timeout_ms);

/**
 * @brief Check if the CAN controller is currently in BUS_OFF recovery mode.
 *
 * @return True if in bus-off recovery, false if bus is healthy.
 */
bool twai_daemon_is_bus_off(void);

/**
 * @brief Stop and uninstall the TWAI controller.
 *
 * @return ESP_OK on success.
 */
esp_err_t twai_daemon_deinit(void);

#ifdef __cplusplus
}
#endif
