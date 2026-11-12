// SPDX-License-Identifier: MIT
// A device's family answer is immutable. Keep the runtime's exact answer,
// including NO for unknown values, without repeating its complete family audit.
// The association belongs to the Objective-C device; its ABI gains no ivars.
static char gFamilyAnswersKey;

static BOOL familyArgAnswer(id device,SEL cmd,NSUInteger arg) {
 @synchronized(device) {
  NSMutableDictionary<NSNumber *,NSNumber *> *answers=objc_getAssociatedObject(device,&gFamilyAnswersKey);
  NSNumber *key=@(arg),*cached=answers[key];
  if(cached)return cached.boolValue;
  uint64_t value=0;
  if(!nmb_device_answer(gDevice,sel_getName(cmd),arg,&value)) {
   // A failed query is not an immutable NO. Preserve the reason and retry it
   // on a later call, just as the original uncached flagArgAnswer does.
   NBLOG(@"native-metal: %s(%lu): %@",sel_getName(cmd),(unsigned long)arg,lastError());
   return NO;
  }
  const BOOL answer=value!=0;
  if(!answers) {
   answers=[NSMutableDictionary dictionary];
   objc_setAssociatedObject(device,&gFamilyAnswersKey,answers,OBJC_ASSOCIATION_RETAIN_NONATOMIC);
  }
  answers[key]=@(answer);
  return answer;
 }
}
