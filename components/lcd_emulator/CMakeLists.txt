idf_component_register(
    SRCS "src/lcd_emulator.c"
    INCLUDE_DIRS "include"
    REQUIRES lvgl esp_timer log
)

target_compile_definitions(${COMPONENT_TARGET}
    PRIVATE "-DLV_LVGL_H_INCLUDE_SIMPLE"
)
