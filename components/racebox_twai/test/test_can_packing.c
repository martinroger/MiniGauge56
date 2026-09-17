/**
 * @file test_can_packing.c
 * @brief Host-side unit test runner for RaceBox CAN frame packing and signal scaling.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include "racebox_parser.h"
#include "racebox_can_types.h"

// Official sample 88-byte packet from RaceBox BLE Protocol Specification rev 9
static const uint8_t s_sample_packet[] = {
    0xB5, 0x62,                         // Header (Sync 1 & 2)
    0xFF, 0x01,                         // Class 0xFF, ID 0x01
    0x50, 0x00,                         // Length: 80 bytes (0x0050)
    0xA0, 0xE7, 0x0C, 0x07,             // iTOW: 118286240
    0xE6, 0x07,                         // Year: 2022
    0x01,                               // Month: 1
    0x0A,                               // Day: 10
    0x08,                               // Hour: 8
    0x33,                               // Minute: 51
    0x08,                               // Second: 8
    0x37,                               // Validity flags: 0x37
    0x19, 0x00, 0x00, 0x00,             // Time accuracy: 25 ns
    0x2A, 0xAD, 0x4D, 0x0E,             // Nanoseconds: 239971626 ns
    0x03,                               // Fix status: 3 (3D Fix)
    0x01,                               // Fix status flags: 0x01 (Fix OK)
    0xEA,                               // Date/Time flags: 0xEA
    0x0B,                               // Number of SVs: 11
    0xC6, 0x93, 0xE1, 0x0D,             // Longitude: 232887238 (23.2887238 deg)
    0x3B, 0x37, 0x6F, 0x19,             // Latitude: 426719035 (42.6719035 deg)
    0x61, 0x8C, 0x09, 0x00,             // WGS Altitude: 625761 mm (625.761 m)
    0x0F, 0x01, 0x09, 0x00,             // MSL Altitude: 590095 mm (590.095 m)
    0x9C, 0x03, 0x00, 0x00,             // Horizontal accuracy: 924 mm (0.924 m)
    0x2C, 0x07, 0x00, 0x00,             // Vertical accuracy: 1836 mm (1.836 m)
    0x23, 0x00, 0x00, 0x00,             // Speed: 35 mm/s (0.126 km/h)
    0x00, 0x00, 0x00, 0x00,             // Heading: 0 deg
    0xD0, 0x00, 0x00, 0x00,             // Speed accuracy: 208 mm/s
    0x88, 0xA9, 0xDD, 0x00,             // Heading accuracy: 14526856 (145.26856 deg)
    0x2C, 0x01,                         // PDOP: 300 (3.00)
    0x00,                               // Lat/Lon flags: 0x00
    0x59,                               // Battery status: 0x59 (89%, not charging)
    0xFD, 0xFF,                         // GForceX: -3 (-0.003 g)
    0x71, 0x00,                         // GForceY: 113 (0.113 g)
    0xCE, 0x03,                         // GForceZ: 974 (0.974 g)
    0x2F, 0xFF,                         // RotRateX: -209 (-2.09 deg/s)
    0x56, 0x00,                         // RotRateY: 86 (0.86 deg/s)
    0xFC, 0xFF,                         // RotRateZ: -4 (-0.04 deg/s)
    0x06, 0xDB                          // Checksum: CK_A=0x06, CK_B=0xDB
};

static void test_struct_sizes(void)
{
    printf("Testing struct sizes and alignments...\n");
    assert(sizeof(racebox_can_speed_heading_t) == 8);
    assert(sizeof(racebox_can_lat_lon_t) == 8);
    assert(sizeof(racebox_can_alt_accuracy_t) == 8);
    assert(sizeof(racebox_can_imu_accel_t) == 8);
    assert(sizeof(racebox_can_imu_gyro_t) == 8);
    assert(sizeof(racebox_can_utc_time_t) == 8);
    printf("  PASS: All 6 CAN message structs are exactly 8 bytes (DLC=8).\n");
}

static void test_can_ids(void)
{
    printf("Testing CAN identifiers...\n");
    assert(RACEBOX_CAN_ID_SPEED_HEADING == 0x600);
    assert(RACEBOX_CAN_ID_LAT_LON       == 0x601);
    assert(RACEBOX_CAN_ID_ALT_ACCURACY  == 0x602);
    assert(RACEBOX_CAN_ID_IMU_ACCEL     == 0x603);
    assert(RACEBOX_CAN_ID_IMU_GYRO      == 0x604);
    assert(RACEBOX_CAN_ID_UTC_TIME      == 0x605);
    printf("  PASS: Base ID 0x600 offsets are contiguous 0x600..0x605.\n");
}

typedef struct {
    bool received;
    racebox_pvt_t pvt;
} test_parser_ctx_t;

static void on_test_pvt(const racebox_pvt_t *pvt, void *user_data)
{
    test_parser_ctx_t *ctx = (test_parser_ctx_t *)user_data;
    ctx->received = true;
    ctx->pvt = *pvt;
}

static void test_packing_sample_packet(void)
{
    printf("Testing packing of official RaceBox sample packet...\n");

    test_parser_ctx_t ctx = {0};
    racebox_parser_t parser;
    racebox_parser_init(&parser, on_test_pvt, &ctx);

    racebox_err_t err = racebox_parser_feed(&parser, s_sample_packet, sizeof(s_sample_packet));
    assert(err == RACEBOX_OK);
    assert(ctx.received);
    const racebox_pvt_t *pvt = &ctx.pvt;

    // 1. Message 0x600: Speed & Heading
    racebox_can_speed_heading_t msg_0x600;
    memset(&msg_0x600, 0, sizeof(msg_0x600));
    racebox_can_pack_speed_heading(pvt, &msg_0x600);

    // Speed: 35 mm/s = 0.126 km/h -> 13 in 0.01 km/h
    assert(msg_0x600.speed_raw == 13);
    assert(msg_0x600.heading_raw == 0);
    // Speed acc: 208 mm/s = 0.7488 km/h -> 75 in 0.01 km/h
    assert(msg_0x600.speed_acc_raw == 75);
    assert(msg_0x600.fix_status == 3);
    assert(msg_0x600.valid_fix == 1);
    assert(msg_0x600.valid_heading == 0);
    assert(msg_0x600.num_sv == 11);

    const uint8_t *b600 = (const uint8_t *)&msg_0x600;
    assert(b600[0] == 0x0D);
    assert(b600[1] == 0x00);
    assert(b600[2] == 0x00);
    assert(b600[3] == 0x00);
    assert(b600[4] == 0x4B);
    assert(b600[5] == 0x00);
    assert(b600[6] == 0x13); // fix_status=3 | (valid_fix=1 << 4)
    assert(b600[7] == 0x0B); // num_sv=11
    printf("  PASS: Message 0x600 bit-exact layout verified.\n");

    // 2. Message 0x601: Latitude & Longitude
    racebox_can_lat_lon_t msg_0x601;
    memset(&msg_0x601, 0, sizeof(msg_0x601));
    racebox_can_pack_lat_lon(pvt, &msg_0x601);

    assert(msg_0x601.latitude_raw == 426719035);
    assert(msg_0x601.longitude_raw == 232887238);

    const uint8_t *b601 = (const uint8_t *)&msg_0x601;
    assert(b601[0] == 0x3B);
    assert(b601[1] == 0x37);
    assert(b601[2] == 0x6F);
    assert(b601[3] == 0x19);
    assert(b601[4] == 0xC6);
    assert(b601[5] == 0x93);
    assert(b601[6] == 0xE1);
    assert(b601[7] == 0x0D);
    printf("  PASS: Message 0x601 bit-exact layout verified.\n");

    // 3. Message 0x602: Altitude & Precision
    racebox_can_alt_accuracy_t msg_0x602;
    memset(&msg_0x602, 0, sizeof(msg_0x602));
    racebox_can_pack_alt_accuracy(pvt, &msg_0x602);

    assert(msg_0x602.msl_altitude_mm == 590095);
    // Hor accuracy: 0.924 m -> 92
    assert(msg_0x602.hor_accuracy_raw == 92);
    // PDOP: 3.00 -> 300
    assert(msg_0x602.pdop_raw == 300);

    const uint8_t *b602 = (const uint8_t *)&msg_0x602;
    assert(b602[0] == 0x0F);
    assert(b602[1] == 0x01);
    assert(b602[2] == 0x09);
    assert(b602[3] == 0x00);
    assert(b602[4] == 0x5C);
    assert(b602[5] == 0x00);
    assert(b602[6] == 0x2C);
    assert(b602[7] == 0x01);
    printf("  PASS: Message 0x602 bit-exact layout verified.\n");

    // 4. Message 0x603: IMU Accelerometer & Battery
    racebox_can_imu_accel_t msg_0x603;
    memset(&msg_0x603, 0, sizeof(msg_0x603));
    racebox_can_pack_imu_accel(pvt, 42, &msg_0x603);

    assert(msg_0x603.g_force_x_mg == -3);
    assert(msg_0x603.g_force_y_mg == 113);
    assert(msg_0x603.g_force_z_mg == 974);
    assert(msg_0x603.battery_percent == 89);
    assert(msg_0x603.is_charging == 0);
    assert(msg_0x603.rolling_counter == 42);

    const uint8_t *b603 = (const uint8_t *)&msg_0x603;
    assert(b603[0] == 0xFD);
    assert(b603[1] == 0xFF);
    assert(b603[2] == 0x71);
    assert(b603[3] == 0x00);
    assert(b603[4] == 0xCE);
    assert(b603[5] == 0x03);
    assert(b603[6] == 0x59); // 89% (0x59) | charging(0)
    assert(b603[7] == 42);
    printf("  PASS: Message 0x603 bit-exact layout verified.\n");

    // 5. Message 0x604: IMU Gyroscope
    racebox_can_imu_gyro_t msg_0x604;
    memset(&msg_0x604, 0, sizeof(msg_0x604));
    racebox_can_pack_imu_gyro(pvt, &msg_0x604);

    assert(msg_0x604.rot_rate_x_cdeg == -209);
    assert(msg_0x604.rot_rate_y_cdeg == 86);
    assert(msg_0x604.rot_rate_z_cdeg == -4);
    assert(msg_0x604.reserved == 0);

    const uint8_t *b604 = (const uint8_t *)&msg_0x604;
    assert(b604[0] == 0x2F);
    assert(b604[1] == 0xFF);
    assert(b604[2] == 0x56);
    assert(b604[3] == 0x00);
    assert(b604[4] == 0xFC);
    assert(b604[5] == 0xFF);
    assert(b604[6] == 0x00);
    assert(b604[7] == 0x00);
    printf("  PASS: Message 0x604 bit-exact layout verified.\n");

    // 6. Message 0x605: UTC Date & Time
    racebox_can_utc_time_t msg_0x605;
    memset(&msg_0x605, 0, sizeof(msg_0x605));
    racebox_can_pack_utc_time(pvt, &msg_0x605);

    assert(msg_0x605.year == 2022);
    assert(msg_0x605.month == 1);
    assert(msg_0x605.day == 10);
    assert(msg_0x605.hour == 8);
    assert(msg_0x605.minute == 51);
    assert(msg_0x605.second == 8);
    assert(msg_0x605.subsecond_csec == 23); // 239971626 / 10000000 = 23

    const uint8_t *b605 = (const uint8_t *)&msg_0x605;
    assert(b605[0] == 0xE6);
    assert(b605[1] == 0x07);
    assert(b605[2] == 0x01);
    assert(b605[3] == 0x0A);
    assert(b605[4] == 0x08);
    assert(b605[5] == 0x33);
    assert(b605[6] == 0x08);
    assert(b605[7] == 23);
    printf("  PASS: Message 0x605 bit-exact layout verified.\n");
}

static void test_edge_cases(void)
{
    printf("Testing edge cases and boundary handling...\n");
    racebox_pvt_t pvt;
    memset(&pvt, 0, sizeof(pvt));

    // Over-speed clamp test (> 655.35 km/h)
    pvt.speed_kmh = 700.0f;
    racebox_can_speed_heading_t msg_speed;
    racebox_can_pack_speed_heading(&pvt, &msg_speed);
    assert(msg_speed.speed_raw == 65535);

    // Negative coord test
    pvt.raw.latitude = -338688200;  // Sydney
    pvt.raw.longitude = 1512093000;
    racebox_can_lat_lon_t msg_coords;
    racebox_can_pack_lat_lon(&pvt, &msg_coords);
    assert(msg_coords.latitude_raw == -338688200);
    assert(msg_coords.longitude_raw == 1512093000);

    // Charging flag test
    pvt.battery_percent = 100;
    pvt.is_charging = true;
    racebox_can_imu_accel_t msg_accel;
    racebox_can_pack_imu_accel(&pvt, 255, &msg_accel);
    assert(msg_accel.battery_percent == 100);
    assert(msg_accel.is_charging == 1);
    assert(msg_accel.rolling_counter == 255);
    const uint8_t *b_accel = (const uint8_t *)&msg_accel;
    // byte 6: 100 (0x64) | (1 << 7) = 0xE4
    assert(b_accel[6] == 0xE4);

    // Subsecond 999999999 ns clamp test
    pvt.nanoseconds = 999999999;
    racebox_can_utc_time_t msg_time;
    racebox_can_pack_utc_time(&pvt, &msg_time);
    assert(msg_time.subsecond_csec == 99);

    printf("  PASS: Edge cases handled cleanly.\n");
}

int main(void)
{
    printf("==================================================\n");
    printf("RaceBox Companion CAN Frame Packing Unit Tests\n");
    printf("==================================================\n");

    test_struct_sizes();
    test_can_ids();
    test_packing_sample_packet();
    test_edge_cases();

    printf("==================================================\n");
    printf("ALL CAN PACKING TESTS PASSED SUCCESSFULLY!\n");
    printf("==================================================\n");
    return 0;
}
