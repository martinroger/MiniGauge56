/**
 * @file racebox_twai.c
 * @brief Implementation of RaceBox CAN telemetry packaging, scheduling, and companion orchestrator.
 */

#include "racebox_twai.h"
#include "racebox_companion.h"
#include "twai_daemon.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include <string.h>

#define TAG "racebox_twai"

#define RACEBOX_TWAI_QUEUE_DEPTH        (8)
#define RACEBOX_TWAI_TASK_STACK_SIZE    (4096)
#define RACEBOX_TWAI_TASK_PRIORITY      (5)

static bool s_twai_initialized = false;

#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
static racebox_twai_stats_t s_twai_stats = {0};
#define RB_TWAI_STAT_INC(field)         do { s_twai_stats.field++; } while (0)
#define RB_TWAI_STAT_SET(field, val)    do { s_twai_stats.field = (val); } while (0)
#else
#define RB_TWAI_STAT_INC(field)         do {} while (0)
#define RB_TWAI_STAT_SET(field, val)    do {} while (0)
#endif

static uint8_t s_rolling_counter = 0;
static uint32_t s_stream_frame_index = 0;

static QueueHandle_t s_pvt_queue = NULL;
static TaskHandle_t  s_twai_task_handle = NULL;

/* Helper to evaluate rate dividers from a 25 Hz stream */
static inline bool should_send(uint32_t frame_idx, int rate_mode)
{
    switch (rate_mode) {
    case 0: return true;                        // 25 Hz (all frames)
    case 1: return (frame_idx % 5 == 0) || (frame_idx % 5 == 2); // 10 Hz (2 out of 5 frames)
    case 2: return (frame_idx % 5 == 0);        // 5 Hz (1 out of 5 frames)
    case 3: return (frame_idx % 25 == 0);       // 1 Hz (1 out of 25 frames)
    default: return false;                      // Disabled
    }
}

static int get_rate_mode_speed_heading(void)
{
#if defined(CONFIG_RACEBOX_CAN_RATE_SPEED_HEADING_10HZ)
    return 1;
#elif defined(CONFIG_RACEBOX_CAN_RATE_SPEED_HEADING_5HZ)
    return 2;
#elif defined(CONFIG_RACEBOX_CAN_RATE_SPEED_HEADING_1HZ)
    return 3;
#elif defined(CONFIG_RACEBOX_CAN_RATE_SPEED_HEADING_OFF)
    return -1;
#else
    return 0; // 25 Hz default
#endif
}

static int get_rate_mode_lat_lon(void)
{
#if defined(CONFIG_RACEBOX_CAN_RATE_LAT_LON_10HZ)
    return 1;
#elif defined(CONFIG_RACEBOX_CAN_RATE_LAT_LON_5HZ)
    return 2;
#elif defined(CONFIG_RACEBOX_CAN_RATE_LAT_LON_1HZ)
    return 3;
#elif defined(CONFIG_RACEBOX_CAN_RATE_LAT_LON_OFF)
    return -1;
#else
    return 0;
#endif
}

static int get_rate_mode_alt_accuracy(void)
{
#if defined(CONFIG_RACEBOX_CAN_RATE_ALT_ACCURACY_10HZ)
    return 1;
#elif defined(CONFIG_RACEBOX_CAN_RATE_ALT_ACCURACY_5HZ)
    return 2;
#elif defined(CONFIG_RACEBOX_CAN_RATE_ALT_ACCURACY_1HZ)
    return 3;
#elif defined(CONFIG_RACEBOX_CAN_RATE_ALT_ACCURACY_OFF)
    return -1;
#else
    return 0;
#endif
}

static int get_rate_mode_imu_accel(void)
{
#if defined(CONFIG_RACEBOX_CAN_RATE_IMU_ACCEL_10HZ)
    return 1;
#elif defined(CONFIG_RACEBOX_CAN_RATE_IMU_ACCEL_5HZ)
    return 2;
#elif defined(CONFIG_RACEBOX_CAN_RATE_IMU_ACCEL_1HZ)
    return 3;
#elif defined(CONFIG_RACEBOX_CAN_RATE_IMU_ACCEL_OFF)
    return -1;
#else
    return 0;
#endif
}

