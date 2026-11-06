// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu APPS/MPSS GLINK and QRTR control trial. Wire formats: Linux rpmsg/qrtr.
// A single polling owner handles IPCRTR; no cellular or WLAN data requests.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include "NabuSmem.h"
#include "NabuWirelessLog.h"
#include "NabuTftp.h"
#include "NabuServreg.h"
#include "NabuWlfw.h"
extern "C" bool nabu_rmtfs_available();
extern "C" unsigned nabu_rmtfs_request(const uint8_t *, unsigned, uint8_t *);
extern "C" bool nabu_msa_prepare(const NabuWlfw::Region *,unsigned);

struct GlinkMessage { uint16_t command, channel; uint32_t value; };
struct QrtrHeader { uint32_t version, type, from_node, from_port, confirm, size, to_node, to_port; };
struct QrtrControl { uint32_t command, words[4]; };
static constexpr uint32_t control_port = 0xfffffffe;
static constexpr uint32_t wlfw_service = 0x45;
static void glink_barrier() { __asm__ volatile("dsb sy" ::: "memory"); }

struct NabuGlink {
    NabuSmem memory;
    volatile uint32_t *doorbell;
    NabuSmemItem descriptor{}, tx{}, rx{};
    uint16_t remote_channel = 0;
    uint32_t features = 1, sent = 0, received = 0, peer = 0, servers = 0, wlfw_node = 0, wlfw_port = 0;
    bool agreed = false, requested = false, acknowledged = false, opened = false, broken = false;
    bool hello_queued = false, hello_replied = false, intent_requested = false, close_ack = false;
    bool peer_seen = false, closing = false;
    const uint8_t *wlan_firmware = nullptr;
    unsigned wlan_bytes = 0, tftp_requests = 0, tftp_completed = 0;
    NabuTftp transfers[2]{};
    NabuServreg registry;
    uint8_t server_check[4096]{};
    unsigned server_check_size = 0;
    bool server_check_valid = false;
    NabuWlfw wlfw;
    bool qmi_enabled = false;
    uint8_t transmit[8192]{};
    struct RemoteIntent { uint32_t id, size; bool present, used; } remote[64]{};
    struct LocalIntent { uint8_t *data; uint32_t size, fill; } local[16]{};
    unsigned local_count = 0;
    struct Pending { QrtrHeader header; QrtrControl control; } pending[16]{};
    unsigned pending_head = 0, pending_count = 0;
    struct Response { uint32_t node, port, from, bytes; uint8_t data[1024]; } responses[8]{};
    unsigned response_head = 0, response_count = 0;

