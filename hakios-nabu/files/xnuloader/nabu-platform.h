/*
 * Pure validation shared by the nabu loader and host tests.
 * Facts: the tablet's Android FDT, not the iPad user-space donor identity.
 */
#ifndef HAKIOS_NABU_PLATFORM_H
#define HAKIOS_NABU_PLATFORM_H

#include <stdint.h>
#include <stddef.h>

#define NBU_PAYLOAD_BASE       0xf0000000ULL
#define NBU_PAYLOAD_BYTES      0x04000000ULL
#define NBU_WINDOW_LIMIT       0x100000000ULL
#define NBU_GICD               0x17a00000ULL
#define NBU_GICR               0x17a60000ULL
#define NBU_COUNTER_HZ         19200000ULL
#define NBU_VIRTUAL_TIMER_IRQ  19u

struct nbu_fdt_facts {
	uint64_t gic_dist, gic_redist;
	uint32_t timer_irq, counter_hz, cpu_mask;
	uint32_t payload_reserved;
};

struct nbu_region {
	uint64_t base, bytes;
};

static uint32_t
nbu_be32(const void *p)
{
	const uint8_t *v = p;
	return (uint32_t)v[0] << 24 | (uint32_t)v[1] << 16 | (uint32_t)v[2] << 8 | v[3];
}

static int
nbu_text(const uint8_t *v, uint32_t bytes, const char *want)
{
	uint32_t n = 0;
	while (want[n]) {
		if (n >= bytes || v[n] != (uint8_t)want[n]) {
			return 0;
		}
		n++;
	}
	return n < bytes && v[n] == 0;
}

static int
nbu_string_list(const uint8_t *v, uint32_t bytes, const char *want)
{
	for (uint32_t at = 0; at < bytes;) {
		if (nbu_text(v + at, bytes - at, want)) {
			return 1;
		}
		while (at < bytes && v[at]) {
			at++;
		}
		if (at == bytes) {
			return 0;
		}
		at++;
	}
	return 0;
}

static int
nbu_range(uint64_t base, uint64_t bytes, uint64_t *end)
{
	if (bytes == 0 || bytes > UINT64_MAX - base) {
		return 0;
	}
	*end = base + bytes;
	return 1;
}

static int
nbu_overlap(uint64_t base, uint64_t bytes, uint64_t other, uint64_t other_bytes)
{
	uint64_t end, other_end;
	return !nbu_range(base, bytes, &end) || !nbu_range(other, other_bytes, &other_end) ||
	    (base < other_end && other < end);
}

/*
 * Read only after the caller proves the 40-byte header, then the declared
 * total size, are mapped RAM. No unbounded C-string reads of FDT data.
 */
