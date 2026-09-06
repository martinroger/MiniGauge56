# How-To Guide: `racebox_ble` Component

## 1. Overview & Capabilities
The `racebox_ble` component is a modular, standalone ESP-IDF component that handles:
- **Pure C Frame Reassembly & UBX Stream Parser** (`racebox_parser.h/.c`): Zero-allocation finite state machine validating 8-bit Fletcher checksums and reconstructing 25 Hz telemetry frames from arbitrary byte streams.
- **NimBLE Central Client & GATT Manager** (`racebox_ble.h/.c`): Automated BLE 5.0 scanning, name-prefix filtering (`RaceBox *`), target bonding/locking via NVS, MTU exchange (512 bytes), connection interval negotiation (7.5–15 ms), and Nordic UART Service (NUS) subscription.
- **Canonical Telemetry Types** (`racebox_types.h`): Standard engineering units (km/h, degrees, g, deg/s, meters) unpacked from wire bitfields.

---

## 2. Component Dependencies & CMake Setup
`racebox_ble` has **zero dependencies** on CAN, TWAI, or `twai_daemon`. It can be added to any ESP-IDF project (e.g. WiFi data loggers, display clusters, SD card recorders).

### In your project or component `CMakeLists.txt`:
```cmake
idf_component_register(
    SRCS "your_app.c"
    INCLUDE_DIRS "."
    REQUIRES racebox_ble
)
```

### SDKConfig Requirements (`sdkconfig.defaults`):
To enable Apache NimBLE (and disable Bluedroid to save ~100 KB of RAM):
```ini
CONFIG_BT_ENABLED=y
CONFIG_BT_NIMBLE_ENABLED=y
CONFIG_BT_NIMBLE_ROLE_CENTRAL=y
CONFIG_BT_NIMBLE_ROLE_PERIPHERAL=n
CONFIG_BT_NIMBLE_ROLE_BROADCASTER=n
CONFIG_BT_NIMBLE_MAX_CONNECTIONS=1
CONFIG_BT_NIMBLE_ATT_PREFERRED_MTU=512
```

---

## 3. Integration Patterns

### Pattern A: Turnkey BLE Central Ingestion (Most Common)
Scans for any physical RaceBox (Mini, Mini S, Micro), connects, exchanges MTU, subscribes to NUS notifications, and invokes your callback whenever a 25 Hz PVT packet is received.

```c
#include <stdio.h>
#include "esp_log.h"
#include "nvs_flash.h"
#include "racebox_ble.h"

static const char *TAG = "ble_example";

// 1. Invoked whenever a valid 88-byte telemetry frame is unpacked
static void on_telemetry(const racebox_pvt_t *pvt, void *user_data)
{
    ESP_LOGI(TAG, "Speed: %.1f km/h | Lat: %.6f, Lon: %.6f | 3D Fix: %d (SVs: %d) | G(X,Y,Z): [%.2f, %.2f, %.2f]",
             pvt->speed_kmh,
             pvt->latitude_deg,
             pvt->longitude_deg,
             pvt->fix_status,
             pvt->num_sv,
             pvt->g_force_x,
             pvt->g_force_y,
             pvt->g_force_z);
}

// 2. Invoked on BLE connection lifecycle events
static void on_ble_event(racebox_ble_event_t event, const racebox_ble_event_data_t *data, void *user_data)
{
    switch (event) {
    case RACEBOX_BLE_EVT_SCAN_STARTED:
        ESP_LOGI(TAG, "Scanning for RaceBox peripherals...");
        break;
    case RACEBOX_BLE_EVT_DISCOVERED:
        ESP_LOGI(TAG, "Found target: '%s'", data->discovered.device.name);
        break;
    case RACEBOX_BLE_EVT_CONNECTED:
        ESP_LOGI(TAG, "Connected to RaceBox (conn_handle: %d)", data->connected.conn_handle);
        break;
    case RACEBOX_BLE_EVT_SUBSCRIBED:
        ESP_LOGI(TAG, "Subscribed to NUS TX notifications. Streaming live telemetry!");
        break;
    case RACEBOX_BLE_EVT_DISCONNECTED:
        ESP_LOGW(TAG, "Disconnected (reason: %d). Central will auto-reconnect.", data->disconnected.reason);
        break;
    default:
        break;
    }
}

void app_main(void)
{
    // NVS is required for BLE bonding and radio calibration
    ESP_ERROR_CHECK(nvs_flash_init());

    racebox_ble_config_t config = {
        .name_prefix = "RaceBox ",      // Matches RaceBox Mini, Mini S, Micro
        .event_cb    = on_ble_event,    // Lifecycle callback
        .pvt_cb      = on_telemetry,    // Decoded telemetry callback (25 Hz)
        .user_data   = NULL,
    };

    // Initialize BLE Central stack and background task
    ESP_ERROR_CHECK(racebox_ble_init(&config));

    // Start background scanning and auto-connection
    ESP_ERROR_CHECK(racebox_ble_start_scan());
}
```

---

### Pattern B: Pure C Stream Parser Standalone (No BLE / Host Verified)
If you ingest RaceBox UBX binary frames over a different transport (e.g. wired UART, USB serial, SPI, or on a Linux host), you can use `racebox_parser.h` directly without NimBLE:

```c
#include <stdio.h>
#include "racebox_parser.h"

static void on_packet_decoded(const racebox_pvt_t *pvt, void *user_data)
{
    printf("Decoded frame at iTOW %u: Speed = %.2f km/h\n", pvt->itow, pvt->speed_kmh);
}

void process_uart_stream(void)
{
    racebox_parser_t parser;
    racebox_parser_init(&parser, on_packet_decoded, NULL);

    uint8_t incoming_chunk[128];
    // Feed arbitrary chunks as they arrive from UART/SPI:
    while (/* reading bytes */ 1) {
        size_t bytes_read = read_from_transport(incoming_chunk, sizeof(incoming_chunk));
        // Feed into parser FSM: handles fragmentation, concatenation, and CRC automatically
        racebox_parser_feed(&parser, incoming_chunk, bytes_read);
    }
}
```

---

### Pattern C: Single Target Lock via NVS
By default, `racebox_ble` connects to the first discovered peripheral matching `"RaceBox "`. To lock to a specific unit (e.g. fleet management):

```c
// Lock by 10-digit serial number:
racebox_ble_save_target_lock(true, false, "0123456789", NULL);

// Or lock by 6-byte Bluetooth MAC address:
uint8_t target_mac[6] = {0xC0, 0xDE, 0xFA, 0x12, 0x34, 0x56};
racebox_ble_save_target_lock(true, true, NULL, target_mac);
```

