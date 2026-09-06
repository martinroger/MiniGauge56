/**
 * @file racebox_ble.c
 * @brief NimBLE Central GAP client and connection manager implementation.
 */

#include "racebox_ble.h"
#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "nvs_flash.h"
#include "nvs.h"

#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/ble_gap.h"
#include "host/ble_gatt.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"

#define TAG "racebox_ble"
#define NVS_NAMESPACE "rb_ble"

// Fallback configuration defaults if not present in sdkconfig
#ifndef CONFIG_RACEBOX_BLE_TARGET_NAME_PREFIX
#define CONFIG_RACEBOX_BLE_TARGET_NAME_PREFIX "RaceBox "
#endif

#ifndef CONFIG_RACEBOX_BLE_PREFERRED_MTU
#define CONFIG_RACEBOX_BLE_PREFERRED_MTU (512)
#endif

#ifndef CONFIG_RACEBOX_BLE_CONN_ITVL_MIN
#define CONFIG_RACEBOX_BLE_CONN_ITVL_MIN (6) // 7.5 ms
#endif

#ifndef CONFIG_RACEBOX_BLE_CONN_ITVL_MAX
#define CONFIG_RACEBOX_BLE_CONN_ITVL_MAX (12) // 15 ms
#endif

static racebox_ble_config_t s_config = {
    .name_prefix = CONFIG_RACEBOX_BLE_TARGET_NAME_PREFIX,
    .event_cb = NULL,
    .pvt_cb = NULL,
    .user_data = NULL
};

static racebox_target_lock_t s_target_lock = {0};
static racebox_ble_state_t  s_state = RACEBOX_BLE_STATE_UNINITIALIZED;
static uint8_t              s_own_addr_type = 0;
static uint16_t             s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static uint16_t             s_negotiated_mtu = 23;
static racebox_parser_t     s_parser;
static racebox_ble_device_t s_connected_peer;

// Nordic UART Service (NUS) base UUID: 6E400001-B5A3-F393-E0A9-E50E24DCCA9E
static const ble_uuid128_t s_nus_svc_uuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x01, 0x00, 0x40, 0x6e
);

// NUS TX Characteristic (Notify from RaceBox): 6E400003-B5A3-F393-E0A9-E50E24DCCA9E
static const ble_uuid128_t s_nus_tx_uuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x03, 0x00, 0x40, 0x6e
);

// NUS RX Characteristic (Write to RaceBox): 6E400002-B5A3-F393-E0A9-E50E24DCCA9E
static const ble_uuid128_t s_nus_rx_uuid = BLE_UUID128_INIT(
    0x9e, 0xca, 0xdc, 0x24, 0x0e, 0xe5, 0xa9, 0xe0,
    0x93, 0xf3, 0xa3, 0xb5, 0x02, 0x00, 0x40, 0x6e
);

// Device Information Service (DIS) and Firmware Revision UUIDs
#define BLE_GATT_SVC_DEV_INFO_UUID16        0x180A
#define BLE_GATT_CHR_FIRMWARE_REV_UUID16    0x2A26

static uint16_t s_dis_svc_start_handle = 0;
static uint16_t s_dis_svc_end_handle = 0;
static uint16_t s_dis_firmware_val_handle = 0;

static uint16_t s_nus_svc_start_handle = 0;
static uint16_t s_nus_svc_end_handle = 0;
static uint16_t s_nus_tx_def_handle = 0;
static uint16_t s_nus_tx_val_handle = 0;
static uint16_t s_nus_tx_cccd_handle = 0;
static uint16_t s_nus_rx_def_handle = 0;
static uint16_t s_nus_rx_val_handle = 0;

static int gap_event_cb(struct ble_gap_event *event, void *arg);
static void start_gatt_discovery(void);
static void discover_nus_chrs(uint16_t conn_handle);
static int on_disc_svc(uint16_t conn_handle, const struct ble_gatt_error *error,
                       const struct ble_gatt_svc *service, void *arg);
static int on_disc_dis_chr(uint16_t conn_handle, const struct ble_gatt_error *error,
                           const struct ble_gatt_chr *chr, void *arg);
static int on_read_firmware(uint16_t conn_handle, const struct ble_gatt_error *error,
                            struct ble_gatt_attr *attr, void *arg);
static int on_disc_chr(uint16_t conn_handle, const struct ble_gatt_error *error,
                       const struct ble_gatt_chr *chr, void *arg);
static int on_disc_dsc(uint16_t conn_handle, const struct ble_gatt_error *error,
                       uint16_t chr_val_handle, const struct ble_gatt_dsc *dsc, void *arg);