    bool datagram(unsigned type, unsigned from, unsigned node, unsigned port, const void *data, unsigned size) {
        unsigned total = (sizeof(QrtrHeader) + size + 3) & ~3u;
        if (total > sizeof(transmit)) return false;
        int selected = -1;
        for (unsigned i = 0; i < 64; ++i)
            if (remote[i].present && !remote[i].used && remote[i].size >= total) { selected = i; break; }
        if (selected < 0) {
            if (!intent_requested) { command(7, 1, total); intent_requested = true; }
            return false;
        }
        QrtrHeader qrtr{1, type, 1, from, 0, size, node, port};
        memcpy(transmit, &qrtr, sizeof(qrtr)); memcpy(transmit + sizeof(qrtr), data, size);
        for (unsigned i = sizeof(qrtr) + size; i < total; ++i) transmit[i] = 0;
        struct { GlinkMessage message; uint32_t size, left; } header{{9, 1, remote[selected].id}, total, 0};
        if (!send(&header, sizeof(header), transmit, total)) return false;
        remote[selected].used = true; return true;
    }
    void announce_tftp(unsigned node) {
        if (nabu_rmtfs_available()) { uint32_t server[4] = {14, 1, 1, 0x4001}; queue_control(4, node, control_port, server); }
        if (registry.records) { uint32_t server[4] = {64, 257, 1, 0x4002}; queue_control(4,node,control_port,server); }
        if (!wlan_firmware) return;
        uint32_t server[4] = {4096, 1, 1, 0x4000}; queue_control(4, node, control_port, server);
    }
    void tftp(unsigned node, unsigned from, unsigned to, const uint8_t *data, unsigned bytes) {
        if (to == 0x4000) {
            for (unsigned i = 0; i < 2; ++i) if (!transfers[i].active && !transfers[i].pending) {
                NabuTftp &t = transfers[i]; t = NabuTftp{};
                t.node = node; t.peer_port = from; t.local_port = 0x4010 + i;
                t.write_buffer=server_check;t.write_capacity=sizeof(server_check);
                bool check=bytes>2+strlen("/readwrite/server_check.txt") && !memcmp(data+2,"/readwrite/server_check.txt",strlen("/readwrite/server_check.txt")+1);
                const uint8_t *file=check?(server_check_valid?server_check:nullptr):wlan_firmware;
                unsigned file_bytes=check?server_check_size:wlan_bytes;
                if (t.begin(data, bytes, file, file_bytes)) {
                    ++tftp_requests;
                    if(tftp_requests<=40)nabu_wireless_log("NABU TFTP: request file=%s opcode=%u seek=%u rsize=%u block=%u offered=%u\n", t.name, data[1], t.seek, t.requested, t.block_size, t.file != nullptr || t.writing);
                }
                return;
            }
        } else if (to >= 0x4010 && to < 0x4012) {
            NabuTftp &t = transfers[to - 0x4010];
            if (node == t.node && from == t.peer_port) {
                bool was_complete = t.complete; t.acknowledge(data, bytes);
                if (t.complete && !was_complete) { ++tftp_completed; nabu_wireless_log("NABU TFTP: completed file=%s seek=%u bytes=%u\n", t.name, t.seek, t.delivered); }
            }
        }
    }
    void tftp_flush() {
        if (!opened || broken || closing) return;
        while (response_count) {
            Response &r = responses[response_head];
            if (!datagram(1, r.from, r.node, r.port, r.data, r.bytes)) break;
            response_head = (response_head+1)%8; --response_count;
        }
        for (auto &t : transfers) {
            if (t.pending && datagram(1, t.local_port, t.node, t.peer_port, t.payload, t.payload_bytes)) {
                bool complete=t.complete;t.sent();
                if(t.writing && t.complete && !complete) {
                    server_check_size=t.written;server_check_valid=true;++tftp_completed;
                    nabu_wireless_log("NABU TFTP: server_check saved in RAM bytes=%u\n",server_check_size);
                }
            }
        }
        if(qmi_enabled&&wlfw_port&&!wlfw.waiting&&!wlfw.failed&&!wlfw.complete){
            if(wlfw.step==7&&wlfw.post_cal_wait<2000)return;
            if(wlfw.activate&&wlfw.step==3&&!wlfw.permissions_ready){
                wlfw.permissions_ready=nabu_msa_prepare(wlfw.regions,wlfw.region_count);
                if(!wlfw.permissions_ready){wlfw.failed=true;return;}
            }
            if(!wlfw.bytes)wlfw.prepare();
            if(datagram(1,0x4003,wlfw_node,wlfw_port,wlfw.request,wlfw.bytes)){
                wlfw.sent();nabu_wireless_log("NABU WLFW: request message=%#x transaction=%u bytes=%u\n",wlfw.message,wlfw.transaction,wlfw.bytes);
            }
        }
    }

