#include <stdio.h>
#include <time.h>
#include <sys/time.h>
#include "esp32_s3_touch_amoled_1_75.h"
#include "ui.h"
#include "esp_log.h"
#include "logging.h"
#include "twai_daemon.h"
// #include "binocan.h"
#include "bmwp2000.h"
#include "lcd_emulator.h"
#include "math.h"

/**
 * @file main.cpp
 * @brief Application entry point and UI/hardware coordination for MiniGauge56.
 *
 * Coordinates AMOLED display management, touch events, SD card mounting,
 * modern TWAI CAN daemon lifecycle, BMWP2000 diagnostic telemetry daemon
 * (BMW-FAST-over-CAN), and real-time telemetry display updates.
 */

/** @brief Global LVGL display object pointer */
lv_display_t *main_display = NULL;

#pragma region Cached daemon containers

/** @brief Handle of the update_display task, woken by task notification on fresh telemetry */
static TaskHandle_t s_update_display_task = NULL;

/** @brief Minimum interval between update_display wake-ups requested by the telemetry callback (microseconds) */
#define UI_NOTIFY_MIN_INTERVAL_US 50000

/** @brief Fallback refresh period of update_display when no telemetry notification arrives */
#define UI_REFRESH_TIMEOUT_MS 100

/** @brief Counter of valid decoded BMWP2000 LID telemetry frames */
static uint32_t s_bmwp_frame_count = 0;

/** @brief Timestamp of last received BMWP2000 telemetry frame (esp_timer_get_time in microseconds) */
static int64_t s_bmwp_last_frame_us = 0;

/** @brief Cached engine RPM decoded from BMWP2000 telemetry */
static double s_bmwp_cached_rpm = 0.0;

/** @brief Cached oil temperature (degC) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_oil_temp = 0.0;

/** @brief Cached engine coolant temperature (degC) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_engine_temp = 0.0;

/** @brief Cached high-pressure fuel pump pressure (Bar) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_hpfp = 0.0;

/** @brief Cached vehicle speed (km/h) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_vehicle_speed = 0.0;

// Not part of the active LID (config/lids.json), re-enable when added back to the LID
// /** @brief Cached mass air flow (kg/h) decoded from BMWP2000 telemetry */
// static double s_bmwp_cached_maf = 0.0;

// /** @brief Cached intake air temperature (degC) decoded from BMWP2000 telemetry */
// static double s_bmwp_cached_iat = 0.0;

/** @brief Cached pre-throttle charge pressure (hPa) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_throttle_pressure = 0.0;

/** @brief Cached intake manifold boost pressure 1 (hPa) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_manifold_pressure_boost1 = 0.0;

/** @brief Cached engine oil temperature (degC) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_engine_oil_temp = 0.0;

/** @brief Cached actual oil pressure (hPa) decoded from BMWP2000 telemetry */
static double s_bmwp_cached_oil_pressure_actual = 0.0;

/** @brief Cached engine coolant temperature (degC) from the coolantTemp CID decoded from BMWP2000 telemetry */
static double s_bmwp_cached_coolant_temp = 0.0;

// Not part of the active LID (config/lids.json), re-enable when added back to the LID
// /** @brief Cached actual gear decoded from BMWP2000 telemetry */
// static double s_bmwp_cached_gear_actual = 0.0;

#pragma endregion

#pragma region Arc value mapping

/** @brief Full-scale value of every gauge arc (lv_arc_set_range(0, UI_ARC_FULL_SCALE) in the EEZ project) */
#define UI_ARC_FULL_SCALE 1000

/** @brief Engine / coolant temperature arc span (degC) */
#define UI_ARC_COOLANT_MIN 50.0
#define UI_ARC_COOLANT_MAX 130.0

/** @brief Oil temperature arc span (degC), shared by oilTemp and engineOilTemp */
#define UI_ARC_OIL_TEMP_MIN 50.0
#define UI_ARC_OIL_TEMP_MAX 150.0

/** @brief Oil pressure arc span (hPa) */
#define UI_ARC_OIL_PRESSURE_MIN 0.0
#define UI_ARC_OIL_PRESSURE_MAX 6000.0

/** @brief Absolute charge pressure arc span (hPa), shared by manifold and pre-throttle pressure */
#define UI_ARC_BOOST_MIN 500.0
#define UI_ARC_BOOST_MAX 2500.0

