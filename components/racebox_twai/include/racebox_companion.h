/**
 * @file racebox_companion.h
 * @brief Turnkey top-level orchestrator and wrapper API for RaceBoxCompanion.
 *
 * Provides a modular, single-entrypoint initialization and lifecycle API for
 * embedding RaceBox BLE telemetry ingestion and TWAI CAN broadcasting into
 * any ESP-IDF project.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"
#include "racebox_types.h"
#include "racebox_ble.h"
#include "racebox_twai.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Configuration parameters for the turnkey RaceBox Companion orchestrator.
 */
typedef struct {
    const char             *name_prefix;      /**< BLE device name prefix (Default: "RaceBox ") */
    bool                    auto_can_forward; /**< True to automatically forward valid PVT frames to CAN bus (Default: true) */
    racebox_pvt_callback_t  pvt_cb;           /**< Optional user callback for decoded telemetry (Default: NULL) */
    racebox_ble_event_cb_t  ble_evt_cb;       /**< Optional user callback for BLE lifecycle events (Default: NULL) */
    void                   *user_data;        /**< User context pointer passed to callbacks (Default: NULL) */
} racebox_companion_config_t;

/**
 * @brief Combined diagnostic metrics across BLE parser, TWAI CAN bus, and ESP32 system health.
 */
typedef struct {
    racebox_parser_stats_t ble_parser;                /**< BLE parser statistics */
    racebox_twai_stats_t   twai_stats;                /**< TWAI CAN transmit statistics */
    uint16_t               negotiated_mtu;            /**< Active negotiated GATT MTU */
    racebox_ble_state_t    ble_state;                 /**< Current BLE Central state */
    uint32_t               free_heap_bytes;           /**< Current free heap size in bytes */
    uint32_t               min_free_heap_bytes;       /**< Historical minimum free heap size in bytes */
    uint32_t               twai_task_stack_min_words; /**< Stack high-water mark for TWAI task (in words) */
} racebox_companion_stats_t;

/**
 * @brief Initialize all RaceBox subsystems (NVS, BLE Central, TWAI CAN Driver).
 *
 * Strictly guarded against double-initialization failures.
 *
 * @param[in] config Pointer to orchestrator configuration (Default settings used if NULL).
 * @return ESP_OK on success, or an error code on failure.
 * @note Idempotent: strictly guarded against double-initialization failures.
 * @note Thread-safety: Not thread-safe. Must be invoked during single-threaded application startup.
 */
esp_err_t racebox_companion_init(const racebox_companion_config_t *config);

/**
 * @brief Start active scanning and connection to target RaceBox device.
 *
 * @return ESP_OK on success.
 * @note Initiates BLE Central scanning for configured RaceBox devices.
 * @note Thread-safety: Not thread-safe.
 */
esp_err_t racebox_companion_start(void);

/**
 * @brief Stop scanning or disconnect active link.
 *
 * @return ESP_OK on success.
 * @note Halts BLE Central scanning or terminates active link with RaceBox.
 * @note Thread-safety: Not thread-safe.
 */
esp_err_t racebox_companion_stop(void);

/**
 * @brief Query combined diagnostic metrics across BLE and CAN.
 *
 * @param[out] stats Pointer to caller-allocated stats structure.
 * @return ESP_OK on success, or ESP_ERR_INVALID_ARG if stats is NULL.
 * @note Thread-safety: Thread-safe.
 */
esp_err_t racebox_companion_get_stats(racebox_companion_stats_t *stats);

#ifdef __cplusplus
}
#endif