static int get_rate_mode_imu_gyro(void)
{
#if defined(CONFIG_RACEBOX_CAN_RATE_IMU_GYRO_10HZ)
    return 1;
#elif defined(CONFIG_RACEBOX_CAN_RATE_IMU_GYRO_5HZ)
    return 2;
#elif defined(CONFIG_RACEBOX_CAN_RATE_IMU_GYRO_1HZ)
    return 3;
#elif defined(CONFIG_RACEBOX_CAN_RATE_IMU_GYRO_OFF)
    return -1;
#else
    return 0;
#endif
}

static int get_rate_mode_utc_time(void)
{
#if defined(CONFIG_RACEBOX_CAN_RATE_UTC_TIME_10HZ)
    return 1;
#elif defined(CONFIG_RACEBOX_CAN_RATE_UTC_TIME_5HZ)
    return 2;
#elif defined(CONFIG_RACEBOX_CAN_RATE_UTC_TIME_1HZ)
    return 3;
#elif defined(CONFIG_RACEBOX_CAN_RATE_UTC_TIME_OFF)
    return -1;
#else
    return 0;
#endif
}

static void racebox_twai_task(void *pvParameters)
{
    (void)pvParameters;
    ESP_LOGD(TAG, "RaceBox TWAI asynchronous dispatch task started");
    racebox_pvt_t pvt;

    while (1) {
        if (xQueueReceive(s_pvt_queue, &pvt, portMAX_DELAY) == pdTRUE) {
#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
            s_twai_stats.queue_depth_current = (uint32_t)uxQueueMessagesWaiting(s_pvt_queue);
#endif
            racebox_twai_broadcast_pvt(&pvt);
        }
    }
}

TaskHandle_t racebox_twai_get_task_handle(void)
{
    return s_twai_task_handle;
}

esp_err_t racebox_twai_enqueue_pvt(const racebox_pvt_t *pvt)
{
    if (!s_twai_initialized || !pvt || !s_pvt_queue) {
        return ESP_ERR_INVALID_STATE;
    }

#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
    UBaseType_t waiting = uxQueueMessagesWaiting(s_pvt_queue);
    s_twai_stats.queue_depth_current = (uint32_t)waiting;
    if (waiting > s_twai_stats.queue_depth_peak) {
        s_twai_stats.queue_depth_peak = (uint32_t)waiting;
    }
#endif

    // Non-blocking handoff: drops frames safely if CAN queue is backlogged
    if (xQueueSend(s_pvt_queue, pvt, 0) != pdTRUE) {
        RB_TWAI_STAT_INC(tx_queue_dropped);
        return ESP_ERR_TIMEOUT;
    }

#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
    waiting = uxQueueMessagesWaiting(s_pvt_queue);
    s_twai_stats.queue_depth_current = (uint32_t)waiting;
    if (waiting > s_twai_stats.queue_depth_peak) {
        s_twai_stats.queue_depth_peak = (uint32_t)waiting;
    }
#endif

    return ESP_OK;
}

esp_err_t racebox_twai_init(void)
{
    if (s_twai_initialized) {
        return ESP_OK;
    }

    ESP_LOGI(TAG, "Initializing TWAI driver for RaceBox telemetry (Base ID: 0x%03lX)...",
             (unsigned long)CONFIG_RACEBOX_CAN_BASE_ID);

    esp_err_t err = initCAN(NULL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "initCAN failed: %s", esp_err_to_name(err));
        return err;
    }

    if (s_pvt_queue == NULL) {
        s_pvt_queue = xQueueCreate(RACEBOX_TWAI_QUEUE_DEPTH, sizeof(racebox_pvt_t));
        if (s_pvt_queue == NULL) {
            ESP_LOGE(TAG, "Failed to create TWAI PVT queue");
            return ESP_ERR_NO_MEM;
        }
    }

    if (s_twai_task_handle == NULL) {
        BaseType_t t_res = xTaskCreate(racebox_twai_task,
                                       "rb_twai_task",
                                       RACEBOX_TWAI_TASK_STACK_SIZE,
                                       NULL,
                                       RACEBOX_TWAI_TASK_PRIORITY,
                                       &s_twai_task_handle);
        if (t_res != pdPASS) {
            ESP_LOGE(TAG, "Failed to create TWAI dispatch task");
            return ESP_FAIL;
        }
    }

