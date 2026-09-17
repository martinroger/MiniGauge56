/**
 * @file racebox_types.h
 * @brief Canonical types, wire format definitions, and protocol constants for RaceBox BLE telemetry.
 *
 * This header defines both the packed on-the-wire memory structures matching the
 * RaceBox UBX binary protocol (Class 0xFF, ID 0x01) and canonical unpacked representations
 * with converted engineering units (km/h, degrees, g, deg/s).
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** @brief RaceBox UBX packet preamble byte 1 */
#define RACEBOX_PREAMBLE_SYNC1          (0xB5)

/** @brief RaceBox UBX packet preamble byte 2 */
#define RACEBOX_PREAMBLE_SYNC2          (0x62)

/** @brief RaceBox message class for proprietary telemetry */
#define RACEBOX_MSG_CLASS_DATA          (0xFF)

/** @brief RaceBox message ID for periodic NAV-PVT + IMU telemetry */
#define RACEBOX_MSG_ID_PVT              (0x01)

/** @brief Exact expected payload size in bytes for Class 0xFF ID 0x01 */
#define RACEBOX_PVT_PAYLOAD_SIZE        (80)

/** @brief Total wire packet size in bytes for Class 0xFF ID 0x01 (Header + Payload + Checksum) */
#define RACEBOX_PVT_PACKET_SIZE         (88)

/** @brief Maximum permissible RaceBox packet size in bytes */
#define RACEBOX_MAX_PACKET_SIZE         (512)

/** @brief Maximum permissible RaceBox payload size in bytes */
#define RACEBOX_MAX_PAYLOAD_SIZE        (504)

/**
 * @brief GNSS Fix status enumeration.
 */
typedef enum {
    RACEBOX_FIX_NONE    = 0,    /**< No GNSS fix acquired */
    RACEBOX_FIX_DEAD_REC = 1,   /**< Dead reckoning only */
    RACEBOX_FIX_2D      = 2,    /**< 2D GNSS fix */
    RACEBOX_FIX_3D      = 3,    /**< 3D GNSS fix (Recommended for valid telemetry) */
    RACEBOX_FIX_GNSS_DR = 4,    /**< GNSS + Dead reckoning combined */
    RACEBOX_FIX_TIME    = 5     /**< Time-only fix */
} racebox_fix_status_t;

/**
 * @brief Validity bitmask flags for date and time fields.
 */
typedef enum {
    RACEBOX_VALID_DATE              = (1 << 0), /**< UTC Date is valid */
    RACEBOX_VALID_TIME              = (1 << 1), /**< UTC Time of day is valid */
    RACEBOX_VALID_FULLY_RESOLVED    = (1 << 2), /**< UTC time of day has been fully resolved (no leap second ambiguity) */
    RACEBOX_VALID_MAG_DECLINATION   = (1 << 3)  /**< Magnetic declination is valid */
} racebox_validity_flags_t;

/**
 * @brief Fix status flag bitmask.
 */
typedef enum {
    RACEBOX_FIX_FLAG_GNSS_FIX_OK    = (1 << 0), /**< 1 = Valid fix acquired within accuracy thresholds */
    RACEBOX_FIX_FLAG_DIFF_CORR      = (1 << 1), /**< 1 = Differential corrections were applied */
    RACEBOX_FIX_FLAG_HEADING_VALID  = (1 << 5)  /**< 1 = Vehicle heading of motion is valid */
} racebox_fix_flags_t;

/**
 * @brief Raw packed wire format of the 80-byte RaceBox Data Message payload (Class 0xFF, ID 0x01).
 *
 * All multi-byte fields are stored in Little-Endian byte order as transmitted over BLE.
 * Total size MUST equal exactly 80 bytes.
 */