static int on_cccd_written(uint16_t conn_handle, const struct ble_gatt_error *error,
                           struct ble_gatt_attr *attr, void *arg);
static int on_mtu_exchange_complete(uint16_t conn_handle, const struct ble_gatt_error *error,
                                    uint16_t mtu, void *arg);

static void notify_event(racebox_ble_event_t event_type, const racebox_ble_event_data_t *data)
{
    if (s_config.event_cb) {
        s_config.event_cb(event_type, data, s_config.user_data);
    }
}

static bool __attribute__((unused)) parse_mac_string(const char *str, uint8_t *mac)
{
    if (!str || !mac) return false;
    unsigned int bytes[6];
    if (sscanf(str, "%02x:%02x:%02x:%02x:%02x:%02x",
               &bytes[0], &bytes[1], &bytes[2], &bytes[3], &bytes[4], &bytes[5]) == 6) {
        for (int i = 0; i < 6; i++) {
            mac[i] = (uint8_t)bytes[i];
        }
        return true;
    }
    return false;
}

esp_err_t racebox_ble_load_target_lock(racebox_target_lock_t *lock)
{
    if (!lock) return ESP_ERR_INVALID_ARG;

    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READONLY, &handle);
    if (err == ESP_OK) {
        uint8_t en = 0, use_mac = 0;
        nvs_get_u8(handle, "lock_en", &en);
        nvs_get_u8(handle, "use_mac", &use_mac);
        lock->enabled = (en != 0);
        lock->use_mac = (use_mac != 0);

        size_t slen = sizeof(lock->serial);
        nvs_get_str(handle, "serial", lock->serial, &slen);

        size_t mlen = sizeof(lock->mac);
        nvs_get_blob(handle, "mac", lock->mac, &mlen);

        nvs_close(handle);
        ESP_LOGI(TAG, "Loaded target lock from NVS: enabled=%d, use_mac=%d, serial='%s'",
                 lock->enabled, lock->use_mac, lock->serial);
        return ESP_OK;
    }

    // Default configuration from Kconfig
    memset(lock, 0, sizeof(*lock));
#ifdef CONFIG_RACEBOX_BLE_SINGLE_TARGET_MODE
    lock->enabled = true;
#ifdef CONFIG_RACEBOX_BLE_LOCK_BY_MAC
    lock->use_mac = true;
    parse_mac_string(CONFIG_RACEBOX_BLE_LOCKED_MAC, lock->mac);
    ESP_LOGI(TAG, "Using Kconfig target MAC: %s", CONFIG_RACEBOX_BLE_LOCKED_MAC);
#else
    lock->use_mac = false;
    strncpy(lock->serial, CONFIG_RACEBOX_BLE_LOCKED_SERIAL, sizeof(lock->serial) - 1);
    ESP_LOGI(TAG, "Using Kconfig target Serial: %s", CONFIG_RACEBOX_BLE_LOCKED_SERIAL);
#endif
#else
    lock->enabled = false;
    ESP_LOGD(TAG, "Single target lock mode is disabled (promiscuous prefix matching active)");
#endif

    return ESP_OK;
}

esp_err_t racebox_ble_save_target_lock(bool enabled,
                                      bool use_mac,
                                      const char *serial,
                                      const uint8_t *mac)
{
    nvs_handle_t handle;
    esp_err_t err = nvs_open(NVS_NAMESPACE, NVS_READWRITE, &handle);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to open NVS namespace %s: %s", NVS_NAMESPACE, esp_err_to_name(err));
        return err;
    }

    nvs_set_u8(handle, "lock_en", enabled ? 1 : 0);
    nvs_set_u8(handle, "use_mac", use_mac ? 1 : 0);
    if (serial) {
        nvs_set_str(handle, "serial", serial);
    }
    if (mac) {
        nvs_set_blob(handle, "mac", mac, RACEBOX_BLE_MAC_LEN);
    }

    err = nvs_commit(handle);
    nvs_close(handle);

    // Update in-memory lock struct
    s_target_lock.enabled = enabled;
    s_target_lock.use_mac = use_mac;
    if (serial) {
        strncpy(s_target_lock.serial, serial, sizeof(s_target_lock.serial) - 1);
    }
    if (mac) {
        memcpy(s_target_lock.mac, mac, RACEBOX_BLE_MAC_LEN);
    }

    ESP_LOGI(TAG, "Saved target lock to NVS: enabled=%d, use_mac=%d", enabled, use_mac);
    return err;
}

