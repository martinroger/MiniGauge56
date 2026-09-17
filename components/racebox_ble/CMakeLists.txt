idf_component_register(SRCS "racebox_parser.c"
                            "racebox_ble.c"
                       INCLUDE_DIRS "include"
                       REQUIRES bt nvs_flash log esp_timer freertos)
