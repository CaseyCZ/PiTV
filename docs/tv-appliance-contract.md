# PiTV TV Appliance Contract

PiTV is a TV appliance, not a Linux desktop with a launcher on top. This
contract is the baseline for all future UI, Store and runtime changes.

## 0. LibreELEC-style system architecture

- PiTV follows the appliance model used by LibreELEC: the TV interface is a
  supervised system service/target, not a shell started by tty autologin.
- `pitv.target` is the TV-oriented boot target above `multi-user.target`.
  Server services such as SSH, Tailscale, Homebridge and Docker remain normal
  system services and are independent of the TV UI.
- `pitv-shell.service` owns tty1 and the Wayland TV session and uses
  `Restart=always`. A launcher/compositor failure is recovered by systemd,
  not by rebooting Linux.
- labwc uses its native `-S` primary-client lifecycle: PiTV starts only after
  Wayland is ready, and the compositor terminates when PiTV exits. systemd then
  rebuilds the whole visual session as one unit.
- `/run/user/<pitv-uid>/pitv-wayland-display` is the only canonical visible
  compositor locator. Native applications and outer Android launchers must
  never pick the first `wayland-*` socket because nested Cage owns a separate
  socket in the same runtime directory.
- Optional heavy runtimes are separate services. In particular Android warm-up
  must never be a child prerequisite of the Home launcher.
- Hardware/input/display services must exist below the shell; applications must
  not individually own or reinitialize the whole TV input/display stack.
- The compositor is an implementation detail required by PiTV's multi-app and
  Android overlay model. No desktop panels, window chrome or pointer-driven
  workflow may be exposed to the user.

## 1. Immediate launcher

- PiTV Home must become usable before optional application runtimes are warmed.
- Home, Settings and Store must never wait for Waydroid, Flatpak, Kodi or
  server services to initialize.
- Background preparation must not steal focus or change workspace.

## 2. Direct application launch

- Selecting an installed application with OK launches that application, not an
  intermediate desktop, Android launcher, shell, notification shade or setup UI.
- Android TV applications use one persistent hidden Cage/Waydroid runtime.
- The Android workspace is revealed only after the requested package has a
  visible Android activity/window.
- Native Linux TV applications open directly in their dedicated workspace.
- A failed launch returns to PiTV with a visible error instead of leaving a
  black/frozen surface.

## 3. Warm runtime lifecycle

- `pitv-android-warm.service` prewarms optional Android in the background
  after the TV shell is started; PiTV Home never waits for it.
- Closing one Android application stops only that package. It must not reboot
  Waydroid or stop the container.
- Full Waydroid/Cage teardown is a recovery/session-restart operation, not an
  ordinary app-exit operation.
- A transient readiness timeout must not immediately throw the user back to
  PiTV.
- Warm readiness is a local liveness contract, not a synchronous status
  probe on every launch. The persistent Cage client writes its PID to
  `pitv-waydroid-runtime-ready` only after Android reaches `boot_completed`;
  app launch validates that PID locally.
- A normal installed APK launch must go directly to `waydroid app launch`.
  It must not enumerate the complete Android app catalog first. APK
  installation/listing is fallback or management work, not part of warm launch.
- PiTV stays visible until the requested package owns a visible Android
  activity; only then is the Android workspace revealed.
- One-time migrations may run only against an already-ready warm runtime.
  They must never start/stop the Waydroid container, block an app launch or
  compete with an active/pending Android application.

## 4. Remote and focus

- Remote input lives below the visual shell. The normal PiTV 1.5 path is:
  `HDMI-CEC kernel → pitv-inputd → uinput "PiTV TV Remote" → labwc → focused client`.
- PiTV, Kodi, native Stremio and nested Cage/Android therefore receive the
  same Linux D-pad/OK/Back device. The launcher must not relay ordinary
  navigation with `wtype` or Android `input keyevent`.
- `pitv-inputd.service` starts before `pitv-shell.service`, owns the one CEC
  monitor for the appliance, reconnects independently of launcher/app crashes
  and publishes its active adapter in `/run/pitv/cec-device`.
- The PiTV GUI contains no CEC wire parser or second monitor. CEC input has one
  owner only: `pitv-inputd`. TV output commands are separate, short-lived and
  allowlisted through `pitv-cec-control` (Power, Standby, Active Source,
  Volume and Mute only).
- Raw + decoded representations of one CEC press collapse to one navigation
  step. Held arrows repeat only after a deliberate delay; a real release makes
  the next physical press immediate.
- Home/menu CEC commands become the private F13 appliance action. labwc consumes
  F13 globally, reveals PiTV and asks it to suspend the foreground task.
- Holding Back for 3 seconds becomes private F14. labwc consumes it globally,
  reveals PiTV and asks it to close the foreground task. Short Back continues
  directly to the focused application.
- There is always one obvious focused item. Up/Down/Left/Right move focus; OK
  activates it; Back goes back.
- Settings never hides actions behind Right/Left shortcuts.
- The physical baseline on the current TV is Up/Down/Left/Right + OK + Back.
- The legacy in-process CEC reader and per-app relay remain compatibility-only
  code for a pre-1.5 installation; an installed 1.5 system must not use them.

## 5. One immersive fullscreen surface

- PiTV and foreground TV applications are fullscreen appliance surfaces.
- Window decorations, desktop chrome and intermediate compositor windows must
  never be part of the normal TV experience.
- HDMI/EDID disconnect/reconnect must restore PiTV to the full current output
  size without requiring an OS reboot.
- Output geometry belongs below the UI. `pitv-displayd.service` is the only
  HDMI/EDID recovery owner. It fingerprints the DRM connector, modes and EDID,
  waits for reconnect state to settle, then normalizes the matching wlroots
  output to origin `0,0`, normal transform and scale 1.
- A valid current TV mode is preserved; preferred mode is selected only when a
  genuinely reconnected output is disabled or has no current mode. Periodic
  drift checks never wake a disabled/standby TV.
- After a repair the daemon sends the normal appliance `display` action.
  PiTV re-binds SDL fullscreen on its main render thread without killing the
  foreground app. Repeated wlroots repair failure restarts only
  `pitv-shell.service`, never the server OS.
- Booting with the TV off is supported: the first later HDMI connection uses
  the same recovery path.
- labwc reuses an already-valid DRM mode when possible and TV window rules
  pin appliance surfaces to `0,0` before maximizing them.

## 6. Global activity feedback

- Long-running work uses one global activity banner drawn above every PiTV page
  and modal.
- App launch, install, update and recovery must expose progress/state through
  this banner while PiTV remains visible.
- Short confirmations may use a toast, but a toast is not a replacement for
  progress on a long-running operation.

## 7. Performance priority

Order of priorities for future work:

1. remote/focus correctness;
2. application launch and return speed;
3. stable fullscreen/session lifecycle;
4. playback/audio reliability;
5. Store/install/update reliability;
6. UI polish and visual changes.

A visual improvement must not regress any higher-priority item.

## Physical acceptance sequence

After a clean boot:

1. Home responds immediately to arrows, OK and Back.
2. Wait briefly for hidden Android warm-up; Home must remain usable.
3. Launch SmartTube: PiTV stays visible with the global banner until SmartTube
   itself is visible; Android Home/Quick Settings must not flash onscreen.
4. Verify arrows, OK and Back in SmartTube.
5. Hold Back 3 seconds: PiTV returns quickly.
6. Launch SmartTube again: the Android OS must not cold-boot again.
7. Turn the TV off/on or force an HDMI reconnect: PiTV returns fullscreen with
   correct geometry.
8. Repeat with Kodi and native Stremio without changing the input model.