static bool is_target_match(const char *dev_name, const ble_addr_t *addr)
{
    if (s_target_lock.enabled) {
        if (s_target_lock.use_mac) {
            if (memcmp(addr->val, s_target_lock.mac, RACEBOX_BLE_MAC_LEN) == 0) {
                ESP_LOGI(TAG, "Target match by MAC: %02x:%02x:%02x:%02x:%02x:%02x",
                         addr->val[5], addr->val[4], addr->val[3],
                         addr->val[2], addr->val[1], addr->val[0]);
                return true;
            }
            return false;
        } else {
            if (dev_name && strstr(dev_name, s_target_lock.serial) != NULL) {
                ESP_LOGI(TAG, "Target match by Serial '%s' in name '%s'",
                         s_target_lock.serial, dev_name);
                return true;
            }
            return false;
        }
    }

    // Promiscuous prefix match mode
    const char *prefix = s_config.name_prefix ? s_config.name_prefix : CONFIG_RACEBOX_BLE_TARGET_NAME_PREFIX;
    if (dev_name && strncmp(dev_name, prefix, strlen(prefix)) == 0) {
        ESP_LOGI(TAG, "Target match by prefix '%s' (Device: '%s')", prefix, dev_name);
        return true;
    }

    return false;
}

static void start_gatt_discovery(void)
{
    if (s_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
        return;
    }

    if (s_state == RACEBOX_BLE_STATE_DISCOVERING || s_state == RACEBOX_BLE_STATE_SUBSCRIBED) {
        return;
    }

    s_state = RACEBOX_BLE_STATE_DISCOVERING;
    s_dis_svc_start_handle = 0;
    s_dis_svc_end_handle = 0;
    s_dis_firmware_val_handle = 0;
    s_nus_svc_start_handle = 0;
    s_nus_svc_end_handle = 0;
    s_nus_tx_def_handle = 0;
    s_nus_tx_val_handle = 0;
    s_nus_tx_cccd_handle = 0;
    s_nus_rx_def_handle = 0;
    s_nus_rx_val_handle = 0;

    ESP_LOGD(TAG, "Starting GATT service discovery (conn_handle = %d)...", s_conn_handle);
    int rc = ble_gattc_disc_all_svcs(s_conn_handle, on_disc_svc, NULL);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gattc_disc_all_svcs failed: rc = %d", rc);
        s_state = RACEBOX_BLE_STATE_CONNECTED;
    }
}

static void discover_nus_chrs(uint16_t conn_handle)
{
    if (s_nus_svc_start_handle != 0) {
        ESP_LOGD(TAG, "Discovering characteristics for Nordic UART Service [%d..%d]...",
                 s_nus_svc_start_handle, s_nus_svc_end_handle);
        int rc = ble_gattc_disc_all_chrs(conn_handle,
                                         s_nus_svc_start_handle,
                                         s_nus_svc_end_handle,
                                         on_disc_chr, NULL);
        if (rc != 0) {
            ESP_LOGE(TAG, "ble_gattc_disc_all_chrs failed: rc = %d", rc);
        }
    } else {
        ESP_LOGE(TAG, "Nordic UART Service (NUS) not found on peer device!");
    }
}

static int on_read_firmware(uint16_t conn_handle,
                            const struct ble_gatt_error *error,
                            struct ble_gatt_attr *attr,
                            void *arg)
{
    (void)arg;
    if (error->status == 0 && attr && attr->om) {
        char fw_str[64] = {0};
        uint16_t len = OS_MBUF_PKTLEN(attr->om);
        if (len >= sizeof(fw_str)) len = sizeof(fw_str) - 1;
        ble_hs_mbuf_to_flat(attr->om, fw_str, len, NULL);
        fw_str[len] = '\0';
        ESP_LOGI(TAG, "============================================================");
        ESP_LOGI(TAG, ">>> RaceBox Firmware Revision (UUID: 0x2A26): '%s'", fw_str);
        ESP_LOGI(TAG, "============================================================");
    } else {
        ESP_LOGW(TAG, "Failed to read Firmware Revision characteristic: status = %d", error->status);
    }

    discover_nus_chrs(conn_handle);
    return 0;
}

