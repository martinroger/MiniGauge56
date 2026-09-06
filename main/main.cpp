#include <stdio.h>
#include <time.h>
#include <sys/time.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"
#include "logging.h"
#include "twai_daemon.h"
#include "racebox_companion.h"

/**
 * @file main.cpp
 * @brief Application entry point and UI/hardware coordination for MiniGauge56.
 *
 * Coordinates AMOLED display management, touch events, SD card mounting,
 * modern TWAI CAN daemon lifecycle, RaceBox BLE Central connection,
 * GPS 3D fix system time synchronization, and real-time telemetry display updates.
 */

/** @brief Global LVGL display object pointer */
lv_display_t *main_display = NULL;

/** @brief Flag indicating whether the AMOLED display backlight is asleep/off */
bool display_off = false;

/** @brief Software timer handle for display inactivity sleep timeout */
static TimerHandle_t sleepDisplayTimer = NULL;

/**
 * @brief Converts UTC calendar time fields to Unix epoch seconds.
 *
 * @param[in] tm Pointer to struct tm with year, month, day, hour, min, sec.
 * @return time_t Seconds elapsed since Unix epoch (1970-01-01 00:00:00 UTC).
 */
static time_t utc_tm_to_epoch(const struct tm *tm)
{
    int year = tm->tm_year + 1900;
    int mon = tm->tm_mon + 1;
    int day = tm->tm_mday;

    int a = (14 - mon) / 12;
    int y = year + 4800 - a;
    int m = mon + 12 * a - 3;
    long jdn = day + (153 * m + 2) / 5 + 365L * y + y / 4 - y / 100 + y / 400 - 32045;
    long days = jdn - 2440588L; // JDN of 1970-01-01

    return (time_t)(days * 86400L + tm->tm_hour * 3600L + tm->tm_min * 60L + tm->tm_sec);
}

/**
 * @brief Callback invoked whenever a 25 Hz RaceBox PVT telemetry frame is decoded.
 *
 * Upon receiving the first valid 3D GPS fix, updates the ESP32 internal POSIX RTC
 * system clock via settimeofday() so that SD file creation dates and log filenames
 * reflect the accurate UTC time.
 *
 * @param[in] pvt Pointer to canonical decoded RaceBox PVT telemetry struct.
 * @param[in] user_data User context pointer passed during callback registration (unused).
 * @note Thread-safety: Called from the NimBLE client task context.
 */
static void on_racebox_telemetry(const racebox_pvt_t *pvt, void *user_data)
{
    (void)user_data;
    if (pvt == NULL)
    {
        return;
    }

    // Synchronize system clock upon acquiring the first valid 3D GPS fix
    if (!is_gps_time_synced && pvt->valid_date && pvt->valid_time && pvt->valid_fix &&
        pvt->fix_status >= RACEBOX_FIX_3D && pvt->num_sv >= 4)
    {
        struct tm tm_utc = {};
        tm_utc.tm_sec = pvt->second;
        tm_utc.tm_min = pvt->minute;
        tm_utc.tm_hour = pvt->hour;
        tm_utc.tm_mday = pvt->day;
        tm_utc.tm_mon = pvt->month - 1;
        tm_utc.tm_year = pvt->year - 1900;
        tm_utc.tm_isdst = 0;

        time_t epoch_sec = utc_tm_to_epoch(&tm_utc);
        if (epoch_sec > 1700000000)
        {
            struct timeval tv = {
                .tv_sec = epoch_sec,
                .tv_usec = (suseconds_t)(pvt->nanoseconds > 0 ? pvt->nanoseconds / 1000 : 0)
            };
            settimeofday(&tv, NULL);
            logging_set_gps_synced(true);
            ESP_LOGI("GPS_SYNC", "System time synchronized with RaceBox 3D fix: %04d-%02d-%02d %02d:%02d:%02d UTC (SVs: %d)",
                     pvt->year, pvt->month, pvt->day, pvt->hour, pvt->minute, pvt->second, pvt->num_sv);
        }
    }
}

