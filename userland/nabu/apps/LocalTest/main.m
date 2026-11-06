#import <UIKit/UIKit.h>

@interface LocalTestController : UIViewController
@property(nonatomic, strong) NSURL *stateURL;
@property(nonatomic, strong) UILabel *countsLabel;
@property(nonatomic, strong) UILabel *statusLabel;
@property(nonatomic, strong) UIButton *saveButton;
@property(nonatomic) unsigned long long launches;
@property(nonatomic) unsigned long long saves;
@end

@implementation LocalTestController
- (void)updateCounts {
    self.countsLabel.text = [NSString stringWithFormat:
        @"持久启动次数：%llu\n按钮保存次数：%llu", self.launches, self.saves];
}

- (BOOL)saveLaunches:(unsigned long long)launches saves:(unsigned long long)saves {
    NSError *error = nil;
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:
        @{@"LaunchCount": @(launches), @"SaveCount": @(saves)}
        format:NSPropertyListBinaryFormat_v1_0 options:0 error:&error];
    if (!data || ![data writeToURL:self.stateURL options:NSDataWritingAtomic error:&error]) {
        self.statusLabel.text = [NSString stringWithFormat:@"保存失败：%@", error.localizedDescription];
        return NO;
    }
    self.launches = launches;
    self.saves = saves;
    [self updateCounts];
    self.statusLabel.text = @"已保存到 Documents/counts.plist";
    return YES;
}

- (void)saveTapped {
    [self saveLaunches:self.launches saves:self.saves + 1];
}

- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.systemBackgroundColor;

    UILabel *title = [UILabel new];
    title.text = @"Nabu本地应用测试";
    title.font = [UIFont preferredFontForTextStyle:UIFontTextStyleLargeTitle];
    title.adjustsFontForContentSizeCategory = YES;
    title.numberOfLines = 0;
    title.textAlignment = NSTextAlignmentCenter;

    self.countsLabel = [UILabel new];
    self.countsLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleTitle2];
    self.countsLabel.adjustsFontForContentSizeCategory = YES;
    self.countsLabel.numberOfLines = 0;
    self.countsLabel.textAlignment = NSTextAlignmentCenter;

    self.statusLabel = [UILabel new];
    self.statusLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    self.statusLabel.adjustsFontForContentSizeCategory = YES;
    self.statusLabel.numberOfLines = 0;
    self.statusLabel.textAlignment = NSTextAlignmentCenter;
    self.statusLabel.textColor = UIColor.secondaryLabelColor;

    self.saveButton = [UIButton buttonWithType:UIButtonTypeSystem];
    [self.saveButton setTitle:@"累加并保存" forState:UIControlStateNormal];
    self.saveButton.titleLabel.font = [UIFont preferredFontForTextStyle:UIFontTextStyleTitle2];
    [self.saveButton addTarget:self action:@selector(saveTapped) forControlEvents:UIControlEventTouchUpInside];

    UILabel *hint = [UILabel new];
    hint.text = @"退出应用后重新打开，或重启设备后再次打开，核对计数是否保留。\n此应用不使用网络。";
    hint.font = [UIFont preferredFontForTextStyle:UIFontTextStyleBody];
    hint.adjustsFontForContentSizeCategory = YES;
    hint.numberOfLines = 0;
    hint.textAlignment = NSTextAlignmentCenter;

    UIStackView *stack = [[UIStackView alloc] initWithArrangedSubviews:
        @[title, self.countsLabel, self.saveButton, self.statusLabel, hint]];
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 24;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:stack];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [stack.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor],
        [stack.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [stack.leadingAnchor constraintGreaterThanOrEqualToAnchor:safe.leadingAnchor constant:24],
        [stack.trailingAnchor constraintLessThanOrEqualToAnchor:safe.trailingAnchor constant:-24],
        [stack.widthAnchor constraintLessThanOrEqualToConstant:600],
        [self.saveButton.heightAnchor constraintGreaterThanOrEqualToConstant:48]
    ]];

    NSFileManager *files = [NSFileManager defaultManager];
    NSURL *documents = [files URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    self.stateURL = [documents URLByAppendingPathComponent:@"counts.plist"];
    NSError *error = nil;
    if (![files createDirectoryAtURL:documents withIntermediateDirectories:YES attributes:nil error:&error]) {
        self.statusLabel.text = [NSString stringWithFormat:@"无法创建 Documents：%@", error.localizedDescription];
        self.saveButton.enabled = NO;
        return;
    }
    NSData *data = [NSData dataWithContentsOfURL:self.stateURL options:0 error:&error];
    if (data) {
        NSDictionary *counts = [NSPropertyListSerialization propertyListWithData:data
            options:NSPropertyListImmutable format:NULL error:&error];
        if (![counts isKindOfClass:[NSDictionary class]]) {
            self.statusLabel.text = @"无法读取已保存的计数。";
            self.saveButton.enabled = NO;
            return;
        }
        self.launches = [counts[@"LaunchCount"] unsignedLongLongValue];
        self.saves = [counts[@"SaveCount"] unsignedLongLongValue];
    } else if (![error.domain isEqualToString:NSCocoaErrorDomain] || error.code != NSFileReadNoSuchFileError) {
        self.statusLabel.text = [NSString stringWithFormat:@"读取失败：%@", error.localizedDescription];
        self.saveButton.enabled = NO;
        return;
    }
    [self updateCounts];
    if (![self saveLaunches:self.launches + 1 saves:self.saves]) self.saveButton.enabled = NO;
}
@end

@interface LocalTestAppDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end

@implementation LocalTestAppDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application;
    (void)options;
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [LocalTestController new];
    [self.window makeKeyAndVisible];
    return YES;
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass([LocalTestAppDelegate class]));
    }
}