static int on_disc_dis_chr(uint16_t conn_handle,
                           const struct ble_gatt_error *error,
                           const struct ble_gatt_chr *chr,
                           void *arg)
{
    (void)arg;

    if (error->status == 0) {
        if (chr->uuid.u.type == BLE_UUID_TYPE_16 &&
            chr->uuid.u16.value == BLE_GATT_CHR_FIRMWARE_REV_UUID16) {
            s_dis_firmware_val_handle = chr->val_handle;
            ESP_LOGD(TAG, "Found Firmware Revision Characteristic (UUID 0x2A26): def_handle=%d, val_handle=%d",
                     chr->def_handle, chr->val_handle);
        }
        return 0;
    }

    if (error->status == BLE_HS_EDONE) {
        if (s_dis_firmware_val_handle != 0) {
            ESP_LOGD(TAG, "Reading Firmware Revision (handle=%d)...", s_dis_firmware_val_handle);
            int rc = ble_gattc_read(conn_handle, s_dis_firmware_val_handle, on_read_firmware, NULL);
            if (rc != 0) {
                ESP_LOGE(TAG, "ble_gattc_read for Firmware Revision failed: rc = %d", rc);
                discover_nus_chrs(conn_handle);
            }
        } else {
            ESP_LOGW(TAG, "Firmware Revision characteristic (0x2A26) not found in DIS");
            discover_nus_chrs(conn_handle);
        }
        return 0;
    }

    ESP_LOGE(TAG, "DIS characteristic discovery error: status = %d", error->status);
    discover_nus_chrs(conn_handle);
    return 0;
}

static int on_disc_svc(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       const struct ble_gatt_svc *service,
                       void *arg)
{
    (void)arg;

    if (error->status == 0) {
        if (ble_uuid_cmp(&service->uuid.u, &s_nus_svc_uuid.u) == 0) {
            ESP_LOGI(TAG, "Discovered Nordic UART Service: handles [%d..%d]",
                     service->start_handle, service->end_handle);
            s_nus_svc_start_handle = service->start_handle;
            s_nus_svc_end_handle = service->end_handle;
        } else if (service->uuid.u.type == BLE_UUID_TYPE_16 &&
                   service->uuid.u16.value == BLE_GATT_SVC_DEV_INFO_UUID16) {
            ESP_LOGI(TAG, "Discovered Device Information Service (DIS 0x180A): handles [%d..%d]",
                     service->start_handle, service->end_handle);
            s_dis_svc_start_handle = service->start_handle;
            s_dis_svc_end_handle = service->end_handle;
        }
        return 0;
    }

    if (error->status == BLE_HS_EDONE) {
        if (s_dis_svc_start_handle != 0) {
            ESP_LOGI(TAG, "Discovering characteristics in Device Information Service [%d..%d]...",
                     s_dis_svc_start_handle, s_dis_svc_end_handle);
            int rc = ble_gattc_disc_all_chrs(conn_handle,
                                             s_dis_svc_start_handle,
                                             s_dis_svc_end_handle,
                                             on_disc_dis_chr, NULL);
            if (rc != 0) {
                ESP_LOGE(TAG, "ble_gattc_disc_all_chrs for DIS failed: rc = %d", rc);
                discover_nus_chrs(conn_handle);
            }
        } else {
            discover_nus_chrs(conn_handle);
        }
        return 0;
    }

    ESP_LOGE(TAG, "GATT service discovery error: status = %d", error->status);
    return 0;
}

static int on_disc_chr(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       const struct ble_gatt_chr *chr,
                       void *arg)
{
    (void)arg;

    if (error->status == 0) {
        if (ble_uuid_cmp(&chr->uuid.u, &s_nus_tx_uuid.u) == 0) {
            s_nus_tx_def_handle = chr->def_handle;
            s_nus_tx_val_handle = chr->val_handle;
            ESP_LOGI(TAG, "Found NUS TX Characteristic (Notify): def_handle=%d, val_handle=%d, props=0x%02x",
                     chr->def_handle, chr->val_handle, chr->properties);
        } else if (ble_uuid_cmp(&chr->uuid.u, &s_nus_rx_uuid.u) == 0) {
            s_nus_rx_def_handle = chr->def_handle;
            s_nus_rx_val_handle = chr->val_handle;
            ESP_LOGI(TAG, "Found NUS RX Characteristic (Write): def_handle=%d, val_handle=%d, props=0x%02x",
                     chr->def_handle, chr->val_handle, chr->properties);
        }
        return 0;
    }

    if (error->status == BLE_HS_EDONE) {
        if (s_nus_tx_val_handle != 0) {
            uint16_t dsc_end_handle = s_nus_svc_end_handle;
            if (s_nus_rx_def_handle > s_nus_tx_def_handle) {
                dsc_end_handle = s_nus_rx_def_handle - 1;
            }
            ESP_LOGI(TAG, "Characteristics discovery complete. Discovering descriptors for NUS TX [%d..%d]...",
                     s_nus_tx_val_handle, dsc_end_handle);

            int rc = ble_gattc_disc_all_dscs(conn_handle,
                                             s_nus_tx_val_handle,
                                             dsc_end_handle,
                                             on_disc_dsc, NULL);
            if (rc != 0) {
                ESP_LOGE(TAG, "ble_gattc_disc_all_dscs failed: rc = %d", rc);
            }
        } else {
            ESP_LOGE(TAG, "NUS TX characteristic not found!");
        }
        return 0;
    }

    ESP_LOGE(TAG, "GATT characteristic discovery error: status = %d", error->status);
    return 0;
}

