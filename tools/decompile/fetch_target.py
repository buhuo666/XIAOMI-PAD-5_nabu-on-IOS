"""Fetch only the pinned OS component from official Apple IPSW; no local uploads."""
import hashlib, io, json, urllib.request, zipfile, sys
from pathlib import Path
URL="https://updates.cdn-apple.com/2023SummerFCS/fullrestores/042-44385/366890C4-D9B5-4938-B399-C19FB58DBEE0/iPad_Pro_HFR_16.6.1_20G81_Restore.ipsw"
OS_SHA="449fc8ba53cbf5ccd5946d56586f454b21b7e43335332d3974940eaa7310c49e"
TARGET_SHA="b9ed5ef0594dc52ceebb561b74878c3467fba4cbbdb5b6b543dbb39b09fedcfa"
class Remote(io.RawIOBase):
 def __init__(self):
  self.pos=0; self.cache={}; self.block=8<<20
  with urllib.request.urlopen(urllib.request.Request(URL,headers={"Range":"bytes=0-0","Accept-Encoding":"identity"}),timeout=120) as r:
   if r.status!=206: raise ValueError("Range unsupported")
   self.size=int(r.headers["Content-Range"].split("/")[1])
 def readable(self): return True
 def seekable(self): return True
 def tell(self): return self.pos
 def seek(self,o,w=0):
  self.pos=(0,self.pos,self.size)[w]+o
  if not 0<=self.pos<=self.size: raise ValueError("invalid seek")
  return self.pos
 def readinto(self,b):
  count=min(len(b),self.size-self.pos); done=0
  while done<count:
   index,offset=divmod(self.pos,self.block)
   if index not in self.cache:
    start=index*self.block; end=min(start+self.block,self.size)-1
    request=urllib.request.Request(URL,headers={"Range":f"bytes={start}-{end}","Accept-Encoding":"identity"})
    with urllib.request.urlopen(request,timeout=120) as r:
     if r.status!=206 or r.headers.get("Content-Range")!=f"bytes {start}-{end}/{self.size}": raise ValueError("range mismatch")
     data=r.read(end-start+2)
    if len(data)!=end-start+1: raise ValueError("short range")
    if len(self.cache)>=4: self.cache.pop(next(iter(self.cache)))
    self.cache[index]=data
   data=self.cache[index][offset:offset+count-done]
   b[done:done+len(data)]=data; done+=len(data); self.pos+=len(data)
  return done
if __name__=="__main__":
 out=Path(sys.argv[1]); out.mkdir(exist_ok=True,parents=True)
 with Remote() as remote, zipfile.ZipFile(remote) as z:
  manifest=z.read("BuildManifest.plist")
  if hashlib.sha256(manifest).hexdigest()!="284e991153baa96f3a19ddb57b828ccddf871b4886aff9d9f936f957c19127c5": raise ValueError("manifest mismatch")
  entry=z.getinfo("096-57366-083.dmg")
  if entry.file_size!=4250815697: raise ValueError("OS size mismatch")
  h=hashlib.sha256()
  with z.open(entry) as src, (out/"os.dmg").open("xb") as dst:
   while data:=src.read(8<<20): dst.write(data); h.update(data)
  if h.hexdigest()!=OS_SHA: raise ValueError("OS hash mismatch")
 print("Official OS component verified",flush=True)
