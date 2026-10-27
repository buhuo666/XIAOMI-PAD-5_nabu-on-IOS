/*
 * Host regression tests for the NT36523 frame and HID slot helpers.
 *
 * SPDX-License-Identifier: BSD-2-Clause-Patent
 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "nabu_touch_board.h"
#include "nabu_touch_input.h"

struct emitted_event {
	int slot;
	int down;
	int x;
	int y;
};

static struct emitted_event events[64];
static unsigned event_count;
static uint8_t fake_frame[NVT_POINT_DATA_LEN];
static uint16_t fake_page;

static void
emit(int slot, int down, int x, int y)
{
	assert(event_count < sizeof(events) / sizeof(events[0]));
	events[event_count++] = (struct emitted_event){ slot, down, x, y };
}

static int
fake_xfer(void *ctx, const uint8_t *tx, uint8_t *rx, size_t length)
{
	(void)ctx;
	assert(tx != NULL && length != 0);
	if (tx[0] == 0xffu && length == 3 && rx == NULL) {
		fake_page = (uint16_t)((uint16_t)tx[1] << 8 | tx[2]);
		return 0;
	}
	if (rx != NULL && length == NVT_POINT_DATA_LEN + 2u &&
	    tx[0] == (NVT_EVENT_BUF_ADDR & 0x7fu)) {
		memcpy(rx, tx, length);
		memcpy(rx + 2, fake_frame, sizeof(fake_frame));
		return 0;
	}
	return -1;
}

static void
finish_frame(void)
{
	unsigned sum = 0;
	fake_frame[NVT_POINT_DATA_LEN - 1] = 0;
	for (unsigned i = 0; i < NVT_POINT_DATA_LEN - 1; i++) {
		sum += fake_frame[i];
	}
	fake_frame[NVT_POINT_DATA_LEN - 1] = (uint8_t)(0u - sum);
}

static void
set_contact(unsigned index, unsigned id, unsigned event, unsigned x, unsigned y)
{
	uint8_t *p = fake_frame + index * 6u;
	p[0] = (uint8_t)((id << 3) | event);
	p[1] = (uint8_t)(x >> 4);
	p[2] = (uint8_t)(y >> 4);
	p[3] = (uint8_t)(((x & 0xfu) << 4) | (y & 0xfu));
	p[4] = 5;
	p[5] = 20;
}

int
main(void)
{
	struct nvt_bus bus = { .xfer = fake_xfer };
	struct nbu_touch_slots slots = {0};
	struct nvt_contact contacts[NVT_MAX_FINGERS];
	struct nvt_info info;
	uint8_t frame[NVT_POINT_DATA_LEN];
	uint8_t fwinfo[39] = {0};

	assert(nbu_touch_pin_mux(23) == 2 && nbu_touch_pin_mux(24) == 3);
	assert(nbu_touch_pin_mux(25) == 3 && nbu_touch_pin_mux(26) == 2);
	assert(nbu_touch_branch_ready(NBU_TOUCH_S_AHB, 0x80000002u,
	    NBU_TOUCH_VOTES));
	assert(!nbu_touch_branch_ready(NBU_TOUCH_S_AHB, 0x80000000u,
	    NBU_TOUCH_VOTES));
	assert(!nbu_touch_branch_ready(NBU_TOUCH_M_AHB, 0,
	    NBU_TOUCH_VOTES & ~(1u << 2)));
	assert(nbu_touch_xo_level((uint32_t[8]){0x106, 0x106, 0x100001}) == 2);
	assert(nbu_touch_hid_x(0) == 0);
	assert(nbu_touch_hid_x(1599) == 1079);
	assert(nbu_touch_hid_y(0) == 0);
	assert(nbu_touch_hid_y(2559) == 2399);

	fwinfo[0] = 0x12;
	fwinfo[1] = 0xed;
	fwinfo[2] = 18;
	fwinfo[3] = 32;
	fwinfo[4] = 0x06;
	fwinfo[5] = 0x40;
	fwinfo[6] = 0x0a;
	fwinfo[7] = 0x00;
	assert(nvt_parse_fwinfo(fwinfo, sizeof(fwinfo), &info) == 0);
	assert(info.valid && info.max_x == 1600 && info.max_y == 2560);
	fwinfo[1] = 0;
	assert(nvt_parse_fwinfo(fwinfo, sizeof(fwinfo), &info) == 0);
	assert(!info.valid);

	set_contact(0, 1, 1, 0, 0);
	set_contact(1, 10, 2, 1599, 2559);
	finish_frame();
	assert(nvt_validate_point_frame(fake_frame) == 0);
	assert(nvt_read_point_frame(&bus, frame) == 0);
	assert(fake_page == (NVT_EVENT_BUF_ADDR >> 7));
	assert(nvt_parse_points(frame, 1599, 2559, contacts, NVT_MAX_FINGERS) == 2);
	assert(contacts[0].id == 1 && contacts[0].x == 0 && contacts[0].y == 0);
	assert(contacts[1].id == 10 && contacts[1].x == 1599 && contacts[1].y == 2559);

	set_contact(1, 1, 2, 10, 20);
	finish_frame();
	assert(nvt_parse_points(fake_frame, 1599, 2559, contacts,
	    NVT_MAX_FINGERS) == -1);
	memset(fake_frame, 0, sizeof(fake_frame));
	set_contact(0, 1, 2, 1600, 20);
	finish_frame();
	assert(nvt_parse_points(fake_frame, 1599, 2559, contacts,
	    NVT_MAX_FINGERS) == -1);
	memset(fake_frame, 0, sizeof(fake_frame));
	set_contact(0, 1, 4, 10, 20);
	finish_frame();
	assert(nvt_parse_points(fake_frame, 1599, 2559, contacts,
	    NVT_MAX_FINGERS) == -1);

	memset(fake_frame, 0, sizeof(fake_frame));
	set_contact(0, 1, 1, 0, 0);
	set_contact(1, 10, 2, 1599, 2559);
	finish_frame();
	assert(nvt_parse_points(fake_frame, 1599, 2559, contacts,
	    NVT_MAX_FINGERS) == 2);
	assert(nbu_touch_publish(&slots, contacts, 2, 1599, 2559, emit) == 0);
	assert(event_count == 2 && slots.active == 0x201u);
	assert(events[0].slot == 0 && events[0].down);
	assert(events[1].slot == 9 && events[1].down);
	assert(nbu_touch_publish(&slots, contacts, 2, 1599, 2559, emit) == 0);
	assert(event_count == 4); /* Snapshot replay lets a late HID service catch up. */

	contacts[0].x = 800;
	assert(nbu_touch_publish(&slots, contacts, 1, 1599, 2559, emit) == 0);
	assert(event_count == 6);
	assert(events[4].slot == 9 && !events[4].down);
	assert(events[5].slot == 0 && events[5].down && events[5].x == 800);
	assert(slots.active == 1u);

	struct nvt_contact invalid[2] = {
		{ .id = 2, .down = 1, .x = 10, .y = 20 },
		{ .id = 2, .down = 1, .x = 30, .y = 40 },
	};
	assert(nbu_touch_publish(&slots, invalid, 2, 1599, 2559, emit) == -1);
	assert(event_count == 6 && slots.active == 1u);
	invalid[1].id = 3;
	invalid[1].x = 1600;
	assert(nbu_touch_publish(&slots, invalid, 2, 1599, 2559, emit) == -1);
	assert(event_count == 6 && slots.active == 1u);

	nbu_touch_release(&slots, emit);
	assert(event_count == 7 && events[6].slot == 0 && !events[6].down);
	nbu_touch_release(&slots, emit);
	assert(event_count == 7 && slots.active == 0);

	fake_frame[10] ^= 1u;
	assert(nvt_validate_point_frame(fake_frame) == -1);
	memset(fake_frame, 0x77, 6);
	finish_frame();
	assert(nvt_validate_point_frame(fake_frame) == -1);
	memset(fake_frame, 0xfd, 6);
	finish_frame();
	assert(nvt_validate_point_frame(fake_frame) == -1);

	puts("NT36523 frame validation, GPIO mapping helpers and HID slot transitions passed.");
	return 0;
}