/**
 * @brief Linearly maps a physical value onto the 0..UI_ARC_FULL_SCALE arc range.
 *
 * @param[in] value Physical value to map.
 * @param[in] min Value drawn as an empty arc.
 * @param[in] max Value drawn as a full arc.
 * @return Arc value clamped to 0..UI_ARC_FULL_SCALE (0 if max <= min).
 */
static int32_t ui_arc_value(double value, double min, double max)
{
	if (max <= min)
	{
		return 0;
	}
	double ratio = (value - min) / (max - min);
	if (ratio < 0.0)
	{
		ratio = 0.0;
	}
	else if (ratio > 1.0)
	{
		ratio = 1.0;
	}
	return (int32_t)lround(ratio * UI_ARC_FULL_SCALE);
}

#pragma endregion

/**
 * @brief Callback triggered when a fresh BMWP2000 LID packet is parsed.
 *
 * Silently updates internal cached telemetry metrics for subsequent UI / status retrieval.
 *
 * @param[in] user_ctx User context pointer passed during callback registration (unused).
 * @note Thread-safety: Executed in the context of bmwp_daemon_task.
 */
static void on_bmwp_telemetry_updated(void *user_ctx)
{
	(void)user_ctx;
	s_bmwp_frame_count++;
	int64_t now_us = esp_timer_get_time();
	int64_t last_notify_us = s_bmwp_last_frame_us;
	s_bmwp_last_frame_us = now_us;

	bmwp2000_get_cid_value("rpm", &s_bmwp_cached_rpm);
	bmwp2000_get_cid_value("oilTemp", &s_bmwp_cached_oil_temp);
	bmwp2000_get_cid_value("engineTemp", &s_bmwp_cached_engine_temp);
	bmwp2000_get_cid_value("hpfpPressure", &s_bmwp_cached_hpfp);
	bmwp2000_get_cid_value("vehicleSpeed", &s_bmwp_cached_vehicle_speed);
	// bmwp2000_get_cid_value("maf", &s_bmwp_cached_maf);
	// bmwp2000_get_cid_value("iat", &s_bmwp_cached_iat);
	bmwp2000_get_cid_value("throttlePressure", &s_bmwp_cached_throttle_pressure);
	bmwp2000_get_cid_value("manifoldPressureBoost1", &s_bmwp_cached_manifold_pressure_boost1);
	bmwp2000_get_cid_value("engineOilTemp", &s_bmwp_cached_engine_oil_temp);
	bmwp2000_get_cid_value("oilPressureActual", &s_bmwp_cached_oil_pressure_actual);
	bmwp2000_get_cid_value("coolantTemp", &s_bmwp_cached_coolant_temp);
	// bmwp2000_get_cid_value("gearActual", &s_bmwp_cached_gear_actual);

	// Wake the UI task, throttled so LVGL is not redrawn at the raw LID frame rate
	if (s_update_display_task && (now_us - last_notify_us) >= UI_NOTIFY_MIN_INTERVAL_US)
	{
		xTaskNotifyGive(s_update_display_task);
	}
}

/** @brief Pause on the fully loaded Loading screen before switching to the main screen (milliseconds) */
#define LOADING_SCREEN_HOLD_MS 1000

/**
 * @brief LVGL timer callback that switches from the Loading screen to the main screen.
 *
 * @param[in] timer LVGL timer (one-shot, deleted automatically by LVGL after the single run).
 * @note Thread-safety: Executed in the LVGL task context, display lock already held.
 */
static void show_main_screen_cb(lv_timer_t *timer)
{
	(void)timer;
	loadScreen(SCREEN_ID_MAIN);
}

/**
 * @brief Callback triggered while BMWP2000 loads its CID and LID dictionaries.
 *
 * Pushes a progress line to the serial output and reveals one loading arc per completed 25%
 * (load_0_25 at >=25%, load_25_50 at >=50%, load_50_75 at >=75%, load_75_100 at 100%).
 * Once loading is done, switches to the main screen after a LOADING_SCREEN_HOLD_MS pause.
 *
 * @param[in] progress Snapshot of the loading progress (valid only during the call).
 * @param[in] user_ctx User context pointer passed during callback registration (unused).
 * @note Thread-safety: Executed synchronously in the context of the task calling bmwp2000_init().
 */
