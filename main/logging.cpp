#include "logging.h"
#include <stdio.h>
#include <string.h>
#include <sys/unistd.h>
#include "esp_vfs_fat.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/ringbuf.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "twai_daemon.h"
#include <time.h>
#include <sys/time.h>

/**
 * @file logging.cpp
 * @brief Implementation of high-throughput CAN frame logging to SD card.
 *
 * Receives TWAI frames from the twai_daemon dispatcher callback, buffers them in a 32 KB
 * PSRAM ringbuffer, and flushes blocks of 512 frames (8 KB) to the SD card via sd_writer_task.
 */

// LVGL Globals
char current_log_filename[64] = "None";
uint32_t current_file_size = 0;
uint32_t current_buffered_bytes = 0;
bool is_logging = false;
bool is_gps_time_synced = false;
static volatile bool sd_writer_running = false;

void logging_set_gps_synced(bool synced)
{
    is_gps_time_synced = synced;
}

/**
 * @brief Packed 16-byte binary record representing a single logged CAN frame.
 */
typedef struct
{
    uint32_t timestamp; /**< Milliseconds timestamp since boot (4 bytes) */
    uint16_t id;        /**< Standard 11-bit CAN frame identifier (2 bytes) */
    uint8_t dlc;        /**< Data length code (1 byte, 0-8) */
    uint8_t data[8];    /**< Frame payload data (8 bytes) */
    uint8_t padding;    /**< Explicit padding byte to maintain 16-byte alignment */
} __attribute__((packed)) can_log_record_t;

/** @brief Number of 16-byte frame records per DMA block written to SD */
#define FRAMES_PER_BLOCK 512

/** @brief Total size in bytes of a single block write to SD card (8 KB) */
#define BLOCK_SIZE (FRAMES_PER_BLOCK * sizeof(can_log_record_t))

/** @brief Size in bytes of the intermediate PSRAM ringbuffer (32 KB) */
#define RB_SIZE (32 * 1024)

/** @brief Maximum period in milliseconds before partially filled block is flushed to SD */
#define LAZY_FLUSH_MS 5000

/** @brief Handle to the statically allocated PSRAM ringbuffer */
static RingbufHandle_t can_rb = NULL;

/**
 * @brief Frame ingestion callback registered with the CAN frame routing pipeline.
 *
 * Packs incoming TWAI frames into 16-byte records and pushes them non-blocking
 * to the PSRAM ringbuffer if logging is active.
 *
 * @param[in] frame Pointer to received TWAI frame descriptor.
 * @note Thread-safety: Thread-safe across FreeRTOS tasks.
 * @note Side effects: Copies frame into can_rb if is_logging is true; drops on overflow.
 */
void log_can_frame_handler(const twai_frame_t *frame)
{
    if (frame == NULL || !is_logging || can_rb == NULL)
    {
        return;
    }

    can_log_record_t record;

    // Pack the 16-byte struct
    record.timestamp = (uint32_t)(esp_timer_get_time() / 1000);
    record.id = (uint16_t)frame->header.id;
    record.dlc = frame->header.dlc;
    record.padding = 0;

    // Clear and copy data payload
    memset(record.data, 0, sizeof(record.data));
    uint8_t len = (record.dlc > 8) ? 8 : record.dlc;
    if (frame->buffer != NULL && len > 0)
    {
        memcpy(record.data, frame->buffer, len);
    }

    // Push to PSRAM Ring Buffer with zero-wait non-blocking semantics
    xRingbufferSend(can_rb, &record, sizeof(can_log_record_t), 0);
}

/**
 * @brief FreeRTOS task that drains the PSRAM ringbuffer and writes batch blocks to SD card.
 *
 * @param[in] pvParameters Task parameters passed by FreeRTOS (unused).
 * @note Thread-safety: Runs as an independent worker task.
 * @note Side effects: Opens log file on /sdcard, performs block DMA writes, and updates LVGL metrics.
 */
