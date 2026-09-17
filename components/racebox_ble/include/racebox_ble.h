/**
 * @file racebox_ble.h
 * @brief NimBLE Central GAP client and connection manager for RaceBox receivers.
 *
 * Provides active BLE scanning with name-prefix filtering, single-target bonding / lock
 * storage in NVS, connection establishment, MTU exchange, and parameter negotiation.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include "esp_err.h"
#include "racebox_types.h"
#include "racebox_parser.h"

#ifdef __cplusplus
extern "C" {
#endif

/** @brief Maximum length of device name buffer */
#define RACEBOX_BLE_MAX_NAME_LEN        (32)

/** @brief Bluetooth device address length in bytes */
#define RACEBOX_BLE_MAC_LEN             (6)

/**
 * @brief Connection and GAP manager lifecycle states.
 */
typedef enum {
    RACEBOX_BLE_STATE_UNINITIALIZED = 0,    /**< BLE stack not initialized */
    RACEBOX_BLE_STATE_DISCONNECTED,         /**< Initialized, idle, disconnected */
    RACEBOX_BLE_STATE_SCANNING,             /**< Actively scanning for RaceBox peripherals */
    RACEBOX_BLE_STATE_CONNECTING,           /**< Connection establishment in progress */
    RACEBOX_BLE_STATE_CONNECTED,            /**< Connected to RaceBox peripheral */
    RACEBOX_BLE_STATE_DISCOVERING,          /**< Discovering GATT NUS service and characteristics */
    RACEBOX_BLE_STATE_SUBSCRIBED            /**< Subscribed to NUS TX notifications, streaming active */
} racebox_ble_state_t;

/**
 * @brief GAP and GATT client event notifications.
 */
typedef enum {
    RACEBOX_BLE_EVT_SCAN_STARTED = 0,       /**< GAP discovery scanning started */
    RACEBOX_BLE_EVT_SCAN_STOPPED,           /**< GAP discovery scanning halted */
    RACEBOX_BLE_EVT_DISCOVERED,             /**< Matching RaceBox advertisement detected */
    RACEBOX_BLE_EVT_CONNECTED,              /**< Link established with peripheral */
    RACEBOX_BLE_EVT_DISCONNECTED,           /**< Link terminated */
    RACEBOX_BLE_EVT_MTU_UPDATED,            /**< GATT MTU exchange completed */
    RACEBOX_BLE_EVT_CONN_UPDATED,           /**< Connection timing parameters updated */
    RACEBOX_BLE_EVT_SUBSCRIBED              /**< Subscribed to RaceBox NUS TX notifications */
} racebox_ble_event_t;

/**
 * @brief Metadata describing a discovered or connected RaceBox peripheral.
 */
typedef struct {
    char    name[RACEBOX_BLE_MAX_NAME_LEN]; /**< Advertised device name (e.g. "RaceBox Mini 1234567890") */
    uint8_t addr[RACEBOX_BLE_MAC_LEN];      /**< Bluetooth MAC address */
    uint8_t addr_type;                      /**< Address type (0 = Public, 1 = Random) */
    int8_t  rssi;                           /**< Received Signal Strength Indicator in dBm */
} racebox_ble_device_t;

/**
 * @brief Payload associated with racebox_ble_event_t notifications.
 */
typedef union {
    struct {
        racebox_ble_device_t device;        /**< Discovered candidate peripheral */
    } discovered;

    struct {
        uint16_t             conn_handle;   /**< Active NimBLE connection handle */
        racebox_ble_device_t device;        /**< Connected peripheral metadata */
    } connected;

    struct {
        uint16_t conn_handle;               /**< Terminated connection handle */
        int      reason;                    /**< HCI disconnect reason code */
    } disconnected;

    struct {
        uint16_t conn_handle;               /**< Connection handle */
        uint16_t mtu;                       /**< Negotiated GATT MTU in bytes */
    } mtu_updated;

    struct {
        uint16_t conn_handle;               /**< Connection handle */
        uint16_t conn_itvl;                 /**< Connection interval (in 1.25 ms units) */
        uint16_t conn_latency;              /**< Connection latency (in connection events) */
        uint16_t supervision_timeout;       /**< Supervision timeout (in 10 ms units) */
    } conn_updated;

    struct {
        uint16_t conn_handle;               /**< Subscribed connection handle */
    } subscribed;
} racebox_ble_event_data_t;