#pragma pack(push, 1)
typedef struct {
    uint32_t itow;              /**< [Bytes 0..3] GPS Time of Week in milliseconds */
    uint16_t year;              /**< [Bytes 4..5] UTC Year (e.g. 2024) */
    uint8_t  month;             /**< [Byte 6] UTC Month (1..12) */
    uint8_t  day;               /**< [Byte 7] UTC Day of month (1..31) */
    uint8_t  hour;              /**< [Byte 8] UTC Hour of day (0..23) */
    uint8_t  minute;            /**< [Byte 9] UTC Minute of hour (0..59) */
    uint8_t  second;            /**< [Byte 10] UTC Second of minute (0..59) */
    uint8_t  validity_flags;    /**< [Byte 11] Validity flags (see racebox_validity_flags_t) */
    uint32_t time_accuracy;     /**< [Bytes 12..15] Time accuracy estimate in nanoseconds */
    int32_t  nanoseconds;       /**< [Bytes 16..19] Fractional nanoseconds remainder of UTC second (signed) */
    uint8_t  fix_status;        /**< [Byte 20] Fix status (see racebox_fix_status_t) */
    uint8_t  fix_status_flags;  /**< [Byte 21] Fix status flags (see racebox_fix_flags_t) */
    uint8_t  date_time_flags;   /**< [Byte 22] Additional date/time confirmation flags */
    uint8_t  num_sv;            /**< [Byte 23] Number of satellites (SVs) used in solution */
    int32_t  longitude;         /**< [Bytes 24..27] Longitude in degrees * 1e7 */
    int32_t  latitude;          /**< [Bytes 28..31] Latitude in degrees * 1e7 */
    int32_t  wgs_altitude;      /**< [Bytes 32..35] WGS84 ellipsoidal altitude in millimeters */
    int32_t  msl_altitude;      /**< [Bytes 36..39] Mean Sea Level altitude in millimeters */
    uint32_t hor_accuracy;      /**< [Bytes 40..43] Horizontal accuracy estimate in millimeters */
    uint32_t ver_accuracy;      /**< [Bytes 44..47] Vertical accuracy estimate in millimeters */
    int32_t  speed;             /**< [Bytes 48..51] Speed over ground in millimeters/second */
    int32_t  heading;           /**< [Bytes 52..55] Heading of motion in degrees * 1e5 (0 = North) */
    uint32_t speed_accuracy;    /**< [Bytes 56..59] Speed accuracy estimate in millimeters/second */
    uint32_t heading_accuracy;  /**< [Bytes 60..63] Heading accuracy estimate in degrees * 1e5 */
    uint16_t pdop;              /**< [Bytes 64..65] Position Dilution of Precision * 100 */
    uint8_t  lat_lon_flags;     /**< [Byte 66] Lat/Lon validity and differential correction flags */
    uint8_t  battery_status;    /**< [Byte 67] Battery status (Mini: bit 7 = charging, bits 0..6 = %; Micro: Vin * 10) */
    int16_t  g_force_x;         /**< [Bytes 68..69] Longitudinal acceleration in milli-g (front/back) */
    int16_t  g_force_y;         /**< [Bytes 70..71] Lateral acceleration in milli-g (right/left) */
    int16_t  g_force_z;         /**< [Bytes 72..73] Vertical acceleration in milli-g (up/down) */
    int16_t  rot_rate_x;        /**< [Bytes 74..75] Roll rotation rate in centi-degrees/second (roll) */
    int16_t  rot_rate_y;        /**< [Bytes 76..77] Pitch rotation rate in centi-degrees/second (pitch) */
    int16_t  rot_rate_z;        /**< [Bytes 78..79] Yaw rotation rate in centi-degrees/second (yaw) */
} racebox_wire_pvt_t;
#pragma pack(pop)

_Static_assert(sizeof(racebox_wire_pvt_t) == RACEBOX_PVT_PAYLOAD_SIZE,
               "racebox_wire_pvt_t layout size must be exactly 80 bytes");

/**
 * @brief Canonical decoded telemetry representation with engineering units.
 *
 * Multipliers from the wire format have been normalized into standard units:
 * - Latitude / Longitude: floating-point degrees
 * - Speed: kilometers per hour (km/h)
 * - Altitudes & Accuracies: meters (m)
 * - Accelerations: g (1 g ~ 9.81 m/s^2)
 * - Rotation Rates: degrees per second (deg/s)
 * - PDOP: dimensionless float
 */
typedef struct {
    uint32_t itow;              /**< GPS Time of Week in milliseconds */
    uint16_t year;              /**< UTC Year (e.g. 2024) */
    uint8_t  month;             /**< UTC Month (1..12) */
    uint8_t  day;               /**< UTC Day (1..31) */
    uint8_t  hour;              /**< UTC Hour (0..23) */
    uint8_t  minute;            /**< UTC Minute (0..59) */
    uint8_t  second;            /**< UTC Second (0..59) */
    int32_t  nanoseconds;       /**< UTC fractional nanoseconds (-1e9 .. 1e9) */
    bool     valid_date;        /**< True if UTC date is verified valid */
    bool     valid_time;        /**< True if UTC time is verified valid */
    bool     valid_fix;         /**< True if GNSS fix status is valid (Fix OK flag set) */

    racebox_fix_status_t fix_status; /**< Fix status classification (None, 2D, 3D) */
    uint8_t  num_sv;            /**< Number of satellites used in navigation solution */

    double   longitude_deg;     /**< Longitude in decimal degrees [-180.0 .. 180.0] */
    double   latitude_deg;      /**< Latitude in decimal degrees [-90.0 .. 90.0] */
    float    wgs_altitude_m;    /**< Ellipsoidal altitude in meters */
    float    msl_altitude_m;    /**< Mean Sea Level altitude in meters */
    float    hor_accuracy_m;    /**< Horizontal position accuracy estimate in meters */
    float    ver_accuracy_m;    /**< Vertical position accuracy estimate in meters */

    float    speed_kmh;         /**< Vehicle ground speed in km/h */
    float    heading_deg;       /**< Heading of motion in degrees [0.0 .. 360.0), 0 = North */
    float    speed_acc_kmh;     /**< Speed accuracy estimate in km/h */
    float    heading_acc_deg;   /**< Heading accuracy estimate in degrees */
    float    pdop;              /**< Position Dilution of Precision */

    bool     is_charging;       /**< True if device is connected to external power / charging */
    uint8_t  battery_percent;   /**< Battery state of charge in percent [0..100] (for Mini / Mini S) */
    float    input_voltage_v;   /**< Input power rail voltage in Volts (for Micro) */

    float    g_force_x;         /**< Longitudinal acceleration in g (+ = acceleration, - = braking) */
    float    g_force_y;         /**< Lateral acceleration in g (+ = right, - = left) */
    float    g_force_z;         /**< Vertical acceleration in g (+ = upward / normal gravity) */

    float    rot_rate_x;        /**< Roll rate in deg/s */
    float    rot_rate_y;        /**< Pitch rate in deg/s */
    float    rot_rate_z;        /**< Yaw rate in deg/s */

    racebox_wire_pvt_t raw;     /**< Unmodified bit-exact wire representation */
} racebox_pvt_t;

#ifdef __cplusplus
}
#endif