/**
 * @brief Callback invoked on RaceBox BLE connection lifecycle events.
 *
 * @param[in] event Lifecycle event type (e.g. scan started, discovered, connected, disconnected).
 * @param[in] data Event payload containing connection or discovery metadata.
 * @param[in] user_data User context pointer (unused).
 */
static void on_racebox_ble_event(racebox_ble_event_t event, const racebox_ble_event_data_t *data, void *user_data)
{
    (void)user_data;
    switch (event)
    {
    case RACEBOX_BLE_EVT_SCAN_STARTED:
        ESP_LOGI("RaceBox_BLE", "Scanning for RaceBox peripherals...");
        break;
    case RACEBOX_BLE_EVT_DISCOVERED:
        ESP_LOGI("RaceBox_BLE", "Discovered: '%s'", data ? data->discovered.device.name : "");
        break;
    case RACEBOX_BLE_EVT_CONNECTED:
        ESP_LOGI("RaceBox_BLE", "Connected to RaceBox (conn_handle: %d)", data ? data->connected.conn_handle : 0);
        break;
    case RACEBOX_BLE_EVT_SUBSCRIBED:
        ESP_LOGI("RaceBox_BLE", "Subscribed to NUS notifications — streaming telemetry and broadcasting to CAN");
        break;
    case RACEBOX_BLE_EVT_DISCONNECTED:
        ESP_LOGW("RaceBox_BLE", "Disconnected (reason: %d). Central will auto-reconnect.", data ? data->disconnected.reason : 0);
        break;
    default:
        break;
    }
}

/**
 * @brief Top-level CAN frame router registered with twai_daemon.
 *
 * Dispatches incoming frames from the TWAI RX worker task to all registered consumers
 * (such as CAN SD logging and future gauge/display decoders).
 *
 * @param[in] rx_frame Pointer to received TWAI frame descriptor.
 * @return esp_err_t ESP_OK on successful dispatch handling.
 * @note Thread-safety: Executed in the context of twai_daemon's CAN_RX_Task (Core 1).
 */
static esp_err_t app_can_frame_router(const twai_frame_t *rx_frame)
{
    log_can_frame_handler(rx_frame);
    // Future gauge decoders (RPM, speed, sensors) hook in here
    return ESP_OK;
}

/**
 * @brief Wakes up the display backlight and resets the inactivity timer.
 *
 * @note Thread-safety: Thread-safe; acquires BSP display lock with 100 ms timeout.
 * @note Side effects: Powers on display backlight and resets sleepDisplayTimer.
 */
void wakeDisplay(void)
{
    if (display_off)
    {
        if (bsp_display_lock(100) == ESP_OK)
        {
            bsp_display_backlight_on();
            display_off = false;
            bsp_display_unlock();
        }
    }
    xTimerReset(sleepDisplayTimer, pdMS_TO_TICKS(100));
}

/**
 * @brief Puts the display backlight to sleep to conserve power.
 *
 * @note Thread-safety: Thread-safe; acquires BSP display lock with 100 ms timeout.
 * @note Side effects: Turns off display backlight and marks display_off true.
 */
void sleepDisplay(void)
{
    if (!display_off)
    {
        if (bsp_display_lock(100) == ESP_OK)
        {
            bsp_display_backlight_off();
            display_off = true;
            bsp_display_unlock();
        }
    }
}

/**
 * @brief FreeRTOS software timer callback triggered upon display inactivity timeout.
 *
 * @param[in] xTimer Handle of the expired FreeRTOS software timer.
 */
static void sleepDisplayTimer_cb(TimerHandle_t xTimer)
{
    sleepDisplay();
}

/**
 * @brief LVGL event callback triggered when the start/stop logging button is clicked.
 *
 * @param[in] e Pointer to LVGL event descriptor.
 * @note Thread-safety: Must be called from the LVGL task context.
 */
extern "C" void action_start_stop_clicked(lv_event_t *e)
{
    if (display_off)
    {
        wakeDisplay();
        return;
    }

    if (is_logging)
    {
        stop_logging();
    }
    else
    {
        start_logging();
        // start_logging_test();
    }
    wakeDisplay();
}

