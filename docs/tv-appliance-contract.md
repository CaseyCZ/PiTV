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

## 4. Remote and focus

- There is always one obvious focused item.
- Up/Down/Left/Right move focus; OK activates the focused item; Back goes back.
- Settings never hides actions behind Right/Left shortcuts.
- Android D-pad events are serialized through one ordered input queue.
- The physical baseline on the current TV is Up/Down/Left/Right + OK + Back.
- Holding Back for 3 seconds is the deterministic appliance escape back to PiTV.

## 5. One immersive fullscreen surface

- PiTV and foreground TV applications are fullscreen appliance surfaces.
- Window decorations, desktop chrome and intermediate compositor windows must
  never be part of the normal TV experience.
- HDMI/EDID disconnect/reconnect must restore PiTV to the full current output
  size without requiring an OS reboot.

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
