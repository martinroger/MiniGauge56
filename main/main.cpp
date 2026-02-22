#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"
#include <dirent.h>
#include <sys/stat.h>
#include <string.h>

lv_display_t *main_display;

static void list_dir(const char *path)
{
    const char *TAG = "SD";
    DIR *dir = opendir(path);
    if (!dir) {
        ESP_LOGW(TAG, "opendir failed: %s", path);
        return;
    }
    struct dirent *ent;
    while ((ent = readdir(dir)) != NULL) {
        if (strcmp(ent->d_name, ".") == 0 || strcmp(ent->d_name, "..") == 0) continue;
        char full[512];
        snprintf(full, sizeof(full), "%s/%s", path, ent->d_name);
        struct stat st;
        if (stat(full, &st) == 0) {
            ESP_LOGI(TAG, "%c %s", (S_ISDIR(st.st_mode) ? 'd' : '-'), full);
        } else {
            ESP_LOGI(TAG, "? %s", full);
        }
    }
    closedir(dir);
}


extern "C" void app_main(void)
{
    if(bsp_sdcard_mount() != ESP_OK)
    {
        ESP_LOGW(__func__,"Could not mount SD CARD");
    }
    else
    {
        ESP_LOGI(__func__, "SD card mounted at %s", BSP_SD_MOUNT_POINT);
        list_dir(BSP_SD_MOUNT_POINT);
    }
    main_display = bsp_display_start();
    bsp_display_brightness_set(100);
    // if(bsp_display_lock(100))
    // {
    //     ESP_LOGI(__func__,"first mutex taken");
        
    //     bsp_display_unlock();
    // }
    bsp_display_lock(-1);
    ui_init();
    bsp_display_unlock();

    uint8_t brightness = 0;
    // bsp_display_brightness_set(10);

    

    while (true)
    {

        vTaskDelay(pdMS_TO_TICKS(100));


        // // Testing brightness control
        // brightness += 1;
        // brightness %= 100;
        
        // if (bsp_display_lock(-1) == ESP_OK)
        // {
        //     bsp_display_brightness_set(brightness);
        //     bsp_display_unlock();
        // }

        
        // bsp_display_brightness_set(brightness);
        // if (bsp_display_lock(1000))
        // {
        //     if (bsp_display_brightness_set(brightness) != ESP_OK)
        //         ESP_LOGE(__func__, "Cannot set brightness");
        //     else
        //         ESP_LOGI(__func__, "Brightness set to %u", brightness);
        //     bsp_display_unlock();
        // }
        // else
        // {
        //     ESP_LOGW(__func__,"mutex not available");
        // }
    }
}
