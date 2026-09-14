/*
 * rtk_probe - standalone libusb validation tool for the Realtek /
 * Microarray "USB2.0 Finger Print Bridge" MOC sensor family.
 *
 * Replicates exactly the init sequence used by the libfprint `realtek`
 * driver (libfprint/drivers/realtek/realtek.c) so the protocol can be
 * validated without installing a patched libfprint.
 *
 * Usage: rtk_probe [vid:pid]      (default 3274:9011)
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <libusb-1.0/libusb.h>

#define EP_OUT 0x01
#define EP_IN  0x82

#define CMD_TIMEOUT   1000
#define DATA_TIMEOUT  5000
#define STATUS_TIMEOUT 2000

struct rtk_cmd_bulk {
    uint8_t cmd[2];
    uint8_t param[4];
    uint8_t addr[4];
    uint8_t data_len[2];
};

static struct rtk_cmd_bulk co_select_system   = { .cmd = {0x05, 0x13} };
static struct rtk_cmd_bulk co_get_enroll_num  = { .cmd = {0x45, 0x0d}, .data_len = {0x02} };
static struct rtk_cmd_bulk co_start_capture   = { .cmd = {0x05, 0x05} };
static struct rtk_cmd_bulk co_cancel_capture  = { .cmd = {0x05, 0x07} };
static struct rtk_cmd_bulk co_get_template    = { .cmd = {0x45, 0x0e} };

static void hexdump(const char *tag, const uint8_t *b, int n)
{
    printf("%s (%d bytes):", tag, n);
    for (int i = 0; i < n; i++)
        printf(" %02x", b[i]);
    printf("\n");
}

static int bulk_out(libusb_device_handle *h, const void *data, int len)
{
    int transferred = 0;
    int r = libusb_bulk_transfer(h, EP_OUT, (unsigned char *)data, len,
                                 &transferred, CMD_TIMEOUT);
    if (r < 0) {
        fprintf(stderr, "  bulk OUT failed: %s (%d)\n", libusb_error_name(r), transferred);
        return r;
    }
    printf("  bulk OUT ok (%d bytes)\n", transferred);
    return 0;
}

/* read one bulk-IN packet; returns length or negative error */
static int bulk_in(libusb_device_handle *h, uint8_t *buf, int buflen, int timeout)
{
    int transferred = 0;
    int r = libusb_bulk_transfer(h, EP_IN, buf, buflen, &transferred, timeout);
    if (r < 0) {
        fprintf(stderr, "  bulk IN failed: %s\n", libusb_error_name(r));
        return r;
    }
    return transferred;
}

/* mimic fp_cmd_receive_cb's message parsing */
static void parse_status(const uint8_t *buf, int len)
{
    hexdump("  status", buf, len);
    if (len >= 1) {
        /* first byte is the in-status code (FP_RTK_SUCCESS == 0) */
        printf("  -> status code = 0x%02x (%s)\n", buf[0],
               buf[0] == 0 ? "SUCCESS" : "nonzero/error");
    }
}

int main(int argc, char **argv)
{
    unsigned vid = 0x3274, pid = 0x9011;
    if (argc > 1)
        sscanf(argv[1], "%x:%x", &vid, &pid);

    libusb_context *ctx = NULL;
    int r = libusb_init(&ctx);
    if (r < 0) { fprintf(stderr, "libusb_init: %s\n", libusb_error_name(r)); return 1; }

    libusb_device **list = NULL;
    ssize_t n = libusb_get_device_list(ctx, &list);
    libusb_device *dev = NULL;
    for (ssize_t i = 0; i < n; i++) {
        struct libusb_device_descriptor d;
        if (libusb_get_device_descriptor(list[i], &d) == 0 &&
            d.idVendor == vid && d.idProduct == pid) {
            dev = list[i];
            printf("Found %04x:%04x on bus %d addr %d\n", vid, pid,
                   libusb_get_bus_number(dev), libusb_get_device_address(dev));
            break;
        }
    }
    if (!dev) { fprintf(stderr, "Device %04x:%04x not found\n", vid, pid); return 2; }

    /* string descriptors */
    libusb_device_handle *h = NULL;
    r = libusb_open(dev, &h);
    if (r < 0) { fprintf(stderr, "libusb_open: %s (need root / udev rule)\n",
                         libusb_error_name(r)); return 3; }

    struct libusb_device_descriptor d;
    libusb_get_device_descriptor(dev, &d);
    char sbuf[256];
    if (d.iManufacturer && libusb_get_string_descriptor_ascii(h, d.iManufacturer,
            (unsigned char *)sbuf, sizeof sbuf) > 0) printf("  Manufacturer: %s\n", sbuf);
    if (d.iProduct && libusb_get_string_descriptor_ascii(h, d.iProduct,
            (unsigned char *)sbuf, sizeof sbuf) > 0) printf("  Product     : %s\n", sbuf);
    if (d.iSerialNumber && libusb_get_string_descriptor_ascii(h, d.iSerialNumber,
            (unsigned char *)sbuf, sizeof sbuf) > 0) printf("  Serial      : %s\n", sbuf);

    /* --- dev_probe(): reset + claim, then release --- */
    printf("\n[probe] reset + claim interface 0\n");
    libusb_reset_device(h);
    r = libusb_claim_interface(h, 0);
    if (r < 0) { fprintf(stderr, "claim_interface: %s\n", libusb_error_name(r)); return 4; }

    /* --- dev_init() step 1: GET_DEVICE_INFO vendor control transfer --- */
    printf("\n[init 1/3] GET_DEVICE_INFO ctrl req=0x07 value=0x000d index=0 len=8\n");
    uint8_t info[8] = {0};
    r = libusb_control_transfer(h, 0xC0 /* dev->host, vendor, device */,
                                0x07, 0x000D, 0x0000, info, sizeof info, CMD_TIMEOUT);
    if (r < 0) {
        fprintf(stderr, "  control transfer failed: %s\n", libusb_error_name(r));
    } else {
        hexdump("  device info", info, r);
    }

    /* --- dev_init() step 2: select system --- */
    printf("\n[init 2/3] co_select_system (0x05 0x13, param0=0x01)\n");
    co_select_system.param[0] = 0x01;
    if (bulk_out(h, &co_select_system, sizeof co_select_system) == 0) {
        uint8_t buf[2048];
        int len = bulk_in(h, buf, sizeof buf, STATUS_TIMEOUT);
        if (len >= 0) parse_status(buf, len);
    }

    /* --- dev_init() step 3: get enroll num --- */
    printf("\n[init 3/3] co_get_enroll_num (0x45 0x0d, data_len=2)\n");
    if (bulk_out(h, &co_get_enroll_num, sizeof co_get_enroll_num) == 0) {
        uint8_t buf[2048];
        int len = bulk_in(h, buf, sizeof buf, DATA_TIMEOUT);
        if (len >= 0) hexdump("  enroll data", buf, len);
        int len2 = bulk_in(h, buf, sizeof buf, STATUS_TIMEOUT);
        if (len2 >= 0) parse_status(buf, len2);
    }

    printf("\n[done] releasing interface\n");
    libusb_release_interface(h, 0);
    libusb_close(h);
    libusb_free_device_list(list, 1);
    libusb_exit(ctx);
    return 0;
}
