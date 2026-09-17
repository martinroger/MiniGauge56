/**
 * @file racebox_parser.h
 * @brief Pure C stream parser and frame reassembler for RaceBox UBX binary protocol.
 *
 * This parser processes arbitrary byte streams (e.g. fragmented or concatenated BLE notifications),
 * reconstructs whole frames, validates Fletcher-8 checksums, and dispatches parsed telemetry
 * callbacks without dynamic memory allocation.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "racebox_types.h"

#ifdef __cplusplus
extern "C" {
#endif

/** @brief Parser reassembly buffer capacity in bytes (must accommodate at least two maximum frames) */
#define RACEBOX_PARSER_BUFFER_SIZE      (1024)

/**
 * @brief Parser return status and error codes.
 */
typedef enum {
    RACEBOX_OK                      =  0,   /**< Operation succeeded */
    RACEBOX_ERR_INVALID_ARG         = -1,   /**< Null pointer or invalid parameter passed */
    RACEBOX_ERR_OVERFLOW            = -2    /**< Buffer overflow */
} racebox_err_t;

/**
 * @brief Callback signature invoked upon successful reception and validation of a telemetry packet.
 *
 * @param[in] pvt Pointer to canonical unpacked telemetry structure.
 * @param[in] user_data Context pointer registered during parser initialization.
 */
typedef void (*racebox_pvt_callback_t)(const racebox_pvt_t *pvt, void *user_data);

/**
 * @brief Statistics counters for stream health and diagnostic monitoring.
 */
typedef struct {
    uint32_t frames_received;           /**< Total number of valid frames successfully decoded */
    uint32_t frames_checksum_error;     /**< Total number of frames dropped due to checksum mismatch */
    uint32_t frames_oversized_dropped;  /**< Total number of frames dropped due to excessive length */
    uint32_t bytes_ingested;            /**< Total raw stream bytes processed by parser */
} racebox_parser_stats_t;

/**
 * @brief Parser instance context.
 *
 * Maintains stream state and a statically allocated reassembly buffer sized to RACEBOX_PARSER_BUFFER_SIZE.
 */
typedef struct {
    uint8_t  buffer[RACEBOX_PARSER_BUFFER_SIZE]; /**< Statically allocated reassembly buffer */
    size_t   buf_len;                            /**< Current number of unparsed bytes in buffer */

    racebox_pvt_callback_t callback;             /**< Registered frame completion callback */
    void *user_data;                              /**< User context passed to callback */

    racebox_parser_stats_t stats;                 /**< Parser diagnostic metrics */
} racebox_parser_t;

/**
 * @brief Initialize a parser instance context.
 *
 * @param[out] parser Pointer to caller-allocated parser structure.
 * @param[in]  callback Function pointer to invoke when a valid frame is assembled (can be NULL).
 * @param[in]  user_data Optional user pointer passed to callback (Default: NULL).
 * @return RACEBOX_OK on success, or RACEBOX_ERR_INVALID_ARG if parser is NULL.
 */
racebox_err_t racebox_parser_init(racebox_parser_t *parser,
                                  racebox_pvt_callback_t callback,
                                  void *user_data);

/**
 * @brief Feed a chunk of raw stream bytes into the parser.
 *
 * Can be called repeatedly with arbitrary chunk sizes (e.g., individual BLE notifications).
 * If valid packets are identified and validated, registered callbacks are executed synchronously.
 *
 * @param[in,out] parser Pointer to initialized parser context.
 * @param[in]     data Pointer to incoming buffer of bytes.
 * @param[in]     len Number of bytes in incoming buffer.
 * @return RACEBOX_OK on success, or RACEBOX_ERR_INVALID_ARG if parser or data is NULL.
 */
racebox_err_t racebox_parser_feed(racebox_parser_t *parser,
                                  const uint8_t *data,
                                  size_t len);

/**
 * @brief Reset parser state and empty the reassembly buffer (e.g. on BLE disconnect).
 *
 * Preserves diagnostic statistics and registered callbacks.
 *
 * @param[in,out] parser Pointer to parser context.
 * @return RACEBOX_OK on success, or RACEBOX_ERR_INVALID_ARG if parser is NULL.
 */
racebox_err_t racebox_parser_reset(racebox_parser_t *parser);

/**
 * @brief Unpack an 80-byte raw wire struct into a canonical scaled telemetry struct.
 *
 * Converts scaled integers into standard units (degrees, km/h, g, deg/s, meters).
 *
 * @param[in]  wire Pointer to 80-byte packed wire buffer.
 * @param[out] out_pvt Pointer to caller-allocated canonical output struct.
 */
void racebox_unpack_pvt(const racebox_wire_pvt_t *wire, racebox_pvt_t *out_pvt);

#ifdef __cplusplus
}
#endif
