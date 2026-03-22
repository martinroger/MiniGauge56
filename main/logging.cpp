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
#include "driver/twai.h"

// LVGL Globals
char current_log_filename[64] = "None";
uint32_t current_file_size = 0;
uint32_t current_buffered_bytes = 0;
bool is_logging = false;

typedef struct
{
    uint32_t timestamp; // 4 bytes
    uint16_t id;        // 2 bytes (Fits 0x7FF easily)
    uint8_t dlc;        // 1 byte
    uint8_t data[8];    // 8 bytes
    uint8_t padding;    // 1 byte (Explicitly brings total to 16)
} __attribute__((packed)) can_log_record_t;

#define FRAMES_PER_BLOCK 512
#define BLOCK_SIZE (FRAMES_PER_BLOCK * sizeof(can_log_record_t))
#define RB_SIZE (32 * 1024)
#define LAZY_FLUSH_MS 5000

static RingbufHandle_t can_rb = NULL;

// --- CAN Task: Drains the Hardware into the RingBuffer ---
static void can_rx_task(void *arg)
{
    twai_message_t rx_msg;

    while (1)
    {
        // 1. Block until a hardware frame arrives
        if (twai_receive(&rx_msg, pdMS_TO_TICKS(1000)) == ESP_OK)
        {

            // 2. Only process if logging is active
            if (is_logging && can_rb)
            {
                can_log_record_t record;

                // 3. Pack the 16-byte struct manually
                record.timestamp = (uint32_t)(esp_timer_get_time() / 1000);
                record.id = (uint16_t)rx_msg.identifier; // Cast 32-bit ID to 16-bit
                record.dlc = rx_msg.data_length_code;
                record.padding = 0;

                // Clear and copy data payload
                memset(record.data, 0, 8);
                uint8_t len = (record.dlc > 8) ? 8 : record.dlc;
                memcpy(record.data, rx_msg.data, len);

                // 4. Push to PSRAM Ring Buffer
                // If the buffer is full (overflow), this returns immediately
                xRingbufferSend(can_rb, &record, sizeof(can_log_record_t), 0);
            }
        }
    }
}

// --- SD Task: Drains the RingBuffer into the SD Card ---
static void sd_writer_task(void *pvParameters)
{
    sprintf(current_log_filename, "/sdcard/log_%lld.bin", esp_timer_get_time());
    current_file_size = 0;

    FILE *f = fopen(current_log_filename, "wb");
    if (!f)
    {
        is_logging = false;
        vTaskDelete(NULL);
        return;
    }
    setvbuf(f, NULL, _IONBF, 0);

    can_log_record_t *batch_buffer = (can_log_record_t *)heap_caps_malloc(BLOCK_SIZE, MALLOC_CAP_DMA);
    size_t items_in_batch = 0;
    uint32_t last_flush_time = esp_timer_get_time() / 1000;

    while (is_logging || items_in_batch > 0)
    {
        size_t item_size;
        can_log_record_t *item = (can_log_record_t *)xRingbufferReceive(can_rb, &item_size, pdMS_TO_TICKS(100));

        current_buffered_bytes = items_in_batch * 16;

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

        uint32_t now = esp_timer_get_time() / 1000;
        if (items_in_batch >= FRAMES_PER_BLOCK || (items_in_batch > 0 && (now - last_flush_time > LAZY_FLUSH_MS || !is_logging)))
        {
            size_t bytes_to_write = items_in_batch * sizeof(can_log_record_t);
            fwrite(batch_buffer, 1, bytes_to_write, f);
            fsync(fileno(f));

            current_file_size += bytes_to_write; // Update for LVGL
            items_in_batch = 0;
            last_flush_time = now;
        }
    }

    heap_caps_free(batch_buffer);
    fclose(f);
    vTaskDelete(NULL);
}

bool init_can_logging()
{
    // 1. TWAI Init
    twai_general_config_t g_config = TWAI_GENERAL_CONFIG_DEFAULT(GPIO_NUM_43, GPIO_NUM_44, TWAI_MODE_LISTEN_ONLY);
    twai_timing_config_t t_config = TWAI_TIMING_CONFIG_500KBITS();
    twai_filter_config_t f_config = TWAI_FILTER_CONFIG_ACCEPT_ALL();

    if (twai_driver_install(&g_config, &t_config, &f_config) != ESP_OK)
        return false;
    if (twai_start() != ESP_OK)
        return false;

    // 2. RingBuffer Init (PSRAM)
    uint8_t *storage = (uint8_t *)heap_caps_malloc(RB_SIZE, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    static StaticRingbuffer_t rb_struct;
    if (storage)
        can_rb = xRingbufferCreateStatic(RB_SIZE, RINGBUF_TYPE_NOSPLIT, storage, &rb_struct);

    // 3. Start high-priority CAN listener
    xTaskCreate(can_rx_task, "can_rx", 4096, NULL, 10, NULL);

    return (can_rb != NULL);
}

void start_logging()
{
    if (!is_logging && can_rb)
    {
        is_logging = true;
        xTaskCreate(sd_writer_task, "sd_writer", 4096, NULL, 5, NULL);
        ESP_LOGI(__func__, "Block size: %lu", BLOCK_SIZE);
    }
}

void stop_logging()
{
    is_logging = false;
}

static void mock_can_producer_task(void *pvParameters)
{
    uint8_t count = 0;
    uint16_t mock_id = 0x123;

    ESP_LOGW("MOCK", "Starting dummy data generator @ 20 Hz");

    while (is_logging)
    {
        // 1. Manually pack the "Golden" 16-byte struct
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
            BaseType_t res = xRingbufferSend(can_rb, &record, sizeof(can_log_record_t), 0);
        }

        // 20Hz = 50ms delay
        vTaskDelay(pdMS_TO_TICKS(2));
    }

    vTaskDelete(NULL);
}

void start_logging_test()
{
    if (!is_logging && can_rb)
    {
        is_logging = true;
        // Start the SD Writer
        xTaskCreate(sd_writer_task, "sd_writer", 4096, NULL, 5, NULL);
        // Start the Dummy Generator
        xTaskCreate(mock_can_producer_task, "mock_can", 2048, NULL, 5, NULL);
        ESP_LOGI(__func__, "Block size: %lu", BLOCK_SIZE);
    }
}