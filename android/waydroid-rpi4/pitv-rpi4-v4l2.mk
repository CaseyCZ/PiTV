# PiTV Raspberry Pi 4 hardware video decode additions.
#
# H.264/AVC uses the stateful V4L2 Codec2 service. HEVC/H.265 on Raspberry Pi 4
# uses the rpivid stateless decoder through Raspberry Vanilla's FFmpeg Codec2
# service and FFmpeg V4L2 Request API implementation.

# v4l2_codec2 is a Soong project. The Android 13 Raspberry-Vanilla FFmpeg
# trees use Android.mk and therefore must not be listed as Soong namespaces.
PRODUCT_SOONG_NAMESPACES += \
    external/v4l2_codec2

PRODUCT_PACKAGES += \
    android.hardware.media.c2@1.0-service-v4l2 \
    android.hardware.media.c2@1.2-service-ffmpeg \
    libc2plugin_store

# Codec priority and hardware-enable properties live in vendor.prop and are
# attached through TARGET_VENDOR_PROP by the build script. This matches the
# Android 13 Raspberry Pi device pattern and keeps media properties in vendor.

PRODUCT_COPY_FILES += \
    vendor/pitv/rpi4/codec2.vendor.ext.policy:$(TARGET_COPY_OUT_VENDOR)/etc/seccomp_policy/codec2.vendor.ext.policy
