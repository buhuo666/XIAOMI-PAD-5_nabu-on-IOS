"""Offline 20F66 Hall interface inventory/disassembly from local shipped files."""
import argparse
import bisect
import json
from pathlib import Path
import struct
import capstone

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


class Image:
    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        self.sections, self.segments, self.names, self.starts = [], [], {}, []
        at = 32
        for _ in range(struct.unpack_from('<I', self.data, 16)[0]):
            cmd, size = struct.unpack_from('<II', self.data, at)
            if cmd == 0x19:
                seg = struct.unpack_from('<16s4Q', self.data, at+8)
                self.segments.append(seg)
                for n in range(struct.unpack_from('<I', self.data, at+64)[0]):
                    o = at+72+80*n
                    name, segment, va, length, off = struct.unpack_from('<16s16sQQI', self.data, o)
                    self.sections.append(dict(name=name.rstrip(b'\0').decode(), va=va, size=length, offset=off,
                                              reserved=struct.unpack_from('<II', self.data, o+68)))
            elif cmd == 2:
                symoff, nsyms, stroff, strsize = struct.unpack_from('<4I', self.data, at+8)
            elif cmd == 0xb:
                indirectoff, indirectcount = struct.unpack_from('<II', self.data, at+56)
            elif cmd == 0x26:
                startoff, startsize = struct.unpack_from('<II', self.data, at+8)
            elif cmd == 0x80000034:
                self.fixoff, self.fixsize = struct.unpack_from('<II', self.data, at+8)
            at += size
        self.base = next(s[1] for s in self.segments if s[0].rstrip(b'\0') == b'__TEXT')
        self.symbols = []
        for n in range(nsyms):
            so, typ, sec, desc, va = struct.unpack_from('<IBBHQ', self.data, symoff+16*n)
            name = self.data[stroff+so:self.data.index(0, stroff+so)].decode()
            self.symbols.append(name)
            if va: self.names[va] = name
        indirect = struct.unpack_from('<'+str(indirectcount)+'I', self.data, indirectoff)
        for s in self.sections:
            if s['name'] == '__stubs':
                index, stride = s['reserved']
                for n in range(s['size']//stride):
                    self.names[s['va']+n*stride] = self.symbols[indirect[index+n]]
        address = self.base
        value = shift = 0
        for byte in self.data[startoff:startoff+startsize]:
            value |= (byte & 127) << shift
            if byte & 128: shift += 7
            else:
                if not value: break
                address += value
                self.starts.append(address)
                value = shift = 0
        version, chains, imports, strings, count, fmt, symbols_fmt = struct.unpack_from('<7I', self.data, self.fixoff)
        assert fmt == 1 and symbols_fmt == 0
        self.imports = []
        for n in range(count):
            word = struct.unpack_from('<I', self.data, self.fixoff+imports+4*n)[0]
            o = self.fixoff+strings+(word>>9)
            self.imports.append(self.data[o:self.data.index(0,o)].decode())
        self.pointer_formats = {}
        scount = struct.unpack_from('<I', self.data, self.fixoff+chains)[0]
        for n in range(scount):
            off = struct.unpack_from('<I', self.data, self.fixoff+chains+4+4*n)[0]
            if off:
                f = struct.unpack_from('<H', self.data, self.fixoff+chains+off+6)[0]
                assert f in (2,6), f
                self.pointer_formats[self.segments[n][1]] = f
        self.methods = []
        classes = next((s for s in self.sections if s['name']=='__objc_classlist'), None)
        if classes:
            for n in range(classes['size']//8):
                cls = self.pointer(classes['va']+8*n)
                for kind, obj in (('-', cls), ('+', self.pointer(cls))):
                    ro = self.pointer(obj+32) & ~7
                    name = self.string(self.pointer(ro+24))
                    methods = self.pointer(ro+32)
                    if not methods: continue
                    flags, count = struct.unpack('<II', self.read(methods,8))
                    stride = flags & 0xfffc
                    for i in range(count):
                        loc = methods+8+i*stride
                        if flags & 0x80000000:
                            no, to, io = struct.unpack('<iii', self.read(loc,12))
                            selector = self.string(loc+no if flags & 0x40000000 else self.pointer(loc+no))
                            enc, imp = self.string(loc+4+to), loc+8+io
                        else:
                            selector, enc, imp = self.string(self.pointer(loc)), self.string(self.pointer(loc+8)), self.pointer(loc+16)
                        self.names[imp] = f'{kind}[{name} {selector}]'
                        self.methods.append(dict(address=hex(imp), name=self.names[imp], encoding=enc))

    def read(self, a, n):
        s = next(s for s in self.segments if s[4] and s[1] <= a and a+n <= s[1]+s[4])
        return self.data[s[3]+a-s[1]:s[3]+a-s[1]+n]

    def pointer(self, a):
        word = struct.unpack('<Q', self.read(a,8))[0]
        if word >> 63: return self.imports[word & 0xffffff]
        target = word & 0xfffffffff
        s = next(s for s in self.segments if s[1] <= a < s[1]+s[2])
        return target+self.base if target and self.pointer_formats.get(s[1])==6 else target

    def string(self, a):
        out = bytearray()
        while (b := self.read(a+len(out),1)) != b'\0': out.extend(b)
        return out.decode(errors='replace')

    def disassemble(self, a):
        end = self.starts[bisect.bisect_right(self.starts,a)]
        lines = []
        regs = {}
        for i in capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN).disasm(self.read(a,end-a),a):
            note = ''
            parts = i.op_str.split(', ')
            if i.mnemonic=='adrp': regs[parts[0]] = int(parts[1][1:],16)
            elif i.mnemonic=='add' and len(parts)==3 and parts[1] in regs and parts[2].startswith('#'):
                addr = regs[parts[1]]+int(parts[2][1:],0); regs[parts[0]]=addr
                if any(s['va']<=addr<s['va']+s['size'] and s['name'] in ('__cstring','__objc_methname','__oslogstring') for s in self.sections): note=repr(self.string(addr))
            elif i.mnemonic=='ldr' and '[' in i.op_str:
                src=parts[1].lstrip('[').rstrip(']')
                if src in regs:
                    addr=regs[src]+(int(parts[2].rstrip(']')[1:],0) if len(parts)>2 and parts[2].startswith('#') else 0)
                    try:
                        p=self.pointer(addr)
                        if isinstance(p,str): note=p
                        elif any(s['va']<=p<s['va']+s['size'] and s['name'] in ('__cstring','__objc_methname') for s in self.sections): note=self.string(p)
                        elif p in self.names:note=self.names[p]
                    except (StopIteration,ValueError,IndexError): pass
            if i.mnemonic in ('bl','b'): note=self.names.get(int(i.op_str[1:],16),'')
            lines.append(f'{i.address:#x} {i.mnemonic} {i.op_str}'+(' ; '+note if note else ''))
            if i.mnemonic=='bl':
                for r in range(19):regs.pop('x'+str(r),None)
        return dict(address=hex(a), name=self.names.get(a), bytes=end-a, assembly=lines)


def main():
    p=argparse.ArgumentParser()
    p.add_argument('path',type=Path)
    p.add_argument('--query',default='cover|hall|clamshell')
    p.add_argument('--address',action='append',default=[])
    a=p.parse_args()
    im=Image(a.path)
    name=a.path.name
    (OUT/(name+'-methods.json')).write_text(json.dumps(im.methods,indent=2)+'\n')
    if a.address:
        for address in a.address:
            d=im.disassemble(int(address,0))
            (OUT/(name+'-'+address+'.json')).write_text(json.dumps(d,indent=2)+'\n')
            print('\n'.join(d['assembly']))
    else:
        print('\n'.join(f'{addr:#x} {n}' for addr,n in im.names.items() if any(t in n.lower() for t in a.query.lower().split('|'))))


if __name__=='__main__': main()