static void sd_writer_task(void *pvParameters)
{
    sd_writer_running = true;

    time_t now_epoch = time(NULL);
    if (is_gps_time_synced && now_epoch > 1700000000)
    {
        struct tm tm_utc;
        gmtime_r(&now_epoch, &tm_utc);
        snprintf(current_log_filename, sizeof(current_log_filename),
                 "/sdcard/%04d%02d%02d_log_%02d%02d%02d.bin",
                 tm_utc.tm_year + 1900, tm_utc.tm_mon + 1, tm_utc.tm_mday,
                 tm_utc.tm_hour, tm_utc.tm_min, tm_utc.tm_sec);
    }
    else
    {
        snprintf(current_log_filename, sizeof(current_log_filename),
                 "/sdcard/log_%lld.bin", esp_timer_get_time());
    }
    current_file_size = 0;

    FILE *f = fopen(current_log_filename, "wb");
    if (!f)
    {
        is_logging = false;
        sd_writer_running = false;
        vTaskDelete(NULL);
        return;
    }
    setvbuf(f, NULL, _IONBF, 0);

    can_log_record_t *batch_buffer = (can_log_record_t *)heap_caps_malloc(BLOCK_SIZE, MALLOC_CAP_DMA);
    if (!batch_buffer)
    {
        fclose(f);
        is_logging = false;
        sd_writer_running = false;
        vTaskDelete(NULL);
        return;
    }

    size_t items_in_batch = 0;
    uint32_t last_flush_time = (uint32_t)(esp_timer_get_time() / 1000);

    while (true)
    {
        size_t item_size;
        // Wait up to 100ms while active; poll immediately (0ms) once stopping to drain remaining items
        TickType_t wait_ticks = is_logging ? pdMS_TO_TICKS(100) : 0;
        can_log_record_t *item = (can_log_record_t *)xRingbufferReceive(can_rb, &item_size, wait_ticks);

        if (item)
        {
            memcpy(&batch_buffer[items_in_batch++], item, sizeof(can_log_record_t));
            vRingbufferReturnItem(can_rb, (void *)item);

            while (items_in_batch < FRAMES_PER_BLOCK)
            {
                can_log_record_t *next = (can_log_record_t *)xRingbufferReceive(can_rb, &item_size, 0);
                if (!next)
                    break;
                memcpy(&batch_buffer[items_in_batch++], next, sizeof(can_log_record_t));
                vRingbufferReturnItem(can_rb, (void *)next);
            }
        }

        current_buffered_bytes = items_in_batch * 16;

        uint32_t now = (uint32_t)(esp_timer_get_time() / 1000);
        bool flush_due_to_time = (items_in_batch > 0 && (now - last_flush_time > LAZY_FLUSH_MS));
        bool flush_due_to_stop = (items_in_batch > 0 && !is_logging);
        bool block_full = (items_in_batch >= FRAMES_PER_BLOCK);

        if (block_full || flush_due_to_time || flush_due_to_stop)
        {
            size_t bytes_to_write = items_in_batch * sizeof(can_log_record_t);
            fwrite(batch_buffer, 1, bytes_to_write, f);
            fsync(fileno(f));

            current_file_size += bytes_to_write; // Update for LVGL
            items_in_batch = 0;
            last_flush_time = now;
            current_buffered_bytes = 0;
        }

        // Exit once logging has stopped, no items remain in the current batch, and ringbuffer is drained
        if (!is_logging && item == NULL && items_in_batch == 0)
        {
            break;
        }
    }

    heap_caps_free(batch_buffer);
    fclose(f);
    current_buffered_bytes = 0;
    sd_writer_running = false;
    vTaskDelete(NULL);
}

bool init_can_logging(void)
{
    if (can_rb != NULL)
    {
        return true;
    }

    // RingBuffer Init (PSRAM)
    uint8_t *storage = (uint8_t *)heap_caps_malloc(RB_SIZE, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    static StaticRingbuffer_t rb_struct;
    if (storage != NULL)
    {
        can_rb = xRingbufferCreateStatic(RB_SIZE, RINGBUF_TYPE_NOSPLIT, storage, &rb_struct);
    }

    return (can_rb != NULL);
}

void start_logging(void)
{
    if (!is_logging && !sd_writer_running && can_rb)
    {
        // Purge any stale records from previous session to guarantee a fresh start
        size_t stale_size;
        void *stale_item;
        while ((stale_item = xRingbufferReceive(can_rb, &stale_size, 0)) != NULL)
        {
            vRingbufferReturnItem(can_rb, stale_item);
        }

        is_logging = true;
        xTaskCreate(sd_writer_task, "sd_writer", 4096, NULL, 5, NULL);
        ESP_LOGI(__func__, "Block size: %lu", BLOCK_SIZE);
    }
}

void stop_logging(void)
{
    is_logging = false;
}

/**
 * @brief FreeRTOS task generating synthetic CAN records to test SD write throughput.
 *
 * @param[in] pvParameters Task parameters passed by FreeRTOS (unused).
 * @note Thread-safety: Runs as an independent worker task.
 * @note Side effects: Pushes synthetic 16-byte records into can_rb every 2 ms (500 Hz).
 */
static void mock_can_producer_task(void *pvParameters)
{
    uint8_t count = 0;
    uint16_t mock_id = 0x123;

    ESP_LOGW("MOCK", "Starting dummy data generator @ 500 Hz");

    while (is_logging)
    {
        // 1. Manually pack the 16-byte struct
        can_log_record_t record;
        record.timestamp = (uint32_t)(esp_timer_get_time() / 1000);
        record.id = mock_id;
        record.dlc = 8;
        record.padding = 0; // Maintain 16-byte alignment

        // 2. Fill data with incrementing counter for integrity checks
        memset(record.data, 0xAA, 8);
        record.data[0] = count++;

        // 3. Push to Ring Buffer
        if (can_rb)
        {
            xRingbufferSend(can_rb, &record, sizeof(can_log_record_t), 0);
        }

        // 500Hz = 2ms delay
        vTaskDelay(pdMS_TO_TICKS(2));
    }

    vTaskDelete(NULL);
}

void start_logging_test(void)
{
    if (!is_logging && !sd_writer_running && can_rb)
    {
        // Purge any stale records from previous session to guarantee a fresh start
        size_t stale_size;
        void *stale_item;
        while ((stale_item = xRingbufferReceive(can_rb, &stale_size, 0)) != NULL)
        {
            vRingbufferReturnItem(can_rb, stale_item);
        }

        is_logging = true;
        // Start the SD Writer
        xTaskCreate(sd_writer_task, "sd_writer", 4096, NULL, 5, NULL);
        // Start the Dummy Generator
        xTaskCreate(mock_can_producer_task, "mock_can", 2048, NULL, 5, NULL);
        ESP_LOGI(__func__, "Block size: %lu", BLOCK_SIZE);
    }
}