    uint32_t word(unsigned at) { return memory.u32(descriptor.offset + at); }
    void store(unsigned at, uint32_t value) {
        glink_barrier();
        *(volatile uint32_t *)(memory.data + descriptor.offset + at) = value;
        glink_barrier();
    }
    void ring() { *doorbell = 1u << 12; glink_barrier(); }
    unsigned waiting() {
        unsigned head = word(12), tail = word(8);
        if (head >= rx.size || tail >= rx.size) { broken = true; return 0; }
        glink_barrier();
        return (head + rx.size - tail) % rx.size;
    }
    void peek(void *to, unsigned offset, unsigned bytes) {
        unsigned tail = word(8);
        for (unsigned i = 0; i < bytes; ++i) ((uint8_t *)to)[i] = memory.data[rx.offset + (tail + offset + i) % rx.size];
    }
    void advance(unsigned bytes) { store(8, (word(8) + bytes) % rx.size); }
    bool send(const void *header, unsigned header_bytes, const void *data = nullptr, unsigned bytes = 0) {
        unsigned head = word(4), tail = word(0), total = (header_bytes + bytes + 7) & ~7u;
        if (head >= tx.size || tail >= tx.size) { broken = true; return false; }
        unsigned room = tail <= head ? tx.size - head + tail : tail - head;
        if (room < total + 16) return false;
        volatile uint8_t *fifo = const_cast<volatile uint8_t *>(memory.data) + tx.offset;
        for (unsigned i = 0; i < total; ++i)
            fifo[(head + i) % tx.size] = i < header_bytes ? ((const uint8_t *)header)[i] :
                i < header_bytes + bytes ? ((const uint8_t *)data)[i - header_bytes] : 0;
        store(4, (head + total) % tx.size); ring(); sent++;
        return true;
    }
    bool command(uint16_t command, uint16_t channel, uint32_t value, const void *data = nullptr, unsigned bytes = 0) {
        GlinkMessage message{command, channel, value};
        bool ok = send(&message, sizeof(message), data, bytes);
        if (!ok) { broken = true; nabu_wireless_log("NABU GLINK: command=%u could not be queued\n", command); }
        return ok;
    }
    bool offer(unsigned size) {
        if (!size || size > 65536 || local_count == 16) return false;
        uint8_t *data = (uint8_t *)IOMalloc(size);
        if (!data) return false;
        unsigned slot = local_count++;
        local[slot] = {data, size, 0};
        uint32_t pair[2] = {size, slot + 1};
        return command(5, 1, 1, pair, sizeof(pair));
    }
    void queue_control(unsigned command, unsigned node, unsigned port, const uint32_t *words = nullptr, unsigned from_port = control_port) {
        if (pending_count == 16) { broken = true; return; }
        Pending &p = pending[(pending_head + pending_count++) % 16];
        p.header = {1, command, 1, from_port, 0, sizeof(QrtrControl), node, port};
        p.control = {command, {0, 0, 0, 0}};
        if (words) memcpy(p.control.words, words, sizeof(p.control.words));
    }
    void flush() {
        while (opened && pending_count && !broken) {
            int selected = -1;
            for (unsigned i = 0; i < 64; ++i)
                if (remote[i].present && !remote[i].used && remote[i].size >= sizeof(Pending)) { selected = i; break; }
            if (selected < 0) {
                if (!intent_requested) { command(7, 1, sizeof(Pending)); intent_requested = true; }
                return;
            }
            struct { GlinkMessage message; uint32_t size, left; } header{{9, 1, remote[selected].id}, sizeof(Pending), 0};
            if (!send(&header, sizeof(header), &pending[pending_head], sizeof(Pending))) return;
            remote[selected].used = true;
            pending_head = (pending_head + 1) % 16; pending_count--;
        }
    }
    void qrtr(const uint8_t *data, unsigned size) {
        NabuSmem packet{data, size}; QrtrHeader header{}; unsigned at;
        if (size >= 32 && packet.u32(0) == 1) { memcpy(&header, data, 32); at = 32; }
        else if (size >= 16 && data[0] == 3) {
            header.type = data[1]; header.confirm = data[2] & 1; header.size = packet.u32(4);
            header.from_node = packet.u16(8); header.from_port = packet.u16(10);
            header.to_node = packet.u16(12); header.to_port = packet.u16(14); at = 16 + data[3];
            if (header.from_port == 0xfffe) header.from_port = control_port;
            if (header.to_port == 0xfffe) header.to_port = control_port;
        } else { nabu_wireless_log("NABU QRTR: unsupported packet bytes=%u\n", size); return; }
        if (!packet.span(at, header.size) || header.size < 4) return;
        if (!peer_seen) { peer = header.from_node; peer_seen = true; }
        if (header.confirm) {
            uint32_t words[4] = {header.to_node, header.to_port, 0, 0};
            queue_control(7, header.from_node, header.from_port, words, header.to_port);
        }
        unsigned command = packet.u32(at);
        if (header.to_port != control_port && header.type == 1) {
            if(qmi_enabled&&header.to_port==0x4003&&header.from_node==wlfw_node&&header.from_port==wlfw_port){
                const uint8_t *qmi=data+at;
                if(header.size>=7&&qmi[0]==4){wlfw.receive(qmi,header.size);nabu_wireless_log("NABU WLFW: indication message=%#x bytes=%u\n",NabuRmtfs::u16(qmi+3),header.size);}
                else if(wlfw.receive(qmi,header.size)){
                    unsigned n=0;const uint8_t *result=NabuRmtfs::tlv(qmi,header.size,2,n);
                    nabu_wireless_log("NABU WLFW: response message=%#x result=%u error=%u\n",NabuRmtfs::u16(qmi+3),result?NabuRmtfs::u16(result):65535,result?NabuRmtfs::u16(result+2):65535);
                    if(wlfw.message==0x2d)for(unsigned i=0;i<wlfw.region_count;++i)nabu_wireless_log("NABU WLFW: MSA region=%u address=%#llx size=%#x secure=%u\n",i,wlfw.regions[i].address,wlfw.regions[i].size,wlfw.regions[i].secure);
                    if(wlfw.message==0x24&&wlfw.capability_valid)nabu_wireless_log("NABU WLFW: chip=%#x family=%#x board=%#x soc=%#x fw=%#x build=%s\n",wlfw.chip_id,wlfw.chip_family,wlfw.board_id,wlfw.soc_id,wlfw.fw_version,wlfw.build_id);
                    if(wlfw.message==0x24)nabu_wireless_log("NABU WLFW: board-id-valid=%u\n",wlfw.board_id_valid);
                    if(wlfw.board_sent)nabu_wireless_log("NABU WLFW: board-data acknowledged=%u/%u segments=%u\n",wlfw.board_sent,wlfw.board_bytes,wlfw.board_segment);
                    if(wlfw.message==0x20)nabu_wireless_log("NABU WLFW: status valid=%u flags=%#llx\n",wlfw.status_valid,wlfw.fw_status);
                }
                return;
            }
            if (header.to_port == 0x4001 && nabu_rmtfs_available()) {
                if (response_count == 8) { broken = true; return; }
                Response &r = responses[(response_head+response_count)%8]; r.node = header.from_node; r.port = header.from_port;r.from=0x4001;
                r.bytes = nabu_rmtfs_request(data+at, header.size, r.data); if (r.bytes) ++response_count;
                return;
            }
            if(header.to_port==0x4002 && registry.records) {
                if(response_count==8){broken=true;return;}
                Response &r=responses[(response_head+response_count)%8];r.node=header.from_node;r.port=header.from_port;r.from=0x4002;
                r.bytes=registry.answer(data+at,header.size,r.data);if(r.bytes)++response_count;
                unsigned name_bytes=0;const uint8_t *name=NabuRmtfs::tlv(data+at,header.size,1,name_bytes);
                nabu_wireless_log("NABU SERVREG: request=%#x service=%.*s reply-bytes=%u\n",NabuRmtfs::u16(data+at+3),name?(int)name_bytes:0,name?(const char*)name:"",r.bytes);
                return;
            }
            if (wlan_firmware && header.to_port >= 0x4000 && header.to_port <= 0x4011) {
                tftp(header.from_node, header.from_port, header.to_port, data + at, header.size); return;
            }
            nabu_wireless_log("NABU QRTR: data from=%u:%u to-port=%u bytes=%u\n", header.from_node, header.from_port, header.to_port, header.size);
            return;
        }
        if (command == 2 && !hello_replied) {
            hello_replied = true; queue_control(2, header.from_node, control_port);
            announce_tftp(header.from_node);
            nabu_wireless_log("NABU QRTR: HELLO from node=%u\n", header.from_node);
        } else if ((command == 4 || command == 5) && header.size >= 20) {
            uint32_t service = packet.u32(at + 4), instance = packet.u32(at + 8);
            uint32_t node = packet.u32(at + 12), port = packet.u32(at + 16);
            if (service && command == 4) servers++;
            nabu_wireless_log("NABU QRTR: %s service=%u version=%u instance=%u node=%u port=%u\n", command == 4 ? "server" : "removed", service, instance & 255, instance >> 8, node, port);
            if (service == wlfw_service && command == 4) { wlfw_node = node; wlfw_port = port; }
        } else if (command == 10 && header.size >= 20) {
            nabu_wireless_log("NABU QRTR: peer lookup service=%u instance=%#x\n", packet.u32(at + 4), packet.u32(at + 8));
            if (packet.u32(at+4) == 0 || packet.u32(at+4) == 4096 || packet.u32(at+4) == 14 || packet.u32(at+4)==64) announce_tftp(header.from_node);
            queue_control(4, header.from_node, header.from_port);
        } else if (command == 3) {
            nabu_wireless_log("NABU QRTR: peer BYE\n"); broken = true;
        }
    }
    void pump() {
        for (unsigned round = 0; round < 512 && !broken; ++round) {
            unsigned available = waiting();
            if (available < 8) break;
            GlinkMessage message; peek(&message, 0, 8);
            unsigned bytes = 8; uint32_t fragment[2]{};
            if (message.command == 2) {
                unsigned name_bytes = message.value & 0xffff;
                if (name_bytes > rx.size - 16) { broken = true; break; }
                bytes += name_bytes;
            } else if (message.command == 5) {
                if (message.value > (rx.size - 16) / 8) { broken = true; break; }
                bytes += 8 * message.value;
            } else if (message.command == 9 || message.command == 12) {
                if (available < 16) break;
                peek(fragment, 8, 8);
                if (fragment[0] > rx.size - 24) { broken = true; break; }
                bytes = 16 + fragment[0];
            }
            bytes = (bytes + 7) & ~7u;
            if (available < bytes) break;
            received++;
            if (message.command != 9 && message.command != 12 && message.command != 14 && received <= 80)
                nabu_wireless_log("NABU GLINK: RX command=%u channel=%u value=%#x\n", message.command, message.channel, message.value);
            switch (message.command) {
            case 0:
                features &= message.value; advance(bytes); command(1, 1, features); break;
            case 1:
                advance(bytes);
                if (message.channel == 1 && message.value == features) agreed = true;
                else if (message.channel) { features &= message.value; command(0, 1, features); }
                break;
            case 2: {
                char name[64]{}; unsigned length = message.value & 0xffff;
                peek(name, 8, length < sizeof(name) - 1 ? length : sizeof(name) - 1); advance(bytes);
                nabu_wireless_log("NABU GLINK: remote OPEN name=%s channel=%u\n", name, message.channel);
                if (!strcmp(name, "IPCRTR")) { remote_channel = message.channel; command(4, remote_channel, 0); }
                break;
            }
            case 4:
                advance(bytes); if (message.channel == 1) acknowledged = true; break;
            case 5:
                if (message.channel == remote_channel) for (unsigned i = 0; i < message.value; ++i) {
                    uint32_t pair[2]; peek(pair, 8 + 8 * i, 8);
                    for (unsigned n = 0; n < 64; ++n) if (!remote[n].present || remote[n].id == pair[1]) {
                        remote[n] = {pair[1], pair[0], true, false}; break;
                    }
                }
                advance(bytes); intent_requested = false; break;
            case 6: case 14:
                if (message.channel == remote_channel) for (auto &intent : remote) if (intent.present && intent.id == message.value) {
                    intent.used = false; intent.present = message.command == 14;
                }
                advance(bytes); break;
            case 7: {
                advance(bytes);
                if (message.channel == remote_channel) { bool granted = offer(message.value); command(8, 1, granted); }
                break;
            }
            case 8:
                advance(bytes); if (!message.value) { broken = true; nabu_wireless_log("NABU GLINK: remote refused TX intent\n"); } break;
            case 9: case 12: {
                unsigned id = message.value;
                if (message.channel != remote_channel || !id || id > local_count || fragment[0] > local[id-1].size - local[id-1].fill) {
                    broken = true; nabu_wireless_log("NABU GLINK: invalid RX fragment channel=%u intent=%u bytes=%u\n", message.channel, id, fragment[0]); break;
                }
                LocalIntent &intent = local[id-1]; peek(intent.data + intent.fill, 16, fragment[0]); intent.fill += fragment[0]; advance(bytes);
                if (!fragment[1]) {
                    qrtr(intent.data, intent.fill); intent.fill = 0;
                    command(features & 1 ? 14 : 6, 1, id);
                    if (!(features & 1)) { uint32_t pair[2] = {intent.size, id}; command(5, 1, 1, pair, 8); }
                }
                break;
            }
            case 13: advance(bytes); ring(); break;
            case 3:
                advance(bytes); command(11, message.channel, 0);
                if (message.channel == remote_channel) { opened = false; if (!closing) broken = true; } break;
            case 11: advance(bytes); if (message.channel == 1) close_ack = true; break;
            case 15: advance(bytes); break;
            default:
                nabu_wireless_log("NABU GLINK: unsupported command=%u\n", message.command); broken = true; break;
            }
            if (agreed && !requested) { command(2, 1, 7, "IPCRTR", 7); requested = true; }
            if (remote_channel && acknowledged && !opened && !broken && !closing) {
                opened = true; nabu_wireless_log("NABU GLINK: IPCRTR open local=1 remote=%u\n", remote_channel);
                for (unsigned i = 0; i < 4; ++i) if (!offer(8192)) { broken = true; break; }
                if (!hello_queued) { queue_control(2, 0xffffffff, control_port); hello_queued = true; }
            }
            flush();
            tftp_flush();
        }
        flush();
        tftp_flush();
    }
    void release() { for (unsigned i = 0; i < local_count; ++i) IOFree(local[i].data, local[i].size); }
};