static int on_disc_dsc(uint16_t conn_handle,
                       const struct ble_gatt_error *error,
                       uint16_t chr_val_handle,
                       const struct ble_gatt_dsc *dsc,
                       void *arg)
{
    (void)arg;
    (void)chr_val_handle;

    if (error->status == 0) {
        if (ble_uuid_cmp(&dsc->uuid.u, BLE_UUID16_DECLARE(BLE_GATT_DSC_CLT_CFG_UUID16)) == 0) {
            s_nus_tx_cccd_handle = dsc->handle;
            ESP_LOGI(TAG, "Found NUS TX CCCD descriptor: handle = %d", dsc->handle);
        }
        return 0;
    }

    if (error->status == BLE_HS_EDONE) {
        if (s_nus_tx_cccd_handle != 0) {
            ESP_LOGI(TAG, "Enabling notifications on NUS TX CCCD (handle = %d)...", s_nus_tx_cccd_handle);
            static const uint8_t notify_enable[2] = {0x01, 0x00};
            int rc = ble_gattc_write_flat(conn_handle,
                                          s_nus_tx_cccd_handle,
                                          notify_enable,
                                          sizeof(notify_enable),
                                          on_cccd_written,
                                          NULL);
            if (rc != 0) {
                ESP_LOGE(TAG, "ble_gattc_write_flat failed: rc = %d", rc);
            }
        } else {
            ESP_LOGE(TAG, "CCCD descriptor (0x2902) not found for NUS TX!");
        }
        return 0;
    }

    ESP_LOGE(TAG, "GATT descriptor discovery error: status = %d", error->status);
    return 0;
}

static int on_cccd_written(uint16_t conn_handle,
                           const struct ble_gatt_error *error,
                           struct ble_gatt_attr *attr,
                           void *arg)
{
    (void)arg;
    (void)attr;

    if (error->status == 0) {
        s_state = RACEBOX_BLE_STATE_SUBSCRIBED;
        ESP_LOGD(TAG, ">>> Successfully subscribed to RaceBox NUS TX notifications! Telemetry stream active.");

        racebox_ble_event_data_t evt_data = {0};
        evt_data.subscribed.conn_handle = conn_handle;
        notify_event(RACEBOX_BLE_EVT_SUBSCRIBED, &evt_data);
    } else {
        ESP_LOGE(TAG, "Failed to write CCCD: status = %d, att_handle = %d",
                 error->status, error->att_handle);
    }
    return 0;
}

static int on_mtu_exchange_complete(uint16_t conn_handle,
                                    const struct ble_gatt_error *error,
                                    uint16_t mtu,
                                    void *arg)
{
    (void)arg;
    if (error->status == 0) {
        ESP_LOGD(TAG, "MTU exchange complete: conn_handle = %d, MTU = %d bytes", conn_handle, mtu);
        s_negotiated_mtu = mtu;
    } else {
        ESP_LOGW(TAG, "MTU exchange procedure completed with status = %d", error->status);
    }

    start_gatt_discovery();
    return 0;
}

