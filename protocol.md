# HAF 700 EVO Iris protocol notes

Last updated: 2026-10-02

This document is the standalone wire-protocol reference derived from the stock Android APK, passive/live-device inspection, captured MasterPlus state, and physically observed tests. It describes the current consolidated understanding.

## Scope and confidence labels

- **Source confirmed** means the behavior is visible in the decompiled APK and/or smali.
- **Transport confirmed** means the real device accepted the bytes through TCP.
- **Physically confirmed** means the user observed the expected result on the LCD.
- **Unresolved** means a plausible field or behavior still lacks enough evidence.

The fixed investigated unit has ADB serial `1234567890ABCDEF`. The unrelated Android serial `R52N201MZPD` is outside this project's scope.

## Transport

The stock `com.magic.box` application listens on TCP port `9900` using OkSocket. It was observed bound as UID 1000 on `:::9900`. The original MasterPlus arrangement used an ADB forward from host port `8888` to device port `9900`. The replacement GUI uses host port `18888` to avoid colliding with that mapping:

```text
localhost:18888 -> 1234567890ABCDEF:9900
```

There is no protocol authentication. The service must not be exposed on an untrusted network. Some commands can alter time, delete files, or write media even though this project does not use those paths.

### Connection lifetime

This is operationally important:

- Persistent/manual command `0x12` uses a one-shot TCP connection and waits for an exact ACK.
- Live response command `0x15` does not return the same ACK and must not wait for one.
- Consecutive `0x15` updates should reuse one TCP connection.

Opening a new TCP connection for every live frame caused missed physical presentations even though sends completed and the Android state eventually matched. A five-value test over one persistent connection sent 1.11, 2.22, 3.33, 4.44, and 5.55 GHz; `currentType`, the Android UI tree, and the physical LCD all matched all five. The GUI therefore keeps one live socket until Stop, disconnect, reboot, reconnect, application exit, socket failure, or an ACK-bearing command requires an isolated transaction.

## General frame

Every instruction starts with a six-byte header:

| Absolute offset | Size | Meaning |
| ---: | ---: | --- |
| 0 | 1 | Command byte |
| 1 | 3 | Sync/direction sequence, confirmed as `80 00 01` for the display frames used here |
| 4 | 2 | Body length, big-endian; parsed by Java as a signed `short` |
| 6 | N | Command-specific body |

For the confirmed numeric-display frames, body length is 24 bytes (`00 18`) and total frame length is 30 bytes.

Compact notation:

```text
[command:1] [80 00 01] [body_length_be:2] [body:N]
```

Lengths above 32767 are unsafe because the stock application treats the field as a signed Java `short`.

## Numeric LCD mode body

`LcdModeInstruction` parses the body as follows:

| Body offset | Absolute offset | Size | Meaning |
| ---: | ---: | ---: | --- |
| 0 | 6 | 1 | LCD mode ID |
| 1 | 7 | 2 | Current numeric value, big-endian; negative temperatures work as signed two's complement |
| 3 | 9 | 2 | Style/ring lower threshold, big-endian |
| 5 | 11 | 2 | Style/ring upper threshold, big-endian |
| 7 | 13 | 1 | Text/logo scroll setting |
| 8 | 14 | 3 | Present but unused by the recovered parser |
| 11 | 17 | 1 | `roundSpeed`; any nonzero value behaves as a boolean override |
| 12 | 18 | 4 | Text color, big-endian ARGB |
| 16 | 22 | 1 | Text byte length |
| 17 | 23 | variable | Text bytes |
| next | variable | 1 | Background state/type |
| next | variable | 4 | Background color, big-endian ARGB |
| next | variable | 1 | Image filename length |
| next | variable | variable | Image filename |
| next | variable | 1 | Media filename length |
| next | variable | variable | Media filename |

The replacement app's normal 24-byte body uses:

