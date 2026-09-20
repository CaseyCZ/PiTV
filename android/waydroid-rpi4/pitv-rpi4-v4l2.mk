# PiTV Raspberry Pi 4 hardware video decode additions.
#
# H.264/AVC uses the stateful V4L2 Codec2 service. HEVC/H.265 on Raspberry Pi 4
# uses the rpivid stateless decoder through Raspberry Vanilla's FFmpeg Codec2
# service and FFmpeg V4L2 Request API implementation.

PRODUCT_SOONG_NAMESPACES += \
    external/v4l2_codec2 \
    external/ffmpeg \
    external/ffmpeg_codec2 \
    external/libudev-zero

PRODUCT_PACKAGES += \
    android.hardware.media.c2@1.0-service-v4l2 \
    android.hardware.media.c2@1.2-service-ffmpeg \
    libc2plugin_store

# Prefer the dedicated V4L2 H.264 component (rank 128) over FFmpeg video
# components (rank 256). FFmpeg H.264 V4L2 is kept disabled; its stateless
# V4L2 Request path is enabled only for HEVC/rpivid.
PRODUCT_PROPERTY_OVERRIDES += \
    debug.stagefright.c2-poolmask=0x350000 \
    persist.v4l2_codec2.rank.decoder=128 \
    persist.ffmpeg_codec2.rank.video=256 \
    persist.ffmpeg_codec2.v4l2.h264=false \
    persist.ffmpeg_codec2.v4l2.h265=true \
    ro.vendor.v4l2_codec2.decode_concurrent_instances=4

PRODUCT_COPY_FILES += \
    vendor/pitv/rpi4/codec2.vendor.ext.policy:$(TARGET_COPY_OUT_VENDOR)/etc/seccomp_policy/codec2.vendor.ext.policy
