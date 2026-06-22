#!/bin/sh
# Watch bl_power and restore brightness when display unblanks.
# The DRM driver resets brightness to ~255 on resume; this script
# waits for bl_power to return to 0 (unblank) then sets 2000.

BRIGHTNESS=2000
BACKLIGHT=/sys/class/backlight/panel0-backlight
BL_POWER="$BACKLIGHT/bl_power"
BL_BRIGHT="$BACKLIGHT/brightness"

while true; do
	# Wait for bl_power to change
	prev=$(cat "$BL_POWER" 2>/dev/null)
	while [ "$(cat "$BL_POWER" 2>/dev/null)" = "$prev" ]; do
		sleep 0.5
	done
	# If unblanked (bl_power=0), restore brightness
	if [ "$(cat "$BL_POWER" 2>/dev/null)" = "0" ]; then
		sleep 1
		echo "$BRIGHTNESS" > "$BL_BRIGHT" 2>/dev/null
	fi
done