static void on_bmwp_load_progress(const bmwp2000_load_progress_t *progress, void *user_ctx)
{
	(void)user_ctx;
	static const char *const phase_names[] = {"IDLE", "PARSING_CIDS", "PARSING_LIDS", "LOADING_CIDS", "LOADING_LIDS", "DONE", "FAILED"};
	const char *phase_name = progress->phase <= BMWP2000_LOAD_FAILED ? phase_names[progress->phase] : "?";
	ESP_LOGI("BMWP_LOAD", "%s %u%% | CIDs %lu/%lu | LIDs %lu/%lu", phase_name, progress->percent,
			 (unsigned long)progress->cids_loaded, (unsigned long)progress->cids_total,
			 (unsigned long)progress->lids_loaded, (unsigned long)progress->lids_total);

	if (bsp_display_lock(100) == ESP_OK)
	{
		if (progress->percent >= 25)
		{
			lv_obj_remove_flag(objects.load_0_25, LV_OBJ_FLAG_HIDDEN);
		}
		if (progress->percent >= 50)
		{
			lv_obj_remove_flag(objects.load_25_50, LV_OBJ_FLAG_HIDDEN);
		}
		if (progress->percent >= 75)
		{
			lv_obj_remove_flag(objects.load_50_75, LV_OBJ_FLAG_HIDDEN);
		}
		if (progress->percent >= 100)
		{
			lv_obj_remove_flag(objects.load_75_100, LV_OBJ_FLAG_HIDDEN);
		}
		if (progress->phase == BMWP2000_LOAD_DONE)
		{
			// Hold the completed loading screen for LOADING_SCREEN_HOLD_MS, then fade to the main screen
			lv_timer_t *timer = lv_timer_create(show_main_screen_cb, LOADING_SCREEN_HOLD_MS, NULL);
			lv_timer_set_repeat_count(timer, 1);
		}
		bsp_display_unlock();
	}
}

/** @brief Flag indicating whether the AMOLED display backlight is asleep/off */
bool display_off = false;

/** @brief Active-state display brightness (percent), set by the brightness slider and used when waking the display */
static int s_brightness_percent = 60;

/** @brief Lowest brightness reachable from the slider, so the display can never be turned fully black by touch */
#define MIN_BRIGHTNESS_PERCENT 5

/** @brief Always-on backlight mode (inactivity sleep disabled); enabled by default at boot */
bool backlight_override = true;

/** @brief Software timer handle for display inactivity sleep timeout */
static TimerHandle_t sleepDisplayTimer = NULL;

/**
 * @brief Top-level CAN frame router registered with twai_daemon.
 *
 * Dispatches incoming frames from the TWAI RX worker task to all registered consumers
 * (such as CAN SD logging and future gauge/display decoders).
 *
 * @param[in] rx_frame Pointer to received TWAI frame descriptor.
 * @return esp_err_t ESP_OK on successful dispatch handling.
 * @note Thread-safety: Executed in the context of twai_daemon's CAN_RX_Task (Core 1).
 */
static esp_err_t app_can_frame_router(const twai_frame_t *rx_frame)
{
	log_can_frame_handler(rx_frame);
	bmwp2000_feed_can_frame(rx_frame);
	// Future gauge decoders (RPM, speed, sensors) hook in here
	// switch (rx_frame->header.id)
	// {

	// default:
	//     break;
	// }
	return ESP_OK;
}

#pragma region Display sleep management
/**
 * @brief Wakes up the display backlight and resets the inactivity timer.
 *
 * @note Thread-safety: Thread-safe; acquires BSP display lock with WAKE_DISPLAY_LOCK_TIMEOUT_MS timeout.
 * @note Side effects: Powers on display backlight and resets sleepDisplayTimer.
 */
/** @brief Lock timeout for waking the display; the boot-time first-frame render can hold the LVGL lock for >100 ms */
#define WAKE_DISPLAY_LOCK_TIMEOUT_MS 500

