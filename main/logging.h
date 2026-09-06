#pragma once

#ifndef LOGGING_H
#define LOGGING_H

#include <stdint.h>
#include <stdbool.h>
#include "esp_twai_types.h"

/**
 * @file logging.h
 * @brief High-throughput CAN telemetry logging subsystem to SD card.
 *
 * Manages an asynchronous PSRAM ringbuffer and SD card writer task for logging
 * received TWAI/CAN frames, with metrics exported for LVGL UI presentation.
 */

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief Current active log file path on the mounted SD card.
 */
extern char current_log_filename[64];

/**
 * @brief Total size in bytes of data written to the active log file.
 */
extern uint32_t current_file_size;

/**
 * @brief Current depth in bytes buffered in the batch memory queue.
 */
extern uint32_t current_buffered_bytes;

/**
 * @brief State flag indicating whether CAN logging to SD is currently active.
 */
extern bool is_logging;

/**
 * @brief Initializes the PSRAM ringbuffer for buffering incoming CAN frames.
 *
 * @return bool True if PSRAM storage allocation and ringbuffer creation succeed, false otherwise.
 * @note Thread-safety: Not thread-safe. Must be invoked once during system initialization before starting logging.
 * @note Side effects: Allocates 32 KB in PSRAM (MALLOC_CAP_SPIRAM) for static ringbuffer storage.
 */
bool init_can_logging(void);

/**
 * @brief Ingests and buffers a received TWAI frame into the logging ringbuffer.
 *
 * Called by the top-level CAN frame router. If logging is active, converts the TWAI
 * frame to a 16-byte packed log record and enqueues it with zero-timeout non-blocking semantics.
 *
 * @param[in] frame Pointer to received TWAI frame descriptor.
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 * @note Side effects: Pushes a 16-byte record into can_rb if is_logging is true. Drops frame if ringbuffer is full.
 */
void log_can_frame_handler(const twai_frame_t *frame);

/**
 * @brief Starts the background SD writer task and begins recording incoming frames.
 *
 * @note Thread-safety: Thread-safe.
 * @note Side effects: Sets is_logging to true, opens a new timestamped file on SD card,
 *                    and spawns the sd_writer FreeRTOS task (stack 4096, priority 5).
 */
void start_logging(void);

/**
 * @brief Stops active logging and signals the SD writer task to flush remaining frames and terminate.
 *
 * @note Thread-safety: Thread-safe.
 * @note Side effects: Sets is_logging to false.
 */
void stop_logging(void);

/**
 * @brief Starts an internal SD logging stress test using a synthetic frame generator task.
 *
 * @note Thread-safety: Thread-safe.
 * @note Side effects: Sets is_logging to true, spawns sd_writer task, and spawns mock_can task.
 */
void start_logging_test(void);

#ifdef __cplusplus
}
#endif

#endif // LOGGING_H