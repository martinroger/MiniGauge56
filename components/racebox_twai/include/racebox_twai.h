/**
 * @file racebox_twai.h
 * @brief TWAI CAN frame encoding, scheduling, and transmission interface.
 *
 * Interfaces telemetry data from racebox_ble into standard 11-bit CAN messages
 * using the modern on-chip TWAI daemon from vx-binocle-espidf.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include "esp_err.h"
#include "racebox_types.h"
#include "racebox_can_types.h"

#if defined(ESP_PLATFORM)
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#else
typedef void *TaskHandle_t;
#endif

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Diagnostic metrics for TWAI CAN transmission.
 */
typedef struct {
    uint32_t frames_sent_total;     /**< Total CAN frames transmitted */
    uint32_t frames_speed_heading;  /**< RB_SPEED_HEADING frames transmitted */
    uint32_t frames_lat_lon;        /**< RB_LAT_LON frames transmitted */
    uint32_t frames_alt_acc;        /**< RB_ALT_ACCURACY frames transmitted */
    uint32_t frames_imu_accel;      /**< RB_IMU_ACCEL frames transmitted */
    uint32_t frames_imu_gyro;       /**< RB_IMU_GYRO frames transmitted */
    uint32_t frames_utc_time;       /**< RB_UTC_TIME frames transmitted */
    uint32_t tx_failed;             /**< Transmit attempts rejected or timed out */
    uint32_t tx_queue_dropped;      /**< Telemetry frames dropped due to full dispatch queue */
    uint32_t queue_depth_current;   /**< Current messages waiting in PVT dispatch queue */
    uint32_t queue_depth_peak;      /**< Peak messages waiting in PVT dispatch queue */
    float    can_tx_fps;            /**< Transmitted CAN frames per second over measurement window */
    float    bus_utilization_pct;   /**< Estimated CAN bus utilization percentage (0.0 to 100.0%) */
    bool     bus_off;               /**< True if currently in bus-off recovery */
} racebox_twai_stats_t;

/**
 * @brief Get the FreeRTOS task handle of the TWAI dispatch worker task.
 *
 * @return TaskHandle_t or NULL if uninitialized.
 * @note Thread-safety: Thread-safe.
 */
TaskHandle_t racebox_twai_get_task_handle(void);

/**
 * @brief Initialize the TWAI driver and CAN telemetry packaging engine.
 *
 * Safe against double-initialization.
 *
 * @return ESP_OK on success, or an error code from the driver.
 * @note Idempotent: safe against double-initialization.
 * @note Thread-safety: Not thread-safe. Must be invoked during single-threaded system initialization.
 */
esp_err_t racebox_twai_init(void);

/**
 * @brief Deinitialize the TWAI subsystem.
 *
 * @return ESP_OK on success.
 * @note Idempotent: safe to call if already uninitialized.
 * @note Thread-safety: Not thread-safe. Stops transmission worker task and tears down driver resources.
 */
esp_err_t racebox_twai_deinit(void);

/**
 * @brief Enqueue a telemetry frame for asynchronous CAN broadcast.
 *
 * Non-blocking. If the CAN queue is full (e.g. stalled CAN bus), the frame
 * is safely dropped without blocking the calling task (e.g. NimBLE host).
 *
 * @param[in] pvt Pointer to canonical telemetry structure.
 * @return ESP_OK if enqueued, ESP_ERR_TIMEOUT if dropped.
 * @note Non-blocking: will drop frames rather than block the calling task (e.g. NimBLE host).
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 */
esp_err_t racebox_twai_enqueue_pvt(const racebox_pvt_t *pvt);

/**
 * @brief Encode and broadcast a telemetry frame over CAN.
 *
 * Evaluates rate prescalers for all 6 messages and queues active frames into
 * the TWAI TX descriptor pool.
 *
 * @param[in] pvt Pointer to canonical telemetry structure.
 * @return ESP_OK on success, or error code on failure.
 * @note Evaluates rate prescalers (Kconfig) and transmits active frames.
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 */
esp_err_t racebox_twai_broadcast_pvt(const racebox_pvt_t *pvt);

/**
 * @brief Query current TWAI transmission statistics.
 *
 * @param[out] stats Pointer to caller-allocated stats structure.
 * @return ESP_OK on success, ESP_ERR_INVALID_ARG if stats is NULL, or
 *         ESP_ERR_NOT_SUPPORTED if CONFIG_RACEBOX_TWAI_STATS_ENABLE is disabled.
 * @note Thread-safety: Thread-safe.
 * @note If CONFIG_RACEBOX_TWAI_STATS_ENABLE is disabled via Kconfig, clears stats,
 *       updates the bus_off state flag, and returns ESP_ERR_NOT_SUPPORTED.
 */
esp_err_t racebox_twai_get_stats(racebox_twai_stats_t *stats);

/**
 * @brief Check if the CAN controller is in bus-off state.
 *
 * @return True if bus-off, false if active.
 * @note Thread-safety: Thread-safe.
 */
bool racebox_twai_is_bus_off(void);

#ifdef __cplusplus
}
#endif