```text
[mode]
[value_be:2]
[lower_be:2]
[upper_be:2]
[00 00 00 00 00]
[FF FF FF FF]       # white text
[00]                # zero text bytes
[03]                # black/background renderer state
[FF 00 00 00]       # black ARGB
[00]                # empty image name
[00]                # empty media name
```

The earlier theory that `03` was a text length was wrong. Source parsing and byte enumeration confirm it is the background state following a zero-length text field.

## Display commands

### `0x12` — `LED_CAROUSEL`

- Applies a complete LCD mode record.
- Persists the record in the stock application.
- Returns the exact confirmed ACK `12 80 00 01 00 00`.
- The replacement app requires the ACK to match exactly before reporting success.

### `0x15` — `RESPONSE_MODE_DATA`

- Applies the same complete LCD mode record as a live response/update.
- Does not produce the `0x12` ACK in confirmed testing.
- Must be sent without an ACK wait.
- Works best over one persistent connection.
- The stock APK still writes the accepted frame to shared-preference key `currentType`.

An early live implementation incorrectly waited three seconds for a `0x12`-style ACK after every `0x15`. The LCD changed, but every iteration logged `timed out`. The timeout was host logic, not device rejection.

## Numeric mode IDs

All modes exposed below have been physically confirmed to render and respond to manual value changes:

| Mode | Display meaning | Confirmed manual range used by the app | Automatic live source status |
| ---: | --- | ---: | --- |
| 1 | CPU frequency | 0–9990 MHz | Confirmed: LHM load-weighted physical-core clock |
| 2 | GPU frequency | 0–6000 MHz | Implemented: LHM GPU Core `/gpu-nvidia/0/clock/0`; physical live-cycle confirmation pending |
| 3 | CPU temperature | -20–150 °C configured; -10 and 120 °C physically shown | Confirmed: LHM CPU Package |
| 4 | GPU temperature | 0–100 °C | Implemented: LHM GPU Core `/gpu-nvidia/0/temperature/0`; physical live-cycle confirmation pending |
| 5 | CPU usage | 0–100% | Confirmed: LHM CPU Total |
| 6 | GPU usage | 0–100% | Implemented: LHM GPU Core `/gpu-nvidia/0/load/0`; physical live-cycle confirmation pending |
| 7 | RAM usage | 0–100% | Implemented: Win32 physical-memory load; physical live-cycle confirmation pending |
| 8 | CPU fan | 0–10000 RPM | Sensor mapping pending |
| 9 | Case fan 1 | 0–10000 RPM | Sensor mapping pending |
| 10 | Case fan 2 | 0–10000 RPM | Sensor mapping pending |
| 11 | Case fan 3 | 0–10000 RPM | Sensor mapping pending |
| 12 | Case fan 4 | 0–10000 RPM | Sensor mapping pending |
| 13 | Case fan 5 | 0–10000 RPM | Sensor mapping pending |
| 14 | Ping renderer | APK/source only; not exposed as a numeric metric |
| 15 | Microphone renderer | APK/source only |
| 16 | Time renderer | APK/source only |
| 17 | Media renderer | APK/source only |
| 18 | Logo renderer | APK/source only |
| 19 | APM renderer | APK/source only |

“Sensor mapping pending” does not mean the LCD mode is untested. It means the PC-side automatic source and exact LHM sensor identity have not yet been validated.

Usage modes 5–7 use a 101-frame bitmap array only for values 0–100. An out-of-range value changes the numeric text but leaves the prior dial bitmap in place. Frame index 100 also reuses the apparent frame-99 asset. Senders should clamp/reject rather than rely on the renderer.

## Confirmed example frames

### Persist CPU frequency at 4.733 GHz

```text
12 80 00 01 00 18 01 12 7D 04 4C 17 70 00 00 00 00 00 FF FF FF FF 00 03 FF 00 00 00 00 00
```

Compact hex:

```text
12800001001801127D044C17700000000000FFFFFFFF0003FF0000000000
```

