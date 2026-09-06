/**
 * @file racebox_can_types.h
 * @brief Canonical 11-bit CAN frame layouts and packing definitions for RaceBox telemetry.
 *
 * Defines bit-exact packed structures (8 bytes DLC) and signal scaling factors
 * for messages 0x600 through 0x605 in Intel (Little-Endian) byte order.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include "racebox_types.h"

#ifdef __cplusplus
extern "C" {
#endif

#ifndef CONFIG_RACEBOX_CAN_BASE_ID
#define CONFIG_RACEBOX_CAN_BASE_ID (0x600)
#endif

/** @brief CAN standard 11-bit message identifiers */
#define RACEBOX_CAN_ID_SPEED_HEADING    ((uint32_t)(CONFIG_RACEBOX_CAN_BASE_ID + 0)) // 0x600
#define RACEBOX_CAN_ID_LAT_LON          ((uint32_t)(CONFIG_RACEBOX_CAN_BASE_ID + 1)) // 0x601
#define RACEBOX_CAN_ID_ALT_ACCURACY     ((uint32_t)(CONFIG_RACEBOX_CAN_BASE_ID + 2)) // 0x602
#define RACEBOX_CAN_ID_IMU_ACCEL        ((uint32_t)(CONFIG_RACEBOX_CAN_BASE_ID + 3)) // 0x603
#define RACEBOX_CAN_ID_IMU_GYRO         ((uint32_t)(CONFIG_RACEBOX_CAN_BASE_ID + 4)) // 0x604
#define RACEBOX_CAN_ID_UTC_TIME         ((uint32_t)(CONFIG_RACEBOX_CAN_BASE_ID + 5)) // 0x605

/**
 * @brief CAN Message 0x600: Speed & Heading Dynamics (DLC = 8)
 */
typedef struct __attribute__((packed)) {
    uint16_t speed_raw;         /**< Scale: 0.01 km/h (speed_kmh * 100), range [0, 655.35] */
    uint16_t heading_raw;       /**< Scale: 0.01 deg (heading_deg * 100), range [0, 359.99] */
    uint16_t speed_acc_raw;     /**< Scale: 0.01 km/h (speed_acc_kmh * 100), range [0, 655.35] */
    uint8_t  fix_status: 4;     /**< Fix status: 0=None, 2=2D, 3=3D */
    uint8_t  valid_fix: 1;      /**< 1 if GNSS Fix OK */
    uint8_t  valid_heading: 1;  /**< 1 if Heading of motion is valid */
    uint8_t  reserved: 2;       /**< Reserved bits */
    uint8_t  num_sv;            /**< Satellites used in navigation solution [0, 255] */
} racebox_can_speed_heading_t;
_Static_assert(sizeof(racebox_can_speed_heading_t) == 8, "racebox_can_speed_heading_t must be 8 bytes");

/**
 * @brief CAN Message 0x601: GPS Coordinates Latitude & Longitude (DLC = 8)
 */
typedef struct __attribute__((packed)) {
    int32_t latitude_raw;       /**< Scale: 1e-7 deg (divide by 1e7 for degrees), signed */
    int32_t longitude_raw;      /**< Scale: 1e-7 deg (divide by 1e7 for degrees), signed */
} racebox_can_lat_lon_t;
_Static_assert(sizeof(racebox_can_lat_lon_t) == 8, "racebox_can_lat_lon_t must be 8 bytes");

/**
 * @brief CAN Message 0x602: Altitude & Precision Accuracies (DLC = 8)
 */
typedef struct __attribute__((packed)) {
    int32_t  msl_altitude_mm;   /**< Scale: 0.001 m (direct millimeters from MSL) */
    uint16_t hor_accuracy_raw;  /**< Scale: 0.01 m (hor_accuracy_m * 100) */
    uint16_t pdop_raw;          /**< Scale: 0.01 (pdop * 100) */
} racebox_can_alt_accuracy_t;
_Static_assert(sizeof(racebox_can_alt_accuracy_t) == 8, "racebox_can_alt_accuracy_t must be 8 bytes");

/**
 * @brief CAN Message 0x603: 3-Axis Accelerometer & Battery Status (DLC = 8)
 */
typedef struct __attribute__((packed)) {
    int16_t g_force_x_mg;       /**< Scale: 0.001 g (milli-g), signed [-32768, +32767] */
    int16_t g_force_y_mg;       /**< Scale: 0.001 g (milli-g), signed [-32768, +32767] */
    int16_t g_force_z_mg;       /**< Scale: 0.001 g (milli-g), signed [-32768, +32767] */
    uint8_t battery_percent: 7; /**< Battery level [0..100] % */
    uint8_t is_charging: 1;     /**< 1 if charging, 0 if discharging */
    uint8_t rolling_counter;    /**< Rolling transmission counter [0..255] */
} racebox_can_imu_accel_t;
_Static_assert(sizeof(racebox_can_imu_accel_t) == 8, "racebox_can_imu_accel_t must be 8 bytes");