void wakeDisplay(void)
{
	if (display_off)
	{
		if (bsp_display_lock(WAKE_DISPLAY_LOCK_TIMEOUT_MS) == ESP_OK)
		{
			// bsp_display_backlight_on();
			bsp_display_brightness_set(s_brightness_percent);
			display_off = false;
			bsp_display_unlock();
		}
	}
	else // If the display is on already
	{
		if (bsp_display_lock(WAKE_DISPLAY_LOCK_TIMEOUT_MS) == ESP_OK)
		{
			// backlight_override ? bsp_display_brightness_set(50) : bsp_display_backlight_on();
			// bsp_display_backlight_on();
			bsp_display_brightness_set(s_brightness_percent);
			bsp_display_unlock();
		}
	}
	// Manage timer
	if (!backlight_override)
	{
		xTimerReset(sleepDisplayTimer, pdMS_TO_TICKS(100));
	}
	else
	{
		xTimerStop(sleepDisplayTimer, pdMS_TO_TICKS(100));
	}
}

/**
 * @brief Puts the display backlight to sleep to conserve power.
 *
 * @note Thread-safety: Thread-safe; acquires BSP display lock with 100 ms timeout.
 * @note Side effects: Turns off display backlight and marks display_off true.
 */
void sleepDisplay(void)
{
	if (!display_off)
	{
		if (bsp_display_lock(100) == ESP_OK)
		{
			bsp_display_backlight_off();
			display_off = true;
			bsp_display_unlock();
		}
	}
}

/**
 * @brief FreeRTOS software timer callback triggered upon display inactivity timeout.
 *
 * @param[in] xTimer Handle of the expired FreeRTOS software timer.
 */
static void sleepDisplayTimer_cb(TimerHandle_t xTimer)
{
	sleepDisplay();
}

#pragma endregion

#pragma region UI action callbacks
/**
 * @brief LVGL event callback triggered when the start/stop logging button is clicked.
 *
 * @param[in] e Pointer to LVGL event descriptor.
 * @note Thread-safety: Must be called from the LVGL task context.
 */
extern "C" void action_start_stop_clicked(lv_event_t *e)
{
	if (display_off)
	{
		wakeDisplay();
		return;
	}
	if (lv_obj_has_state(objects.log_sw, LV_STATE_CHECKED))
	{
		start_logging();
		if (!is_logging)
		{
			// Writer still draining a previous session, or start refused: revert the switch
			lv_obj_remove_state(objects.log_sw, LV_STATE_CHECKED);
		}
	}
	else
	{
		if (is_logging)
		{
			stop_logging();
		}
	}
	wakeDisplay();
}

/**
 * @brief Global touch press event callback to wake display upon any user interaction.
 *
 * @param[in] e Pointer to LVGL event descriptor.
 */
extern "C" void action_global_pressed(lv_event_t *e)
{
	wakeDisplay();
}

/**
 * @brief LVGL event callback triggered when the backlight override switch is turned on.
 *
 * Forces the display to remain always on (full brightness) and cancels inactivity sleep timer.
 *
 * @param[in] e Pointer to LVGL event descriptor.
 * @note Thread-safety: Must be called from the LVGL task context.
 */
extern "C" void action_backlight_sw_checked(lv_event_t *e)
{
	backlight_override = true;
	wakeDisplay();
}

/**
 * @brief LVGL event callback triggered when the backlight override switch is turned off.
 *
 * Restores automatic display power management (100% active brightness with inactivity sleep timeout).
 *
 * @param[in] e Pointer to LVGL event descriptor.
 * @note Thread-safety: Must be called from the LVGL task context.
 */
extern "C" void action_backlight_sw_unchecked(lv_event_t *e)
{
	backlight_override = false;
	wakeDisplay(); // For good measure to restart the sleep timer
}

/**
 * @brief LVGL event callback triggered when the brightness slider value changes.
 *
 * Applies the slider value (clamped to MIN_BRIGHTNESS_PERCENT..100) to the panel brightness.
 *
 * @param[in] e Pointer to LVGL event descriptor.
 * @note Thread-safety: Takes the BSP display lock (recursive, so safe from the LVGL task context).
 */
static void on_brightness_slider_changed(lv_event_t *e)
{
	int32_t value = lv_slider_get_value(lv_event_get_target_obj(e));
	if (value < MIN_BRIGHTNESS_PERCENT)
	{
		value = MIN_BRIGHTNESS_PERCENT;
	}
	if (bsp_display_lock(WAKE_DISPLAY_LOCK_TIMEOUT_MS) == ESP_OK)
	{
		s_brightness_percent = value;
		bsp_display_brightness_set(s_brightness_percent);
		bsp_display_unlock();
	}
}

