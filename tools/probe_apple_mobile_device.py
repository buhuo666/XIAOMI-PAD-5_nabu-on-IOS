#!/usr/bin/env python3
"""Observe Apple Mobile Device USB discovery and read basic lockdown values.

Uses the installed Windows Apple Mobile Device Support libraries. This probe
does not pair, validate pairing, start a session, or start device services.
"""
import argparse
import ctypes as C
import datetime
import json
import os
from pathlib import Path
import plistlib
import socket
import struct
import time


UTF8 = 0x08000100
VALUE_KEYS = (
    'ProductType', 'ProductVersion', 'BuildVersion', 'DeviceClass',
    'HardwareModel', 'ActivationState',
)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def return_code(value):
    return {'signed': value, 'hex': f'0x{value & 0xffffffff:08x}'}


def list_mux_devices():
    request = plistlib.dumps({
        'MessageType': 'ListDevices',
        'ClientVersionString': 'nabu-native-usb-readonly',
        'ProgName': 'nabu-native-usb-readonly',
        'kLibUSBMuxVersion': 3,
    })
    with socket.create_connection(('127.0.0.1', 27015), timeout=5) as connection:
        connection.sendall(struct.pack('<4I', len(request) + 16, 1, 8, 1) + request)

        def receive(size):
            data = bytearray()
            while len(data) < size:
                part = connection.recv(size - len(data))
                if not part:
                    raise EOFError('AMDS closed the ListDevices response')
                data.extend(part)
            return bytes(data)

        length, version, message_type, tag = struct.unpack('<4I', receive(16))
        response = plistlib.loads(receive(length - 16))
    return {
        'captured_utc': utc_now(),
        'transport': '127.0.0.1:27015',
        'header': {'length': length, 'version': version, 'type': message_type, 'tag': tag},
        'response': response,
    }


class NotificationInfo(C.Structure):
    _fields_ = [('device', C.c_void_p), ('message', C.c_uint32)]


NotificationCallback = C.CFUNCTYPE(None, C.POINTER(NotificationInfo), C.c_void_p)


