#pragma once
#include <stdio.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "esp_log.h"
#include "ff.h"            // Native FatFs
#include "diskio.h"        // For disk status
#include <sys/stat.h>      // For file existence checks

// Logic variables
const uint64_t FOUR_GB = 4ULL * 1024 * 1024 * 1024;
const uint32_t MAX_FILE_SIZE = 512 * 1024 * 1024; // 512MB
FILE* current_file = NULL;
uint32_t current_file_idx = 0;
size_t current_file_size = 0;
bool sd_full_flag = false;

inline void check_and_prepare_storage() {
    FATFS *fs;
    DWORD fre_clust;

    // Use "" to refer to the default/current drive
    FRESULT res = f_getfree("", &fre_clust, &fs);
    
    if (res == FR_OK) {
        // Calculate free space: Free Clusters * Sectors Per Cluster * Sector Size
        // Sector size is almost universally 512 for SD cards
        uint64_t free_bytes = (uint64_t)fre_clust * fs->csize * 512;
        
        ESP_LOGI("SD", "Free space check: %llu GB", free_bytes / (1024 * 1024 * 1024));

        if (free_bytes < FOUR_GB) {
            ESP_LOGW("SD", "Space < 4GB. Triggering Format...");
            // The BSP usually handles the format wrapper
            esp_vfs_fat_sdcard_format(BSP_SD_MOUNT_POINT, NULL);
            ESP_LOGI("SD", "Format complete.");
        }
    } else {
        ESP_LOGE("SD", "Could not get free space. Error: %d", res);
    }
}

inline void open_next_log_file() {
    if (current_file) {
        fclose(current_file);
        current_file = NULL;
    }

    char filename[128];
    struct stat st;

    // Search for a filename that doesn't exist yet
    while (true) {
        snprintf(filename, sizeof(filename), "%s/log_%lu.txt", BSP_SD_MOUNT_POINT, (unsigned long)current_file_idx);
        if (stat(filename, &st) != 0) {
            // stat fails = file doesn't exist. We found our name.
            break;
        }
        current_file_idx++;
    }

    current_file = fopen(filename, "w");
    if (current_file) {
        current_file_size = 0;
        ESP_LOGI("SD", "Now logging to: %s", filename);
    }
}

inline void log_to_sd(const char* data) {
    if (sd_full_flag || !current_file) return;

    size_t len = strlen(data);

    // Check if we need a new file before writing
    if (current_file_size + len > MAX_FILE_SIZE) {
        open_next_log_file();
    }

    // Attempt the write
    size_t written = fwrite(data, 1, len, current_file);
    
    if (written < len) {
        // If written is less than requested, the card is full or error occurred
        ESP_LOGE("SD", "Write failed. Card might be full.");
        sd_full_flag = true;
        fclose(current_file);
        current_file = NULL;
    } else {
        current_file_size += written;
    }
}