/**
 * @brief CAN Message 0x604: 3-Axis Gyroscope Rotation Rates (DLC = 8)
 */
typedef struct __attribute__((packed)) {
    int16_t  rot_rate_x_cdeg;   /**< Roll rate, scale: 0.01 deg/s (cdeg/s), signed */
    int16_t  rot_rate_y_cdeg;   /**< Pitch rate, scale: 0.01 deg/s (cdeg/s), signed */
    int16_t  rot_rate_z_cdeg;   /**< Yaw rate, scale: 0.01 deg/s (cdeg/s), signed */
    uint16_t reserved;          /**< Reserved */
} racebox_can_imu_gyro_t;
_Static_assert(sizeof(racebox_can_imu_gyro_t) == 8, "racebox_can_imu_gyro_t must be 8 bytes");

/**
 * @brief CAN Message 0x605: GPS UTC Date & Time (DLC = 8)
 */
typedef struct __attribute__((packed)) {
    uint16_t year;              /**< UTC Year (e.g. 2026) */
    uint8_t  month;             /**< UTC Month [1..12] */
    uint8_t  day;               /**< UTC Day of month [1..31] */
    uint8_t  hour;              /**< UTC Hour [0..23] */
    uint8_t  minute;            /**< UTC Minute [0..59] */
    uint8_t  second;            /**< UTC Second [0..59] */
    uint8_t  subsecond_csec;    /**< UTC Centiseconds [0..99] */
} racebox_can_utc_time_t;
_Static_assert(sizeof(racebox_can_utc_time_t) == 8, "racebox_can_utc_time_t must be 8 bytes");

/* -------------------------------------------------------------------------
 * Inline Packing Helper Functions
 * ------------------------------------------------------------------------- */

/**
 * @brief Pack speed, heading, accuracy, and GNSS fix status into CAN message 0x600 format.
 *
 * Encodes floating point speed and heading values into fixed-point raw units (0.01 scale),
 * clamping values to valid 16-bit ranges, and extracts GNSS fix status bitfields.
 *
 * @param[in]  pvt Pointer to canonical telemetry structure (must not be NULL).
 * @param[out] out Pointer to destination CAN message structure (must not be NULL).
 * @note Byte layout: Intel (Little-Endian) byte order, DLC = 8 bytes.
 */
static inline void racebox_can_pack_speed_heading(const racebox_pvt_t *pvt, racebox_can_speed_heading_t *out)
{
    if (!pvt || !out) return;
    float spd = pvt->speed_kmh * 100.0f;
    out->speed_raw = (spd < 0.0f) ? 0 : ((spd > 65535.0f) ? 65535 : (uint16_t)(spd + 0.5f));

    float hdg = pvt->heading_deg * 100.0f;
    out->heading_raw = (hdg < 0.0f) ? 0 : ((hdg > 65535.0f) ? 65535 : (uint16_t)(hdg + 0.5f));

    float spd_acc = pvt->speed_acc_kmh * 100.0f;
    out->speed_acc_raw = (spd_acc < 0.0f) ? 0 : ((spd_acc > 65535.0f) ? 65535 : (uint16_t)(spd_acc + 0.5f));

    out->fix_status = (uint8_t)(pvt->fix_status & 0x0F);
    out->valid_fix = pvt->valid_fix ? 1 : 0;
    out->valid_heading = (pvt->raw.fix_status_flags & RACEBOX_FIX_FLAG_HEADING_VALID) ? 1 : 0;
    out->reserved = 0;
    out->num_sv = pvt->num_sv;
}

/**
 * @brief Pack GPS Latitude and Longitude coordinates into CAN message 0x601 format.
 *
 * Directly copies signed 32-bit integer micro-degrees (1e-7 deg scale factor) matching
 * the UBX wire representation.
 *
 * @param[in]  pvt Pointer to canonical telemetry structure (must not be NULL).
 * @param[out] out Pointer to destination CAN message structure (must not be NULL).
 * @note Byte layout: Intel (Little-Endian) byte order, DLC = 8 bytes.
 */
static inline void racebox_can_pack_lat_lon(const racebox_pvt_t *pvt, racebox_can_lat_lon_t *out)
{
    if (!pvt || !out) return;
    out->latitude_raw = pvt->raw.latitude;
    out->longitude_raw = pvt->raw.longitude;
}