#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
    memset(&s_twai_stats, 0, sizeof(s_twai_stats));
#endif
    s_rolling_counter = 0;
    s_stream_frame_index = 0;
    s_twai_initialized = true;

    ESP_LOGD(TAG, "RaceBox TWAI subsystem initialized successfully (Queue Depth: %d)",
             RACEBOX_TWAI_QUEUE_DEPTH);
    return ESP_OK;
}

esp_err_t racebox_twai_deinit(void)
{
    if (s_twai_task_handle != NULL) {
        vTaskDelete(s_twai_task_handle);
        s_twai_task_handle = NULL;
    }
    if (s_pvt_queue != NULL) {
        vQueueDelete(s_pvt_queue);
        s_pvt_queue = NULL;
    }
    s_twai_initialized = false;
    return ESP_OK;
}

esp_err_t racebox_twai_broadcast_pvt(const racebox_pvt_t *pvt)
{
    if (!s_twai_initialized || !pvt) {
        return ESP_ERR_INVALID_STATE;
    }

    if (g_twai_bus_off) {
#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
        s_twai_stats.bus_off = true;
#endif
        RB_TWAI_STAT_INC(tx_failed);
        return ESP_ERR_INVALID_STATE;
    }
#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
    s_twai_stats.bus_off = false;
#endif

    uint32_t idx = s_stream_frame_index++;
    s_rolling_counter++;

    // 1. RB_SPEED_HEADING (0x600)
    if (should_send(idx, get_rate_mode_speed_heading())) {
        racebox_can_speed_heading_t msg;
        racebox_can_pack_speed_heading(pvt, &msg);
        esp_err_t err = twai_transmit_msg(RACEBOX_CAN_ID_SPEED_HEADING, (const uint8_t *)&msg, sizeof(msg), false, 0);
        if (err == ESP_OK) {
            RB_TWAI_STAT_INC(frames_sent_total);
            RB_TWAI_STAT_INC(frames_speed_heading);
        } else {
            RB_TWAI_STAT_INC(tx_failed);
        }
    }

    // 2. RB_LAT_LON (0x601)
    if (should_send(idx, get_rate_mode_lat_lon())) {
        racebox_can_lat_lon_t msg;
        racebox_can_pack_lat_lon(pvt, &msg);
        esp_err_t err = twai_transmit_msg(RACEBOX_CAN_ID_LAT_LON, (const uint8_t *)&msg, sizeof(msg), false, 0);
        if (err == ESP_OK) {
            RB_TWAI_STAT_INC(frames_sent_total);
            RB_TWAI_STAT_INC(frames_lat_lon);
        } else {
            RB_TWAI_STAT_INC(tx_failed);
        }
    }

    // 3. RB_ALT_ACCURACY (0x602)
    if (should_send(idx, get_rate_mode_alt_accuracy())) {
        racebox_can_alt_accuracy_t msg;
        racebox_can_pack_alt_accuracy(pvt, &msg);
        esp_err_t err = twai_transmit_msg(RACEBOX_CAN_ID_ALT_ACCURACY, (const uint8_t *)&msg, sizeof(msg), false, 0);
        if (err == ESP_OK) {
            RB_TWAI_STAT_INC(frames_sent_total);
            RB_TWAI_STAT_INC(frames_alt_acc);
        } else {
            RB_TWAI_STAT_INC(tx_failed);
        }
    }

    // 4. RB_IMU_ACCEL (0x603)
    if (should_send(idx, get_rate_mode_imu_accel())) {
        racebox_can_imu_accel_t msg;
        racebox_can_pack_imu_accel(pvt, s_rolling_counter, &msg);
        esp_err_t err = twai_transmit_msg(RACEBOX_CAN_ID_IMU_ACCEL, (const uint8_t *)&msg, sizeof(msg), false, 0);
        if (err == ESP_OK) {
            RB_TWAI_STAT_INC(frames_sent_total);
            RB_TWAI_STAT_INC(frames_imu_accel);
        } else {
            RB_TWAI_STAT_INC(tx_failed);
        }
    }

    // 5. RB_IMU_GYRO (0x604)
    if (should_send(idx, get_rate_mode_imu_gyro())) {
        racebox_can_imu_gyro_t msg;
        racebox_can_pack_imu_gyro(pvt, &msg);
        esp_err_t err = twai_transmit_msg(RACEBOX_CAN_ID_IMU_GYRO, (const uint8_t *)&msg, sizeof(msg), false, 0);
        if (err == ESP_OK) {
            RB_TWAI_STAT_INC(frames_sent_total);
            RB_TWAI_STAT_INC(frames_imu_gyro);
        } else {
            RB_TWAI_STAT_INC(tx_failed);
        }
    }

    // 6. RB_UTC_TIME (0x605)
    if (should_send(idx, get_rate_mode_utc_time())) {
        racebox_can_utc_time_t msg;
        racebox_can_pack_utc_time(pvt, &msg);
        esp_err_t err = twai_transmit_msg(RACEBOX_CAN_ID_UTC_TIME, (const uint8_t *)&msg, sizeof(msg), false, 0);
        if (err == ESP_OK) {
            RB_TWAI_STAT_INC(frames_sent_total);
            RB_TWAI_STAT_INC(frames_utc_time);
        } else {
            RB_TWAI_STAT_INC(tx_failed);
        }
    }

    return ESP_OK;
}

