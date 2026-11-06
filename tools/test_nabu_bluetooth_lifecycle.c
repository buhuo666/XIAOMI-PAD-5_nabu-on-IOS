/* Exercise the production HCI consumer against a fragmented socket peer. */
#define main nabu_lifecycle_server_main
#include "../userland/nabu/src/bluetooth_lifecycle.c"
#undef main
#include <assert.h>
#include <pthread.h>

struct Peer { int fd; unsigned mode; };

static void send_event(int fd, const uint8_t *data, size_t bytes) {
    size_t offset = 0;
    while (offset < bytes) {
        size_t fragment = 1 + offset % 3;
        if (fragment > bytes - offset) fragment = bytes - offset;
        assert(write(fd, data + offset, fragment) == (ssize_t)fragment);
        offset += fragment;
    }
}

static void expect_command(int fd, uint16_t opcode) {
    uint8_t command[4];
    assert(transfer(fd, command, 4, false, seconds_now()+2) == 0);
    assert(command[0] == 1 && command[1] == (uint8_t)opcode &&
           command[2] == (uint8_t)(opcode >> 8) && command[3] == 0);
}

static void *peer_main(void *context) {
    struct Peer *peer = context;
    if (peer->mode == 7) {
        const uint8_t expected[] = {1, 0x0b, 0x20, 7, 0, 0xe0, 1, 0x30, 0, 0, 0};
        uint8_t command[sizeof(expected)];
        assert(transfer(peer->fd, command, sizeof(command), false, seconds_now()+2) == 0);
        assert(memcmp(command, expected, sizeof(command)) == 0);
        const uint8_t complete[] = {4, 0x0e, 4, 1, 0x0b, 0x20, 0};
        send_event(peer->fd, complete, sizeof(complete));
    } else if (peer->mode <= 2) {
        expect_command(peer->fd, 0x1001);
        const uint8_t unrelated[] = {4,0xff,3,0xfd,0xfc,0xfe};
        send_event(peer->fd, unrelated, sizeof(unrelated));
        uint8_t version[] = {4,0x0e,12,1,1,0x10,0,11,0,0,11,0x1d,0,0x3f,0x37};
        if (peer->mode == 2) version[11] = 0x0f;
        send_event(peer->fd, version, sizeof(version));
        if (peer->mode != 2) {
            expect_command(peer->fd, 0x1009);
            const uint8_t address[] = {4,0x0e,10,1,9,0x10,0,0x57,0x46,0x35,0x24,0x13,2};
            send_event(peer->fd, address, sizeof(address));
        }
    } else {
        expect_command(peer->fd, 0x0c03);
        if (peer->mode == 3) {
            const uint8_t denied[] = {4,0x0f,4,0x0c,1,3,0x0c};
            send_event(peer->fd, denied, sizeof(denied));
        } else if (peer->mode == 4) {
            const uint8_t invalid[] = {0xfd};
            send_event(peer->fd, invalid, sizeof(invalid));
        } else if (peer->mode == 5) {
            /* A matching opcode with no status is not a successful reply. */
            const uint8_t short_event[] = {4,0x0e,3,1,3,0x0c};
            send_event(peer->fd, short_event, sizeof(short_event));
        }
    }
    close(peer->fd);
    return NULL;
}

int main(void) {
    for (unsigned mode = 0; mode < 8; ++mode) {
        int pair[2];
        assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
        assert(fcntl(pair[0], F_SETFL, O_NONBLOCK) == 0);
        struct Peer peer = {pair[1], mode};
        pthread_t thread;
        assert(pthread_create(&thread, NULL, peer_main, &peer) == 0);
        struct LifecycleResult result = {0};
        int error;
        if (mode == 7) {
            const uint8_t parameters[] = {0, 0xe0, 1, 0x30, 0, 0, 0};
            uint8_t response[8]; size_t size = sizeof(response);
            error = hci_command_data(pair[0], 0x200b, parameters, sizeof(parameters), response, &size, &result);
            assert(error == 0 && size == 1 && response[0] == 0);
        } else if (mode <= 2) {
            error = verify_controller(pair[0], mode == 1 ? "02:13:24:35:46:58" : "02:13:24:35:46:57", &result);
            assert(error == (mode == 0 ? 0 : mode == 1 ? ENXIO : ENODEV));
            assert(result.address_checked == (mode == 0));
        } else {
            uint8_t response[32]; size_t size = sizeof(response);
            error = hci_command(pair[0], 0x0c03, response, &size, &result);
            assert(error == (mode == 3 ? EIO : mode == 4 ? EPROTO : EPIPE));
            if (mode == 3) assert(result.hci_status == 0x0c);
        }
        close(pair[0]);
        assert(pthread_join(thread, NULL) == 0);
    }
    int pair[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) == 0);
    assert(fcntl(pair[0], F_SETFL, O_NONBLOCK) == 0);
    uint8_t byte;
    assert(transfer(pair[0], &byte, 1, false, seconds_now()+0.02) == ETIMEDOUT);
    close(pair[0]); close(pair[1]);
    puts("Production HCI readiness: fragmented events, unrelated payload bytes, address mismatch, wrong firmware, command error, malformed frame, EOF and deadline passed");
    return 0;
}