static int
nbu_fdt(const void *blob, size_t available, struct nbu_fdt_facts *out)
{
	struct node {
		const uint8_t *reg, *interrupts;
		uint32_t reg_bytes, interrupt_bytes, address_cells, size_cells;
		uint32_t parent_address_cells, parent_size_cells, frequency;
		int gic, timer, psci, smc, cpu, reservations, payload_node, payload_marker, no_map;
	} stack[32] = {0};
	const uint8_t *data = blob;
	uint32_t total, tree, tree_bytes, strings, string_bytes, at, end;
	uint32_t depth = 0, roots = 0, gics = 0, timers = 0, pscis = 0, cpu_mask = 0;
	int board = 0, soc = 0, named = 0, ended = 0;
	struct nbu_fdt_facts facts = {0};

	if (available < 40 || nbu_be32(data) != 0xd00dfeedu) {
		return 0;
	}
	total = nbu_be32(data + 4);
	tree = nbu_be32(data + 8);
	strings = nbu_be32(data + 12);
	string_bytes = nbu_be32(data + 32);
	tree_bytes = nbu_be32(data + 36);
	if (total > available || total < 40 || nbu_be32(data + 20) < 17 ||
	    tree < 40 || tree > total || tree_bytes > total - tree ||
	    strings < 40 || strings > total || string_bytes > total - strings ||
	    (tree < strings + string_bytes && strings < tree + tree_bytes)) {
		return 0;
	}
	at = tree;
	end = tree + tree_bytes;
	while (at <= end && end - at >= 4) {
		uint32_t token = nbu_be32(data + at);
		at += 4;
		if (token == 1) {
			if (depth == 32) {
				return 0;
			}
			struct node node = { .address_cells = 2, .size_cells = 1 };
			if (depth) {
				node.parent_address_cells = stack[depth - 1].address_cells;
				node.parent_size_cells = stack[depth - 1].size_cells;
			} else {
				roots++;
			}
			node.reservations = depth == 1 && nbu_text(data + at, end - at, "reserved-memory");
			node.payload_node = depth == 2 && stack[depth - 1].reservations &&
			    nbu_text(data + at, end - at, "hakios-payload@f0000000");
			while (at < end && data[at]) {
				at++;
			}
			if (at == end || at > UINT32_MAX - 4) {
				return 0;
			}
			at = (at + 4) & ~3u;
			stack[depth++] = node;
		} else if (token == 2) {
			if (!depth) {
				return 0;
			}
			struct node *n = &stack[--depth];
			if (n->payload_node) {
				uint32_t ac = n->parent_address_cells, sc = n->parent_size_cells;
				if (facts.payload_reserved || !n->payload_marker || n->no_map || ac < 1 || ac > 2 ||
				    sc < 1 || sc > 2 || n->reg_bytes != (ac + sc) * 4) {
					return 0;
				}
				uint64_t base = 0, bytes = 0;
				for (uint32_t i = 0; i < ac; i++) {
					base = base << 32 | nbu_be32(n->reg + i * 4);
				}
				for (uint32_t i = 0; i < sc; i++) {
					bytes = bytes << 32 | nbu_be32(n->reg + (ac + i) * 4);
				}
				if (base != NBU_PAYLOAD_BASE || bytes != NBU_PAYLOAD_BYTES) {
					return 0;
				}
				facts.payload_reserved = 1;
			}
			if (n->gic) {
				uint32_t ac = n->parent_address_cells, sc = n->parent_size_cells, width = ac + sc;
				if (++gics != 1 || ac < 1 || ac > 2 || sc < 1 || sc > 2 ||
				    n->reg_bytes != 2 * width * 4) {
					return 0;
				}
				uint64_t values[4] = {0};
				for (uint32_t part = 0; part < 2; part++) {
					const uint8_t *reg = n->reg + part * width * 4;
					for (uint32_t i = 0; i < ac; i++) {
						values[part * 2] = values[part * 2] << 32 | nbu_be32(reg + i * 4);
					}
					for (uint32_t i = 0; i < sc; i++) {
						values[part * 2 + 1] = values[part * 2 + 1] << 32 | nbu_be32(reg + (ac + i) * 4);
					}
				}
				if (values[0] != NBU_GICD || values[1] != 0x10000 ||
				    values[2] != NBU_GICR || values[3] != 0x100000) {
					return 0;
				}
				facts.gic_dist = values[0];
				facts.gic_redist = values[2];
			}
			if (n->timer) {
				if (++timers != 1 || n->interrupt_bytes < 36 || n->interrupt_bytes % 12 ||
				    nbu_be32(n->interrupts + 24) != 1 ||
				    nbu_be32(n->interrupts + 28) != NBU_VIRTUAL_TIMER_IRQ - 16 ||
				    n->frequency != NBU_COUNTER_HZ) {
					return 0;
				}
				facts.timer_irq = NBU_VIRTUAL_TIMER_IRQ;
				facts.counter_hz = n->frequency;
			}
			if (n->psci && (++pscis != 1 || !n->smc)) {
				return 0;
			}
			if (n->cpu) {
				uint32_t ac = n->parent_address_cells;
				if ((ac != 1 && ac != 2) || n->reg_bytes != ac * 4) {
					return 0;
				}
				uint64_t mpidr = ac == 2 ? (uint64_t)nbu_be32(n->reg) << 32 : 0;
				mpidr |= nbu_be32(n->reg + (ac - 1) * 4);
				if (mpidr > 0x700 || (mpidr & 0xff) || (cpu_mask & (1u << (mpidr >> 8)))) {
					return 0;
				}
				cpu_mask |= 1u << (mpidr >> 8);
			}
		} else if (token == 3) {
			if (!depth || end - at < 8) {
				return 0;
			}
			uint32_t bytes = nbu_be32(data + at), name_offset = nbu_be32(data + at + 4);
			at += 8;
			if (bytes > end - at || name_offset >= string_bytes) {
				return 0;
			}
			const uint8_t *name = data + strings + name_offset, *value = data + at;
			uint32_t name_bytes = string_bytes - name_offset;
			uint32_t name_end = 0;
			while (name_end < name_bytes && name[name_end]) {
				name_end++;
			}
			if (name_end == name_bytes) {
				return 0;
			}
			struct node *n = &stack[depth - 1];
			if (nbu_text(name, name_bytes, "#address-cells") || nbu_text(name, name_bytes, "#size-cells")) {
				/* Other buses (PCI, for example) may use three address cells. */
				if (bytes != 4) {
					return 0;
				}
				if (name[1] == 'a') {
					n->address_cells = nbu_be32(value);
				} else {
					n->size_cells = nbu_be32(value);
				}
			} else if (nbu_text(name, name_bytes, "compatible")) {
				if (depth == 1) {
					soc = nbu_string_list(value, bytes, "qcom,sm8150");
					board = nbu_string_list(value, bytes, "xiaomi,nabu");
				}
				n->gic = nbu_string_list(value, bytes, "arm,gic-v3");
				n->timer = nbu_string_list(value, bytes, "arm,armv8-timer");
				n->psci = nbu_string_list(value, bytes, "arm,psci-1.0") ||
				    nbu_string_list(value, bytes, "arm,psci-0.2");
				n->payload_marker = nbu_string_list(value, bytes, "hakios,payload");
			} else if (depth == 1 && nbu_text(name, name_bytes, "model")) {
				named = nbu_text(value, bytes, "NABU");
			} else if (nbu_text(name, name_bytes, "reg")) {
				n->reg = value;
				n->reg_bytes = bytes;
			} else if (nbu_text(name, name_bytes, "interrupts")) {
				n->interrupts = value;
				n->interrupt_bytes = bytes;
			} else if (nbu_text(name, name_bytes, "clock-frequency") && bytes == 4) {
				n->frequency = nbu_be32(value);
			} else if (nbu_text(name, name_bytes, "method")) {
				n->smc = nbu_text(value, bytes, "smc");
			} else if (nbu_text(name, name_bytes, "device_type")) {
				n->cpu = nbu_text(value, bytes, "cpu");
			} else if (nbu_text(name, name_bytes, "no-map")) {
				n->no_map = 1;
			}
			if (at > UINT32_MAX - bytes - 3) {
				return 0;
			}
			at = (at + bytes + 3) & ~3u;
		} else if (token == 9) {
			if (depth || roots != 1) {
				return 0;
			}
			ended = 1;
			break;
		} else if (token != 4) {
			return 0;
		}
	}
	if (!ended || !soc || !(board || named) || gics != 1 || timers != 1 || pscis != 1 || cpu_mask != 0xff) {
		return 0;
	}
	facts.cpu_mask = cpu_mask;
	*out = facts;
	return 1;
}