#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
static int64_t  s_last_stats_calc_us = 0;
static uint32_t s_last_frames_sent = 0;
#endif

esp_err_t racebox_twai_get_stats(racebox_twai_stats_t *stats)
{
    if (!stats) return ESP_ERR_INVALID_ARG;

#if CONFIG_RACEBOX_TWAI_STATS_ENABLE
    int64_t now_us = esp_timer_get_time();
    if (s_last_stats_calc_us > 0 && now_us > s_last_stats_calc_us) {
        float dt_sec = (float)(now_us - s_last_stats_calc_us) / 1000000.0f;
        uint32_t delta_frames = s_twai_stats.frames_sent_total - s_last_frames_sent;
        s_twai_stats.can_tx_fps = (float)delta_frames / dt_sec;
        // Standard 11-bit CAN frame @ 500 kbps: avg 120 bits (with bit stuffing)
        // Bus load % = (can_tx_fps * 120 / 500000) * 100% = can_tx_fps * 0.024%
        s_twai_stats.bus_utilization_pct = s_twai_stats.can_tx_fps * 0.024f;
        s_last_stats_calc_us = now_us;
        s_last_frames_sent = s_twai_stats.frames_sent_total;
    } else if (s_last_stats_calc_us == 0) {
        s_last_stats_calc_us = now_us;
        s_last_frames_sent = s_twai_stats.frames_sent_total;
    }

    if (s_pvt_queue) {
        s_twai_stats.queue_depth_current = (uint32_t)uxQueueMessagesWaiting(s_pvt_queue);
    }

    *stats = s_twai_stats;
    stats->bus_off = g_twai_bus_off;
    return ESP_OK;
#else
    memset(stats, 0, sizeof(*stats));
    stats->bus_off = g_twai_bus_off;
    return ESP_ERR_NOT_SUPPORTED;
#endif
}

bool racebox_twai_is_bus_off(void)
{
    return g_twai_bus_off;
}