extern "C" void action_filter_sw_actuated(lv_event_t *e)
{
	if (lv_obj_has_state(objects.filter_sw, LV_STATE_CHECKED))
	{
		// Turn off emulation
		lcd_emulator_set_enabled(false);
	}
	else
	{
		// Turn on emulation
		lcd_emulator_set_enabled(true);
	}
}

#pragma endregion

/**
 * @brief FreeRTOS UI update task that refreshes LVGL telemetry labels periodically.
 *
 * @param[in] pvParameters Task parameters passed by FreeRTOS (unused).
 * @note Thread-safety: Locks LVGL display mutex before modifying UI widgets.
 */
void update_display(void *pvParameters)
{
	while (1)
	{
		uint32_t tabID = lv_tabview_get_tab_active(objects.global_tabview);
		if (bsp_display_lock(100) == ESP_OK)
		{

			// Selective tab update
			switch (tabID)
			{
			case 0: // Engine temp
					lv_label_set_text_fmt(objects.engine_temp, "%.1f", s_bmwp_cached_engine_temp);
					lv_arc_set_value(objects.engine_temp_arc, ui_arc_value(s_bmwp_cached_engine_temp, UI_ARC_COOLANT_MIN, UI_ARC_COOLANT_MAX));
					break;

			case 1: // Oil temp
					lv_label_set_text_fmt(objects.oil_temp, "%.1f", s_bmwp_cached_oil_temp);
					lv_arc_set_value(objects.oil_temp_arc, ui_arc_value(s_bmwp_cached_oil_temp, UI_ARC_OIL_TEMP_MIN, UI_ARC_OIL_TEMP_MAX));
					break;

			case 2: // Oil pressure
					lv_label_set_text_fmt(objects.oil_pressure, "%.0f", s_bmwp_cached_oil_pressure_actual);
					lv_arc_set_value(objects.oil_pressure_arc, ui_arc_value(s_bmwp_cached_oil_pressure_actual, UI_ARC_OIL_PRESSURE_MIN, UI_ARC_OIL_PRESSURE_MAX));
					break;

			case 3: // Oil temp + engine oil temp
					lv_label_set_text_fmt(objects.oil_temp_2, "%.1f", s_bmwp_cached_oil_temp);
					lv_arc_set_value(objects.oil_temp_arc_2, ui_arc_value(s_bmwp_cached_oil_temp, UI_ARC_OIL_TEMP_MIN, UI_ARC_OIL_TEMP_MAX));
					lv_label_set_text_fmt(objects.engine_oil_temp, "%.1f", s_bmwp_cached_engine_oil_temp);
					lv_arc_set_value(objects.engine_oil_temp_arc, ui_arc_value(s_bmwp_cached_engine_oil_temp, UI_ARC_OIL_TEMP_MIN, UI_ARC_OIL_TEMP_MAX));
					break;

			case 4: // Engine temp + coolant temp
					lv_label_set_text_fmt(objects.engine_temp_2, "%.1f", s_bmwp_cached_engine_temp);
					lv_arc_set_value(objects.engine_temp_arc_2, ui_arc_value(s_bmwp_cached_engine_temp, UI_ARC_COOLANT_MIN, UI_ARC_COOLANT_MAX));
					lv_label_set_text_fmt(objects.coolant_temp, "%.1f", s_bmwp_cached_coolant_temp);
					lv_arc_set_value(objects.coolant_temp_arc, ui_arc_value(s_bmwp_cached_coolant_temp, UI_ARC_COOLANT_MIN, UI_ARC_COOLANT_MAX));
					break;

			case 5: // Manifold + pre-throttle pressure
					lv_label_set_text_fmt(objects.manifold_pressure, "%.0f", s_bmwp_cached_manifold_pressure_boost1);
					lv_arc_set_value(objects.manifold_pressure_arc, ui_arc_value(s_bmwp_cached_manifold_pressure_boost1, UI_ARC_BOOST_MIN, UI_ARC_BOOST_MAX));
					lv_label_set_text_fmt(objects.throttle_pressure, "%.0f", s_bmwp_cached_throttle_pressure);
					lv_arc_set_value(objects.throttle_pressure_arc, ui_arc_value(s_bmwp_cached_throttle_pressure, UI_ARC_BOOST_MIN, UI_ARC_BOOST_MAX));
					break;

			case 6: // BM Daemon
					lv_label_set_text_fmt(objects.bmw_engine_temp, "%.1f", s_bmwp_cached_engine_temp);
					lv_label_set_text_fmt(objects.bmw_frames_count, "%lu", s_bmwp_frame_count);
					lv_label_set_text_fmt(objects.bmw_hpfp, "%.1f", s_bmwp_cached_hpfp);
					lv_label_set_text_fmt(objects.bmw_oil_temp, "%.1f", s_bmwp_cached_oil_temp);
					lv_label_set_text_fmt(objects.bmw_rpm, "%lu", lround(s_bmwp_cached_rpm));
					lv_label_set_text_fmt(objects.bmw_throttle_pressure, "%.0f", s_bmwp_cached_throttle_pressure);
					lv_label_set_text_fmt(objects.bmw_manifold_boost, "%.0f", s_bmwp_cached_manifold_pressure_boost1);
					lv_label_set_text_fmt(objects.bmw_engine_oil_temp, "%.1f", s_bmwp_cached_engine_oil_temp);
					lv_label_set_text_fmt(objects.bmw_engine_oil_pressure, "%.0f", s_bmwp_cached_oil_pressure_actual);
					lv_label_set_text_fmt(objects.bmw_coolant_temp, "%.1f", s_bmwp_cached_coolant_temp);
				switch (bmwp2000_get_state())
				{
				case BMWP2000_STATE_BACKOFF_WAIT:
					lv_label_set_text(objects.bmw_state, "WAIT");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;
				case BMWP2000_STATE_SETUP_LID:
					lv_label_set_text(objects.bmw_state, "SETUP");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;

				case BMWP2000_STATE_RUNNING:
					lv_label_set_text(objects.bmw_state, "RUNNING");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;

				case BMWP2000_STATE_CLEAR_LID:
					lv_label_set_text(objects.bmw_state, "CLEARING");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_ALT);
					break;

				case BMWP2000_STATE_READ_REQ:
					lv_label_set_text(objects.bmw_state, "REQUEST");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;
				case BMWP2000_STATE_RESPONSE_PENDING:
					lv_label_set_text(objects.bmw_state, "PENDING");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;
				case BMWP2000_STATE_RX_WAIT_CF:
					lv_label_set_text(objects.bmw_state, "WAIT CF");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;
				case BMWP2000_STATE_TX_WAIT_FC:
					lv_label_set_text(objects.bmw_state, "WAIT FC");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;
				case BMWP2000_STATE_UNINIT:
					lv_label_set_text(objects.bmw_state, "UNINIT");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_ALT);
					break;
				default:
					lv_label_set_text(objects.bmw_state, "BMWP2000");
					lcd_emulator_select_palette_slot(LCD_PALETTE_SLOT_PRIMARY);
					break;
				}
				break;

			case 7: // Logger

				break;

			default:
				break;
			}

			// Update in any case
			// Revert the switch if the writer aborted (e.g. file open failure)
			if (!is_logging && lv_obj_has_state(objects.log_sw, LV_STATE_CHECKED))
			{
				lv_obj_remove_state(objects.log_sw, LV_STATE_CHECKED);
			}
			uint32_t displayed_size = current_file_size + current_buffered_bytes;
			if (displayed_size > 1024 * 1024)
			{
				lv_label_set_text_fmt(objects.current_file_size, "%.1f MB", (float)displayed_size / (1024.0 * 1024.0));
			}
			else
			{
				lv_label_set_text_fmt(objects.current_file_size, "%lu kB", displayed_size / 1024);
			}
			lv_label_set_text_fmt(objects.status, "%s", is_logging ? "LOGGING" : "PAUSED");

			bsp_display_unlock();
		}
		// Sleep until fresh telemetry notifies us, or refresh anyway after the timeout
		ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(UI_REFRESH_TIMEOUT_MS));
	}
}

