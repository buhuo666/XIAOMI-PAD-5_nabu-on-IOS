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
uint32_t gNabuLogSlot, gNabuLogSpan, gNabuLogFlushed;
int gNabuLogRuntimeError;

// PE_parse_boot_argn accepts bare flags and also copies nonnumeric strings.
// A storage capability must instead have one explicit decimal slot value.
int nabuLogParseValue(const char *args,const char *key,uint32_t maximum,uint32_t *valueOut)
{
  if (!args || !key || !valueOut) return -1;
  size_t length=0;
  while (length<608 && args[length]) ++length;
  if (length==608) return -1;
  const size_t keyLength=strlen(key);
  bool found=false;
  for (size_t at=0;at<length;) {
    while (at<length && (args[at]==' ' || args[at]=='\t')) ++at;
    size_t end=at;
    while (end<length && args[end]!=' ' && args[end]!='\t') ++end;
    size_t n=end-at;
    if (n>=keyLength && !memcmp(args+at,key,keyLength) &&
        (n==keyLength || args[at+keyLength]=='=')) {
      if (found || n<=keyLength+1) return -1;
      uint32_t value=0;
      for (size_t i=at+keyLength+1;i<end;++i) {
        if (args[i]<'0' || args[i]>'9') return -1;
        value=value*10+uint32_t(args[i]-'0');
        if (value>maximum) return -1;
      }
      *valueOut=value; found=true;
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
  bool again=false;
  // Up to 8 MiB per callback. Give root readers the lock between records;
  // the old 1 MiB / 2 s budget could not keep up with measured console traffic.
  for (unsigned record=0;record<128;++record) {
    IOLockLock(gNabuReadLock);
    again=!gNabuLogFinishing && !gNabuLogRuntimeError && nabuLogIsOpen();
    bool pending=again && gNabuLogFlushed<nabu_log_capture_length();
    if (pending) again=nabuLogDrain(1);
    IOLockUnlock(gNabuReadLock);
    if (!again || !pending) break;
  }
  if (again) {
    uint64_t deadline;
    clock_interval_to_deadline(250,NSEC_PER_MSEC,&deadline);
    thread_call_enter_delayed(gNabuLogCall,deadline);
  }
}

int nabuLogBeginConfigured(void)
{
  uint32_t slot=0,span=1;
  int parsed=nabuLogParseValue(PE_boot_args(),"nabu-log-slot",15,&slot);
  int spanParsed=nabuLogParseValue(PE_boot_args(),"nabu-log-span",16,&span);
  if (!parsed && !spanParsed) return 0;
  gNabuLogSelected=true; gNabuLogSlot=slot; gNabuLogSpan=span;
  if (parsed!=1 || spanParsed<0 || !span || span>16-slot ||
      (spanParsed==1 && span==1)) return gNabuLogRuntimeError=EINVAL;
  gNabuLogCall=thread_call_allocate_with_priority(nabuLogPump,NULL,THREAD_CALL_PRIORITY_KERNEL);
  if (!gNabuLogCall) return gNabuLogRuntimeError=ENOMEM;
  IOLockLock(gNabuReadLock);
  bool opened=nabuLogStart(slot,span);
  IOLockUnlock(gNabuReadLock);
  if (!opened) return gNabuLogRuntimeError=EIO;
  loader_log_line("NABU LOG: append-only persistent capture started\n");
  uint64_t deadline;
  clock_interval_to_deadline(250,NSEC_PER_MSEC,&deadline);
  thread_call_enter_delayed(gNabuLogCall,deadline);
  return 0;
}
}

// The GPU worker checkpoints each hardware phase against the same committed
// prefix as recovery. It only observes this writer and never seals the log.
extern "C" int nabu_gpu_log_status(uint64_t *committed,uint32_t *error)
{
  *committed=0; *error=0;
  if (!gNabuReadLock) return 1;
  IOLockLock(gNabuReadLock);
  *committed=gNabuLogFlushed;
  *error=gNabuLogRuntimeError;
  int unavailable=!gNabuLogSelected || gNabuLogFinishing ||
      gNabuLogRuntimeError || !nabuLogIsOpen();
  IOLockUnlock(gNabuReadLock);
  return unavailable;
}

// Normal-thread diagnostic boundary, without sealing or a separate disk path.
// GPU188/189 stopped between the periodic pump's last prefix and the first
// display handover. Commit a fixed captured prefix before each traced step;
// release the shared root-read lock between records just as the pump does.
extern "C" int nabu_log_checkpoint(void)
{
  if (!gNabuReadLock || !gNabuLogSelected) return ENXIO;
  const uint32_t target=nabu_log_capture_length();
  for (;;) {
    IOLockLock(gNabuReadLock);
    int error=gNabuLogRuntimeError;
    if (!error && (gNabuLogFinishing || !nabuLogIsOpen())) error=EBUSY;
    if (!error && gNabuLogFlushed<target && !nabuLogDrain(1)) error=gNabuLogRuntimeError;
    const bool done=gNabuLogFlushed>=target;
    IOLockUnlock(gNabuReadLock);
    if (error || done) return error;
  }
}

extern "C" void nabu_log_append_report(void)
{
  if (!gNabuLogSelected) return;
  char line[224];
  snprintf(line,sizeof(line),
      "NABU LOG: slot=%u span=%u captured=%u saved=%u lost=%llu complete=%u errno=%d writer=%u records=%llu\n",
      gNabuLogSlot,gNabuLogSpan,nabu_log_capture_length(),gNabuLogFlushed,
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