Here `12 7D` is 4733 MHz, while `04 4C`/`17 70` are stock ring thresholds 1100/6000.

### Persist CPU frequency at 6.000 GHz

```text
128000010018011770044C17700000000000FFFFFFFF0003FF0000000000
```

### Persist CPU temperature at -10 °C

```text
12800001001803FFF6002800500000000000FFFFFFFF0003FF0000000000
```

`FF F6` is signed 16-bit two's-complement -10. The ring thresholds remain 40/80 °C (`00 28`/`00 50`).

### Live CPU temperature at 45 °C

```text
15800001001803002D002800500000000000FFFFFFFF0003FF0000000000
```

### Live CPU usage at 38%

```text
158000010018050026000000640000000000FFFFFFFF0003FF0000000000
```

## Value formatting in the APK

For CPU/GPU clock modes, `BaseView.setValue()` divides integer MHz by 1000 and formats it with Java `DecimalFormat("##0.00")` using half-up two-decimal rounding. A transmitted 4255 MHz therefore appears as `4.26 GHZ` in the Android UI tree.

Temperatures, percentages, and RPM modes display whole numeric values with their mode-specific labels/assets.

## Ring and animation behavior

The lower/upper fields are renderer thresholds, not validation limits. With `roundSpeed == 0`, source inspection and physical tests show three coarse animation bands:

| Current value | Approximate revolution time |
| --- | ---: |
| Below lower threshold | 4.5 seconds |
| Between thresholds | 3.5 seconds |
| Above upper threshold | 2.5 seconds |

Any nonzero `roundSpeed` bypasses threshold evaluation and forces the middle speed. Its magnitude is ignored.

Confirmed consequences:

- Temperature with 40/80 °C thresholds visibly changes between slow, medium, and fast bands.
- CPU frequency with stock 1100/6000 MHz thresholds normally remains in the middle band, so changing frequency does not produce proportional ring speed.
- Sending experimental 2000/4500 thresholds was present in the exact acknowledged frames but did not visibly produce the expected CPU-frequency band changes. That path was removed from the normal GUI.
- Modes 5–7 use bitmap gauges rather than the rotating ring behavior.

Continuous proportional ring motion cannot be produced by merely changing the numeric value in the stock renderer. It would require changing bounds dynamically in a way the renderer actually honors, or modifying/replacing the Android renderer.

## APK acceptance and feedback levels

The receive path for modes 1–13 is:

1. TCP frame is parsed as `LcdModeInstruction`.
2. The complete accepted frame is written to shared preference `magic.xml`, key `currentType`.
3. Work is posted with `runOnUiThread`.
4. The reused `BaseView` receives mode, value, style, and background setters.
5. `BaseView.setValue()` updates the active `TextView`.
6. `build()` clears the black overlay.
7. `setContentView()` installs the view again.

There is no renderer callback, draw listener, frame-present acknowledgement, getter command, or response packet containing the visible value. Evidence therefore has distinct levels:

| Evidence | What it proves |
| --- | --- |
| Host `sendall` completed | Bytes reached the local TCP stack |
| `currentType` matches | APK accepted and persisted the exact frame |
| `uiautomator` TextView matches | UI runnable updated the Android view tree |
| Human/video observation | Physical LCD presented the value |

The read-only UI-tree command is:

```powershell
adb -s 1234567890ABCDEF shell uiautomator dump /dev/tty
```

It takes roughly four seconds on this device and must not be confused with LCD refresh timing. The relevant frequency value view is `com.magic.box:id/base_view_layout_ghzValue`.

## Other recovered command IDs

These are documented for completeness, not endorsed for experimentation:

