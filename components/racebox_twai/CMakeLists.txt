idf_component_register(
    SRCS "racebox_twai.c"
    INCLUDE_DIRS "include"
    REQUIRES twai_daemon racebox_ble esp_timer nvs_flash freertos
)
