/**
 * @file test_parser.c
 * @brief Host-side unit test runner for RaceBox pure C stream parser.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <assert.h>
#include "racebox_parser.h"

// Official sample 88-byte packet from RaceBox BLE Protocol Specification rev 9 (pages 7-9)
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

typedef struct {
    uint32_t callback_count;
    racebox_pvt_t last_pvt;
} test_context_t;

static void on_pvt_frame(const racebox_pvt_t *pvt, void *user_data)
{
    test_context_t *ctx = (test_context_t *)user_data;
    ctx->callback_count++;
    ctx->last_pvt = *pvt;
}

static bool float_near(float a, float b, float epsilon)
{
    return fabsf(a - b) <= epsilon;
}

static bool double_near(double a, double b, double epsilon)
{
    return fabs(a - b) <= epsilon;
}

static void test_official_sample_frame(void)
{
    printf("[RUN] Testing official sample frame decoding...\n");
    test_context_t ctx = {0};
    racebox_parser_t parser;

    assert(racebox_parser_init(&parser, on_pvt_frame, &ctx) == RACEBOX_OK);
    assert(racebox_parser_feed(&parser, s_sample_packet, sizeof(s_sample_packet)) == RACEBOX_OK);

    assert(ctx.callback_count == 1);
    assert(parser.stats.frames_received == 1);
    assert(parser.stats.frames_checksum_error == 0);

    // Verify time
    assert(ctx.last_pvt.itow == 118286240);
    assert(ctx.last_pvt.year == 2022);
    assert(ctx.last_pvt.month == 1);
    assert(ctx.last_pvt.day == 10);
    assert(ctx.last_pvt.hour == 8);
    assert(ctx.last_pvt.minute == 51);
    assert(ctx.last_pvt.second == 8);
    assert(ctx.last_pvt.nanoseconds == 239971626);
    assert(ctx.last_pvt.valid_date == true);
    assert(ctx.last_pvt.valid_time == true);
    assert(ctx.last_pvt.valid_fix == true);

    // Verify coordinates
    assert(double_near(ctx.last_pvt.longitude_deg, 23.2887238, 1e-6));
    assert(double_near(ctx.last_pvt.latitude_deg, 42.6719035, 1e-6));

    // Verify altitudes & accuracies
    assert(float_near(ctx.last_pvt.wgs_altitude_m, 625.761f, 0.001f));
    assert(float_near(ctx.last_pvt.msl_altitude_m, 590.095f, 0.001f));
    assert(float_near(ctx.last_pvt.hor_accuracy_m, 0.924f, 0.001f));
    assert(float_near(ctx.last_pvt.ver_accuracy_m, 1.836f, 0.001f));

    // Verify speed & heading
    assert(float_near(ctx.last_pvt.speed_kmh, 0.126f, 0.001f));
    assert(float_near(ctx.last_pvt.heading_deg, 0.0f, 0.001f));
    assert(float_near(ctx.last_pvt.heading_acc_deg, 145.26856f, 0.001f));
    assert(float_near(ctx.last_pvt.pdop, 3.00f, 0.01f));

    // Verify battery
    assert(ctx.last_pvt.is_charging == false);
    assert(ctx.last_pvt.battery_percent == 89);

    // Verify IMU
    assert(float_near(ctx.last_pvt.g_force_x, -0.003f, 0.0005f));
    assert(float_near(ctx.last_pvt.g_force_y, 0.113f, 0.0005f));
    assert(float_near(ctx.last_pvt.g_force_z, 0.974f, 0.0005f));
    assert(float_near(ctx.last_pvt.rot_rate_x, -2.09f, 0.01f));
    assert(float_near(ctx.last_pvt.rot_rate_y, 0.86f, 0.01f));
    assert(float_near(ctx.last_pvt.rot_rate_z, -0.04f, 0.01f));

    printf("[PASS] Official sample frame decoded and verified.\n");
}

static void test_fragmented_streaming(void)
{
    printf("[RUN] Testing fragmented streaming across small chunks...\n");
    test_context_t ctx = {0};
    racebox_parser_t parser;

    assert(racebox_parser_init(&parser, on_pvt_frame, &ctx) == RACEBOX_OK);

    // Test byte-by-byte ingestion (chunk size = 1)
    for (size_t i = 0; i < sizeof(s_sample_packet); i++) {
        assert(racebox_parser_feed(&parser, &s_sample_packet[i], 1) == RACEBOX_OK);
    }
    assert(ctx.callback_count == 1);
    assert(parser.stats.frames_received == 1);

    // Test uneven chunk sizes (e.g. 17, 23, 11, 37 bytes)
    ctx.callback_count = 0;
    size_t chunk_sizes[] = {17, 23, 11, 37};
    size_t offset = 0;
    for (size_t i = 0; i < sizeof(chunk_sizes)/sizeof(chunk_sizes[0]); i++) {
        size_t csize = chunk_sizes[i];
        assert(racebox_parser_feed(&parser, &s_sample_packet[offset], csize) == RACEBOX_OK);
        offset += csize;
    }
    assert(ctx.callback_count == 1);
    assert(parser.stats.frames_received == 2);

    printf("[PASS] Fragmented streaming verified across arbitrary chunk boundaries.\n");
}

static void test_concatenated_frames(void)
{
    printf("[RUN] Testing concatenated frames in a single notification chunk...\n");
    test_context_t ctx = {0};
    racebox_parser_t parser;

    assert(racebox_parser_init(&parser, on_pvt_frame, &ctx) == RACEBOX_OK);

    // Concatenate 3 frames together (3 * 88 = 264 bytes)
    uint8_t buffer[sizeof(s_sample_packet) * 3];
    memcpy(buffer, s_sample_packet, sizeof(s_sample_packet));
    memcpy(buffer + sizeof(s_sample_packet), s_sample_packet, sizeof(s_sample_packet));
    memcpy(buffer + sizeof(s_sample_packet) * 2, s_sample_packet, sizeof(s_sample_packet));

    assert(racebox_parser_feed(&parser, buffer, sizeof(buffer)) == RACEBOX_OK);
    assert(ctx.callback_count == 3);
    assert(parser.stats.frames_received == 3);

    printf("[PASS] Concatenated frames decoded correctly.\n");
}

static void test_corrupted_checksum_and_resync(void)
{
    printf("[RUN] Testing corrupted checksum handling and stream resync...\n");
    test_context_t ctx = {0};
    racebox_parser_t parser;

    assert(racebox_parser_init(&parser, on_pvt_frame, &ctx) == RACEBOX_OK);

    // Create corrupted frame with inverted checksum
    uint8_t corrupt_frame[sizeof(s_sample_packet)];
    memcpy(corrupt_frame, s_sample_packet, sizeof(s_sample_packet));
    corrupt_frame[sizeof(corrupt_frame) - 1] ^= 0xFF; // Invert CK_B

    // Feed corrupt frame
    assert(racebox_parser_feed(&parser, corrupt_frame, sizeof(corrupt_frame)) == RACEBOX_OK);
    assert(ctx.callback_count == 0);
    assert(parser.stats.frames_checksum_error == 1);

    // Feed valid frame immediately after
    assert(racebox_parser_feed(&parser, s_sample_packet, sizeof(s_sample_packet)) == RACEBOX_OK);
    assert(ctx.callback_count == 1);
    assert(parser.stats.frames_received == 1);

    printf("[PASS] Corrupted checksum rejected and resynchronized successfully.\n");
}

static void test_garbage_bytes_recovery(void)
{
    printf("[RUN] Testing garbage bytes injection and recovery...\n");
    test_context_t ctx = {0};
    racebox_parser_t parser;

    assert(racebox_parser_init(&parser, on_pvt_frame, &ctx) == RACEBOX_OK);

    // Feed random garbage, fake sync bytes, and partial preambles
    uint8_t garbage[] = {
        0x12, 0x34, 0xB5, 0x00, 0x00, 0xB5, 0xB5, 0xB5, 0x62, 0x01, 0x02,
        0x50, 0x00, 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF, 0x00, 0x11
    };
    assert(racebox_parser_feed(&parser, garbage, sizeof(garbage)) == RACEBOX_OK);
    assert(ctx.callback_count == 0);

    // Feed valid frame
    assert(racebox_parser_feed(&parser, s_sample_packet, sizeof(s_sample_packet)) == RACEBOX_OK);
    assert(ctx.callback_count == 1);
    assert(parser.stats.frames_received == 1);

    printf("[PASS] Garbage recovery test passed.\n");
}

static void test_oversized_payload_rejection(void)
{
    printf("[RUN] Testing oversized payload rejection...\n");
    test_context_t ctx = {0};
    racebox_parser_t parser;

    assert(racebox_parser_init(&parser, on_pvt_frame, &ctx) == RACEBOX_OK);

    // Header declaring 505 bytes payload (limit is 504)
    uint8_t oversized_header[] = { 0xB5, 0x62, 0xFF, 0x01, 0xF9, 0x01 }; // 0x01F9 = 505
    assert(racebox_parser_feed(&parser, oversized_header, sizeof(oversized_header)) == RACEBOX_OK);
    assert(parser.stats.frames_oversized_dropped == 1);

    // Confirm it can still parse a subsequent valid frame
    assert(racebox_parser_feed(&parser, s_sample_packet, sizeof(s_sample_packet)) == RACEBOX_OK);
    assert(ctx.callback_count == 1);
    assert(parser.stats.frames_received == 1);

    printf("[PASS] Oversized payload rejected cleanly.\n");
}

int main(void)
{
    printf("==============================================\n");
    printf(" RaceBox Stream Parser - Unit Test Suite\n");
    printf("==============================================\n");

    test_official_sample_frame();
    test_fragmented_streaming();
    test_concatenated_frames();
    test_corrupted_checksum_and_resync();
    test_garbage_bytes_recovery();
    test_oversized_payload_rejection();

    printf("==============================================\n");
    printf(" ALL 6 UNIT TESTS PASSED SUCCESSFULLY!\n");
    printf("==============================================\n");

    return 0;
}
