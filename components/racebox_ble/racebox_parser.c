/**
 * @file racebox_parser.c
 * @brief Pure C implementation of RaceBox UBX stream parser and reassembler.
 */

#include "racebox_parser.h"
#include <string.h>

racebox_err_t racebox_parser_init(racebox_parser_t *parser,
                                  racebox_pvt_callback_t callback,
                                  void *user_data)
{
    if (!parser) {
        return RACEBOX_ERR_INVALID_ARG;
    }

    memset(parser, 0, sizeof(*parser));
    parser->callback = callback;
    parser->user_data = user_data;

    return RACEBOX_OK;
}

racebox_err_t racebox_parser_reset(racebox_parser_t *parser)
{
    if (!parser) {
        return RACEBOX_ERR_INVALID_ARG;
    }

    parser->buf_len = 0;
    return RACEBOX_OK;
}

void racebox_unpack_pvt(const racebox_wire_pvt_t *wire, racebox_pvt_t *out_pvt)
{
    if (!wire || !out_pvt) {
        return;
    }

    memset(out_pvt, 0, sizeof(*out_pvt));

    // Preserve raw bit-exact wire struct
    memcpy(&out_pvt->raw, wire, sizeof(racebox_wire_pvt_t));

    // Time fields
    out_pvt->itow = wire->itow;
    out_pvt->year = wire->year;
    out_pvt->month = wire->month;
    out_pvt->day = wire->day;
    out_pvt->hour = wire->hour;
    out_pvt->minute = wire->minute;
    out_pvt->second = wire->second;
    out_pvt->nanoseconds = wire->nanoseconds;

    // Validity flags
    out_pvt->valid_date = (wire->validity_flags & RACEBOX_VALID_DATE) != 0;
    out_pvt->valid_time = (wire->validity_flags & RACEBOX_VALID_TIME) != 0;
    out_pvt->valid_fix = (wire->fix_status_flags & RACEBOX_FIX_FLAG_GNSS_FIX_OK) != 0;

    // Fix status & satellites
    out_pvt->fix_status = (racebox_fix_status_t)wire->fix_status;
    out_pvt->num_sv = wire->num_sv;

    // Position coordinates (scale: 1e-7 deg)
    out_pvt->longitude_deg = (double)wire->longitude * 1e-7;
    out_pvt->latitude_deg  = (double)wire->latitude * 1e-7;

    // Altitudes & accuracies (scale: mm to meters)
    out_pvt->wgs_altitude_m = (float)wire->wgs_altitude / 1000.0f;
    out_pvt->msl_altitude_m = (float)wire->msl_altitude / 1000.0f;
    out_pvt->hor_accuracy_m = (float)wire->hor_accuracy / 1000.0f;
    out_pvt->ver_accuracy_m = (float)wire->ver_accuracy / 1000.0f;

    // Velocity & Heading (speed: mm/s to km/h, heading: 1e-5 deg)
    out_pvt->speed_kmh       = (float)wire->speed * 0.0036f;
    out_pvt->heading_deg     = (float)wire->heading * 1e-5f;
    out_pvt->speed_acc_kmh   = (float)wire->speed_accuracy * 0.0036f;
    out_pvt->heading_acc_deg = (float)wire->heading_accuracy * 1e-5f;

    // PDOP (scale: 1e-2)
    out_pvt->pdop = (float)wire->pdop * 0.01f;

    // Battery / Power (bit 7 = charging, bits 0..6 = %, or input voltage * 10)
    out_pvt->is_charging     = (wire->battery_status & 0x80) != 0;
    out_pvt->battery_percent = (wire->battery_status & 0x7F);
    out_pvt->input_voltage_v = (float)wire->battery_status * 0.1f;

    // Accelerometer (scale: milli-g to g)
    out_pvt->g_force_x = (float)wire->g_force_x / 1000.0f;
    out_pvt->g_force_y = (float)wire->g_force_y / 1000.0f;
    out_pvt->g_force_z = (float)wire->g_force_z / 1000.0f;

    // Gyroscope (scale: centi-deg/s to deg/s)
    out_pvt->rot_rate_x = (float)wire->rot_rate_x * 0.01f;
    out_pvt->rot_rate_y = (float)wire->rot_rate_y * 0.01f;
    out_pvt->rot_rate_z = (float)wire->rot_rate_z * 0.01f;
}

