// Actual Foundation/Objective-C objects and complete production frontend bundle.
// No Rust/GPU calls. Zero-handle probes use NSObject's real dealloc implementation.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <cstring>
#include <stdexcept>
#include <string>
#include "protocol-type-comparator.inc"

static Protocol *requiredProtocol(NSString *name) {
#include "protocol-references.inc"
 return objc_getProtocol(name.UTF8String);
}
static id probe(Class cls,unsigned serial) {
 NSString *name=[NSString stringWithFormat:@"NBProtocolProbe%u",serial];
 Class child=objc_allocateClassPair(cls,name.UTF8String,0);
 class_addMethod(child,sel_registerName("dealloc"),class_getMethodImplementation([NSObject class],sel_registerName("dealloc")),"v16@0:8");
 objc_registerClassPair(child);
 return class_createInstance(child,0);
}
int main(int argc,char **argv) {@autoreleasepool {
 if(argc!=5)return 64;
 bool fixed=!strcmp(argv[3],"fixed");
 NSMutableArray *failures=[NSMutableArray array],*rows=[NSMutableArray array],*typed=[NSMutableArray array];
 auto check=[&](bool ok,NSString *message){if(!ok)[failures addObject:message];};
 NSError *error=nil;
 NSDictionary *manifest=[NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:@(argv[2])] options:0 error:&error];
 if(!manifest){fprintf(stderr,"manifest: %s\n",error.description.UTF8String);return 65;}
 void *bundle=dlopen(argv[1],RTLD_LAZY|RTLD_LOCAL);
 if(!bundle){fprintf(stderr,"dlopen: %s\n",dlerror());return 66;}
 auto install=(Class(*)(void))dlsym(bundle,"nabu_test_install_protocols");
 if(!install)return 67;
 Class device=install();unsigned serial=0,missingClass=0,missingInstance=0,methodChecks=0,negativeChecks=0,inheritanceChecks=0;
 NSArray *classes=manifest[@"classes"];
 for(NSDictionary *row in classes){
  NSString *name=row[@"cls"],*protocolName=row[@"protocol"];Class cls=objc_getClass(name.UTF8String);
  Protocol *protocol=requiredProtocol(protocolName);check(cls&&protocol,[NSString stringWithFormat:@"missing class/protocol %@ %@",name,protocolName]);
  if(!cls||!protocol)continue;
  id object=probe(cls,++serial);
  bool classOK=class_conformsToProtocol(cls,protocol),instanceOK=[object conformsToProtocol:protocol];
  if(!classOK)missingClass++;if(!instanceOK)missingInstance++;
  check(classOK,[name stringByAppendingString:@" class does not conform"]);
  check(instanceOK,[name stringByAppendingString:@" instance does not conform"]);
  if(!fixed){
   check(classOK==[row[@"baseline_class_conforms"] boolValue],[name stringByAppendingString:@" unexpected baseline metadata"]);
   check(instanceOK==[row[@"baseline_instance_conforms"] boolValue],[name stringByAppendingString:@" unexpected baseline instance"]);
  }
  for(NSString *parent in row[@"protocol_closure"]){
   if([parent isEqualToString:protocolName])continue;
   Protocol *p=requiredProtocol(parent);inheritanceChecks++;
   if(fixed)check(p&&class_conformsToProtocol(cls,p)&&[object conformsToProtocol:p],[name stringByAppendingFormat:@" missing inherited %@",parent]);
  }
  for(NSDictionary *other in classes){
   NSString *otherName=other[@"protocol"];
   if([row[@"protocol_closure"] containsObject:otherName])continue;
   negativeChecks++;Protocol *p=requiredProtocol(otherName);
   check(p&&!class_conformsToProtocol(cls,p)&&![object conformsToProtocol:p],[name stringByAppendingFormat:@" falsely claims %@",otherName]);
  }
  [rows addObject:@{@"class":name,@"protocol":protocolName,@"class_conforms":@(classOK),@"instance_conforms":@(instanceOK),@"inherits":row[@"protocol_closure"]}];
 }
 for(NSDictionary *row in manifest[@"required_methods"]){
  Class cls=objc_getClass([row[@"frontend_class"] UTF8String]);SEL selector=sel_registerName([row[@"selector"] UTF8String]);
  Method method=class_getInstanceMethod(cls,selector);methodChecks++;
  check(method!=nullptr,[NSString stringWithFormat:@"missing required %@ %@",row[@"frontend_class"],row[@"selector"]]);
  if(method)check(signaturesEqual(describeSignature(method_getTypeEncoding(method)),describeSignature([row[@"encoding"] UTF8String])),[NSString stringWithFormat:@"wrong required ABI %@ %@",row[@"frontend_class"],row[@"selector"]]);
 }
 // Real per-instance binding kind must not become a blanket typed-protocol claim.
 NSArray *fixtures=@[
  @{@"type":@(MTLBindingTypeBuffer),@"bufferAlignment":@4},
  @{@"type":@(MTLBindingTypeThreadgroupMemory),@"threadgroupMemoryAlignment":@4},
  @{@"type":@(MTLBindingTypeTexture),@"textureType":@(MTLTextureType2D)},
  @{@"type":@(MTLBindingTypeObjectPayload),@"objectPayloadAlignment":@16},
  @{@"type":@(MTLBindingTypeSampler)},@{@"type":@(MTLBindingTypeImageblockData)},
  @{@"type":@(MTLBindingTypeImageblock)},@{@"type":@(MTLBindingTypeVisibleFunctionTable)},
  @{@"type":@(MTLBindingTypePrimitiveAccelerationStructure)},@{@"type":@(MTLBindingTypeInstanceAccelerationStructure)},
  @{@"type":@(MTLBindingTypeIntersectionFunctionTable)}];
 NSArray *expected=@[@"MTLBufferBinding",@"MTLThreadgroupBinding",@"MTLTextureBinding",@"MTLObjectPayloadBinding",@"",@"",@"",@"",@"",@"",@""];
 for(NSUInteger i=0;i<fixtures.count;i++){
  id object=probe(objc_getClass("NBReflectedBinding"),++serial);
  [object setValue:fixtures[i] forKey:@"nbData"];
  for(NSString *name in manifest[@"typed_bindings"]){
   BOOL actual=[object conformsToProtocol:requiredProtocol(name)],wanted=[name isEqualToString:expected[i]];
   check(actual==wanted,[NSString stringWithFormat:@"typed binding %@ erroneously reports %@",fixtures[i],name]);
   [typed addObject:@{@"kind":fixtures[i][@"type"],@"protocol":name,@"conforms":@(actual),@"expected":@(wanted)}];
  }
 }
 // The device metadata helper is production code. The donor is never a device.
 check(device&&class_conformsToProtocol(device,@protocol(MTLDevice)),@"actual device class lacks MTLDevice");
 id deviceObject=probe(device,++serial);
 check([deviceObject conformsToProtocol:@protocol(MTLDevice)],@"actual device instance lacks MTLDevice");
 Protocol *spi=objc_getProtocol("MTLDeviceSPI");
 if(spi)check(class_conformsToProtocol(device,spi)&&[deviceObject conformsToProtocol:spi],@"actual device class/instance lacks available MTLDeviceSPI");
 for(NSString *helper in manifest[@"unregistered_helpers"]){
  Class cls=objc_getClass(helper.UTF8String);id object=probe(cls,++serial);
  for(NSDictionary *row in classes){Protocol *p=requiredProtocol(row[@"protocol"]);check(!class_conformsToProtocol(cls,p)&&![object conformsToProtocol:p],[helper stringByAppendingFormat:@" falsely claims %@",row[@"protocol"]]);}
  check(!class_conformsToProtocol(cls,@protocol(MTLDevice))&&![object conformsToProtocol:@protocol(MTLDevice)],[helper stringByAppendingString:@" falsely claims device"]);
 }
 NSDictionary *wrappers=manifest[@"objc_class_wrappers"];
 for(NSString *name in wrappers){
  Class cls=objc_getClass(name.UTF8String),parent=objc_getClass([wrappers[name] UTF8String]);
  check(cls&&parent&&class_getSuperclass(cls)==parent,[name stringByAppendingString:@" changed native class inheritance"]);
  unsigned count=0;Protocol *__unsafe_unretained *own=class_copyProtocolList(cls,&count);
  check(count==0,[name stringByAppendingString:@" received unrelated explicit protocol metadata"]);free(own);
 }
 id command=probe(objc_getClass("NBCommandBuffer"),++serial);
 BOOL mpsGate=[command conformsToProtocol:@protocol(MTLCommandBuffer)];
 check(mpsGate==fixed,@"MPS cache's exact public-protocol gate did not reproduce baseline/fix");
 NSDictionary *report=@{@"variant":@(argv[3]),@"root_class_checks":@(classes.count),@"missing_class_conformance":@(missingClass),
  @"missing_instance_conformance":@(missingInstance),@"inherited_protocol_checks":@(inheritanceChecks),@"negative_protocol_checks":@(negativeChecks),
  @"required_method_abi_checks":@(methodChecks),@"typed_binding_checks":@(typed.count),@"native_class_wrapper_checks":@(wrappers.count),@"mps_public_protocol_gate":@(mpsGate),
  @"device_spi_present":@(spi!=nil),@"failure_count":@(failures.count),@"failures":failures,@"classes":rows,@"typed_bindings":typed,
  @"gpu_executed":@NO,@"original_mps_executed":@NO};
 [[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil] writeToFile:@(argv[4]) atomically:YES];
 printf("PROTOCOL_RESULT roots=%lu class_missing=%u instance_missing=%u methods=%u failures=%lu mps_gate=%d\n",(unsigned long)classes.count,missingClass,missingInstance,methodChecks,(unsigned long)failures.count,mpsGate);
 for(NSString *failure in failures)fprintf(stderr,"%s\n",failure.UTF8String);
 return failures.count?2:0;
}}