/* -------------------------------------------------------------------------
 * Turnkey RaceBox Companion Orchestrator Implementation
 * ------------------------------------------------------------------------- */

static bool s_companion_initialized = false;
static racebox_companion_config_t s_companion_config = {
    .name_prefix = "RaceBox ",
    .auto_can_forward = true,
    .pvt_cb = NULL,
    .ble_evt_cb = NULL,
    .user_data = NULL
};

static void on_internal_pvt(const racebox_pvt_t *pvt, void *user_data)
{
    (void)user_data;
    if (!pvt) return;

    // Automatic asynchronous CAN forwarding via FreeRTOS queue
    if (s_companion_config.auto_can_forward) {
        racebox_twai_enqueue_pvt(pvt);
    }

    // User callback if registered
    if (s_companion_config.pvt_cb) {
        s_companion_config.pvt_cb(pvt, s_companion_config.user_data);
    }
}

static void on_internal_ble_event(racebox_ble_event_t event, const racebox_ble_event_data_t *data, void *user_data)
{
    (void)user_data;
    if (s_companion_config.ble_evt_cb) {
        s_companion_config.ble_evt_cb(event, data, s_companion_config.user_data);
    }
}

esp_err_t racebox_companion_init(const racebox_companion_config_t *config)
{
    if (s_companion_initialized) {
        ESP_LOGD(TAG, "RaceBox Companion orchestrator already initialized");
        return ESP_OK;
    }

    if (config) {
        s_companion_config = *config;
    } else {
        s_companion_config.name_prefix = "RaceBox ";
        s_companion_config.auto_can_forward = true;
        s_companion_config.pvt_cb = NULL;
        s_companion_config.ble_evt_cb = NULL;
        s_companion_config.user_data = NULL;
    }

    ESP_LOGI(TAG, "==============================================");
    ESP_LOGI(TAG, " Initializing RaceBox Companion Subsystems");
    ESP_LOGI(TAG, "==============================================");

    // 1. Initialize NVS flash (guarded against duplicate init)
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "NVS flash initialization failed: %s", esp_err_to_name(ret));
        return ret;
    }

    // 2. Initialize TWAI CAN driver
    ret = racebox_twai_init();
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "TWAI initialization failed: %s", esp_err_to_name(ret));
        return ret;
    }

    // 3. Initialize BLE Central Manager
    racebox_ble_config_t ble_cfg = {
        .name_prefix = s_companion_config.name_prefix,
        .event_cb = on_internal_ble_event,
        .pvt_cb = on_internal_pvt,
        .user_data = NULL,
    };
    ret = racebox_ble_init(&ble_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "BLE initialization failed: %s", esp_err_to_name(ret));
        return ret;
    }

    s_companion_initialized = true;
    ESP_LOGI(TAG, "RaceBox Companion orchestrator initialized successfully");
    return ESP_OK;
}

esp_err_t racebox_companion_start(void)
{
    if (!s_companion_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    return racebox_ble_start_scan();
}

esp_err_t racebox_companion_stop(void)
{
    if (!s_companion_initialized) {
        return ESP_ERR_INVALID_STATE;
    }
    racebox_ble_stop_scan();
    return racebox_ble_disconnect();
}

esp_err_t racebox_companion_get_stats(racebox_companion_stats_t *stats)
{
    if (!stats) return ESP_ERR_INVALID_ARG;
    memset(stats, 0, sizeof(*stats));

    racebox_ble_get_parser_stats(&stats->ble_parser);
    racebox_twai_get_stats(&stats->twai_stats);
    stats->negotiated_mtu = racebox_ble_get_negotiated_mtu();
    stats->ble_state = racebox_ble_get_state();
    stats->free_heap_bytes = esp_get_free_heap_size();
    stats->min_free_heap_bytes = esp_get_minimum_free_heap_size();
    if (s_twai_task_handle != NULL) {
        stats->twai_task_stack_min_words = (uint32_t)uxTaskGetStackHighWaterMark(s_twai_task_handle);
    }

    return ESP_OK;
}
