# PiTV installation

<p align="center">
  Complete guide from an empty microSD card to the first <strong>PiTV boot on Raspberry Pi 4</strong>.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Raspberry%20Pi-4-C51A4A?style=for-the-badge&logo=raspberrypi&logoColor=white" alt="Raspberry Pi 4" />
  <img src="https://img.shields.io/badge/Ubuntu%20Server-24.04%20LTS-E95420?style=for-the-badge&logo=ubuntu&logoColor=white" alt="Ubuntu Server 24.04 LTS" />
  <img src="https://img.shields.io/badge/PiTV-v1.3.0-38BDF8?style=for-the-badge&labelColor=0284C7" alt="PiTV 1.3.0" />
</p>

## What you need

- Raspberry Pi 4
- microSD card
- microSD reader or microSD → SD adapter
- micro-HDMI → HDMI cable
- USB-C power supply for Raspberry Pi 4
- TV or monitor
- Wi-Fi
- computer for preparing the microSD card
- keyboard as an optional local recovery method

For normal PiTV control, a TV remote through **HDMI-CEC** is recommended.

## 1. Test the TV and remote

Before installing PiTV, verify Power, arrows, OK, Back / Return, Volume and Mute. Home / Menu is optional; holding Back for 3 seconds is PiTV's universal app-exit gesture.

Enable **HDMI-CEC** in the TV settings. Depending on the TV manufacturer it may be called Anynet+, SIMPLINK, BRAVIA Sync, VIERA Link or EasyLink.

## 2. Install Raspberry Pi Imager

Download **Raspberry Pi Imager** from:

https://www.raspberrypi.com/software/

Insert the microSD card into your computer.

> Writing the image erases all data on the selected microSD card.

## 3. Select the operating system

In Raspberry Pi Imager select:

1. **Raspberry Pi Device** → Raspberry Pi 4
2. **Operating System** → Ubuntu
3. **Ubuntu Server 24.04 LTS (64-bit)**
4. **Storage** → your microSD card

Do not use Ubuntu Desktop or Raspberry Pi OS Desktop. PiTV is designed as a lightweight TV/server system without a full desktop environment.

## 4. Configure Wi-Fi and SSH before writing

Recommended image settings:

- hostname, for example `pitv`
- your own administrator username
- a secure password
- Wi-Fi SSID and password
- correct Wi-Fi country
- timezone
- keyboard layout
- **Enable SSH**

You do not need to create a `pitv` user manually. The PiTV installer creates its own kiosk user.

## 5. Write the image

Write the image and let Raspberry Pi Imager complete its verification. Safely eject the card afterwards.

## 6. First Raspberry Pi boot

Insert the microSD card, connect HDMI, connect power and wait for Ubuntu Server to complete its first boot.

If Wi-Fi was configured in Raspberry Pi Imager, the Raspberry Pi should connect automatically.

## 7. Connect over SSH

From another computer on the same network:

```bash
ssh YOUR_USER@pitv.local
```

If mDNS does not resolve, use the Raspberry Pi IP address instead:

```bash
ssh YOUR_USER@IP_ADDRESS
```

## 8. Update Ubuntu

```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

Reconnect over SSH after the reboot.

## 9. Install PiTV

```bash
git clone https://github.com/CaseyCZ/PiTV.git
cd PiTV
sudo ./install.sh
sudo reboot
```

The installer prepares the PiTV runtime, labwc / Wayland session, kiosk user, HDMI-CEC tools, Store catalogs and restricted privileged helpers.

## 10. First PiTV start

After reboot PiTV should start automatically on HDMI:

```text
Ubuntu Server
└── tty1 autologin: pitv
    └── labwc / Wayland
        └── PiTV
```

SSH and background server services remain available.

## 11. First checks

Verify HDMI video, resolution, arrows, OK, Back, the 3-second Back app-exit gesture, optional Home / Menu, HDMI-CEC, HDMI audio, Wi-Fi, both PiTV themes and the screensaver.

Then continue with PiTV Store, Android / APK or Server Store.

## PiTV Store

**Settings → Applications → PiTV Store**

Kodi, SmartTube, Stremio, YouTube, Spotify and Plex are available.

## Android / Google Play

**Settings → Android / APK → Waydroid + Google Play → Install**

Android is optional. PiTV works without Waydroid.

## Server Store

**Settings → Server Store**

Homebridge, Tailscale, Docker Engine and ATVLoadly can be installed directly from PiTV.

## Troubleshooting

Check tty1:

```bash
systemctl status getty@tty1
```

Start the PiTV session manually:

```bash
sudo -u pitv /usr/local/bin/pitv-session
```

Check CEC adapters:

```bash
cec-client -l
```

Check HDMI/ALSA audio devices:

```bash
aplay -l
```

## Uninstall

```bash
cd PiTV
sudo ./uninstall.sh
```

<p align="center">
  <a href="README_EN.md"><img src="https://img.shields.io/badge/PiTV-Back%20to%20README-172033?style=for-the-badge&labelColor=111827&logo=github&logoColor=white" alt="Back to README" /></a>
</p>
