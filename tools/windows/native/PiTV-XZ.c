/*
 * PiTV-XZ - tiny .xz -> raw file decoder for PiTV SD Installer.
 *
 * liblzma is provided by XZ Utils and is licensed under 0BSD.
 * This program intentionally has no command-line option parser:
 *     PiTV-XZ.exe input.img.xz output.img
 */

#include <lzma.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define BUF_SIZE (1024U * 1024U)

static int fail(const char *message)
{
    fprintf(stderr, "PiTV-XZ: %s\n", message);
    return 1;
}

int main(int argc, char **argv)
{
    FILE *input = NULL;
    FILE *output = NULL;
    uint8_t *in_buf = NULL;
    uint8_t *out_buf = NULL;
    lzma_stream strm = LZMA_STREAM_INIT;
    lzma_ret ret;
    int result = 1;
    int input_finished = 0;

    if (argc != 3)
        return fail("usage: PiTV-XZ.exe input.xz output.img");

    input = fopen(argv[1], "rb");
    if (input == NULL)
        return fail("cannot open input file");

    output = fopen(argv[2], "wb");
    if (output == NULL) {
        fclose(input);
        return fail("cannot create output file");
    }

    in_buf = (uint8_t *)malloc(BUF_SIZE);
    out_buf = (uint8_t *)malloc(BUF_SIZE);
    if (in_buf == NULL || out_buf == NULL) {
        fail("not enough memory");
        goto cleanup;
    }

    ret = lzma_stream_decoder(&strm, UINT64_MAX, LZMA_CONCATENATED);
    if (ret != LZMA_OK) {
        fail("cannot initialize XZ decoder");
        goto cleanup;
    }

    while (1) {
        lzma_action action = LZMA_RUN;

        if (strm.avail_in == 0 && !input_finished) {
            const size_t count = fread(in_buf, 1, BUF_SIZE, input);
            if (ferror(input)) {
                fail("read error");
                goto cleanup_decoder;
            }

            strm.next_in = in_buf;
            strm.avail_in = count;
            if (feof(input))
                input_finished = 1;
        }

        if (input_finished)
            action = LZMA_FINISH;

        strm.next_out = out_buf;
        strm.avail_out = BUF_SIZE;

        ret = lzma_code(&strm, action);

        {
            const size_t produced = BUF_SIZE - strm.avail_out;
            if (produced > 0 && fwrite(out_buf, 1, produced, output) != produced) {
                fail("write error");
                goto cleanup_decoder;
            }
        }

        if (ret == LZMA_STREAM_END) {
            if (fflush(output) != 0) {
                fail("flush error");
                goto cleanup_decoder;
            }
            result = 0;
            break;
        }

        if (ret != LZMA_OK) {
            switch (ret) {
                case LZMA_FORMAT_ERROR:
                    fail("input is not a valid .xz stream");
                    break;
                case LZMA_OPTIONS_ERROR:
                    fail("unsupported XZ compression options");
                    break;
                case LZMA_DATA_ERROR:
                    fail("XZ data is corrupt");
                    break;
                case LZMA_MEM_ERROR:
                    fail("not enough memory while decoding");
                    break;
                case LZMA_BUF_ERROR:
                    fail("unexpected end of XZ input");
                    break;
                default:
                    fail("XZ decoder error");
                    break;
            }
            goto cleanup_decoder;
        }
    }

cleanup_decoder:
    lzma_end(&strm);

cleanup:
    free(out_buf);
    free(in_buf);
    if (output != NULL)
        fclose(output);
    if (input != NULL)
        fclose(input);

    if (result != 0)
        remove(argv[2]);

    return result;
}
