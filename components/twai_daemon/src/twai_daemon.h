#pragma once
#include "driver/gpio.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "stdio.h"
#include "stdlib.h"
#include "esp_twai.h"
#include "esp_twai_onchip.h"
#include "esp_twai_types.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"

/** @brief Default GPIO pin for TWAI RX if not configured in Kconfig */
#ifndef CONFIG_CAN_RX
#define CONFIG_CAN_RX 3
#endif

/** @brief Default GPIO pin for TWAI TX if not configured in Kconfig */
#ifndef CONFIG_CAN_TX
#define CONFIG_CAN_TX 2
#endif

/** @brief Default FreeRTOS core affinity for the CAN RX worker task */
#ifndef CONFIG_CAN_CORE_AFFINITY
#define CONFIG_CAN_CORE_AFFINITY 1
#endif

/** @brief Default timeout in milliseconds for the CAN RX worker task before setting CAN_RX_TimedOut */
#ifndef CONFIG_CAN_RX_TIMEOUT_MS
#define CONFIG_CAN_RX_TIMEOUT_MS 3000
#endif

/**
 * @brief Queued frame container for thread-safe ISR-to-Task handoff.
 */
typedef struct {
    twai_frame_header_t header; /**< TWAI frame header containing ID, DLC, and flags */
    uint8_t data[8];            /**< Payload data buffer */
    uint8_t buffer_len;         /**< Length of valid payload data bytes */
} twai_queued_frame_t;

/**
 * @brief Callback function prototype for dispatching received TWAI frames.
 * 
 * @param[in] messageToDispatch Pointer to received TWAI frame.
 * @return esp_err_t ESP_OK on successful dispatch handling, or error code.
 */
typedef esp_err_t frameDispatcher_t(const twai_frame_t *messageToDispatch);

/**
 * @brief Global TWAI on-chip node handle.
 */
extern twai_node_handle_t g_twai_node_hdl;

/**
 * @brief Pointer to frame dispatcher function, registered during initCAN().
 */
extern frameDispatcher_t *dispatchCANFrame;

/**
 * @brief Status flag set to true if the CAN RX worker task timed out waiting for incoming frames.
 */
extern bool CAN_RX_TimedOut;

/**
 * @brief State flag set to true if the TWAI controller has entered the BUS_OFF state.
 */
extern bool g_twai_bus_off;

/**
 * @brief FreeRTOS task handle for the CAN RX worker task.
 */
extern TaskHandle_t CAN_RX_tsk_hdl;

/**
 * @brief FreeRTOS queue handle for buffered TWAI frames received from ISR.
 */
extern QueueHandle_t g_twai_rx_queue;

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Initialises the modern TWAI driver node and attaches optional frame dispatcher function.
 * 
 * @param[in] frameDispatcher Pointer to frame dispatcher callback function or nullptr if RX dispatch is not needed (Default: nullptr).
 * @return esp_err_t ESP_OK on success, or driver/queue allocation error code otherwise.
 * @note Thread-safety: Not thread-safe. Must be invoked once during system initialization.
 * @note Side effects: Allocates internal TX pool and RX queue, configures and enables on-chip TWAI peripheral,
 *                    registers ISR callbacks, and spawns CAN_RX_Task if frameDispatcher is provided.
 */
#ifdef __cplusplus
esp_err_t initCAN(frameDispatcher_t *frameDispatcher = nullptr);
#else
esp_err_t initCAN(frameDispatcher_t *frameDispatcher);
#endif

/**
 * @brief Transmit a TWAI frame directly into driver queue using the zero-copy TX pool.
 * 
 * @param[in] frame Pointer to twai_frame_t structure containing frame header and buffer.
 * @param[in] timeout_ms Maximum time to wait in milliseconds for an available TX slot and transmission (Default: 10).
 * @return esp_err_t ESP_OK on success, ESP_ERR_INVALID_STATE if driver is uninitialized or in bus-off,
 *                   ESP_ERR_TIMEOUT if pool is exhausted or transmission timed out.
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 * @note Side effects: Acquires a slot from internal TX frame pool, copies frame data, and passes frame to TWAI driver.
 */
#ifdef __cplusplus
esp_err_t twai_transmit_frame(const twai_frame_t *frame, int timeout_ms = 10);
#else
esp_err_t twai_transmit_frame(const twai_frame_t *frame, int timeout_ms);
#endif

/**
 * @brief Helper to transmit standard or extended CAN message payload.
 * 
 * @param[in] can_id CAN identifier (11-bit standard or 29-bit extended).
 * @param[in] data Pointer to payload data buffer (can be nullptr if dlc is 0).
 * @param[in] dlc Data length code (0 to 8 bytes).
 * @param[in] is_ext Extended frame flag: true for 29-bit extended ID, false for 11-bit standard ID (Default: false).
 * @param[in] timeout_ms Maximum time to wait in milliseconds for an available TX slot and transmission (Default: 10).
 * @return esp_err_t ESP_OK on success, ESP_ERR_INVALID_STATE if driver is uninitialized or in bus-off,
 *                   ESP_ERR_TIMEOUT if pool is exhausted or transmission timed out.
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 * @note Side effects: Populates a TX frame slot from the pool and schedules it for transmission.
 */
#ifdef __cplusplus
esp_err_t twai_transmit_msg(uint32_t can_id, const uint8_t *data, uint8_t dlc, bool is_ext = false, int timeout_ms = 10);
#else
esp_err_t twai_transmit_msg(uint32_t can_id, const uint8_t *data, uint8_t dlc, bool is_ext, int timeout_ms);
#endif

/**
 * @brief Receive a queued frame directly from the RX queue.
 * 
 * @param[out] frame Output pointer to receive the queued frame struct.
 * @param[in] wait_ticks FreeRTOS ticks to wait for incoming frame.
 * @return esp_err_t ESP_OK on success, ESP_ERR_INVALID_STATE if RX queue uninitialized or frame is nullptr,
 *                   ESP_ERR_TIMEOUT if wait period expired.
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 * @note Side effects: Dequeues a frame from g_twai_rx_queue.
 */
esp_err_t twai_receive_queued_frame(twai_queued_frame_t *frame, TickType_t wait_ticks);

/**
 * @brief Clears all pending frames in the RX queue.
 * 
 * @return esp_err_t ESP_OK on success, ESP_ERR_INVALID_STATE if RX queue uninitialized.
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 * @note Side effects: Resets g_twai_rx_queue, discarding any buffered frames.
 */
esp_err_t twai_clear_rx_queue(void);

/**
 * @brief FreeRTOS task that ingests frames from ISR queue and sends to dispatcher.
 * 
 * @param[in] pvParameters Task parameters passed by FreeRTOS (unused).
 * @note Thread-safety: Runs as an independent FreeRTOS task pinned to CONFIG_CAN_CORE_AFFINITY.
 * @note Side effects: Blocks on g_twai_rx_queue, invokes dispatchCANFrame callback, and updates CAN_RX_TimedOut.
 */
void CAN_RX_Task(void *pvParameters);

#ifdef __cplusplus
}
#endif