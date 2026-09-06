#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"
#include "logging.h"
#include "twai_daemon.h"

/**
 * @file main.cpp
 * @brief Application entry point and UI/hardware coordination for MiniGauge56.
 *
 * Coordinates AMOLED display management, touch events, SD card mounting,
 * modern TWAI CAN daemon lifecycle, and real-time telemetry display updates.
 */

/** @brief Global LVGL display object pointer */
lv_display_t *main_display = NULL;

/** @brief Flag indicating whether the AMOLED display backlight is asleep/off */
bool display_off = false;

/** @brief Software timer handle for display inactivity sleep timeout */
static TimerHandle_t sleepDisplayTimer = NULL;

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

