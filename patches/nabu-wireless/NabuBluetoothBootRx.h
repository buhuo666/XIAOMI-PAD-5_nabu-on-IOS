// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include <string.h>

// The boot HCI stream can carry QCA diagnostic ACL packets before a response.
// Their 16-bit handle is 0x2edc (hci_qca.c QCA_DEBUG_HANDLE), not a connection.
// Drain their declared payload, never search that payload for an HCI marker.
struct NabuBluetoothBootRx {
    uint8_t type=0,header[4]{},event[258]{},response[258]{};
    unsigned header_bytes=0,remaining=0,event_bytes=0,response_bytes=0;
    uint16_t expected_opcode=0;
    bool failed=false;
    unsigned debug_frames=0,debug_bytes=0,other_events=0;
    void begin(uint16_t opcode) {expected_opcode=opcode;response_bytes=0;}
    void finish_event() {
        // One command is outstanding. Match only command-complete opcode;
        // the command-specific caller still checks status and payload.
        if(event_bytes>=6&&event[1]==0x0e&&
            (unsigned)(event[4]|event[5]<<8)==expected_opcode&&!response_bytes) {
            memcpy(response,event,event_bytes);response_bytes=event_bytes;
        } else ++other_events;
        type=0;
    }
    void take(uint8_t byte) {
        if(failed)return;
        if(!type) {
            if(byte!=2&&byte!=4){failed=true;return;}
            type=byte;header_bytes=remaining=0;event_bytes=0;
            if(type==4)event[event_bytes++]=byte;
            return;
        }
        unsigned need=type==2?4:2;
        if(header_bytes<need) {
            header[header_bytes++]=byte;
            if(type==4)event[event_bytes++]=byte;
            if(header_bytes==need) {
                if(type==2) {
                    if((unsigned)(header[0]|header[1]<<8)!=0x2edc){failed=true;return;}
                    remaining=header[2]|header[3]<<8;
                    ++debug_frames;debug_bytes+=remaining;
                    if(!remaining)type=0;
                } else {
                    remaining=header[1];
                    if(!remaining)finish_event();
                }
            }
            return;
        }
        if(type==4)event[event_bytes++]=byte;
        if(!--remaining) {
            if(type==4)finish_event();
            else type=0;
        }
    }
};
