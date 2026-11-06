"""AFC roundtrip through the installed Windows Apple MobileDevice library.

MobileDevice 1860.49.2.1 disassembly confirms a pointer-sized SOCKET from
AMDeviceStartService, size_t lengths, and an opaque AFCConnection pointer.
"""
import ctypes as C
import uuid

from probe_apple_mobile_device import UTF8


def roundtrip(apple, device, report, save):
    am = apple.am
    apple.bind(am, 'AMDeviceStartService', C.c_int32,
               C.c_void_p, C.c_void_p, C.POINTER(C.c_size_t), C.c_void_p)
    apple.bind(am, 'AFCConnectionOpen', C.c_int32,
               C.c_size_t, C.c_size_t, C.POINTER(C.c_void_p))
    apple.bind(am, 'AFCConnectionClose', C.c_int32, C.c_void_p)
    apple.bind(am, 'AFCFileRefOpen', C.c_int32,
               C.c_void_p, C.c_char_p, C.c_uint64, C.POINTER(C.c_void_p))
    apple.bind(am, 'AFCFileRefWrite', C.c_int32,
               C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t)
    apple.bind(am, 'AFCFileRefRead', C.c_int32,
               C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_size_t))
    apple.bind(am, 'AFCFileRefClose', C.c_int32, C.c_void_p, C.c_void_p)
    apple.bind(am, 'AFCRemovePath', C.c_int32, C.c_void_p, C.c_char_p)
    result = report['native_afc'] = {'roundtrip_verified': False, 'removed': False}

    def check(name, code):
        result[name] = code
        save()
        if code:
            raise RuntimeError(f'{name} returned {code:#x}')

    service_name = apple.cf.CFStringCreateWithCString(None, b'com.apple.afc', UTF8)
    service_socket = C.c_size_t()
    try:
        check('start_service', am.AMDeviceStartService(device, service_name,
                                                      C.byref(service_socket), None))
    finally:
        apple.cf.CFRelease(service_name)
    connection = C.c_void_p()
    code = am.AFCConnectionOpen(service_socket, 0, C.byref(connection))
    if code:
        winsock = C.WinDLL('Ws2_32.dll')
        apple.bind(winsock, 'closesocket', C.c_int, C.c_size_t)
        winsock.closesocket(service_socket)
    check('connection_open', code)
    path = ('/nabu-native-afc-' + uuid.uuid4().hex + '.bin').encode()
    payload = bytes(range(256)) * 4096 + b'nabu-native-AFC-final-block'
    result.update(path=path.decode(), bytes=len(payload))
    created = False
    opened = False
    handle = C.c_void_p()
    try:
        check('file_open_write', am.AFCFileRefOpen(connection, path, 3, C.byref(handle)))
        created = opened = True
        for offset in range(0, len(payload), 32768):
            chunk = payload[offset:offset + 32768]
            check('file_write', am.AFCFileRefWrite(connection, handle, chunk, len(chunk)))
        check('file_close_write', am.AFCFileRefClose(connection, handle))
        opened = False
        check('file_open_read', am.AFCFileRefOpen(connection, path, 1, C.byref(handle)))
        opened = True
        received = bytearray()
        while len(received) < len(payload):
            count = C.c_size_t(min(32768, len(payload) - len(received)))
            buffer = C.create_string_buffer(count.value)
            check('file_read', am.AFCFileRefRead(connection, handle, buffer, C.byref(count)))
            if not count.value:
                raise EOFError('Native AFC returned EOF before the expected length')
            received.extend(buffer.raw[:count.value])
        result['readback_equal'] = bytes(received) == payload
        if not result['readback_equal']:
            raise RuntimeError('Native AFC readback differs from written bytes')
        check('file_close_read', am.AFCFileRefClose(connection, handle))
        opened = False
        result['roundtrip_verified'] = True
    finally:
        try:
            if opened:
                check('file_close_cleanup', am.AFCFileRefClose(connection, handle))
        finally:
            try:
                if created:
                    check('remove_path', am.AFCRemovePath(connection, path))
                    result['removed'] = True
            finally:
                check('connection_close', am.AFCConnectionClose(connection))
                save()