/* A map record is admitted only when it has a complete descriptor stride. */
static int
nbu_map_valid(uint64_t bytes, uint64_t stride)
{
	return stride >= 40 && stride <= 4096 && stride % 8 == 0 && bytes != 0 && bytes % stride == 0;
}

static uint64_t
nbu_le64(const uint8_t *v)
{
	uint64_t value = 0;
	for (unsigned i = 0; i < 8; i++) {
		value |= (uint64_t)v[i] << (8 * i);
	}
	return value;
}

static int
nbu_map_covers(const void *map, uint64_t map_bytes, uint64_t stride,
    uint64_t start, uint64_t bytes, uint32_t allowed)
{
	const uint8_t *data = map;
	uint64_t end;
	if (!nbu_map_valid(map_bytes, stride) || !nbu_range(start, bytes, &end)) {
		return 0;
	}
	while (start < end) {
		uint64_t next = start;
		for (uint64_t at = 0; at < map_bytes; at += stride) {
			const uint8_t *d = data + at;
			uint32_t type = (uint32_t)nbu_le64(d);
			uint64_t lo = nbu_le64(d + 8), pages = nbu_le64(d + 24), hi;
			uint64_t attributes = nbu_le64(d + 32);
			if (type >= 32 || !(allowed & (1u << type)) || pages > (UINT64_MAX >> 12) ||
			    !nbu_range(lo, pages << 12, &hi) || (attributes & 0x2000ULL) ||
			    (allowed == ((1u << 2) | (1u << 4)) && attributes & (0x1000ULL | 0x20000ULL))) {
				continue;
			}
			if (lo <= start && hi > next) {
				next = hi;
			}
		}
		if (next == start) {
			return 0;
		}
		start = next;
	}
	return 1;
}

