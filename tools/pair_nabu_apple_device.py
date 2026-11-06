#!/usr/bin/env python3
"""Pair normally or validate an existing pairing, then start a real session."""
import argparse
import ctypes as C
import json
from pathlib import Path
import time
from probe_apple_mobile_device import AppleMobileDevice, NotificationCallback, return_code, utc_now


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    action=ap.add_mutually_exclusive_group(required=True)
    action.add_argument('--pair',action='store_true')
    action.add_argument('--validate-existing',action='store_true',help='Validate persisted pairing without sending Pair')
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    apple=AppleMobileDevice(Path('C:/Program Files/Common Files/Apple/Mobile Device Support'))
    for name in ('AMDevicePair','AMDeviceValidatePairing','AMDeviceStartSession','AMDeviceStopSession'):
        apple.bind(apple.am,name,C.c_int32,C.c_void_p)
    apple.bind(apple.am,'AMDErrorString',C.c_char_p,C.c_int32)
    report={'started_utc':utc_now(),'state':'waiting-device','pair_requested':a.pair,
            'pairing_verified':False,'session_verified':False,'sync_verified':False}
    def save():
        (a.output/'pairing.json').write_text(json.dumps(report,indent=2)+'\n')
    def result(code):
        name=apple.am.AMDErrorString(code)
        return {**return_code(code),'name':name.decode() if name else None}
    done=False
    @NotificationCallback
    def callback(info,context):
        nonlocal done
        if done or info.contents.message!=1:return
        done=True;device=info.contents.device;session=False;connected=False
        try:
            code=apple.am.AMDeviceConnect(device);report['connect']=result(code);save()
            if code:report['state']='connect-failed';return
            connected=True
            product=apple.copy_value(device,'ProductType');report['product_type']=product
            if product!='iPad7,11':report['state']='unexpected-product';return
            report['identifier']=apple.take_string(apple.am.AMDeviceCopyDeviceIdentifier(device))
            if a.pair:
                report['state']='pair-request';save()
                code=apple.am.AMDevicePair(device);report['pair']=result(code);save()
                if code:report['state']='pair-failed';return
            report['state']='validate-existing-pairing';save()
            code=apple.am.AMDeviceValidatePairing(device);report['validate']=result(code);save()
            if code:report['state']='validation-failed';return
            report['pairing_verified']=True
            code=apple.am.AMDeviceStartSession(device);report['start_session']=result(code);save()
            if code:report['state']='session-failed';return
            session=True;report['session_verified']=True;report['state']='session-verified'
        except Exception as error:report.update(state='error',error=str(error))
        finally:
            if session:report['stop_session']=result(apple.am.AMDeviceStopSession(device))
            if connected:report['disconnect']=result(apple.am.AMDeviceDisconnect(device))
            save()
    handle=C.c_void_p();save()
    code=apple.am.AMDeviceNotificationSubscribeWithOptions(callback,0,0,None,C.byref(handle),None)
    report['subscribe']=result(code);save()
    if code:report['state']='subscribe-failed'
    else:
        end=time.monotonic()+20
        try:
            while not done and time.monotonic()<end:
                apple.cf.CFRunLoopRunInMode(apple.default_mode,0.25,0)
        finally:apple.am.AMDeviceNotificationUnsubscribe(handle)
        if not done:report['state']='device-not-found'
    report['finished_utc']=utc_now();save();print(json.dumps(report,indent=2))


if __name__=='__main__':main()
