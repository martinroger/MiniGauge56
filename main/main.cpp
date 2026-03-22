#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"
// Courtesy of https://github.com/ubx/CAN-logger2
#include "logging.h"

lv_display_t *main_display;
bool display_off = false;
static TimerHandle_t sleepDisplayTimer = NULL;

void wakeDisplay()
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

void sleepDisplay()
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

static void sleepDisplayTimer_cb(TimerHandle_t xTimer)
{
    sleepDisplay();
}

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
        // start_logging();
        start_logging_test();
    }
    wakeDisplay();
}

extern "C" void action_global_pressed(lv_event_t *e)
{
    wakeDisplay();
}

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
            lv_label_set_text_fmt(objects.status, "%s", is_logging ? "Logging" : "Paused");
            bsp_display_unlock();
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
}

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
            ESP_LOGI(__func__, "CAN logger ready");
        else
            ESP_LOGE(__func__, "Could not start CAN logger");
    }

    // Display init
    main_display = bsp_display_start();

    if (bsp_display_lock(-1) == ESP_OK)
    {
        // bsp_display_brightness_set(0);
        ui_init();
        bsp_display_unlock();
    }
    else
    {
        ESP_LOGE(__func__, "Could not catch mutex for LVGL, aborting");
        return;
    }
    wakeDisplay();

    // uint8_t brightness = 0;

    xTaskCreate(update_display, "upd_disp", 4096, NULL, 3, NULL);
    while (true)
    {

        vTaskDelay(pdMS_TO_TICKS(1000));
        ESP_LOGI("STATUS", "File: %s | Size: %lu kB | Buffered: %lu B",
                 current_log_filename, current_file_size / 1024, current_buffered_bytes);

        // // Testing brightness control
        // brightness += 1;
        // brightness %= 100;

        // if (bsp_display_lock(-1) == ESP_OK)
        // {
        //     bsp_display_brightness_set(brightness);
        //     bsp_display_unlock();
        // }
    }
}
