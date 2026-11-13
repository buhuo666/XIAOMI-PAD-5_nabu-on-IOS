"""Encode original-board pd-mapper JSON into fixed records for the kernel trial."""
import json
import struct


def encode(directory):
    records=[]
    for path in sorted(directory.glob('*.jsn')):
        document=json.loads(path.read_text());domain=document['sr_domain']
        name='/'.join(domain[key] for key in ('soc','domain','subdomain')).encode()
        for service in document['sr_service']:
            identifier=(service['provider']+'/'+service['service']).encode()
            assert len(name)<64 and len(identifier)<64
            records.append(struct.pack('<64s64sIII',identifier,name,domain['qmi_instance_id'],
                service['service_data_valid'],service['service_data']))
    return b'NSR1'+struct.pack('<I',len(records))+b''.join(records)