| Command | APK name | Recovered behavior |
| ---: | --- | --- |
| `10` | `LED_DIRECTION` | Sets rotation and acknowledges |
| `E0` | `RESET` / duplicated `QUERY_FILE_NAME` | No action in this build |
| `FC` | `SYNC_TIME` | Sets system time/timezone |
| `F0` | `QUERY_SPACE` | Returns external-storage geometry |
| `F1` | `QUERY_FILE_LIST` | Lists private media names |
| `F2` | `DELETE_FILE` | Deletes one/all private media files and echoes request |
| `F3` | `FILE_EXIST` | Checks a private media filename |
| `F4` | `PLAY_FILE` | No action found |
| `F5` | `JOIN_DOWNLOAD` | Creates/replaces app-private PNG/JPG/MP4 |
| `F6` | `EXIT_DOWNLOAD` | Flushes/closes transfer stream |
| `F7` | `DOWNLOAD_FILE` | Writes a chunk after four leading body bytes |
| `F8` | `LED_CONTROL` | Brightness/sleep/keep-screen-on behavior |
| `14` | `QUERY_MODE_DATA` | Starts/stops timed carousel and requests PC records |
| `16` | `SAVE_DATE` | Writes a four-character named data blob |
| `17` | `GET_DATA` | Reads a four-character named data blob |
| `18` | `SLEEP_TYPE` | Persists sleep behavior |
| `19` | `GET_VERSION` | Reads driver versions from sysfs |
| `1A` | `SET_VOLUME` | Enum exists; no handler branch found |

File commands are unsafe to probe casually. The recovered code directly concatenates received names beneath app storage without canonical-path validation, validates extension rather than content, and lacks robust length/hash checks. `QUERY_FILE_LIST` can also crash its request path when the directory is empty.

## Device reboot and recovery

Rebooting the LCD is not a port-9900 protocol command in the replacement app. The confirmed recovery control is the fixed-target ADB command:

```powershell
adb -s 1234567890ABCDEF reboot
```

Before reboot, the GUI removes only its own `tcp:18888` forward. Physical recovery from a backlight-only state was confirmed, but Android/LCD startup is unusually slow—approximately two minutes was observed in one logged GUI cycle.

## Genuine transition videos and the corrected trigger attribution

The stock APK contains `res/raw/shutdown.mp4` and `res/raw/start.mp4`, but its
Volume-key playback path is unreliable. Decompiled `MediaView` starts IJK
playback before `SplashActivity` attaches the video view. Device logs repeatedly
show `Video: first frame decoded`, then `NULL native_window`, and only afterward
surface attachment. Pausing telemetry removes competing view replacements but
does not eliminate this ordering race.

The unmodified device includes an MP4-capable system activity:

```text
com.android.gallery3d/.app.MovieActivity
```

An unchanged asset can be staged temporarily and launched without modifying
the APK or firmware:

```powershell
adb -s 1234567890ABCDEF shell mkdir -p /data/local/tmp/haf_transition_test
adb -s 1234567890ABCDEF push shutdown.mp4 /data/local/tmp/haf_transition_test/shutdown.mp4
adb -s 1234567890ABCDEF shell chmod 644 /data/local/tmp/haf_transition_test/shutdown.mp4
adb -s 1234567890ABCDEF shell am start -a android.intent.action.VIEW -d file:///data/local/tmp/haf_transition_test/shutdown.mp4 -t video/mp4 -n com.android.gallery3d/.app.MovieActivity
```

Use the corresponding path and filename for `start.mp4`. Do not use
`am start -W` as proof of playback: it can report `Status: timeout` despite
launching MovieActivity. Verify hashes, focus, decoder logs, and the physical
LCD independently.

| Asset | SHA-256 | Confirmed result |
| --- | --- | --- |
| `shutdown.mp4` | `0a812331a9a49461a4681d2410ee43b291c474dfafd59898f20274b84fc78e5c` | Genuine shutdown animation physically shown after stock Volume Down; it was not played by MovieActivity |
| `start.mp4` | `b7d154170875d1965799196202e25197a5831c2748e63380ce0a511a2acd098e` | Opens as AVC but fails in the RDA hardware decoder, leaving backlight only |