racebox_err_t racebox_parser_feed(racebox_parser_t *parser,
                                  const uint8_t *data,
                                  size_t len)
{
    if (!parser || !data) {
        return RACEBOX_ERR_INVALID_ARG;
    }

    if (len == 0) {
        return RACEBOX_OK;
    }

    parser->stats.bytes_ingested += (uint32_t)len;

    // Append incoming data to stream buffer
    if (parser->buf_len + len > RACEBOX_PARSER_BUFFER_SIZE) {
        // Drop excess oldest bytes to avoid memory corruption
        size_t excess = (parser->buf_len + len) - RACEBOX_PARSER_BUFFER_SIZE;
        if (excess >= parser->buf_len) {
            parser->buf_len = 0;
        } else {
            memmove(parser->buffer, parser->buffer + excess, parser->buf_len - excess);
            parser->buf_len -= excess;
        }
        if (len > RACEBOX_PARSER_BUFFER_SIZE) {
            data += (len - RACEBOX_PARSER_BUFFER_SIZE);
            len = RACEBOX_PARSER_BUFFER_SIZE;
        }
    }

    memcpy(parser->buffer + parser->buf_len, data, len);
    parser->buf_len += len;

    // Parse packet frames from stream buffer
    while (parser->buf_len >= 2) {
        // Search for sync preamble (0xB5 0x62)
        size_t sync_idx = 0;
        bool found_sync = false;

        for (size_t i = 0; i + 1 < parser->buf_len; i++) {
            if (parser->buffer[i] == RACEBOX_PREAMBLE_SYNC1 &&
                parser->buffer[i + 1] == RACEBOX_PREAMBLE_SYNC2) {
                sync_idx = i;
                found_sync = true;
                break;
            }
        }

        if (!found_sync) {
            // If the very last byte is 0xB5, preserve it for the next feed call
            if (parser->buffer[parser->buf_len - 1] == RACEBOX_PREAMBLE_SYNC1) {
                parser->buffer[0] = RACEBOX_PREAMBLE_SYNC1;
                parser->buf_len = 1;
            } else {
                parser->buf_len = 0;
            }
            break;
        }

        // Discard any garbage bytes before sync_idx
        if (sync_idx > 0) {
            memmove(parser->buffer, parser->buffer + sync_idx, parser->buf_len - sync_idx);
            parser->buf_len -= sync_idx;
        }

        // Need at least full header (6 bytes: Sync1, Sync2, Class, ID, LenL, LenH)
        if (parser->buf_len < 6) {
            break; // Wait for remaining header bytes
        }

        uint8_t  msg_class   = parser->buffer[2];
        uint8_t  msg_id      = parser->buffer[3];
        uint16_t payload_len = (uint16_t)parser->buffer[4] | ((uint16_t)parser->buffer[5] << 8);

        // Sanity check declared payload length
        if (payload_len > RACEBOX_MAX_PAYLOAD_SIZE) {
            parser->stats.frames_oversized_dropped++;
            // Discard 0xB5 byte and continue scanning for next sync
            memmove(parser->buffer, parser->buffer + 1, parser->buf_len - 1);
            parser->buf_len -= 1;
            continue;
        }

        size_t full_packet_size = 6 + (size_t)payload_len + 2;
        if (parser->buf_len < full_packet_size) {
            break; // Wait for full packet to arrive in buffer
        }

        // Compute 8-bit Fletcher checksum over Class, ID, Length, and Payload
        uint8_t ck_a = 0;
        uint8_t ck_b = 0;
        for (size_t i = 2; i < 6 + (size_t)payload_len; i++) {
            ck_a = (uint8_t)(ck_a + parser->buffer[i]);
            ck_b = (uint8_t)(ck_b + ck_a);
        }

        uint8_t expected_ck_a = parser->buffer[6 + payload_len];
        uint8_t expected_ck_b = parser->buffer[7 + payload_len];

        if (ck_a == expected_ck_a && ck_b == expected_ck_b) {
            parser->stats.frames_received++;

            if (msg_class == RACEBOX_MSG_CLASS_DATA &&
                msg_id == RACEBOX_MSG_ID_PVT &&
                payload_len == RACEBOX_PVT_PAYLOAD_SIZE) {
                racebox_pvt_t pvt;
                racebox_unpack_pvt((const racebox_wire_pvt_t *)(parser->buffer + 6), &pvt);
                if (parser->callback) {
                    parser->callback(&pvt, parser->user_data);
                }
            }

            // Advance buffer past the verified packet
            memmove(parser->buffer, parser->buffer + full_packet_size, parser->buf_len - full_packet_size);
            parser->buf_len -= full_packet_size;
        } else {
            parser->stats.frames_checksum_error++;
            // Checksum failed: false preamble candidate or corrupted frame.
            // Discard 1 byte so we scan starting from next byte to find legitimate sync.
            memmove(parser->buffer, parser->buffer + 1, parser->buf_len - 1);
            parser->buf_len -= 1;
        }
    }

    return RACEBOX_OK;
}
