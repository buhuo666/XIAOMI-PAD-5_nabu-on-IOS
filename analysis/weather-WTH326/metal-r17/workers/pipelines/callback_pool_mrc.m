// A valid non-ARC consumer callback creates an autoreleased temporary owner.
// The callback returns void: no autoreleased-return optimization applies.
#import <Foundation/Foundation.h>
@interface NabuPoolTemporary : NSObject { id held; }
- (instancetype)initWithObject:(id)object;
@end
@implementation NabuPoolTemporary
- (instancetype)initWithObject:(id)object {
 if((self=[super init]))held=[object retain];return self;
}
- (void)dealloc {[held release];[super dealloc];}
@end
void nabu_test_autoreleased_owner(id object) {
 NabuPoolTemporary *owner=[[NabuPoolTemporary alloc] initWithObject:object];
 [owner autorelease];
}