/* Subtract every live reservation before choosing one aligned contiguous window. */
static struct nbu_region
nbu_window(uint64_t base, uint64_t bytes, const struct nbu_region *excluded,
    unsigned count, uint64_t cap)
{
	struct nbu_region pieces[8] = {{base, bytes}}, result = {0};
	unsigned used = 1;
	uint64_t end;
	if (!nbu_range(base, bytes, &end) || count > 6 || cap == 0) {
		return result;
	}
	for (unsigned i = 0; i < count; i++) {
		if (!excluded[i].bytes) {
			continue;
		}
		uint64_t cut_end;
		if (!nbu_range(excluded[i].base, excluded[i].bytes, &cut_end)) {
			return result;
		}
		unsigned original = used;
		for (unsigned j = 0; j < original; j++) {
			uint64_t lo = pieces[j].base, hi = lo + pieces[j].bytes;
			if (!pieces[j].bytes || lo >= cut_end || excluded[i].base >= hi) {
				continue;
			}
			uint64_t left = excluded[i].base > lo ? excluded[i].base - lo : 0;
			if (cut_end < hi) {
				if (used == 8) {
					return result;
				}
				pieces[used++] = (struct nbu_region){cut_end, hi - cut_end};
			}
			pieces[j].bytes = left;
		}
	}
	for (unsigned i = 0; i < used; i++) {
		uint64_t lo = pieces[i].base, hi = lo + pieces[i].bytes;
		if (!pieces[i].bytes || lo > UINT64_MAX - 0x1ffffff) {
			continue;
		}
		lo = (lo + 0x1ffffff) & ~0x1ffffffULL;
		hi &= ~0x1ffffffULL;
		uint64_t room = hi > lo ? hi - lo : 0;
		if (room > cap) {
			room = cap & ~0x1ffffffULL;
		}
		if (room > result.bytes) {
			result = (struct nbu_region){lo, room};
		}
	}
	return result;
}

/* Bring-up stays single-core and cannot enable the reference board's devices. */
static int
nbu_boot_args(const char *args)
{
	for (const char *p = args; *p;) {
		while (*p == ' ') {
			p++;
		}
		const char *end = p;
		while (*end && *end != ' ') {
			end++;
		}
		uint32_t len = (uint32_t)(end - p);
		static const char *const blocked[] = {
			"bootcpu=", "cpumask=", "ufs=", "ufs_", "ufsroot=", "ufsrw=", "rootrw=", "var_store=",
			"gpu=", "adreno=", "cpufreq=", "touchscreen=", "battery=", "adsp=", "sound=",
			"mic=", "wifi=", "modem=", "haptic=", "cam=", "torch=", "pmic=", "thermal="
		};
		for (uint32_t i = 0; i < sizeof(blocked) / sizeof(blocked[0]); i++) {
			uint32_t n = 0;
			while (n < len && blocked[i][n] && p[n] == blocked[i][n]) {
				n++;
			}
			if (!blocked[i][n]) {
				return 0;
			}
		}
		if (len >= 5 && p[0] == 'c' && p[1] == 'p' && p[2] == 'u' && p[3] == 's' && p[4] == '=' &&
		    !(len == 6 && p[5] == '1')) {
			return 0;
		}
		p = end;
	}
	return 1;
}

#endif
