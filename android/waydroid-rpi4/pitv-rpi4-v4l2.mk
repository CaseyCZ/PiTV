# PiTV Raspberry Pi 4 V4L2 Codec2 vendor additions.
#
# Based on the Android-RPi Android 13 media configuration.  The Pi 4 kernel
# exposes the bcm2835-codec V4L2 nodes to Waydroid; this product fragment adds
# the Android Codec2 service that can actually consume those nodes.

PRODUCT_SOONG_NAMESPACES += \
    external/v4l2_codec2

PRODUCT_PACKAGES += \
    android.hardware.media.c2@1.0-service-v4l2 \
    libc2plugin_store

# Android-RPi's Pi 4 profile uses the V4L2 buffer queue/pool mask rather than
# the generic Codec2 example.  Keep concurrency conservative for one TV player.
PRODUCT_PROPERTY_OVERRIDES += \
    debug.stagefright.c2-poolmask=0x350000 \
    ro.vendor.v4l2_codec2.decode_concurrent_instances=4

PRODUCT_COPY_FILES += \
    vendor/pitv/rpi4/codec2.vendor.ext.policy:$(TARGET_COPY_OUT_VENDOR)/etc/seccomp_policy/codec2.vendor.ext.policy