Important chronology correction for the one physically successful shutdown
playback: Gallery was launched only after the stock Volume-Down handler had
already attempted shutdown playback for 30 seconds from the CM-logo state.
That preceding attempt kept brightness at 255 and logged `NULL native_window`,
but it may have primed media or display state. The exact successful sequence
was:

```powershell
adb -s 1234567890ABCDEF shell input keyevent 25
# Wait 30 seconds, then launch shutdown.mp4 through MovieActivity.
```

The sequence was reproduced from a clean post-reboot CM-logo state. The user
observed the genuine shutdown animation immediately from the stock Volume-Down
path. The later Gallery launch then failed in OMX and left only the backlight
visible. This proves the earlier animation was misattributed to Gallery. Do not
use Gallery in the shutdown design.

The startup failure was reproduced both from a clean post-reboot CM-logo state
and immediately after a verified `Asleep -> Awake` transition. In both cases
the system player reported `OMX-VPU interrupt timeout`, `OMX_EventError`, and
`MEDIA_ERROR -2147483648`. Therefore being in the off state is not sufficient.
A possible non-APK next step is to re-encode a derived temporary copy of
`start.mp4` to codec parameters proven compatible with the working shutdown
asset, while preserving the original file and hash.

The stock reboot path is different from Gallery and does invoke the startup
asset successfully through bundled IJK/FFmpeg. A clean boot trace showed:

1. `SplashActivity.onCreate()` calls `initView()`.
2. `initView()` calls `mediaView.setVideoRaw(callback, false)`, whose recovered
   implementation always selects `R.raw.start`.
3. IJK opens and starts the 480x480 stream.
4. The first decoded frame still encounters `NULL native_window`, but the
   surface attaches about 250 ms later and playback continues.
5. `FFP_MSG_COMPLETED` arrives about 27 seconds after playback preparation.
6. The completion callback parses the persisted `currentType` and restores that
   display (mode 18 CM logo in the captured run).

Captured device timeline on 2026-10-03:

```text
01:19:23.050  IJK prepare/start for bundled start video
01:19:23.990  first frame decoded; NULL native_window
01:19:24.240  video surface attached
01:19:50.790  FFP_MSG_COMPLETED
01:19:57.260  host ADB connection returned
```

This explains why an observer connecting after reboot sees only the restored
logo: the startup video has already finished before ADB becomes available.
Gallery uses Android's older hardware OMX path instead of the APK's IJK/FFmpeg
path, which explains why the identical `start.mp4` can complete during stock
boot yet fail in Gallery with a VPU timeout.

The same successful IJK startup path can be triggered without rebooting Android
and without modifying the APK:

```powershell
adb -s 1234567890ABCDEF shell am force-stop com.magic.box
# Wait for Android HOME to recreate SplashActivity and verify port 9900 LISTEN.
# Use an explicit am start only as a fallback if the process did not return.
```

On the clean device this created a fresh `SplashActivity`, invoked `initView()`,
played the bundled `R.raw.start` through IJK for approximately 27 seconds,
emitted `FFP_MSG_COMPLETED`, and restored persisted `currentType`. The user
physically confirmed the genuine startup splash was visible. Because
`com.magic.box` is the HOME activity, so Android relaunches it immediately after
`force-stop`. A later live test proved that stacking an explicit `am start` on
top of that automatic launch can create two `SplashActivity` instances. Both
call `initSocket()`; the second port-9900 bind fails and OkSocket's catch path
calls `shutdown()`, removing the valid listener. The correct path is therefore
force-stop once, wait for automatic HOME restoration, and require port 9900 to
be listening. Explicit start is only a fallback when no stock process returns.

The currently confirmed non-APK transition strategy uses stock application
paths for both animations:

- stop telemetry/cycling, ensure the stock app is in a clean visible state,
  send Volume Down (key 25), and let its delayed IJK shutdown playback finish
  before powering the Android display off;