/**
 * @brief Global touch press event callback to wake display upon any user interaction.
 *
 * @param[in] e Pointer to LVGL event descriptor.
 */
extern "C" void action_global_pressed(lv_event_t *e)
{
    wakeDisplay();
}

/**
 * @brief FreeRTOS UI update task that refreshes LVGL telemetry labels periodically.
 *
 * @param[in] pvParameters Task parameters passed by FreeRTOS (unused).
 * @note Thread-safety: Locks LVGL display mutex before modifying UI widgets.
 */
void update_display(void *pvParameters)
{
    while (1)
    {
        if (bsp_display_lock(100) == ESP_OK)
        {
            lv_label_set_text_fmt(objects.filename, "%s", current_log_filename);
            lv_label_set_text_fmt(objects.filesize, "%lu kB", current_file_size / 1024);
            lv_label_set_text_fmt(objects.buffered_size, "%lu B", current_buffered_bytes);
            lv_label_set_text_fmt(objects.start_stop_lbl, "%s", is_logging ? "STOP" : "START");
            lv_obj_set_state(objects.start_stop_btn, LV_STATE_CHECKED, is_logging);
            lv_label_set_text_fmt(objects.status, "%s", is_logging ? "Logging" : "Paused");
            bsp_display_unlock();
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

/**
 * @brief Application main entry point.
 *
 * Initializes display power management timer, mounts SD card, allocates PSRAM
 * logging buffers, initializes the modern twai_daemon controller, and launches UI.
 */
extern "C" void app_main(void)
{
    sleepDisplayTimer = xTimerCreate("slp_disp", pdMS_TO_TICKS(10000), pdFALSE, NULL, sleepDisplayTimer_cb);

    if (bsp_sdcard_mount() != ESP_OK)
    {
        ESP_LOGW(__func__, "Could not mount SD CARD");
    }
    else
    {
        ESP_LOGI(__func__, "SD card mounted at %s", BSP_SD_MOUNT_POINT);
        if (init_can_logging())
        {
            ESP_LOGI(__func__, "CAN logger ringbuffer ready");
        }
        else
        {
            ESP_LOGE(__func__, "Could not allocate CAN logger ringbuffer");
        }
    }

    // Initialize modern TWAI driver and route frames through app_can_frame_router
    if (initCAN(app_can_frame_router) == ESP_OK)
    {
        ESP_LOGI(__func__, "TWAI modern driver initialized successfully");
    }
    else
    {
        ESP_LOGE(__func__, "Failed to initialize TWAI modern driver");
    }

    // Initialize RaceBox Companion (BLE Central scanner & auto CAN broadcaster)
    racebox_companion_config_t companion_cfg = {
        .name_prefix = "RaceBox ",
        .auto_can_forward = true,
        .pvt_cb = on_racebox_telemetry,
        .ble_evt_cb = on_racebox_ble_event,
        .user_data = NULL
    };

    if (racebox_companion_init(&companion_cfg) == ESP_OK)
    {
        ESP_LOGI(__func__, "RaceBox Companion initialized successfully");
        if (racebox_companion_start() == ESP_OK)
        {
            ESP_LOGI(__func__, "RaceBox BLE scanning started");
        }
        else
        {
            ESP_LOGE(__func__, "Failed to start RaceBox BLE scanning");
        }
    }
    else
    {
        ESP_LOGE(__func__, "Failed to initialize RaceBox Companion");
    }

    // Display init
    main_display = bsp_display_start();

    if (bsp_display_lock(-1) == ESP_OK)
    {
        ui_init();
        bsp_display_unlock();
    }
    else
    {
        ESP_LOGE(__func__, "Could not catch mutex for LVGL, aborting");
        return;
    }
    wakeDisplay();

    xTaskCreate(update_display, "upd_disp", 4096, NULL, 3, NULL);
    while (true)
    {
        vTaskDelay(pdMS_TO_TICKS(1000));
        ESP_LOGI("STATUS", "File: %s | Size: %lu kB | Buffered: %lu B",
                 current_log_filename, current_file_size / 1024, current_buffered_bytes);
    }
}

