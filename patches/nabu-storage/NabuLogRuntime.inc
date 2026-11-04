// SPDX-License-Identifier: BSD-2-Clause-Patent
// Included after the validated Nabu storage implementation and log writer.
extern "C" const char *nabu_log_capture_data(void);
extern "C" uint32_t nabu_log_capture_length(void);
extern "C" uint64_t nabu_log_capture_lost(void);
extern "C" int nabu_log_capture_seal(void);
extern "C" void nabu_storage_append_report(void);

namespace {
thread_call_t gNabuLogCall;
bool gNabuLogSelected, gNabuLogFinishing, gNabuLogFinalized;
uint32_t gNabuLogSlot, gNabuLogFlushed;
int gNabuLogRuntimeError;

// PE_parse_boot_argn accepts bare flags and also copies nonnumeric strings.
// A storage capability must instead have one explicit decimal slot value.
int nabuLogParseSlot(const char *args,uint32_t *slot)
{
  if (!args || !slot) return -1;
  size_t length=0;
  while (length<608 && args[length]) ++length;
  if (length==608) return -1;
  const char key[]="nabu-log-slot";
  bool found=false;
  for (size_t at=0;at<length;) {
    while (at<length && (args[at]==' ' || args[at]=='\t')) ++at;
    size_t end=at;
    while (end<length && args[end]!=' ' && args[end]!='\t') ++end;
    size_t n=end-at;
    if (n>=sizeof(key)-1 && !memcmp(args+at,key,sizeof(key)-1) &&
        (n==sizeof(key)-1 || args[at+sizeof(key)-1]=='=')) {
      if (found || n<=sizeof(key)) return -1;
      uint32_t value=0;
      for (size_t i=at+sizeof(key);i<end;++i) {
        if (args[i]<'0' || args[i]>'9') return -1;
        value=value*10+uint32_t(args[i]-'0');
        if (value>=16) return -1;
      }
      *slot=value; found=true;
    }
    at=end;
  }
  return found?1:0;
}

// The read lock serializes log records with root reads. Capture bytes already
// published by the producer never change, so disk I/O holds no producer lock.
bool nabuLogDrain(unsigned maximumRecords)
{
  uint32_t length=nabu_log_capture_length();
  const char *data=nabu_log_capture_data();
  while (gNabuLogFlushed<length && maximumRecords--) {
    uint32_t take=length-gNabuLogFlushed;
    if (take>65536) take=65536;
    if (!nabuLogAppend(data+gNabuLogFlushed,take)) {
      gNabuLogRuntimeError=nabuLogLastError()==kNabuLogFull?ENOSPC:EIO;
      return false;
    }
    gNabuLogFlushed+=take;
  }
  return true;
}

void nabuLogPump(__unused thread_call_param_t p0,__unused thread_call_param_t p1)
{
  IOLockLock(gNabuReadLock);
  bool again=!gNabuLogFinishing && !gNabuLogRuntimeError && nabuLogIsOpen();
  if (again) again=nabuLogDrain(16);
  IOLockUnlock(gNabuReadLock);
  if (again) {
    uint64_t deadline;
    clock_interval_to_deadline(2,NSEC_PER_SEC,&deadline);
    thread_call_enter_delayed(gNabuLogCall,deadline);
  }
}

int nabuLogBeginConfigured(void)
{
  uint32_t slot=0;
  int parsed=nabuLogParseSlot(PE_boot_args(),&slot);
  if (!parsed) return 0;
  gNabuLogSelected=true; gNabuLogSlot=slot;
  if (parsed<0 || slot>=16) return gNabuLogRuntimeError=EINVAL;
  gNabuLogCall=thread_call_allocate_with_priority(nabuLogPump,NULL,THREAD_CALL_PRIORITY_KERNEL);
  if (!gNabuLogCall) return gNabuLogRuntimeError=ENOMEM;
  IOLockLock(gNabuReadLock);
  bool opened=nabuLogStart(slot);
  IOLockUnlock(gNabuReadLock);
  if (!opened) return gNabuLogRuntimeError=EIO;
  loader_log_line("NABU LOG: append-only persistent capture started\n");
  uint64_t deadline;
  clock_interval_to_deadline(2,NSEC_PER_SEC,&deadline);
  thread_call_enter_delayed(gNabuLogCall,deadline);
  return 0;
}
}

extern "C" void nabu_log_append_report(void)
{
  if (!gNabuLogSelected) return;
  char line[224];
  snprintf(line,sizeof(line),
      "NABU LOG: slot=%u captured=%u saved=%u lost=%llu complete=%u errno=%d writer=%u records=%llu\n",
      gNabuLogSlot,nabu_log_capture_length(),gNabuLogFlushed,
      (unsigned long long)nabu_log_capture_lost(),
      (gNabuLogFinalized && nabuLogHasEnded() && !nabuLogFinalStatus() && !nabuLogFinalLost())?1:0,
      gNabuLogRuntimeError,nabuLogLastError(),(unsigned long long)nabuLogCommittedRecords());
  loader_log_line(line);
}

// Called only by the normal return timer, before stopping CPUs or UFS. A panic
// never waits on this lock or starts new disk writes; recovery then exposes the
// last committed prefix as incomplete.
extern "C" void nabu_log_finish(void)
{
  if (!gNabuLogSelected || !gNabuReadLock) return;
  IOLockLock(gNabuReadLock);
  if (gNabuLogFinishing) { IOLockUnlock(gNabuReadLock); return; }
  gNabuLogFinishing=true;
  IOLockUnlock(gNabuReadLock);
  nabu_storage_append_report();
  loader_log_line("\n--- persistent runtime capture sealed before CPU/UFS shutdown ---\n");
  int seal=nabu_log_capture_seal();
  IOLockLock(gNabuReadLock);
  if (seal) gNabuLogRuntimeError=seal;
  if (!seal && nabuLogIsOpen()) {
    if (!gNabuLogRuntimeError) (void)nabuLogDrain(0xffffffffU);
    if (nabuLogIsOpen()) {
      uint64_t lost=nabu_log_capture_lost();
      if (!nabuLogEnd(lost,gNabuLogRuntimeError?gNabuLogRuntimeError:(lost?ENOSPC:0))) gNabuLogRuntimeError=EIO;
      else { gNabuLogFinalized=true; if (lost) gNabuLogRuntimeError=ENOSPC; }
    }
  }
  IOLockUnlock(gNabuReadLock);
  nabu_log_append_report();
}
