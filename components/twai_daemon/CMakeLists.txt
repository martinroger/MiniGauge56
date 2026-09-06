set(SRCS_DIR "src")

file(GLOB_RECURSE CPP_SRCS "${SRCS_DIR}/*.cpp")
file(GLOB_RECURSE C_SRCS "${SRCS_DIR}/*.c")


idf_component_register(
    SRCS ${C_SRCS} ${CPP_SRCS}
    INCLUDE_DIRS ${SRCS_DIR}
    REQUIRES esp_driver_twai esp_driver_gpio driver esp_timer
)

target_compile_options(${COMPONENT_LIB} PRIVATE -Wno-missing-field-initializers)