static int gap_event_cb(struct ble_gap_event *event, void *arg)
{
    (void)arg;
    struct ble_gap_conn_desc desc;
    int rc;

    switch (event->type) {
    case BLE_GAP_EVENT_DISC: {
        struct ble_hs_adv_fields fields;
        rc = ble_hs_adv_parse_fields(&fields, event->disc.data, event->disc.length_data);
        if (rc != 0) {
            return 0;
        }

        char dev_name[RACEBOX_BLE_MAX_NAME_LEN] = {0};
        if (fields.name != NULL && fields.name_len > 0) {
            size_t copy_len = fields.name_len < (sizeof(dev_name) - 1) ? fields.name_len : (sizeof(dev_name) - 1);
            memcpy(dev_name, fields.name, copy_len);
            dev_name[copy_len] = '\0';
        }

        if (is_target_match(dev_name, &event->disc.addr)) {
            ESP_LOGI(TAG, "Connecting to target RaceBox device: '%s' [%02x:%02x:%02x:%02x:%02x:%02x] (RSSI: %d dBm)",
                     dev_name,
                     event->disc.addr.val[5], event->disc.addr.val[4], event->disc.addr.val[3],
                     event->disc.addr.val[2], event->disc.addr.val[1], event->disc.addr.val[0],
                     event->disc.rssi);

            ble_gap_disc_cancel();
            s_state = RACEBOX_BLE_STATE_CONNECTING;

            racebox_ble_event_data_t evt_data = {0};
            strncpy(evt_data.discovered.device.name, dev_name, sizeof(evt_data.discovered.device.name) - 1);
            memcpy(evt_data.discovered.device.addr, event->disc.addr.val, RACEBOX_BLE_MAC_LEN);
            evt_data.discovered.device.addr_type = event->disc.addr.type;
            evt_data.discovered.device.rssi = event->disc.rssi;
            notify_event(RACEBOX_BLE_EVT_DISCOVERED, &evt_data);

            // Fast connection parameters
            struct ble_gap_conn_params conn_params = {
                .scan_itvl = 16,
                .scan_window = 16,
                .itvl_min = CONFIG_RACEBOX_BLE_CONN_ITVL_MIN,
                .itvl_max = CONFIG_RACEBOX_BLE_CONN_ITVL_MAX,
                .latency = 0,
                .supervision_timeout = 500, // 500 * 10 ms = 5000 ms
                .min_ce_len = 0,
                .max_ce_len = 0,
            };

            rc = ble_gap_connect(s_own_addr_type, &event->disc.addr, 30000,
                                 &conn_params, gap_event_cb, NULL);
            if (rc != 0) {
                ESP_LOGE(TAG, "ble_gap_connect failed: rc = %d", rc);
                racebox_ble_start_scan();
            }
        }
        return 0;
    }

    case BLE_GAP_EVENT_CONNECT: {
        if (event->connect.status == 0) {
            s_conn_handle = event->connect.conn_handle;
            s_state = RACEBOX_BLE_STATE_CONNECTED;

            rc = ble_gap_conn_find(event->connect.conn_handle, &desc);
            if (rc == 0) {
                memcpy(s_connected_peer.addr, desc.peer_id_addr.val, RACEBOX_BLE_MAC_LEN);
                s_connected_peer.addr_type = desc.peer_id_addr.type;
            }

            ESP_LOGI(TAG, "BLE connection established (conn_handle = %d)", s_conn_handle);

            // Initiate MTU exchange if not already negotiated
            if (s_negotiated_mtu <= 23) {
                rc = ble_gattc_exchange_mtu(s_conn_handle, on_mtu_exchange_complete, NULL);
                if (rc == BLE_HS_EALREADY) {
                    start_gatt_discovery();
                } else if (rc != 0) {
                    ESP_LOGW(TAG, "Failed to initiate MTU exchange (rc = %d), proceeding to GATT discovery directly", rc);
                    start_gatt_discovery();
                }
            } else {
                start_gatt_discovery();
            }

            // Request connection parameter update
            struct ble_gap_upd_params upd_params = {
                .itvl_min = CONFIG_RACEBOX_BLE_CONN_ITVL_MIN,
                .itvl_max = CONFIG_RACEBOX_BLE_CONN_ITVL_MAX,
                .latency = 0,
                .supervision_timeout = 500,
                .min_ce_len = 0,
                .max_ce_len = 0,
            };
            rc = ble_gap_update_params(s_conn_handle, &upd_params);
            if (rc != 0) {
                ESP_LOGW(TAG, "Failed to request connection param update: rc = %d", rc);
            }

            racebox_ble_event_data_t evt_data = {0};
            evt_data.connected.conn_handle = s_conn_handle;
            evt_data.connected.device = s_connected_peer;
            notify_event(RACEBOX_BLE_EVT_CONNECTED, &evt_data);

        } else {
            ESP_LOGE(TAG, "Connection attempt failed: status = %d", event->connect.status);
            s_state = RACEBOX_BLE_STATE_DISCONNECTED;
            racebox_ble_start_scan();
        }
        return 0;
    }

    case BLE_GAP_EVENT_DISCONNECT: {
        ESP_LOGI(TAG, "Disconnected from peripheral (reason = %d)", event->disconnect.reason);
        uint16_t old_handle = s_conn_handle;
        s_conn_handle = BLE_HS_CONN_HANDLE_NONE;
        s_state = RACEBOX_BLE_STATE_DISCONNECTED;
        s_negotiated_mtu = 23;

        s_dis_svc_start_handle = 0;
        s_dis_svc_end_handle = 0;
        s_dis_firmware_val_handle = 0;
        s_nus_svc_start_handle = 0;
        s_nus_svc_end_handle = 0;
        s_nus_tx_def_handle = 0;
        s_nus_tx_val_handle = 0;
        s_nus_tx_cccd_handle = 0;
        s_nus_rx_def_handle = 0;
        s_nus_rx_val_handle = 0;

        racebox_parser_reset(&s_parser);

        racebox_ble_event_data_t evt_data = {0};
        evt_data.disconnected.conn_handle = old_handle;
        evt_data.disconnected.reason = event->disconnect.reason;
        notify_event(RACEBOX_BLE_EVT_DISCONNECTED, &evt_data);

        // Automatic seamless reconnect
        racebox_ble_start_scan();
        return 0;
    }

    case BLE_GAP_EVENT_MTU: {
        s_negotiated_mtu = event->mtu.value;
        ESP_LOGI(TAG, "GATT MTU updated: conn_handle = %d, MTU = %d bytes",
                 event->mtu.conn_handle, s_negotiated_mtu);

        racebox_ble_event_data_t evt_data = {0};
        evt_data.mtu_updated.conn_handle = event->mtu.conn_handle;
        evt_data.mtu_updated.mtu = event->mtu.value;
        notify_event(RACEBOX_BLE_EVT_MTU_UPDATED, &evt_data);

        start_gatt_discovery();
        return 0;
    }

    case BLE_GAP_EVENT_CONN_UPDATE_REQ: {
        ESP_LOGI(TAG, "Peer requested conn params: itvl_min=%d (%.2f ms), itvl_max=%d (%.2f ms)",
                 event->conn_update_req.peer_params->itvl_min,
                 event->conn_update_req.peer_params->itvl_min * 1.25f,
                 event->conn_update_req.peer_params->itvl_max,
                 event->conn_update_req.peer_params->itvl_max * 1.25f);

        // Clamp connection interval to keep low latency for telemetry
        event->conn_update_req.self_params->itvl_min = CONFIG_RACEBOX_BLE_CONN_ITVL_MIN;
        if (event->conn_update_req.peer_params->itvl_max > CONFIG_RACEBOX_BLE_CONN_ITVL_MAX) {
            event->conn_update_req.self_params->itvl_max = CONFIG_RACEBOX_BLE_CONN_ITVL_MAX;
        } else {
            event->conn_update_req.self_params->itvl_max = event->conn_update_req.peer_params->itvl_max;
        }
        event->conn_update_req.self_params->latency = 0;
        event->conn_update_req.self_params->supervision_timeout = event->conn_update_req.peer_params->supervision_timeout;
        return 0;
    }

    case BLE_GAP_EVENT_CONN_UPDATE: {
        if (event->conn_update.status == 0) {
            rc = ble_gap_conn_find(event->conn_update.conn_handle, &desc);
            if (rc == 0) {
                ESP_LOGI(TAG, "Connection parameters updated: interval = %.2f ms, latency = %d, timeout = %d ms",
                         desc.conn_itvl * 1.25f, desc.conn_latency, desc.supervision_timeout * 10);

                racebox_ble_event_data_t evt_data = {0};
                evt_data.conn_updated.conn_handle = event->conn_update.conn_handle;
                evt_data.conn_updated.conn_itvl = desc.conn_itvl;
                evt_data.conn_updated.conn_latency = desc.conn_latency;
                evt_data.conn_updated.supervision_timeout = desc.supervision_timeout;
                notify_event(RACEBOX_BLE_EVT_CONN_UPDATED, &evt_data);
            }
        } else {
            ESP_LOGW(TAG, "Connection update failed: status = %d", event->conn_update.status);
        }
        return 0;
    }

    case BLE_GAP_EVENT_NOTIFY_RX: {
        // Feed received notification bytes to the stream parser
        if (s_nus_tx_val_handle == 0 || event->notify_rx.attr_handle == s_nus_tx_val_handle) {
            uint16_t om_len = OS_MBUF_PKTLEN(event->notify_rx.om);
            if (om_len > 0) {
                static uint8_t s_rx_buf[RACEBOX_MAX_PACKET_SIZE];
                uint16_t copy_len = om_len < sizeof(s_rx_buf) ? om_len : sizeof(s_rx_buf);
                os_mbuf_copydata(event->notify_rx.om, 0, copy_len, s_rx_buf);
                racebox_parser_feed(&s_parser, s_rx_buf, copy_len);
            }
        }
        return 0;
    }

    default:
        break;
    }

    return 0;
}