class AppleMobileDevice:
    def __init__(self, directory):
        # Keep the search directory registered until both libraries are unused.
        self.dll_directory = os.add_dll_directory(str(directory))
        self.cf = C.CDLL(str(directory / 'CoreFoundation.dll'))
        self.am = C.CDLL(str(directory / 'MobileDevice.dll'))
        self.bind(self.cf, 'CFStringCreateWithCString', C.c_void_p,
                  C.c_void_p, C.c_char_p, C.c_uint32)
        self.bind(self.cf, 'CFStringGetLength', C.c_ssize_t, C.c_void_p)
        self.bind(self.cf, 'CFStringGetCString', C.c_ubyte,
                  C.c_void_p, C.c_void_p, C.c_ssize_t, C.c_uint32)
        self.bind(self.cf, 'CFGetTypeID', C.c_size_t, C.c_void_p)
        self.bind(self.cf, 'CFStringGetTypeID', C.c_size_t)
        self.bind(self.cf, 'CFCopyDescription', C.c_void_p, C.c_void_p)
        self.bind(self.cf, 'CFRelease', None, C.c_void_p)
        self.bind(self.cf, 'CFRunLoopRunInMode', C.c_int32,
                  C.c_void_p, C.c_double, C.c_ubyte)
        self.bind(self.am, 'AMDeviceNotificationSubscribeWithOptions', C.c_int32,
                  NotificationCallback, C.c_uint32, C.c_uint32, C.c_void_p,
                  C.POINTER(C.c_void_p), C.c_void_p)
        self.bind(self.am, 'AMDeviceNotificationUnsubscribe', C.c_int32, C.c_void_p)
        self.bind(self.am, 'AMDeviceConnect', C.c_int32, C.c_void_p)
        self.bind(self.am, 'AMDeviceDisconnect', C.c_int32, C.c_void_p)
        self.bind(self.am, 'AMDeviceIsPaired', C.c_int32, C.c_void_p)
        self.bind(self.am, 'AMDeviceCopyDeviceIdentifier', C.c_void_p, C.c_void_p)
        self.bind(self.am, 'AMDeviceGetConnectionID', C.c_uint32, C.c_void_p)
        self.bind(self.am, 'AMDeviceGetInterfaceType', C.c_int32, C.c_void_p)
        self.bind(self.am, 'AMDeviceCopyValue', C.c_void_p,
                  C.c_void_p, C.c_void_p, C.c_void_p)
        self.default_mode = C.c_void_p.in_dll(self.cf, 'kCFRunLoopDefaultMode')

    @staticmethod
    def bind(library, name, result, *arguments):
        function = getattr(library, name)
        function.restype = result
        function.argtypes = arguments

    def take_string(self, value):
        if not value:
            return None
        try:
            if self.cf.CFGetTypeID(value) != self.cf.CFStringGetTypeID():
                return self.take_string(self.cf.CFCopyDescription(value))
            buffer = C.create_string_buffer(self.cf.CFStringGetLength(value) * 4 + 1)
            if not self.cf.CFStringGetCString(value, buffer, len(buffer), UTF8):
                raise ValueError('CoreFoundation could not encode a value as UTF-8')
            return buffer.value.decode('utf-8')
        finally:
            self.cf.CFRelease(value)

    def copy_value(self, device, key):
        key_ref = self.cf.CFStringCreateWithCString(None, key.encode('utf-8'), UTF8)
        try:
            return self.take_string(self.am.AMDeviceCopyValue(device, None, key_ref))
        finally:
            self.cf.CFRelease(key_ref)

    def read_device(self, device, expected_product):
        result = {
            'connection_id': self.am.AMDeviceGetConnectionID(device),
            'interface_type': self.am.AMDeviceGetInterfaceType(device),
            'identifier': self.take_string(self.am.AMDeviceCopyDeviceIdentifier(device)),
        }
        code = self.am.AMDeviceConnect(device)
        result['connect'] = return_code(code)
        if code:
            return result
        try:
            # This is the library's status flag, not proof of a usable pairing.
            result['is_paired_status'] = self.am.AMDeviceIsPaired(device)
            product = self.copy_value(device, 'ProductType')
            result['expected_product_match'] = product == expected_product
            result['values'] = {'ProductType': product}
            if product == expected_product:
                for key in VALUE_KEYS[1:]:
                    result['values'][key] = self.copy_value(device, key)
        finally:
            result['disconnect'] = return_code(self.am.AMDeviceDisconnect(device))
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=15,
                        help='Notification observation time; native reads can extend this')
    parser.add_argument('--expected-product', default='iPad7,11')
    parser.add_argument('--dll-directory', type=Path,
                        default=Path('C:/Program Files/Common Files/Apple/Mobile Device Support'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {
        'started_utc': utc_now(), 'state': 'starting',
        'dll_directory': str(args.dll_directory),
        'expected_product': args.expected_product,
        'observation_seconds': args.seconds,
        'pairing_or_trust_changes': False,
        'pairing_verified': False, 'sync_verified': False,
        'events': [],
    }

    def save():
        (args.output / 'native-probe.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    save()
    try:
        report['amds_before'] = list_mux_devices()
        apple = AppleMobileDevice(args.dll_directory.resolve())
        report['libraries_loaded'] = True

        @NotificationCallback
        def callback(info, context):
            event = {'received_utc': utc_now(), 'message': info.contents.message}
            report['events'].append(event)
            try:
                if info.contents.message == 1:
                    event['device'] = apple.read_device(info.contents.device, args.expected_product)
            except Exception as error:
                event['error'] = f'{type(error).__name__}: {error}'
            save()
            print(json.dumps(event, ensure_ascii=False), flush=True)

        notification = C.c_void_p()
        code = apple.am.AMDeviceNotificationSubscribeWithOptions(
            callback, 0, 0, None, C.byref(notification), None)
        report['subscribe'] = return_code(code)
        if code:
            report['state'] = 'subscribe-failed'
        else:
            report['state'] = 'observing'
            save()
            print('Apple native notification subscription active', flush=True)
            try:
                deadline = time.monotonic() + args.seconds
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    report['last_run_loop_result'] = apple.cf.CFRunLoopRunInMode(
                        apple.default_mode, min(0.25, remaining), 0)
            except KeyboardInterrupt:
                report['interrupted'] = True
            finally:
                report['unsubscribe'] = return_code(
                    apple.am.AMDeviceNotificationUnsubscribe(notification))
            matches = [e for e in report['events']
                       if e.get('device', {}).get('expected_product_match')]
            report['state'] = 'expected-device-observed' if matches else 'expected-device-not-observed'
        report['amds_after'] = list_mux_devices()
    except Exception as error:
        report.update(state='probe-error', error=f'{type(error).__name__}: {error}')
    finally:
        report['finished_utc'] = utc_now()
        save()
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 1 if report['state'] in ('probe-error', 'subscribe-failed') else 0


if __name__ == '__main__':
    raise SystemExit(main())