/**
 * @brief Pack MSL altitude, horizontal accuracy, and PDOP into CAN message 0x602 format.
 *
 * Encodes Mean Sea Level altitude in integer millimeters, horizontal accuracy in
 * centimeters (0.01 m scale), and PDOP (0.01 scale).
 *
 * @param[in]  pvt Pointer to canonical telemetry structure (must not be NULL).
 * @param[out] out Pointer to destination CAN message structure (must not be NULL).
 * @note Byte layout: Intel (Little-Endian) byte order, DLC = 8 bytes.
 */
static inline void racebox_can_pack_alt_accuracy(const racebox_pvt_t *pvt, racebox_can_alt_accuracy_t *out)
{
    if (!pvt || !out) return;
    out->msl_altitude_mm = pvt->raw.msl_altitude;

    float hacc = pvt->hor_accuracy_m * 100.0f;
    out->hor_accuracy_raw = (hacc < 0.0f) ? 0 : ((hacc > 65535.0f) ? 65535 : (uint16_t)(hacc + 0.5f));

    float pdop = pvt->pdop * 100.0f;
    out->pdop_raw = (pdop < 0.0f) ? 0 : ((pdop > 65535.0f) ? 65535 : (uint16_t)(pdop + 0.5f));
}

/**
 * @brief Pack 3-axis accelerometer, battery status, and rolling counter into CAN message 0x603 format.
 *
 * Encodes G-forces in signed milli-g (-32768 to +32767), battery state of charge (0..100%),
 * charging bit, and rolling frame counter.
 *
 * @param[in]  pvt Pointer to canonical telemetry structure (must not be NULL).
 * @param[in]  counter 8-bit sequential rolling counter for message alive validation.
 * @param[out] out Pointer to destination CAN message structure (must not be NULL).
 * @note Byte layout: Intel (Little-Endian) byte order, DLC = 8 bytes.
 */
static inline void racebox_can_pack_imu_accel(const racebox_pvt_t *pvt, uint8_t counter, racebox_can_imu_accel_t *out)
{
    if (!pvt || !out) return;
    out->g_force_x_mg = pvt->raw.g_force_x;
    out->g_force_y_mg = pvt->raw.g_force_y;
    out->g_force_z_mg = pvt->raw.g_force_z;
    out->battery_percent = (uint8_t)(pvt->battery_percent & 0x7F);
    out->is_charging = pvt->is_charging ? 1 : 0;
    out->rolling_counter = counter;
}

/**
 * @brief Pack 3-axis gyroscope angular rotation rates into CAN message 0x604 format.
 *
 * Encodes Roll, Pitch, and Yaw angular rates in signed centi-degrees/second (0.01 deg/s scale).
 *
 * @param[in]  pvt Pointer to canonical telemetry structure (must not be NULL).
 * @param[out] out Pointer to destination CAN message structure (must not be NULL).
 * @note Byte layout: Intel (Little-Endian) byte order, DLC = 8 bytes.
 */
static inline void racebox_can_pack_imu_gyro(const racebox_pvt_t *pvt, racebox_can_imu_gyro_t *out)
{
    if (!pvt || !out) return;
    out->rot_rate_x_cdeg = pvt->raw.rot_rate_x;
    out->rot_rate_y_cdeg = pvt->raw.rot_rate_y;
    out->rot_rate_z_cdeg = pvt->raw.rot_rate_z;
    out->reserved = 0;
}

/**
 * @brief Pack GPS UTC date, time of day, and fractional centiseconds into CAN message 0x605 format.
 *
 * Encodes UTC Year (uint16), Month, Day, Hour, Minute, Second, and subsecond centiseconds (0..99).
 *
 * @param[in]  pvt Pointer to canonical telemetry structure (must not be NULL).
 * @param[out] out Pointer to destination CAN message structure (must not be NULL).
 * @note Byte layout: Intel (Little-Endian) byte order, DLC = 8 bytes.
 */
static inline void racebox_can_pack_utc_time(const racebox_pvt_t *pvt, racebox_can_utc_time_t *out)
{
    if (!pvt || !out) return;
    out->year = pvt->year;
    out->month = pvt->month;
    out->day = pvt->day;
    out->hour = pvt->hour;
    out->minute = pvt->minute;
    out->second = pvt->second;
    uint32_t csec = (uint32_t)(pvt->nanoseconds / 10000000);
    out->subsecond_csec = (uint8_t)(csec < 100 ? csec : 99);
}

#ifdef __cplusplus
}
#endif
