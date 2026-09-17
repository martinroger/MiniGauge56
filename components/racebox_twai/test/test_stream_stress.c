/**
 * @file test_stream_stress.c
 * @brief Host-side stress and endurance test runner for RaceBox telemetry ingestion and CAN packing.
 *
 * Simulates high-rate ingestion of 100,000 continuous telemetry frames, verifying rate prescaling
 * distribution, bitfield consistency, rolling counters, and microsecond packing throughput.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <time.h>
#include "racebox_parser.h"
#include "racebox_can_types.h"

// Official sample 88-byte packet from RaceBox BLE Protocol Specification rev 9 (pages 7-9)
static const uint8_t s_sample_packet[88] = {
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

static inline bool should_send(uint32_t frame_idx, int rate_mode)
{
    switch (rate_mode) {
    case 0: return true;                        // 25 Hz (all frames)
    case 1: return (frame_idx % 5 == 0) || (frame_idx % 5 == 2); // 10 Hz (2 out of 5)
    case 2: return (frame_idx % 5 == 0);        // 5 Hz (1 out of 5)
    case 3: return (frame_idx % 25 == 0);       // 1 Hz (1 out of 25)
    default: return false;
    }
}

typedef struct {
    uint32_t count_25hz;
    uint32_t count_10hz;
    uint32_t count_5hz;
    uint32_t count_1hz;
    uint8_t  last_counter;
} stress_context_t;

static void on_frame(const racebox_pvt_t *pvt, void *user_data)
{
    stress_context_t *ctx = (stress_context_t *)user_data;
    uint32_t idx = ctx->count_25hz++;
    ctx->last_counter++;

    // Pack all CAN messages
    racebox_can_speed_heading_t m0;
    racebox_can_lat_lon_t       m1;
    racebox_can_alt_accuracy_t  m2;
    racebox_can_imu_accel_t     m3;
    racebox_can_imu_gyro_t      m4;
    racebox_can_utc_time_t      m5;

    racebox_can_pack_speed_heading(pvt, &m0);
    racebox_can_pack_lat_lon(pvt, &m1);
    racebox_can_pack_alt_accuracy(pvt, &m2);
    racebox_can_pack_imu_accel(pvt, ctx->last_counter, &m3);
    racebox_can_pack_imu_gyro(pvt, &m4);
    racebox_can_pack_utc_time(pvt, &m5);

    // Verify rolling counter
    assert(m3.rolling_counter == ctx->last_counter);

    // Test rate divider models
    if (should_send(idx, 1)) ctx->count_10hz++;
    if (should_send(idx, 2)) ctx->count_5hz++;
    if (should_send(idx, 3)) ctx->count_1hz++;
}

int main(void)
{
    printf("====================================================\n");
    printf(" RaceBox Telemetry & CAN Pipeline Stress Test\n");
    printf("====================================================\n");

    racebox_parser_t parser;
    stress_context_t ctx = {0};

    int init_res = racebox_parser_init(&parser, on_frame, &ctx);
    assert(init_res == RACEBOX_OK);

    const uint32_t TOTAL_FRAMES = 100000;
    printf("[STRESS] Ingesting %u continuous frames through parser & CAN packer...\n", TOTAL_FRAMES);

    clock_t start = clock();

    for (uint32_t i = 0; i < TOTAL_FRAMES; i++) {
        racebox_err_t err = racebox_parser_feed(&parser, s_sample_packet, sizeof(s_sample_packet));
        if (err != RACEBOX_OK) {
            fprintf(stderr, "Feed error at frame %u: %d\n", i, err);
            return 1;
        }
    }

    clock_t end = clock();
    double elapsed_sec = (double)(end - start) / CLOCKS_PER_SEC;
    double throughput_fps = (double)TOTAL_FRAMES / elapsed_sec;

    printf("[PASS] Processed %u frames in %.3f seconds (%.0f frames/sec)\n",
           TOTAL_FRAMES, elapsed_sec, throughput_fps);

    // Validate parser statistics
    assert(parser.stats.frames_received == TOTAL_FRAMES);
    assert(parser.stats.frames_checksum_error == 0);
    assert(parser.stats.frames_oversized_dropped == 0);
    assert(parser.stats.bytes_ingested == TOTAL_FRAMES * sizeof(s_sample_packet));

    // Validate rate prescalers
    printf("[CHECK] Verifying rate divider counts over %u frames:\n", TOTAL_FRAMES);
    printf("  25 Hz count: %u (expected: %u)\n", ctx.count_25hz, TOTAL_FRAMES);
    printf("  10 Hz count: %u (expected: %u)\n", ctx.count_10hz, (TOTAL_FRAMES * 2) / 5);
    printf("   5 Hz count: %u (expected: %u)\n", ctx.count_5hz, TOTAL_FRAMES / 5);
    printf("   1 Hz count: %u (expected: %u)\n", ctx.count_1hz, TOTAL_FRAMES / 25);

    assert(ctx.count_25hz == TOTAL_FRAMES);
    assert(ctx.count_10hz == (TOTAL_FRAMES * 2) / 5);
    assert(ctx.count_5hz == TOTAL_FRAMES / 5);
    assert(ctx.count_1hz == TOTAL_FRAMES / 25);

    printf("====================================================\n");
    printf(" ALL STRESS AND ENDURANCE CHECKS PASSED!\n");
    printf("====================================================\n");
    return 0;
}