extern "C" void nabu_glink_trial(vm_offset_t smem, vm_offset_t ipc) {
    NabuGlink *link = (NabuGlink *)IOMalloc(sizeof(NabuGlink));
    if (!link) return;
    // All state belongs to this one bounded trial; no interrupt callback retains it.
    bzero(link, sizeof(*link)); link->features = 1;
    link->memory = {(const volatile uint8_t *)smem, 0x200000}; link->doorbell = (volatile uint32_t *)ipc;
    IORegistryEntry *firmware_entry = IORegistryEntry::fromPath("/nabu-modem", gIODTPlane);
    if (firmware_entry) {
        OSData *firmware = OSDynamicCast(OSData, firmware_entry->getProperty("wlanmdsp"));
        if (firmware) { link->wlan_firmware = (const uint8_t *)firmware->getBytesNoCopy(); link->wlan_bytes = firmware->getLength(); }
        OSData *registry=OSDynamicCast(OSData,firmware_entry->getProperty("servreg"));
        if(registry)link->registry.load((const uint8_t*)registry->getBytesNoCopy(),registry->getLength());
        link->qmi_enabled=firmware_entry->getProperty("wlfw-qmi")!=nullptr;
        link->wlfw.activate=firmware_entry->getProperty("wlfw-msa")!=nullptr;
        OSData *board=OSDynamicCast(OSData,firmware_entry->getProperty("wlfw-board"));
        if(board){link->wlfw.board_data=(const uint8_t*)board->getBytesNoCopy();link->wlfw.board_bytes=board->getLength();}
    }
    if (!link->memory.find(478, &link->descriptor) || link->descriptor.size != 32 ||
        !link->memory.find(479, &link->tx) || !link->memory.find(480, &link->rx) ||
        link->tx.size != 16384 || link->rx.size != 16384) {
        nabu_wireless_log("NABU GLINK: descriptor or 16 KiB queues unavailable\n");
        if (firmware_entry) firmware_entry->release(); IOFree(link, sizeof(*link)); return;
    }
    nabu_wireless_log("NABU GLINK: queues ready tx-head=%u rx-head=%u; begin version1\n", link->word(4), link->word(12));
    link->command(0, 1, 1);
    for (unsigned i = 0; i < 30000 && !link->broken; ++i) {
        link->pump(); for (auto &t : link->transfers) t.tick(); link->wlfw.tick(); IOSleep(1);
    }
    bool was_open = link->opened;
    if (link->opened && !link->broken) {
        link->closing = true;
        link->command(3, 1, 0);
        for (unsigned i = 0; i < 100 && !link->close_ack && !link->broken; ++i) { link->pump(); IOSleep(10); }
    }
    nabu_wireless_log("NABU GLINK: trial complete agreed=%u open=%u broken=%u tx=%u rx=%u close-ack=%u\n", link->agreed, was_open, link->broken, link->sent, link->received, link->close_ack);
    nabu_wireless_log("NABU QRTR: inventory peer=%u servers=%u WLFW-node=%u WLFW-port=%u; WLAN data path not started\n", link->peer, link->servers, link->wlfw_node, link->wlfw_port);
    nabu_wireless_log("NABU TFTP: requests=%u completed=%u firmware-bytes=%u\n", link->tftp_requests, link->tftp_completed, link->wlan_bytes);
    nabu_wireless_log("NABU SERVREG: records=%u requests=%u\n",link->registry.count,link->registry.requests);
    if(link->qmi_enabled)nabu_wireless_log("NABU WLFW: complete=%u failed=%u waiting=%u step=%u regions=%u permissions=%u msa-ready=%u\n",link->wlfw.complete,link->wlfw.failed,link->wlfw.waiting,link->wlfw.step,link->wlfw.region_count,link->wlfw.permissions_ready,link->wlfw.msa_ready);
    if(link->wlfw.board_data)nabu_wireless_log("NABU WLFW: board-bytes=%u fw-ready-indication=%u init-done=%u status=%#llx\n",link->wlfw.board_sent,link->wlfw.fw_ready,link->wlfw.init_done,link->wlfw.fw_status);
    if (firmware_entry) firmware_entry->release();
    link->release(); IOFree(link, sizeof(*link));
}