static void on_sync(void)
{
    int rc = ble_hs_id_infer_auto(0, &s_own_addr_type);
    if (rc != 0) {
        ESP_LOGE(TAG, "Failed to determine local own address type: rc = %d", rc);
        return;
    }

    ESP_LOGD(TAG, "NimBLE host synced, starting discovery scan...");
    racebox_ble_start_scan();
}

static void on_reset(int reason)
{
    ESP_LOGW(TAG, "NimBLE host reset: reason = %d", reason);
}

static void nimble_host_task(void *param)
{
    (void)param;
    ESP_LOGD(TAG, "NimBLE Host Task running");
    nimble_port_run();
    nimble_port_freertos_deinit();
}

static bool s_ble_initialized = false;

esp_err_t racebox_ble_init(const racebox_ble_config_t *config)
{
    if (s_ble_initialized) {
        ESP_LOGW(TAG, "racebox_ble already initialized, skipping");
        return ESP_OK;
    }

    if (config) {
        s_config = *config;
    }

    // Load target lock settings from NVS
    racebox_ble_load_target_lock(&s_target_lock);

    // Initialize telemetry parser
    racebox_parser_init(&s_parser, s_config.pvt_cb, s_config.user_data);

    // Initialize NimBLE port
    esp_err_t err = nimble_port_init();
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "nimble_port_init failed: %s", esp_err_to_name(err));
        return err;
    }

    // Set GAP device name
    ble_svc_gap_device_name_set("RaceBoxCompanion");

    // Set preferred GATT MTU
    ble_att_set_preferred_mtu(CONFIG_RACEBOX_BLE_PREFERRED_MTU);

    // Configure host stack
    ble_hs_cfg.reset_cb = on_reset;
    ble_hs_cfg.sync_cb = on_sync;
    ble_hs_cfg.store_status_cb = ble_store_util_status_rr;

    // Start NimBLE FreeRTOS task
    nimble_port_freertos_init(nimble_host_task);

    s_state = RACEBOX_BLE_STATE_DISCONNECTED;
    s_ble_initialized = true;
    return ESP_OK;
}