/**
 * @brief Event callback invoked when GAP or connection lifecycle events occur.
 *
 * @param[in] event Event type identifier.
 * @param[in] data Event specific payload (NULL for events without payload).
 * @param[in] user_data Context pointer registered during initialization.
 */
typedef void (*racebox_ble_event_cb_t)(racebox_ble_event_t event,
                                       const racebox_ble_event_data_t *data,
                                       void *user_data);

/**
 * @brief Configuration parameters for racebox_ble initialization.
 */
typedef struct {
    const char             *name_prefix;    /**< Advertised name prefix to filter on (Default: "RaceBox ") */
    racebox_ble_event_cb_t event_cb;       /**< Optional GAP event callback (Default: NULL) */
    racebox_pvt_callback_t pvt_cb;         /**< Telemetry frame decoded callback (Default: NULL) */
    void                   *user_data;      /**< Context pointer passed to callbacks (Default: NULL) */
} racebox_ble_config_t;

/**
 * @brief Target lock configuration stored in NVS.
 */
typedef struct {
    bool    enabled;                        /**< True if single target mode is active */
    bool    use_mac;                        /**< True if locked by MAC address, false if locked by Serial Number */
    char    serial[16];                     /**< Target 10-digit serial number string */
    uint8_t mac[RACEBOX_BLE_MAC_LEN];       /**< Target 6-byte Bluetooth MAC address */
} racebox_target_lock_t;

/**
 * @brief Initialize the NimBLE host stack and configure the RaceBox Central manager.
 *
 * Initializes NVS namespace, loads target lock settings, registers GAP event callbacks,
 * and starts the FreeRTOS host task.
 *
 * @param[in] config Pointer to initialization configuration (Default values used if NULL).
 * @return ESP_OK on success, or an error code on failure.
 */
esp_err_t racebox_ble_init(const racebox_ble_config_t *config);

/**
 * @brief Begin scanning for matching RaceBox advertising devices.
 *
 * If single target mode is enabled, only connects to the configured target device.
 * If in promiscuous mode, connects to the first discovered device with matching name prefix.
 *
 * @return ESP_OK on success, or ESP_ERR_INVALID_STATE if already scanning/connected.
 */
esp_err_t racebox_ble_start_scan(void);

/**
 * @brief Stop active GAP discovery scanning.
 *
 * @return ESP_OK on success, or ESP_FAIL if stopping failed.
 */
esp_err_t racebox_ble_stop_scan(void);

/**
 * @brief Terminate an active connection with the RaceBox receiver.
 *
 * @return ESP_OK on success, or ESP_ERR_INVALID_STATE if not connected.
 */
esp_err_t racebox_ble_disconnect(void);

/**
 * @brief Query the current GAP connection state.
 *
 * @return Current racebox_ble_state_t value.
 */
racebox_ble_state_t racebox_ble_get_state(void);

/**
 * @brief Query the active negotiated GATT MTU.
 *
 * @return Negotiated MTU in bytes (defaults to 23 before negotiation).
 */
uint16_t racebox_ble_get_negotiated_mtu(void);

/**
 * @brief Save target lock parameters to non-volatile storage (NVS).
 *
 * @param[in] enabled Set to true to activate single target lock mode.
 * @param[in] use_mac Set to true to lock by MAC address, false to lock by serial number.
 * @param[in] serial Null-terminated serial number string (used if use_mac is false).
 * @param[in] mac 6-byte Bluetooth MAC address array (used if use_mac is true).
 * @return ESP_OK on success, or NVS error code.
 */
esp_err_t racebox_ble_save_target_lock(bool enabled,
                                      bool use_mac,
                                      const char *serial,
                                      const uint8_t *mac);

/**
 * @brief Load target lock parameters from non-volatile storage (NVS).
 *
 * If no parameters are saved in NVS, defaults from Kconfig are loaded.
 *
 * @param[out] lock Pointer to caller-allocated target lock structure.
 * @return ESP_OK on success, or ESP_ERR_INVALID_ARG if lock is NULL.
 */
esp_err_t racebox_ble_load_target_lock(racebox_target_lock_t *lock);

/**
 * @brief Retrieve current stream parser diagnostic statistics.
 *
 * Provides diagnostic counters for frames received, checksum errors, dropped frames,
 * and ingested byte throughput.
 *
 * @param[out] stats Pointer to caller-allocated racebox_parser_stats_t struct.
 * @return ESP_OK on success, or ESP_ERR_INVALID_ARG if stats is NULL.
 */
esp_err_t racebox_ble_get_parser_stats(racebox_parser_stats_t *stats);

#ifdef __cplusplus
}
#endif
