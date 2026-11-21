// SPDX-License-Identifier: MIT
#pragma once

#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <mutex>
#include <sys/sysctl.h>
#include <unistd.h>

namespace systemformatpolicy {

// The installed board policy changes 21H461's signed text during page-in.
// This reader identifies the loaded frameworks by UUID and records whether
// their instruction words contain those changes. It never writes framework
// memory. The plugin reports each observed state transition through its sink.
enum class State : unsigned {
    Waiting,
    Applied,
    Original,
    UnexpectedInstruction,
    UnsupportedImage,
};

struct Instruction {
    uintptr_t address;
    uint32_t original;
    uint32_t replacement;
};

static std::atomic<State> renderBox{State::Waiting};
static std::atomic<State> quartzCore{State::Waiting};
static std::atomic<unsigned> requested{0};
static const char *stateName(State state);

static void reportImage(const char *name, State state)
{
    char text[128];
    int size = snprintf(text, sizeof(text), "native-metal: 21H461 format policy %s state=%s\n", name, stateName(state));
    if (size > 0 && size < int(sizeof(text))) {
        (void)write(STDERR_FILENO, text, size_t(size));
    }
}

static State readInstructions(intptr_t slide, const Instruction *instructions, size_t count)
{
    bool foundOriginal = false;
    for (size_t index = 0; index < count; ++index) {
        const Instruction &instruction = instructions[index];
        const auto *address = reinterpret_cast<const volatile uint32_t *>(instruction.address + slide);
        uint32_t actual = *address;
        if (actual == instruction.original) {
            foundOriginal = true;
        } else if (actual != instruction.replacement) {
            return State::UnexpectedInstruction;
        }
    }

    return foundOriginal ? State::Original : State::Applied;
}

static void imageAdded(const mach_header *header, intptr_t slide)
{
    if (header->magic != MH_MAGIC_64) {
        return;
    }

    const auto *image = reinterpret_cast<const mach_header_64 *>(header);
    const auto *cursor = reinterpret_cast<const uint8_t *>(image + 1);
    const uint8_t *end = cursor + image->sizeofcmds;
    const char *name = nullptr;
    const uint8_t *uuid = nullptr;
    for (uint32_t index = 0; index < image->ncmds; ++index) {
        if (size_t(end - cursor) < sizeof(load_command)) {
            return;
        }

        const auto *command = reinterpret_cast<const load_command *>(cursor);
        if (command->cmdsize < sizeof(load_command) || command->cmdsize > size_t(end - cursor)) {
            return;
        }
        if (command->cmd == LC_ID_DYLIB && command->cmdsize >= sizeof(dylib_command)) {
            const auto *library = reinterpret_cast<const dylib_command *>(cursor);
            uint32_t offset = library->dylib.name.offset;
            if (offset < command->cmdsize && memchr(cursor + offset, 0, command->cmdsize - offset)) {
                name = reinterpret_cast<const char *>(cursor + offset);
            }
        } else if (command->cmd == LC_UUID && command->cmdsize >= sizeof(uuid_command)) {
            uuid = reinterpret_cast<const uuid_command *>(cursor)->uuid;
        }
        cursor += command->cmdsize;
    }

    if (!name) {
        return;
    }

    if (strcmp(name, "/System/Library/PrivateFrameworks/RenderBox.framework/RenderBox") == 0) {
        static const uint8_t expectedUuid[] = {
            0x94, 0x7f, 0xcc, 0xe5, 0x18, 0x83, 0x3b, 0x77,
            0x8d, 0x1e, 0x04, 0x62, 0x5b, 0x7e, 0x8e, 0xb4,
        };
        static const Instruction instructions[] = {
            // ColorMode::pixel_format returns its existing BGRA80/81 choice
            // for ordinary RGB8 output. ColorSpace and alpha flags remain
            // outputs of the original function before resource allocation.
            {0x1e262844c, 0x3617fcc2, 0x17ffffe8},
        };
        State state = uuid && memcmp(uuid, expectedUuid, sizeof(expectedUuid)) == 0 ?
            readInstructions(slide, instructions, sizeof(instructions) / sizeof(instructions[0])) :
            State::UnsupportedImage;
        renderBox.store(state, std::memory_order_release);
        reportImage("RenderBox", state);
    } else if (strcmp(name, "/System/Library/Frameworks/QuartzCore.framework/QuartzCore") == 0) {
        static const uint8_t expectedUuid[] = {
            0xbc, 0xa7, 0x4c, 0xf2, 0x23, 0x6a, 0x30, 0xac,
            0xbd, 0x05, 0x88, 0x72, 0xb2, 0xc2, 0x26, 0x2d,
        };
        static const Instruction instructions[] = {
            {0x18957be88, 0x39384260, 0x3938427f},
            {0x18957bec0, 0x39384268, 0x3938427f},
            {0x1894d9f04, 0x39308100, 0x3930811f},
            {0x1894d9ea8, 0x39254100, 0x3925411f},
            {0x189682ae8, 0x393b0128, 0x393b013f},
            {0x189683b80, 0x393b8100, 0x393b811f},
            {0x189683ce4, 0x3923c109, 0x3923c11f},
        };
        State state = uuid && memcmp(uuid, expectedUuid, sizeof(expectedUuid)) == 0 ?
            readInstructions(slide, instructions, sizeof(instructions) / sizeof(instructions[0])) :
            State::UnsupportedImage;
        quartzCore.store(state, std::memory_order_release);
        reportImage("QuartzCore", state);
    }
}

static void start(const char *path)
{
    static std::once_flag once;
    std::call_once(once, [path] {
        FILE *file = fopen(path, "r");
        if (!file) {
            return;
        }

        char version[64] = {};
        char *line = fgets(version, sizeof(version), file);
        fclose(file);
        version[strcspn(version, "\r\n")] = 0;
        if (!line || strcmp(version, "21H461-srgb-bgra8-1") != 0) {
            requested.store(3, std::memory_order_release);
            return;
        }

        char build[32] = {};
        size_t size = sizeof(build);
        if (sysctlbyname("kern.osversion", build, &size, nullptr, 0) != 0 || strcmp(build, "21H461") != 0) {
            requested.store(2, std::memory_order_release);
            return;
        }

        requested.store(1, std::memory_order_release);
        // dyld visits images already loaded and invokes this callback for
        // future images before their initializers. The callback only reads
        // Mach-O headers and text; it performs no loader or Objective-C calls.
        _dyld_register_func_for_add_image(imageAdded);
    });
}

static unsigned statusCode()
{
    return requested.load(std::memory_order_acquire) |
        (unsigned(renderBox.load(std::memory_order_acquire)) << 4) |
        (unsigned(quartzCore.load(std::memory_order_acquire)) << 8);
}

static const char *stateName(State state)
{
    switch (state) {
        case State::Waiting:
            return "unloaded";
        case State::Applied:
            return "applied";
        case State::Original:
            return "not-applied";
        case State::UnexpectedInstruction:
            return "bad-code";
        case State::UnsupportedImage:
            return "bad-uuid";
    }
    return "unknown";
}

static void status(char *text, size_t size)
{
    unsigned mode = requested.load(std::memory_order_acquire);
    const char *os = mode == 1 ? "21H461" : mode == 2 ? "unsupported" : mode == 3 ? "bad-version" : "disabled";
    snprintf(text, size, "FMT %s RB=%s CA=%s", os,
        stateName(renderBox.load(std::memory_order_acquire)),
        stateName(quartzCore.load(std::memory_order_acquire)));
}

} // namespace systemformatpolicy
