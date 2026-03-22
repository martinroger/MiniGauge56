#pragma once

#ifndef LOGGING_H
#define LOGGING_H

#include <stdint.h>
#include <stdbool.h>

// LVGL-accessible variables
extern char current_log_filename[64];
extern uint32_t current_file_size;
extern uint32_t current_buffered_bytes;
extern bool is_logging;

// Public API
bool init_can_logging(); // Combined TWAI and Ringbuffer init
void start_logging();
void stop_logging();

void start_logging_test();

#endif