/**
 * @brief Application main entry point.
 *
 * Initializes display power management timer, mounts SD card, allocates PSRAM
 * logging buffers, initializes the modern twai_daemon controller, and launches UI.
 */
extern "C" void app_main(void)
{
	sleepDisplayTimer = xTimerCreate("slp_disp", pdMS_TO_TICKS(10000), pdFALSE, NULL, sleepDisplayTimer_cb);

	// SD CARD check
	if (bsp_sdcard_mount() != ESP_OK)
	{
		ESP_LOGW(__func__, "Could not mount SD CARD");
	}
	else
	{
		ESP_LOGI(__func__, "SD card mounted at %s", BSP_SD_MOUNT_POINT);
		if (init_can_logging())
		{
			ESP_LOGI(__func__, "CAN logger ringbuffer ready");
		}
		else
		{
			ESP_LOGE(__func__, "Could not allocate CAN logger ringbuffer");
		}
	}

	// Initialize modern TWAI driver and route frames through app_can_frame_router
	if (initCAN(app_can_frame_router) == ESP_OK)
	{
		ESP_LOGI(__func__, "TWAI modern driver initialized successfully");
	}
	else
	{
		ESP_LOGE(__func__, "Failed to initialize TWAI modern driver");
	}

	// Display init
	main_display = bsp_display_start();
	if (main_display)
	{
		if (bsp_display_lock(-1) == ESP_OK)
		{
			if (lcd_emulator_init(main_display) == ESP_OK)
			{
				ESP_LOGI(__func__, "Retro LCD flush decorator attached successfully");
			}
			ui_init();
			// Reflect the default always-on backlight mode on the switch
			if (objects.backlight_sw)
			{
				if (backlight_override)
				{
					lv_obj_add_state(objects.backlight_sw, LV_STATE_CHECKED);
				}
				else
				{
					lv_obj_remove_state(objects.backlight_sw, LV_STATE_CHECKED);
				}
			}
			if (objects.filter_sw)
			{
				if (lcd_emulator_is_enabled())
				{
					lv_obj_remove_state(objects.filter_sw, LV_STATE_CHECKED);
				}
				else
				{
					lv_obj_add_state(objects.filter_sw, LV_STATE_CHECKED);
				}
			}
			if (objects.brightness_slider)
			{
				lv_slider_set_range(objects.brightness_slider, MIN_BRIGHTNESS_PERCENT, 100);
				lv_slider_set_value(objects.brightness_slider, s_brightness_percent, LV_ANIM_OFF);
				lv_obj_add_event_cb(objects.brightness_slider, on_brightness_slider_changed, LV_EVENT_VALUE_CHANGED, NULL);
			}
			bsp_display_unlock();
		}
		else
		{
			ESP_LOGE(__func__, "Could not catch mutex for LVGL, aborting");
			return;
		}
	}
	wakeDisplay();

	// Initialize BMWP2000 Diagnostic Daemon (ISO 14230-3 / ISO 15765-2)

	bmwp2000_register_load_progress_callback(on_bmwp_load_progress, NULL);

	if (bmwp2000_init() == ESP_OK)
	{
		ESP_LOGI(__func__, "BMWP2000 diagnostic engine initialized successfully");
		bmwp2000_register_callback(on_bmwp_telemetry_updated, NULL);
		if (bmwp2000_start() == ESP_OK)
		{
			ESP_LOGI(__func__, "BMWP2000 background daemon task started");
		}
		else
		{
			ESP_LOGE(__func__, "Failed to start BMWP2000 background daemon task");
		}
	}
	else
	{
		ESP_LOGE(__func__, "Failed to initialize BMWP2000 diagnostic engine");
	}

	xTaskCreate(update_display, "upd_disp", 4096, NULL, 3, &s_update_display_task);
	while (true)
	{
		vTaskDelay(pdMS_TO_TICKS(1000));
		// ESP_LOGD("STATUS", "File: %s | Size: %lu kB | Buffered: %lu B",
		//          current_log_filename, current_file_size / 1024, current_buffered_bytes);
		// ESP_LOGD("BMWP_STATUS", "Frames: %lu | RPM: %.0f | Oil: %.1f degC | Coolant: %.1f degC | HPFP: %.1f Bar",
		//          (unsigned long)s_bmwp_frame_count, s_bmwp_cached_rpm, s_bmwp_cached_oil_temp, s_bmwp_cached_engine_temp, s_bmwp_cached_hpfp);
	}
}