- on wake, restart the stock `com.magic.box` activity and let its bundled IJK
  path play the genuine startup asset to completion;
- restore the selected metric and resume telemetry only after the startup
  playback/completion window and a successful protocol readiness check.

The shutdown half has now been physically validated end to end. Starting from
the stable CM logo with telemetry stopped, send Volume Down (key 25), wait 35
seconds, and then send Android Power (key 26). In the confirmed run the stock
player began preparing the shutdown asset about six seconds after the key
event; the user saw the entire animation finish before Power, after which the
LCD and backlight were fully off and Android reported
`mWakefulness=Asleep`. Treat 35 seconds as the currently proven conservative
delay, not as the exact media duration.

The matching wake half is also physically validated. From the fully off state:

1. Send Android Power (key 26).
2. Wait three seconds and verify Android is Awake.
3. Force-stop only `com.magic.box`.
4. Start `com.magic.box/.ui.SplashActivity`.
5. Do not send display frames while the startup video is playing.

The user observed the complete genuine `start.mp4`, followed by the persisted
CM logo. This establishes the transition sequence itself; a controller must
still wait for startup completion/readiness before restoring its previous mode
and resuming telemetry.

Android `dumpsys power` `mWakefulness` matches the physically confirmed panel
power states and is suitable for control gating: internal `Awake` is displayed
as `ON` and permits OFF; `Asleep` is displayed as `OFF` and permits ON. This state does not describe
which metric or video is currently rendered.

The panel retains its last framebuffer across Android Power-off. On wake, that
retained image may flash briefly before the first `start.mp4` frame reaches the
surface. This is a confirmed cosmetic artifact, not an early telemetry send;
host TX remained paused throughout the observed flash and startup playback.

Gallery handoff can leave the panel backlight-only and the stock HOME activity
without a focused window. Stopping Gallery and restarting `SplashActivity` did
not reliably recover that state during testing. The confirmed recovery remains
the fixed-serial HAF reboot documented above.

## Current sender rules

1. Target only fixed serial `1234567890ABCDEF`.
2. Forward a dedicated localhost port to device port 9900.
3. Validate whole-number inputs before encoding.
4. Encode negative temperature values as signed 16-bit big-endian.
5. Use `0x12` plus exact ACK validation for manual/persistent changes.
6. Use `0x15` with no ACK wait for live values.
7. Reuse one live TCP connection.
8. Log the sensor input, chosen semantic, encoded value/unit, complete frame, socket lifecycle, and any error.
9. Treat successful send as expected LCD state, not physical-display proof.
10. Close the live socket on Stop, disconnect, reboot, reconnect, transport failure, or exit.

## Unresolved or deliberately deferred

- Exact automatic sensor identifiers/semantics for CPU fan and case fans. Modes 2, 4, 6, and 7 are mapped but still await complete physical live-cycle confirmation.
- Whether a useful stock `0x14 QUERY_MODE_DATA` carousel can be driven entirely on-device without the PC continuously supplying records. The replacement app currently performs deterministic host-side cycling instead.
- A genuine physical-framebuffer/panel-present acknowledgement path.
- Why the stock APK sometimes reaches a backlight-only state and why its boot is slow.
- Whether dynamic bounds can reliably control frequency-ring speed; the tested 2000/4500 substitution did not.
- Patching or replacing the APK renderer to remove bitmap-heavy animation, repeated `setContentView`, and other UI overhead.

## Workspace implementation references

- Frame construction: `APP/haf_protocol.py`
- TCP/ADB transport and logging: `APP/haf_device.py`
- GUI/live controller: `APP/app.py`
- CPU sensor selection: `APP/cpu_sensors.py`
- Decompiled APK: `analysis/jadx/`
- Protocol utilities and captures: `analysis/protocol/` and `analysis/telemetry_captures/`
- Running task status: `checklist.md`