esp_err_t racebox_ble_start_scan(void)
{
    if (s_state == RACEBOX_BLE_STATE_SCANNING || s_state == RACEBOX_BLE_STATE_CONNECTED) {
        return ESP_OK;
    }

    struct ble_gap_disc_params disc_params = {
        .passive = 1,
        .itvl = 16,     // 16 * 0.625 ms = 10 ms
        .window = 16,   // 16 * 0.625 ms = 10 ms (100% duty cycle for fast discovery)
        .filter_policy = 0,
        .limited = 0,
        .filter_duplicates = 1,
    };

    int rc = ble_gap_disc(s_own_addr_type, BLE_HS_FOREVER, &disc_params, gap_event_cb, NULL);
    if (rc != 0 && rc != BLE_HS_EALREADY) {
        ESP_LOGE(TAG, "ble_gap_disc failed: rc = %d", rc);
        return ESP_FAIL;
    }

    s_state = RACEBOX_BLE_STATE_SCANNING;
    ESP_LOGI(TAG, "GAP discovery scan started (looking for '%s' devices)...",
             s_config.name_prefix ? s_config.name_prefix : "RaceBox ");

    notify_event(RACEBOX_BLE_EVT_SCAN_STARTED, NULL);
    return ESP_OK;
}

esp_err_t racebox_ble_stop_scan(void)
{
    if (s_state != RACEBOX_BLE_STATE_SCANNING) {
        return ESP_OK;
    }

    int rc = ble_gap_disc_cancel();
    if (rc != 0) {
        ESP_LOGW(TAG, "ble_gap_disc_cancel: rc = %d", rc);
        return ESP_FAIL;
    }

    s_state = RACEBOX_BLE_STATE_DISCONNECTED;
    notify_event(RACEBOX_BLE_EVT_SCAN_STOPPED, NULL);
    return ESP_OK;
}

esp_err_t racebox_ble_disconnect(void)
{
    if (s_conn_handle == BLE_HS_CONN_HANDLE_NONE) {
        return ESP_ERR_INVALID_STATE;
    }

    int rc = ble_gap_terminate(s_conn_handle, BLE_ERR_REM_USER_CONN_TERM);
    if (rc != 0) {
        ESP_LOGE(TAG, "ble_gap_terminate failed: rc = %d", rc);
        return ESP_FAIL;
    }

    return ESP_OK;
}

racebox_ble_state_t racebox_ble_get_state(void)
{
    return s_state;
}

uint16_t racebox_ble_get_negotiated_mtu(void)
{
    return s_negotiated_mtu;
}

esp_err_t racebox_ble_get_parser_stats(racebox_parser_stats_t *stats)
{
    if (!stats) {
        return ESP_ERR_INVALID_ARG;
    }
    *stats = s_parser.stats;
    return ESP_OK;
}
